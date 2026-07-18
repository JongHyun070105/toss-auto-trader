#!/usr/bin/env python3
"""Test declared Korean gap-strategy features not covered by prior grids.

This module is research-only. It reads daily candles, never imports the live
trader, and never calls account or order endpoints. Candidate selection uses
2011-2023 only. The 2024+ period is a reused diagnostic because earlier project
research has already inspected it; only future observations can validate a
live change.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
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
DEFAULT_OUT_DIR = "data/kr_novel_feature_research"
COSTS = {"base": 0.0035, "realistic": 0.0075, "harsh": 0.0135, "extreme": 0.0245}


@dataclass(frozen=True, slots=True)
class NovelEvent:
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
    atr20: float
    prev_return1: float
    prev_return2: float
    prev_return3: float
    prev_return5: float
    prev_return20: float
    prev_body_return: float
    prev_lower_wick_share: float
    position20: float
    drawdown20: float
    sma5_distance: float
    sma20_distance: float
    range_ratio5_20: float
    normalized_gap: float
    gap_z60: float
    gap_history60: int
    position252: float
    history252: int


@dataclass(frozen=True, slots=True)
class Hypothesis:
    name: str
    entry_rule: str = "anchor"
    rank: str = "lowest_price"
    exit_rule: str = "fixed_stop0225_take12"


def load_events(db_path: str, *, start: str, end: str) -> list[NovelEvent]:
    sql = """
    WITH lagged AS (
      SELECT
        symbol,
        timestamp,
        substr(timestamp,1,10) AS date,
        CAST(open_price AS REAL) AS open_price,
        CAST(high_price AS REAL) AS high_price,
        CAST(low_price AS REAL) AS low_price,
        CAST(close_price AS REAL) AS close_price,
        CAST(volume AS REAL) AS volume,
        LAG(CAST(open_price AS REAL),1) OVER w AS prev_open,
        LAG(CAST(high_price AS REAL),1) OVER w AS prev_high,
        LAG(CAST(low_price AS REAL),1) OVER w AS prev_low,
        LAG(CAST(close_price AS REAL),1) OVER w AS prev_close,
        LAG(CAST(close_price AS REAL),2) OVER w AS close_lag2,
        LAG(CAST(close_price AS REAL),3) OVER w AS close_lag3,
        LAG(CAST(close_price AS REAL),4) OVER w AS close_lag4,
        LAG(CAST(close_price AS REAL),6) OVER w AS close_lag6,
        LAG(CAST(close_price AS REAL),21) OVER w AS close_lag21,
        LAG(CAST(volume AS REAL),1) OVER w AS prev_volume
      FROM candle_cache
      WHERE interval='1d'
      WINDOW w AS (PARTITION BY symbol ORDER BY timestamp)
    ), raw AS (
      SELECT *,
        open_price/NULLIF(prev_close,0)-1.0 AS gap_return,
        MAX(
          high_price-low_price,
          ABS(high_price-prev_close),
          ABS(low_price-prev_close)
        )/NULLIF(prev_close,0) AS true_range
      FROM lagged
    ), enriched AS (
      SELECT *,
        AVG(CAST(volume AS REAL)) OVER (
          PARTITION BY symbol ORDER BY timestamp ROWS BETWEEN 21 PRECEDING AND 2 PRECEDING
        ) AS avg_prev20_volume,
        AVG(CAST(close_price AS REAL)*CAST(volume AS REAL)) OVER (
          PARTITION BY symbol ORDER BY timestamp ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING
        ) AS avg_dollar_volume20,
        AVG((CAST(high_price AS REAL)-CAST(low_price AS REAL))/NULLIF(CAST(close_price AS REAL),0)) OVER (
          PARTITION BY symbol ORDER BY timestamp ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING
        ) AS avg_range20,
        AVG(true_range) OVER (
          PARTITION BY symbol ORDER BY timestamp ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING
        ) AS atr20,
        AVG(true_range) OVER (
          PARTITION BY symbol ORDER BY timestamp ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING
        ) AS atr5,
        AVG(gap_return) OVER (
          PARTITION BY symbol ORDER BY timestamp ROWS BETWEEN 60 PRECEDING AND 1 PRECEDING
        ) AS gap_mean60,
        AVG(gap_return*gap_return) OVER (
          PARTITION BY symbol ORDER BY timestamp ROWS BETWEEN 60 PRECEDING AND 1 PRECEDING
        ) AS gap_square_mean60,
        COUNT(gap_return) OVER (
          PARTITION BY symbol ORDER BY timestamp ROWS BETWEEN 60 PRECEDING AND 1 PRECEDING
        ) AS gap_count60,
        AVG(CAST(close_price AS REAL)) OVER (
          PARTITION BY symbol ORDER BY timestamp ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING
        ) AS sma5_prev,
        AVG(CAST(close_price AS REAL)) OVER (
          PARTITION BY symbol ORDER BY timestamp ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING
        ) AS sma20_prev,
        MAX(CAST(high_price AS REAL)) OVER (
          PARTITION BY symbol ORDER BY timestamp ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING
        ) AS high20_prev,
        MIN(CAST(low_price AS REAL)) OVER (
          PARTITION BY symbol ORDER BY timestamp ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING
        ) AS low20_prev,
        MAX(CAST(high_price AS REAL)) OVER (
          PARTITION BY symbol ORDER BY timestamp ROWS BETWEEN 252 PRECEDING AND 1 PRECEDING
        ) AS high252_prev,
        MIN(CAST(low_price AS REAL)) OVER (
          PARTITION BY symbol ORDER BY timestamp ROWS BETWEEN 252 PRECEDING AND 1 PRECEDING
        ) AS low252_prev,
        COUNT(*) OVER (
          PARTITION BY symbol ORDER BY timestamp ROWS BETWEEN 252 PRECEDING AND 1 PRECEDING
        ) AS history252,
        COUNT(*) OVER (
          PARTITION BY symbol ORDER BY timestamp ROWS BETWEEN 21 PRECEDING AND 2 PRECEDING
        ) AS prev_count
      FROM raw
    )
    SELECT * FROM enriched
    WHERE date BETWEEN ? AND ? AND prev_count=20
      AND prev_close BETWEEN 500 AND 30000 AND open_price > 0
      AND high_price >= MAX(open_price,close_price)
      AND low_price <= MIN(open_price,close_price)
      AND avg_prev20_volume > 0 AND avg_range20 > 0 AND atr20 > 0
      AND sma5_prev > 0 AND sma20_prev > 0 AND high20_prev > low20_prev
      AND (open_price/prev_close-1.0) <= -0.02
    ORDER BY date,symbol
    """
    connection = sqlite3.connect(f"file:{Path(db_path).resolve()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(sql, (start, end)).fetchall()
    finally:
        connection.close()

    result: list[NovelEvent] = []
    for row in rows:
        prev_close = float(row["prev_close"])
        prev_open = float(row["prev_open"] or prev_close)
        prev_high = float(row["prev_high"] or max(prev_open, prev_close))
        prev_low = float(row["prev_low"] or min(prev_open, prev_close))
        prev_range = max(0.0, prev_high - prev_low)
        lower_wick = max(0.0, min(prev_open, prev_close) - prev_low)
        high20 = float(row["high20_prev"])
        low20 = float(row["low20_prev"])
        avg_range20 = float(row["avg_range20"])
        gap = float(row["open_price"]) / prev_close - 1.0
        atr20 = float(row["atr20"])
        gap_variance = max(
            0.0,
            float(row["gap_square_mean60"] or 0.0) - float(row["gap_mean60"] or 0.0) ** 2,
        )
        gap_std = math.sqrt(gap_variance)
        high252 = float(row["high252_prev"] or high20)
        low252 = float(row["low252_prev"] or low20)
        result.append(
            NovelEvent(
                date=str(row["date"]),
                symbol=str(row["symbol"]),
                prev_close=prev_close,
                open=float(row["open_price"]),
                high=float(row["high_price"]),
                low=float(row["low_price"]),
                close=float(row["close_price"]),
                gap=gap,
                prev_vol_ratio=float(row["prev_volume"]) / float(row["avg_prev20_volume"]),
                avg_dollar_volume20=float(row["avg_dollar_volume20"]),
                avg_range20=avg_range20,
                atr20=atr20,
                prev_return1=prev_close / float(row["close_lag2"] or prev_close) - 1.0,
                prev_return2=float(row["close_lag2"] or prev_close) / float(row["close_lag3"] or prev_close) - 1.0,
                prev_return3=float(row["close_lag3"] or prev_close) / float(row["close_lag4"] or prev_close) - 1.0,
                prev_return5=prev_close / float(row["close_lag6"] or prev_close) - 1.0,
                prev_return20=prev_close / float(row["close_lag21"] or prev_close) - 1.0,
                prev_body_return=prev_close / prev_open - 1.0 if prev_open > 0 else 0.0,
                prev_lower_wick_share=lower_wick / prev_range if prev_range > 0 else 0.0,
                position20=(prev_close - low20) / (high20 - low20),
                drawdown20=prev_close / high20 - 1.0,
                sma5_distance=prev_close / float(row["sma5_prev"]) - 1.0,
                sma20_distance=prev_close / float(row["sma20_prev"]) - 1.0,
                range_ratio5_20=float(row["atr5"] or atr20) / atr20,
                normalized_gap=gap / atr20,
                gap_z60=(gap - float(row["gap_mean60"] or 0.0)) / gap_std if gap_std > 0 else 0.0,
                gap_history60=int(row["gap_count60"] or 0),
                position252=(prev_close - low252) / (high252 - low252) if high252 > low252 else 0.5,
                history252=int(row["history252"] or 0),
            )
        )
    return result


def hypotheses() -> list[Hypothesis]:
    """Declared candidate list; this repository does not prove preregistration."""
    return [
        Hypothesis("anchor"),
        Hypothesis("gap_atr_1", entry_rule="normalized_gap_1"),
        Hypothesis("gap_atr_1_5", entry_rule="normalized_gap_1_5"),
        Hypothesis("gap_z60_2", entry_rule="gap_z60_2"),
        Hypothesis("gap_z60_3", entry_rule="gap_z60_3"),
        Hypothesis("market_residual_gap3", entry_rule="market_residual_gap3"),
        Hypothesis("position20_bottom25", entry_rule="position20_bottom25"),
        Hypothesis("position252_bottom20", entry_rule="position252_bottom20"),
        Hypothesis("drawdown20_10", entry_rule="drawdown20_10"),
        Hypothesis("two_down_closes", entry_rule="two_down"),
        Hypothesis("three_down_closes", entry_rule="three_down"),
        Hypothesis("range_compression75", entry_rule="compression75"),
        Hypothesis("prev_red_body2", entry_rule="prev_red_body2"),
        Hypothesis("prev_green_body", entry_rule="prev_green_body"),
        Hypothesis("prev_lower_wick40", entry_rule="prev_lower_wick40"),
        Hypothesis("below_sma20_5", entry_rule="below_sma20_5"),
        Hypothesis("oversold_position_gap", entry_rule="oversold_position_gap"),
        Hypothesis("failed_breakdown", entry_rule="failed_breakdown"),
        Hypothesis("rank_deepest_drawdown", rank="deepest_drawdown"),
        Hypothesis("rank_normalized_gap", rank="normalized_gap"),
        Hypothesis("rank_gap_z60", rank="gap_z60"),
        Hypothesis("rank_market_residual", rank="market_residual"),
        Hypothesis("rank_exhaustion", rank="exhaustion"),
        Hypothesis("exit_gap_fill50", exit_rule="gap_fill50"),
        Hypothesis("exit_gap_fill75", exit_rule="gap_fill75"),
        Hypothesis("exit_gap_fill100", exit_rule="gap_fill100"),
        Hypothesis("exit_range_half_two", exit_rule="range_half_two"),
        Hypothesis("exit_range_threequarter_twohalf", exit_rule="range_threequarter_twohalf"),
        Hypothesis("combo_position_gap_rank", entry_rule="oversold_position_gap", rank="deepest_drawdown"),
        Hypothesis("combo_three_down_gapfill75", entry_rule="three_down", exit_rule="gap_fill75"),
        Hypothesis("combo_compression_atr_rank", entry_rule="compression75", rank="normalized_gap"),
        Hypothesis("combo_failed_breakdown_gapfill50", entry_rule="failed_breakdown", exit_rule="gap_fill50"),
    ]


def anchor_passes(event: NovelEvent, market: Market) -> bool:
    return (
        market.open_vs_sma5 <= -0.01
        and event.gap <= -0.05
        and 1000.0 <= event.prev_close <= 8000.0
        and event.open <= 8000.0
        and 0.0 <= event.prev_vol_ratio < 0.8
    )


def feature_passes(event: NovelEvent, market: Market, rule: str) -> bool:
    checks = {
        "anchor": True,
        "normalized_gap_1": event.normalized_gap <= -1.0,
        "normalized_gap_1_5": event.normalized_gap <= -1.5,
        "gap_z60_2": event.gap_history60 >= 40 and event.gap_z60 <= -2.0,
        "gap_z60_3": event.gap_history60 >= 40 and event.gap_z60 <= -3.0,
        "market_residual_gap3": event.gap - market.index_gap <= -0.03,
        "position20_bottom25": event.position20 <= 0.25,
        "position252_bottom20": event.history252 >= 252 and event.position252 <= 0.20,
        "drawdown20_10": event.drawdown20 <= -0.10,
        "two_down": event.prev_return1 <= 0 and event.prev_return2 <= 0,
        "three_down": event.prev_return1 <= 0 and event.prev_return2 <= 0 and event.prev_return3 <= 0,
        "compression75": event.range_ratio5_20 <= 0.75,
        "prev_red_body2": event.prev_body_return <= -0.02,
        "prev_green_body": event.prev_body_return >= 0.0,
        "prev_lower_wick40": event.prev_lower_wick_share >= 0.40,
        "below_sma20_5": event.sma20_distance <= -0.05,
        "oversold_position_gap": event.position20 <= 0.35 and event.normalized_gap <= -1.0,
        "failed_breakdown": event.position20 <= 0.25 and event.prev_lower_wick_share >= 0.30,
    }
    if rule not in checks:
        raise ValueError(f"unknown entry rule: {rule}")
    return checks[rule]


def rank_key(event: NovelEvent, rank: str, market: Market | None = None) -> tuple[float, str]:
    values = {
        "lowest_price": event.open,
        "deepest_drawdown": event.drawdown20,
        "normalized_gap": event.normalized_gap,
        "gap_z60": event.gap_z60 if event.gap_history60 >= 40 else math.inf,
        "market_residual": event.gap - market.index_gap if market is not None else event.gap,
        "exhaustion": event.normalized_gap + event.position20 + event.prev_return5,
    }
    if rank not in values:
        raise ValueError(f"unknown rank: {rank}")
    return values[rank], event.symbol


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def _apply_daily_exit_levels(
    event: NovelEvent,
    *,
    stop_price: float,
    target_price: float,
    target_reason: str,
    execution_model: str,
) -> tuple[float, str]:
    if execution_model not in {"standing_bracket", "daily_adverse_proxy"}:
        raise ValueError(f"unknown execution model: {execution_model}")
    if event.low <= stop_price:
        if execution_model == "daily_adverse_proxy":
            return stop_price * 0.99, "stop_daily_adverse_proxy"
        return stop_price, "stop"
    if execution_model == "daily_adverse_proxy":
        if event.close >= target_price:
            return target_price, f"{target_reason}_close_confirmed"
        return event.close * 0.995, "close_daily_proxy_stress"
    if event.high >= target_price:
        return target_price, target_reason
    return event.close, "close_auction_proxy"


def exit_for(
    event: NovelEvent, rule: str, *, execution_model: str = "standing_bracket"
) -> tuple[float, str]:
    if rule == "fixed_stop0225_take12":
        stop_pct, take_pct = 0.0225, 0.12
    elif rule.startswith("gap_fill"):
        fractions = {"gap_fill50": 0.50, "gap_fill75": 0.75, "gap_fill100": 1.0}
        if rule not in fractions:
            raise ValueError(f"unknown exit rule: {rule}")
        return _apply_daily_exit_levels(
            event,
            stop_price=event.open * (1.0 - 0.0225),
            target_price=event.open + fractions[rule] * (event.prev_close - event.open),
            target_reason=rule,
            execution_model=execution_model,
        )
    elif rule == "range_half_two":
        stop_pct = _clamp(event.atr20 * 0.50, 0.015, 0.04)
        take_pct = _clamp(event.atr20 * 2.00, 0.08, 0.18)
    elif rule == "range_threequarter_twohalf":
        stop_pct = _clamp(event.atr20 * 0.75, 0.015, 0.05)
        take_pct = _clamp(event.atr20 * 2.50, 0.10, 0.22)
    else:
        raise ValueError(f"unknown exit rule: {rule}")
    return _apply_daily_exit_levels(
        event,
        stop_price=event.open * (1.0 - stop_pct),
        target_price=event.open * (1.0 + take_pct),
        target_reason="take",
        execution_model=execution_model,
    )


def simulate(
    events: Sequence[NovelEvent],
    markets: dict[str, Market],
    hypothesis: Hypothesis,
    *,
    roundtrip_cost: float,
    execution_model: str = "standing_bracket",
) -> list[Trade]:
    by_date: dict[str, list[NovelEvent]] = {}
    for event in events:
        market = markets.get(event.date)
        if market and anchor_passes(event, market) and feature_passes(event, market, hypothesis.entry_rule):
            by_date.setdefault(event.date, []).append(event)
    trades: list[Trade] = []
    for date in sorted(by_date):
        event = min(by_date[date], key=lambda row: rank_key(row, hypothesis.rank, markets[date]))
        quantity = int(CAPITAL // event.open)
        if quantity <= 0:
            continue
        exit_price, reason = exit_for(
            event, hypothesis.exit_rule, execution_model=execution_model
        )
        invested = quantity * event.open
        gross = quantity * (exit_price - event.open)
        net = gross - invested * roundtrip_cost
        trades.append(
            Trade(
                date=date,
                exit_date=date,
                symbol=event.symbol,
                entry=event.open,
                exit=exit_price,
                quantity=quantity,
                invested=invested,
                gross_pnl=gross,
                net_pnl=net,
                net_return_on_capital=net / CAPITAL,
                reason=reason,
                gap=event.gap,
                avg_dollar_volume20=event.avg_dollar_volume20,
                avg_range20=event.avg_range20,
                prev_return5=event.prev_return5,
                market_open_vs_sma5=markets[date].open_vs_sma5,
            )
        )
    return trades


def pretest_score(trades: Sequence[Trade]) -> float:
    train = metrics(scoped(trades, *WINDOWS["train_2011_2018"]))
    validation = metrics(scoped(trades, *WINDOWS["validation_2019_2023"]))
    train_miss = missed_winners(scoped(trades, *WINDOWS["train_2011_2018"]), 0.25)
    validation_miss = missed_winners(scoped(trades, *WINDOWS["validation_2019_2023"]), 0.25)
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
    pf_floor = min(float(train.profit_factor or 0), float(validation.profit_factor or 0), 5.0)
    sample = min(train.trades, validation.trades)
    return pf_floor * math.log1p(sample) - 0.35 * (train.mdd_on_capital + validation.mdd_on_capital)


def window_payload(trades: Sequence[Trade]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for name, bounds in WINDOWS.items():
        rows = scoped(trades, *bounds)
        payload[name] = {
            "metrics": asdict(metrics(rows)),
            "miss_top_winners_25pct": asdict(missed_winners(rows, 0.25)),
            "monthly_bootstrap_positive_probability": monthly_bootstrap_positive_probability(rows),
        }
    return payload


def evaluate_hypothesis(
    events: Sequence[NovelEvent], markets: dict[str, Market], hypothesis: Hypothesis
) -> dict[str, Any]:
    profiles = {}
    for profile_name, cost in COSTS.items():
        profiles[profile_name] = window_payload(
            simulate(events, markets, hypothesis, roundtrip_cost=cost)
        )
    harsh_trades = simulate(events, markets, hypothesis, roundtrip_cost=COSTS["harsh"])
    return {
        "hypothesis": asdict(hypothesis),
        "pretest_score": pretest_score(harsh_trades),
        "profiles": profiles,
        "daily_adverse_proxy_harsh": window_payload(
            simulate(
                events,
                markets,
                hypothesis,
                roundtrip_cost=COSTS["harsh"],
                execution_model="daily_adverse_proxy",
            )
        ),
    }


def selected_without_recent_diagnostic(
    events: Sequence[NovelEvent], markets: dict[str, Market], *, limit: int = 8
) -> list[Hypothesis]:
    rows = []
    for hypothesis in hypotheses():
        trades = simulate(events, markets, hypothesis, roundtrip_cost=COSTS["harsh"])
        rows.append((pretest_score(trades), hypothesis))
    rows.sort(key=lambda row: (math.isfinite(row[0]), row[0], row[1].name), reverse=True)
    selected = [row[1] for row in rows if math.isfinite(row[0])][:limit]
    anchor = next(item for item in hypotheses() if item.name == "anchor")
    if anchor not in selected:
        selected.append(anchor)
    return selected


def pretest_leaderboard(
    events: Sequence[NovelEvent], markets: dict[str, Market]
) -> list[dict[str, Any]]:
    rows = []
    for hypothesis in hypotheses():
        trades = simulate(events, markets, hypothesis, roundtrip_cost=COSTS["harsh"])
        train_rows = scoped(trades, *WINDOWS["train_2011_2018"])
        validation_rows = scoped(trades, *WINDOWS["validation_2019_2023"])
        score = pretest_score(trades)
        rows.append(
            {
                "hypothesis": asdict(hypothesis),
                "pretest_passed": math.isfinite(score),
                "pretest_score": score,
                "train": asdict(metrics(train_rows)),
                "validation": asdict(metrics(validation_rows)),
                "train_miss_top_winners_25pct": asdict(missed_winners(train_rows, 0.25)),
                "validation_miss_top_winners_25pct": asdict(
                    missed_winners(validation_rows, 0.25)
                ),
            }
        )
    rows.sort(
        key=lambda row: (
            row["pretest_passed"],
            row["pretest_score"] if row["pretest_passed"] else -math.inf,
            row["hypothesis"]["name"],
        ),
        reverse=True,
    )
    return rows


def historical_diagnostic_passed(candidate: dict[str, Any], baseline: dict[str, Any]) -> bool:
    candidate_harsh = candidate["profiles"]["harsh"]
    baseline_harsh = baseline["profiles"]["harsh"]
    candidate_extreme = candidate["profiles"]["extreme"]
    for window in ("test_pre_nxt_2024_20250303", "post_nxt_20250304_2026"):
        current = candidate_harsh[window]["metrics"]
        base = baseline_harsh[window]["metrics"]
        if (
            current["trades"] < 8
            or current["total_pnl"] <= base["total_pnl"]
            or (current["profit_factor"] or 0) <= 1
            or current["mdd_on_capital"] > max(0.30, base["mdd_on_capital"] * 1.25)
            or candidate_harsh[window]["miss_top_winners_25pct"]["total_pnl"] <= 0
            or candidate_extreme[window]["metrics"]["total_pnl"] <= 0
        ):
            return False
    return True


def render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# KR Novel Feature Research",
        "",
        f"- generated: `{payload['generated_at']}`",
        f"- events: `{payload['event_rows']}` / market days: `{payload['market_days']}`",
        f"- declared hypotheses: `{payload['hypotheses_tested']}`",
        "- selection data: `2011-01-01~2023-12-31`",
        "- reused recent diagnostic: `2024-01-01~2026-07-16` (not an untouched holdout)",
        f"- live change accepted: `{payload['live_change_accepted']}`",
        "",
        "## Harsh-cost reused recent diagnostic",
        "",
        "| hypothesis | window | trades | pnl | PF | MDD/10k | miss top 25% pnl |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for row in payload["evaluations"]:
        name = row["hypothesis"]["name"]
        harsh = row["profiles"]["harsh"]
        for window in ("test_pre_nxt_2024_20250303", "post_nxt_20250304_2026", "recent_2026"):
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
            "Selection never reads 2024+ metrics. Daily OHLC uses stop-first when stop and target both touch.",
            "Current-survivor candles retain survivorship bias, so a passing result is research evidence only.",
            "",
        ]
    )
    return "\n".join(lines)


def source_fingerprints(db_path: str, index_rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    database = Path(db_path).resolve()
    digest = hashlib.sha256()
    stat = database.stat()
    sample_size = 1024 * 1024
    with database.open("rb") as handle:
        digest.update(handle.read(sample_size))
        if stat.st_size > sample_size:
            handle.seek(max(0, stat.st_size - sample_size))
            digest.update(handle.read(sample_size))
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    try:
        rows, symbols, first_date, last_date = connection.execute(
            "SELECT COUNT(*), COUNT(DISTINCT symbol), MIN(substr(timestamp,1,10)), "
            "MAX(substr(timestamp,1,10)) FROM candle_cache WHERE interval='1d'"
        ).fetchone()
    finally:
        connection.close()
    script_path = Path(__file__).resolve()
    index_payload = json.dumps(
        index_rows, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    ).encode("utf-8")
    return {
        "script_sha256": hashlib.sha256(script_path.read_bytes()).hexdigest(),
        "database_sample_sha256": digest.hexdigest(),
        "database_size_bytes": stat.st_size,
        "database_daily_rows": int(rows or 0),
        "database_symbols": int(symbols or 0),
        "database_first_date": first_date,
        "database_last_date": last_date,
        "kosdaq_index_sha256": hashlib.sha256(index_payload).hexdigest(),
        "kosdaq_index_rows": len(index_rows),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Novel Korean gap-feature research; no order endpoints")
    parser.add_argument("--db-path", default=DEFAULT_DB)
    parser.add_argument("--out-dir", default=DEFAULT_OUT_DIR)
    parser.add_argument("--start", default="2011-01-01")
    parser.add_argument("--end", default="2026-07-16")
    parser.add_argument(
        "--selection-limit",
        type=int,
        default=100,
        help="Pretest-passing hypotheses to open in the reused recent diagnostic",
    )
    args = parser.parse_args()

    events = load_events(args.db_path, start=args.start, end=args.end)
    index_rows = fetch_kosdaq_index(args.start, args.end)
    markets = build_markets(events, index_rows)
    leaderboard = pretest_leaderboard(events, markets)
    selected = selected_without_recent_diagnostic(events, markets, limit=args.selection_limit)
    evaluations = [evaluate_hypothesis(events, markets, item) for item in selected]
    baseline = next(row for row in evaluations if row["hypothesis"]["name"] == "anchor")
    promoted = [
        row for row in evaluations
        if row["hypothesis"]["name"] != "anchor" and historical_diagnostic_passed(row, baseline)
    ]
    payload = {
        "generated_at": datetime.now().astimezone().isoformat(),
        "db_path": args.db_path,
        "requested_start": args.start,
        "requested_end": args.end,
        "source_fingerprints": source_fingerprints(args.db_path, index_rows),
        "event_rows": len(events),
        "market_days": len(markets),
        "hypotheses_tested": len(hypotheses()),
        "pretest_passed": sum(row["pretest_passed"] for row in leaderboard),
        "pretest_leaderboard": leaderboard,
        "selected_without_recent_diagnostic": [asdict(item) for item in selected],
        "live_change_accepted": False,
        "historical_diagnostic_candidates": [row["hypothesis"] for row in promoted],
        "evaluations": evaluations,
        "limits": [
            "current-survivor universe creates survivorship bias",
            "daily OHLC cannot reproduce opening auction fills or intraday path",
            "same-bar stop and target uses conservative stop-first ordering",
            "historical Toss warnings, VI, and point-in-time delistings are unavailable",
            "multiple fixed hypotheses still create multiple-testing risk",
            "2024+ was consumed by prior project research and is not a fresh holdout",
        ],
    }
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "kr_novel_feature_research.json").write_text(
        json.dumps(json_safe(payload), ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    (out / "kr_novel_feature_research.md").write_text(render_markdown(payload), encoding="utf-8")
    print(
        json.dumps(
            {
                "out_dir": str(out),
                "events": len(events),
                "selected": [item.name for item in selected],
                "live_change_accepted": False,
                "historical_diagnostic_candidates": [row["hypothesis"]["name"] for row in promoted],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
