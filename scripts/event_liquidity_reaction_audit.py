#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sqlite3
from bisect import bisect_right
from collections import Counter
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from statistics import mean, median
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")
HYPOTHESIS_ID = "EVENT_LIQUIDITY_REACTION_H3_V1"
MODE = "research_only_no_send_event_liquidity_reaction_audit"

POSITIVE_KEYWORDS = [
    "공급계약",
    "수주",
    "계약 체결",
    "호실적",
    "실적 개선",
    "흑자전환",
    "영업이익 증가",
    "매출 증가",
    "최대 실적",
    "승인",
    "품목허가",
    "FDA",
    "CE 인증",
    "자사주",
    "배당",
    "무상증자",
    "M&A",
    "인수",
    "투자 유치",
    "특허",
    "국책과제",
    "신규 공급",
    "확대",
]

NEGATIVE_KEYWORDS = [
    "적자",
    "손실",
    "실적 부진",
    "하락",
    "급락",
    "리스크",
    "소송",
    "감자",
    "유상증자",
    "불성실공시",
    "관리종목",
    "상장폐지",
    "거래정지",
    "압수수색",
    "제재",
    "노조 리스크",
]


def norm_date(ts: str) -> str:
    return str(ts)[:10]


def safe_float(value) -> float | None:
    try:
        if value is None or value == "":
            return None
        v = float(value)
        if math.isnan(v) or math.isinf(v):
            return None
        return v
    except Exception:
        return None


def pct(a: float, b: float) -> float:
    return (b - a) / a if a and a > 0 else 0.0


def summarize(vals: list[float]) -> dict:
    if not vals:
        return {"n": 0, "avg": None, "median": None, "win_rate": None}
    return {
        "n": len(vals),
        "avg": mean(vals),
        "median": median(vals),
        "win_rate": sum(1 for v in vals if v > 0) / len(vals),
    }


def parse_published_date(value: str | None) -> str | None:
    if not value:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    if re.fullmatch(r"\d+(\.\d+)?", raw):
        ts = float(raw)
        if ts > 10_000_000_000:
            ts = ts / 1000.0
        try:
            return datetime.fromtimestamp(ts, tz=timezone.utc).astimezone(KST).date().isoformat()
        except Exception:
            return None
    if re.match(r"^\d{4}-\d{2}-\d{2}", raw):
        try:
            text = raw.replace("Z", "+00:00")
            dt = datetime.fromisoformat(text)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=KST)
            return dt.astimezone(KST).date().isoformat()
        except Exception:
            return raw[:10]
    try:
        dt = parsedate_to_datetime(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=KST)
        return dt.astimezone(KST).date().isoformat()
    except Exception:
        return None


def catalyst_score(title: str, summary: str | None = None, sentiment: float | None = None) -> dict:
    text = f"{title or ''} {summary or ''}"
    lowered = text.lower()
    pos_hits = [kw for kw in POSITIVE_KEYWORDS if kw.lower() in lowered]
    neg_hits = [kw for kw in NEGATIVE_KEYWORDS if kw.lower() in lowered]
    score = len(pos_hits) - len(neg_hits)
    if sentiment is not None:
        if sentiment >= 0.15:
            score += 1
        elif sentiment <= -0.15:
            score -= 1
    return {
        "score": score,
        "positive_keywords": pos_hits,
        "negative_keywords": neg_hits,
    }


def allowed_market_set(raw: str | None) -> set[str]:
    return {x.strip().upper() for x in str(raw or "").split(",") if x.strip()}


def load_symbol_map(path: str, allowed_markets: set[str] | None = None) -> tuple[dict[str, dict], Counter]:
    skipped: Counter = Counter()
    p = Path(path)
    if not p.exists():
        skipped["symbol_map_missing"] += 1
        return {}, skipped
    with p.open(newline="") as f:
        rows = list(csv.DictReader(f))
    out = {}
    for row in rows:
        query = (row.get("query") or "").strip()
        symbol = (row.get("symbol") or "").strip()
        market = (row.get("market") or "").strip().upper()
        if not query or not symbol:
            skipped["symbol_map_bad_row"] += 1
            continue
        if allowed_markets and market and market not in allowed_markets:
            skipped["symbol_map_market_excluded"] += 1
            continue
        out[query] = dict(row)
    return out, skipped


def table_exists(con: sqlite3.Connection, name: str) -> bool:
    row = con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone()
    return row is not None


def load_news_events(news_db: str, symbol_map: dict[str, dict], *, limit: int = 0) -> tuple[list[dict], Counter, int]:
    skipped: Counter = Counter()
    p = Path(news_db)
    if not p.exists():
        skipped["news_db_missing"] += 1
        return [], skipped, 0
    events: list[dict] = []
    seen = set()
    con = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        if not table_exists(con, "news_context"):
            skipped["news_context_table_missing"] += 1
            return [], skipped, 0
        sql = """
            SELECT provider, query, title, url, source, published_at, sentiment, summary, created_at
            FROM news_context
            ORDER BY created_at ASC, id ASC
        """
        rows = con.execute(sql).fetchall()
        source_rows = len(rows)
        for r in rows:
            query = str(r["query"] or "").strip()
            mapping = symbol_map.get(query)
            if not mapping:
                skipped["query_unmapped"] += 1
                continue
            event_date = parse_published_date(r["published_at"]) or parse_published_date(r["created_at"])
            if not event_date:
                skipped["published_date_unparsed"] += 1
                continue
            sentiment = safe_float(r["sentiment"])
            score = catalyst_score(r["title"], r["summary"], sentiment)
            key = (mapping["symbol"], event_date, r["provider"], r["title"], r["url"])
            if key in seen:
                skipped["cross_query_duplicate_news_event"] += 1
                continue
            seen.add(key)
            events.append({
                "provider": r["provider"],
                "query": query,
                "symbol": mapping["symbol"],
                "name": mapping.get("name") or query,
                "event_date": event_date,
                "title": r["title"],
                "url": r["url"],
                "source": r["source"],
                "published_at": r["published_at"],
                "summary": r["summary"],
                "sentiment": sentiment,
                "catalyst_score": score["score"],
                "positive_keywords": score["positive_keywords"],
                "negative_keywords": score["negative_keywords"],
            })
            if limit and len(events) >= limit:
                break
        return events, skipped, source_rows
    finally:
        con.close()


def load_candle_map(db_path: str) -> tuple[dict[str, list[dict]], dict[str, list[str]], Counter]:
    skipped: Counter = Counter()
    p = Path(db_path)
    if not p.exists():
        skipped["source_db_missing"] += 1
        return {}, {}, skipped
    by_symbol: dict[str, list[dict]] = {}
    con = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    try:
        if not table_exists(con, "candle_cache"):
            skipped["candle_cache_table_missing"] += 1
            return {}, {}, skipped
        cur = con.execute(
            """
            SELECT symbol, timestamp, open_price, close_price, volume
            FROM candle_cache
            WHERE interval='1d'
            ORDER BY symbol, timestamp
            """
        )
        current_symbol = None
        rows: list[dict] = []
        for sym, ts, open_p, close_p, volume in cur:
            if current_symbol is not None and sym != current_symbol:
                if rows:
                    by_symbol[str(current_symbol)] = rows
                rows = []
            current_symbol = sym
            op = safe_float(open_p)
            cp = safe_float(close_p)
            vol = safe_float(volume)
            if op is None or cp is None or vol is None or op <= 0 or cp <= 0:
                skipped["bad_candle_row"] += 1
                continue
            rows.append({"date": norm_date(ts), "open": op, "close": cp, "volume": vol})
        if current_symbol is not None and rows:
            by_symbol[str(current_symbol)] = rows
    finally:
        con.close()
    dates = {sym: [r["date"] for r in rows] for sym, rows in by_symbol.items()}
    return by_symbol, dates, skipped


def prior_avg(rows: list[dict], idx: int, field: str, window: int) -> float | None:
    start = idx - window
    if start < 0:
        return None
    vals = [float(rows[i][field]) for i in range(start, idx)]
    return mean(vals) if vals else None


def prior_avg_turnover(rows: list[dict], idx: int, window: int) -> float | None:
    start = idx - window
    if start < 0:
        return None
    vals = [float(rows[i]["close"]) * float(rows[i]["volume"]) for i in range(start, idx)]
    return mean(vals) if vals else None


def event_position(dates: list[str], event_date: str) -> int:
    return bisect_right(dates, event_date) - 1


def eligible_baseline(
    by_symbol: dict[str, list[dict]],
    dates_by_symbol: dict[str, list[str]],
    event_date: str,
    *,
    horizon: int,
    lookback: int,
    min_close_price: float,
    min_avg_turnover_20d: float,
    roundtrip_cost_pct: float,
) -> dict:
    vals: list[float] = []
    for sym, rows in by_symbol.items():
        dates = dates_by_symbol[sym]
        pos = event_position(dates, event_date)
        if pos < lookback:
            continue
        entry_idx = pos + 1
        exit_idx = entry_idx + horizon
        if exit_idx >= len(rows):
            continue
        if rows[pos]["close"] < min_close_price:
            continue
        avg_turnover = prior_avg_turnover(rows, pos, 20)
        if avg_turnover is None or avg_turnover < min_avg_turnover_20d:
            continue
        vals.append(pct(rows[entry_idx]["open"], rows[exit_idx]["close"]) - roundtrip_cost_pct)
    stats = summarize(vals)
    stats["eligible_symbols"] = len(vals)
    return stats


def evaluate_events(args, events: list[dict], by_symbol: dict[str, list[dict]], dates_by_symbol: dict[str, list[str]]) -> tuple[list[dict], list[dict], Counter]:
    skipped: Counter = Counter()
    rows_out: list[dict] = []
    pending_rows: list[dict] = []
    baseline_cache: dict[tuple[str, int], dict] = {}
    lookback = int(args.lookback)
    horizon = int(args.horizon)
    min_volume_multiple = float(args.min_volume_multiple)
    min_avg_turnover = float(args.min_avg_turnover_20d)
    min_close_price = float(args.min_close_price)
    roundtrip_cost_pct = float(args.roundtrip_cost_pct)

    for event in sorted(events, key=lambda r: (r["event_date"], r["symbol"], r["title"])):
        symbol = event["symbol"]
        rows = by_symbol.get(symbol)
        if not rows:
            skipped["symbol_candle_missing"] += 1
            continue
        dates = dates_by_symbol[symbol]
        pos = event_position(dates, event["event_date"])
        if pos < lookback:
            skipped["insufficient_prior_history"] += 1
            continue
        entry_idx = pos + 1
        exit_idx = entry_idx + horizon
        if rows[pos]["close"] < min_close_price:
            skipped["close_below_min"] += 1
            continue
        avg_vol = prior_avg(rows, pos, "volume", 20)
        avg_turnover = prior_avg_turnover(rows, pos, 20)
        if avg_vol is None or avg_vol <= 0:
            skipped["avg_volume_unavailable"] += 1
            continue
        if avg_turnover is None or avg_turnover < min_avg_turnover:
            skipped["avg_turnover_below_min"] += 1
            continue
        volume_multiple = rows[pos]["volume"] / avg_vol
        if event["catalyst_score"] <= 0:
            skipped["catalyst_score_not_positive"] += 1
            continue
        if volume_multiple < min_volume_multiple:
            skipped["volume_multiple_below_min"] += 1
            continue
        if entry_idx >= len(rows) or exit_idx >= len(rows):
            skipped["pending_future_horizon"] += 1
            pending_rows.append({
                "hypothesis_id": args.hypothesis_id,
                "paper_only": True,
                "order_sent": False,
                "live_order_allowed": False,
                "status": "event_liquidity_reaction_pending_future_horizon_no_send",
                "symbol": symbol,
                "name": event.get("name"),
                "query": event["query"],
                "provider": event["provider"],
                "source": event.get("source"),
                "event_date": event["event_date"],
                "signal_date": rows[pos]["date"],
                "horizon": horizon,
                "title": event["title"],
                "url": event["url"],
                "catalyst_score": event["catalyst_score"],
                "positive_keywords": ";".join(event.get("positive_keywords") or []),
                "negative_keywords": ";".join(event.get("negative_keywords") or []),
                "event_close": rows[pos]["close"],
                "event_volume": rows[pos]["volume"],
                "avg_volume_20d_prior": avg_vol,
                "volume_multiple": volume_multiple,
                "avg_turnover_20d_prior": avg_turnover,
                "needed_future_bars": max(0, exit_idx - (len(rows) - 1)),
                "available_last_candle_date": rows[-1]["date"],
            })
            continue
        baseline_key = (event["event_date"], horizon)
        if baseline_key not in baseline_cache:
            baseline_cache[baseline_key] = eligible_baseline(
                by_symbol,
                dates_by_symbol,
                event["event_date"],
                horizon=horizon,
                lookback=lookback,
                min_close_price=min_close_price,
                min_avg_turnover_20d=min_avg_turnover,
                roundtrip_cost_pct=roundtrip_cost_pct,
            )
        baseline = baseline_cache[baseline_key]
        if not baseline.get("eligible_symbols"):
            skipped["eligible_baseline_unavailable"] += 1
            continue
        entry = rows[entry_idx]["open"]
        exit_price = rows[exit_idx]["close"]
        ret = pct(entry, exit_price) - roundtrip_cost_pct
        baseline_avg = baseline.get("avg")
        rows_out.append({
            "hypothesis_id": args.hypothesis_id,
            "paper_only": True,
            "order_sent": False,
            "live_order_allowed": False,
            "status": "event_liquidity_reaction_research_only_no_send",
            "symbol": symbol,
            "name": event.get("name"),
            "query": event["query"],
            "provider": event["provider"],
            "source": event.get("source"),
            "event_date": event["event_date"],
            "signal_date": rows[pos]["date"],
            "entry_date": rows[entry_idx]["date"],
            "exit_date": rows[exit_idx]["date"],
            "horizon": horizon,
            "title": event["title"],
            "url": event["url"],
            "catalyst_score": event["catalyst_score"],
            "positive_keywords": ";".join(event.get("positive_keywords") or []),
            "negative_keywords": ";".join(event.get("negative_keywords") or []),
            "event_close": rows[pos]["close"],
            "event_volume": rows[pos]["volume"],
            "avg_volume_20d_prior": avg_vol,
            "volume_multiple": volume_multiple,
            "avg_turnover_20d_prior": avg_turnover,
            "entry_price": entry,
            "exit_price": exit_price,
            "net_return_after_cost": ret,
            "eligible_universe_avg_return_after_cost": baseline_avg,
            "eligible_universe_median_return_after_cost": baseline.get("median"),
            "eligible_universe_win_rate": baseline.get("win_rate"),
            "eligible_universe_symbols": baseline.get("eligible_symbols"),
            "excess_vs_eligible_universe": (ret - baseline_avg) if baseline_avg is not None else None,
        })
    return rows_out, pending_rows, skipped


def split_train_locked(rows: list[dict], train_fraction: float) -> tuple[list[dict], list[dict]]:
    ordered = sorted(rows, key=lambda r: (r["event_date"], r["symbol"], r["title"]))
    if not ordered:
        return [], []
    cut = int(len(ordered) * train_fraction)
    if len(ordered) > 1:
        cut = min(max(cut, 1), len(ordered) - 1)
    return ordered[:cut], ordered[cut:]


def evaluate_rows(rows: list[dict], train_fraction: float) -> dict:
    train, locked = split_train_locked(rows, train_fraction)

    def stats(part: list[dict]) -> dict:
        rets = [float(r["net_return_after_cost"]) for r in part]
        base = [float(r["eligible_universe_avg_return_after_cost"]) for r in part if r.get("eligible_universe_avg_return_after_cost") is not None]
        excess = [float(r["excess_vs_eligible_universe"]) for r in part if r.get("excess_vs_eligible_universe") is not None]
        return {
            "events": len(part),
            "event_symbols": len({r["symbol"] for r in part}),
            "event_return": summarize(rets),
            "eligible_universe_avg_by_event_date": summarize(base),
            "excess_vs_eligible_universe": summarize(excess),
        }

    return {
        "all": stats(rows),
        "train": stats(train),
        "locked_test": stats(locked),
    }


def blocker_list(report: dict, *, min_total_events: int, min_event_symbols: int, min_locked_events: int) -> list[str]:
    blockers = ["future_holdout_required_for_any_promotion"]
    all_stats = report["all"]
    locked = report["locked_test"]
    if all_stats["events"] < min_total_events:
        blockers.append("insufficient_total_event_signals")
    if all_stats["event_symbols"] < min_event_symbols:
        blockers.append("insufficient_event_symbol_breadth")
    if locked["events"] < min_locked_events:
        blockers.append("insufficient_locked_test_event_signals")
    locked_ret = locked["event_return"]
    locked_excess = locked["excess_vs_eligible_universe"]
    if locked_ret["avg"] is None or locked_ret["avg"] <= 0:
        blockers.append("locked_test_avg_not_positive")
    if locked_ret["median"] is None or locked_ret["median"] < 0:
        blockers.append("locked_test_median_negative")
    if locked_ret["win_rate"] is None or locked_ret["win_rate"] <= 0.52:
        blockers.append("locked_test_win_rate_too_low")
    if locked_excess["avg"] is None or locked_excess["avg"] <= 0:
        blockers.append("locked_test_not_above_eligible_universe")
    return blockers


def write_pending_jsonl(path: str, rows: list[dict]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")


def write_rows_csv(path: str, rows: list[dict]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "hypothesis_id",
        "paper_only",
        "order_sent",
        "live_order_allowed",
        "status",
        "symbol",
        "name",
        "query",
        "provider",
        "source",
        "event_date",
        "signal_date",
        "entry_date",
        "exit_date",
        "horizon",
        "title",
        "url",
        "catalyst_score",
        "positive_keywords",
        "negative_keywords",
        "event_close",
        "event_volume",
        "avg_volume_20d_prior",
        "volume_multiple",
        "avg_turnover_20d_prior",
        "entry_price",
        "exit_price",
        "net_return_after_cost",
        "eligible_universe_avg_return_after_cost",
        "eligible_universe_median_return_after_cost",
        "eligible_universe_win_rate",
        "eligible_universe_symbols",
        "excess_vs_eligible_universe",
    ]
    with p.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def run(args) -> dict:
    allowed_markets = allowed_market_set(getattr(args, "allowed_markets", ""))
    symbol_map, symbol_map_skipped = load_symbol_map(args.symbol_map, allowed_markets=allowed_markets or None)
    events, news_skipped, news_source_rows = load_news_events(args.news_db, symbol_map, limit=int(args.news_limit))
    by_symbol, dates_by_symbol, candle_skipped = load_candle_map(args.source_db)
    rows, pending_rows, eval_skipped = evaluate_events(args, events, by_symbol, dates_by_symbol) if events and by_symbol else ([], [], Counter())
    evaluation = evaluate_rows(rows, float(args.train_fraction))
    blockers = blocker_list(
        evaluation,
        min_total_events=int(args.min_total_events),
        min_event_symbols=int(args.min_event_symbols),
        min_locked_events=int(args.min_locked_events),
    )
    if not symbol_map:
        blockers.append("symbol_map_missing_or_empty")
    if news_source_rows == 0:
        blockers.append("no_news_context_source_rows")
    if not events:
        blockers.append("no_mapped_news_events")
    if not rows:
        blockers.append("no_evaluable_event_liquidity_signals")
    skipped = Counter()
    skipped.update(symbol_map_skipped)
    skipped.update(news_skipped)
    skipped.update(candle_skipped)
    skipped.update(eval_skipped)
    report = {
        "mode": MODE,
        "hypothesis_id": args.hypothesis_id,
        "paper_only": True,
        "order_sent": False,
        "live_order_allowed": False,
        "edge_ok_same_history_only": False,
        "data_scope": "recent_cached_news_context_joined_to_cached_daily_candles",
        "source_db": args.source_db,
        "news_db": args.news_db,
        "symbol_map": args.symbol_map,
        "news_source_rows": news_source_rows,
        "mapped_queries": len(symbol_map),
        "allowed_markets": sorted(allowed_markets),
        "mapped_news_events": len(events),
        "evaluable_event_signals": len(rows),
        "pending_future_event_signals": len(pending_rows),
        "unique_event_symbols": len({r["symbol"] for r in rows}),
        "parameters": {
            "horizon": int(args.horizon),
            "lookback": int(args.lookback),
            "roundtrip_cost_pct": float(args.roundtrip_cost_pct),
            "min_volume_multiple": float(args.min_volume_multiple),
            "min_avg_turnover_20d": float(args.min_avg_turnover_20d),
            "min_close_price": float(args.min_close_price),
            "train_fraction": float(args.train_fraction),
        },
        "evaluation": evaluation,
        "blockers": sorted(set(blockers)),
        "skipped": dict(skipped),
        "sample_events": events[:5],
        "sample_signals": rows[:5],
        "sample_pending_events": pending_rows[:5],
    }
    if args.rows_out:
        write_rows_csv(args.rows_out, rows)
        report["rows_out"] = args.rows_out
    pending_out = getattr(args, "pending_out", "")
    if pending_out:
        write_pending_jsonl(pending_out, pending_rows)
        report["pending_out"] = pending_out
    return report


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Research-only event/news catalyst + liquidity reaction audit. Never sends orders.")
    ap.add_argument("--source-db", default="data/edge_research_universe_long.sqlite3")
    ap.add_argument("--news-db", default="data/news_context_latest.sqlite3")
    ap.add_argument("--symbol-map", default="research/news_event_symbol_map.csv")
    ap.add_argument("--out", default="data/event_liquidity_reaction_latest.json")
    ap.add_argument("--rows-out", default="data/event_liquidity_reaction_rows.csv")
    ap.add_argument("--pending-out", default="data/event_liquidity_reaction_pending.jsonl")
    ap.add_argument("--allowed-markets", default="")
    ap.add_argument("--hypothesis-id", default=HYPOTHESIS_ID)
    ap.add_argument("--horizon", type=int, default=3)
    ap.add_argument("--lookback", type=int, default=20)
    ap.add_argument("--roundtrip-cost-pct", default="0.0046")
    ap.add_argument("--min-volume-multiple", default="1.5")
    ap.add_argument("--min-avg-turnover-20d", default="50000000")
    ap.add_argument("--min-close-price", default="1000")
    ap.add_argument("--train-fraction", default="0.7")
    ap.add_argument("--min-total-events", type=int, default=100)
    ap.add_argument("--min-event-symbols", type=int, default=30)
    ap.add_argument("--min-locked-events", type=int, default=30)
    ap.add_argument("--news-limit", type=int, default=0)
    return ap


def main() -> int:
    args = build_parser().parse_args()
    report = run(args)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
