#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from datetime import datetime, time as dtime
from pathlib import Path
from zoneinfo import ZoneInfo

KST = ZoneInfo('Asia/Seoul')


def parse_hhmm(value: str) -> dtime:
    hh, mm = value.split(':', 1)
    return dtime(int(hh), int(mm), tzinfo=KST)


def now_kst() -> datetime:
    return datetime.now(KST)


def run_cmd(cmd: list[str], *, timeout: int = 240) -> dict:
    env = os.environ.copy()
    env['PYTHONPATH'] = 'src'
    proc = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout, env=env)
    return {
        'cmd': cmd,
        'returncode': proc.returncode,
        'stdout_tail': proc.stdout[-4000:],
        'stderr_tail': proc.stderr[-4000:],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description='Paper-only/no-send market watch loop. Never sends live orders.')
    ap.add_argument('--start-at', default='08:55')
    ap.add_argument('--end-at', default='15:30')
    ap.add_argument('--interval-seconds', type=int, default=600)
    ap.add_argument('--candidate-limit', type=int, default=5)
    ap.add_argument('--log', default='logs/no_send_market_watch.jsonl')
    ap.add_argument('--once', action='store_true')
    args = ap.parse_args()

    Path(args.log).parent.mkdir(parents=True, exist_ok=True)
    start_time = parse_hhmm(args.start_at)
    end_time = parse_hhmm(args.end_at)

    while True:
        current = now_kst()
        if current.timetz() < start_time and not args.once:
            time.sleep(min(60, max(1, int((datetime.combine(current.date(), start_time, tzinfo=KST) - current).total_seconds()))))
            continue
        if current.timetz() > end_time and not args.once:
            break

        row = {
            'observed_at_kst': current.isoformat(),
            'mode': 'paper_only_no_send',
            'live_order_allowed': False,
            'steps': [],
        }
        commands = [
            ['python3', 'scripts/spread_guard_candidates.py', '--path', 'data/live_paper_candidates.json', '--candidate-limit', str(args.candidate_limit), '--max-spread-bps', '30', '--market-impact-levels', '5', '--max-impact-bps', '30', '--enforce-stale'],
            ['python3', 'scripts/paper_observe_candidates.py', '--candidates', 'data/live_paper_candidates.json', '--limit', str(args.candidate_limit)],
            ['python3', 'scripts/observation_guard_candidates.py', '--candidates', 'data/live_paper_candidates.json', '--min-observations', '3'],
            ['python3', 'scripts/pre_live_order_checklist.py', '--path', 'data/live_paper_candidates.json', '--candidate-index', '0', '--require-spread-ok', '--require-observation-ok', '--require-stress-ok', '--require-edge-ok', '--ack', 'I_UNDERSTAND_THIS_DOES_NOT_SEND_ORDERS'],
        ]
        for cmd in commands:
            try:
                row['steps'].append(run_cmd(cmd))
            except Exception as exc:
                row['steps'].append({'cmd': cmd, 'returncode': None, 'error': str(exc)[:1000]})
        with open(args.log, 'a') as f:
            f.write(json.dumps(row, ensure_ascii=False) + '\n')
        print(json.dumps({'observed_at_kst': row['observed_at_kst'], 'step_returncodes': [s.get('returncode') for s in row['steps']], 'log': args.log}, ensure_ascii=False))
        if args.once:
            break
        time.sleep(max(60, args.interval_seconds))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
