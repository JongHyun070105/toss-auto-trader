#!/usr/bin/env python3
"""Deep dive on the count of broad -5% opening-gap events.

This is research-only. It tests whether requiring multiple simultaneous gap
events improves the current strategy, and whether any apparent optimum is a
stable plateau instead of a single lucky threshold.
"""
from __future__ import annotations

import argparse
import json
import math
from dataclasses import asdict, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence

import kr_broad_strategy_research as broad
from simple_gap_strategy_audit import fetch_kosdaq_index


DEFAULT_OUT_DIR = "data/kr_breadth_gate_research"


def threshold_configs() -> list[broad.Config]:
    base = broad.anchor_config()
    return [base, *[
        replace(base, name=f"gap5_count_at_least_{threshold}", gap5_count_min=threshold)
        for threshold in range(1, 21)
    ]]


def research_rows(
    events: Sequence[broad.Event], markets: dict[str, broad.Market]
) -> list[dict[str, Any]]:
    rows = []
    for config in threshold_configs():
        trades = broad.simulate(events, markets, config)
        blocks = broad.window_metrics(trades)
        post = broad.scoped(trades, *broad.WINDOWS["post_nxt_20250304_2026"])
        rows.append({
            "threshold": config.gap5_count_min or 0,
            "config": asdict(config),
            "selection_score": broad.selection_score(blocks),
            "windows": {name: asdict(metric) for name, metric in blocks.items()},
            "post_nxt_miss_top_25pct": asdict(broad.missed_winners(post, 0.25)),
            "post_nxt_bootstrap_positive_probability": broad.monthly_bootstrap_positive_probability(post),
        })
    return rows


def select_pretest(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    return max(
        rows,
        key=lambda row: (
            math.isfinite(row["selection_score"]),
            row["selection_score"] if math.isfinite(row["selection_score"]) else -math.inf,
        ),
    )


def stress(
    events: Sequence[broad.Event], markets: dict[str, broad.Market], selected: broad.Config
) -> dict[str, Any]:
    return {
        label: {
            "baseline": broad.evaluation(events, markets, broad.profile(broad.anchor_config(), label)),
            "selected": broad.evaluation(events, markets, broad.profile(selected, label)),
        }
        for label in ("base", "realistic", "harsh", "extreme")
    }


def shadow_candidate(rows: Sequence[dict[str, Any]], selected: dict[str, Any], stress_rows: dict[str, Any]) -> bool:
    threshold = selected["threshold"]
    neighbors = [row for row in rows if abs(row["threshold"] - threshold) <= 2]
    post = selected["windows"]["post_nxt_20250304_2026"]
    pre = selected["windows"]["test_pre_nxt_2024_20250303"]
    extreme_post = stress_rows["extreme"]["selected"]["windows"]["post_nxt_20250304_2026"]
    return bool(
        threshold > 0
        and math.isfinite(selected["selection_score"])
        and pre["trades"] >= 10
        and pre["total_pnl"] > 0
        and post["trades"] >= 25
        and post["total_pnl"] > 0
        and post["mdd_on_capital"] <= 0.15
        and selected["post_nxt_miss_top_25pct"]["total_pnl"] > 0
        and (selected["post_nxt_bootstrap_positive_probability"] or 0) >= 0.70
        and extreme_post["metrics"]["total_pnl"] > 0
        and len(neighbors) >= 3
        and all(row["windows"]["post_nxt_20250304_2026"]["total_pnl"] > 0 for row in neighbors)
    )


def markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# KR Breadth Gate Research",
        "",
        f"- selected on 2011-2023: gap5 count >= `{payload['selected_threshold']}`",
        f"- candidate for shadow logging: `{payload['candidate_for_shadow_logging']}`",
        f"- live strategy changed: `False`",
        "",
        "| min count | train trades | validation trades | pre-NXT PF | post-NXT trades | post-NXT PnL | post-NXT PF | MDD | miss top 25% PnL |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in payload["threshold_rows"]:
        pre = row["windows"]["test_pre_nxt_2024_20250303"]
        post = row["windows"]["post_nxt_20250304_2026"]
        lines.append(
            f"| {row['threshold']} | {row['windows']['train_2011_2018']['trades']} | "
            f"{row['windows']['validation_2019_2023']['trades']} | {(pre['profit_factor'] or 0):.2f} | "
            f"{post['trades']} | {post['total_pnl']:,.0f} | {(post['profit_factor'] or 0):.2f} | "
            f"{post['mdd_on_capital']*100:.1f}% | {row['post_nxt_miss_top_25pct']['total_pnl']:,.0f} |"
        )
    lines.extend([
        "",
        "Count uses all current-universe symbols priced 500-30,000 won with an opening gap of -5% or worse. "
        "That definition must be reproduced in live provisional-price data before adoption.",
        "",
    ])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Research broad gap-count thresholds")
    parser.add_argument("--db-path", default=broad.DEFAULT_DB)
    parser.add_argument("--out-dir", default=DEFAULT_OUT_DIR)
    parser.add_argument("--start", default="2011-01-01")
    parser.add_argument("--end", default="2026-07-16")
    args = parser.parse_args()

    events = broad.load_events(args.db_path, start=args.start, end=args.end)
    markets = broad.build_markets(events, fetch_kosdaq_index(args.start, args.end))
    rows = research_rows(events, markets)
    selected_row = select_pretest(rows)
    selected_config = replace(
        broad.anchor_config(),
        name=f"breadth_gap5_min_{selected_row['threshold']}",
        gap5_count_min=selected_row["threshold"] or None,
    )
    stress_rows = stress(events, markets, selected_config)
    payload = {
        "generated_at": datetime.now().astimezone().isoformat(),
        "selection_cutoff": "2023-12-31",
        "event_rows": len(events),
        "market_days": len(markets),
        "thresholds_tested": len(rows),
        "selected_threshold": selected_row["threshold"],
        "selected_pretest_score": selected_row["selection_score"],
        "candidate_for_shadow_logging": shadow_candidate(rows, selected_row, stress_rows),
        "live_strategy_changed": False,
        "threshold_rows": rows,
        "stress": stress_rows,
        "limits": [
            "current surviving symbol universe creates survivorship bias",
            "daily OHLC cannot reproduce the 09:01 observation and fill sequence",
            "historical Toss warnings, VI, and NXT venue data are unavailable",
            "live provisional quote coverage may differ from database breadth coverage",
        ],
    }
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "kr_breadth_gate_research.json").write_text(
        json.dumps(broad.json_safe(payload), ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    (out / "kr_breadth_gate_research.md").write_text(markdown(payload), encoding="utf-8")
    print(json.dumps({
        "out_dir": str(out),
        "selected_threshold": payload["selected_threshold"],
        "candidate_for_shadow_logging": payload["candidate_for_shadow_logging"],
        "post_nxt_harsh": stress_rows["harsh"]["selected"]["windows"]["post_nxt_20250304_2026"]["metrics"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
