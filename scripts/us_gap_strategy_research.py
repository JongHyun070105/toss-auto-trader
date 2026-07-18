#!/usr/bin/env python3
"""Research a US regular-session gap strategy from cached Toss daily candles.

This file never calls account or order endpoints. Selection is performed on
train/validation windows only; 2024+ is held out for the final report.
"""
from __future__ import annotations

import argparse
import json
import math
import sqlite3
import statistics
from collections import defaultdict
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Sequence


DEFAULT_DB = "data/us_gap_research.sqlite3"
DEFAULT_UNIVERSE = "data/us_gap_research_universe.json"
DEFAULT_OUT_DIR = "data/us_gap_strategy_research"
CAPITAL_USD = 7.0


@dataclass(frozen=True, slots=True)
class Candle:
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(frozen=True, slots=True)
class Candidate:
    date: str
    symbol: str
    open: float
    high: float
    low: float
    close: float
    prev_close: float
    gap: float
    prev_vol_ratio: float
    avg_dollar_volume20: float
    spy_open_vs_sma5: float | None
    qqq_open_vs_sma5: float | None
    iwm_open_vs_sma5: float | None


@dataclass(frozen=True, slots=True)
class StrategyConfig:
    name: str
    market_proxy: str | None
    market_gate_max: float | None
    gap_max: float
    gap_min: float | None
    prev_vol_ratio_max: float
    min_dollar_volume: float
    rank: str
    stop_loss: float | None
    take_profit: float | None
    roundtrip_cost: float


@dataclass(frozen=True, slots=True)
class Trade:
    date: str
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


@dataclass(frozen=True, slots=True)
class Metrics:
    trades: int
    active_days: int
    win_rate: float | None
    avg_return: float | None
    median_return: float | None
    total_pnl_usd: float
    profit_factor: float | None
    cash_mdd_usd: float
    mdd_on_capital: float
    stop_rate: float | None
    take_rate: float | None
    close_rate: float | None
    both_stop_take: int


def load_universe(path: str) -> list[str]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return [str(row["symbol"]) for row in payload.get("stocks", []) if row.get("symbol")]


def load_candles(db_path: str, symbols: Iterable[str], *, start: str, end: str) -> dict[str, list[Candle]]:
    symbol_list = list(dict.fromkeys(symbols))
    if not symbol_list:
        return {}
    placeholders = ",".join("?" for _ in symbol_list)
    params: list[Any] = [*symbol_list, start, end]
    con = sqlite3.connect(f"file:{Path(db_path).resolve()}?mode=ro", uri=True)
    try:
        rows = con.execute(
            f"""
            SELECT symbol, substr(timestamp,1,10),
                   CAST(open_price AS REAL), CAST(high_price AS REAL),
                   CAST(low_price AS REAL), CAST(close_price AS REAL), CAST(volume AS REAL)
            FROM candle_cache
            WHERE interval='1d' AND symbol IN ({placeholders})
              AND substr(timestamp,1,10) BETWEEN ? AND ?
            ORDER BY symbol, timestamp
            """,
            params,
        ).fetchall()
    finally:
        con.close()
    grouped: dict[str, list[Candle]] = defaultdict(list)
    for symbol, date, open_, high, low, close, volume in rows:
        values = (float(open_), float(high), float(low), float(close), float(volume))
        if min(values[:4]) <= 0 or values[1] < max(values[0], values[3]) or values[2] > min(values[0], values[3]):
            continue
        grouped[str(symbol)].append(Candle(str(date), *values))
    return dict(grouped)


def market_gate_map(candles: Sequence[Candle]) -> dict[str, float]:
    result: dict[str, float] = {}
    for index in range(4, len(candles)):
        row = candles[index]
        sma5_live = (row.open + sum(c.close for c in candles[index - 4 : index])) / 5.0
        if sma5_live > 0:
            result[row.date] = row.open / sma5_live - 1.0
    return result


def build_candidates(candles_by_symbol: dict[str, list[Candle]], markets: dict[str, dict[str, float]]) -> list[Candidate]:
    candidates: list[Candidate] = []
    for symbol, candles in candles_by_symbol.items():
        if symbol in {"SPY", "QQQ", "IWM"}:
            continue
        for index in range(21, len(candles)):
            row = candles[index]
            previous = candles[index - 1]
            baseline = candles[index - 21 : index - 1]
            if len(baseline) != 20 or previous.close <= 0:
                continue
            avg_volume = statistics.mean(item.volume for item in baseline)
            avg_dollar_volume = statistics.mean(item.close * item.volume for item in candles[index - 20 : index])
            if avg_volume <= 0 or avg_dollar_volume <= 0:
                continue
            gap = row.open / previous.close - 1.0
            if gap > -0.02:
                continue
            candidates.append(
                Candidate(
                    date=row.date,
                    symbol=symbol,
                    open=row.open,
                    high=row.high,
                    low=row.low,
                    close=row.close,
                    prev_close=previous.close,
                    gap=gap,
                    prev_vol_ratio=previous.volume / avg_volume,
                    avg_dollar_volume20=avg_dollar_volume,
                    spy_open_vs_sma5=markets.get("SPY", {}).get(row.date),
                    qqq_open_vs_sma5=markets.get("QQQ", {}).get(row.date),
                    iwm_open_vs_sma5=markets.get("IWM", {}).get(row.date),
                )
            )
    return candidates


def passes(candidate: Candidate, config: StrategyConfig) -> bool:
    market_value = {
        "SPY": candidate.spy_open_vs_sma5,
        "QQQ": candidate.qqq_open_vs_sma5,
        "IWM": candidate.iwm_open_vs_sma5,
    }.get(config.market_proxy)
    return (
        candidate.gap <= config.gap_max
        and (config.gap_min is None or candidate.gap >= config.gap_min)
        and candidate.prev_vol_ratio < config.prev_vol_ratio_max
        and candidate.avg_dollar_volume20 >= config.min_dollar_volume
        and (
            config.market_gate_max is None
            or (market_value is not None and market_value <= config.market_gate_max)
        )
    )


def rank_key(candidate: Candidate, rank: str) -> tuple[float, str]:
    if rank == "most_negative_gap":
        return candidate.gap, candidate.symbol
    if rank == "mildest_eligible_gap":
        return -candidate.gap, candidate.symbol
    if rank == "highest_liquidity":
        return -candidate.avg_dollar_volume20, candidate.symbol
    if rank == "lowest_price":
        return candidate.open, candidate.symbol
    raise ValueError(f"unknown rank: {rank}")


def exit_trade(candidate: Candidate, config: StrategyConfig) -> tuple[float, str, bool]:
    stop_price = candidate.open * (1.0 - config.stop_loss) if config.stop_loss is not None else None
    take_price = candidate.open * (1.0 + config.take_profit) if config.take_profit is not None else None
    hit_stop = stop_price is not None and candidate.low <= stop_price
    hit_take = take_price is not None and candidate.high >= take_price
    if hit_stop:
        return float(stop_price), "stop", bool(hit_take)
    if hit_take:
        return float(take_price), "take", False
    return candidate.close, "close", False


def simulate(candidates: Sequence[Candidate], config: StrategyConfig, *, start: str, end: str) -> list[Trade]:
    grouped: dict[str, list[Candidate]] = defaultdict(list)
    for candidate in candidates:
        if start <= candidate.date <= end and passes(candidate, config):
            grouped[candidate.date].append(candidate)
    trades: list[Trade] = []
    for date in sorted(grouped):
        candidate = min(grouped[date], key=lambda row: rank_key(row, config.rank))
        exit_price, reason, both = exit_trade(candidate, config)
        gross_return = exit_price / candidate.open - 1.0
        net_return = gross_return - config.roundtrip_cost
        market_value = {
            "SPY": candidate.spy_open_vs_sma5,
            "QQQ": candidate.qqq_open_vs_sma5,
            "IWM": candidate.iwm_open_vs_sma5,
        }.get(config.market_proxy)
        trades.append(
            Trade(
                date=date,
                symbol=candidate.symbol,
                entry=candidate.open,
                exit=exit_price,
                reason=reason,
                gap=candidate.gap,
                prev_vol_ratio=candidate.prev_vol_ratio,
                avg_dollar_volume20=candidate.avg_dollar_volume20,
                market_proxy=config.market_proxy,
                market_open_vs_sma5=market_value,
                gross_return=gross_return,
                net_return=net_return,
                net_pnl_usd=CAPITAL_USD * net_return,
                both_stop_take=both,
            )
        )
    return trades


def metrics(trades: Sequence[Trade]) -> Metrics:
    if not trades:
        return Metrics(0, 0, None, None, None, 0.0, None, 0.0, 0.0, None, None, None, 0)
    returns = [trade.net_return for trade in trades]
    pnls = [trade.net_pnl_usd for trade in trades]
    gains = sum(value for value in pnls if value > 0)
    losses = -sum(value for value in pnls if value < 0)
    equity = 0.0
    peak = 0.0
    cash_mdd = 0.0
    for pnl in pnls:
        equity += pnl
        peak = max(peak, equity)
        cash_mdd = max(cash_mdd, peak - equity)
    count = len(trades)
    return Metrics(
        trades=count,
        active_days=len({trade.date for trade in trades}),
        win_rate=sum(value > 0 for value in pnls) / count,
        avg_return=statistics.mean(returns),
        median_return=statistics.median(returns),
        total_pnl_usd=sum(pnls),
        profit_factor=(gains / losses) if losses > 0 else (math.inf if gains > 0 else None),
        cash_mdd_usd=cash_mdd,
        mdd_on_capital=cash_mdd / CAPITAL_USD,
        stop_rate=sum(trade.reason == "stop" for trade in trades) / count,
        take_rate=sum(trade.reason == "take" for trade in trades) / count,
        close_rate=sum(trade.reason == "close" for trade in trades) / count,
        both_stop_take=sum(trade.both_stop_take for trade in trades),
    )


def selection_score(train: Metrics, validation: Metrics) -> float:
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
    mdd_penalty = train.mdd_on_capital + validation.mdd_on_capital
    return pf_floor * math.log1p(min(train.trades, validation.trades)) - 0.25 * mdd_penalty


def diagnostic_score(train: Metrics, validation: Metrics) -> float:
    train_pf = min(float(train.profit_factor or 0.0), 5.0)
    validation_pf = min(float(validation.profit_factor or 0.0), 5.0)
    sample = math.log1p(min(train.trades, validation.trades))
    pnl_bonus = float(train.total_pnl_usd > 0) + float(validation.total_pnl_usd > 0)
    return min(train_pf, validation_pf) * sample + pnl_bonus - 0.25 * (train.mdd_on_capital + validation.mdd_on_capital)


def entry_grid() -> list[StrategyConfig]:
    configs: list[StrategyConfig] = []
    market_options = [(None, None)] + [
        (proxy, gate)
        for proxy in ("SPY", "QQQ", "IWM")
        for gate in (0.0, -0.01)
    ]
    for proxy, gate in market_options:
        for gap_max in (-0.02, -0.03, -0.05, -0.07):
            for gap_min in (None, -0.10, -0.15):
                if gap_min is not None and gap_min > gap_max:
                    continue
                for volume_max in (0.8, 1.2, 99.0):
                    for dollar_volume in (5_000_000.0, 25_000_000.0, 100_000_000.0):
                        for rank in ("most_negative_gap", "mildest_eligible_gap", "highest_liquidity"):
                            name = (
                                f"{proxy}_gate{gate}_gap{gap_max}_floor{gap_min}_vol{volume_max}_"
                                f"dv{int(dollar_volume)}_{rank}"
                            )
                            configs.append(
                                StrategyConfig(name, proxy, gate, gap_max, gap_min, volume_max, dollar_volume, rank, 0.03, 0.08, 0.01)
                            )
    return configs


def exit_grid(base: StrategyConfig) -> list[StrategyConfig]:
    configs: list[StrategyConfig] = []
    for stop in (0.02, 0.03, 0.05, 0.08, None):
        for take in (0.05, 0.08, 0.12, 0.20, None):
            configs.append(replace(base, name=f"{base.name}_stop{stop}_take{take}", stop_loss=stop, take_profit=take))
    return configs


def profile_config(config: StrategyConfig, profile: str) -> StrategyConfig:
    costs = {"base": 0.004, "mid": 0.010, "harsh": 0.020}
    return replace(config, name=f"{config.name}_{profile}", roundtrip_cost=costs[profile])


def annual_metrics(trades: Sequence[Trade]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[Trade]] = defaultdict(list)
    for trade in trades:
        grouped[trade.date[:4]].append(trade)
    return {year: asdict(metrics(rows)) for year, rows in sorted(grouped.items())}


def missed_winner_metrics(trades: Sequence[Trade], share: float) -> Metrics:
    winners = sorted((trade for trade in trades if trade.net_pnl_usd > 0), key=lambda trade: trade.net_pnl_usd, reverse=True)
    remove_count = int(len(winners) * share)
    removed = set(winners[:remove_count])
    return metrics([trade for trade in trades if trade not in removed])


def json_safe(value: Any) -> Any:
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    return value


def config_evaluation(candidates: Sequence[Candidate], config: StrategyConfig) -> dict[str, Any]:
    windows = {
        "train_2011_2020": ("2011-01-01", "2020-12-31"),
        "validation_2021_2023": ("2021-01-01", "2023-12-31"),
        "test_2024_2026": ("2024-01-01", "2026-12-31"),
        "recent_2025_2026": ("2025-01-01", "2026-12-31"),
        "full_2011_2026": ("2011-01-01", "2026-12-31"),
    }
    result: dict[str, Any] = {"config": asdict(config), "windows": {}}
    for name, (start, end) in windows.items():
        trades = simulate(candidates, config, start=start, end=end)
        result["windows"][name] = {
            "metrics": asdict(metrics(trades)),
            "annual": annual_metrics(trades),
            "miss_top_winners_25pct": asdict(missed_winner_metrics(trades, 0.25)),
        }
    return result


def baseline_config() -> StrategyConfig:
    return StrategyConfig(
        "domestic_rules_direct_copy",
        "SPY",
        -0.01,
        -0.05,
        None,
        0.8,
        5_000_000.0,
        "lowest_price",
        0.0225,
        0.12,
        0.01,
    )


def choose_configs(candidates: Sequence[Candidate]) -> tuple[StrategyConfig, bool, list[dict[str, Any]], list[dict[str, Any]]]:
    entry_results: list[tuple[float, float, StrategyConfig, Metrics, Metrics]] = []
    for config in entry_grid():
        train = metrics(simulate(candidates, config, start="2011-01-01", end="2020-12-31"))
        validation = metrics(simulate(candidates, config, start="2021-01-01", end="2023-12-31"))
        strict = selection_score(train, validation)
        entry_results.append((strict, diagnostic_score(train, validation), config, train, validation))
    entry_results.sort(key=lambda row: (math.isfinite(row[0]), row[0] if math.isfinite(row[0]) else row[1]), reverse=True)
    entry_payload = [
        {"passed": math.isfinite(strict), "score": strict if math.isfinite(strict) else diagnostic, "config": asdict(config), "train": asdict(train), "validation": asdict(validation)}
        for strict, diagnostic, config, train, validation in entry_results[:50]
    ]

    exit_results: list[tuple[float, float, StrategyConfig, Metrics, Metrics]] = []
    seen: set[tuple[Any, ...]] = set()
    for _, _, entry, _, _ in entry_results[:10]:
        for config in exit_grid(entry):
            key = (
                config.market_proxy,
                config.market_gate_max,
                config.gap_max,
                config.gap_min,
                config.prev_vol_ratio_max,
                config.min_dollar_volume,
                config.rank,
                config.stop_loss,
                config.take_profit,
            )
            if key in seen:
                continue
            seen.add(key)
            train = metrics(simulate(candidates, config, start="2011-01-01", end="2020-12-31"))
            validation = metrics(simulate(candidates, config, start="2021-01-01", end="2023-12-31"))
            strict = selection_score(train, validation)
            exit_results.append((strict, diagnostic_score(train, validation), config, train, validation))
    exit_results.sort(key=lambda row: (math.isfinite(row[0]), row[0] if math.isfinite(row[0]) else row[1]), reverse=True)
    if not exit_results:
        raise RuntimeError("strategy search produced no configurations")
    exit_payload = [
        {"passed": math.isfinite(strict), "score": strict if math.isfinite(strict) else diagnostic, "config": asdict(config), "train": asdict(train), "validation": asdict(validation)}
        for strict, diagnostic, config, train, validation in exit_results[:50]
    ]
    return exit_results[0][2], math.isfinite(exit_results[0][0]), entry_payload, exit_payload


def markdown(payload: dict[str, Any]) -> str:
    selected = payload["selected_config"]
    lines = [
        "# US Gap Strategy Research",
        "",
        f"- generated_at: `{payload['generated_at']}`",
        f"- universe: `{payload['universe_count']}` current liquid active common stocks",
        f"- candles: `{payload['candle_rows']}` / candidates: `{payload['candidate_rows']}`",
        "- bias: current-universe liquidity selection; delisted and formerly-liquid names are absent.",
        "- execution: $7 fixed amount order, fractional quantity, US regular-session open proxy.",
        "- costs: base 0.4%, mid 1.0%, harsh 2.0% round trip; under-$10 Toss commission waiver is not treated as guaranteed future policy.",
        "- daily OHLC ambiguity: stop first when stop and take are both touched.",
        "- FX: strategy is measured in USD. KRW/USD conversion is a separate one-time funding cost when USD proceeds remain in USD.",
        "",
        "## Selected without using 2024+",
        "",
        f"```json\n{json.dumps(selected, ensure_ascii=False, indent=2)}\n```",
        "",
    ]
    for label in ("baseline", "selected"):
        lines += [f"## {label}", ""]
        for profile, evaluation in payload["evaluations"][label].items():
            lines.append(f"### {profile}")
            for window, block in evaluation["windows"].items():
                m = block["metrics"]
                pf = m["profit_factor"]
                pf_text = "n/a" if pf is None else ("inf" if math.isinf(pf) else f"{pf:.3f}")
                lines.append(
                    f"- {window}: trades={m['trades']} pnl=${m['total_pnl_usd']:.2f} "
                    f"PF={pf_text} MDD={m['mdd_on_capital'] * 100:.1f}% win={((m['win_rate'] or 0) * 100):.1f}%"
                )
            lines.append("")
    lines += [
        "## Interpretation limits",
        "",
        "- Daily open is not the exact fill of a fractional amount market order after 09:30 ET.",
        "- Historical earnings/news exclusions and point-in-time warning flags are unavailable.",
        "- A positive held-out result is a paper-forward candidate, not approval for live orders.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Research-only US gap strategy; never sends orders")
    parser.add_argument("--db-path", default=DEFAULT_DB)
    parser.add_argument("--universe", default=DEFAULT_UNIVERSE)
    parser.add_argument("--out-dir", default=DEFAULT_OUT_DIR)
    parser.add_argument("--start", default="2011-01-01")
    parser.add_argument("--end", default="2026-12-31")
    args = parser.parse_args()

    symbols = load_universe(args.universe)
    candles = load_candles(args.db_path, ["SPY", "QQQ", "IWM", *symbols], start=args.start, end=args.end)
    if "SPY" not in candles:
        raise RuntimeError("SPY candles are required for the US market gate")
    markets = {
        symbol: market_gate_map(candles[symbol])
        for symbol in ("SPY", "QQQ", "IWM")
        if symbol in candles
    }
    candidates = build_candidates(candles, markets)
    chosen, selection_accepted, entry_search, exit_search = choose_configs(candidates)

    evaluations: dict[str, dict[str, Any]] = {"baseline": {}, "selected": {}}
    for profile in ("base", "mid", "harsh"):
        evaluations["baseline"][profile] = config_evaluation(candidates, profile_config(baseline_config(), profile))
        evaluations["selected"][profile] = config_evaluation(candidates, profile_config(chosen, profile))

    payload = {
        "generated_at": datetime.now().astimezone().isoformat(),
        "db_path": args.db_path,
        "universe_path": args.universe,
        "universe_count": len(symbols),
        "loaded_symbols": len(candles),
        "candle_rows": sum(len(rows) for rows in candles.values()),
        "candidate_rows": len(candidates),
        "selection_windows": {"train": "2011-2020", "validation": "2021-2023", "untouched_test": "2024-2026"},
        "selected_config": asdict(chosen),
        "selection_accepted": selection_accepted,
        "entry_search_top50": entry_search,
        "exit_search_top50": exit_search,
        "evaluations": evaluations,
        "method_limits": [
            "current liquid universe causes survivorship and selection bias",
            "daily OHLC cannot reproduce exact 09:30 fractional amount-order fills",
            "historical earnings, news, halts, and warning flags are not available",
            "USD returns exclude daily KRW translation; keep experimental proceeds in USD to avoid per-trade conversion",
        ],
    }
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "us_gap_research.json").write_text(
        json.dumps(json_safe(payload), ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    (out_dir / "us_gap_research.md").write_text(markdown(payload), encoding="utf-8")
    selected_trades = simulate(candidates, profile_config(chosen, "harsh"), start="2011-01-01", end="2026-12-31")
    (out_dir / "selected_harsh_trades.json").write_text(
        json.dumps([asdict(trade) for trade in selected_trades], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "out_dir": str(out_dir),
                "universe": len(symbols),
                "candidates": len(candidates),
                "selected": asdict(chosen),
                "test_harsh": evaluations["selected"]["harsh"]["windows"]["test_2024_2026"]["metrics"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
