from __future__ import annotations

import argparse
import json
from collections import defaultdict
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from pathlib import Path

from kosdaq_sma5_gate_deep_dive import dates_for_slice, gate_rows, to_index_candles
from simple_gap_strategy_audit import fetch_kosdaq_index
from simple_gap_variant_core import Candidate, VariantConfig, TradeResult, rank_value, simulate_day, simulate_variant
from simple_gap_variant_data import load_candidates


@dataclass(frozen=True, slots=True)
class Scenario:
    name: str
    config: VariantConfig


@dataclass(frozen=True, slots=True)
class CashMetrics:
    trades: int
    pnl: float
    cash_mdd: float
    avg_trade_pnl: float
    avg_invested: float
    win_rate: float


def pct(value: float) -> str:
    return f"{value * 100:+.2f}%"


def grouped_by_date(rows: list[Candidate]) -> dict[str, list[Candidate]]:
    grouped: dict[str, list[Candidate]] = defaultdict(list)
    for row in rows:
        grouped[row.date].append(row)
    return dict(grouped)


def cash_metrics(grouped: dict[str, list[Candidate]], config: VariantConfig, *, miss_winner_share: float = 0.0) -> CashMetrics:
    trades: list[TradeResult] = []
    for date in sorted(grouped):
        _day_return, day_trades = simulate_day(grouped[date], config)
        trades.extend(day_trades)
    if miss_winner_share > 0:
        winners = [row for row in trades if row.net_pnl > 0]
        miss_count = int(len(winners) * miss_winner_share)
        missed = set(sorted(winners, key=lambda row: row.net_pnl, reverse=True)[:miss_count])
        trades = [row for row in trades if row not in missed]
    equity = 0.0
    peak = 0.0
    drawdown = 0.0
    invested = 0.0
    wins = 0
    pnl = 0.0
    for trade in trades:
        trade_invested = trade.quantity * trade.open_price
        invested += trade_invested
        pnl += trade.net_pnl
        wins += 1 if trade.net_pnl > 0 else 0
        equity += trade.net_pnl
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    count = len(trades)
    return CashMetrics(
        trades=count,
        pnl=pnl,
        cash_mdd=drawdown,
        avg_trade_pnl=pnl / count if count else 0.0,
        avg_invested=invested / count if count else 0.0,
        win_rate=wins / count if count else 0.0,
    )


def annual_cash(grouped: dict[str, list[Candidate]], config: VariantConfig) -> dict[str, CashMetrics]:
    years: dict[str, dict[str, list[Candidate]]] = defaultdict(dict)
    for date, rows in grouped.items():
        years[date[:4]][date] = rows
    return {year: cash_metrics(rows, config) for year, rows in sorted(years.items())}


def path_stats(grouped: dict[str, list[Candidate]], config: VariantConfig) -> dict[str, int | list[tuple[str, str, float, float, float]]]:
    stats = {"selected": 0, "both": 0, "stop_only": 0, "take_only": 0, "close_exit": 0}
    examples: list[tuple[str, str, float, float, float]] = []
    for date, rows in grouped.items():
        filtered = [row for row in rows if config.min_price <= row.prev_close <= config.max_price and row.open_price <= config.max_price and row.open_price > 0 and row.gap_return <= config.gap_threshold and config.prev_vol_ratio_min <= row.prev_vol_ratio < config.prev_vol_ratio_max]
        picked = sorted(filtered, key=lambda row: rank_value(row, config.rank))[: config.top_n]
        for row in picked:
            if row.open_price > config.capital or int(config.capital // row.open_price) <= 0:
                continue
            stats["selected"] += 1
            hit_stop = config.stop_loss is not None and row.low_price <= row.open_price * (1.0 - config.stop_loss)
            hit_take = config.take_profit is not None and row.high_price >= row.open_price * (1.0 + config.take_profit)
            if hit_stop and hit_take:
                stats["both"] += 1
                if len(examples) < 10:
                    examples.append((date, row.symbol, row.open_price, row.low_price, row.high_price))
            elif hit_stop:
                stats["stop_only"] += 1
            elif hit_take:
                stats["take_only"] += 1
            else:
                stats["close_exit"] += 1
    return stats | {"examples": examples}


def scenario_payload(rows: list[Candidate], scenario: Scenario, *, start: str, end: str) -> dict[str, str | float | int | dict[str, float | int] | dict[str, dict[str, float | int]]]:
    scoped = [row for row in rows if start <= row.date <= end]
    grouped = grouped_by_date(scoped)
    variant = simulate_variant(scoped, scenario.config)
    cash = cash_metrics(grouped, scenario.config)
    annual = annual_cash(grouped, scenario.config)
    return {
        "name": scenario.name,
        "start": start,
        "end": end,
        "trades": variant.trades,
        "compounded_return": variant.compounded_return,
        "max_drawdown": variant.max_drawdown,
        "profit_factor": 0.0 if variant.profit_factor is None else float(variant.profit_factor),
        "cash": asdict(cash),
        "annual_cash": {year: asdict(metrics) for year, metrics in annual.items()},
        "miss_winner_10": asdict(cash_metrics(grouped, scenario.config, miss_winner_share=0.10)),
        "miss_winner_25": asdict(cash_metrics(grouped, scenario.config, miss_winner_share=0.25)),
        "path_stats": path_stats(grouped, scenario.config),
    }


def markdown(payload: dict[str, object]) -> str:
    market_gate = payload["market_gate"]
    assert isinstance(market_gate, dict)
    lines = [
        "# current strategy risk audit",
        "",
        f"- generated_at: {payload['generated_at']}",
        f"- rows_loaded_before_market_gate: {payload['rows_loaded_before_market_gate']}",
        f"- rows_loaded_after_market_gate: {payload['rows_loaded']}",
        f"- market_gate: {market_gate['definition']}",
        f"- eligible_market_days: {market_gate['eligible_days']} / index_rows: {market_gate['index_rows']}",
        "",
    ]
    for item in payload["scenarios"]:
        if not isinstance(item, dict):
            continue
        cash = item["cash"]
        path = item["path_stats"]
        lines += [
            f"## {item['name']} {item['start']}~{item['end']}",
            f"- trades: {item['trades']} / compounded: {pct(float(item['compounded_return']))} / MDD: {float(item['max_drawdown']) * 100:.2f}% / PF: {float(item['profit_factor']):.3f}",
            f"- cash pnl: {cash['pnl']:,.0f}원 / cash MDD: {cash['cash_mdd']:,.0f}원 / avg trade: {cash['avg_trade_pnl']:,.0f}원 / win: {cash['win_rate'] * 100:.1f}%",
            f"- path: selected={path['selected']} both_stop_take={path['both']} stop_only={path['stop_only']} take_only={path['take_only']} close_exit={path['close_exit']}",
            f"- miss winners 10% pnl: {item['miss_winner_10']['pnl']:,.0f}원 / miss winners 25% pnl: {item['miss_winner_25']['pnl']:,.0f}원",
            "",
            "| year | trades | pnl | cash MDD | win | avg/trade |",
            "|---:|---:|---:|---:|---:|---:|",
        ]
        for year, metrics in item["annual_cash"].items():
            lines.append(f"| {year} | {metrics['trades']} | {metrics['pnl']:,.0f} | {metrics['cash_mdd']:,.0f} | {metrics['win_rate'] * 100:.1f}% | {metrics['avg_trade_pnl']:,.0f} |")
        lines.append("")
    return "\n".join(lines)


def scenarios() -> list[Scenario]:
    live = VariantConfig("robust_gap5_stop0225_take12", 10000.0, 1000.0, 8000.0, -0.05, 0.0, 0.8, 0, 1, "lowest_price", 0.0035, 0.0, 0.0225, 0.12)
    close_exit = replace(live, name="close_exit", stop_loss=None, take_profit=None)
    take_only = replace(live, name="take_only", stop_loss=None)
    stop_only = replace(live, name="stop_only", take_profit=None)
    tight_stop = replace(live, name="tight_stop", stop_loss=0.015)
    wide_stop = replace(live, name="wide_stop", stop_loss=0.035)

    def harsh(config: VariantConfig, name: str) -> VariantConfig:
        return replace(config, name=name, roundtrip_cost=0.0055, slippage=0.008)

    return [
        Scenario("live_base_cost035", live),
        Scenario("live_mid_cost075", replace(live, name="mid", roundtrip_cost=0.0045, slippage=0.003)),
        Scenario("live_harsh_cost135", harsh(live, "harsh")),
        Scenario("take12_only_base", take_only),
        Scenario("take12_only_harsh", harsh(take_only, "take_only_harsh")),
        Scenario("stop0225_only_base", stop_only),
        Scenario("stop0225_only_harsh", harsh(stop_only, "stop_only_harsh")),
        Scenario("no_stop_take_close_exit", close_exit),
        Scenario("no_stop_take_close_exit_harsh", harsh(close_exit, "close_exit_harsh")),
        Scenario("tight_stop_take12", tight_stop),
        Scenario("tight_stop_take12_harsh", harsh(tight_stop, "tight_stop_harsh")),
        Scenario("wide_stop_take12", wide_stop),
        Scenario("wide_stop_take12_harsh", harsh(wide_stop, "wide_stop_harsh")),
    ]


def run() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db-path", default="data/edge_research_universe_15y.sqlite3")
    parser.add_argument("--out-dir", default="data/strategy_research_20h/current_audit")
    parser.add_argument("--start", default="2011-01-01")
    parser.add_argument("--end", default="2026-07-03")
    parser.add_argument("--window-starts", default="2011-01-01,2019-01-01,2021-01-01")
    parser.add_argument("--no-market-gate", action="store_true", help="Research-only comparison without the live 1%% KOSDAQ gate")
    args = parser.parse_args()
    all_rows = load_candidates(args.db_path, start=args.start, end=args.end, broad_gap=-0.05)
    index_rows = to_index_candles(fetch_kosdaq_index(args.start, args.end))
    eligible_dates = dates_for_slice(gate_rows(index_rows), "live_buy_gate_1pct")
    rows = all_rows if args.no_market_gate else [row for row in all_rows if row.date in eligible_dates]
    window_starts = [value.strip() for value in args.window_starts.split(",") if value.strip()]
    blocks = []
    for scenario in scenarios():
        for start in window_starts:
            blocks.append(scenario_payload(rows, scenario, start=start, end=args.end))
    payload = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "rows_loaded_before_market_gate": len(all_rows),
        "rows_loaded": len(rows),
        "market_gate": {
            "enabled": not args.no_market_gate,
            "definition": "KOSDAQ open <= live-style SMA5 * 0.99" if not args.no_market_gate else "disabled",
            "eligible_days": len(eligible_dates),
            "index_rows": len(index_rows),
        },
        "scenarios": blocks,
    }
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "risk_audit.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    (out_dir / "risk_audit.md").write_text(markdown(payload) + "\n", encoding="utf-8")
    print(json.dumps({"out_dir": str(out_dir), "rows": len(rows), "scenarios": len(blocks)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
