from __future__ import annotations

import math
import statistics
from collections import defaultdict
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Candidate:
    date: str
    symbol: str
    prev_close: float
    open_price: float
    close_price: float
    high_price: float
    low_price: float
    gap_return: float
    prev_vol_ratio: float
    future_closes: tuple[float | None, ...]


@dataclass(frozen=True, slots=True)
class VariantConfig:
    name: str
    capital: float
    min_price: float
    max_price: float
    gap_threshold: float
    prev_vol_ratio_min: float
    prev_vol_ratio_max: float
    exit_offset: int
    top_n: int
    rank: str
    roundtrip_cost: float
    slippage: float
    stop_loss: float | None = None
    take_profit: float | None = None


@dataclass(frozen=True, slots=True)
class TradeResult:
    date: str
    symbol: str
    open_price: float
    exit_price: float
    quantity: int
    allocated_capital: float
    net_pnl: float
    net_return: float
    gap_return: float
    prev_vol_ratio: float


@dataclass(frozen=True, slots=True)
class VariantResult:
    config: VariantConfig
    trades: int
    active_days: int
    avg_day_return: float | None
    median_day_return: float | None
    win_rate_days: float | None
    win_rate_trades: float | None
    compounded_return: float
    max_drawdown: float
    profit_factor: float | None
    avg_cash_used_pct: float | None
    sample_trades: tuple[TradeResult, ...]


def rank_value(candidate: Candidate, rank: str) -> tuple[float, str]:
    match rank:
        case "largest_gap":
            return (candidate.gap_return, candidate.symbol)
        case "quiet_volume":
            return (candidate.prev_vol_ratio, candidate.symbol)
        case "lowest_price":
            return (candidate.open_price, candidate.symbol)
        case "highest_price":
            return (-candidate.open_price, candidate.symbol)
        case "gap_then_quiet":
            return (candidate.gap_return, candidate.prev_vol_ratio, candidate.symbol)
        case _:
            return (candidate.gap_return, candidate.symbol)


def exit_price(candidate: Candidate, config: VariantConfig) -> float | None:
    if config.exit_offset == 0:
        if config.stop_loss is not None and candidate.low_price <= candidate.open_price * (1.0 - config.stop_loss):
            return candidate.open_price * (1.0 - config.stop_loss)
        if config.take_profit is not None and candidate.high_price >= candidate.open_price * (1.0 + config.take_profit):
            return candidate.open_price * (1.0 + config.take_profit)
        return candidate.close_price
    idx = config.exit_offset - 1
    if idx < 0 or idx >= len(candidate.future_closes):
        return None
    return candidate.future_closes[idx]


def passes_filters(candidate: Candidate, config: VariantConfig) -> bool:
    return (
        config.min_price <= candidate.prev_close <= config.max_price
        and candidate.open_price <= config.max_price
        and candidate.open_price > 0
        and candidate.gap_return <= config.gap_threshold
        and config.prev_vol_ratio_min <= candidate.prev_vol_ratio < config.prev_vol_ratio_max
    )


def max_drawdown(day_returns: list[float]) -> float:
    equity = 1.0
    peak = 1.0
    drawdown = 0.0
    for value in day_returns:
        equity *= max(0.0, 1.0 + value)
        peak = max(peak, equity)
        if peak > 0:
            drawdown = max(drawdown, (peak - equity) / peak)
    return drawdown


def compounded(day_returns: list[float]) -> float:
    equity = 1.0
    for value in day_returns:
        equity *= max(0.0, 1.0 + value)
    return equity - 1.0


def profit_factor(trades: list[TradeResult]) -> float | None:
    gains = sum(row.net_pnl for row in trades if row.net_pnl > 0)
    losses = -sum(row.net_pnl for row in trades if row.net_pnl < 0)
    if losses <= 0:
        return math.inf if gains > 0 else None
    return gains / losses


def simulate_day(candidates: list[Candidate], config: VariantConfig) -> tuple[float, list[TradeResult]]:
    filtered = [row for row in candidates if passes_filters(row, config)]
    picked = sorted(filtered, key=lambda row: rank_value(row, config.rank))[: config.top_n]
    if not picked:
        return 0.0, []
    slot_capital = config.capital / max(1, config.top_n)
    costs = config.roundtrip_cost + config.slippage
    trades: list[TradeResult] = []
    for row in picked:
        price = exit_price(row, config)
        if price is None or price <= 0 or row.open_price > slot_capital:
            continue
        quantity = int(slot_capital // row.open_price)
        if quantity <= 0:
            continue
        invested = quantity * row.open_price
        net_pnl = quantity * (price - row.open_price) - invested * costs
        trades.append(
            TradeResult(
                row.date,
                row.symbol,
                row.open_price,
                price,
                quantity,
                slot_capital,
                net_pnl,
                net_pnl / config.capital,
                row.gap_return,
                row.prev_vol_ratio,
            )
        )
    return sum(row.net_return for row in trades), trades


def simulate_variant(rows: list[Candidate], config: VariantConfig) -> VariantResult:
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
    if not day_returns:
        return VariantResult(config, 0, 0, None, None, None, None, 0.0, 0.0, None, None, ())
    trade_wins = sum(1 for row in trades if row.net_pnl > 0)
    cash_used = [row.quantity * row.open_price / row.allocated_capital for row in trades]
    return VariantResult(
        config=config,
        trades=len(trades),
        active_days=len(day_returns),
        avg_day_return=statistics.mean(day_returns),
        median_day_return=statistics.median(day_returns),
        win_rate_days=sum(1 for value in day_returns if value > 0) / len(day_returns),
        win_rate_trades=trade_wins / len(trades),
        compounded_return=compounded(day_returns),
        max_drawdown=max_drawdown(day_returns),
        profit_factor=profit_factor(trades),
        avg_cash_used_pct=statistics.mean(cash_used) if cash_used else None,
        sample_trades=tuple(sorted(trades, key=lambda row: row.net_return, reverse=True)[:5]),
    )
