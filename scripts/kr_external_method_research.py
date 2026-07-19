#!/usr/bin/env python3
"""Reproduce external Korean-equity methods against the local daily-candle DB.

This module is research-only. It never imports the live trader and never calls
account or order endpoints. Stock features use the current open plus data that
ended no later than the previous session. Results after 2023 are a reused
diagnostic, not an untouched holdout.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import sqlite3
import statistics
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from statistics import NormalDist
from typing import Any, Sequence

from kr_broad_strategy_research import (
    CAPITAL,
    Market,
    Trade,
    WINDOWS,
    build_markets,
    json_safe,
    metrics,
    missed_winners,
    monthly_bootstrap_positive_probability,
    scoped,
)
from simple_gap_strategy_audit import fetch_kosdaq_index


DEFAULT_DB = "data/edge_research_universe_15y.sqlite3"
DEFAULT_OUT_DIR = "data/kr_external_method_research"
COSTS = {"base": 0.0035, "realistic": 0.0075, "harsh": 0.0135, "extreme": 0.0245}


@dataclass(frozen=True, slots=True)
class ResearchEvent:
    date: str
    symbol: str
    prev_close: float
    open: float
    high: float
    low: float
    close: float
    next_date: str | None
    next_open: float | None
    gap: float
    prev_vol_ratio: float
    avg_dollar_volume20: float
    prev_return20: float
    beta60: float
    ivol60: float
    history60: int
    max_return20: float
    amihud20: float
    volume_z50: float


@dataclass(frozen=True, slots=True)
class Method:
    name: str
    universe: str = "anchor"
    filter_rule: str = "none"
    rank: str = "lowest_price"
    exit_rule: str = "same_day_bracket"
    positions: int = 1
    fractional_portfolio_proxy: bool = False
    use_market_gate: bool = True


def _market_rows(index_rows: Sequence[dict[str, Any]]) -> list[tuple[str, float]]:
    ordered = sorted(index_rows, key=lambda row: str(row["date"]))
    result: list[tuple[str, float]] = []
    previous_close: float | None = None
    for row in ordered:
        close = float(row["close"])
        market_return = close / previous_close - 1.0 if previous_close else 0.0
        result.append((str(row["date"]), market_return))
        previous_close = close
    return result


def load_events(
    db_path: str,
    index_rows: Sequence[dict[str, Any]],
    *,
    start: str,
    end: str,
) -> list[ResearchEvent]:
    """Load open-known features; every rolling frame ends at t-1 or earlier."""
    sql = """
    WITH lagged AS (
      SELECT
        c.symbol,
        substr(c.timestamp,1,10) AS date,
        CAST(c.open_price AS REAL) AS open_price,
        CAST(c.high_price AS REAL) AS high_price,
        CAST(c.low_price AS REAL) AS low_price,
        CAST(c.close_price AS REAL) AS close_price,
        CAST(c.volume AS REAL) AS volume,
        k.market_return,
        LAG(CAST(c.close_price AS REAL),1) OVER w AS prev_close,
        LAG(CAST(c.close_price AS REAL),21) OVER w AS close_lag21,
        LAG(CAST(c.volume AS REAL),1) OVER w AS prev_volume,
        LEAD(substr(c.timestamp,1,10),1) OVER w AS next_date,
        LEAD(CAST(c.open_price AS REAL),1) OVER w AS next_open
      FROM candle_cache c
      JOIN temp.kosdaq_daily k ON k.date=substr(c.timestamp,1,10)
      WHERE c.interval='1d'
      WINDOW w AS (PARTITION BY c.symbol ORDER BY c.timestamp)
    ), returns AS (
      SELECT *,
        close_price/NULLIF(prev_close,0)-1.0 AS stock_return,
        ABS(close_price/NULLIF(prev_close,0)-1.0)
          / NULLIF(close_price*volume,0) AS daily_amihud
      FROM lagged
    ), rolling AS (
      SELECT *,
        AVG(volume) OVER (
          PARTITION BY symbol ORDER BY date ROWS BETWEEN 21 PRECEDING AND 2 PRECEDING
        ) AS avg_prev20_volume,
        COUNT(*) OVER (
          PARTITION BY symbol ORDER BY date ROWS BETWEEN 21 PRECEDING AND 2 PRECEDING
        ) AS prev_count20,
        AVG(close_price*volume) OVER (
          PARTITION BY symbol ORDER BY date ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING
        ) AS avg_dollar_volume20,
        AVG(volume) OVER (
          PARTITION BY symbol ORDER BY date ROWS BETWEEN 51 PRECEDING AND 2 PRECEDING
        ) AS volume_mean50,
        AVG(volume*volume) OVER (
          PARTITION BY symbol ORDER BY date ROWS BETWEEN 51 PRECEDING AND 2 PRECEDING
        ) AS volume_square_mean50,
        COUNT(*) OVER (
          PARTITION BY symbol ORDER BY date ROWS BETWEEN 51 PRECEDING AND 2 PRECEDING
        ) AS volume_count50,
        AVG(daily_amihud) OVER (
          PARTITION BY symbol ORDER BY date ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING
        ) AS amihud20,
        MAX(stock_return) OVER (
          PARTITION BY symbol ORDER BY date ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING
        ) AS max_return20,
        AVG(stock_return) OVER (
          PARTITION BY symbol ORDER BY date ROWS BETWEEN 60 PRECEDING AND 1 PRECEDING
        ) AS stock_mean60,
        AVG(stock_return*stock_return) OVER (
          PARTITION BY symbol ORDER BY date ROWS BETWEEN 60 PRECEDING AND 1 PRECEDING
        ) AS stock_square_mean60,
        AVG(market_return) OVER (
          PARTITION BY symbol ORDER BY date ROWS BETWEEN 60 PRECEDING AND 1 PRECEDING
        ) AS market_mean60,
        AVG(market_return*market_return) OVER (
          PARTITION BY symbol ORDER BY date ROWS BETWEEN 60 PRECEDING AND 1 PRECEDING
        ) AS market_square_mean60,
        AVG(stock_return*market_return) OVER (
          PARTITION BY symbol ORDER BY date ROWS BETWEEN 60 PRECEDING AND 1 PRECEDING
        ) AS cross_mean60,
        COUNT(stock_return) OVER (
          PARTITION BY symbol ORDER BY date ROWS BETWEEN 60 PRECEDING AND 1 PRECEDING
        ) AS history60
      FROM returns
    )
    SELECT * FROM rolling
    WHERE date BETWEEN ? AND ? AND prev_count20=20
      AND prev_close >= 500 AND open_price > 0
      AND high_price >= MAX(open_price,close_price)
      AND low_price <= MIN(open_price,close_price)
      AND avg_prev20_volume > 0 AND avg_dollar_volume20 > 0
      AND (open_price/prev_close-1.0) <= -0.02
    ORDER BY date,symbol
    """
    connection = sqlite3.connect(f"file:{Path(db_path).resolve()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute(
            "CREATE TEMP TABLE kosdaq_daily (date TEXT PRIMARY KEY, market_return REAL NOT NULL)"
        )
        connection.executemany(
            "INSERT INTO kosdaq_daily(date,market_return) VALUES (?,?)",
            _market_rows(index_rows),
        )
        rows = connection.execute(sql, (start, end)).fetchall()
    finally:
        connection.close()

    result: list[ResearchEvent] = []
    for row in rows:
        stock_mean = float(row["stock_mean60"] or 0.0)
        market_mean = float(row["market_mean60"] or 0.0)
        stock_variance = max(
            0.0, float(row["stock_square_mean60"] or 0.0) - stock_mean * stock_mean
        )
        market_variance = max(
            0.0,
            float(row["market_square_mean60"] or 0.0) - market_mean * market_mean,
        )
        covariance = float(row["cross_mean60"] or 0.0) - stock_mean * market_mean
        beta = covariance / market_variance if market_variance > 1e-12 else 1.0
        residual_variance = max(
            0.0,
            stock_variance - covariance * covariance / market_variance
            if market_variance > 1e-12
            else stock_variance,
        )
        volume_mean = float(row["volume_mean50"] or 0.0)
        volume_variance = max(
            0.0, float(row["volume_square_mean50"] or 0.0) - volume_mean * volume_mean
        )
        volume_std = math.sqrt(volume_variance)
        prev_close = float(row["prev_close"])
        result.append(
            ResearchEvent(
                date=str(row["date"]),
                symbol=str(row["symbol"]),
                prev_close=prev_close,
                open=float(row["open_price"]),
                high=float(row["high_price"]),
                low=float(row["low_price"]),
                close=float(row["close_price"]),
                next_date=str(row["next_date"]) if row["next_date"] else None,
                next_open=float(row["next_open"]) if row["next_open"] else None,
                gap=float(row["open_price"]) / prev_close - 1.0,
                prev_vol_ratio=float(row["prev_volume"]) / float(row["avg_prev20_volume"]),
                avg_dollar_volume20=float(row["avg_dollar_volume20"]),
                prev_return20=prev_close / float(row["close_lag21"] or prev_close) - 1.0,
                beta60=beta,
                ivol60=math.sqrt(residual_variance),
                history60=int(row["history60"] or 0),
                max_return20=float(row["max_return20"] or 0.0),
                amihud20=float(row["amihud20"] or 0.0),
                volume_z50=(float(row["prev_volume"]) - volume_mean) / volume_std
                if volume_std > 0 and int(row["volume_count50"] or 0) >= 40
                else 0.0,
            )
        )
    return result


def methods() -> list[Method]:
    """Coarse, declared hypotheses; no threshold is selected from 2024+ results."""
    return [
        Method("anchor"),
        Method("beta_residual_gap3", filter_rule="beta_residual_gap3"),
        Method("beta_residual_gap5", filter_rule="beta_residual_gap5"),
        Method("rank_beta_residual", rank="beta_residual"),
        Method("ivol_bottom_half", filter_rule="ivol_bottom_half"),
        Method("rank_low_ivol", rank="low_ivol"),
        Method("avoid_high_max_third", filter_rule="avoid_high_max_third"),
        Method("rank_low_max", rank="low_max"),
        Method("rank_low_amihud", rank="low_amihud"),
        Method("rank_high_amihud", rank="high_amihud"),
        Method("volume_z50_below_minus1", filter_rule="volume_z50_below_minus1"),
        Method("rank_low_volume_z50", rank="low_volume_z50"),
        Method("beta_ivol_combo", filter_rule="beta_ivol_combo", rank="beta_residual"),
        Method("rank_gap_momentum_z", rank="gap_momentum_z"),
        Method("anchor_next_open", exit_rule="next_open_close_stop"),
        Method(
            "public_gap_mom_top1",
            universe="public_gap_mom",
            rank="gap_momentum_z",
            exit_rule="next_open_close_stop",
            use_market_gate=False,
        ),
        Method(
            "public_gap_mom_top1_guard",
            universe="public_gap_mom",
            rank="gap_momentum_z",
            exit_rule="next_open_close_stop",
        ),
        Method(
            "public_gap_mom_top5_fractional",
            universe="public_gap_mom",
            rank="gap_momentum_z",
            exit_rule="next_open_close_stop",
            positions=5,
            fractional_portfolio_proxy=True,
            use_market_gate=False,
        ),
        Method(
            "public_gap_only_top5_fractional",
            universe="public_gap_mom",
            rank="gap_only",
            exit_rule="next_open_close_stop",
            positions=5,
            fractional_portfolio_proxy=True,
            use_market_gate=False,
        ),
        Method(
            "public_gap_mom_top5_guard_fractional",
            universe="public_gap_mom",
            rank="gap_momentum_z",
            exit_rule="next_open_close_stop",
            positions=5,
            fractional_portfolio_proxy=True,
        ),
    ]


def _quantile(values: Sequence[float], probability: float) -> float:
    if not values:
        return math.nan
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def base_passes(event: ResearchEvent, market: Market, method: Method) -> bool:
    if method.use_market_gate and market.open_vs_sma5 > -0.01:
        return False
    if method.universe == "anchor":
        return (
            event.gap <= -0.05
            and 1000.0 <= event.prev_close <= 8000.0
            and event.open <= 8000.0
            and 0.0 <= event.prev_vol_ratio < 0.8
        )
    if method.universe == "public_gap_mom":
        return (
            -0.15 <= event.gap <= -0.03
            and event.prev_return20 <= 0.0
            and 0.0 <= event.prev_vol_ratio < 2.0
            and event.prev_close >= 500.0
        )
    raise ValueError(f"unknown universe: {method.universe}")


def market_residual_gap(event: ResearchEvent, market: Market) -> float:
    return event.gap - event.beta60 * market.index_gap


def apply_filter(
    candidates: Sequence[ResearchEvent], market: Market, rule: str
) -> list[ResearchEvent]:
    if rule == "none":
        return list(candidates)
    history = [event for event in candidates if event.history60 >= 40]
    if rule == "beta_residual_gap3":
        return [event for event in history if market_residual_gap(event, market) <= -0.03]
    if rule == "beta_residual_gap5":
        return [event for event in history if market_residual_gap(event, market) <= -0.05]
    if rule == "ivol_bottom_half":
        cutoff = _quantile([event.ivol60 for event in history], 0.5)
        return [event for event in history if event.ivol60 <= cutoff]
    if rule == "avoid_high_max_third":
        cutoff = _quantile([event.max_return20 for event in candidates], 2.0 / 3.0)
        return [event for event in candidates if event.max_return20 <= cutoff]
    if rule == "volume_z50_below_minus1":
        return [event for event in candidates if event.volume_z50 <= -1.0]
    if rule == "beta_ivol_combo":
        residual = [
            event for event in history if market_residual_gap(event, market) <= -0.03
        ]
        cutoff = _quantile([event.ivol60 for event in residual], 0.5)
        return [event for event in residual if event.ivol60 <= cutoff]
    raise ValueError(f"unknown filter rule: {rule}")


def _z_scores(events: Sequence[ResearchEvent], field: str) -> dict[str, float]:
    values = [float(getattr(event, field)) for event in events]
    mean = statistics.fmean(values) if values else 0.0
    std = statistics.pstdev(values) if len(values) > 1 else 0.0
    return {
        event.symbol: (float(getattr(event, field)) - mean) / std if std > 0 else 0.0
        for event in events
    }


def ranked(
    candidates: Sequence[ResearchEvent], rank: str, market: Market
) -> list[ResearchEvent]:
    if rank == "gap_momentum_z":
        gap_z = _z_scores(candidates, "gap")
        momentum_z = _z_scores(candidates, "prev_return20")
        return sorted(
            candidates,
            key=lambda event: (gap_z[event.symbol] + momentum_z[event.symbol], event.symbol),
        )
    keys = {
        "lowest_price": lambda event: event.open,
        "beta_residual": lambda event: market_residual_gap(event, market),
        "low_ivol": lambda event: event.ivol60 if event.history60 >= 40 else math.inf,
        "low_max": lambda event: event.max_return20,
        "low_amihud": lambda event: event.amihud20,
        "high_amihud": lambda event: -event.amihud20,
        "low_volume_z50": lambda event: event.volume_z50,
        "gap_only": lambda event: event.gap,
    }
    if rank not in keys:
        raise ValueError(f"unknown rank: {rank}")
    return sorted(candidates, key=lambda event: (keys[rank](event), event.symbol))


def exit_for(
    event: ResearchEvent,
    rule: str,
    *,
    execution_model: str,
    last_market_date: str,
) -> tuple[str, float, str] | None:
    if execution_model not in {"reference", "adverse"}:
        raise ValueError(f"unknown execution model: {execution_model}")
    if rule == "same_day_bracket":
        stop = event.open * (1.0 - 0.0225)
        take = event.open * (1.0 + 0.12)
        if event.low <= stop:
            return event.date, stop * (0.99 if execution_model == "adverse" else 1.0), "stop"
        if execution_model == "reference" and event.high >= take:
            return event.date, take, "take"
        if execution_model == "adverse" and event.close >= take:
            return event.date, take, "take_close_confirmed"
        return (
            event.date,
            event.close * (0.995 if execution_model == "adverse" else 1.0),
            "close_proxy",
        )
    if rule == "next_open_close_stop":
        if event.close <= event.open * 0.98:
            return (
                event.date,
                event.close * (0.995 if execution_model == "adverse" else 1.0),
                "close_stop",
            )
        if event.next_open is not None and event.next_date is not None:
            return (
                event.next_date,
                event.next_open * (0.995 if execution_model == "adverse" else 1.0),
                "next_open",
            )
        if event.date < last_market_date:
            return event.date, 0.0, "missing_next_open_total_loss"
        return None
    raise ValueError(f"unknown exit rule: {rule}")


def _trade_from_single(
    event: ResearchEvent,
    market: Market,
    method: Method,
    *,
    roundtrip_cost: float,
    execution_model: str,
    last_market_date: str,
) -> Trade | None:
    entry = event.open * (1.005 if execution_model == "adverse" else 1.0)
    quantity = int(CAPITAL // entry)
    exit_data = exit_for(
        event,
        method.exit_rule,
        execution_model=execution_model,
        last_market_date=last_market_date,
    )
    if quantity <= 0 or exit_data is None:
        return None
    exit_date, exit_price, reason = exit_data
    invested = quantity * entry
    gross = quantity * (exit_price - entry)
    net = gross - invested * roundtrip_cost
    return Trade(
        date=event.date,
        exit_date=exit_date,
        symbol=event.symbol,
        entry=entry,
        exit=exit_price,
        quantity=quantity,
        invested=invested,
        gross_pnl=gross,
        net_pnl=net,
        net_return_on_capital=net / CAPITAL,
        reason=reason,
        gap=event.gap,
        avg_dollar_volume20=event.avg_dollar_volume20,
        avg_range20=event.ivol60,
        prev_return5=event.prev_return20,
        market_open_vs_sma5=market.open_vs_sma5,
    )


def _trade_from_fractional_portfolio(
    selected: Sequence[ResearchEvent],
    market: Market,
    method: Method,
    *,
    roundtrip_cost: float,
    execution_model: str,
    last_market_date: str,
) -> Trade | None:
    outcomes: list[tuple[ResearchEvent, str, float, str, float]] = []
    for event in selected:
        entry = event.open * (1.005 if execution_model == "adverse" else 1.0)
        exit_data = exit_for(
            event,
            method.exit_rule,
            execution_model=execution_model,
            last_market_date=last_market_date,
        )
        if exit_data is None:
            continue
        exit_date, exit_price, reason = exit_data
        outcomes.append((event, exit_date, exit_price, reason, entry))
    if not outcomes:
        return None
    gross_return = statistics.fmean(exit_price / entry - 1.0 for _, _, exit_price, _, entry in outcomes)
    net_return = gross_return - roundtrip_cost
    latest_exit = max(exit_date for _, exit_date, _, _, _ in outcomes)
    return Trade(
        date=selected[0].date,
        exit_date=latest_exit,
        symbol=",".join(event.symbol for event, _, _, _, _ in outcomes),
        entry=1.0,
        exit=1.0 + gross_return,
        quantity=int(CAPITAL),
        invested=CAPITAL,
        gross_pnl=CAPITAL * gross_return,
        net_pnl=CAPITAL * net_return,
        net_return_on_capital=net_return,
        reason="fractional_" + "+".join(sorted({reason for _, _, _, reason, _ in outcomes})),
        gap=statistics.fmean(event.gap for event, _, _, _, _ in outcomes),
        avg_dollar_volume20=statistics.fmean(
            event.avg_dollar_volume20 for event, _, _, _, _ in outcomes
        ),
        avg_range20=statistics.fmean(event.ivol60 for event, _, _, _, _ in outcomes),
        prev_return5=statistics.fmean(event.prev_return20 for event, _, _, _, _ in outcomes),
        market_open_vs_sma5=market.open_vs_sma5,
    )


def simulate(
    events: Sequence[ResearchEvent],
    markets: dict[str, Market],
    method: Method,
    *,
    roundtrip_cost: float,
    execution_model: str = "reference",
) -> list[Trade]:
    grouped: dict[str, list[ResearchEvent]] = defaultdict(list)
    for event in events:
        market = markets.get(event.date)
        if market is not None and base_passes(event, market, method):
            grouped[event.date].append(event)
    last_market_date = max(markets) if markets else ""
    unavailable_through = ""
    trades: list[Trade] = []
    for date in sorted(grouped):
        # A next-open exit releases capital at that open, so that day's signal
        # remains executable. Dates strictly before a delayed exit stay blocked.
        if date < unavailable_through:
            continue
        market = markets[date]
        candidates = apply_filter(grouped[date], market, method.filter_rule)
        selected = ranked(candidates, method.rank, market)[: method.positions]
        if not selected:
            continue
        if method.fractional_portfolio_proxy:
            trade = _trade_from_fractional_portfolio(
                selected,
                market,
                method,
                roundtrip_cost=roundtrip_cost,
                execution_model=execution_model,
                last_market_date=last_market_date,
            )
        else:
            trade = _trade_from_single(
                selected[0],
                market,
                method,
                roundtrip_cost=roundtrip_cost,
                execution_model=execution_model,
                last_market_date=last_market_date,
            )
        if trade is not None:
            trades.append(trade)
            unavailable_through = trade.exit_date
    return trades


def window_payload(trades: Sequence[Trade]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for name, bounds in WINDOWS.items():
        rows = scoped(trades, *bounds)
        yearly_pnl: dict[str, float] = defaultdict(float)
        reasons: dict[str, int] = defaultdict(int)
        for trade in rows:
            yearly_pnl[trade.date[:4]] += trade.net_pnl
            reasons[trade.reason] += 1
        result[name] = {
            "metrics": asdict(metrics(rows)),
            "miss_top_winners_25pct": asdict(missed_winners(rows, 0.25)),
            "monthly_bootstrap_positive_probability": monthly_bootstrap_positive_probability(rows),
            "yearly_pnl": dict(sorted(yearly_pnl.items())),
            "exit_reason_counts": dict(sorted(reasons.items())),
        }
    return result


def _pretest_score(trades: Sequence[Trade]) -> float:
    train_rows = scoped(trades, *WINDOWS["train_2011_2018"])
    validation_rows = scoped(trades, *WINDOWS["validation_2019_2023"])
    train = metrics(train_rows)
    validation = metrics(validation_rows)
    train_miss = missed_winners(train_rows, 0.25)
    validation_miss = missed_winners(validation_rows, 0.25)
    if (
        train.trades < 40
        or validation.trades < 25
        or train.total_pnl <= 0
        or validation.total_pnl <= 0
        or train_miss.total_pnl <= 0
        or validation_miss.total_pnl <= 0
        or (train.profit_factor or 0) <= 1
        or (validation.profit_factor or 0) <= 1
    ):
        return -math.inf
    return min(float(train.profit_factor or 0), float(validation.profit_factor or 0), 5.0) * math.log1p(
        min(train.trades, validation.trades)
    ) - 0.35 * (train.mdd_on_capital + validation.mdd_on_capital)


def evaluate_method(
    events: Sequence[ResearchEvent], markets: dict[str, Market], method: Method
) -> dict[str, Any]:
    harsh = simulate(events, markets, method, roundtrip_cost=COSTS["harsh"])
    return {
        "method": asdict(method),
        "pretest_score": _pretest_score(harsh),
        "pretest_passed": math.isfinite(_pretest_score(harsh)),
        "profiles": {
            name: window_payload(simulate(events, markets, method, roundtrip_cost=cost))
            for name, cost in COSTS.items()
        },
        "adverse_harsh": window_payload(
            simulate(
                events,
                markets,
                method,
                roundtrip_cost=COSTS["harsh"],
                execution_model="adverse",
            )
        ),
    }


def _daily_returns(
    trades: Sequence[Trade], dates: Sequence[str], *, start: str, end: str
) -> list[float]:
    pnl = defaultdict(float)
    for trade in trades:
        if start <= trade.date <= end:
            pnl[trade.date] += trade.net_return_on_capital
    return [pnl[date] for date in dates if start <= date <= end]


def _return_moments(values: Sequence[float]) -> tuple[float, float, float, float] | None:
    if len(values) < 3:
        return None
    mean = statistics.fmean(values)
    std = statistics.pstdev(values)
    if std <= 0:
        return None
    centered = [value - mean for value in values]
    skew = statistics.fmean(value**3 for value in centered) / std**3
    kurtosis = statistics.fmean(value**4 for value in centered) / std**4
    return mean / std, math.sqrt(252.0) * mean / std, skew, kurtosis


def deflated_sharpe_diagnostic(
    trades_by_name: dict[str, Sequence[Trade]], market_dates: Sequence[str]
) -> dict[str, Any]:
    """Approximate DSR; sparse non-IID returns prevent an independent significance claim."""
    start, end = "2011-01-01", "2023-12-31"
    rows: dict[str, tuple[list[float], tuple[float, float, float, float]]] = {}
    for name, trades in trades_by_name.items():
        values = _daily_returns(trades, market_dates, start=start, end=end)
        moments = _return_moments(values)
        if moments is not None:
            rows[name] = (values, moments)
    per_period_sharpes = [moments[0] for _, moments in rows.values()]
    trial_sigma = statistics.pstdev(per_period_sharpes) if len(per_period_sharpes) > 1 else 0.0
    trials = max(2, len(per_period_sharpes))
    gamma = 0.5772156649015329
    normal = NormalDist()
    benchmark = trial_sigma * (
        (1.0 - gamma) * normal.inv_cdf(1.0 - 1.0 / trials)
        + gamma * normal.inv_cdf(1.0 - 1.0 / (trials * math.e))
    )
    methods_payload: dict[str, Any] = {}
    for name, (values, (sharpe, annualized, skew, kurtosis)) in rows.items():
        denominator = math.sqrt(
            max(1e-12, 1.0 - skew * sharpe + ((kurtosis - 1.0) / 4.0) * sharpe * sharpe)
        )
        statistic = (sharpe - benchmark) * math.sqrt(len(values) - 1) / denominator
        methods_payload[name] = {
            "annualized_sharpe": annualized,
            "deflated_sharpe_probability": normal.cdf(statistic),
            "observations": len(values),
        }
    return {
        "selection_window": f"{start}~{end}",
        "declared_correlated_trials": len(trades_by_name),
        "effective_trials_in_calculation": len(rows),
        "benchmark_per_period_sharpe": benchmark,
        "independent_significance_claim": False,
        "methods": methods_payload,
    }


def random_rank_benchmark(
    events: Sequence[ResearchEvent],
    markets: dict[str, Market],
    *,
    start: str,
    end: str,
    samples: int = 2000,
    seed: int = 20260718,
) -> dict[str, Any]:
    anchor = methods()[0]
    by_date: dict[str, list[float]] = defaultdict(list)
    last_market_date = max(markets) if markets else ""
    for event in events:
        market = markets.get(event.date)
        if market is None or not (start <= event.date <= end) or not base_passes(event, market, anchor):
            continue
        trade = _trade_from_single(
            event,
            market,
            anchor,
            roundtrip_cost=COSTS["harsh"],
            execution_model="reference",
            last_market_date=last_market_date,
        )
        if trade is not None:
            by_date[event.date].append(trade.net_pnl)
    actual_trades = simulate(events, markets, anchor, roundtrip_cost=COSTS["harsh"])
    actual = metrics(scoped(actual_trades, start, end)).total_pnl
    rng = random.Random(seed)
    totals = [sum(rng.choice(values) for values in by_date.values()) for _ in range(samples)]
    return {
        "window": f"{start}~{end}",
        "candidate_days": len(by_date),
        "samples": samples,
        "anchor_lowest_price_pnl": actual,
        "random_median_pnl": statistics.median(totals) if totals else None,
        "random_p05_pnl": _quantile(totals, 0.05) if totals else None,
        "random_p95_pnl": _quantile(totals, 0.95) if totals else None,
        "probability_random_beats_anchor": sum(total >= actual for total in totals) / len(totals)
        if totals
        else None,
    }


def source_fingerprints(
    db_path: str, index_rows: Sequence[dict[str, Any]]
) -> dict[str, Any]:
    database = Path(db_path).resolve()
    stat = database.stat()
    digest = hashlib.sha256()
    sample_size = 1024 * 1024
    with database.open("rb") as handle:
        digest.update(handle.read(sample_size))
        if stat.st_size > sample_size:
            handle.seek(max(0, stat.st_size - sample_size))
            digest.update(handle.read(sample_size))
    index_payload = json.dumps(
        index_rows, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    ).encode("utf-8")
    return {
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "database_sample_sha256": digest.hexdigest(),
        "database_size_bytes": stat.st_size,
        "kosdaq_index_sha256": hashlib.sha256(index_payload).hexdigest(),
        "kosdaq_index_rows": len(index_rows),
    }


def render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# KR External Method Research",
        "",
        f"- generated: `{payload['generated_at']}`",
        f"- events: `{payload['event_rows']}` / market days: `{payload['market_days']}`",
        f"- declared methods: `{payload['methods_tested']}`",
        "- selection: `2011-01-01~2023-12-31`",
        "- reused diagnostic: `2024-01-01~2026-07-16`",
        f"- live change accepted: `{payload['live_change_accepted']}`",
        "",
        "## Harsh-cost comparison",
        "",
        "| method | window | trades | pnl | PF | MDD/10k | miss top 25% pnl |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for row in payload["evaluations"]:
        name = row["method"]["name"]
        harsh = row["profiles"]["harsh"]
        for window in (
            "validation_2019_2023",
            "test_pre_nxt_2024_20250303",
            "post_nxt_20250304_2026",
            "recent_2026",
        ):
            block = harsh[window]
            metric = block["metrics"]
            pf = "n/a" if metric["profit_factor"] is None else f"{metric['profit_factor']:.2f}"
            lines.append(
                f"| {name} | {window} | {metric['trades']} | {metric['total_pnl']:,.0f} | "
                f"{pf} | {metric['mdd_on_capital'] * 100:.1f}% | "
                f"{block['miss_top_winners_25pct']['total_pnl']:,.0f} |"
            )
    lines.extend(
        [
            "",
            "`fractional` methods are 10,000-won normalized portfolio-return proxies, not executable Korean fractional-share orders.",
            "Daily OHLC uses stop-first for the live anchor and a close-confirmed -2% stop for the public overnight reproduction.",
            "Current-survivor candles, historical warning/VI gaps, and reused 2024+ data prevent live promotion.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="External Korean methods research; no order endpoints")
    parser.add_argument("--db-path", default=DEFAULT_DB)
    parser.add_argument("--out-dir", default=DEFAULT_OUT_DIR)
    parser.add_argument("--start", default="2011-01-01")
    parser.add_argument("--end", default="2026-07-16")
    args = parser.parse_args()

    index_rows = fetch_kosdaq_index(args.start, args.end)
    events = load_events(args.db_path, index_rows, start=args.start, end=args.end)
    markets = build_markets(events, index_rows)
    declared = methods()
    evaluations = [evaluate_method(events, markets, method) for method in declared]
    harsh_trades = {
        method.name: simulate(events, markets, method, roundtrip_cost=COSTS["harsh"])
        for method in declared
    }
    anchor = next(row for row in evaluations if row["method"]["name"] == "anchor")
    anchor_harsh = anchor["profiles"]["harsh"]
    same_day_improvements: list[str] = []
    for row in evaluations:
        spec = row["method"]
        if spec["name"] == "anchor" or spec["exit_rule"] != "same_day_bracket":
            continue
        candidate = row["profiles"]["harsh"]
        if all(
            candidate[window]["metrics"]["total_pnl"]
            > anchor_harsh[window]["metrics"]["total_pnl"]
            and candidate[window]["miss_top_winners_25pct"]["total_pnl"] > 0
            and row["profiles"]["extreme"][window]["metrics"]["total_pnl"] > 0
            for window in ("test_pre_nxt_2024_20250303", "post_nxt_20250304_2026")
        ):
            same_day_improvements.append(spec["name"])
    market_dates = sorted(markets)
    payload = {
        "generated_at": datetime.now().astimezone().isoformat(),
        "db_path": args.db_path,
        "requested_start": args.start,
        "requested_end": args.end,
        "source_fingerprints": source_fingerprints(args.db_path, index_rows),
        "event_rows": len(events),
        "market_days": len(markets),
        "methods_tested": len(declared),
        "pretest_passed": sum(row["pretest_passed"] for row in evaluations),
        "live_change_accepted": False,
        "historical_same_day_improvements": same_day_improvements,
        "evaluations": evaluations,
        "deflated_sharpe_diagnostic": deflated_sharpe_diagnostic(harsh_trades, market_dates),
        "random_rank_benchmarks": [
            random_rank_benchmark(
                events, markets, start="2011-01-01", end="2023-12-31"
            ),
            random_rank_benchmark(
                events, markets, start="2024-01-01", end=args.end
            ),
        ],
        "limits": [
            "current-survivor universe creates survivorship bias",
            "historical Toss warnings, VI flags, and point-in-time delistings are unavailable",
            "daily OHLC cannot reproduce opening-auction queue position or intraday path",
            "official KOSDAQ open gate differs from the live 09:01 snapshot gate",
            "2024+ has already been inspected and is not an untouched holdout",
            "fractional top-five results are normalized research proxies, not executable 10k orders",
            "deflated Sharpe is approximate because sparse daily returns are non-IID and method trials are correlated",
        ],
    }
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "kr_external_method_research.json").write_text(
        json.dumps(json_safe(payload), ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    (out / "kr_external_method_research.md").write_text(
        render_markdown(payload), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "out_dir": str(out),
                "events": len(events),
                "methods": len(declared),
                "pretest_passed": payload["pretest_passed"],
                "historical_same_day_improvements": same_day_improvements,
                "live_change_accepted": False,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
