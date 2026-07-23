#!/usr/bin/env python3
"""Audit a raw-gap integrity floor against the Korean gap strategy.

This module is research-only. It reads candle databases in SQLite read-only
mode, never imports the live trader, and never calls account or order APIs.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence

from kr_broad_strategy_research import (
    WINDOWS,
    Event,
    Market,
    Trade,
    anchor_config,
    build_markets,
    json_safe,
    load_events,
    metrics,
    missed_winners,
    passes,
    profile,
    scoped,
    simulate,
)
from simple_gap_strategy_audit import fetch_kosdaq_index
from toss_auto_trader.gap_integrity import (
    MIN_RAW_ENTRY_GAP,
    is_noncomparable_base_gap,
)


DEFAULT_DB = "data/edge_research_universe_15y.sqlite3"
DEFAULT_OUT_DIR = "data/kr_gap_integrity_audit"
COST_PROFILES = ("base", "realistic", "harsh", "extreme")
KRX_BASE_PRICE_URL = (
    "https://global.krx.co.kr/contents/GLB/06/0602/0602010201/"
    "GLB0602010201T6.jsp"
)
KRX_KOSDAQ_LIMIT_URL = (
    "https://global.krx.co.kr/contents/GLB/06/0602/0602020202/"
    "GLB0602020202T2.jsp"
)
KRX_SPECIAL_BASE_URL = (
    "https://global.krx.co.kr/contents/GLB/06/0602/0602020202/"
    "GLB0602020202T4.jsp"
)
KRX_LIQUIDATION_URL = (
    "https://global.krx.co.kr/contents/GLB/06/0602/0602020203/"
    "GLB0602020203T8.jsp"
)


def trade_payload(trade: Trade | None) -> dict[str, Any] | None:
    if trade is None:
        return None
    return {
        "date": trade.date,
        "symbol": trade.symbol,
        "gap": trade.gap,
        "entry": trade.entry,
        "exit": trade.exit,
        "net_pnl": trade.net_pnl,
        "reason": trade.reason,
    }


def changed_trade_days(
    baseline: Sequence[Trade], guarded: Sequence[Trade]
) -> list[dict[str, Any]]:
    baseline_by_date = {trade.date: trade for trade in baseline}
    guarded_by_date = {trade.date: trade for trade in guarded}
    rows: list[dict[str, Any]] = []
    for date in sorted(set(baseline_by_date) | set(guarded_by_date)):
        left = baseline_by_date.get(date)
        right = guarded_by_date.get(date)
        if (
            left is not None
            and right is not None
            and left.symbol == right.symbol
            and abs(left.net_pnl - right.net_pnl) < 1e-9
        ):
            continue
        rows.append(
            {
                "date": date,
                "baseline": trade_payload(left),
                "guarded": trade_payload(right),
                "net_pnl_delta": (right.net_pnl if right else 0.0)
                - (left.net_pnl if left else 0.0),
            }
        )
    return rows


def window_payload(trades: Sequence[Trade]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for name, bounds in WINDOWS.items():
        selected = scoped(trades, *bounds)
        result[name] = {
            "metrics": asdict(metrics(selected)),
            "top_winners_25pct_removed": asdict(missed_winners(selected, 0.25)),
        }
    return result


def eligible_extreme_events(
    events: Sequence[Event], markets: dict[str, Market]
) -> list[Event]:
    baseline = anchor_config()
    return [
        event
        for event in events
        if (market := markets.get(event.date)) is not None
        and passes(event, market, baseline)
        and is_noncomparable_base_gap(event.gap)
    ]


def safety_guard_decision(
    *,
    extreme_event_count: int,
    positive_required_windows: bool,
    post_nxt_trade_selection_changed: bool,
    harsh_baseline_windows: dict[str, Any],
    harsh_guarded_windows: dict[str, Any],
) -> dict[str, Any]:
    def delta(window: str, metric: str) -> float:
        return (
            harsh_guarded_windows[window]["metrics"][metric]
            - harsh_baseline_windows[window]["metrics"][metric]
        )

    recommended = bool(extreme_event_count and positive_required_windows)
    return {
        "classification": "data_integrity_guard_not_alpha_filter",
        "live_safety_guard_recommended": recommended,
        "recommendation_basis": (
            "noncomparable raw-gap observations exist and every predeclared "
            "harsh-cost window remains profitable after exclusion"
            if recommended
            else "insufficient safety or robustness evidence"
        ),
        "positive_required_windows_after_guard": positive_required_windows,
        "post_nxt_trade_selection_changed": post_nxt_trade_selection_changed,
        "recent_selection_change_blocks_recommendation": False,
        "harsh_full_pnl_delta": delta("full", "total_pnl"),
        "harsh_post_nxt_pnl_delta": delta(
            "post_nxt_20250304_2026", "total_pnl"
        ),
        "harsh_full_mdd_delta": delta("full", "mdd_on_capital"),
        "harsh_post_nxt_mdd_delta": delta(
            "post_nxt_20250304_2026", "mdd_on_capital"
        ),
        "strategy_alpha_claim": False,
    }


def audit_events(
    events: Sequence[Event],
    markets: dict[str, Market],
    *,
    database: str,
) -> dict[str, Any]:
    baseline_config = anchor_config()
    guarded_config = replace(
        baseline_config,
        name="robust_gap5_stop0225_take12_gap_integrity31",
        gap_min=MIN_RAW_ENTRY_GAP,
    )
    profiles: dict[str, Any] = {}
    harsh_baseline: list[Trade] = []
    harsh_guarded: list[Trade] = []
    for cost_name in COST_PROFILES:
        baseline_trades = simulate(
            events, markets, profile(baseline_config, cost_name)
        )
        guarded_trades = simulate(
            events, markets, profile(guarded_config, cost_name)
        )
        profiles[cost_name] = {
            "baseline": window_payload(baseline_trades),
            "guarded": window_payload(guarded_trades),
        }
        if cost_name == "harsh":
            harsh_baseline = baseline_trades
            harsh_guarded = guarded_trades

    changed = changed_trade_days(harsh_baseline, harsh_guarded)
    extreme_events = eligible_extreme_events(events, markets)
    recent_changed = [row for row in changed if row["date"] >= "2025-03-04"]
    guarded_windows = profiles["harsh"]["guarded"]
    required_windows = (
        "train_2011_2018",
        "validation_2019_2023",
        "test_pre_nxt_2024_20250303",
        "post_nxt_20250304_2026",
    )
    positive_required_windows = all(
        guarded_windows[name]["metrics"]["total_pnl"] > 0
        for name in required_windows
    )
    decision = safety_guard_decision(
        extreme_event_count=len(extreme_events),
        positive_required_windows=positive_required_windows,
        post_nxt_trade_selection_changed=bool(recent_changed),
        harsh_baseline_windows=profiles["harsh"]["baseline"],
        harsh_guarded_windows=guarded_windows,
    )
    return {
        "database": database,
        "event_rows": len(events),
        "event_date_min": min((event.date for event in events), default=None),
        "event_date_max": max((event.date for event in events), default=None),
        "market_days": len(markets),
        "raw_gap_floor": MIN_RAW_ENTRY_GAP,
        "eligible_extreme_event_count": len(extreme_events),
        "eligible_extreme_symbols": len({event.symbol for event in extreme_events}),
        "eligible_extreme_dates": len({event.date for event in extreme_events}),
        "harsh_selected_extreme_trades": [
            trade_payload(trade)
            for trade in harsh_baseline
            if is_noncomparable_base_gap(trade.gap)
        ],
        "harsh_changed_days": changed,
        "harsh_changed_days_post_nxt": recent_changed,
        "profiles": profiles,
        "decision": decision,
    }


def render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# KR Raw Gap Integrity Audit",
        "",
        f"- generated: `{payload['generated_at']}`",
        f"- raw gap floor: `{payload['raw_gap_floor']:.2%}`",
        "- purpose: data-integrity guard, not an alpha filter",
        "",
        "## Harsh-cost comparison",
        "",
        "| database | strategy | window | trades | pnl | PF | MDD/10k |",
        "|---|---|---|---:|---:|---:|---:|",
    ]
    for database in payload["databases"]:
        for strategy in ("baseline", "guarded"):
            windows = database["profiles"]["harsh"][strategy]
            for window in (
                "train_2011_2018",
                "validation_2019_2023",
                "test_pre_nxt_2024_20250303",
                "post_nxt_20250304_2026",
                "recent_2026",
                "full",
            ):
                values = windows[window]["metrics"]
                pf = values["profit_factor"]
                lines.append(
                    f"| {Path(database['database']).name} | {strategy} | {window} | "
                    f"{values['trades']} | {values['total_pnl']:,.0f} | "
                    f"{'n/a' if pf is None else f'{pf:.2f}'} | "
                    f"{values['mdd_on_capital'] * 100:.1f}% |"
                )
    lines.extend(["", "## Changed selections", ""])
    for database in payload["databases"]:
        decision = database["decision"]
        lines.append(
            f"- `{Path(database['database']).name}`: "
            f"events {database['event_date_min']}~{database['event_date_max']}, "
            f"{len(database['harsh_changed_days'])} changed days; "
            f"{len(database['harsh_changed_days_post_nxt'])} after NXT; "
            f"full delta {decision['harsh_full_pnl_delta']:+,.0f} KRW; "
            f"post-NXT delta {decision['harsh_post_nxt_pnl_delta']:+,.0f} KRW"
        )
        for row in database["harsh_changed_days"]:
            baseline = row["baseline"] or {}
            guarded = row["guarded"] or {}
            lines.append(
                f"  - {row['date']}: "
                f"{baseline.get('symbol', 'none')} ({baseline.get('gap', 0):.2%}) -> "
                f"{guarded.get('symbol', 'none')} ({guarded.get('gap', 0):.2%}), "
                f"delta {row['net_pnl_delta']:+,.0f} KRW"
            )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "- KRX ordinary daily price limits are +/-30% of the day's base price.",
            "- Corporate actions can replace the previous close with an adjusted base price.",
            "- A raw open/previous-cached-close gap below -31% is therefore not treated as an ordinary selloff.",
            "- The one-point buffer avoids rejecting normal limit-down prices due to tick rounding.",
            "- A changed recent selection is diagnostic evidence, not an automatic rejection of a data-integrity guard.",
            "- This audit does not claim that the guard increases expected return.",
            "",
            "## Sources",
            "",
            f"- [KRX base-price rules]({KRX_BASE_PRICE_URL})",
            f"- [KRX KOSDAQ price-limit rules]({KRX_KOSDAQ_LIMIT_URL})",
            f"- [KRX special opening-price rules]({KRX_SPECIAL_BASE_URL})",
            f"- [KRX liquidation-trading rules]({KRX_LIQUIDATION_URL})",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Research-only raw-gap integrity audit; never sends orders"
    )
    parser.add_argument("--db-path", action="append", default=[])
    parser.add_argument("--out-dir", default=DEFAULT_OUT_DIR)
    parser.add_argument("--start", default="2011-01-01")
    parser.add_argument("--end", default=datetime.now().strftime("%Y-%m-%d"))
    args = parser.parse_args()

    db_paths = args.db_path or [DEFAULT_DB]
    index_rows = fetch_kosdaq_index(args.start, args.end)
    database_payloads = []
    for db_path in db_paths:
        events = load_events(db_path, start=args.start, end=args.end)
        markets = build_markets(events, index_rows)
        database_payloads.append(
            audit_events(events, markets, database=str(Path(db_path)))
        )

    payload = {
        "generated_at": datetime.now().astimezone().isoformat(),
        "start": args.start,
        "end": args.end,
        "raw_gap_floor": MIN_RAW_ENTRY_GAP,
        "sources": [
            KRX_BASE_PRICE_URL,
            KRX_KOSDAQ_LIMIT_URL,
            KRX_SPECIAL_BASE_URL,
            KRX_LIQUIDATION_URL,
        ],
        "databases": database_payloads,
        "limits": [
            "Daily OHLC cannot reproduce opening-auction queue position.",
            "Historical live warning and VI states remain incomplete.",
            "A raw-gap floor identifies comparison-basis risk; it does not identify the exact corporate action.",
            "Post-2024 data has already been inspected and is not an untouched holdout.",
        ],
    }
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "kr_gap_integrity_audit.json").write_text(
        json.dumps(json_safe(payload), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (out_dir / "kr_gap_integrity_audit.md").write_text(
        render_markdown(payload), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "out_dir": str(out_dir),
                "raw_gap_floor": MIN_RAW_ENTRY_GAP,
                "databases": [
                    {
                        "database": row["database"],
                        "event_rows": row["event_rows"],
                        "event_date_max": row["event_date_max"],
                        "changed_days": len(row["harsh_changed_days"]),
                        "post_nxt_changed_days": len(
                            row["harsh_changed_days_post_nxt"]
                        ),
                        "guard_recommended": row["decision"][
                            "live_safety_guard_recommended"
                        ],
                    }
                    for row in database_payloads
                ],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
