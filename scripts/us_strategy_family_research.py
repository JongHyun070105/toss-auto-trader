#!/usr/bin/env python3
"""Compare US gap strategy families using cached Toss daily candles only.

The script is research-only. It never imports the Toss client and never calls
account or order endpoints. Configurations are selected on 2011-2023 data;
2024+ remains untouched until the final evaluation.
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
from collections import defaultdict
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence

import us_gap_strategy_research as gap


@dataclass(frozen=True, slots=True)
class Event:
    date: str
    symbol: str
    open: float
    close: float
    gap: float
    prev_vol_ratio: float
    avg_dollar_volume20: float
    spy_open_vs_sma5: float | None
    qqq_open_vs_sma5: float | None
    future: tuple[tuple[str, float, float], ...]


@dataclass(frozen=True, slots=True)
class FamilyConfig:
    name: str
    direction: str
    entry_timing: str
    exit_timing: str
    hold_days: int
    gap_threshold: float
    extreme_cap: float | None
    prev_vol_ratio_max: float
    min_dollar_volume: float
    rank: str
    market_proxy: str | None
    market_gate: float | None
    roundtrip_cost: float


@dataclass(frozen=True, slots=True)
class FamilyTrade:
    date: str
    signal_date: str
    exit_date: str
    symbol: str
    entry: float
    exit: float
    reason: str
    gap: float
    prev_vol_ratio: float
    avg_dollar_volume20: float
    market_proxy: str | None
    market_open_vs_sma5: float | None
    gross_return: float
    net_return: float
    net_pnl_usd: float
    both_stop_take: bool


def build_events(
    candles_by_symbol: dict[str, list[gap.Candle]],
    markets: dict[str, dict[str, float]],
) -> list[Event]:
    events: list[Event] = []
    for symbol, candles in candles_by_symbol.items():
        if symbol in {"SPY", "QQQ", "IWM"}:
            continue
        for index in range(21, len(candles)):
            row = candles[index]
            previous = candles[index - 1]
            history = candles[index - 21 : index - 1]
            if len(history) != 20 or previous.close <= 0:
                continue
            avg_volume = statistics.mean(item.volume for item in history)
            avg_dollar_volume = statistics.mean(
                item.close * item.volume for item in candles[index - 20 : index]
            )
            if avg_volume <= 0 or avg_dollar_volume <= 0:
                continue
            gap_return = row.open / previous.close - 1.0
            if abs(gap_return) < 0.03:
                continue
            future = tuple(
                (item.date, item.open, item.close)
                for item in candles[index + 1 : index + 6]
            )
            events.append(
                Event(
                    date=row.date,
                    symbol=symbol,
                    open=row.open,
                    close=row.close,
                    gap=gap_return,
                    prev_vol_ratio=previous.volume / avg_volume,
                    avg_dollar_volume20=avg_dollar_volume,
                    spy_open_vs_sma5=markets.get("SPY", {}).get(row.date),
                    qqq_open_vs_sma5=markets.get("QQQ", {}).get(row.date),
                    future=future,
                )
            )
    return events


def market_value(event: Event, proxy: str | None) -> float | None:
    return {
        "SPY": event.spy_open_vs_sma5,
        "QQQ": event.qqq_open_vs_sma5,
    }.get(proxy)


def passes(event: Event, config: FamilyConfig) -> bool:
    magnitude = abs(event.gap)
    direction_ok = event.gap <= -config.gap_threshold if config.direction == "down" else event.gap >= config.gap_threshold
    value = market_value(event, config.market_proxy)
    if config.market_gate is None:
        market_ok = True
    elif value is None:
        market_ok = False
    elif config.direction == "down":
        market_ok = value <= config.market_gate
    else:
        market_ok = value >= config.market_gate
    return (
        direction_ok
        and (config.extreme_cap is None or magnitude <= config.extreme_cap)
        and event.prev_vol_ratio < config.prev_vol_ratio_max
        and event.avg_dollar_volume20 >= config.min_dollar_volume
        and market_ok
        and len(event.future) >= config.hold_days
    )


def rank_key(event: Event, rank: str) -> tuple[float, str]:
    if rank == "highest_liquidity":
        return -event.avg_dollar_volume20, event.symbol
    if rank == "mildest_gap":
        return abs(event.gap), event.symbol
    raise ValueError(f"unknown rank: {rank}")


def entry_exit(event: Event, config: FamilyConfig) -> tuple[float, float, str]:
    entry = event.open if config.entry_timing == "open" else event.close
    if config.exit_timing == "close" and config.hold_days == 0:
        return entry, event.close, event.date
    date, next_open, future_close = event.future[config.hold_days - 1]
    exit_price = next_open if config.exit_timing == "open" else future_close
    return entry, exit_price, date


def simulate(events: Sequence[Event], config: FamilyConfig, *, start: str, end: str) -> list[FamilyTrade]:
    grouped: dict[str, list[Event]] = defaultdict(list)
    for event in events:
        if start <= event.date <= end and passes(event, config):
            grouped[event.date].append(event)
    trades: list[FamilyTrade] = []
    unavailable_through = ""
    for date in sorted(grouped):
        if date <= unavailable_through:
            continue
        event = min(grouped[date], key=lambda row: rank_key(row, config.rank))
        entry, exit_price, exit_date = entry_exit(event, config)
        gross_return = exit_price / entry - 1.0
        net_return = gross_return - config.roundtrip_cost
        trades.append(
            FamilyTrade(
                date=exit_date,
                signal_date=date,
                exit_date=exit_date,
                symbol=event.symbol,
                entry=entry,
                exit=exit_price,
                reason=f"{config.entry_timing}_to_{config.hold_days}d_{config.exit_timing}",
                gap=event.gap,
                prev_vol_ratio=event.prev_vol_ratio,
                avg_dollar_volume20=event.avg_dollar_volume20,
                market_proxy=config.market_proxy,
                market_open_vs_sma5=market_value(event, config.market_proxy),
                gross_return=gross_return,
                net_return=net_return,
                net_pnl_usd=gap.CAPITAL_USD * net_return,
                both_stop_take=False,
            )
        )
        unavailable_through = exit_date
    return trades


def family_specs() -> list[tuple[str, str, str, int]]:
    return [
        ("down", "open", "close", 0),
        ("down", "close", "open", 1),
        ("down", "open", "close", 1),
        ("down", "open", "close", 3),
        ("down", "open", "close", 5),
        ("up", "open", "close", 0),
        ("up", "open", "close", 1),
        ("up", "open", "close", 3),
        ("up", "open", "close", 5),
    ]


def config_grid() -> list[FamilyConfig]:
    result: list[FamilyConfig] = []
    for direction, entry, exit_, hold in family_specs():
        market_options = [(None, None), ("SPY", -0.01 if direction == "down" else 0.01), ("QQQ", -0.01 if direction == "down" else 0.01)]
        for threshold in (0.03, 0.05, 0.07):
            for extreme_cap in (0.15, None):
                for volume_max in (0.8, 99.0):
                    for dollar_volume in (25_000_000.0, 100_000_000.0):
                        for rank in ("highest_liquidity", "mildest_gap"):
                            for proxy, gate_value in market_options:
                                name = (
                                    f"{direction}_{entry}_to_{hold}d_{exit_}_gap{threshold}_cap{extreme_cap}_"
                                    f"vol{volume_max}_dv{int(dollar_volume)}_{rank}_{proxy}_gate{gate_value}"
                                )
                                result.append(
                                    FamilyConfig(
                                        name, direction, entry, exit_, hold, threshold, extreme_cap,
                                        volume_max, dollar_volume, rank, proxy, gate_value, 0.01,
                                    )
                                )
    return result


def score(train: gap.Metrics, validation: gap.Metrics) -> float:
    if (
        train.trades < 30
        or validation.trades < 12
        or train.total_pnl_usd <= 0
        or validation.total_pnl_usd <= 0
        or train.profit_factor is None
        or validation.profit_factor is None
    ):
        return -math.inf
    pf_floor = min(float(train.profit_factor), float(validation.profit_factor), 5.0)
    return pf_floor * math.log1p(min(train.trades, validation.trades)) - 0.25 * (
        train.mdd_on_capital + validation.mdd_on_capital
    )


def diagnostic_score(train: gap.Metrics, validation: gap.Metrics) -> float:
    pf_floor = min(float(train.profit_factor or 0.0), float(validation.profit_factor or 0.0), 5.0)
    return pf_floor * math.log1p(min(train.trades, validation.trades)) + float(train.total_pnl_usd > 0) + float(validation.total_pnl_usd > 0)


def evaluate_window(events: Sequence[Event], config: FamilyConfig, start: str, end: str) -> dict[str, Any]:
    trades = simulate(events, config, start=start, end=end)
    return {
        "metrics": asdict(gap.metrics(trades)),
        "annual": gap.annual_metrics(trades),
        "miss_top_winners_25pct": asdict(gap.missed_winner_metrics(trades, 0.25)),
    }


def profile(config: FamilyConfig, name: str) -> FamilyConfig:
    return replace(config, name=f"{config.name}_{name}", roundtrip_cost={"base": 0.004, "mid": 0.01, "harsh": 0.02}[name])


def search(events: Sequence[Event]) -> tuple[FamilyConfig, bool, list[dict[str, Any]]]:
    rows: list[tuple[float, float, FamilyConfig, gap.Metrics, gap.Metrics]] = []
    for config in config_grid():
        train = gap.metrics(simulate(events, config, start="2011-01-01", end="2020-12-31"))
        validation = gap.metrics(simulate(events, config, start="2021-01-01", end="2023-12-31"))
        strict = score(train, validation)
        rows.append((strict, diagnostic_score(train, validation), config, train, validation))
    rows.sort(key=lambda row: (math.isfinite(row[0]), row[0] if math.isfinite(row[0]) else row[1]), reverse=True)
    top = [
        {
            "passed": math.isfinite(strict),
            "score": strict if math.isfinite(strict) else diagnostic,
            "config": asdict(config),
            "train": asdict(train),
            "validation": asdict(validation),
        }
        for strict, diagnostic, config, train, validation in rows[:100]
    ]
    return rows[0][2], math.isfinite(rows[0][0]), top


def holdout_diagnostics(events: Sequence[Event], search_top: Sequence[dict[str, Any]]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for item in search_top:
        config = FamilyConfig(**item["config"])
        harsh = profile(config, "harsh")
        test_trades = simulate(events, harsh, start="2024-01-01", end="2026-12-31")
        recent_trades = simulate(events, harsh, start="2025-01-01", end="2026-12-31")
        test = gap.metrics(test_trades)
        recent = gap.metrics(recent_trades)
        miss_winners = gap.missed_winner_metrics(test_trades, 0.25)
        rows.append({
            "passed_pretest_evidence_gate": bool(item["passed"]),
            "config": asdict(config),
            "test": asdict(test),
            "recent": asdict(recent),
            "miss_top_winners_25pct": asdict(miss_winners),
        })
    robust = [
        row for row in rows
        if row["passed_pretest_evidence_gate"]
        and row["test"]["total_pnl_usd"] > 0
        and (row["test"]["profit_factor"] or 0) > 1
        and row["recent"]["total_pnl_usd"] > 0
        and row["miss_top_winners_25pct"]["total_pnl_usd"] > 0
    ]
    eligible = [row for row in rows if row["passed_pretest_evidence_gate"]]
    best = max(eligible, key=lambda row: row["test"]["total_pnl_usd"], default=None)
    return {
        "evaluated_preselected_configs": len(rows),
        "passed_pretest_evidence_gate": len(eligible),
        "positive_test_pnl": sum(row["test"]["total_pnl_usd"] > 0 for row in rows),
        "positive_recent_pnl": sum(row["recent"]["total_pnl_usd"] > 0 for row in rows),
        "robust_after_cost_and_missed_winner_checks": len(robust),
        "best_test_result_is_diagnostic_not_selectable": best,
    }


def markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# US Strategy Family Research",
        "",
        f"- selection accepted: `{payload['selection_accepted']}`",
        f"- final live candidate accepted: `{payload['final_live_candidate_accepted']}`",
        f"- events: `{payload['event_rows']}` / configurations: `{payload['configurations']}`",
        "- selection: 2011-2020 train + 2021-2023 validation; 2024+ untouched test.",
        "- capital: one $7 position; overlapping signals are skipped until the prior exit.",
        "- costs: base 0.4%, mid 1.0%, harsh 2.0% round trip.",
        "- close entries are an optimistic close-price proxy and require paper-forward execution validation.",
        "",
        "## Selected configuration",
        "",
        f"```json\n{json.dumps(payload['selected_config'], ensure_ascii=False, indent=2)}\n```",
        "",
        "## Results",
        "",
    ]
    for profile_name, evaluation in payload["evaluations"].items():
        lines.append(f"### {profile_name}")
        for window, block in evaluation.items():
            m = block["metrics"]
            pf = "n/a" if m["profit_factor"] is None else f"{m['profit_factor']:.3f}"
            lines.append(
                f"- {window}: trades={m['trades']} pnl=${m['total_pnl_usd']:.2f} "
                f"PF={pf} MDD={m['mdd_on_capital'] * 100:.1f}% win={((m['win_rate'] or 0) * 100):.1f}%"
            )
        lines.append("")
    diagnostics = payload["holdout_diagnostics"]
    lines += [
        "## Holdout diagnostics",
        "",
        f"- preselected configs evaluated: `{diagnostics['evaluated_preselected_configs']}`",
        f"- passed train/validation evidence gate: `{diagnostics['passed_pretest_evidence_gate']}`",
        f"- positive 2024+ harsh PnL: `{diagnostics['positive_test_pnl']}`",
        f"- positive 2025+ harsh PnL: `{diagnostics['positive_recent_pnl']}`",
        f"- passed cost + recent + missed-winner checks: `{diagnostics['robust_after_cost_and_missed_winner_checks']}`",
        "- The best holdout row is diagnostic only; selecting it after viewing 2024+ would contaminate the test set.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Research-only US strategy-family comparison")
    parser.add_argument("--db-path", default=gap.DEFAULT_DB)
    parser.add_argument("--universe", default=gap.DEFAULT_UNIVERSE)
    parser.add_argument("--out-dir", default="data/us_strategy_family_research")
    parser.add_argument("--start", default="2011-01-01")
    parser.add_argument("--end", default="2026-12-31")
    args = parser.parse_args()

    symbols = gap.load_universe(args.universe)
    candles = gap.load_candles(args.db_path, ["SPY", "QQQ", "IWM", *symbols], start=args.start, end=args.end)
    markets = {symbol: gap.market_gate_map(candles[symbol]) for symbol in ("SPY", "QQQ") if symbol in candles}
    events = build_events(candles, markets)
    selected, accepted, search_top = search(events)
    diagnostics = holdout_diagnostics(events, search_top)
    windows = {
        "train_2011_2020": ("2011-01-01", "2020-12-31"),
        "validation_2021_2023": ("2021-01-01", "2023-12-31"),
        "test_2024_2026": ("2024-01-01", "2026-12-31"),
        "recent_2025_2026": ("2025-01-01", "2026-12-31"),
        "full_2011_2026": ("2011-01-01", "2026-12-31"),
    }
    evaluations = {
        profile_name: {
            window: evaluate_window(events, profile(selected, profile_name), *bounds)
            for window, bounds in windows.items()
        }
        for profile_name in ("base", "mid", "harsh")
    }
    selected_test = evaluations["harsh"]["test_2024_2026"]
    selected_recent = evaluations["harsh"]["recent_2025_2026"]
    final_live_candidate_accepted = bool(
        accepted
        and selected_test["metrics"]["total_pnl_usd"] > 0
        and (selected_test["metrics"]["profit_factor"] or 0) > 1
        and selected_recent["metrics"]["total_pnl_usd"] > 0
        and selected_test["miss_top_winners_25pct"]["total_pnl_usd"] > 0
    )
    payload = {
        "generated_at": datetime.now().astimezone().isoformat(),
        "event_rows": len(events),
        "configurations": len(config_grid()),
        "selection_accepted": accepted,
        "final_live_candidate_accepted": final_live_candidate_accepted,
        "selected_config": asdict(selected),
        "search_top100": search_top,
        "holdout_diagnostics": diagnostics,
        "evaluations": evaluations,
        "limits": [
            "current liquid universe has survivorship and current-selection bias",
            "daily OHLC cannot reproduce exact regular-session fills",
            "close-entry families use an optimistic closing-price proxy",
            "historical news, earnings, halts, and point-in-time warning flags are unavailable",
            "results are USD-only and exclude KRW translation",
        ],
    }
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "us_strategy_family_research.json").write_text(
        json.dumps(gap.json_safe(payload), ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    (out_dir / "us_strategy_family_research.md").write_text(markdown(payload), encoding="utf-8")
    harsh_trades = simulate(events, profile(selected, "harsh"), start="2011-01-01", end="2026-12-31")
    (out_dir / "selected_harsh_trades.json").write_text(
        json.dumps([asdict(row) for row in harsh_trades], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "out_dir": str(out_dir),
        "events": len(events),
        "configs": len(config_grid()),
        "accepted": accepted,
        "final_live_candidate_accepted": final_live_candidate_accepted,
        "selected": asdict(selected),
        "test_harsh": evaluations["harsh"]["test_2024_2026"]["metrics"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
