from __future__ import annotations

import sqlite3
import statistics
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from simple_gap_variant_core import Candidate


@dataclass(frozen=True, slots=True)
class MarketContext:
    date: str
    market_gap: float
    prev_market_return: float
    prev_breadth_up: float
    prev_volatility20: float
    prev_avg_range: float
    active_symbols: int


@dataclass(frozen=True, slots=True)
class MarketFilter:
    name: str
    market_gap_min: float | None = None
    market_gap_max: float | None = None
    prev_market_return_min: float | None = None
    prev_market_return_max: float | None = None
    prev_breadth_up_min: float | None = None
    prev_breadth_up_max: float | None = None
    volatility20_max: float | None = None
    prev_avg_range_max: float | None = None


@dataclass(frozen=True, slots=True)
class MarketContextQuery:
    start: str
    end: str
    volatility_window: int = 20


@dataclass(frozen=True, slots=True)
class DailyAggregate:
    date: str
    market_gap: float
    market_return: float
    breadth_up: float
    avg_range: float
    active_symbols: int


def _within(value: float, minimum: float | None, maximum: float | None) -> bool:
    if minimum is not None and value < minimum:
        return False
    if maximum is not None and value > maximum:
        return False
    return True


def volatility(values: Sequence[float]) -> float:
    if len(values) < 2:
        return 0.0
    return statistics.pstdev(values)


def passes_market_filter(context: MarketContext, market_filter: MarketFilter) -> bool:
    return (
        _within(context.market_gap, market_filter.market_gap_min, market_filter.market_gap_max)
        and _within(context.prev_market_return, market_filter.prev_market_return_min, market_filter.prev_market_return_max)
        and _within(context.prev_breadth_up, market_filter.prev_breadth_up_min, market_filter.prev_breadth_up_max)
        and _within(context.prev_volatility20, None, market_filter.volatility20_max)
        and _within(context.prev_avg_range, None, market_filter.prev_avg_range_max)
    )


def filter_candidates_by_market(
    rows: Sequence[Candidate],
    contexts: Mapping[str, MarketContext],
    market_filter: MarketFilter,
) -> list[Candidate]:
    return [row for row in rows if row.date in contexts and passes_market_filter(contexts[row.date], market_filter)]


def load_market_contexts(db_path: str, query: MarketContextQuery) -> Mapping[str, MarketContext]:
    sql = """
    WITH enriched AS (
      SELECT
        symbol,
        substr(timestamp,1,10) AS date,
        CAST(open_price AS REAL) AS open_price,
        CAST(high_price AS REAL) AS high_price,
        CAST(low_price AS REAL) AS low_price,
        CAST(close_price AS REAL) AS close_price,
        LAG(CAST(close_price AS REAL)) OVER (PARTITION BY symbol ORDER BY timestamp) AS prev_close
      FROM candle_cache
      WHERE interval='1d'
    )
    SELECT date,
           AVG((open_price - prev_close) / prev_close) AS market_gap,
           AVG((close_price - prev_close) / prev_close) AS market_return,
           AVG(CASE WHEN close_price > prev_close THEN 1.0 ELSE 0.0 END) AS breadth_up,
           AVG((high_price - low_price) / prev_close) AS avg_range,
           COUNT(*) AS active_symbols
    FROM enriched
    WHERE date >= ?
      AND date <= ?
      AND prev_close > 0
      AND open_price > 0
      AND high_price >= low_price
      AND close_price > 0
    GROUP BY date
    ORDER BY date ASC
    """
    params = (query.start, query.end)
    with closing(sqlite3.connect(f"file:{Path(db_path).resolve()}?mode=ro", uri=True)) as con:
        con.row_factory = sqlite3.Row
        rows = con.execute(sql, params).fetchall()
    aggregates = [
        DailyAggregate(
            date=str(row["date"]),
            market_gap=float(row["market_gap"]),
            market_return=float(row["market_return"]),
            breadth_up=float(row["breadth_up"]),
            avg_range=float(row["avg_range"]),
            active_symbols=int(row["active_symbols"]),
        )
        for row in rows
    ]
    contexts: dict[str, MarketContext] = {}
    history: list[float] = []
    previous = DailyAggregate("", 0.0, 0.0, 0.5, 0.0, 0)
    for aggregate in aggregates:
        window = history[-query.volatility_window :]
        contexts[aggregate.date] = MarketContext(
            date=aggregate.date,
            market_gap=aggregate.market_gap,
            prev_market_return=previous.market_return,
            prev_breadth_up=previous.breadth_up,
            prev_volatility20=volatility(window),
            prev_avg_range=previous.avg_range,
            active_symbols=aggregate.active_symbols,
        )
        history.append(aggregate.market_return)
        previous = aggregate
    return contexts
