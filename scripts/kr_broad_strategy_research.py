#!/usr/bin/env python3
"""Broad, research-only Korean gap-strategy robustness search.

The live trader is not imported and no Toss account or order endpoint is used.
Entry selection uses only values available at the regular-session open. Search
uses data through 2023; 2024+ and the post-NXT period are opened afterwards.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sqlite3
import statistics
from collections import defaultdict
from dataclasses import asdict, dataclass, fields, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Sequence

from kosdaq_sma5_gate_deep_dive import gate_rows, to_index_candles
from simple_gap_strategy_audit import fetch_kosdaq_index


CAPITAL = 10_000.0
DEFAULT_DB = "data/edge_research_universe_15y.sqlite3"
DEFAULT_OUT_DIR = "data/kr_broad_strategy_research"
NXT_START = "2025-03-04"


@dataclass(frozen=True, slots=True)
class Event:
    date: str
    symbol: str
    prev_close: float
    open: float
    high: float
    low: float
    close: float
    gap: float
    prev_vol_ratio: float
    avg_dollar_volume20: float
    avg_range20: float
    prev_return1: float
    prev_return5: float
    prev_return20: float
    prev_close_location: float
    future: tuple[tuple[int, str, float], ...]


@dataclass(frozen=True, slots=True)
class Market:
    date: str
    open_vs_sma5: float
    index_gap: float
    gap2_count: int
    gap5_count: int


@dataclass(frozen=True, slots=True)
class Config:
    name: str
    market_min: float | None
    market_max: float | None
    index_gap_min: float | None
    gap_min: float | None
    gap_max: float
    min_price: float
    max_price: float
    prev_vol_ratio_min: float
    prev_vol_ratio_max: float
    min_dollar_volume: float
    avg_range_min: float | None
    avg_range_max: float | None
    prev_return5_min: float | None
    prev_return5_max: float | None
    close_location_min: float | None
    close_location_max: float | None
    gap5_count_min: int | None
    gap5_count_max: int | None
    rank: str
    exit_days: int
    stop_loss: float | None
    take_profit: float | None
    roundtrip_cost: float


@dataclass(frozen=True, slots=True)
class Trade:
    date: str
    exit_date: str
    symbol: str
    entry: float
    exit: float
    quantity: int
    invested: float
    gross_pnl: float
    net_pnl: float
    net_return_on_capital: float
    reason: str
    gap: float
    avg_dollar_volume20: float
    avg_range20: float
    prev_return5: float
    market_open_vs_sma5: float


@dataclass(frozen=True, slots=True)
class Metrics:
    trades: int
    active_days: int
    total_pnl: float
    avg_pnl: float | None
    median_pnl: float | None
    win_rate: float | None
    profit_factor: float | None
    cash_mdd: float
    mdd_on_capital: float
    break_even_roundtrip_cost: float | None
    positive_year_share: float | None
    max_symbol_share: float | None
    max_month_share: float | None


@dataclass(frozen=True, slots=True)
class Ablation:
    label: str
    changes: tuple[tuple[str, Any], ...]


def load_events(db_path: str, *, start: str, end: str) -> list[Event]:
    sql = """
    WITH enriched AS (
      SELECT
        symbol, substr(timestamp,1,10) AS date,
        CAST(open_price AS REAL) AS open_price,
        CAST(high_price AS REAL) AS high_price,
        CAST(low_price AS REAL) AS low_price,
        CAST(close_price AS REAL) AS close_price,
        LAG(CAST(close_price AS REAL),1) OVER w AS prev_close,
        LAG(CAST(close_price AS REAL),2) OVER w AS close_lag2,
        LAG(CAST(close_price AS REAL),6) OVER w AS close_lag6,
        LAG(CAST(close_price AS REAL),21) OVER w AS close_lag21,
        LAG(CAST(open_price AS REAL),1) OVER w AS prev_open,
        LAG(CAST(high_price AS REAL),1) OVER w AS prev_high,
        LAG(CAST(low_price AS REAL),1) OVER w AS prev_low,
        LAG(CAST(volume AS REAL),1) OVER w AS prev_volume,
        AVG(CAST(volume AS REAL)) OVER (
          PARTITION BY symbol ORDER BY timestamp ROWS BETWEEN 21 PRECEDING AND 2 PRECEDING
        ) AS avg_prev20_volume,
        AVG(CAST(close_price AS REAL) * CAST(volume AS REAL)) OVER (
          PARTITION BY symbol ORDER BY timestamp ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING
        ) AS avg_dollar_volume20,
        AVG((CAST(high_price AS REAL)-CAST(low_price AS REAL))/NULLIF(CAST(close_price AS REAL),0)) OVER (
          PARTITION BY symbol ORDER BY timestamp ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING
        ) AS avg_range20,
        COUNT(*) OVER (
          PARTITION BY symbol ORDER BY timestamp ROWS BETWEEN 21 PRECEDING AND 2 PRECEDING
        ) AS prev_count,
        LEAD(substr(timestamp,1,10),1) OVER w AS date_fwd1,
        LEAD(substr(timestamp,1,10),3) OVER w AS date_fwd3,
        LEAD(substr(timestamp,1,10),5) OVER w AS date_fwd5,
        LEAD(CAST(close_price AS REAL),1) OVER w AS close_fwd1,
        LEAD(CAST(close_price AS REAL),3) OVER w AS close_fwd3,
        LEAD(CAST(close_price AS REAL),5) OVER w AS close_fwd5
      FROM candle_cache WHERE interval='1d'
      WINDOW w AS (PARTITION BY symbol ORDER BY timestamp)
    )
    SELECT * FROM enriched
    WHERE date BETWEEN ? AND ? AND prev_count=20
      AND prev_close BETWEEN 500 AND 30000 AND open_price > 0
      AND high_price >= MAX(open_price,close_price)
      AND low_price <= MIN(open_price,close_price)
      AND avg_prev20_volume > 0 AND avg_range20 > 0
      AND (open_price/prev_close-1) <= -0.02
    ORDER BY date,symbol
    """
    con = sqlite3.connect(f"file:{Path(db_path).resolve()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(sql, (start, end)).fetchall()
    finally:
        con.close()
    events: list[Event] = []
    for row in rows:
        prev_close = float(row["prev_close"])
        prev_high = float(row["prev_high"] or prev_close)
        prev_low = float(row["prev_low"] or prev_close)
        location = (prev_close - prev_low) / (prev_high - prev_low) if prev_high > prev_low else 0.5
        future = tuple(
            (days, str(row[f"date_fwd{days}"]), float(row[f"close_fwd{days}"]))
            for days in (1, 3, 5)
            if row[f"date_fwd{days}"] and row[f"close_fwd{days}"] and float(row[f"close_fwd{days}"]) > 0
        )
        close_lag2 = float(row["close_lag2"] or prev_close)
        close_lag6 = float(row["close_lag6"] or prev_close)
        close_lag21 = float(row["close_lag21"] or prev_close)
        events.append(Event(
            date=str(row["date"]), symbol=str(row["symbol"]), prev_close=prev_close,
            open=float(row["open_price"]), high=float(row["high_price"]), low=float(row["low_price"]),
            close=float(row["close_price"]), gap=float(row["open_price"])/prev_close-1.0,
            prev_vol_ratio=float(row["prev_volume"])/float(row["avg_prev20_volume"]),
            avg_dollar_volume20=float(row["avg_dollar_volume20"]), avg_range20=float(row["avg_range20"]),
            prev_return1=prev_close/close_lag2-1.0, prev_return5=prev_close/close_lag6-1.0,
            prev_return20=prev_close/close_lag21-1.0, prev_close_location=location, future=future,
        ))
    return events


def build_markets(events: Sequence[Event], index_rows: Sequence[dict[str, Any]]) -> dict[str, Market]:
    by_date: dict[str, list[Event]] = defaultdict(list)
    for event in events:
        by_date[event.date].append(event)
    gates = gate_rows(to_index_candles(index_rows))
    index_by_date = {str(row["date"]): row for row in index_rows}
    sorted_dates = sorted(index_by_date)
    previous_close: dict[str, float] = {}
    for idx in range(1, len(sorted_dates)):
        previous_close[sorted_dates[idx]] = float(index_by_date[sorted_dates[idx - 1]]["close"])
    result: dict[str, Market] = {}
    for date, rows in by_date.items():
        gate = gates.get(date)
        index = index_by_date.get(date)
        prior = previous_close.get(date)
        if gate is None or index is None or not prior:
            continue
        result[date] = Market(
            date=date,
            open_vs_sma5=float(gate.open_vs_live_sma5),
            index_gap=float(index["open"])/prior-1.0,
            gap2_count=len(rows),
            gap5_count=sum(row.gap <= -0.05 for row in rows),
        )
    return result


def anchor_config() -> Config:
    return Config(
        "robust_gap5_stop0225_take12", None, -0.01, None, None, -0.05,
        1000.0, 8000.0, 0.0, 0.8, 0.0, None, None, None, None,
        None, None, None, None, "lowest_price", 0, 0.0225, 0.12, 0.0135,
    )


def passes(event: Event, market: Market, config: Config) -> bool:
    return (
        (config.market_min is None or market.open_vs_sma5 >= config.market_min)
        and (config.market_max is None or market.open_vs_sma5 <= config.market_max)
        and (config.index_gap_min is None or market.index_gap >= config.index_gap_min)
        and (config.gap_min is None or event.gap >= config.gap_min)
        and event.gap <= config.gap_max
        and config.min_price <= event.prev_close <= config.max_price
        and event.open <= config.max_price
        and config.prev_vol_ratio_min <= event.prev_vol_ratio < config.prev_vol_ratio_max
        and event.avg_dollar_volume20 >= config.min_dollar_volume
        and (config.avg_range_min is None or event.avg_range20 >= config.avg_range_min)
        and (config.avg_range_max is None or event.avg_range20 <= config.avg_range_max)
        and (config.prev_return5_min is None or event.prev_return5 >= config.prev_return5_min)
        and (config.prev_return5_max is None or event.prev_return5 <= config.prev_return5_max)
        and (config.close_location_min is None or event.prev_close_location >= config.close_location_min)
        and (config.close_location_max is None or event.prev_close_location <= config.close_location_max)
        and (config.gap5_count_min is None or market.gap5_count >= config.gap5_count_min)
        and (config.gap5_count_max is None or market.gap5_count <= config.gap5_count_max)
    )


def rank_key(event: Event, rank: str) -> tuple[float, str]:
    keys = {
        "lowest_price": event.open,
        "highest_liquidity": -event.avg_dollar_volume20,
        "most_negative_gap": event.gap,
        "mildest_gap": abs(event.gap),
        "quiet_volume": event.prev_vol_ratio,
        "gap_over_range": event.gap/event.avg_range20,
        "prior_strength": -event.prev_return5,
    }
    return keys[rank], event.symbol


def exit_for(event: Event, config: Config) -> tuple[str, float, str] | None:
    if config.exit_days:
        point = next((row for row in event.future if row[0] == config.exit_days), None)
        return (point[1], point[2], f"hold_{config.exit_days}d") if point else None
    stop = event.open*(1.0-config.stop_loss) if config.stop_loss is not None else None
    take = event.open*(1.0+config.take_profit) if config.take_profit is not None else None
    if stop is not None and event.low <= stop:
        return event.date, stop, "stop"
    if take is not None and event.high >= take:
        return event.date, take, "take"
    return event.date, event.close, "close"


def simulate(events: Sequence[Event], markets: dict[str, Market], config: Config) -> list[Trade]:
    grouped: dict[str, list[Event]] = defaultdict(list)
    for event in events:
        market = markets.get(event.date)
        if market is not None and passes(event, market, config):
            grouped[event.date].append(event)
    unavailable_through = ""
    trades: list[Trade] = []
    for date in sorted(grouped):
        if date <= unavailable_through:
            continue
        event = min(grouped[date], key=lambda row: rank_key(row, config.rank))
        exit_data = exit_for(event, config)
        quantity = int(CAPITAL//event.open)
        if exit_data is None or quantity <= 0:
            continue
        exit_date, exit_price, reason = exit_data
        invested = quantity*event.open
        gross = quantity*(exit_price-event.open)
        net = gross-invested*config.roundtrip_cost
        trades.append(Trade(
            date=date, exit_date=exit_date, symbol=event.symbol, entry=event.open, exit=exit_price,
            quantity=quantity, invested=invested, gross_pnl=gross, net_pnl=net,
            net_return_on_capital=net/CAPITAL, reason=reason, gap=event.gap,
            avg_dollar_volume20=event.avg_dollar_volume20, avg_range20=event.avg_range20,
            prev_return5=event.prev_return5, market_open_vs_sma5=markets[date].open_vs_sma5,
        ))
        unavailable_through = exit_date
    return trades


def metrics(trades: Sequence[Trade]) -> Metrics:
    if not trades:
        return Metrics(0, 0, 0.0, None, None, None, None, 0.0, 0.0, None, None, None, None)
    pnls = [row.net_pnl for row in trades]
    gains = sum(value for value in pnls if value > 0)
    losses = -sum(value for value in pnls if value < 0)
    equity = peak = drawdown = 0.0
    for pnl in pnls:
        equity += pnl
        peak = max(peak, equity)
        drawdown = max(drawdown, peak-equity)
    years: dict[str, float] = defaultdict(float)
    symbols: dict[str, int] = defaultdict(int)
    months: dict[str, int] = defaultdict(int)
    for trade in trades:
        years[trade.date[:4]] += trade.net_pnl
        symbols[trade.symbol] += 1
        months[trade.date[:7]] += 1
    invested = sum(row.invested for row in trades)
    return Metrics(
        trades=len(trades), active_days=len({row.date for row in trades}), total_pnl=sum(pnls),
        avg_pnl=statistics.mean(pnls), median_pnl=statistics.median(pnls),
        win_rate=sum(value > 0 for value in pnls)/len(pnls),
        profit_factor=gains/losses if losses else (math.inf if gains else None),
        cash_mdd=drawdown, mdd_on_capital=drawdown/CAPITAL,
        break_even_roundtrip_cost=sum(row.gross_pnl for row in trades)/invested if invested else None,
        positive_year_share=sum(value > 0 for value in years.values())/len(years),
        max_symbol_share=max(symbols.values())/len(trades), max_month_share=max(months.values())/len(trades),
    )


def scoped(trades: Sequence[Trade], start: str, end: str) -> list[Trade]:
    return [row for row in trades if start <= row.date <= end]


WINDOWS = {
    "train_2011_2018": ("2011-01-01", "2018-12-31"),
    "validation_2019_2023": ("2019-01-01", "2023-12-31"),
    "test_pre_nxt_2024_20250303": ("2024-01-01", "2025-03-03"),
    "post_nxt_20250304_2026": (NXT_START, "2026-12-31"),
    "recent_2026": ("2026-01-01", "2026-12-31"),
    "full": ("2011-01-01", "2026-12-31"),
}


def window_metrics(trades: Sequence[Trade]) -> dict[str, Metrics]:
    return {name: metrics(scoped(trades, *bounds)) for name, bounds in WINDOWS.items()}


def selection_score(blocks: dict[str, Metrics]) -> float:
    train, validation = blocks["train_2011_2018"], blocks["validation_2019_2023"]
    if (
        train.trades < 40 or validation.trades < 25 or train.total_pnl <= 0 or validation.total_pnl <= 0
        or train.profit_factor is None or validation.profit_factor is None
    ):
        return -math.inf
    pf_floor = min(float(train.profit_factor), float(validation.profit_factor), 5.0)
    return pf_floor*math.log1p(min(train.trades, validation.trades))-0.3*(train.mdd_on_capital+validation.mdd_on_capital)


def diagnostic_score(blocks: dict[str, Metrics]) -> float:
    train, validation = blocks["train_2011_2018"], blocks["validation_2019_2023"]
    pf = min(float(train.profit_factor or 0), float(validation.profit_factor or 0), 5.0)
    return pf*math.log1p(min(train.trades, validation.trades))+float(train.total_pnl > 0)+float(validation.total_pnl > 0)


def entry_ablations() -> list[Ablation]:
    result = [Ablation("anchor", ())]
    def add(label: str, **changes: Any) -> None:
        result.append(Ablation(label, tuple(sorted(changes.items()))))
    for value in (None, 0.0, -0.005, -0.015, -0.02, -0.03): add(f"market_max_{value}", market_max=value)
    add("market_band_-4_-1", market_min=-0.04, market_max=-0.01)
    add("market_band_-3_-05", market_min=-0.03, market_max=-0.005)
    for value in (-0.04, -0.03, -0.02): add(f"index_gap_floor_{value}", index_gap_min=value)
    for value in (-0.03, -0.04, -0.06, -0.07, -0.08): add(f"gap_{value}", gap_max=value)
    for value in (-0.10, -0.12, -0.15): add(f"gap_floor_{value}", gap_min=value)
    for low, high in ((500,8000),(1000,10000),(2000,8000),(1000,6000),(3000,8000),(1000,15000)):
        add(f"price_{low}_{high}", min_price=float(low), max_price=float(high))
    for value in (0.5,0.65,1.0,1.25,1.5): add(f"volume_max_{value}", prev_vol_ratio_max=value)
    for value in (100_000_000,300_000_000,500_000_000,1_000_000_000): add(f"adv_min_{value}", min_dollar_volume=float(value))
    for value in (0.04,0.06,0.08,0.10,0.15): add(f"range_max_{value}", avg_range_max=value)
    for value in (0.03,0.05,0.08): add(f"range_min_{value}", avg_range_min=value)
    for low, high in ((-0.20,0.0),(-0.10,0.0),(0.0,0.10),(0.0,0.20),(-0.05,0.05)):
        add(f"prev5_{low}_{high}", prev_return5_min=low, prev_return5_max=high)
    for low, high in ((None,0.25),(None,0.5),(0.5,None),(0.75,None)):
        add(f"close_location_{low}_{high}", close_location_min=low, close_location_max=high)
    for low, high in ((None,3),(None,5),(None,10),(2,None),(5,None),(10,None)):
        add(f"gap5_count_{low}_{high}", gap5_count_min=low, gap5_count_max=high)
    for rank in ("highest_liquidity","most_negative_gap","mildest_gap","quiet_volume","gap_over_range","prior_strength"):
        add(f"rank_{rank}", rank=rank)
    return result


def apply_changes(base: Config, label: str, changes: Iterable[tuple[str, Any]]) -> Config:
    payload = dict(changes)
    return replace(base, name=label, **payload)


def config_key(config: Config) -> tuple[Any, ...]:
    return tuple(getattr(config, field.name) for field in fields(Config) if field.name not in {"name","roundtrip_cost"})


def candidate_entries(events: Sequence[Event], markets: dict[str, Market]) -> tuple[list[tuple[float,float,Config,dict[str,Metrics],tuple[tuple[str,Any],...]]], list[dict[str,Any]]]:
    base = anchor_config()
    first: list[tuple[float,float,Config,dict[str,Metrics],tuple[tuple[str,Any],...]]] = []
    for ablation in entry_ablations():
        config = apply_changes(base, ablation.label, ablation.changes)
        blocks = window_metrics(simulate(events, markets, config))
        first.append((selection_score(blocks), diagnostic_score(blocks), config, blocks, ablation.changes))
    first.sort(key=lambda row: (math.isfinite(row[0]), row[0] if math.isfinite(row[0]) else row[1]), reverse=True)

    top = first[:24]
    combined: list[tuple[float,float,Config,dict[str,Metrics],tuple[tuple[str,Any],...]]] = list(first)
    seen = {config_key(row[2]) for row in combined}
    for size, source in ((2,top[:20]),(3,top[:10])):
        from itertools import combinations
        for combo in combinations(source, size):
            merged: dict[str,Any] = {}
            compatible = True
            labels = []
            for row in combo:
                labels.append(row[2].name)
                for key,value in row[4]:
                    if key in merged and merged[key] != value:
                        compatible = False
                    merged[key] = value
            if not compatible or not merged:
                continue
            config = apply_changes(base, "+".join(labels), tuple(sorted(merged.items())))
            key = config_key(config)
            if key in seen:
                continue
            seen.add(key)
            blocks = window_metrics(simulate(events, markets, config))
            combined.append((selection_score(blocks), diagnostic_score(blocks), config, blocks, tuple(sorted(merged.items()))))
    combined.sort(key=lambda row: (math.isfinite(row[0]), row[0] if math.isfinite(row[0]) else row[1]), reverse=True)
    payload = [search_row(row) for row in combined[:100]]
    return combined, payload


def exit_candidates(entry_rows: Sequence[tuple[float,float,Config,dict[str,Metrics],tuple[tuple[str,Any],...]]], events: Sequence[Event], markets: dict[str,Market]) -> list[tuple[float,float,Config,dict[str,Metrics],tuple[tuple[str,Any],...]]]:
    policies = [
        (0,0.0225,0.12),(0,0.015,0.12),(0,0.02,0.18),(0,0.025,0.18),(0,0.03,0.12),
        (0,0.04,0.18),(0,None,0.12),(0,0.0225,None),(0,None,None),
        (1,None,None),(3,None,None),(5,None,None),
    ]
    result = []
    seen: set[tuple[Any,...]] = set()
    for entry in entry_rows[:15]:
        for days,stop,take in policies:
            config = replace(entry[2], name=f"{entry[2].name}_exit{days}_stop{stop}_take{take}", exit_days=days, stop_loss=stop, take_profit=take)
            key = config_key(config)
            if key in seen:
                continue
            seen.add(key)
            blocks = window_metrics(simulate(events, markets, config))
            result.append((selection_score(blocks), diagnostic_score(blocks), config, blocks, entry[4]))
    result.sort(key=lambda row: (math.isfinite(row[0]), row[0] if math.isfinite(row[0]) else row[1]), reverse=True)
    return result


def search_row(row: tuple[float,float,Config,dict[str,Metrics],tuple[tuple[str,Any],...]]) -> dict[str,Any]:
    strict, diagnostic, config, blocks, _ = row
    return {
        "passed_pretest_gate": math.isfinite(strict),
        "score": strict if math.isfinite(strict) else diagnostic,
        "config": asdict(config),
        "train": asdict(blocks["train_2011_2018"]),
        "validation": asdict(blocks["validation_2019_2023"]),
    }


def missed_winners(trades: Sequence[Trade], share: float) -> Metrics:
    winners = sorted((row for row in trades if row.net_pnl > 0), key=lambda row: row.net_pnl, reverse=True)
    removed = set(winners[:int(len(winners)*share)])
    return metrics([row for row in trades if row not in removed])


def monthly_bootstrap_positive_probability(trades: Sequence[Trade], *, samples: int=2000, seed: int=20260718) -> float | None:
    months: dict[str,float] = defaultdict(float)
    for trade in trades:
        months[trade.date[:7]] += trade.net_pnl
    values = list(months.values())
    if len(values) < 3:
        return None
    rng = random.Random(seed)
    positive = 0
    for _ in range(samples):
        positive += sum(rng.choice(values) for _ in values) > 0
    return positive/samples


def evaluation(events: Sequence[Event], markets: dict[str,Market], config: Config) -> dict[str,Any]:
    trades = simulate(events, markets, config)
    windows = {}
    for name,bounds in WINDOWS.items():
        rows = scoped(trades,*bounds)
        windows[name] = {
            "metrics": asdict(metrics(rows)),
            "miss_top_winners_10pct": asdict(missed_winners(rows,0.10)),
            "miss_top_winners_25pct": asdict(missed_winners(rows,0.25)),
            "monthly_bootstrap_positive_probability": monthly_bootstrap_positive_probability(rows),
        }
    return {"config":asdict(config),"windows":windows}


def profile(config: Config, name: str) -> Config:
    costs = {"base":0.0035,"realistic":0.0075,"harsh":0.0135,"extreme":0.0245}
    return replace(config,name=f"{config.name}_{name}",roundtrip_cost=costs[name])


def holdout_diagnostics(rows: Sequence[tuple[float,float,Config,dict[str,Metrics],tuple[tuple[str,Any],...]]], events: Sequence[Event], markets: dict[str,Market]) -> dict[str,Any]:
    diagnostics = []
    for row in rows[:50]:
        config = row[2]
        all_trades = simulate(events,markets,config)
        pre = metrics(scoped(all_trades,*WINDOWS["test_pre_nxt_2024_20250303"]))
        post_rows = scoped(all_trades,*WINDOWS["post_nxt_20250304_2026"])
        post = metrics(post_rows)
        miss = missed_winners(post_rows,0.25)
        robust = bool(
            math.isfinite(row[0]) and pre.total_pnl > 0 and (pre.profit_factor or 0)>1
            and post.trades>=8 and post.total_pnl>0 and (post.profit_factor or 0)>1
            and miss.total_pnl>0
        )
        diagnostics.append({"config":asdict(config),"pre_nxt":asdict(pre),"post_nxt":asdict(post),"post_nxt_miss25":asdict(miss),"robust":robust})
    return {
        "evaluated_pretest_top":len(diagnostics),
        "positive_pre_nxt":sum(row["pre_nxt"]["total_pnl"]>0 for row in diagnostics),
        "positive_post_nxt":sum(row["post_nxt"]["total_pnl"]>0 for row in diagnostics),
        "robust_all_checks":sum(row["robust"] for row in diagnostics),
        "robust_rows":[row for row in diagnostics if row["robust"]][:10],
    }


def json_safe(value: Any) -> Any:
    if isinstance(value,float) and (math.isnan(value) or math.isinf(value)):
        return None
    if isinstance(value,dict): return {key:json_safe(item) for key,item in value.items()}
    if isinstance(value,(list,tuple)): return [json_safe(item) for item in value]
    return value


def markdown(payload: dict[str,Any]) -> str:
    lines = [
        "# KR Broad Strategy Research", "",
        f"- events: `{payload['event_rows']}` / market days: `{payload['market_days']}`",
        f"- entry configs: `{payload['entry_configs_tested']}` / exit configs: `{payload['exit_configs_tested']}`",
        f"- selected without 2024+: `{payload['selected_config']['name']}`",
        f"- final live candidate accepted: `{payload['final_live_candidate_accepted']}`", "",
        "## Harsh comparison", "",
        "| strategy | window | trades | pnl | PF | MDD/capital | win |", "|---|---|---:|---:|---:|---:|---:|",
    ]
    for strategy in ("baseline","selected"):
        evaluation_block = payload["evaluations"][strategy]["harsh"]
        for window in ("train_2011_2018","validation_2019_2023","test_pre_nxt_2024_20250303","post_nxt_20250304_2026","recent_2026"):
            m=evaluation_block["windows"][window]["metrics"]
            pf="n/a" if m["profit_factor"] is None else f"{m['profit_factor']:.2f}"
            lines.append(f"| {strategy} | {window} | {m['trades']} | {m['total_pnl']:,.0f} | {pf} | {m['mdd_on_capital']*100:.1f}% | {((m['win_rate'] or 0)*100):.1f}% |")
    lines += ["", "## Holdout diagnostics", ""]
    for key,value in payload["holdout_diagnostics"].items():
        if key != "robust_rows": lines.append(f"- {key}: `{value}`")
    lines += ["", "Daily OHLC uses stop-first when stop and take are both touched. Current-universe candles retain survivorship bias.", ""]
    return "\n".join(lines)


def main() -> int:
    parser=argparse.ArgumentParser(description="Broad Korean strategy research; never sends orders")
    parser.add_argument("--db-path",default=DEFAULT_DB)
    parser.add_argument("--out-dir",default=DEFAULT_OUT_DIR)
    parser.add_argument("--start",default="2011-01-01")
    parser.add_argument("--end",default="2026-07-16")
    args=parser.parse_args()
    events=load_events(args.db_path,start=args.start,end=args.end)
    index_rows=fetch_kosdaq_index(args.start,args.end)
    markets=build_markets(events,index_rows)
    entry_rows,entry_top=candidate_entries(events,markets)
    exit_rows=exit_candidates(entry_rows,events,markets)
    selected_row=exit_rows[0]
    selected=selected_row[2]
    diagnostics=holdout_diagnostics(exit_rows,events,markets)
    evaluations={
        label:{name:evaluation(events,markets,profile(config,name)) for name in ("base","realistic","harsh","extreme")}
        for label,config in (("baseline",anchor_config()),("selected",selected))
    }
    selected_harsh=evaluations["selected"]["harsh"]["windows"]
    post=selected_harsh["post_nxt_20250304_2026"]
    final_accepted=bool(
        math.isfinite(selected_row[0]) and diagnostics["robust_all_checks"]>0
        and post["metrics"]["mdd_on_capital"]<=0.30
        and (post["monthly_bootstrap_positive_probability"] or 0)>=0.70
    )
    payload={
        "generated_at":datetime.now().astimezone().isoformat(),"db_path":args.db_path,
        "event_rows":len(events),"market_days":len(markets),"selection_cutoff":"2023-12-31",
        "nxt_regime_start":NXT_START,"entry_configs_tested":len(entry_rows),"exit_configs_tested":len(exit_rows),
        "selected_config":asdict(selected),"selected_pretest_passed":math.isfinite(selected_row[0]),
        "final_live_candidate_accepted":final_accepted,"entry_search_top100":entry_top,
        "exit_search_top100":[search_row(row) for row in exit_rows[:100]],
        "holdout_diagnostics":diagnostics,"evaluations":evaluations,
        "limits":[
            "current surviving symbol universe creates survivorship bias",
            "daily OHLC cannot reproduce opening-auction fills or stop/take order",
            "historical point-in-time Toss warnings and VI flags are unavailable",
            "NXT routing and venue-specific fills are absent from daily candles",
        ],
    }
    out=Path(args.out_dir); out.mkdir(parents=True,exist_ok=True)
    (out/"kr_broad_strategy_research.json").write_text(json.dumps(json_safe(payload),ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf-8")
    (out/"kr_broad_strategy_research.md").write_text(markdown(payload),encoding="utf-8")
    print(json.dumps({"out_dir":str(out),"events":len(events),"entry_configs":len(entry_rows),"exit_configs":len(exit_rows),"selected":asdict(selected),"final_live_candidate_accepted":final_accepted,"post_nxt_harsh":post["metrics"]},ensure_ascii=False))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
