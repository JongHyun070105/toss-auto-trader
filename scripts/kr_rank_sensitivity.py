#!/usr/bin/env python3
"""Compare Korean gap-candidate ranking rules without sending orders.

The entry filters, exit rules, capital, and cost profiles stay fixed. This
experiment changes only the one-candidate-per-day ranking rule, so a result
cannot be mistaken for evidence that the broader strategy is improved.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence

import kr_broad_strategy_research as broad
from kr_gap_integrity_audit import changed_trade_days, window_payload
from simple_gap_strategy_audit import fetch_kosdaq_index
from toss_auto_trader.research_fingerprint import candle_database_fingerprint


DEFAULT_DB = broad.DEFAULT_DB
DEFAULT_OUT_DIR = "data/kr_rank_sensitivity"
RANKS = (
    "lowest_price",
    "highest_liquidity",
    "most_negative_gap",
    "mildest_gap",
    "quiet_volume",
    "gap_over_range",
    "prior_strength",
)
COSTS = ("harsh", "extreme")
REQUIRED_WINDOWS = (
    "train_2011_2018",
    "validation_2019_2023",
    "test_pre_nxt_2024_20250303",
    "post_nxt_20250304_2026",
)


def rank_config(rank: str) -> broad.Config:
    if rank not in RANKS:
        raise ValueError(f"unsupported rank: {rank}")
    anchor = broad.anchor_config()
    return replace(anchor, name=f"{anchor.name}_rank_{rank}", rank=rank)


def _metric(block: dict[str, Any], window: str, key: str) -> float:
    value = block[window]["metrics"][key]
    return float(value) if value is not None else 0.0


def robust_rank_decision(
    rank: str,
    candidate: dict[str, Any],
    anchor: dict[str, Any],
) -> dict[str, Any]:
    """Apply a predeclared promotion gate to a rank-only candidate.

    A candidate must remain profitable in every frozen window at both costs,
    match or beat the live anchor's post-NXT PnL and MDD, and stay positive
    after removing the largest 25% of winning trades. The live anchor is never
    replaced by this report automatically.
    """

    failures: list[str] = []
    if rank == "lowest_price":
        return {"status": "current_live", "accepted": False, "failures": []}
    for cost in COSTS:
        candidate_windows = candidate[cost]
        anchor_windows = anchor[cost]
        for window in REQUIRED_WINDOWS:
            if _metric(candidate_windows, window, "total_pnl") <= 0:
                failures.append(f"{cost}:{window}:non_positive_pnl")
        post = "post_nxt_20250304_2026"
        if _metric(candidate_windows, post, "total_pnl") < _metric(
            anchor_windows, post, "total_pnl"
        ):
            failures.append(f"{cost}:{post}:below_live_pnl")
        if _metric(candidate_windows, post, "mdd_on_capital") > _metric(
            anchor_windows, post, "mdd_on_capital"
        ):
            failures.append(f"{cost}:{post}:above_live_mdd")
        top25 = candidate_windows[post]["top_winners_25pct_removed"]
        if float(top25["total_pnl"]) <= 0:
            failures.append(f"{cost}:{post}:non_positive_after_top25_removed")
    return {
        "status": "promote_candidate" if not failures else "keep_live_anchor",
        "accepted": not failures,
        "failures": failures,
    }


def evaluate_rank(
    events: Sequence[broad.Event],
    markets: dict[str, broad.Market],
    rank: str,
    anchor_results: dict[str, Any] | None = None,
) -> dict[str, Any]:
    config = rank_config(rank)
    costs = {
        cost: window_payload(
            broad.simulate(events, markets, broad.profile(config, cost))
        )
        for cost in COSTS
    }
    result: dict[str, Any] = {
        "rank": rank,
        "config": asdict(config),
        **costs,
    }
    if anchor_results is not None:
        result["changed_vs_live"] = {}
        for cost in COSTS:
            baseline_trades = broad.simulate(
                events, markets, broad.profile(rank_config("lowest_price"), cost)
            )
            candidate_trades = broad.simulate(
                events, markets, broad.profile(config, cost)
            )
            changed = changed_trade_days(baseline_trades, candidate_trades)
            post_changed = [
                row for row in changed if row["date"] >= "2025-03-04"
            ]
            result["changed_vs_live"][cost] = {
                "days": len(changed),
                "post_nxt_days": len(post_changed),
                "full_pnl_delta": _metric(result[cost], "full", "total_pnl")
                - _metric(anchor_results[cost], "full", "total_pnl"),
                "post_nxt_pnl_delta": _metric(
                    result[cost], "post_nxt_20250304_2026", "total_pnl"
                )
                - _metric(
                    anchor_results[cost],
                    "post_nxt_20250304_2026",
                    "total_pnl",
                ),
            }
        result["decision"] = robust_rank_decision(rank, result, anchor_results)
    return result


def evaluate_all(
    events: Sequence[broad.Event], markets: dict[str, broad.Market]
) -> dict[str, Any]:
    anchor = evaluate_rank(events, markets, "lowest_price")
    rows = [anchor]
    rows.extend(
        evaluate_rank(events, markets, rank, anchor)
        for rank in RANKS
        if rank != "lowest_price"
    )
    return {
        "event_rows": len(events),
        "market_days": len(markets),
        "anchor_rank": "lowest_price",
        "ranks_tested": list(RANKS),
        "required_windows": list(REQUIRED_WINDOWS),
        "cost_profiles": {
            "harsh": 0.0135,
            "extreme": 0.0245,
        },
        "results": rows,
    }


def _pf(value: Any) -> str:
    return "n/a" if value is None else f"{float(value):.2f}"


def render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# KR Candidate Rank Sensitivity",
        "",
        f"- generated: `{payload['generated_at']}`",
        f"- events: `{payload['event_rows']}` / market days: `{payload['market_days']}`",
        "- filters, entry price, stop, take-profit, capital, and one-position rule are fixed",
        "- only the one-candidate-per-day ranking rule changes",
        "- `harsh` = 1.35% round trip; `extreme` = 2.45% round trip",
        "- post-2024 data is a diagnostic holdout, not untouched data",
        "",
        "## Result",
        "",
        "| rank | harsh full PnL | harsh full PF | harsh MDD | harsh post PnL | extreme post PnL | post top25 removed | changed days | decision |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in payload["results"]:
        harsh = row["harsh"]["full"]["metrics"]
        post = row["harsh"]["post_nxt_20250304_2026"]["metrics"]
        extreme_post = row["extreme"]["post_nxt_20250304_2026"]["metrics"]
        robust = row["harsh"]["post_nxt_20250304_2026"][
            "top_winners_25pct_removed"
        ]
        changed = row.get("changed_vs_live", {}).get("harsh", {}).get("days", 0)
        decision = row.get("decision", {}).get("status", "current_live")
        lines.append(
            f"| `{row['rank']}` | {harsh['total_pnl']:,.0f} | {_pf(harsh['profit_factor'])} | "
            f"{harsh['mdd_on_capital'] * 100:.1f}% | {post['total_pnl']:,.0f} | "
            f"{extreme_post['total_pnl']:,.0f} | {robust['total_pnl']:,.0f} | "
            f"{changed} | `{decision}` |"
        )
    lines.extend(
        [
            "",
            "## Promotion gate",
            "",
            "A non-live rank is accepted only when both cost profiles are positive in all frozen windows, post-NXT PnL is at least the live anchor, post-NXT MDD is no higher than the live anchor, and post-NXT PnL remains positive after removing the largest 25% of winning trades.",
            "",
            "This report never changes the live rank automatically. Daily OHLC still cannot reproduce opening-auction queue position, VI state, order-book depth, or actual fills.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="No-order Korean gap candidate rank sensitivity backtest"
    )
    parser.add_argument("--db-path", default=DEFAULT_DB)
    parser.add_argument("--out-dir", default=DEFAULT_OUT_DIR)
    parser.add_argument("--start", default="2011-01-01")
    parser.add_argument("--end", default=datetime.now().strftime("%Y-%m-%d"))
    args = parser.parse_args()

    events = broad.load_events(args.db_path, start=args.start, end=args.end)
    index_rows = fetch_kosdaq_index(args.start, args.end)
    markets = broad.build_markets(events, index_rows)
    result = evaluate_all(events, markets)
    index_bytes = json.dumps(
        broad.json_safe(index_rows), sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    payload = {
        "generated_at": datetime.now().astimezone().isoformat(),
        "database": str(Path(args.db_path)),
        "start": args.start,
        "end": args.end,
        **result,
        "database_fingerprint": candle_database_fingerprint(args.db_path),
        "source_fingerprints": {
            "kosdaq_index_sha256": hashlib.sha256(index_bytes).hexdigest(),
            "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "broad_strategy_sha256": hashlib.sha256(
                Path(__file__).with_name("kr_broad_strategy_research.py").read_bytes()
            ).hexdigest(),
        },
        "limits": [
            "Current surviving-symbol universe creates survivorship bias.",
            "Post-2024 results are reused diagnostic data, not an untouched holdout.",
            "No account, order, or live-trading API is called.",
        ],
    }
    output = Path(args.out_dir)
    output.mkdir(parents=True, exist_ok=True)
    (output / "kr_rank_sensitivity.json").write_text(
        json.dumps(broad.json_safe(payload), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (output / "kr_rank_sensitivity.md").write_text(
        render_markdown(payload), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "out_dir": str(output),
                "events": len(events),
                "market_days": len(markets),
                "ranks": list(RANKS),
                "accepted": [
                    row["rank"]
                    for row in payload["results"]
                    if row.get("decision", {}).get("accepted")
                ],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
