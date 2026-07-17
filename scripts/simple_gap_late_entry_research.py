from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from collections import defaultdict
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Final, Mapping, Sequence

from kosdaq_sma5_gate_deep_dive import gate_rows, to_index_candles
from simple_gap_strategy_audit import fetch_kosdaq_index
from simple_gap_variant_core import Candidate, VariantConfig, rank_value
from simple_gap_variant_data import load_candidates


DEFAULT_DB: Final = "data/edge_research_universe_15y.sqlite3"
DEFAULT_OUT_DIR: Final = "data/simple_gap_late_entry_research"
BASE_COST: Final = 0.0035
MID_COST: Final = 0.0045
MID_SLIPPAGE: Final = 0.003
HARSH_COST: Final = 0.0055
HARSH_SLIPPAGE: Final = 0.008


@dataclass(frozen=True, slots=True)
class EntryConfig:
    name: str
    base: VariantConfig
    entry_mode: str
    pullback_pct: float = 0.0
    take_policy: str = "high"


@dataclass(frozen=True, slots=True)
class LateTrade:
    date: str
    symbol: str
    entry_price: float
    exit_price: float
    exit_reason: str
    quantity: int
    invested: float
    net_pnl: float
    net_return: float
    open_price: float
    low_price: float
    high_price: float
    close_price: float
    gap_return: float
    prev_vol_ratio: float


@dataclass(frozen=True, slots=True)
class Metrics:
    strategy: str
    cost_profile: str
    window: str
    trades: int
    active_days: int
    compounded_return: float
    max_drawdown: float
    profit_factor: float | None
    win_rate: float | None
    total_pnl: float
    avg_trade_pnl: float | None
    median_trade_pnl: float | None
    avg_cash_used_pct: float | None
    stop_rate: float | None
    take_rate: float | None
    close_rate: float | None


def current_strategy_config() -> VariantConfig:
    return VariantConfig(
        "robust_gap5_stop0225_take12",
        10000.0,
        1000.0,
        8000.0,
        -0.05,
        0.0,
        0.8,
        0,
        1,
        "lowest_price",
        BASE_COST,
        0.0,
        0.0225,
        0.12,
    )


def cost_profiles(base: VariantConfig) -> dict[str, VariantConfig]:
    return {
        "base": replace(base, name="base"),
        "mid": replace(base, name="mid", roundtrip_cost=MID_COST, slippage=MID_SLIPPAGE),
        "harsh": replace(base, name="harsh", roundtrip_cost=HARSH_COST, slippage=HARSH_SLIPPAGE),
    }


def entry_configs(base: VariantConfig) -> list[EntryConfig]:
    return [
        EntryConfig("main_0901_open", base, "open"),
        EntryConfig("late_pullback_005_high_take", base, "pullback", 0.005, "high"),
        EntryConfig("late_pullback_010_high_take", base, "pullback", 0.010, "high"),
        EntryConfig("late_pullback_015_high_take", base, "pullback", 0.015, "high"),
        EntryConfig("late_pullback_020_high_take", base, "pullback", 0.020, "high"),
        EntryConfig("late_pullback_005_close_take", base, "pullback", 0.005, "close"),
        EntryConfig("late_pullback_010_close_take", base, "pullback", 0.010, "close"),
        EntryConfig("late_pullback_015_close_take", base, "pullback", 0.015, "close"),
        EntryConfig("late_pullback_020_close_take", base, "pullback", 0.020, "close"),
    ]


def passes_filters(candidate: Candidate, config: VariantConfig, allowed_dates: set[str]) -> bool:
    return (
        candidate.date in allowed_dates
        and config.min_price <= candidate.prev_close <= config.max_price
        and candidate.open_price <= config.max_price
        and candidate.open_price > 0
        and candidate.gap_return <= config.gap_threshold
        and config.prev_vol_ratio_min <= candidate.prev_vol_ratio < config.prev_vol_ratio_max
    )


def entry_price(candidate: Candidate, entry: EntryConfig) -> float | None:
    if entry.entry_mode == "open":
        return candidate.open_price
    if entry.entry_mode == "pullback":
        price = candidate.open_price * (1.0 - entry.pullback_pct)
        return price if candidate.low_price <= price else None
    raise ValueError(f"unknown entry_mode: {entry.entry_mode}")


def exit_price(candidate: Candidate, entry_px: float, entry: EntryConfig, config: VariantConfig) -> tuple[float, str]:
    stop_px = None if config.stop_loss is None else entry_px * (1.0 - config.stop_loss)
    take_px = None if config.take_profit is None else entry_px * (1.0 + config.take_profit)
    if stop_px is not None and candidate.low_price <= stop_px:
        return stop_px, "stop"
    if take_px is not None:
        if entry.take_policy == "high" and candidate.high_price >= take_px:
            return take_px, "take"
        if entry.take_policy == "close" and candidate.close_price >= take_px:
            return take_px, "take"
    return candidate.close_price, "close"


def simulate_day(candidates: Sequence[Candidate], entry: EntryConfig, config: VariantConfig, allowed_dates: set[str]) -> tuple[float, list[LateTrade]]:
    filtered = [row for row in candidates if passes_filters(row, config, allowed_dates)]
    ranked = sorted(filtered, key=lambda row: rank_value(row, config.rank))
    slot_capital = config.capital / max(1, config.top_n)
    costs = config.roundtrip_cost + config.slippage
    trades: list[LateTrade] = []
    for row in ranked:
        if len(trades) >= config.top_n:
            break
        price = entry_price(row, entry)
        if price is None or price <= 0 or price > slot_capital:
            continue
        quantity = int(slot_capital // price)
        if quantity <= 0:
            continue
        out_price, reason = exit_price(row, price, entry, config)
        invested = quantity * price
        net_pnl = quantity * (out_price - price) - invested * costs
        trades.append(
            LateTrade(
                date=row.date,
                symbol=row.symbol,
                entry_price=price,
                exit_price=out_price,
                exit_reason=reason,
                quantity=quantity,
                invested=invested,
                net_pnl=net_pnl,
                net_return=net_pnl / config.capital,
                open_price=row.open_price,
                low_price=row.low_price,
                high_price=row.high_price,
                close_price=row.close_price,
                gap_return=row.gap_return,
                prev_vol_ratio=row.prev_vol_ratio,
            )
        )
    return sum(row.net_return for row in trades), trades


def grouped_by_date(rows: Sequence[Candidate]) -> dict[str, list[Candidate]]:
    grouped: dict[str, list[Candidate]] = defaultdict(list)
    for row in rows:
        grouped[row.date].append(row)
    return grouped


def max_drawdown(day_returns: Sequence[float]) -> float:
    equity = 1.0
    peak = 1.0
    worst = 0.0
    for value in day_returns:
        equity *= max(0.0, 1.0 + value)
        peak = max(peak, equity)
        worst = max(worst, (peak - equity) / peak)
    return worst


def compounded(day_returns: Sequence[float]) -> float:
    equity = 1.0
    for value in day_returns:
        equity *= max(0.0, 1.0 + value)
    return equity - 1.0


def profit_factor(trades: Sequence[LateTrade]) -> float | None:
    gains = sum(row.net_pnl for row in trades if row.net_pnl > 0)
    losses = -sum(row.net_pnl for row in trades if row.net_pnl < 0)
    if losses <= 0:
        return math.inf if gains > 0 else None
    return gains / losses


def summarize(strategy: str, cost_profile: str, window: str, day_returns: Sequence[float], trades: Sequence[LateTrade]) -> Metrics:
    if not trades:
        return Metrics(strategy, cost_profile, window, 0, 0, 0.0, 0.0, None, None, 0.0, None, None, None, None, None, None)
    pnl = [row.net_pnl for row in trades]
    cash = [row.invested / 10000.0 for row in trades]
    return Metrics(
        strategy=strategy,
        cost_profile=cost_profile,
        window=window,
        trades=len(trades),
        active_days=len(day_returns),
        compounded_return=compounded(day_returns),
        max_drawdown=max_drawdown(day_returns),
        profit_factor=profit_factor(trades),
        win_rate=sum(1 for row in trades if row.net_pnl > 0) / len(trades),
        total_pnl=sum(pnl),
        avg_trade_pnl=statistics.mean(pnl),
        median_trade_pnl=statistics.median(pnl),
        avg_cash_used_pct=statistics.mean(cash),
        stop_rate=sum(1 for row in trades if row.exit_reason == "stop") / len(trades),
        take_rate=sum(1 for row in trades if row.exit_reason == "take") / len(trades),
        close_rate=sum(1 for row in trades if row.exit_reason == "close") / len(trades),
    )


def simulate_window(
    rows: Sequence[Candidate],
    entry: EntryConfig,
    config: VariantConfig,
    allowed_dates: set[str],
    window_name: str,
    start: str,
    end: str,
) -> tuple[Metrics, list[LateTrade]]:
    grouped = grouped_by_date(row for row in rows if start <= row.date <= end)
    day_returns: list[float] = []
    trades: list[LateTrade] = []
    for date in sorted(grouped):
        day_return, day_trades = simulate_day(grouped[date], entry, config, allowed_dates)
        if day_trades:
            day_returns.append(day_return)
            trades.extend(day_trades)
    return summarize(entry.name, config.name, window_name, day_returns, trades), trades


def market_gate_dates(start: str, end: str) -> tuple[set[str], int]:
    index = to_index_candles(fetch_kosdaq_index(start, end))
    gates = gate_rows(index)
    return {date for date, row in gates.items() if row.open_vs_live_sma5 <= -0.01}, len(index)


def safe_float(value: float | None) -> float | None:
    if value is None or math.isinf(value) or math.isnan(value):
        return None
    return float(value)


def write_csv(path: Path, rows: Sequence[Mapping[str, object]]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.1f}%"


def num(value: float | None) -> str:
    if value is None:
        return "n/a"
    if math.isinf(value):
        return "inf"
    return f"{value:.2f}"


def report_markdown(payload: Mapping[str, object]) -> str:
    metrics = payload["metrics"]
    assert isinstance(metrics, list)
    lines = [
        "# Simple Gap Late Entry Research",
        "",
        f"- generated_at: `{payload['generated_at']}`",
        f"- source_db: `{payload['db_path']}`",
        f"- candidate_rows: `{payload['candidate_rows']}`",
        f"- market_gate_dates: `{payload['market_gate_dates']}`",
        "- note: local history has daily OHLC candles only, so late-entry rows are daily pullback-fill proxies, not true 09:10-09:30 intraday replay.",
        "- gate: KOSDAQ open <= live-style SMA5 * 0.99.",
        "- filters: previous close 1,000-8,000 KRW, gap <= -5%, previous volume ratio < 0.8, top1 lowest open price.",
        "- exits: -2.25% stop, +12% take, otherwise same-day close. Pullback variants use stop-first handling when daily OHLC is ambiguous.",
        "",
    ]
    for window in ["full", "train_2016_2023", "test_2024_2026", "recent_2025_2026"]:
        lines += [
            f"## {window}",
            "",
            "| strategy | cost | trades | PF | win | MDD | comp | total pnl | stop | take | close |",
            "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
        for row in metrics:
            if not isinstance(row, Mapping) or row["window"] != window:
                continue
            lines.append(
                f"| {row['strategy']} | {row['cost_profile']} | {row['trades']} | {num(row['profit_factor'])} | "
                f"{pct(row['win_rate'])} | {pct(row['max_drawdown'])} | {pct(row['compounded_return'])} | "
                f"{float(row['total_pnl']):,.0f} | {pct(row['stop_rate'])} | {pct(row['take_rate'])} | {pct(row['close_rate'])} |"
            )
        lines.append("")
    lines += [
        "## decision rule",
        "",
        "- Do not mix late-entry results into `robust_gap5_stop0225_take12` unless a pullback variant beats the 09:01 baseline in the 2024-2026 test window under harsh costs and does not materially raise MDD.",
        "- If used for live learning only, keep it as a separate `late_entry_probe` tag, one trade per day, 10,000 KRW cap, and separate logs/results.",
        "",
    ]
    return "\n".join(lines)


def run(args: argparse.Namespace) -> dict[str, object]:
    base = current_strategy_config()
    rows = load_candidates(args.db_path, start=args.start, end=args.end, broad_gap=base.gap_threshold)
    gate_dates, index_rows = market_gate_dates(args.start, args.end)
    windows = {
        "full": (args.start, args.end),
        "train_2016_2023": (args.start, "2023-12-31"),
        "test_2024_2026": ("2024-01-01", args.end),
        "recent_2025_2026": ("2025-01-01", args.end),
    }
    metrics_rows: list[dict[str, object]] = []
    trade_rows: list[dict[str, object]] = []
    for entry in entry_configs(base):
        for cost_name, cost_config in cost_profiles(base).items():
            for window, (start, end) in windows.items():
                metrics, trades = simulate_window(rows, entry, cost_config, gate_dates, window, start, end)
                metrics_rows.append({key: safe_float(value) if isinstance(value, float) else value for key, value in asdict(metrics).items()})
                for trade in trades:
                    trade_rows.append({"strategy": entry.name, "cost_profile": cost_name, "window": window, **asdict(trade)})
    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "db_path": args.db_path,
        "start": args.start,
        "end": args.end,
        "candidate_rows": len(rows),
        "index_rows": index_rows,
        "market_gate_dates": len(gate_dates),
        "base_config": asdict(base),
        "metrics": metrics_rows,
        "sample_trades": trade_rows[:500],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Research daily-OHLC late-entry probes against the current simple gap strategy.")
    parser.add_argument("--db-path", default=DEFAULT_DB)
    parser.add_argument("--start", default="2016-01-01")
    parser.add_argument("--end", default="2026-07-07")
    parser.add_argument("--out-dir", default=DEFAULT_OUT_DIR)
    args = parser.parse_args()
    payload = run(args)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = out_dir / f"late_entry_research_{stamp}.json"
    md_path = out_dir / f"late_entry_research_{stamp}.md"
    metrics_path = out_dir / f"late_entry_research_{stamp}.metrics.csv"
    trades_path = out_dir / f"late_entry_research_{stamp}.sample_trades.csv"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(report_markdown(payload), encoding="utf-8")
    metrics = payload["metrics"]
    trades = payload["sample_trades"]
    assert isinstance(metrics, list)
    assert isinstance(trades, list)
    write_csv(metrics_path, metrics)
    write_csv(trades_path, trades)
    print(json.dumps({"json": str(json_path), "md": str(md_path), "metrics": str(metrics_path), "sample_trades": str(trades_path)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
