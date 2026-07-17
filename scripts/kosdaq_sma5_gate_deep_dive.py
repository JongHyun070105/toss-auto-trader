# /// script
# requires-python = ">=3.11"
# ///
from __future__ import annotations

import argparse
import json
import statistics
from collections import defaultdict
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Final, Mapping, Sequence

from simple_gap_strategy_audit import fetch_kosdaq_index
from simple_gap_variant_core import Candidate, TradeResult, VariantConfig, simulate_day
from simple_gap_variant_data import load_candidates

DEFAULT_DB: Final = "data/edge_research_universe_15y.sqlite3"
DEFAULT_OUT_DIR: Final = "data/strategy_research_20h"


@dataclass(frozen=True, slots=True)
class IndexCandle:
    date: str
    open_price: float
    close_price: float


@dataclass(frozen=True, slots=True)
class GateRow:
    date: str
    open_price: float
    close_price: float
    live_sma5_at_open: float
    open_vs_live_sma5: float
    prev_close: float
    prev_sma5: float
    prev_close_vs_prev_sma5: float


@dataclass(frozen=True, slots=True)
class Metrics:
    trades: int
    active_days: int
    compounded_return: float
    max_drawdown: float
    profit_factor: float | None
    win_rate: float | None
    avg_trade_pnl: float | None
    total_pnl: float


def live_config() -> VariantConfig:
    return VariantConfig("robust_gap5_stop0225_take12", 10000.0, 1000.0, 8000.0, -0.05, 0.0, 0.8, 0, 1, "lowest_price", 0.0035, 0.0, 0.0225, 0.12)


def to_index_candles(rows: Sequence[Mapping[str, str | int | float]]) -> list[IndexCandle]:
    return [
        IndexCandle(str(row["date"]), float(row["open"]), float(row["close"]))
        for row in rows
        if float(row["open"]) > 0 and float(row["close"]) > 0
    ]


def gate_rows(index_rows: Sequence[IndexCandle]) -> dict[str, GateRow]:
    closes = [row.close_price for row in index_rows]
    gates: dict[str, GateRow] = {}
    for idx in range(5, len(index_rows)):
        row = index_rows[idx]
        prev4 = closes[idx - 4 : idx]
        prev5 = closes[idx - 5 : idx]
        live_sma = (row.open_price + sum(prev4)) / 5.0
        prev_sma = statistics.mean(prev5)
        prev_close = closes[idx - 1]
        gates[row.date] = GateRow(row.date, row.open_price, row.close_price, live_sma, row.open_price / live_sma - 1.0, prev_close, prev_sma, prev_close / prev_sma - 1.0)
    return gates


def split_rows(rows: Sequence[Candidate], start: str, end: str) -> list[Candidate]:
    return [row for row in rows if start <= row.date <= end]


def filtered_by_dates(rows: Sequence[Candidate], dates: set[str]) -> list[Candidate]:
    return [row for row in rows if row.date in dates]


def collect_trades(rows: Sequence[Candidate], config: VariantConfig) -> tuple[list[float], list[TradeResult]]:
    grouped: dict[str, list[Candidate]] = defaultdict(list)
    for row in rows:
        grouped[row.date].append(row)
    day_returns: list[float] = []
    trades: list[TradeResult] = []
    for date in sorted(grouped):
        day_return, day_trades = simulate_day(grouped[date], config)
        if day_trades:
            day_returns.append(day_return)
            trades.extend(day_trades)
    return day_returns, trades


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


def summarize(rows: Sequence[Candidate], config: VariantConfig) -> Metrics:
    day_returns, trades = collect_trades(rows, config)
    if not trades:
        return Metrics(0, 0, 0.0, 0.0, None, None, None, 0.0)
    gains = sum(row.net_pnl for row in trades if row.net_pnl > 0)
    losses = -sum(row.net_pnl for row in trades if row.net_pnl < 0)
    pnl = sum(row.net_pnl for row in trades)
    return Metrics(
        trades=len(trades),
        active_days=len(day_returns),
        compounded_return=compounded(day_returns),
        max_drawdown=max_drawdown(day_returns),
        profit_factor=None if losses <= 0 else gains / losses,
        win_rate=sum(1 for row in trades if row.net_pnl > 0) / len(trades),
        avg_trade_pnl=pnl / len(trades),
        total_pnl=pnl,
    )


def yearly(rows: Sequence[Candidate], config: VariantConfig) -> dict[str, Metrics]:
    years = sorted({row.date[:4] for row in rows})
    return {year: summarize([row for row in rows if row.date.startswith(year)], config) for year in years}


def dates_for_slice(gates: Mapping[str, GateRow], name: str) -> set[str]:
    if name == "all":
        return set(gates)
    if name == "live_open_above":
        return {date for date, row in gates.items() if row.open_vs_live_sma5 >= 0.0}
    if name == "live_open_below":
        return {date for date, row in gates.items() if row.open_vs_live_sma5 < 0.0}
    if name == "live_buy_gate_1pct":
        return {date for date, row in gates.items() if row.open_vs_live_sma5 <= -0.01}
    if name == "live_blocked_gate_1pct":
        return {date for date, row in gates.items() if row.open_vs_live_sma5 > -0.01}
    if name == "below_mild_0_to_1pct":
        return {date for date, row in gates.items() if -0.01 <= row.open_vs_live_sma5 < 0.0}
    if name == "below_mid_1_to_3pct":
        return {date for date, row in gates.items() if -0.03 <= row.open_vs_live_sma5 < -0.01}
    if name == "below_harsh_over_3pct":
        return {date for date, row in gates.items() if row.open_vs_live_sma5 < -0.03}
    if name == "prev_close_above":
        return {date for date, row in gates.items() if row.prev_close_vs_prev_sma5 >= 0.0}
    if name == "prev_close_below":
        return {date for date, row in gates.items() if row.prev_close_vs_prev_sma5 < 0.0}
    raise KeyError(name)


def run(args: argparse.Namespace) -> dict[str, object]:
    config = live_config()
    stress = {
        "base": config,
        "mid": replace(config, name="mid_cost075", roundtrip_cost=0.0045, slippage=0.003),
        "harsh": replace(config, name="harsh_cost135", roundtrip_cost=0.0055, slippage=0.008),
    }
    candidates = load_candidates(args.db_path, start=args.start, end=args.end, broad_gap=config.gap_threshold)
    index = to_index_candles(fetch_kosdaq_index(args.start, args.end))
    gates = gate_rows(index)
    slices = [
        "all",
        "live_buy_gate_1pct",
        "live_blocked_gate_1pct",
        "live_open_above",
        "live_open_below",
        "below_mild_0_to_1pct",
        "below_mid_1_to_3pct",
        "below_harsh_over_3pct",
        "prev_close_above",
        "prev_close_below",
    ]
    windows = {"full": (args.start, args.end), "train_2016_2023": (args.start, "2023-12-31"), "test_2024_2026": ("2024-01-01", args.end), "recent_2025_2026": ("2025-01-01", args.end)}
    results: dict[str, object] = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "strategy": asdict(config),
        "db_path": args.db_path,
        "candidate_rows": len(candidates),
        "index_rows": len(index),
        "gate_definition": {
            "live_open_above": "KOSDAQ open >= live-style SMA5 at open, equivalent to open >= average(previous 4 closes)",
            "live_buy_gate_1pct": "KOSDAQ open <= live-style SMA5 * 0.99, exact daily-open proxy for the live gate",
            "prev_close_above": "previous KOSDAQ close >= previous 5-close SMA; no-lookahead daily proxy",
        },
        "windows": {},
    }
    for window, (start, end) in windows.items():
        window_rows = split_rows(candidates, start, end)
        window_payload: dict[str, object] = {}
        for slice_name in slices:
            slice_rows = filtered_by_dates(window_rows, dates_for_slice(gates, slice_name))
            window_payload[slice_name] = {
                "candidate_rows": len(slice_rows),
                "base": asdict(summarize(slice_rows, stress["base"])),
                "mid": asdict(summarize(slice_rows, stress["mid"])),
                "harsh": asdict(summarize(slice_rows, stress["harsh"])),
            }
        results["windows"][window] = window_payload
    buy_gate_rows = filtered_by_dates(candidates, dates_for_slice(gates, "live_buy_gate_1pct"))
    results["annual_live_buy_gate_1pct_base"] = {year: asdict(metrics) for year, metrics in yearly(buy_gate_rows, config).items()}
    return results


def pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.1f}%"


def money(value: float | None) -> str:
    return "n/a" if value is None else f"{value:,.0f}"


def report_markdown(results: Mapping[str, object]) -> str:
    windows = results["windows"]
    assert isinstance(windows, Mapping)
    lines = [
        "# KOSDAQ SMA5 Gate Deep Dive",
        "",
        f"- generated_at: `{results['generated_at']}`",
        f"- candidate_rows: `{results['candidate_rows']}`",
        f"- index_rows: `{results['index_rows']}`",
        "- live-style gate: KOSDAQ open <= live-style SMA5 * 0.99. The daily-open proxy uses the open plus the previous four closes.",
        "- config: current `robust_gap5_stop0225_take12`, 10,000 KRW, gap <= -5%, price 1,000-8,000, prev volume ratio < 0.8, top1 lowest_price, stop 2.25%, take 12%.",
        "",
    ]
    for window_name, payload in windows.items():
        assert isinstance(payload, Mapping)
        lines += [
            f"## {window_name}",
            "",
            "| slice | trades | PF | MDD | comp | harsh PF | harsh MDD | avg pnl |",
            "|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
        for slice_name, row in payload.items():
            assert isinstance(row, Mapping)
            base = row["base"]
            harsh = row["harsh"]
            assert isinstance(base, Mapping)
            assert isinstance(harsh, Mapping)
            lines.append(
                f"| {slice_name} | {base['trades']} | {base['profit_factor'] if base['profit_factor'] is not None else 'n/a'} | "
                f"{pct(base['max_drawdown'])} | {pct(base['compounded_return'])} | "
                f"{harsh['profit_factor'] if harsh['profit_factor'] is not None else 'n/a'} | {pct(harsh['max_drawdown'])} | {money(base['avg_trade_pnl'])} |"
            )
        lines.append("")
    annual = results["annual_live_buy_gate_1pct_base"]
    assert isinstance(annual, Mapping)
    lines += [
        "## annual live_buy_gate_1pct base",
        "",
        "| year | trades | PF | MDD | comp | total pnl |",
        "|---:|---:|---:|---:|---:|---:|",
    ]
    for year, metrics in annual.items():
        assert isinstance(metrics, Mapping)
        lines.append(
            f"| {year} | {metrics['trades']} | {metrics['profit_factor'] if metrics['profit_factor'] is not None else 'n/a'} | "
            f"{pct(metrics['max_drawdown'])} | {pct(metrics['compounded_return'])} | {money(metrics['total_pnl'])} |"
        )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="No-send KOSDAQ SMA5 gate deep dive for current simple_gap strategy")
    parser.add_argument("--db-path", default=DEFAULT_DB)
    parser.add_argument("--start", default="2016-01-01")
    parser.add_argument("--end", default="2026-07-03")
    parser.add_argument("--out-dir", default=DEFAULT_OUT_DIR)
    args = parser.parse_args()
    results = run(args)
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / f"kosdaq_sma5_gate_deep_dive_{stamp}.json"
    md_path = out_dir / f"kosdaq_sma5_gate_deep_dive_{stamp}.md"
    json_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(report_markdown(results), encoding="utf-8")
    print(json.dumps({"json": str(json_path), "md": str(md_path)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
