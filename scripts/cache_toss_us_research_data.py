#!/usr/bin/env python3
"""Build a read-only Toss US daily-candle research dataset.

The universe is intentionally practical rather than point-in-time complete: it
is the union of current Toss US market trading-amount and trading-volume ranks
across several durations, filtered to active common stocks. That makes the
dataset suitable for live-candidate research, but historical results still have
current-universe survivorship/selection bias and must be labelled accordingly.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from toss_auto_trader import db
from toss_auto_trader.config import Settings
from toss_auto_trader.toss_client import TossApiError, TossInvestClient


DEFAULT_DB = "data/us_gap_research.sqlite3"
DEFAULT_UNIVERSE = "data/us_gap_research_universe.json"
DEFAULT_REPORT = "data/us_gap_research_cache_report.json"
RANKING_TYPES = ("MARKET_TRADING_AMOUNT", "MARKET_TRADING_VOLUME")
RANKING_DURATIONS = ("1mo", "3mo", "6mo", "1y")
BENCHMARK_SYMBOLS = ("SPY", "QQQ", "IWM")
ELIGIBLE_MARKETS = {"NYSE", "NASDAQ", "AMEX"}


@dataclass(frozen=True, slots=True)
class CacheSummary:
    rows: int
    min_timestamp: str | None
    max_timestamp: str | None


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def ranking_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    result = payload.get("result") if isinstance(payload, dict) else None
    rows = result.get("rankings") if isinstance(result, dict) else None
    return [row for row in rows or [] if isinstance(row, dict) and str(row.get("symbol") or "").strip()]


def merge_ranking_sources(payloads: Iterable[tuple[str, str, dict[str, Any]]]) -> dict[str, dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for ranking_type, duration, payload in payloads:
        for row in ranking_rows(payload):
            symbol = str(row["symbol"]).upper()
            item = merged.setdefault(symbol, {"symbol": symbol, "sources": [], "best_rank": 10_000})
            source = {
                "type": ranking_type,
                "duration": duration,
                "rank": int(row.get("rank") or 10_000),
            }
            item["sources"].append(source)
            item["best_rank"] = min(int(item["best_rank"]), source["rank"])
    return merged


def eligible_common_stocks(stock_rows: Iterable[dict[str, Any]], ranking_meta: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    eligible: list[dict[str, Any]] = []
    for row in stock_rows:
        symbol = str(row.get("symbol") or "").upper()
        if (
            symbol in ranking_meta
            and row.get("status") == "ACTIVE"
            and row.get("currency") == "USD"
            and row.get("securityType") == "STOCK"
            and row.get("isCommonShare") is True
            and row.get("market") in ELIGIBLE_MARKETS
        ):
            meta = ranking_meta[symbol]
            eligible.append(
                {
                    "symbol": symbol,
                    "name": row.get("name"),
                    "english_name": row.get("englishName"),
                    "market": row.get("market"),
                    "security_type": row.get("securityType"),
                    "list_date": row.get("listDate"),
                    "sources": sorted(meta["sources"], key=lambda item: (item["type"], item["duration"])),
                    "best_rank": int(meta["best_rank"]),
                    "source_count": len(meta["sources"]),
                }
            )
    return sorted(eligible, key=lambda item: (-int(item["source_count"]), int(item["best_rank"]), item["symbol"]))


def cache_summary(db_path: str, symbol: str) -> CacheSummary:
    if not Path(db_path).exists():
        return CacheSummary(0, None, None)
    con = sqlite3.connect(f"file:{Path(db_path).resolve()}?mode=ro", uri=True)
    try:
        row = con.execute(
            """
            SELECT COUNT(*), MIN(timestamp), MAX(timestamp)
            FROM candle_cache
            WHERE symbol=? AND interval='1d'
            """,
            (symbol,),
        ).fetchone()
    except sqlite3.Error:
        return CacheSummary(0, None, None)
    finally:
        con.close()
    return CacheSummary(int(row[0] or 0), row[1], row[2])


def candle_quality(db_path: str, symbols: Iterable[str]) -> dict[str, Any]:
    symbol_list = list(dict.fromkeys(symbols))
    if not symbol_list or not Path(db_path).exists():
        return {"symbols": 0, "rows": 0, "bad_ohlc": 0, "duplicate_dates": 0, "coverage": {}}
    placeholders = ",".join("?" for _ in symbol_list)
    con = sqlite3.connect(f"file:{Path(db_path).resolve()}?mode=ro", uri=True)
    try:
        rows, min_date, max_date = con.execute(
            f"""
            SELECT COUNT(*), MIN(substr(timestamp,1,10)), MAX(substr(timestamp,1,10))
            FROM candle_cache WHERE interval='1d' AND symbol IN ({placeholders})
            """,
            symbol_list,
        ).fetchone()
        bad_ohlc = con.execute(
            f"""
            SELECT COUNT(*) FROM candle_cache
            WHERE interval='1d' AND symbol IN ({placeholders}) AND (
              CAST(open_price AS REAL) <= 0 OR CAST(high_price AS REAL) <= 0 OR
              CAST(low_price AS REAL) <= 0 OR CAST(close_price AS REAL) <= 0 OR
              CAST(high_price AS REAL) < MAX(CAST(open_price AS REAL), CAST(close_price AS REAL)) OR
              CAST(low_price AS REAL) > MIN(CAST(open_price AS REAL), CAST(close_price AS REAL))
            )
            """,
            symbol_list,
        ).fetchone()[0]
        duplicate_dates = con.execute(
            f"""
            SELECT COUNT(*) FROM (
              SELECT symbol, substr(timestamp,1,10), COUNT(*) n
              FROM candle_cache WHERE interval='1d' AND symbol IN ({placeholders})
              GROUP BY symbol, substr(timestamp,1,10) HAVING n > 1
            )
            """,
            symbol_list,
        ).fetchone()[0]
        coverage_rows = con.execute(
            f"""
            SELECT symbol, COUNT(*), MIN(substr(timestamp,1,10)), MAX(substr(timestamp,1,10))
            FROM candle_cache WHERE interval='1d' AND symbol IN ({placeholders})
            GROUP BY symbol ORDER BY symbol
            """,
            symbol_list,
        ).fetchall()
    finally:
        con.close()
    return {
        "symbols": len(coverage_rows),
        "rows": int(rows or 0),
        "min_date": min_date,
        "max_date": max_date,
        "bad_ohlc": int(bad_ohlc or 0),
        "duplicate_dates": int(duplicate_dates or 0),
        "coverage": {
            str(symbol): {"rows": int(count), "min_date": start, "max_date": end}
            for symbol, count, start, end in coverage_rows
        },
    }


def fetch_universe(client: TossInvestClient) -> dict[str, Any]:
    payloads: list[tuple[str, str, dict[str, Any]]] = []
    ranked_at: dict[str, str | None] = {}
    for ranking_type in RANKING_TYPES:
        for duration in RANKING_DURATIONS:
            payload = client.request_json(
                "GET",
                "/api/v1/rankings",
                params={
                    "type": ranking_type,
                    "marketCountry": "US",
                    "duration": duration,
                    "excludeInvestmentCaution": "true",
                    "count": 100,
                },
            )
            payloads.append((ranking_type, duration, payload))
            result = payload.get("result") if isinstance(payload, dict) else None
            ranked_at[f"{ranking_type}:{duration}"] = result.get("rankedAt") if isinstance(result, dict) else None
    ranking_meta = merge_ranking_sources(payloads)
    symbols = sorted(ranking_meta)
    stock_rows: list[dict[str, Any]] = []
    for offset in range(0, len(symbols), 200):
        result = client.get_stocks(symbols[offset : offset + 200]).get("result")
        stock_rows.extend(row for row in result or [] if isinstance(row, dict))
    eligible = eligible_common_stocks(stock_rows, ranking_meta)
    return {
        "generated_at": datetime.now().astimezone().isoformat(),
        "selection_bias": "current Toss US liquidity rankings; not a point-in-time historical universe",
        "ranking_types": list(RANKING_TYPES),
        "ranking_durations": list(RANKING_DURATIONS),
        "ranked_at": ranked_at,
        "ranked_symbol_count": len(symbols),
        "eligible_common_stock_count": len(eligible),
        "benchmark_symbols": list(BENCHMARK_SYMBOLS),
        "stocks": eligible,
    }


def cache_symbol(
    client: TossInvestClient,
    *,
    db_path: str,
    symbol: str,
    start_date: str,
    max_pages: int,
    sleep_seconds: float,
) -> dict[str, Any]:
    before_summary = cache_summary(db_path, symbol)
    pages: list[dict[str, Any]] = []
    latest = client.get_candles(symbol, "1d", count=200, adjusted=True).get("result", {})
    candles = latest.get("candles", []) if isinstance(latest, dict) else []
    inserted = db.insert_candles(db_path, symbol, "1d", candles) if candles else 0
    dates = [str(row.get("timestamp") or "")[:10] for row in candles if row.get("timestamp")]
    pages.append({"page": 1, "fetched": len(candles), "inserted_or_replaced": inserted})
    oldest = min(dates) if dates else None
    before = before_summary.min_timestamp if before_summary.rows else latest.get("nextBefore")
    page = 1
    while before and page < max_pages and (oldest is None or oldest > start_date):
        time.sleep(max(0.0, sleep_seconds))
        result = client.get_candles(symbol, "1d", count=200, before=before, adjusted=True).get("result", {})
        candles = result.get("candles", []) if isinstance(result, dict) else []
        if not candles:
            break
        inserted = db.insert_candles(db_path, symbol, "1d", candles)
        dates = [str(row.get("timestamp") or "")[:10] for row in candles if row.get("timestamp")]
        if dates:
            oldest = min(oldest, min(dates)) if oldest else min(dates)
        page += 1
        pages.append({"page": page, "fetched": len(candles), "inserted_or_replaced": inserted})
        next_before = result.get("nextBefore")
        if not next_before or next_before == before:
            break
        before = next_before
    after_summary = cache_summary(db_path, symbol)
    return {
        "symbol": symbol,
        "status": "ok",
        "before": asdict(before_summary),
        "after": asdict(after_summary),
        "pages": pages,
        "reached_start": bool(after_summary.min_timestamp and after_summary.min_timestamp[:10] <= start_date),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Cache Toss US candles for research only; never sends orders")
    parser.add_argument("--db-path", default=DEFAULT_DB)
    parser.add_argument("--universe-out", default=DEFAULT_UNIVERSE)
    parser.add_argument("--report-out", default=DEFAULT_REPORT)
    parser.add_argument("--start-date", default="2011-01-01")
    parser.add_argument("--max-pages", type=int, default=25)
    parser.add_argument("--sleep-seconds", type=float, default=0.20)
    parser.add_argument("--limit", type=int, default=0, help="Research smoke limit; 0 means all eligible stocks")
    args = parser.parse_args()

    settings = replace(Settings.from_env(), db_path=args.db_path, dry_run=True, live_trading=False)
    settings.require_credentials()
    client = TossInvestClient(settings)
    universe = fetch_universe(client)
    stocks = list(universe["stocks"])
    if args.limit > 0:
        stocks = stocks[: args.limit]
    symbols = [str(row["symbol"]) for row in stocks]
    cache_symbols = list(dict.fromkeys([*BENCHMARK_SYMBOLS, *symbols]))
    atomic_write_json(Path(args.universe_out), universe | {"selected_for_cache": cache_symbols})

    db.init_db(args.db_path)
    report: dict[str, Any] = {
        "generated_at": datetime.now().astimezone().isoformat(),
        "db_path": args.db_path,
        "start_date": args.start_date,
        "requested_symbols": len(cache_symbols),
        "rows": [],
        "failures": [],
        "note": "read-only market-data collection; no account or order endpoint is called",
    }
    for index, symbol in enumerate(cache_symbols, start=1):
        started = time.monotonic()
        try:
            row = cache_symbol(
                client,
                db_path=args.db_path,
                symbol=symbol,
                start_date=args.start_date,
                max_pages=max(1, args.max_pages),
                sleep_seconds=args.sleep_seconds,
            )
        except TossApiError as exc:
            row = {"symbol": symbol, "status": "api_error", "status_code": exc.status, "error": str(exc)[:500]}
            report["failures"].append(row)
        except Exception as exc:
            row = {"symbol": symbol, "status": "error", "error": f"{type(exc).__name__}: {exc}"[:500]}
            report["failures"].append(row)
        row["elapsed_seconds"] = round(time.monotonic() - started, 3)
        report["rows"].append(row)
        report["completed_symbols"] = index
        report["quality"] = candle_quality(args.db_path, cache_symbols[:index])
        atomic_write_json(Path(args.report_out), report)
        after = row.get("after", {})
        print(
            f"[{index}/{len(cache_symbols)}] {symbol} {row['status']} "
            f"rows={after.get('rows', 0)} min={str(after.get('min_timestamp') or '')[:10]} "
            f"elapsed={row['elapsed_seconds']:.1f}s",
            flush=True,
        )
        time.sleep(max(0.0, args.sleep_seconds))

    report["finished_at"] = datetime.now().astimezone().isoformat()
    report["quality"] = candle_quality(args.db_path, cache_symbols)
    atomic_write_json(Path(args.report_out), report)
    print(json.dumps({"report": args.report_out, "quality": report["quality"], "failures": len(report["failures"])}, ensure_ascii=False))
    return 0 if not report["failures"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
