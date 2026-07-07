from __future__ import annotations

import argparse
import csv
import json
import math
import random
import time
from dataclasses import asdict, replace
from datetime import datetime
from pathlib import Path
from typing import Final, Sequence

from simple_gap_market_context import MarketContext, MarketContextQuery, MarketFilter, filter_candidates_by_market, load_market_contexts
from simple_gap_variant_core import Candidate, VariantConfig, VariantResult, simulate_variant
from simple_gap_variant_data import load_candidates
from simple_gap_variant_search import combined_score, result_score, row_payload

DEFAULT_DB_PATH = "data/edge_research_universe_15y.sqlite3"
DEFAULT_OUT_DIR = "data/simple_gap_realistic_search"
RANKS = ("lowest_price", "lowest_price", "lowest_price", "gap_then_quiet", "largest_gap", "quiet_volume")
PRESET_CONFIGS: Final = (
    ("risk_anchor", 30000.0, 1000.0, 10000.0, -0.04, 0.0, 1.0, 0, 1, "lowest_price", 0.0035, 0.0, 0.02, None),
    ("wide_stop", 30000.0, 2000.0, 15000.0, -0.02, 0.1, 1.5, 0, 1, "lowest_price", 0.0035, 0.0, 0.05, None),
    ("deep_gap", 100000.0, 2000.0, 15000.0, -0.06, 0.0, 1.25, 0, 1, "lowest_price", 0.0035, 0.0, 0.02, 0.12),
    ("robust_gap5", 30000.0, 1000.0, 8000.0, -0.05, 0.0, 0.8, 0, 1, "lowest_price", 0.0035, 0.0, 0.02, 0.12),
    ("quiet_gap5", 30000.0, 1000.0, 10000.0, -0.05, 0.0, 0.65, 0, 1, "lowest_price", 0.0035, 0.0, 0.02, None),
)


class SearchArgs(argparse.Namespace):
    db_path: str
    out_dir: str
    seconds: float
    max_iterations: int
    seed: int
    keep_top: int
    write_every: int
    start: str
    end: str
    broad_gap: float
    train_start: str
    train_end: str
    test_start: str
    test_end: str
    recent_start: str


def split_rows(rows: Sequence[Candidate], *, start: str, end: str) -> list[Candidate]:
    return [row for row in rows if start <= row.date <= end]


def preset_config(idx: int) -> VariantConfig | None:
    if idx > len(PRESET_CONFIGS):
        return None
    name, capital, min_price, max_price, gap, vol_min, vol_max, exit_offset, top_n, rank, cost, slip, stop, take = PRESET_CONFIGS[idx - 1]
    return VariantConfig(f"r{idx:06d}_{name}", capital, min_price, max_price, gap, vol_min, vol_max, exit_offset, top_n, rank, cost, slip, stop, take)


def choose_config(rng: random.Random, idx: int) -> VariantConfig:
    preset = preset_config(idx)
    if preset is not None:
        return preset
    min_price = rng.choice((500.0, 1000.0, 1000.0, 1500.0, 2000.0, 3000.0))
    max_price = rng.choice((8000.0, 10000.0, 10000.0, 15000.0, 20000.0, 30000.0))
    if max_price <= min_price:
        max_price = min_price + 7000.0
    exit_offset = rng.choice((0, 0, 0, 0, 1, 2, 3))
    stop_loss = rng.choice((0.015, 0.02, 0.02, 0.025, 0.03, 0.04, 0.05)) if exit_offset == 0 else None
    take_profit = rng.choice((None, None, 0.06, 0.08, 0.12, 0.18)) if exit_offset == 0 else None
    vol_min = rng.choice((0.0, 0.0, 0.1, 0.2, 0.3, 0.4))
    vol_max = rng.choice((0.5, 0.65, 0.8, 1.0, 1.25, 1.5, 2.0))
    if vol_max <= vol_min:
        vol_max = vol_min + 0.5
    return VariantConfig(
        name=f"r{idx:06d}",
        capital=rng.choice((10000.0, 30000.0, 100000.0, 300000.0)),
        min_price=min_price,
        max_price=max_price,
        gap_threshold=rng.choice((-0.015, -0.02, -0.025, -0.03, -0.035, -0.04, -0.05, -0.06, -0.08, -0.10)),
        prev_vol_ratio_min=vol_min,
        prev_vol_ratio_max=vol_max,
        exit_offset=exit_offset,
        top_n=rng.choice((1, 1, 1, 1, 2)),
        rank=rng.choice(RANKS),
        roundtrip_cost=rng.choice((0.0035, 0.0045, 0.0055)),
        slippage=rng.choice((0.0, 0.001, 0.002, 0.003, 0.005)),
        stop_loss=stop_loss,
        take_profit=take_profit,
    )


def choose_market_filter(rng: random.Random, idx: int) -> MarketFilter:
    if idx <= len(PRESET_CONFIGS):
        return MarketFilter(name=f"m{idx:06d}_all")
    if rng.random() < 0.12:
        return MarketFilter(name=f"m{idx:06d}_all")
    gap_min = rng.choice((None, -0.04, -0.03, -0.02, -0.01))
    gap_max = rng.choice((None, 0.005, 0.015, 0.03, 0.05))
    ret_min = rng.choice((None, -0.04, -0.02, -0.01, 0.0))
    ret_max = rng.choice((None, 0.0, 0.02, 0.04, 0.06))
    breadth_min = rng.choice((None, 0.15, 0.25, 0.35, 0.45))
    breadth_max = rng.choice((None, 0.45, 0.55, 0.65, 0.75))
    if gap_min is not None and gap_max is not None and gap_min > gap_max:
        gap_max = None
    if ret_min is not None and ret_max is not None and ret_min > ret_max:
        ret_max = None
    if breadth_min is not None and breadth_max is not None and breadth_min > breadth_max:
        breadth_max = None
    return MarketFilter(
        name=f"m{idx:06d}",
        market_gap_min=gap_min,
        market_gap_max=gap_max,
        prev_market_return_min=ret_min,
        prev_market_return_max=ret_max,
        prev_breadth_up_min=breadth_min,
        prev_breadth_up_max=breadth_max,
        volatility20_max=rng.choice((None, 0.018, 0.022, 0.028, 0.035, 0.045)),
        prev_avg_range_max=rng.choice((None, 0.055, 0.075, 0.095, 0.13)),
    )


def is_unbounded(market_filter: MarketFilter) -> bool:
    return all(value is None for key, value in asdict(market_filter).items() if key != "name")


def market_rows(rows: Sequence[Candidate], contexts: dict[str, MarketContext], market_filter: MarketFilter) -> list[Candidate]:
    if is_unbounded(market_filter):
        return list(rows)
    return filter_candidates_by_market(rows, contexts, market_filter)


def stress_config(config: VariantConfig, *, suffix: str, slippage_add: float, cost_add: float) -> VariantConfig:
    return replace(
        config,
        name=f"{config.name}_{suffix}",
        slippage=config.slippage + slippage_add,
        roundtrip_cost=config.roundtrip_cost + cost_add,
    )


def realistic_score(train: VariantResult, test: VariantResult, recent: VariantResult, mid: VariantResult, harsh: VariantResult) -> float:
    base = combined_score(train, test, recent)
    mid_score = result_score(mid)
    harsh_score = result_score(harsh)
    if min(base, mid_score, harsh_score) <= -900.0:
        return -999.0
    base_growth = math.log1p(max(-0.99, test.compounded_return))
    harsh_growth = math.log1p(max(-0.99, harsh.compounded_return))
    stress_decay = max(0.0, base_growth - harsh_growth)
    worst_drawdown = max(test.max_drawdown, mid.max_drawdown, harsh.max_drawdown)
    return base * 0.45 + mid_score * 0.25 + harsh_score * 0.30 - worst_drawdown * 1.4 - stress_decay * 0.12


def evaluate(
    rows: tuple[list[Candidate], list[Candidate], list[Candidate]],
    contexts: dict[str, MarketContext],
    config: VariantConfig,
    market_filter: MarketFilter,
) -> tuple[float, MarketFilter, VariantResult, VariantResult, VariantResult, VariantResult, VariantResult]:
    train_rows = market_rows(rows[0], contexts, market_filter)
    test_rows = market_rows(rows[1], contexts, market_filter)
    recent_rows = market_rows(rows[2], contexts, market_filter)
    train = simulate_variant(train_rows, config)
    test = simulate_variant(test_rows, config)
    recent = simulate_variant(recent_rows, config)
    mid = simulate_variant(test_rows, stress_config(config, suffix="mid", slippage_add=0.003, cost_add=0.001))
    harsh = simulate_variant(test_rows, stress_config(config, suffix="harsh", slippage_add=0.008, cost_add=0.002))
    return realistic_score(train, test, recent, mid, harsh), market_filter, train, test, recent, mid, harsh


def update_top(top: list[tuple[float, MarketFilter, VariantResult, VariantResult, VariantResult, VariantResult, VariantResult]], item, limit: int) -> None:
    top.append(item)
    top.sort(key=lambda row: row[0], reverse=True)
    del top[limit:]


def write_outputs(out_dir: Path, top, *, iterations: int, elapsed: float, loaded_rows: int, contexts: int) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "iterations": iterations,
        "elapsed_seconds": elapsed,
        "loaded_candidate_rows": loaded_rows,
        "loaded_market_contexts": contexts,
        "top": [
            {
                "score": score,
                "market_filter": asdict(market_filter),
                "train": row_payload(train, period="train", score=score),
                "test": row_payload(test, period="test", score=score),
                "recent": row_payload(recent, period="recent", score=score),
                "mid_stress": row_payload(mid, period="mid_stress", score=score),
                "harsh_stress": row_payload(harsh, period="harsh_stress", score=score),
            }
            for score, market_filter, train, test, recent, mid, harsh in top
        ],
    }
    (out_dir / "summary.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    with (out_dir / "top_configs.csv").open("w", newline="", encoding="utf-8") as handle:
        fieldnames = list(payload["top"][0]["test"].keys()) + [f"market_{key}" for key in payload["top"][0]["market_filter"]] if top else ["period"]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in payload["top"]:
            writer.writerow(row["test"] | {f"market_{key}": value for key, value in row["market_filter"].items()})
    lines = ["# realistic simple_gap search", "", f"- iterations: {iterations}", f"- elapsed_seconds: {elapsed:.1f}", f"- loaded_candidate_rows: {loaded_rows}", f"- loaded_market_contexts: {contexts}", ""]
    lines.append("| rank | score | test compounded | test MDD | harsh compounded | harsh MDD | trades | config |")
    lines.append("|---:|---:|---:|---:|---:|---:|---:|---|")
    for pos, (score, market_filter, _train, test, _recent, _mid, harsh) in enumerate(top[:25], 1):
        cfg = test.config
        label = f"gap<={cfg.gap_threshold}, price {cfg.min_price:.0f}-{cfg.max_price:.0f}, vol {cfg.prev_vol_ratio_min:.2f}-{cfg.prev_vol_ratio_max:.2f}, exit {cfg.exit_offset}, top{cfg.top_n}, {cfg.rank}, stop {cfg.stop_loss}, market {market_filter.name}"
        lines.append(f"| {pos} | {score:.4f} | {test.compounded_return:+.2%} | {test.max_drawdown:.2%} | {harsh.compounded_return:+.2%} | {harsh.max_drawdown:.2%} | {test.trades} | {label} |")
    (out_dir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(args: SearchArgs) -> None:
    started = time.monotonic()
    rows = load_candidates(args.db_path, start=args.start, end=args.end, broad_gap=args.broad_gap)
    contexts = dict(load_market_contexts(args.db_path, MarketContextQuery(args.start, args.end)))
    row_sets = (
        split_rows(rows, start=args.train_start, end=args.train_end),
        split_rows(rows, start=args.test_start, end=args.test_end),
        split_rows(rows, start=args.recent_start, end=args.test_end),
    )
    rng = random.Random(args.seed)
    deadline = time.monotonic() + args.seconds
    top: list[tuple[float, MarketFilter, VariantResult, VariantResult, VariantResult, VariantResult, VariantResult]] = []
    iterations = 0
    while time.monotonic() < deadline and iterations < args.max_iterations:
        item = evaluate(row_sets, contexts, choose_config(rng, iterations + 1), choose_market_filter(rng, iterations + 1))
        if item[0] > -900.0:
            update_top(top, item, args.keep_top)
        iterations += 1
        if iterations % args.write_every == 0 and top:
            write_outputs(Path(args.out_dir), top, iterations=iterations, elapsed=time.monotonic() - started, loaded_rows=len(rows), contexts=len(contexts))
    write_outputs(Path(args.out_dir), top, iterations=iterations, elapsed=time.monotonic() - started, loaded_rows=len(rows), contexts=len(contexts))
    print(json.dumps({"iterations": iterations, "elapsed_seconds": time.monotonic() - started, "rows": len(rows), "contexts": len(contexts), "out_dir": args.out_dir}, ensure_ascii=False, default=str))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db-path", default=DEFAULT_DB_PATH)
    parser.add_argument("--out-dir", default=DEFAULT_OUT_DIR)
    parser.add_argument("--seconds", type=float, default=3600.0)
    parser.add_argument("--max-iterations", type=int, default=10_000_000)
    parser.add_argument("--seed", type=int, default=20260704)
    parser.add_argument("--keep-top", type=int, default=150)
    parser.add_argument("--write-every", type=int, default=25)
    parser.add_argument("--start", default="2016-01-01")
    parser.add_argument("--end", default="2026-07-03")
    parser.add_argument("--broad-gap", type=float, default=-0.01)
    parser.add_argument("--train-start", default="2016-01-01")
    parser.add_argument("--train-end", default="2023-12-31")
    parser.add_argument("--test-start", default="2024-01-01")
    parser.add_argument("--test-end", default="2026-07-03")
    parser.add_argument("--recent-start", default="2025-01-01")
    run(parser.parse_args(namespace=SearchArgs()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
