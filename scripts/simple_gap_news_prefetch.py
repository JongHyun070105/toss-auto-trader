#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from toss_auto_trader.news_client import NewsHub
from toss_auto_trader.news_prefetch import append_prefetch_snapshot, build_prefetch_snapshot


KST = ZoneInfo("Asia/Seoul")
DEFAULT_OUTPUT = Path("logs/simple_gap_news_prefetch.jsonl")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pre-open OpenDART snapshot; paper-only and no orders")
    parser.add_argument("--date", default=date.today().isoformat())
    parser.add_argument("--lookback-days", type=int, default=3)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--print-only", action="store_true")
    args = parser.parse_args(argv)

    begin_date = (date.fromisoformat(args.date) - timedelta(days=max(0, args.lookback_days))).isoformat()
    hub = NewsHub()
    try:
        items = hub.opendart_disclosures(
            begin_date=begin_date,
            end_date=args.date,
            corp_class="K",
        )
    except Exception as exc:
        print(
            json.dumps(
                {
                    "version": "opendart_kosdaq_prefetch_v1",
                    "trade_date": args.date,
                    "complete": False,
                    "paper_only": True,
                    "order_sent": False,
                    "live_order_allowed": False,
                    "error": str(exc)[:300],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 2

    observed_at = datetime.now(KST).isoformat()
    snapshot = build_prefetch_snapshot(
        items,
        trade_date=args.date,
        observed_at=observed_at,
        begin_date=begin_date,
        end_date=args.date,
    )
    written = False if args.print_only else append_prefetch_snapshot(args.output, snapshot)
    print(
        json.dumps(
            {**snapshot, "items": snapshot["items"][:10], "output": str(args.output), "written": written},
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
