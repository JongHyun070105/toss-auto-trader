#!/usr/bin/env python3
"""Research a guarded fallback entry without touching the live strategy.

The primary leg is the current KOSDAQ <= SMA5 * 0.99 strategy. The fallback
leg may trade only when that primary market guard blocks. Candidate selection
uses data through 2023; 2024+ remains holdout evidence.
"""
from __future__ import annotations

import argparse
import json
import math
from dataclasses import asdict, replace
from datetime import datetime
from itertools import product
from pathlib import Path
from typing import Any, Sequence

import kr_broad_strategy_research as broad
from simple_gap_strategy_audit import fetch_kosdaq_index


DEFAULT_OUT_DIR = "data/kr_guard_fallback_research"


def fallback_configs() -> list[broad.Config]:
    configs: list[broad.Config] = []
    base = broad.anchor_config()
    for (
        gap_max,
        gap_min,
        volume_max,
        min_liquidity,
        prior_mode,
        rank,
        gap_count_max,
        exit_policy,
    ) in product(
        (-0.06, -0.07, -0.08, -0.10),
        (None, -0.15),
        (0.65, 0.8),
        (0.0, 100_000_000.0),
        ("any", "nonpositive"),
        ("lowest_price", "highest_liquidity"),
        (None, 5),
        ((0.015, 0.12), (0.0225, 0.12), (0.02, 0.18)),
    ):
        prior_max = 0.0 if prior_mode == "nonpositive" else None
        stop, take = exit_policy
        name = (
            f"fallback_gap{gap_max}_floor{gap_min}_vol{volume_max}_liq{int(min_liquidity)}_"
            f"prior{prior_mode}_rank{rank}_count{gap_count_max}_stop{stop}_take{take}"
        )
        configs.append(replace(
            base,
            name=name,
            market_min=-0.01,
            market_max=None,
            gap_min=gap_min,
            gap_max=gap_max,
            prev_vol_ratio_max=volume_max,
            min_dollar_volume=min_liquidity,
            prev_return5_min=None,
            prev_return5_max=prior_max,
            gap5_count_max=gap_count_max,
            rank=rank,
            stop_loss=stop,
            take_profit=take,
            roundtrip_cost=0.0135,
        ))
    return configs


def combine_primary_and_fallback(
    primary: Sequence[broad.Trade], fallback: Sequence[broad.Trade]
) -> list[broad.Trade]:
    primary_dates = {trade.date for trade in primary}
    return sorted(
        [*primary, *(trade for trade in fallback if trade.date not in primary_dates)],
        key=lambda trade: (trade.date, trade.symbol),
    )


def fallback_score(blocks: dict[str, broad.Metrics]) -> float:
    train = blocks["train_2011_2018"]
    validation = blocks["validation_2019_2023"]
    if (
        train.trades < 50
        or validation.trades < 30
        or train.total_pnl <= 0
        or validation.total_pnl <= 0
        or (train.profit_factor or 0) <= 1
        or (validation.profit_factor or 0) <= 1
        or train.mdd_on_capital > 0.50
        or validation.mdd_on_capital > 0.50
    ):
        return -math.inf
    pf_floor = min(float(train.profit_factor), float(validation.profit_factor), 4.0)
    return (
        pf_floor * math.log1p(min(train.trades, validation.trades))
        - train.mdd_on_capital
        - validation.mdd_on_capital
    )


def search_fallbacks(
    events: Sequence[broad.Event], markets: dict[str, broad.Market]
) -> list[tuple[float, broad.Config, list[broad.Trade], dict[str, broad.Metrics]]]:
    rows = []
    for config in fallback_configs():
        trades = broad.simulate(events, markets, config)
        blocks = broad.window_metrics(trades)
        rows.append((fallback_score(blocks), config, trades, blocks))
    rows.sort(
        key=lambda row: (
            math.isfinite(row[0]),
            row[0] if math.isfinite(row[0]) else broad.diagnostic_score(row[3]),
        ),
        reverse=True,
    )
    return rows


def stress_evaluation(
    events: Sequence[broad.Event],
    markets: dict[str, broad.Market],
    fallback: broad.Config,
) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for profile_name in ("base", "realistic", "harsh", "extreme"):
        primary_config = broad.profile(broad.anchor_config(), profile_name)
        fallback_config = replace(
            fallback,
            name=f"{fallback.name}_{profile_name}",
            roundtrip_cost=primary_config.roundtrip_cost,
        )
        primary = broad.simulate(events, markets, primary_config)
        secondary = broad.simulate(events, markets, fallback_config)
        combined = combine_primary_and_fallback(primary, secondary)
        output[profile_name] = {
            "baseline": broad.evaluation(events, markets, primary_config),
            "fallback": broad.evaluation(events, markets, fallback_config),
            "combined": evaluate_trades(combined),
        }
    return output


def evaluate_trades(trades: Sequence[broad.Trade]) -> dict[str, Any]:
    windows = {}
    for name, bounds in broad.WINDOWS.items():
        rows = broad.scoped(trades, *bounds)
        windows[name] = {
            "metrics": asdict(broad.metrics(rows)),
            "miss_top_winners_10pct": asdict(broad.missed_winners(rows, 0.10)),
            "miss_top_winners_25pct": asdict(broad.missed_winners(rows, 0.25)),
            "monthly_bootstrap_positive_probability": broad.monthly_bootstrap_positive_probability(rows),
        }
    return {"windows": windows}


def accepted(evaluation: dict[str, Any]) -> bool:
    harsh = evaluation["harsh"]
    extreme = evaluation["extreme"]
    base_post = harsh["baseline"]["windows"]["post_nxt_20250304_2026"]["metrics"]
    fallback_post = harsh["fallback"]["windows"]["post_nxt_20250304_2026"]
    combined_post = harsh["combined"]["windows"]["post_nxt_20250304_2026"]
    extreme_post = extreme["combined"]["windows"]["post_nxt_20250304_2026"]
    combined_metrics = combined_post["metrics"]
    return bool(
        fallback_post["metrics"]["trades"] >= 10
        and fallback_post["metrics"]["total_pnl"] > 0
        and (fallback_post["metrics"]["profit_factor"] or 0) >= 1.2
        and combined_metrics["total_pnl"] > base_post["total_pnl"]
        and combined_metrics["mdd_on_capital"] <= min(0.20, base_post["mdd_on_capital"] + 0.05)
        and combined_post["miss_top_winners_25pct"]["total_pnl"] > 0
        and (combined_post["monthly_bootstrap_positive_probability"] or 0) >= 0.70
        and extreme_post["metrics"]["total_pnl"] > 0
    )


def json_safe(value: Any) -> Any:
    return broad.json_safe(value)


def markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# KR Guard Fallback Research",
        "",
        f"- fallback configurations: `{payload['configs_tested']}`",
        f"- selected using data through 2023: `{payload['selected_config']['name']}`",
        f"- accepted for live adoption: `{payload['accepted_for_live_adoption']}`",
        "",
        "## Harsh-cost comparison",
        "",
        "| strategy | window | trades | PnL (KRW) | PF | MDD/capital | miss top 25% PnL |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    harsh = payload["evaluation"]["harsh"]
    for label in ("baseline", "fallback", "combined"):
        for window in ("train_2011_2018", "validation_2019_2023", "test_pre_nxt_2024_20250303", "post_nxt_20250304_2026", "recent_2026"):
            row = harsh[label]["windows"][window]
            metric = row["metrics"]
            pf = "n/a" if metric["profit_factor"] is None else f"{metric['profit_factor']:.2f}"
            lines.append(
                f"| {label} | {window} | {metric['trades']} | {metric['total_pnl']:,.0f} | {pf} | "
                f"{metric['mdd_on_capital']*100:.1f}% | {row['miss_top_winners_25pct']['total_pnl']:,.0f} |"
            )
    lines.extend([
        "",
        "The fallback is evaluated only on dates where the current market guard blocks. "
        "The live strategy is not imported or changed.",
        "",
    ])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Research a non-overlapping fallback for guard-blocked dates")
    parser.add_argument("--db-path", default=broad.DEFAULT_DB)
    parser.add_argument("--out-dir", default=DEFAULT_OUT_DIR)
    parser.add_argument("--start", default="2011-01-01")
    parser.add_argument("--end", default="2026-07-16")
    args = parser.parse_args()

    events = broad.load_events(args.db_path, start=args.start, end=args.end)
    markets = broad.build_markets(events, fetch_kosdaq_index(args.start, args.end))
    rows = search_fallbacks(events, markets)
    selected_score, selected, _, selected_blocks = rows[0]
    evaluation = stress_evaluation(events, markets, selected)
    payload = {
        "generated_at": datetime.now().astimezone().isoformat(),
        "selection_cutoff": "2023-12-31",
        "event_rows": len(events),
        "market_days": len(markets),
        "configs_tested": len(rows),
        "selected_pretest_passed": math.isfinite(selected_score),
        "selected_score": selected_score,
        "selected_config": asdict(selected),
        "selected_train": asdict(selected_blocks["train_2011_2018"]),
        "selected_validation": asdict(selected_blocks["validation_2019_2023"]),
        "accepted_for_live_adoption": accepted(evaluation),
        "search_top50": [
            {
                "passed_pretest_gate": math.isfinite(score),
                "score": score if math.isfinite(score) else broad.diagnostic_score(blocks),
                "config": asdict(config),
                "train": asdict(blocks["train_2011_2018"]),
                "validation": asdict(blocks["validation_2019_2023"]),
            }
            for score, config, _, blocks in rows[:50]
        ],
        "evaluation": evaluation,
        "limits": [
            "current surviving symbol universe creates survivorship bias",
            "fallback selection still tests many related hypotheses",
            "daily OHLC assumes stop-first and cannot reproduce auction fills",
            "historical Toss warning, VI, and NXT venue flags are unavailable",
        ],
    }
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "kr_guard_fallback_research.json").write_text(
        json.dumps(json_safe(payload), ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    (out / "kr_guard_fallback_research.md").write_text(markdown(payload), encoding="utf-8")
    print(json.dumps({
        "out_dir": str(out),
        "configs": len(rows),
        "selected": asdict(selected),
        "accepted": payload["accepted_for_live_adoption"],
        "post_nxt_harsh": evaluation["harsh"]["combined"]["windows"]["post_nxt_20250304_2026"]["metrics"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
