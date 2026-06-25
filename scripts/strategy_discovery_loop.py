#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from toss_auto_trader.strategy_discovery import append_jsonl, evaluate_strategy_artifacts, load_json_or_none

KST = ZoneInfo("Asia/Seoul")


def run_cmd(cmd: list[str], *, timeout: int = 1800) -> dict:
    env = os.environ.copy()
    env["PYTHONPATH"] = "src"
    # This loop is intentionally no-send. It must not enable live env flags.
    env["TOSS_DRY_RUN"] = "true"
    env["TOSS_LIVE_TRADING"] = "false"
    proc = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, timeout=timeout)
    return {
        "cmd": cmd,
        "returncode": proc.returncode,
        "stdout_tail": proc.stdout[-5000:],
        "stderr_tail": proc.stderr[-5000:],
    }


def command_pack(pack: str, source_db: str) -> list[list[str]]:
    if pack == "none":
        return []
    forward = [
        ["python3", "scripts/rsi_bbands_v3_forward_watch.py", "--source-db", source_db, "--symbols", "cached", "--limit", "50", "--out", "data/rsi_bbands_v3_forward_candidates_latest.json", "--ledger", "data/rsi_bbands_v3_forward_observations.jsonl"],
        ["python3", "scripts/rsi_bbands_v3_forward_outcome_update.py", "--source-db", source_db, "--ledger", "data/rsi_bbands_v3_forward_observations.jsonl", "--outcomes", "data/rsi_bbands_v3_forward_outcomes.jsonl", "--out", "data/rsi_bbands_v3_forward_outcome_latest.json"],
    ]
    if pack == "forward":
        return forward
    light = [
        ["python3", "scripts/market_regime_exposure_gate_audit.py", "--out", "data/market_regime_exposure_gate_latest.json", "--rows-out", "data/market_regime_exposure_gate_rows.csv"],
        ["python3", "scripts/relative_strength_horizon_audit.py", "--source-db", source_db, "--out", "data/relative_strength_horizon_latest.json", "--baskets-out", "data/relative_strength_horizon_baskets.csv", "--signals-out", "data/relative_strength_horizon_signals.csv"],
        ["python3", "scripts/event_liquidity_reaction_audit.py", "--source-db", source_db, "--news-db", "data/news_context_latest.sqlite3", "--symbol-map", "research/news_event_symbol_map.csv", "--allowed-markets", "KOSDAQ", "--out", "data/event_liquidity_reaction_latest.json", "--rows-out", "data/event_liquidity_reaction_rows.csv", "--pending-out", "data/event_liquidity_reaction_pending.jsonl"],
    ] + forward
    if pack == "light":
        return light
    if pack == "full":
        return [["python3", "scripts/run_post_collection_research.py", "--db-path", source_db, "--out", "data/post_collection_research_summary.json"]]
    raise ValueError(f"unknown audit pack: {pack}")


def cycle(args: argparse.Namespace) -> dict:
    observed_at = datetime.now(KST).isoformat()
    policy = load_json_or_none(args.policy) or {}
    steps = []
    for cmd in command_pack(args.audit_pack, args.source_db):
        steps.append(run_cmd(cmd, timeout=args.command_timeout))
    report = evaluate_strategy_artifacts(policy=policy)
    report.update({
        "observed_at_kst": observed_at,
        "loop_mode": "continuous_strategy_discovery_no_send",
        "audit_pack": args.audit_pack,
        "source_db": args.source_db,
        "steps": steps,
        "safety": {
            "order_sent": False,
            "live_order_allowed": False,
            "dry_run_env_for_children": True,
            "live_trading_env_for_children": False,
            "does_not_call_order_live_send": True,
            "next_live_step": "only after selected strategy has forward evidence, candidate pre-live gates pass, and separate exact live-order confirmation is supplied",
        },
    })
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    append_jsonl(args.ledger, report)
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description="Continuous no-send strategy discovery loop. It finds/reviews strategies but never sends live orders.")
    ap.add_argument("--source-db", default="data/edge_research_universe_long.sqlite3")
    ap.add_argument("--policy", default="research/strategy_research_policy.json")
    ap.add_argument("--audit-pack", choices=["none", "forward", "light", "full"], default="forward")
    ap.add_argument("--out", default="data/strategy_discovery_loop_latest.json")
    ap.add_argument("--ledger", default="data/strategy_discovery_loop_history.jsonl")
    ap.add_argument("--interval-seconds", type=int, default=3600)
    ap.add_argument("--max-cycles", type=int, default=1)
    ap.add_argument("--command-timeout", type=int, default=1800)
    args = ap.parse_args()

    cycles = 0
    last = None
    while True:
        last = cycle(args)
        cycles += 1
        print(json.dumps({
            "observed_at_kst": last["observed_at_kst"],
            "audit_pack": args.audit_pack,
            "cycle": cycles,
            "evaluated": last["summary"]["evaluated"],
            "pre_live_review_eligible": last["summary"]["pre_live_review_eligible"],
            "best_name": last["summary"].get("best_name"),
            "best_status": last["summary"].get("best_status"),
            "order_sent": False,
            "live_order_allowed": False,
            "out": args.out,
        }, ensure_ascii=False, default=str))
        if args.max_cycles > 0 and cycles >= args.max_cycles:
            break
        time.sleep(max(60, args.interval_seconds))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
