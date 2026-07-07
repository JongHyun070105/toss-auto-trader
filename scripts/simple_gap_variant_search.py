from __future__ import annotations

import argparse
import csv
import json
import math
import random
import time
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from simple_gap_variant_core import VariantConfig, VariantResult, simulate_variant
from simple_gap_variant_data import load_candidates

DEFAULT_DB_PATH = "data/edge_research_universe_15y.sqlite3"
DEFAULT_OUT_DIR = "data/simple_gap_variant_search"
RANKS = ("largest_gap", "quiet_volume", "lowest_price", "highest_price", "gap_then_quiet")


def split_rows(rows, *, start: str, end: str):
    return [row for row in rows if start <= row.date <= end]


def choose_config(rng: random.Random, idx: int) -> VariantConfig:
    min_price = rng.choice((1000.0, 2000.0, 3000.0, 5000.0, 8000.0, 10000.0))
    max_price = rng.choice((10000.0, 15000.0, 20000.0, 30000.0, 50000.0))
    if max_price <= min_price:
        max_price = min_price + 10000.0
    vol_min = rng.choice((0.0, 0.1, 0.2, 0.3, 0.4))
    vol_max = rng.choice((0.5, 0.65, 0.8, 1.0, 1.25, 1.5, 2.0))
    if vol_max <= vol_min:
        vol_max = vol_min + 0.5
    exit_offset = rng.choice((0, 1, 2, 3, 5, 10))
    stop_loss = None
    take_profit = None
    if exit_offset == 0:
        stop_loss = rng.choice((None, 0.02, 0.03, 0.05, 0.07))
        take_profit = rng.choice((None, 0.03, 0.05, 0.08, 0.12))
    return VariantConfig(
        name=f"v{idx:06d}",
        capital=rng.choice((10000.0, 30000.0, 100000.0, 300000.0, 1000000.0)),
        min_price=min_price,
        max_price=max_price,
        gap_threshold=rng.choice((-0.015, -0.02, -0.025, -0.03, -0.035, -0.04, -0.05, -0.06, -0.08)),
        prev_vol_ratio_min=vol_min,
        prev_vol_ratio_max=vol_max,
        exit_offset=exit_offset,
        top_n=rng.choice((1, 1, 1, 2, 3)),
        rank=rng.choice(RANKS),
        roundtrip_cost=0.0035,
        slippage=rng.choice((0.0, 0.001, 0.002, 0.003, 0.005)),
        stop_loss=stop_loss,
        take_profit=take_profit,
    )


def result_score(result: VariantResult) -> float:
    if result.trades < 40 or result.active_days < 30:
        return -999.0
    pf = result.profit_factor if result.profit_factor is not None else 0.0
    growth = math.log1p(max(-0.99, result.compounded_return))
    median = result.median_day_return if result.median_day_return is not None else 0.0
    return growth - result.max_drawdown * 0.8 + min(pf, 4.0) * 0.05 + median * 20.0


def combined_score(train: VariantResult, test: VariantResult, recent: VariantResult) -> float:
    train_score = result_score(train)
    test_score = result_score(test)
    recent_score = result_score(recent)
    if min(train_score, test_score, recent_score) <= -900.0:
        return -999.0
    train_growth = math.log1p(max(-0.99, train.compounded_return))
    test_growth = math.log1p(max(-0.99, test.compounded_return))
    consistency_penalty = abs(train_growth - test_growth) * 0.08
    return test_score * 0.55 + recent_score * 0.30 + train_score * 0.15 - consistency_penalty


def row_payload(result: VariantResult, *, period: str, score: float):
    cfg = result.config
    return {
        "period": period,
        "score": score,
        "name": cfg.name,
        "capital": cfg.capital,
        "min_price": cfg.min_price,
        "max_price": cfg.max_price,
        "gap_threshold": cfg.gap_threshold,
        "prev_vol_ratio_min": cfg.prev_vol_ratio_min,
        "prev_vol_ratio_max": cfg.prev_vol_ratio_max,
        "exit_offset": cfg.exit_offset,
        "top_n": cfg.top_n,
        "rank": cfg.rank,
        "roundtrip_cost": cfg.roundtrip_cost,
        "slippage": cfg.slippage,
        "stop_loss": cfg.stop_loss,
        "take_profit": cfg.take_profit,
        "trades": result.trades,
        "active_days": result.active_days,
        "avg_day_return": result.avg_day_return,
        "median_day_return": result.median_day_return,
        "win_rate_days": result.win_rate_days,
        "win_rate_trades": result.win_rate_trades,
        "compounded_return": result.compounded_return,
        "max_drawdown": result.max_drawdown,
        "profit_factor": result.profit_factor,
        "avg_cash_used_pct": result.avg_cash_used_pct,
    }


def update_top(top: list[tuple[float, VariantResult, VariantResult, VariantResult]], item, limit: int) -> None:
    top.append(item)
    top.sort(key=lambda row: row[0], reverse=True)
    del top[limit:]


def write_outputs(out_dir: Path, top, *, iterations: int, elapsed: float, loaded_rows: int) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "iterations": iterations,
        "elapsed_seconds": elapsed,
        "loaded_candidate_rows": loaded_rows,
        "train_window": "2016-01-01..2023-12-31",
        "test_window": "2024-01-01..2026-07-03",
        "top": [
            {
                "score": score,
                "train": row_payload(train, period="train", score=score),
                "test": row_payload(test, period="test", score=score),
                "recent": row_payload(recent, period="recent", score=score),
                "sample_trades": [asdict(row) for row in test.sample_trades],
            }
            for score, train, test, recent in top
        ],
    }
    (out_dir / "summary.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    with (out_dir / "top_configs.csv").open("w", newline="", encoding="utf-8") as handle:
        fieldnames = list(row_payload(top[0][2], period="test", score=top[0][0]).keys()) if top else ["period"]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for score, _train, test, _recent in top:
            writer.writerow(row_payload(test, period="test", score=score))
    lines = ["# simple_gap variant search", "", f"- iterations: {iterations}", f"- elapsed_seconds: {elapsed:.1f}", f"- loaded_candidate_rows: {loaded_rows}", ""]
    lines.append("| rank | score | test compounded | test MDD | trades | config |")
    lines.append("|---:|---:|---:|---:|---:|---|")
    for pos, (score, _train, test, _recent) in enumerate(top[:20], 1):
        cfg = test.config
        label = f"gap<={cfg.gap_threshold}, price {cfg.min_price:.0f}-{cfg.max_price:.0f}, vol {cfg.prev_vol_ratio_min:.2f}-{cfg.prev_vol_ratio_max:.2f}, exit {cfg.exit_offset}, top{cfg.top_n}, {cfg.rank}, slip {cfg.slippage}"
        lines.append(f"| {pos} | {score:.4f} | {test.compounded_return:+.2%} | {test.max_drawdown:.2%} | {test.trades} | {label} |")
    (out_dir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(args) -> None:
    started = time.monotonic()
    rows = load_candidates(args.db_path, start=args.start, end=args.end, broad_gap=args.broad_gap)
    train_rows = split_rows(rows, start=args.train_start, end=args.train_end)
    test_rows = split_rows(rows, start=args.test_start, end=args.test_end)
    recent_rows = split_rows(rows, start=args.recent_start, end=args.test_end)
    rng = random.Random(args.seed)
    deadline = time.monotonic() + args.seconds
    top: list[tuple[float, VariantResult, VariantResult, VariantResult]] = []
    iterations = 0
    while time.monotonic() < deadline and iterations < args.max_iterations:
        cfg = choose_config(rng, iterations + 1)
        train = simulate_variant(train_rows, cfg)
        test = simulate_variant(test_rows, cfg)
        recent = simulate_variant(recent_rows, cfg)
        score = combined_score(train, test, recent)
        if score > -900.0:
            update_top(top, (score, train, test, recent), args.keep_top)
        iterations += 1
        if iterations % args.write_every == 0 and top:
            write_outputs(Path(args.out_dir), top, iterations=iterations, elapsed=time.monotonic() - started, loaded_rows=len(rows))
    write_outputs(Path(args.out_dir), top, iterations=iterations, elapsed=time.monotonic() - started, loaded_rows=len(rows))
    print(json.dumps({"iterations": iterations, "elapsed_seconds": time.monotonic() - started, "rows": len(rows), "out_dir": args.out_dir}, ensure_ascii=False, default=str))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db-path", default=DEFAULT_DB_PATH)
    parser.add_argument("--out-dir", default=DEFAULT_OUT_DIR)
    parser.add_argument("--seconds", type=float, default=3600.0)
    parser.add_argument("--max-iterations", type=int, default=10_000_000)
    parser.add_argument("--seed", type=int, default=20260703)
    parser.add_argument("--keep-top", type=int, default=100)
    parser.add_argument("--write-every", type=int, default=25)
    parser.add_argument("--start", default="2016-01-01")
    parser.add_argument("--end", default="2026-07-03")
    parser.add_argument("--broad-gap", type=float, default=-0.01)
    parser.add_argument("--train-start", default="2016-01-01")
    parser.add_argument("--train-end", default="2023-12-31")
    parser.add_argument("--test-start", default="2024-01-01")
    parser.add_argument("--test-end", default="2026-07-03")
    parser.add_argument("--recent-start", default="2025-01-01")
    run(parser.parse_args())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
