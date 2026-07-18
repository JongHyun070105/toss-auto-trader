#!/usr/bin/env python3
"""Research liquid US index-ETF pullback strategies without order side effects."""
from __future__ import annotations

import argparse
import json
import math
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence

import us_gap_strategy_research as gap
from us_strategy_family_research import FamilyTrade


@dataclass(frozen=True, slots=True)
class EtfEvent:
    date: str
    symbol: str
    open: float
    close: float
    open_vs_sma5: float
    prev_return: float
    gap: float
    future: tuple[tuple[str, float], ...]


@dataclass(frozen=True, slots=True)
class EtfConfig:
    name: str
    symbol: str
    open_vs_sma5_max: float
    prev_return_max: float
    gap_max: float
    hold_days: int
    roundtrip_cost: float


def build_events(candles_by_symbol: dict[str, list[gap.Candle]]) -> list[EtfEvent]:
    result: list[EtfEvent] = []
    for symbol in ("SPY", "QQQ", "IWM"):
        candles = candles_by_symbol.get(symbol, [])
        gates = gap.market_gate_map(candles)
        for index in range(5, len(candles)):
            row = candles[index]
            previous = candles[index - 1]
            if previous.close <= 0 or candles[index - 2].close <= 0:
                continue
            result.append(EtfEvent(
                date=row.date,
                symbol=symbol,
                open=row.open,
                close=row.close,
                open_vs_sma5=gates[row.date],
                prev_return=previous.close / candles[index - 2].close - 1.0,
                gap=row.open / previous.close - 1.0,
                future=tuple((item.date, item.close) for item in candles[index + 1 : index + 6]),
            ))
    return result


def passes(event: EtfEvent, config: EtfConfig) -> bool:
    return (
        event.symbol == config.symbol
        and event.open_vs_sma5 <= config.open_vs_sma5_max
        and event.prev_return <= config.prev_return_max
        and event.gap <= config.gap_max
        and len(event.future) >= config.hold_days
    )


def simulate(events: Sequence[EtfEvent], config: EtfConfig, *, start: str, end: str) -> list[FamilyTrade]:
    trades: list[FamilyTrade] = []
    unavailable_through = ""
    for event in events:
        if not (start <= event.date <= end) or event.date <= unavailable_through or not passes(event, config):
            continue
        if config.hold_days == 0:
            exit_date, exit_price = event.date, event.close
        else:
            exit_date, exit_price = event.future[config.hold_days - 1]
        gross_return = exit_price / event.open - 1.0
        net_return = gross_return - config.roundtrip_cost
        trades.append(FamilyTrade(
            date=exit_date,
            signal_date=event.date,
            exit_date=exit_date,
            symbol=event.symbol,
            entry=event.open,
            exit=exit_price,
            reason=f"open_to_{config.hold_days}d_close",
            gap=event.gap,
            prev_vol_ratio=0.0,
            avg_dollar_volume20=0.0,
            market_proxy=event.symbol,
            market_open_vs_sma5=event.open_vs_sma5,
            gross_return=gross_return,
            net_return=net_return,
            net_pnl_usd=gap.CAPITAL_USD * net_return,
            both_stop_take=False,
        ))
        unavailable_through = exit_date
    return trades


def grid() -> list[EtfConfig]:
    result: list[EtfConfig] = []
    for symbol in ("SPY", "QQQ", "IWM"):
        for sma_max in (0.0, -0.01, -0.02, -0.03):
            for prev_max in (0.01, 0.0, -0.01, -0.02):
                for gap_max in (0.01, 0.0, -0.01, -0.02):
                    for hold in (0, 1, 3, 5):
                        name = f"{symbol}_sma{sma_max}_prev{prev_max}_gap{gap_max}_{hold}d"
                        result.append(EtfConfig(name, symbol, sma_max, prev_max, gap_max, hold, 0.01))
    return result


def profile(config: EtfConfig, name: str) -> EtfConfig:
    return replace(config, name=f"{config.name}_{name}", roundtrip_cost={"base": 0.004, "mid": 0.01, "harsh": 0.02}[name])


def score(train: gap.Metrics, validation: gap.Metrics) -> float:
    if (
        train.trades < 50 or validation.trades < 20
        or train.total_pnl_usd <= 0 or validation.total_pnl_usd <= 0
        or train.profit_factor is None or validation.profit_factor is None
    ):
        return -math.inf
    return min(float(train.profit_factor), float(validation.profit_factor), 5.0) * math.log1p(min(train.trades, validation.trades)) - 0.25 * (train.mdd_on_capital + validation.mdd_on_capital)


def diagnostic(train: gap.Metrics, validation: gap.Metrics) -> float:
    return min(float(train.profit_factor or 0), float(validation.profit_factor or 0), 5.0) * math.log1p(min(train.trades, validation.trades))


def search(events: Sequence[EtfEvent]) -> tuple[EtfConfig, bool, list[dict[str, Any]]]:
    rows = []
    for config in grid():
        train = gap.metrics(simulate(events, config, start="2011-01-01", end="2020-12-31"))
        validation = gap.metrics(simulate(events, config, start="2021-01-01", end="2023-12-31"))
        strict = score(train, validation)
        rows.append((strict, diagnostic(train, validation), config, train, validation))
    rows.sort(key=lambda row: (math.isfinite(row[0]), row[0] if math.isfinite(row[0]) else row[1]), reverse=True)
    return rows[0][2], math.isfinite(rows[0][0]), [
        {"passed": math.isfinite(strict), "config": asdict(config), "train": asdict(train), "validation": asdict(validation)}
        for strict, _, config, train, validation in rows[:50]
    ]


def evaluate(events: Sequence[EtfEvent], config: EtfConfig, start: str, end: str) -> dict[str, Any]:
    trades = simulate(events, config, start=start, end=end)
    return {
        "metrics": asdict(gap.metrics(trades)),
        "annual": gap.annual_metrics(trades),
        "miss_top_winners_25pct": asdict(gap.missed_winner_metrics(trades, 0.25)),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Research-only US ETF strategy comparison")
    parser.add_argument("--db-path", default=gap.DEFAULT_DB)
    parser.add_argument("--out-dir", default="data/us_etf_strategy_research")
    args = parser.parse_args()
    candles = gap.load_candles(args.db_path, ["SPY", "QQQ", "IWM"], start="2010-01-01", end="2026-12-31")
    events = sorted(build_events(candles), key=lambda row: (row.date, row.symbol))
    selected, pretest_accepted, top = search(events)
    windows = {
        "train_2011_2020": ("2011-01-01", "2020-12-31"),
        "validation_2021_2023": ("2021-01-01", "2023-12-31"),
        "test_2024_2026": ("2024-01-01", "2026-12-31"),
        "recent_2025_2026": ("2025-01-01", "2026-12-31"),
        "full_2011_2026": ("2011-01-01", "2026-12-31"),
    }
    evaluations = {
        name: {window: evaluate(events, profile(selected, name), *bounds) for window, bounds in windows.items()}
        for name in ("base", "mid", "harsh")
    }
    test = evaluations["harsh"]["test_2024_2026"]
    recent = evaluations["harsh"]["recent_2025_2026"]
    final_accepted = bool(
        pretest_accepted and test["metrics"]["total_pnl_usd"] > 0
        and (test["metrics"]["profit_factor"] or 0) > 1
        and recent["metrics"]["total_pnl_usd"] > 0
        and test["miss_top_winners_25pct"]["total_pnl_usd"] > 0
    )
    payload = {
        "generated_at": datetime.now().astimezone().isoformat(),
        "events": len(events),
        "configurations": len(grid()),
        "pretest_accepted": pretest_accepted,
        "final_live_candidate_accepted": final_accepted,
        "selected_config": asdict(selected),
        "search_top50": top,
        "evaluations": evaluations,
        "limits": ["daily open and close are fill proxies", "USD results exclude KRW translation", "2024+ is used only after selection"],
    }
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "us_etf_strategy_research.json").write_text(json.dumps(gap.json_safe(payload), ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    (out / "selected_harsh_trades.json").write_text(json.dumps([asdict(row) for row in simulate(events, profile(selected, "harsh"), start="2011-01-01", end="2026-12-31")], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out / "selected_base_trades.json").write_text(json.dumps([asdict(row) for row in simulate(events, profile(selected, "base"), start="2011-01-01", end="2026-12-31")], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"events": len(events), "configs": len(grid()), "selected": asdict(selected), "pretest_accepted": pretest_accepted, "final_live_candidate_accepted": final_accepted, "test_harsh": test["metrics"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
