#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import replace
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from toss_auto_trader.config import Settings
from toss_auto_trader.toss_client import TossInvestClient
from toss_auto_trader.vi_reopen_shadow import (
    STRATEGY_NAME,
    load_vi_events,
    simulate_vi_reopen_event,
    summarize_simulations,
)


KST = ZoneInfo("Asia/Seoul")
DEFAULT_AUDIT = Path("logs/simple_gap_entry_price_audit.jsonl")
DEFAULT_OUTPUT = Path("logs/simple_gap_vi_reopen_shadow.jsonl")
def _fetch_trade_day_candles(
    client: TossInvestClient,
    symbol: str,
    trade_date: str,
    *,
    max_pages: int = 3,
) -> list[dict[str, Any]]:
    before = f"{trade_date}T15:31:00+09:00"
    candles_by_timestamp: dict[str, dict[str, Any]] = {}
    for _ in range(max_pages):
        response = client.get_candles(symbol, "1m", count=200, before=before, adjusted=True)
        rows = response.get("result", {}).get("candles", [])
        if not rows:
            break
        for row in rows:
            timestamp = str(row.get("timestamp") or "")
            if timestamp:
                candles_by_timestamp[timestamp] = row
        oldest = str(rows[-1].get("timestamp") or "")
        if not oldest:
            break
        oldest_date = oldest[:10]
        if oldest_date < trade_date or oldest.startswith(f"{trade_date}T09:00"):
            break
        before = oldest
        time.sleep(0.22)
    return list(candles_by_timestamp.values())


def _append_unique(path: Path, rows: list[dict[str, Any]]) -> int:
    existing: set[tuple[str, str, str, str]] = set()
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            existing.add(
                (
                    str(row.get("trade_date") or ""),
                    str(row.get("symbol") or ""),
                    str(row.get("warning_captured_at") or ""),
                    str(row.get("cost_profile") or ""),
                )
            )
    pending = []
    for row in rows:
        key = (
            str(row.get("trade_date") or ""),
            str(row.get("symbol") or ""),
            str(row.get("warning_captured_at") or ""),
            str(row.get("cost_profile") or ""),
        )
        if key not in existing:
            existing.add(key)
            pending.append(row)
    if pending:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            for row in pending:
                handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    return len(pending)


def parse_cost_profiles(raw: str) -> dict[str, float]:
    profiles: dict[str, float] = {}
    for item in raw.split(","):
        name, separator, value = item.strip().partition(":")
        if not separator or not name:
            raise ValueError("cost profiles must look like base:0.35,harsh:1.35")
        profiles[name] = float(value)
    return profiles


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Paper-only VI reopen execution study; never sends orders")
    parser.add_argument("--date", default=date.today().isoformat())
    parser.add_argument("--audit", type=Path, default=DEFAULT_AUDIT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--capital", type=float, default=10_000.0)
    parser.add_argument("--cost-profiles", default="base:0.35,harsh:1.35")
    parser.add_argument("--max-events", type=int, default=20)
    parser.add_argument("--print-only", action="store_true")
    args = parser.parse_args(argv)

    loaded = load_vi_events(args.audit, args.date)
    events = loaded["events"][: max(0, args.max_events)]
    settings = replace(Settings.from_env(), dry_run=True, live_trading=False)
    client = TossInvestClient(settings)
    profiles = parse_cost_profiles(args.cost_profiles)
    rows: list[dict[str, Any]] = []
    api_errors: list[dict[str, str]] = []
    for event in events:
        try:
            candles = _fetch_trade_day_candles(client, str(event["symbol"]), args.date)
        except Exception as exc:
            api_errors.append({"symbol": str(event["symbol"]), "error": str(exc)[:300]})
            continue
        for profile_name, cost_pct in profiles.items():
            result = simulate_vi_reopen_event(
                event,
                candles,
                capital_krw=args.capital,
                roundtrip_cost_pct=cost_pct,
            )
            result["cost_profile"] = profile_name
            result["observed_at"] = datetime.now(KST).isoformat()
            rows.append(result)

    written = 0 if args.print_only else _append_unique(args.output, rows)
    by_profile = {
        name: summarize_simulations([row for row in rows if row.get("cost_profile") == name])
        for name in profiles
    }
    report = {
        "strategy_name": STRATEGY_NAME,
        "trade_date": args.date,
        "paper_only": True,
        "order_sent": False,
        "live_order_allowed": False,
        "audit": {key: value for key, value in loaded.items() if key != "events"},
        "vi_events": len(events),
        "api_errors": api_errors,
        "summaries": by_profile,
        "rows": rows,
        "output": str(args.output),
        "written": written,
        "print_only": args.print_only,
        "research_limitations": [
            "warning capture time is a poll timestamp, not the exact KRX trigger timestamp",
            "one-minute OHLC cannot resolve intrabar stop/take order",
            "sample contains only forward-captured Toss warning events",
        ],
    }
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if not api_errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
