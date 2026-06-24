#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


def run_one(capital: int, out_dir: Path, *, windows: str, horizons: str, max_bars: int, limit: int, isolated: bool) -> dict:
    cap_dir = out_dir / f"capital_{capital}_{'isolated' if isolated else 'shared'}"
    cmd = [
        'python3', 'scripts/pair_grid_runner.py',
        '--capital', str(capital),
        '--windows', windows,
        '--horizons', horizons,
        '--max-bars', str(max_bars),
        '--out-dir', str(cap_dir),
    ]
    if limit:
        cmd.extend(['--limit', str(limit)])
    if isolated:
        cmd.append('--isolated-slots')
    subprocess.run(cmd, check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=900)
    return json.loads((cap_dir / 'summary.json').read_text())


def classify(capital_rows: dict[str, dict]) -> str:
    pnl = {int(k): (v.get('top') or [{}])[0].get('pnl') for k, v in capital_rows.items()}
    small = pnl.get(10000)
    large = pnl.get(1000000) or pnl.get(max(pnl) if pnl else 0)
    if small is not None and large is not None:
        if small > 0 and large > 0:
            return 'stable_across_small_and_large'
        if small <= 0 and large > 0:
            return 'research_only_capital_needed'
        if small > 0 and large <= 0:
            return 'microstructure_artifact_risk'
    return 'mixed_or_insufficient'


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--capitals', default='10000,30000,100000,1000000')
    ap.add_argument('--out-dir', default='data/multi_capital_latest')
    ap.add_argument('--windows', default='40,60')
    ap.add_argument('--horizons', default='1,3,5')
    ap.add_argument('--max-bars', type=int, default=120)
    ap.add_argument('--limit', type=int, default=0, help='debug: pair-grid combination limit per capital')
    ap.add_argument('--isolated-slots', action='store_true')
    args = ap.parse_args()
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    rows = {}
    for cap in [int(x) for x in args.capitals.split(',') if x.strip()]:
        rows[str(cap)] = run_one(cap, out, windows=args.windows, horizons=args.horizons, max_bars=args.max_bars, limit=args.limit, isolated=args.isolated_slots)
    report = {
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'capitals': [int(x) for x in rows],
        'mode': 'isolated_slots' if args.isolated_slots else 'shared_account',
        'classification': classify(rows),
        'top_by_capital': {k: (v.get('top') or [])[:5] for k, v in rows.items()},
    }
    (out / 'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
