#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path

PAIRS = [
    "336570:6000+462860:4000",
    "336570:6000+032620:4000",
    "204620:6000+462860:4000",
    "204620:6000+032620:4000",
    "073240:6000+462860:4000",
    "073240:6000+032620:4000",
]

BRANCHES = "fee_aware_momentum,balanced_momentum_v2,balanced_momentum,technical_aggressive,ultra_conservative,conservative_guarded,observation_first"


def copy_candle_cache(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        dst.unlink()
    source = sqlite3.connect(src)
    target = sqlite3.connect(dst)
    try:
        for line in source.iterdump():
            if "CREATE TABLE" in line or "CREATE INDEX" in line or 'INSERT INTO "candle_cache"' in line:
                try:
                    target.execute(line)
                except sqlite3.OperationalError:
                    pass
        target.commit()
    finally:
        source.close()
        target.close()


def scale_pair(raw_pair: str, capital: int) -> str:
    parts = []
    parsed = []
    for part in raw_pair.split('+'):
        sym, cash = part.split(':', 1)
        parsed.append((sym, int(cash)))
    base = sum(c for _, c in parsed) or 10000
    for sym, cash in parsed:
        parts.append(f"{sym}:{int(round(capital * cash / base))}")
    return '+'.join(parts)


def max_pair_slot(raw_pair: str) -> int:
    return max(int(part.split(':', 1)[1]) for part in raw_pair.split('+') if ':' in part)


def run_one(repo: Path, src_db: Path, out_dir: Path, pair: str, window: int, horizon: int, max_bars: int, isolated_slots: bool = False, compact_events: bool = True, exclude_last_bars: int = 0, initial_cash: int = 10000, config: str = 'config.example.yaml') -> dict:
    safe = pair.replace(":", "-").replace("+", "__")
    mode = "isolated" if isolated_slots else "shared"
    suffix = f"{mode}_x{exclude_last_bars}" if exclude_last_bars else mode
    db_path = out_dir / f"pair_{safe}_w{window}_h{horizon}_{suffix}.sqlite3"
    json_path = out_dir / f"pair_{safe}_w{window}_h{horizon}_{mode}.json"
    copy_candle_cache(src_db, db_path)
    env = os.environ.copy()
    env["PYTHONPATH"] = "src"
    env["TOSS_DB_PATH"] = str(db_path)
    cmd = [
        "python3", "-m", "toss_auto_trader.cli", "portfolio-pair-backtest",
        "--pairs", pair,
        "--config", config,
        "--window", str(window),
        "--horizon", str(horizon),
        "--max-bars", str(max_bars),
        "--initial-cash", str(initial_cash),
        "--max-order", str(max_pair_slot(pair)),
        "--branches", BRANCHES,
        "--status-every", "999999",
    ]
    if compact_events:
        cmd.append("--compact-events")
    if exclude_last_bars:
        cmd.extend(["--exclude-last-bars", str(exclude_last_bars)])
    if isolated_slots:
        cmd.append("--isolated-slots")
    proc = subprocess.run(cmd, cwd=repo, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=300)
    if proc.returncode != 0:
        return {"pair": pair, "window": window, "horizon": horizon, "error": proc.stderr[-2000:]}
    json_path.write_text(proc.stdout)
    data = json.loads(proc.stdout)
    rows = []
    for item in data.get("pair_summaries", []):
        account = item["account"]
        branch = account.split(":", 2)[-1]
        rows.append({
            "pair": pair,
            "window": window,
            "horizon": horizon,
            "branch": branch,
            "equity": float(item["equity"]),
            "pnl": float(item["pnl"]),
            "db": str(db_path),
            "json": str(json_path),
            "mode": "isolated_slots" if isolated_slots else "shared_account",
            "exclude_last_bars": exclude_last_bars,
        })
    return {"rows": rows, "summary": data.get("summary", {})}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source-db", default="data/low_kr_backtest.sqlite3")
    ap.add_argument("--config", default="config.example.yaml")
    ap.add_argument("--out-dir", default="data/grid_runs")
    ap.add_argument("--windows", default="40,60,80")
    ap.add_argument("--horizons", default="1,3,5")
    ap.add_argument("--max-bars", type=int, default=180)
    ap.add_argument("--pairs", default=",".join(PAIRS))
    ap.add_argument("--capital", type=int, default=10000, help="virtual total capital; pair slots are scaled from 6000/4000 base")
    ap.add_argument("--limit", type=int, default=0, help="debug: run only first N combinations")
    ap.add_argument("--isolated-slots", action="store_true", help="compare strict 6k/4k sub-ledgers instead of one shared account")
    ap.add_argument("--full-events", action="store_true", help="log ordinary HOLD events too; default is compact")
    ap.add_argument("--exclude-last-bars", type=int, default=0, help="walk-forward: drop latest N bars before max-bars")
    args = ap.parse_args()
    repo = Path.cwd()
    src_db = repo / args.source_db
    out_dir = repo / args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    windows = [int(x) for x in args.windows.split(",") if x]
    horizons = [int(x) for x in args.horizons.split(",") if x]
    pairs = [scale_pair(x.strip(), args.capital) for x in args.pairs.split(",") if x.strip()]
    results: list[dict] = []
    n = 0
    for pair in pairs:
        for window in windows:
            for horizon in horizons:
                n += 1
                if args.limit and n > args.limit:
                    break
                result = run_one(repo, src_db, out_dir, pair, window, horizon, args.max_bars, args.isolated_slots, not args.full_events, args.exclude_last_bars, args.capital, args.config)
                if result.get("rows"):
                    results.extend(result["rows"])
                else:
                    results.append({"pair": pair, "window": window, "horizon": horizon, "error": result.get("error", "unknown")})
            if args.limit and n > args.limit:
                break
        if args.limit and n > args.limit:
            break
    ranked = sorted([r for r in results if "pnl" in r], key=lambda r: r["pnl"], reverse=True)
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_db": str(src_db),
        "config": args.config,
        "branches": BRANCHES.split(","),
        "windows": windows,
        "horizons": horizons,
        "capital_krw": args.capital,
        "pairs": pairs,
        "mode": "isolated_slots" if args.isolated_slots else "shared_account",
        "compact_events": not args.full_events,
        "exclude_last_bars": args.exclude_last_bars,
        "count": len(results),
        "top": ranked[:20],
        "all": results,
    }
    (out_dir / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    lines = ["# Pair grid summary", "", f"Generated: {report['generated_at']}", "", "| rank | pair | window | horizon | branch | equity | pnl |", "|---:|---|---:|---:|---|---:|---:|"]
    for i, r in enumerate(ranked[:20], 1):
        lines.append(f"| {i} | `{r['pair']}` | {r['window']} | {r['horizon']} | `{r['branch']}` | {r['equity']:.2f} | {r['pnl']:.2f} |")
    (out_dir / "summary.md").write_text("\n".join(lines) + "\n")
    print(json.dumps({"out_dir": str(out_dir), "top": ranked[:10], "count": len(results)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
