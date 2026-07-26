#!/usr/bin/env python3
"""Compare fixed raw-gap floors without touching live trading or order APIs."""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence

from kr_broad_strategy_research import (
    Event,
    Market,
    Trade,
    anchor_config,
    build_markets,
    json_safe,
    load_events,
    passes,
    profile,
    scoped,
    simulate,
)
from kr_gap_integrity_audit import changed_trade_days, window_payload
from simple_gap_strategy_audit import fetch_kosdaq_index
from toss_auto_trader.gap_integrity import MIN_RAW_ENTRY_GAP
from toss_auto_trader.research_fingerprint import candle_database_fingerprint


DEFAULT_DB = "data/edge_research_universe_15y.sqlite3"
DEFAULT_OUT_DIR = "data/kr_gap_floor_sensitivity"
FIXED_GAP_FLOORS: tuple[float | None, ...] = (
    None,
    MIN_RAW_ENTRY_GAP,
    -0.30,
    -0.25,
    -0.20,
    -0.15,
    -0.12,
    -0.10,
    -0.08,
)
REQUIRED_WINDOWS = (
    "train_2011_2018",
    "validation_2019_2023",
    "test_pre_nxt_2024_20250303",
    "post_nxt_20250304_2026",
)
GAP_DISTRIBUTION_THRESHOLDS = (-0.08, -0.10, -0.12, -0.15, -0.20, -0.25, -0.30)
SELECTED_GAP_BUCKETS: tuple[tuple[str, float | None, float], ...] = (
    ("5_to_8pct", -0.08, -0.05),
    ("8_to_10pct", -0.10, -0.08),
    ("10_to_12pct", -0.12, -0.10),
    ("12_to_15pct", -0.15, -0.12),
    ("15_to_20pct", -0.20, -0.15),
    ("20_to_25pct", -0.25, -0.20),
    ("25_to_30pct", -0.30, -0.25),
    ("30pct_or_more", None, -0.30),
)


def floor_label(floor: float | None) -> str:
    if floor is None:
        return "unbounded_old_rule"
    return f"floor_{abs(floor) * 100:g}pct"


def nearest_rank(values: Sequence[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = round((len(ordered) - 1) * quantile)
    return ordered[index]


def selected_gap_distribution(trades: Sequence[Trade]) -> dict[str, Any]:
    values = [trade.gap for trade in trades]
    total = len(values)
    thresholds = {}
    for threshold in GAP_DISTRIBUTION_THRESHOLDS:
        count = sum(value <= threshold for value in values)
        thresholds[f"at_or_below_{abs(threshold) * 100:g}pct"] = {
            "count": count,
            "share": count / total if total else 0.0,
        }
    return {
        "trades": total,
        "minimum": min(values) if values else None,
        "p05": nearest_rank(values, 0.05),
        "p25": nearest_rank(values, 0.25),
        "median": nearest_rank(values, 0.50),
        "thresholds": thresholds,
    }


def gap_bucket_label(gap: float) -> str | None:
    for label, lower, upper in SELECTED_GAP_BUCKETS:
        if gap <= upper and (lower is None or gap > lower):
            return label
    return None


def selected_gap_bucket_payload(
    harsh_trades: Sequence[Trade], extreme_trades: Sequence[Trade]
) -> list[dict[str, Any]]:
    rows = []
    for label, lower, upper in SELECTED_GAP_BUCKETS:
        cost_payload = {}
        for cost_name, trades in (
            ("harsh", harsh_trades),
            ("extreme", extreme_trades),
        ):
            selected = [trade for trade in trades if gap_bucket_label(trade.gap) == label]
            windows = window_payload(selected)
            cost_payload[cost_name] = {
                "full": windows["full"],
                "post_nxt_20250304_2026": windows["post_nxt_20250304_2026"],
            }
        rows.append(
            {
                "label": label,
                "lower_exclusive": lower,
                "upper_inclusive": upper,
                **cost_payload,
            }
        )
    return rows


def eligible_event_count(
    events: Sequence[Event], markets: dict[str, Market], floor: float | None
) -> int:
    config = replace(anchor_config(), gap_min=floor)
    return sum(
        market is not None and passes(event, market, config)
        for event in events
        if (market := markets.get(event.date)) is not None
    )


def evaluate_database(
    events: Sequence[Event],
    markets: dict[str, Market],
    *,
    database: str,
) -> dict[str, Any]:
    config = anchor_config()
    trades_by_floor: dict[float | None, dict[str, list[Trade]]] = {}
    for floor in FIXED_GAP_FLOORS:
        floor_config = replace(
            config,
            name=f"{config.name}_{floor_label(floor)}",
            gap_min=floor,
        )
        trades_by_floor[floor] = {
            cost_name: simulate(events, markets, profile(floor_config, cost_name))
            for cost_name in ("harsh", "extreme")
        }

    baseline_harsh = trades_by_floor[None]["harsh"]
    rows = []
    for floor in FIXED_GAP_FLOORS:
        harsh = trades_by_floor[floor]["harsh"]
        extreme = trades_by_floor[floor]["extreme"]
        changed = changed_trade_days(baseline_harsh, harsh)
        harsh_windows = window_payload(harsh)
        extreme_windows = window_payload(extreme)
        rows.append(
            {
                "floor": floor,
                "label": floor_label(floor),
                "eligible_event_count": eligible_event_count(events, markets, floor),
                "changed_days_vs_old_rule": len(changed),
                "changed_days_post_nxt": sum(
                    row["date"] >= "2025-03-04" for row in changed
                ),
                "changed_days": changed,
                "selected_gap_distribution": selected_gap_distribution(harsh),
                "harsh": harsh_windows,
                "extreme": extreme_windows,
                "all_required_harsh_windows_positive": all(
                    harsh_windows[name]["metrics"]["total_pnl"] > 0
                    for name in REQUIRED_WINDOWS
                ),
                "all_required_extreme_windows_positive": all(
                    extreme_windows[name]["metrics"]["total_pnl"] > 0
                    for name in REQUIRED_WINDOWS
                ),
            }
        )
    return {
        "database": database,
        "event_rows": len(events),
        "event_date_min": min((event.date for event in events), default=None),
        "event_date_max": max((event.date for event in events), default=None),
        "old_rule": "gap <= -5%, no lower bound",
        "live_integrity_floor": MIN_RAW_ENTRY_GAP,
        "old_rule_selected_gap_buckets": selected_gap_bucket_payload(
            trades_by_floor[None]["harsh"], trades_by_floor[None]["extreme"]
        ),
        "floor_results": rows,
    }


def render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# KR Gap Floor Sensitivity",
        "",
        f"- generated: `{payload['generated_at']}`",
        "- old rule: `gap <= -5%`, no lower bound",
        f"- current integrity floor: `{payload['live_integrity_floor']:.0%}`",
        "- fixed floors are diagnostics, not a return-optimized selection grid",
        "",
    ]
    lines.extend(["## Frozen inputs", ""])
    for database in payload["databases"]:
        fingerprint = database["database_fingerprint"]
        lines.append(
            f"- `{Path(database['database']).name}`: "
            f"sha256 `{fingerprint['full_sha256']}`, "
            f"size `{fingerprint['size_bytes']}`, latest `{fingerprint['latest_date']}`"
        )
    lines.extend(
        [
            f"- KOSDAQ index sha256: `{payload['source_fingerprints']['kosdaq_index_sha256']}`",
            f"- script sha256: `{payload['source_fingerprints']['script_sha256']}`",
            "",
        ]
    )
    lines.extend(
        [
            "## Harsh-cost comparison",
            "",
            "| database | floor | full trades | full pnl | PF | MDD/10k | post-NXT trades | post-NXT pnl | PF | changed days | post-NXT changed |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for database in payload["databases"]:
        db_name = Path(database["database"]).name
        for row in database["floor_results"]:
            full = row["harsh"]["full"]["metrics"]
            post = row["harsh"]["post_nxt_20250304_2026"]["metrics"]
            floor = "none" if row["floor"] is None else f"{row['floor']:.0%}"
            lines.append(
                f"| {db_name} | {floor} | {full['trades']} | "
                f"{full['total_pnl']:,.0f} | {full['profit_factor']:.2f} | "
                f"{full['mdd_on_capital'] * 100:.1f}% | {post['trades']} | "
                f"{post['total_pnl']:,.0f} | {post['profit_factor']:.2f} | "
                f"{row['changed_days_vs_old_rule']} | {row['changed_days_post_nxt']} |"
            )

    lines.extend(["", "## Old-rule selected-gap distribution", ""])
    for database in payload["databases"]:
        baseline = database["floor_results"][0]["selected_gap_distribution"]
        threshold = baseline["thresholds"]
        lines.append(
            f"- `{Path(database['database']).name}`: min "
            f"{baseline['minimum']:.2%}, p05 {baseline['p05']:.2%}, "
            f"median {baseline['median']:.2%}; "
            f"<=-10% {threshold['at_or_below_10pct']['count']}, "
            f"<=-15% {threshold['at_or_below_15pct']['count']}, "
            f"<=-20% {threshold['at_or_below_20pct']['count']}, "
            f"<=-30% {threshold['at_or_below_30pct']['count']}"
        )

    lines.extend(
        [
            "",
            "## Old-rule selected-gap bucket performance",
            "",
            "| database | selected gap | harsh trades | harsh pnl | PF | MDD/10k | post-NXT trades | post-NXT pnl | extreme pnl |",
            "|---|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for database in payload["databases"]:
        db_name = Path(database["database"]).name
        for row in database["old_rule_selected_gap_buckets"]:
            harsh = row["harsh"]["full"]["metrics"]
            post = row["harsh"]["post_nxt_20250304_2026"]["metrics"]
            extreme = row["extreme"]["full"]["metrics"]
            pf = harsh["profit_factor"]
            lines.append(
                f"| {db_name} | {row['label']} | {harsh['trades']} | "
                f"{harsh['total_pnl']:,.0f} | "
                f"{'n/a' if pf is None else f'{pf:.2f}'} | "
                f"{harsh['mdd_on_capital'] * 100:.1f}% | {post['trades']} | "
                f"{post['total_pnl']:,.0f} | {extreme['total_pnl']:,.0f} |"
            )

    lines.extend(
        [
            "",
            "## Interpretation boundary",
            "",
            "- Adding any floor narrows the old unbounded `<= -5%` rule; it does not widen it.",
            "- The -31% floor is tied to KRX comparable-base integrity, not historical return maximization.",
            "- Floors tighter than -31% are strategy filters and require unseen or paper-forward validation before live use.",
            "- Daily OHLC cannot establish 09:01 queue position, VI state, or actual fill probability.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="No-order fixed gap-floor sensitivity backtest"
    )
    parser.add_argument("--db-path", action="append", default=[])
    parser.add_argument("--out-dir", default=DEFAULT_OUT_DIR)
    parser.add_argument("--start", default="2011-01-01")
    parser.add_argument("--end", default=datetime.now().strftime("%Y-%m-%d"))
    args = parser.parse_args()

    db_paths = args.db_path or [DEFAULT_DB]
    index_rows = fetch_kosdaq_index(args.start, args.end)
    databases = []
    for db_path in db_paths:
        events = load_events(db_path, start=args.start, end=args.end)
        markets = build_markets(events, index_rows)
        database_payload = evaluate_database(
            events, markets, database=str(Path(db_path))
        )
        database_payload["database_fingerprint"] = candle_database_fingerprint(
            db_path
        )
        databases.append(database_payload)

    index_bytes = json.dumps(
        json_safe(index_rows), sort_keys=True, separators=(",", ":")
    ).encode("utf-8")

    payload = {
        "generated_at": datetime.now().astimezone().isoformat(),
        "start": args.start,
        "end": args.end,
        "fixed_gap_floors": list(FIXED_GAP_FLOORS),
        "live_integrity_floor": MIN_RAW_ENTRY_GAP,
        "source_fingerprints": {
            "kosdaq_index_sha256": hashlib.sha256(index_bytes).hexdigest(),
            "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "dependency_script_sha256": {
                name: hashlib.sha256(path.read_bytes()).hexdigest()
                for name, path in {
                    "kr_broad_strategy_research.py": Path(__file__).with_name(
                        "kr_broad_strategy_research.py"
                    ),
                    "kr_gap_integrity_audit.py": Path(__file__).with_name(
                        "kr_gap_integrity_audit.py"
                    ),
                    "gap_integrity.py": Path(__file__).resolve().parents[1]
                    / "src"
                    / "toss_auto_trader"
                    / "gap_integrity.py",
                }.items()
            },
        },
        "databases": databases,
        "limits": [
            "The fixed floor list was declared before reading this run's results.",
            "Post-2024 data is reused diagnostic data, not an untouched holdout.",
            "The output cannot approve a tighter live strategy floor.",
        ],
    }
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "kr_gap_floor_sensitivity.json").write_text(
        json.dumps(json_safe(payload), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (out_dir / "kr_gap_floor_sensitivity.md").write_text(
        render_markdown(payload), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "out_dir": str(out_dir),
                "fixed_gap_floors": list(FIXED_GAP_FLOORS),
                "databases": [
                    {
                        "database": row["database"],
                        "event_rows": row["event_rows"],
                        "event_date_max": row["event_date_max"],
                    }
                    for row in databases
                ],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
