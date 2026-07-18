#!/usr/bin/env python3
"""Compare the validated KR gap strategy with a research-only US candidate."""
from __future__ import annotations

import argparse
import json
import math
import statistics
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

from current_strategy_risk_audit import grouped_by_date, scenarios
from kosdaq_sma5_gate_deep_dive import dates_for_slice, gate_rows, to_index_candles
from simple_gap_strategy_audit import fetch_kosdaq_index
from simple_gap_variant_core import simulate_day
from simple_gap_variant_data import load_candidates


DEFAULT_KR_DB = "data/edge_research_universe_15y.sqlite3"
DEFAULT_US_TRADES = "data/us_strategy_family_research/selected_harsh_trades.json"
DEFAULT_US_REPORT = "data/us_strategy_family_research/us_strategy_family_research.json"
DEFAULT_OUT_DIR = "data/kr_us_combined_research"


@dataclass(frozen=True, slots=True)
class SeriesMetrics:
    active_days: int
    total_additive_return: float
    compounded_return: float
    max_drawdown: float
    win_rate: float | None
    avg_active_day_return: float | None


def series_metrics(returns: dict[str, float]) -> SeriesMetrics:
    values = [returns[date] for date in sorted(returns)]
    if not values:
        return SeriesMetrics(0, 0.0, 0.0, 0.0, None, None)
    equity = 1.0
    peak = 1.0
    drawdown = 0.0
    for value in values:
        equity *= max(0.0, 1.0 + value)
        peak = max(peak, equity)
        drawdown = max(drawdown, (peak - equity) / peak if peak else 0.0)
    return SeriesMetrics(
        active_days=len(values),
        total_additive_return=sum(values),
        compounded_return=equity - 1.0,
        max_drawdown=drawdown,
        win_rate=sum(value > 0 for value in values) / len(values),
        avg_active_day_return=statistics.mean(values),
    )


def combine_equal_budget(kr: dict[str, float], us: dict[str, float]) -> dict[str, float]:
    return {date: 0.5 * kr.get(date, 0.0) + 0.5 * us.get(date, 0.0) for date in sorted(set(kr) | set(us))}


def combine_sequential_same_cash(kr: dict[str, float], us: dict[str, float]) -> dict[str, float]:
    return {
        date: (1.0 + kr.get(date, 0.0)) * (1.0 + us.get(date, 0.0)) - 1.0
        for date in sorted(set(kr) | set(us))
    }


def pearson(xs: Iterable[float], ys: Iterable[float]) -> float | None:
    left = list(xs)
    right = list(ys)
    if len(left) != len(right) or len(left) < 2:
        return None
    mean_left = statistics.mean(left)
    mean_right = statistics.mean(right)
    numerator = sum((x - mean_left) * (y - mean_right) for x, y in zip(left, right))
    denominator = math.sqrt(sum((x - mean_left) ** 2 for x in left) * sum((y - mean_right) ** 2 for y in right))
    return numerator / denominator if denominator else None


def correlation_payload(kr: dict[str, float], us: dict[str, float]) -> dict[str, float | int | None]:
    union = sorted(set(kr) | set(us))
    overlap = sorted(set(kr) & set(us))
    return {
        "union_active_dates": len(union),
        "overlap_dates": len(overlap),
        "overlap_share_of_union": len(overlap) / len(union) if union else 0.0,
        "zero_filled_union_correlation": pearson([kr.get(date, 0.0) for date in union], [us.get(date, 0.0) for date in union]),
        "same_day_signal_correlation": pearson([kr[date] for date in overlap], [us[date] for date in overlap]),
    }


def annual(returns: dict[str, float]) -> dict[str, dict[str, float | int | None]]:
    grouped: dict[str, dict[str, float]] = defaultdict(dict)
    for date, value in returns.items():
        grouped[date[:4]][date] = value
    return {year: asdict(series_metrics(rows)) for year, rows in sorted(grouped.items())}


def load_us_returns(path: str, *, start: str, end: str) -> dict[str, float]:
    rows = json.loads(Path(path).read_text(encoding="utf-8"))
    return {
        str(row["date"]): float(row["net_return"])
        for row in rows
        if start <= str(row.get("date") or "") <= end
    }


def load_kr_returns(db_path: str, *, start: str, end: str) -> dict[str, float]:
    candidates = load_candidates(db_path, start=start, end=end, broad_gap=-0.05)
    index_rows = to_index_candles(fetch_kosdaq_index(start, end))
    eligible_dates = dates_for_slice(gate_rows(index_rows), "live_buy_gate_1pct")
    scoped = [row for row in candidates if row.date in eligible_dates]
    config = next(item.config for item in scenarios() if item.name == "live_harsh_cost135")
    result: dict[str, float] = {}
    for date, rows in sorted(grouped_by_date(scoped).items()):
        day_return, trades = simulate_day(rows, config)
        if trades:
            result[date] = float(day_return)
    return result


def markdown(payload: dict) -> str:
    lines = [
        "# KR + US Strategy Combination Research",
        "",
        f"- generated_at: `{payload['generated_at']}`",
        f"- window: `{payload['start']}` to `{payload['end']}`",
        f"- US live candidate accepted: `{payload['us_live_candidate_accepted']}`",
        "- KR profile: current robust_gap5 strategy with harsh 1.35% total cost.",
        "- US profile: selected US candidate with harsh 2.0% round-trip execution cost.",
        "- equal budget: separate KRW 10,000 and approximately USD 7 budgets, measured as a two-sleeve portfolio.",
        "- sequential same cash: counterfactual only; settlement and FX funding can make immediate reuse impossible.",
        "",
        "| series | active days | additive | compounded | MDD | win |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for name, block in payload["series"].items():
        m = block["metrics"]
        lines.append(
            f"| {name} | {m['active_days']} | {m['total_additive_return'] * 100:.1f}% | "
            f"{m['compounded_return'] * 100:.1f}% | {m['max_drawdown'] * 100:.1f}% | "
            f"{((m['win_rate'] or 0) * 100):.1f}% |"
        )
    lines += ["", "## Signal overlap", ""]
    for key, value in payload["correlation"].items():
        lines.append(f"- {key}: `{value}`")
    lines += [
        "",
        "## Operational interpretation",
        "",
        "- Diversification is useful only if the US held-out and paper-forward edge remains positive after opening slippage.",
        "- Repeated KRW/USD conversion should not be hidden inside the strategy. Keep the experimental US sleeve funded in USD.",
        "- The sequential same-cash curve must not be used for live sizing without confirming settlement and buying power from Toss.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare KR and research-only US strategy return streams")
    parser.add_argument("--kr-db", default=DEFAULT_KR_DB)
    parser.add_argument("--us-trades", default=DEFAULT_US_TRADES)
    parser.add_argument("--us-report", default=DEFAULT_US_REPORT)
    parser.add_argument("--out-dir", default=DEFAULT_OUT_DIR)
    parser.add_argument("--start", default="2021-01-01")
    parser.add_argument("--end", default="2026-12-31")
    args = parser.parse_args()

    us_report = json.loads(Path(args.us_report).read_text(encoding="utf-8"))
    us_live_candidate_accepted = bool(us_report.get("final_live_candidate_accepted"))

    kr = load_kr_returns(args.kr_db, start=args.start, end=args.end)
    us = load_us_returns(args.us_trades, start=args.start, end=args.end)
    equal = combine_equal_budget(kr, us)
    sequential = combine_sequential_same_cash(kr, us)
    series = {
        "kr_only": kr,
        "us_only": us,
        "equal_budget_separate_sleeves": equal,
        "sequential_same_cash_counterfactual": sequential,
    }
    payload = {
        "generated_at": datetime.now().astimezone().isoformat(),
        "start": args.start,
        "end": args.end,
        "us_live_candidate_accepted": us_live_candidate_accepted,
        "series": {
            name: {"metrics": asdict(series_metrics(values)), "annual": annual(values)}
            for name, values in series.items()
        },
        "correlation": correlation_payload(kr, us),
        "limits": [
            "US current-universe survivorship and selection bias",
            "US series is diagnostic and must not be deployed when us_live_candidate_accepted is false",
            "daily OHLC opening-fill approximation",
            "sequential same-cash scenario ignores settlement and FX conversion timing",
        ],
    }
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "kr_us_combined.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out_dir / "kr_us_combined.md").write_text(markdown(payload), encoding="utf-8")
    print(json.dumps({"out_dir": str(out_dir), "us_live_candidate_accepted": us_live_candidate_accepted, "series": {name: block["metrics"] for name, block in payload["series"].items()}, "correlation": payload["correlation"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
