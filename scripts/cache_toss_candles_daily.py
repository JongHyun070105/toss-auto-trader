#!/usr/bin/env python3
"""Update the local candle_cache with recent daily candles from Toss Invest API.

Operational intent:
- Keep the existing long historical DB intact.
- After market close, replace the latest few daily candles with Toss API data.
- Normalize Toss timestamps to this project's existing daily timestamp key
  (YYYY-MM-DDT00:00:00+09:00) so yfinance-era rows are replaced, not duplicated.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

# src 디렉토리 추가
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from toss_auto_trader import db
from toss_auto_trader.config import Settings
from toss_auto_trader.toss_client import TossApiError, TossInvestClient


DEFAULT_DB_PATH = "data/edge_research_universe_15y.sqlite3"
DEFAULT_SYMBOLS_FILE = "research/kosdaq_symbols.txt"


def load_symbols(path: str, *, limit: int | None = None) -> list[str]:
    symbols: list[str] = []
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"symbols file not found: {path}")
    for raw in p.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        sym = line.split(",", 1)[0].strip()
        if sym:
            symbols.append(sym)
        if limit is not None and len(symbols) >= limit:
            break
    return symbols


def normalize_daily_timestamp(ts: str) -> str:
    """Normalize Toss/yfinance daily timestamps to one DB primary-key format."""
    if not ts:
        return ts
    date_part = ts[:10]
    return f"{date_part}T00:00:00+09:00"


def normalize_candle(candle: dict[str, Any]) -> dict[str, Any]:
    out = dict(candle)
    out["timestamp"] = normalize_daily_timestamp(str(candle.get("timestamp", "")))
    out.setdefault("currency", "KRW")
    out["source"] = "toss"
    return out


def db_summary(db_path: str) -> dict[str, Any]:
    p = Path(db_path)
    if not p.exists():
        return {"exists": False, "path": db_path}
    con = sqlite3.connect(f"file:{p.resolve()}?mode=ro", uri=True)
    try:
        cur = con.cursor()
        cur.execute("SELECT COUNT(*) FROM candle_cache")
        rows = int(cur.fetchone()[0])
        cur.execute("SELECT COUNT(DISTINCT symbol) FROM candle_cache")
        symbols = int(cur.fetchone()[0])
        cur.execute("SELECT MAX(substr(timestamp,1,10)) FROM candle_cache")
        latest = cur.fetchone()[0]
        latest_rows = 0
        if latest:
            cur.execute("SELECT COUNT(*) FROM candle_cache WHERE substr(timestamp,1,10)=?", (latest,))
            latest_rows = int(cur.fetchone()[0])
        return {
            "exists": True,
            "rows": rows,
            "symbols": symbols,
            "latest_date": latest,
            "latest_date_rows": latest_rows,
        }
    finally:
        con.close()


def update_symbol(client: TossInvestClient, db_path: str, symbol: str, *, count: int, dry_run: bool) -> dict[str, Any]:
    resp = client.get_candles(symbol, "1d", count=count)
    result = resp.get("result", {})
    candles_raw = result.get("candles", []) if isinstance(result, dict) else []
    candles = [normalize_candle(c) for c in candles_raw if c.get("timestamp")]
    dates = sorted({c["timestamp"][:10] for c in candles})
    inserted = 0
    if candles and not dry_run:
        inserted = db.insert_candles(db_path, symbol, "1d", candles)
    return {
        "symbol": symbol,
        "fetched": len(candles),
        "inserted_or_replaced": inserted,
        "dates": dates,
        "latest_date": dates[-1] if dates else None,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Update KOSDAQ daily candles from Toss API")
    ap.add_argument("--symbols-file", default=DEFAULT_SYMBOLS_FILE)
    ap.add_argument("--db-path", default=DEFAULT_DB_PATH)
    ap.add_argument("--count", type=int, default=5, help="Recent daily bars per symbol to fetch/replace")
    ap.add_argument("--limit", type=int, default=0, help="Limit symbol count for smoke tests; 0 means all")
    ap.add_argument("--sleep-seconds", type=float, default=0.05, help="Delay between Toss API calls")
    ap.add_argument("--dry-run", action="store_true", help="Fetch and report without writing DB")
    args = ap.parse_args()

    settings = Settings.from_env()
    settings = Settings(
        base_url=settings.base_url,
        client_id=settings.client_id,
        client_secret=settings.client_secret,
        account_seq=settings.account_seq,
        db_path=args.db_path,
        dry_run=settings.dry_run,
        live_trading=settings.live_trading,
    )
    db.init_db(args.db_path)
    client = TossInvestClient(settings)
    symbols = load_symbols(args.symbols_file, limit=args.limit or None)

    started = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"Toss 일봉 캐시 업데이트 시작: {started}")
    print(f"대상 종목 수: {len(symbols)} | count={args.count} | dry_run={args.dry_run}")
    print(f"DB before: {json.dumps(db_summary(args.db_path), ensure_ascii=False)}")

    ok = 0
    failed = 0
    total_fetched = 0
    total_inserted = 0
    latest_dates: dict[str, int] = {}
    errors: list[dict[str, str]] = []

    for i, symbol in enumerate(symbols, 1):
        try:
            row = update_symbol(client, args.db_path, symbol, count=args.count, dry_run=args.dry_run)
            ok += 1
            total_fetched += int(row["fetched"])
            total_inserted += int(row["inserted_or_replaced"])
            if row["latest_date"]:
                latest_dates[row["latest_date"]] = latest_dates.get(row["latest_date"], 0) + 1
        except (TossApiError, Exception) as exc:
            failed += 1
            if len(errors) < 10:
                errors.append({"symbol": symbol, "error": str(exc)[:300]})
        if i % 100 == 0 or i == len(symbols):
            print(f"진행: {i}/{len(symbols)} ok={ok} failed={failed} fetched={total_fetched} inserted={total_inserted}")
        if i < len(symbols) and args.sleep_seconds > 0:
            time.sleep(args.sleep_seconds)

    after = db_summary(args.db_path)
    latest_distribution = dict(sorted(latest_dates.items())[-10:])
    report = {
        "success": failed == 0,
        "ok_symbols": ok,
        "failed_symbols": failed,
        "total_fetched": total_fetched,
        "total_inserted_or_replaced": total_inserted,
        "latest_distribution_tail": latest_distribution,
        "db_after": after,
        "errors_tail": errors,
    }
    print("Toss 일봉 캐시 업데이트 완료")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
