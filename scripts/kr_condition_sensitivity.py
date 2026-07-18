#!/usr/bin/env python3
"""One-factor sensitivity map for the current Korean gap strategy.

Each family changes one rule at a time from the live anchor. Family winners are
ranked only on 2011-2023 data and then reported on untouched 2024+ windows.
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


DEFAULT_OUT_DIR = "data/kr_condition_sensitivity"


def condition_families() -> dict[str, list[broad.Config]]:
    base = broad.anchor_config()

    def configs(family: str, variants: Sequence[tuple[str, dict[str, Any]]]) -> list[broad.Config]:
        return [replace(base, name=f"{family}:{label}", **changes) for label, changes in variants]

    return {
        "market_gate": configs("market_gate", [
            ("none", {"market_max": None}),
            ("below_sma5", {"market_max": 0.0}),
            ("below_0.5pct", {"market_max": -0.005}),
            ("below_1pct_anchor", {"market_max": -0.01}),
            ("below_1.5pct", {"market_max": -0.015}),
            ("below_2pct", {"market_max": -0.02}),
            ("below_3pct", {"market_max": -0.03}),
            ("band_4_to_1pct", {"market_min": -0.04, "market_max": -0.01}),
        ]),
        "stock_gap": configs("stock_gap", [
            ("3pct", {"gap_max": -0.03}),
            ("4pct", {"gap_max": -0.04}),
            ("5pct_anchor", {"gap_max": -0.05}),
            ("6pct", {"gap_max": -0.06}),
            ("7pct", {"gap_max": -0.07}),
            ("8pct", {"gap_max": -0.08}),
            ("5_to_15pct", {"gap_min": -0.15, "gap_max": -0.05}),
        ]),
        "price": configs("price", [
            ("500_8000", {"min_price": 500.0}),
            ("1000_6000", {"max_price": 6000.0}),
            ("1000_8000_anchor", {}),
            ("1000_10000", {"max_price": 10000.0}),
            ("2000_8000", {"min_price": 2000.0}),
            ("3000_8000", {"min_price": 3000.0}),
        ]),
        "prior_volume": configs("prior_volume", [
            ("under_0.5", {"prev_vol_ratio_max": 0.5}),
            ("under_0.65", {"prev_vol_ratio_max": 0.65}),
            ("under_0.8_anchor", {}),
            ("under_1.0", {"prev_vol_ratio_max": 1.0}),
            ("under_1.25", {"prev_vol_ratio_max": 1.25}),
            ("under_1.5", {"prev_vol_ratio_max": 1.5}),
        ]),
        "liquidity": configs("liquidity", [
            ("none_anchor", {}),
            ("adv_100m", {"min_dollar_volume": 100_000_000.0}),
            ("adv_300m", {"min_dollar_volume": 300_000_000.0}),
            ("adv_500m", {"min_dollar_volume": 500_000_000.0}),
            ("adv_1b", {"min_dollar_volume": 1_000_000_000.0}),
        ]),
        "prior_5d_return": configs("prior_5d_return", [
            ("any_anchor", {}),
            ("minus20_to_0", {"prev_return5_min": -0.20, "prev_return5_max": 0.0}),
            ("minus10_to_0", {"prev_return5_min": -0.10, "prev_return5_max": 0.0}),
            ("0_to_plus10", {"prev_return5_min": 0.0, "prev_return5_max": 0.10}),
            ("0_to_plus20", {"prev_return5_min": 0.0, "prev_return5_max": 0.20}),
        ]),
        "prior_close_location": configs("prior_close_location", [
            ("any_anchor", {}),
            ("bottom_25pct", {"close_location_max": 0.25}),
            ("bottom_half", {"close_location_max": 0.5}),
            ("top_half", {"close_location_min": 0.5}),
            ("top_25pct", {"close_location_min": 0.75}),
        ]),
        "market_breadth": configs("market_breadth", [
            ("any_anchor", {}),
            ("gap5_at_most_3", {"gap5_count_max": 3}),
            ("gap5_at_most_5", {"gap5_count_max": 5}),
            ("gap5_at_most_10", {"gap5_count_max": 10}),
            ("gap5_at_least_2", {"gap5_count_min": 2}),
            ("gap5_at_least_5", {"gap5_count_min": 5}),
            ("gap5_at_least_10", {"gap5_count_min": 10}),
        ]),
        "rank": configs("rank", [
            ("lowest_price_anchor", {}),
            ("highest_liquidity", {"rank": "highest_liquidity"}),
            ("most_negative_gap", {"rank": "most_negative_gap"}),
            ("mildest_gap", {"rank": "mildest_gap"}),
            ("quiet_volume", {"rank": "quiet_volume"}),
            ("gap_over_range", {"rank": "gap_over_range"}),
            ("prior_strength", {"rank": "prior_strength"}),
        ]),
        "exit": configs("exit", [
            ("stop1.5_take12", {"stop_loss": 0.015, "take_profit": 0.12}),
            ("stop2.0_take12", {"stop_loss": 0.02, "take_profit": 0.12}),
            ("stop2.25_take12_anchor", {}),
            ("stop3_take12", {"stop_loss": 0.03, "take_profit": 0.12}),
            ("stop2_take18", {"stop_loss": 0.02, "take_profit": 0.18}),
            ("stop2.5_take18", {"stop_loss": 0.025, "take_profit": 0.18}),
            ("no_stop_take12", {"stop_loss": None, "take_profit": 0.12}),
            ("stop2.25_no_take", {"take_profit": None}),
            ("close_only", {"stop_loss": None, "take_profit": None}),
            ("hold_1d", {"exit_days": 1, "stop_loss": None, "take_profit": None}),
            ("hold_3d", {"exit_days": 3, "stop_loss": None, "take_profit": None}),
            ("hold_5d", {"exit_days": 5, "stop_loss": None, "take_profit": None}),
        ]),
    }


def evaluate_config(
    events: Sequence[broad.Event], markets: dict[str, broad.Market], config: broad.Config
) -> dict[str, Any]:
    trades = broad.simulate(events, markets, config)
    blocks = broad.window_metrics(trades)
    post_rows = broad.scoped(trades, *broad.WINDOWS["post_nxt_20250304_2026"])
    return {
        "config": asdict(config),
        "selection_score": broad.selection_score(blocks),
        "windows": {name: asdict(metric) for name, metric in blocks.items()},
        "post_nxt_miss_top_25pct": asdict(broad.missed_winners(post_rows, 0.25)),
        "post_nxt_bootstrap_positive_probability": broad.monthly_bootstrap_positive_probability(post_rows),
    }


def family_winner(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    return max(
        rows,
        key=lambda row: (
            math.isfinite(row["selection_score"]),
            row["selection_score"] if math.isfinite(row["selection_score"]) else -math.inf,
        ),
    )


def markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# KR Condition Sensitivity",
        "",
        f"- configurations: `{payload['configs_tested']}`",
        "- family winners selected on 2011-2023 only; 2024+ is holdout",
        "- cost assumption: 1.35% round trip",
        "",
        "| family | selected rule | validation trades | validation PF | pre-NXT PF | post-NXT PF | post-NXT MDD | miss top 25% PnL |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for family, row in payload["family_winners"].items():
        validation = row["windows"]["validation_2019_2023"]
        pre = row["windows"]["test_pre_nxt_2024_20250303"]
        post = row["windows"]["post_nxt_20250304_2026"]
        lines.append(
            f"| {family} | {row['config']['name']} | {validation['trades']} | "
            f"{(validation['profit_factor'] or 0):.2f} | {(pre['profit_factor'] or 0):.2f} | "
            f"{(post['profit_factor'] or 0):.2f} | {post['mdd_on_capital']*100:.1f}% | "
            f"{row['post_nxt_miss_top_25pct']['total_pnl']:,.0f} |"
        )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="One-factor sensitivity map for the Korean gap strategy")
    parser.add_argument("--db-path", default=broad.DEFAULT_DB)
    parser.add_argument("--out-dir", default=DEFAULT_OUT_DIR)
    parser.add_argument("--start", default="2011-01-01")
    parser.add_argument("--end", default="2026-07-16")
    args = parser.parse_args()

    events = broad.load_events(args.db_path, start=args.start, end=args.end)
    markets = broad.build_markets(events, fetch_kosdaq_index(args.start, args.end))
    evaluations: dict[str, list[dict[str, Any]]] = {}
    winners: dict[str, dict[str, Any]] = {}
    for family, configs in condition_families().items():
        rows = [evaluate_config(events, markets, config) for config in configs]
        evaluations[family] = rows
        winners[family] = family_winner(rows)
    payload = {
        "generated_at": datetime.now().astimezone().isoformat(),
        "selection_cutoff": "2023-12-31",
        "cost": 0.0135,
        "event_rows": len(events),
        "market_days": len(markets),
        "configs_tested": sum(len(rows) for rows in evaluations.values()),
        "family_winners": winners,
        "evaluations": evaluations,
    }
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "kr_condition_sensitivity.json").write_text(
        json.dumps(broad.json_safe(payload), ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    (out / "kr_condition_sensitivity.md").write_text(markdown(payload), encoding="utf-8")
    print(json.dumps({
        "out_dir": str(out),
        "configs": payload["configs_tested"],
        "winners": {family: row["config"]["name"] for family, row in winners.items()},
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
