#!/usr/bin/env python3
"""No-send min-price research for simple_gap_trader.

Purpose:
- Do NOT modify live MIN_PRICE or send broker orders.
- Compare historical min-price thresholds.
- Collect intraday live snapshots with current warning filters.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
import sqlite3
import statistics
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from toss_auto_trader.config import Settings
from toss_auto_trader.toss_client import TossInvestClient

DEFAULT_DB_PATH = ROOT / "data/edge_research_universe_15y.sqlite3"
DEFAULT_HISTORICAL_OUT = ROOT / "data/simple_gap_min_price_historical_latest.json"
DEFAULT_SNAPSHOT_JSONL = ROOT / f"data/simple_gap_min_price_live_{datetime.now().strftime('%Y-%m-%d')}.jsonl"
ROUND_TRIP_COST_DEFAULT = 0.0035


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


SG = load_module("simple_gap_trader", ROOT / "scripts/simple_gap_trader.py")
AUDIT = load_module("simple_gap_strategy_audit", ROOT / "scripts/simple_gap_strategy_audit.py")


def pct(value: Any, digits: int = 2) -> str:
    if value is None:
        return "N/A"
    try:
        f = float(value)
    except Exception:
        return "N/A"
    if math.isnan(f):
        return "N/A"
    return f"{f * 100:+.{digits}f}%"


def money(value: Any) -> str:
    if value is None:
        return "N/A"
    try:
        return f"{float(value):,.0f}원"
    except Exception:
        return str(value)


def parse_csv_floats(raw: str) -> list[float]:
    return [float(x.strip()) for x in raw.split(",") if x.strip()]


def parse_csv_ints(raw: str) -> list[int]:
    return [int(float(x.strip())) for x in raw.split(",") if x.strip()]


def load_base_stocks(db_path: Path, *, min_price: float, max_price: float) -> tuple[str, list[dict[str, Any]]]:
    con = sqlite3.connect(f"file:{db_path.resolve()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        latest_date = con.execute("SELECT max(substr(timestamp,1,10)) FROM candle_cache WHERE interval='1d'").fetchone()[0]
        rows = con.execute(
            """
            WITH prev AS (
              SELECT symbol,
                     substr(timestamp,1,10) AS date,
                     CAST(open_price AS REAL) AS open_price,
                     CAST(close_price AS REAL) AS close_price,
                     CAST(volume AS REAL) AS volume,
                     AVG(CAST(volume AS REAL)) OVER (
                       PARTITION BY symbol ORDER BY timestamp ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING
                     ) AS avg20_volume,
                     COUNT(CAST(volume AS REAL)) OVER (
                       PARTITION BY symbol ORDER BY timestamp ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING
                     ) AS prev_count
              FROM candle_cache
              WHERE interval='1d'
            )
            SELECT symbol, close_price AS prev_close, volume AS prev_vol, avg20_volume AS avg_vol
            FROM prev
            WHERE date = ?
              AND close_price >= ?
              AND close_price <= ?
              AND avg20_volume > 0
              AND prev_count >= 20
            """,
            (latest_date, min_price, max_price),
        ).fetchall()
    finally:
        con.close()
    return str(latest_date), [dict(r) for r in rows]


def current_kosdaq_gate() -> dict[str, Any]:
    try:
        closes = SG.fetch_kosdaq_index()
        if len(closes) < 5:
            return {"ok": True, "available": False, "reason": "index_rows_lt_5"}
        current = float(closes[-1])
        sma5 = statistics.mean(float(x) for x in closes[-5:])
        return {"ok": current >= sma5, "available": True, "current": current, "sma5": sma5}
    except Exception as exc:
        return {"ok": False, "available": False, "reason": f"{type(exc).__name__}: {exc}"}


def live_candidates_for_min_price(
    client: TossInvestClient,
    *,
    db_path: Path,
    min_price: float,
    max_price: float,
    gap_threshold: float,
    prev_vol_ratio_max: float,
    chunk_size: int = 100,
) -> tuple[str, list[dict[str, Any]]]:
    latest_date, base = load_base_stocks(db_path, min_price=min_price, max_price=max_price)
    base_map = {r["symbol"]: r for r in base}
    symbols = list(base_map)
    candidates: list[dict[str, Any]] = []
    for i in range(0, len(symbols), chunk_size):
        chunk = symbols[i : i + chunk_size]
        try:
            prices = client.get_prices(chunk).get("result", []) or []
        except Exception:
            continue
        for p in prices:
            sym = str(p.get("symbol") or "")
            if sym not in base_map:
                continue
            last_price = float(str(p.get("lastPrice", 0) or 0).replace(",", ""))
            if last_price <= 0:
                continue
            b = base_map[sym]
            prev_close = float(b["prev_close"])
            if prev_close <= 0:
                continue
            avg_vol = float(b["avg_vol"])
            if avg_vol <= 0:
                continue
            prev_vol_ratio = float(b["prev_vol"]) / avg_vol
            if prev_vol_ratio >= prev_vol_ratio_max:
                continue
            provisional_gap = (last_price - prev_close) / prev_close
            if provisional_gap > gap_threshold:
                continue
            open_price = SG.get_today_open_price(client, sym)
            if open_price is None:
                continue
            gap_return = (open_price - prev_close) / prev_close
            if gap_return <= gap_threshold:
                candidates.append(
                    {
                        "symbol": sym,
                        "name": p.get("name") or sym,
                        "open_price": open_price,
                        "last_price": last_price,
                        "prev_close": prev_close,
                        "gap_return": gap_return,
                        "prev_vol_ratio": prev_vol_ratio,
                    }
                )
        time.sleep(0.2)
    candidates.sort(key=lambda x: (float(x["gap_return"]), str(x["symbol"])))
    return latest_date, candidates


def select_live_candidate(
    candidates: list[dict[str, Any]],
    *,
    capital: float,
    warning_lookup: Callable[[str], list[str]],
) -> tuple[dict[str, Any] | None, list[dict[str, Any]], int]:
    warning_exclusions: list[dict[str, Any]] = []
    skipped_unaffordable = 0
    for c in candidates:
        open_price = float(c["open_price"])
        if open_price > capital:
            skipped_unaffordable += 1
            continue
        warnings = warning_lookup(str(c["symbol"]))
        if warnings:
            row = dict(c)
            row["warnings"] = warnings
            warning_exclusions.append(row)
            continue
        pick = dict(c)
        pick["limit_price"] = int(open_price)  # same entry basis as backtest
        pick["quantity"] = int(capital // int(open_price))
        pick["notional_krw"] = pick["quantity"] * pick["limit_price"]
        return pick, warning_exclusions, skipped_unaffordable
    return None, warning_exclusions, skipped_unaffordable


def warning_lookup_with_cache(client: TossInvestClient):
    cache: dict[str, list[str]] = {}

    def lookup(symbol: str) -> list[str]:
        if symbol not in cache:
            cache[symbol] = SG.blocking_warnings_for_symbol(client, symbol)
            time.sleep(0.15)
        return cache[symbol]

    return lookup


def run_snapshot(args) -> dict[str, Any]:
    settings = Settings.from_env()
    client = TossInvestClient(settings)
    gate = current_kosdaq_gate()
    lookup = warning_lookup_with_cache(client)
    min_prices = parse_csv_ints(args.min_prices)
    rows = []
    for min_price in min_prices:
        latest_date, candidates = live_candidates_for_min_price(
            client,
            db_path=Path(args.db_path),
            min_price=min_price,
            max_price=args.max_price,
            gap_threshold=args.gap_threshold,
            prev_vol_ratio_max=args.prev_vol_ratio_max,
        )
        selected, warning_exclusions, skipped_unaffordable = select_live_candidate(candidates, capital=args.capital, warning_lookup=lookup)
        rows.append(
            {
                "min_price": min_price,
                "latest_db_date": latest_date,
                "candidate_count": len(candidates),
                "skipped_unaffordable_before_warning": skipped_unaffordable,
                "selected": selected,
                "warning_exclusions": warning_exclusions[:10],
                "top_candidates": candidates[:10],
            }
        )
    record = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "mode": "live_no_send_min_price_snapshot",
        "no_send": True,
        "live_min_price_unchanged": getattr(SG, "MIN_PRICE", None),
        "capital_krw": args.capital,
        "gap_threshold": args.gap_threshold,
        "prev_vol_ratio_max": args.prev_vol_ratio_max,
        "max_price": args.max_price,
        "kosdaq_gate": gate,
        "rows": rows,
    }
    out = Path(args.snapshot_out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    return record


def run_historical(args) -> dict[str, Any]:
    min_prices = parse_csv_ints(args.min_prices)
    result: dict[str, Any] = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "mode": "historical_min_price_sensitivity_no_send",
        "live_min_price_unchanged": getattr(SG, "MIN_PRICE", None),
        "capital_krw": args.capital,
        "min_prices": min_prices,
        "caveats": [
            "Historical database does not include historical 투자주의/경고/VI flags, so warning filters cannot be fully replayed historically.",
            "Use this for price-threshold sensitivity only; today's live snapshots apply current warning filters.",
            "Entry is signal-day open_price and exit is signal-day close_price, matching the current LIMIT-open assumption.",
        ],
        "rows": [],
    }
    for min_price in min_prices:
        ns = SimpleNamespace(
            db_path=args.db_path,
            out=str(Path(args.historical_out).with_name(f"simple_gap_min_price_{min_price}.json")),
            start=args.start,
            end=args.end,
            min_price=float(min_price),
            max_price=float(args.max_price),
            gap_threshold=float(args.gap_threshold),
            prev_vol_ratio_max=float(args.prev_vol_ratio_max),
            roundtrip_cost=float(args.roundtrip_cost),
            capitals=[float(args.capital)],
            sensitivity_gaps=[-0.02, -0.03, -0.04, -0.05],
            sensitivity_vol_ratios=[0.5, 0.75, 1.0, 1.25],
        )
        rep = AUDIT.run(ns)
        cap_key = str(int(args.capital))
        item = rep["daily_top_by_capital"][cap_key]
        result["rows"].append(
            {
                "min_price": min_price,
                "summary": item["summary"],
                "skipped_signal_days_no_affordable_share": item["skipped_signal_days_no_affordable_share"],
                "invested_return_summary": item["invested_return_summary"],
                "kosdaq_index_guard": rep.get("kosdaq_index_guard"),
            }
        )
    out = Path(args.historical_out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return result


def format_historical(report: dict[str, Any]) -> str:
    lines = [
        "[simple_gap MIN_PRICE historical sensitivity]",
        f"- generated: {report.get('generated_at')}",
        f"- capital: {money(report.get('capital_krw'))}",
        f"- live MIN_PRICE unchanged: {money(report.get('live_min_price_unchanged'))}",
        "",
        "| min_price | trades | avg cap net | median | win | PF | avg cash used | skipped |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for r in report.get("rows", []):
        s = r["summary"]
        pf = s.get("profit_factor_net_pnl")
        lines.append(
            f"| {int(r['min_price']):,} | {s['trades']} | {pct(s.get('avg_net_return_on_capital'))} | {pct(s.get('median_net_return_on_capital'))} | "
            f"{pct(s.get('win_rate_net'))} | {pf if pf is not None else 'N/A'} | {pct(s.get('avg_cash_used_pct'))} | {r.get('skipped_signal_days_no_affordable_share')} |"
        )
    lines += ["", "Caveat: historical warning filters are unavailable; live snapshots apply current warning filters."]
    return "\n".join(lines)


def format_snapshot(record: dict[str, Any]) -> str:
    lines = [
        f"[simple_gap MIN_PRICE no-send snapshot] {record.get('generated_at')}",
        f"- capital: {money(record.get('capital_krw'))} / live MIN_PRICE unchanged: {money(record.get('live_min_price_unchanged'))}",
        f"- KOSDAQ gate: {record.get('kosdaq_gate')}",
        "| min_price | candidates | selected | price | warnings skipped | unaffordable skipped |",
        "|---:|---:|---|---:|---:|---:|",
    ]
    for row in record.get("rows", []):
        sel = row.get("selected") or {}
        selected = f"{sel.get('name')}({sel.get('symbol')})" if sel else "없음"
        lines.append(
            f"| {int(row['min_price']):,} | {row['candidate_count']} | {selected} | {money(sel.get('limit_price')) if sel else 'N/A'} | "
            f"{len(row.get('warning_exclusions') or [])} | {row.get('skipped_unaffordable_before_warning')} |"
        )
    return "\n".join(lines)


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def daily_open_close_for_date(db_path: Path, symbol: str, date: str) -> tuple[float, float] | None:
    con = sqlite3.connect(f"file:{db_path.resolve()}?mode=ro", uri=True)
    try:
        row = con.execute(
            """
            SELECT open_price, close_price FROM candle_cache
            WHERE symbol=? AND interval='1d' AND substr(timestamp,1,10)=?
            """,
            (symbol, date),
        ).fetchone()
        if not row:
            return None
        return float(row[0]), float(row[1])
    finally:
        con.close()


def snapshot_outcomes(snapshots: list[dict[str, Any]], *, db_path: Path, roundtrip_cost: float) -> dict[int, list[dict[str, Any]]]:
    out: dict[int, list[dict[str, Any]]] = defaultdict(list)
    daily_cache: dict[tuple[str, str], tuple[float, float] | None] = {}
    for snap in snapshots:
        date = str(snap.get("generated_at", ""))[:10]
        capital = float(snap.get("capital_krw") or 0)
        if not date or capital <= 0:
            continue
        for row in snap.get("rows", []):
            sel = row.get("selected") or {}
            symbol = str(sel.get("symbol") or "")
            if not symbol:
                continue
            entry = float(sel.get("limit_price") or sel.get("open_price") or 0)
            qty = int(sel.get("quantity") or 0)
            if entry <= 0 or qty <= 0:
                continue
            key = (symbol, date)
            if key not in daily_cache:
                daily_cache[key] = daily_open_close_for_date(db_path, symbol, date)
            daily = daily_cache[key]
            if daily is None:
                continue
            db_open, close = daily
            gross_pnl = (close - entry) * qty
            cash_used = entry * qty
            net_pnl = gross_pnl - (cash_used * roundtrip_cost)
            out[int(row["min_price"])].append(
                {
                    "symbol": symbol,
                    "name": sel.get("name") or symbol,
                    "date": date,
                    "entry": entry,
                    "db_open": db_open,
                    "entry_matches_daily_open": abs(entry - db_open) < 0.5,
                    "close": close,
                    "quantity": qty,
                    "net_return_on_capital": net_pnl / capital,
                    "gross_return_on_entry": (close / entry) - 1.0,
                    "cash_used_pct": cash_used / capital,
                }
            )
    return out


def format_outcomes(outcomes: dict[int, list[dict[str, Any]]]) -> list[str]:
    lines = ["## Same-day open→close outcome by threshold"]
    if not outcomes:
        lines.append("- outcome unavailable: no matching close rows yet")
        return lines
    lines.append("| min_price | samples | avg net cap | median | win | avg cash used | latest |")
    lines.append("|---:|---:|---:|---:|---:|---:|---|")
    mismatch_count = 0
    for mp in sorted(outcomes):
        rows = outcomes[mp]
        mismatch_count += sum(1 for r in rows if r.get("entry_matches_daily_open") is False)
        rets = [float(r["net_return_on_capital"]) for r in rows]
        wins = [r for r in rows if float(r["net_return_on_capital"]) > 0]
        cash = [float(r["cash_used_pct"]) for r in rows]
        latest = rows[-1]
        mismatch_tag = " ⚠ entry≠DB-open" if latest.get("entry_matches_daily_open") is False else ""
        latest_text = f"{latest['name']}({latest['symbol']}): {money(latest['entry'])}→{money(latest['close'])}, {pct(latest['net_return_on_capital'])}{mismatch_tag}"
        lines.append(
            f"| {mp:,} | {len(rows)} | {pct(statistics.mean(rets))} | {pct(statistics.median(rets))} | "
            f"{pct(len(wins) / len(rows))} | {pct(statistics.mean(cash))} | {latest_text} |"
        )
    if mismatch_count:
        lines.append(f"- Note: {mismatch_count} snapshot outcomes used recorded entry prices that differed from the final daily open; future snapshots use daily-candle open only.")
    return lines


def run_final(args) -> str:
    snapshots = load_jsonl(Path(args.snapshot_out))
    hist = json.loads(Path(args.historical_out).read_text(encoding="utf-8")) if Path(args.historical_out).exists() else None
    lines = [
        f"[simple_gap MIN_PRICE day review] {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"- no-send snapshots: {len(snapshots)}",
        f"- live MIN_PRICE changed?: {'NO' if snapshots and snapshots[-1].get('live_min_price_unchanged') == 5000 else 'CHECK'}",
        "",
    ]
    if hist:
        lines.append(format_historical(hist))
        lines.append("")
    if snapshots:
        by_min: dict[int, Counter] = defaultdict(Counter)
        selected_prices: dict[int, list[tuple[str, float]]] = defaultdict(list)
        warning_counts: Counter[str] = Counter()
        for snap in snapshots:
            for row in snap.get("rows", []):
                mp = int(row["min_price"])
                sel = row.get("selected") or {}
                symbol = str(sel.get("symbol") or "NO_PICK")
                by_min[mp][symbol] += 1
                if symbol != "NO_PICK":
                    price = float(sel.get("limit_price") or sel.get("open_price") or 0)
                    if price > 0:
                        selected_prices[mp].append((symbol, price))
                for ex in row.get("warning_exclusions") or []:
                    for w in ex.get("warnings") or []:
                        warning_counts[w] += 1
        lines.append("## Intraday selected-symbol frequency")
        for mp in sorted(by_min):
            top = ", ".join(f"{sym}:{cnt}" for sym, cnt in by_min[mp].most_common(5))
            lines.append(f"- min {mp:,}: {top}")
        lines.append("## Low-price concentration check")
        for mp in sorted(by_min):
            total = sum(by_min[mp].values())
            top_symbol, top_count = by_min[mp].most_common(1)[0]
            non_no_pick = [(sym, price) for sym, price in selected_prices.get(mp, []) if sym != "NO_PICK"]
            low_price_count = sum(1 for _, price in non_no_pick if price < 2000)
            avg_selected_price = statistics.mean([price for _, price in non_no_pick]) if non_no_pick else None
            flags = []
            if total and top_symbol != "NO_PICK" and top_count / total >= 0.8:
                flags.append("단일종목쏠림")
            if non_no_pick and low_price_count / len(non_no_pick) >= 0.8:
                flags.append("2천원미만편향")
            flag_text = f" / ⚠ {', '.join(flags)}" if flags else ""
            lines.append(
                f"- min {mp:,}: top={top_symbol} {top_count}/{total}({top_count / total:.0%}), "
                f"avg_selected_price={money(avg_selected_price) if avg_selected_price is not None else 'N/A'}, "
                f"under_2k={low_price_count}/{len(non_no_pick)}{flag_text}"
            )
        if warning_counts:
            lines.append("## Warning-filter hits")
            lines.append(", ".join(f"{k}:{v}" for k, v in warning_counts.most_common(10)))
        lines.append("")
        outcomes = snapshot_outcomes(snapshots, db_path=Path(args.db_path), roundtrip_cost=float(args.roundtrip_cost))
        lines.extend(format_outcomes(outcomes))
        lines.append("")
        lines.append("## Latest snapshot")
        lines.append(format_snapshot(snapshots[-1]))
    else:
        lines.append("No snapshots collected yet.")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="No-send min-price sensitivity research for simple_gap_trader")
    ap.add_argument("--mode", choices=["historical", "snapshot", "final"], required=True)
    ap.add_argument("--db-path", default=str(DEFAULT_DB_PATH))
    ap.add_argument("--historical-out", default=str(DEFAULT_HISTORICAL_OUT))
    ap.add_argument("--snapshot-out", default=str(DEFAULT_SNAPSHOT_JSONL))
    ap.add_argument("--min-prices", default="1000,2000,3000,5000")
    ap.add_argument("--max-price", type=float, default=50000)
    ap.add_argument("--capital", type=float, default=10000)
    ap.add_argument("--gap-threshold", type=float, default=-0.03)
    ap.add_argument("--prev-vol-ratio-max", type=float, default=1.0)
    ap.add_argument("--roundtrip-cost", type=float, default=ROUND_TRIP_COST_DEFAULT)
    ap.add_argument("--start", default="2016-01-01")
    ap.add_argument("--end", default="")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    if args.mode == "historical":
        report = run_historical(args)
        if not args.quiet:
            print(format_historical(report))
    elif args.mode == "snapshot":
        record = run_snapshot(args)
        if not args.quiet:
            print(format_snapshot(record))
    elif args.mode == "final":
        print(run_final(args))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
