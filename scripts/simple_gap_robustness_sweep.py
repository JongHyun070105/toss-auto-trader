from __future__ import annotations

import argparse
import csv
import json
import math
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Final, Mapping, Sequence

from simple_gap_market_context import MarketContext, MarketContextQuery, MarketFilter, load_market_contexts
from simple_gap_realistic_search import evaluate, split_rows
from simple_gap_variant_core import Candidate, VariantConfig, VariantResult
from simple_gap_variant_data import load_candidates
from simple_gap_variant_search import result_score, row_payload

DEFAULT_DB_PATH: Final = "data/edge_research_universe_15y.sqlite3"
DEFAULT_SOURCE_SUMMARY: Final = "data/simple_gap_realistic_search_until_0850_fg2/summary.json"
DEFAULT_OUT_DIR: Final = "data/simple_gap_robustness_sweep"
GAPS: Final = (-0.035, -0.04, -0.045, -0.05, -0.06, -0.08, -0.10)
MAX_PRICES: Final = (8000.0, 10000.0, 15000.0, 20000.0, 30000.0)
VOLUME_MAXES: Final = (0.5, 0.65, 0.8, 1.0, 1.25)
STOPS: Final = (0.015, 0.02, 0.025, 0.03, 0.04)
TAKES: Final = (None, 0.08, 0.12, 0.18)


@dataclass(frozen=True, slots=True)
class ResultBundle:
    train: VariantResult
    test: VariantResult
    recent: VariantResult
    mid: VariantResult
    harsh: VariantResult


@dataclass(frozen=True, slots=True)
class SweepInput:
    rows: tuple[list[Candidate], list[Candidate], list[Candidate]]
    contexts: Mapping[str, MarketContext]
    market_filters: tuple[MarketFilter, ...]


@dataclass(frozen=True, slots=True)
class SweepResult:
    score: float
    market_filter: MarketFilter
    bundle: ResultBundle


@dataclass(frozen=True, slots=True)
class RunMeta:
    generated_at: str
    loaded_candidate_rows: int
    loaded_market_contexts: int


class SweepArgs(argparse.Namespace):
    db_path: str
    source_summary: str
    out_dir: str
    seed_limit: int
    config_limit: int
    keep_top: int
    start: str
    end: str
    broad_gap: float
    train_start: str
    train_end: str
    test_start: str
    test_end: str
    recent_start: str


def _unique_floats(seed: float | None, values: Sequence[float | None]) -> tuple[float | None, ...]:
    seen: set[float | None] = set()
    ordered: list[float | None] = []
    for value in (seed, *values):
        if value not in seen:
            seen.add(value)
            ordered.append(value)
    return tuple(ordered)


def config_neighborhood(seed: VariantConfig, *, limit: int) -> list[VariantConfig]:
    configs: list[VariantConfig] = []
    seen: set[tuple[float, float, float, float | None, float | None]] = set()
    for max_price in _unique_floats(seed.max_price, MAX_PRICES):
        for volume_max in _unique_floats(seed.prev_vol_ratio_max, VOLUME_MAXES):
            for stop in _unique_floats(seed.stop_loss, STOPS):
                for take in _unique_floats(seed.take_profit, TAKES):
                    for gap in _unique_floats(seed.gap_threshold, GAPS):
                        if gap is None or max_price is None or volume_max is None:
                            continue
                        key = (gap, max_price, volume_max, stop, take)
                        if key in seen:
                            continue
                        seen.add(key)
                        configs.append(
                            VariantConfig(
                                name=f"{seed.name}_n{len(configs):03d}",
                                capital=seed.capital,
                                min_price=seed.min_price,
                                max_price=max_price,
                                gap_threshold=gap,
                                prev_vol_ratio_min=seed.prev_vol_ratio_min,
                                prev_vol_ratio_max=volume_max,
                                exit_offset=0,
                                top_n=1,
                                rank="lowest_price",
                                roundtrip_cost=seed.roundtrip_cost,
                                slippage=seed.slippage,
                                stop_loss=stop,
                                take_profit=take,
                            )
                        )
                        if len(configs) >= limit:
                            return configs
    return configs


def robust_score(bundle: ResultBundle) -> float:
    scores = (result_score(bundle.train), result_score(bundle.test), result_score(bundle.recent), result_score(bundle.mid), result_score(bundle.harsh))
    if min(scores) <= -900.0:
        return -999.0
    test_growth = math.log1p(max(-0.99, bundle.test.compounded_return))
    harsh_growth = math.log1p(max(-0.99, bundle.harsh.compounded_return))
    worst_drawdown = max(bundle.test.max_drawdown, bundle.mid.max_drawdown, bundle.harsh.max_drawdown)
    stress_decay = max(0.0, test_growth - harsh_growth)
    return scores[0] * 0.10 + scores[1] * 0.25 + scores[2] * 0.20 + scores[3] * 0.15 + scores[4] * 0.30 - worst_drawdown * 2.0 - stress_decay * 0.18


def seed_config(payload: Mapping[str, str | int | float | None], *, name: str) -> VariantConfig:
    return VariantConfig(
        name=name,
        capital=float(payload["capital"] or 30000.0),
        min_price=float(payload["min_price"] or 1000.0),
        max_price=float(payload["max_price"] or 10000.0),
        gap_threshold=float(payload["gap_threshold"] or -0.05),
        prev_vol_ratio_min=float(payload["prev_vol_ratio_min"] or 0.0),
        prev_vol_ratio_max=float(payload["prev_vol_ratio_max"] or 1.0),
        exit_offset=0,
        top_n=1,
        rank="lowest_price",
        roundtrip_cost=0.0035,
        slippage=float(payload["slippage"] or 0.0),
        stop_loss=None if payload["stop_loss"] is None else float(payload["stop_loss"]),
        take_profit=None if payload["take_profit"] is None else float(payload["take_profit"]),
    )


def load_seed_configs(path: Path, *, limit: int) -> list[VariantConfig]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    seeds: list[VariantConfig] = []
    for idx, row in enumerate(payload["top"][:limit]):
        seeds.append(seed_config(row["test"], name=f"s{idx + 1:02d}_{row['test']['name']}"))
    return seeds


def market_filters() -> tuple[MarketFilter, ...]:
    return (
        MarketFilter(name="all"),
        MarketFilter(name="avoid_crash_open", market_gap_min=-0.04, market_gap_max=0.04),
        MarketFilter(name="calm_prev", prev_market_return_min=-0.02, prev_breadth_up_min=0.25, volatility20_max=0.035),
        MarketFilter(name="calm_range", volatility20_max=0.028, prev_avg_range_max=0.095),
    )


def build_input(args: SweepArgs) -> tuple[SweepInput, int]:
    rows = load_candidates(args.db_path, start=args.start, end=args.end, broad_gap=args.broad_gap)
    contexts = load_market_contexts(args.db_path, MarketContextQuery(args.start, args.end))
    row_sets = (
        split_rows(rows, start=args.train_start, end=args.train_end),
        split_rows(rows, start=args.test_start, end=args.test_end),
        split_rows(rows, start=args.recent_start, end=args.test_end),
    )
    return SweepInput(row_sets, contexts, market_filters()), len(rows)


def run_sweep(sweep_input: SweepInput, configs: Sequence[VariantConfig], *, keep_top: int) -> list[SweepResult]:
    top: list[SweepResult] = []
    for config in configs:
        for market_filter in sweep_input.market_filters:
            score, used_filter, train, test, recent, mid, harsh = evaluate(sweep_input.rows, sweep_input.contexts, config, market_filter)
            bundle = ResultBundle(train, test, recent, mid, harsh)
            robust = min(score, robust_score(bundle))
            if robust <= -900.0:
                continue
            top.append(SweepResult(robust, used_filter, bundle))
            top.sort(key=lambda row: row.score, reverse=True)
            del top[keep_top:]
    return top


def output_row(result: SweepResult) -> dict[str, str | int | float | None]:
    test = row_payload(result.bundle.test, period="test", score=result.score)
    harsh = result.bundle.harsh
    return test | {
        "market_filter": result.market_filter.name,
        "harsh_compounded_return": harsh.compounded_return,
        "harsh_max_drawdown": harsh.max_drawdown,
        "harsh_profit_factor": harsh.profit_factor,
    }


def write_outputs(out_dir: Path, results: Sequence[SweepResult], meta: RunMeta) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": meta.generated_at,
        "loaded_candidate_rows": meta.loaded_candidate_rows,
        "loaded_market_contexts": meta.loaded_market_contexts,
        "top": [
            {
                "score": row.score,
                "market_filter": asdict(row.market_filter),
                "train": row_payload(row.bundle.train, period="train", score=row.score),
                "test": row_payload(row.bundle.test, period="test", score=row.score),
                "recent": row_payload(row.bundle.recent, period="recent", score=row.score),
                "mid_stress": row_payload(row.bundle.mid, period="mid_stress", score=row.score),
                "harsh_stress": row_payload(row.bundle.harsh, period="harsh_stress", score=row.score),
            }
            for row in results
        ],
    }
    (out_dir / "summary.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    with (out_dir / "top_configs.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(output_row(results[0]).keys()) if results else ["period"])
        writer.writeheader()
        for result in results:
            writer.writerow(output_row(result))
    lines = ["# simple_gap robustness sweep", "", f"- generated_at: {meta.generated_at}", f"- loaded_candidate_rows: {meta.loaded_candidate_rows}", f"- loaded_market_contexts: {meta.loaded_market_contexts}", ""]
    lines.append("| rank | score | test compounded | test MDD | harsh compounded | harsh MDD | trades | config |")
    lines.append("|---:|---:|---:|---:|---:|---:|---:|---|")
    for pos, row in enumerate(results[:25], 1):
        cfg = row.bundle.test.config
        label = f"gap<={cfg.gap_threshold}, price {cfg.min_price:.0f}-{cfg.max_price:.0f}, vol {cfg.prev_vol_ratio_min:.2f}-{cfg.prev_vol_ratio_max:.2f}, stop {cfg.stop_loss}, take {cfg.take_profit}, market {row.market_filter.name}"
        lines.append(f"| {pos} | {row.score:.4f} | {row.bundle.test.compounded_return:+.2%} | {row.bundle.test.max_drawdown:.2%} | {row.bundle.harsh.compounded_return:+.2%} | {row.bundle.harsh.max_drawdown:.2%} | {row.bundle.test.trades} | {label} |")
    (out_dir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(args: SweepArgs) -> None:
    seeds = load_seed_configs(Path(args.source_summary), limit=args.seed_limit)
    configs = [config for seed in seeds for config in config_neighborhood(seed, limit=args.config_limit)]
    sweep_input, loaded_rows = build_input(args)
    results = run_sweep(sweep_input, configs, keep_top=args.keep_top)
    meta = RunMeta(datetime.now().strftime("%Y-%m-%d %H:%M:%S"), loaded_rows, len(sweep_input.contexts))
    write_outputs(Path(args.out_dir), results, meta)
    print(json.dumps({"evaluated_configs": len(configs), "evaluated_pairs": len(configs) * len(sweep_input.market_filters), "out_dir": args.out_dir}, ensure_ascii=False))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db-path", default=DEFAULT_DB_PATH)
    parser.add_argument("--source-summary", default=DEFAULT_SOURCE_SUMMARY)
    parser.add_argument("--out-dir", default=DEFAULT_OUT_DIR)
    parser.add_argument("--seed-limit", type=int, default=12)
    parser.add_argument("--config-limit", type=int, default=180)
    parser.add_argument("--keep-top", type=int, default=120)
    parser.add_argument("--start", default="2016-01-01")
    parser.add_argument("--end", default="2026-07-03")
    parser.add_argument("--broad-gap", type=float, default=-0.01)
    parser.add_argument("--train-start", default="2016-01-01")
    parser.add_argument("--train-end", default="2023-12-31")
    parser.add_argument("--test-start", default="2024-01-01")
    parser.add_argument("--test-end", default="2026-07-03")
    parser.add_argument("--recent-start", default="2025-01-01")
    run(parser.parse_args(namespace=SweepArgs()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
