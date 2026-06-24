#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path


def write_dynamic_config(base_path: str, out_path: str, costs_path: str) -> float:
    base = Path(base_path).read_text()
    costs = json.loads(Path(costs_path).read_text()) if Path(costs_path).exists() else {}
    slip = float(costs.get('portfolio_worst_one_way_slippage_pct') or 0.001)
    text = re.sub(r'(buy_slippage_pct:\s*)[0-9.]+', rf'\g<1>{slip}', base)
    text = re.sub(r'(sell_slippage_pct:\s*)[0-9.]+', rf'\g<1>{slip}', text)
    Path(out_path).write_text(text)
    return slip


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--base-config', default='config.example.yaml')
    ap.add_argument('--out-config', default='data/config.dynamic_slippage.yaml')
    ap.add_argument('--costs', default='data/dynamic_execution_costs.json')
    ap.add_argument('--out-dir', default='data/grid_dynamic_slippage_latest')
    ap.add_argument('--capital', type=int, default=10000)
    ap.add_argument('--windows', default='40,60')
    ap.add_argument('--horizons', default='1,3,5')
    ap.add_argument('--limit', type=int, default=0)
    ap.add_argument('--isolated-slots', action='store_true')
    args = ap.parse_args()
    slip = write_dynamic_config(args.base_config, args.out_config, args.costs)
    cmd = [
        'python3', 'scripts/pair_grid_runner.py',
        '--config', args.out_config,
        '--capital', str(args.capital),
        '--windows', args.windows,
        '--horizons', args.horizons,
        '--out-dir', args.out_dir,
    ]
    if args.limit:
        cmd.extend(['--limit', str(args.limit)])
    if args.isolated_slots:
        cmd.append('--isolated-slots')
    subprocess.run(cmd, check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=900)
    summary = json.loads((Path(args.out_dir) / 'summary.json').read_text())
    report = {'dynamic_slippage_pct': slip, 'out_dir': args.out_dir, 'top': summary.get('top', [])[:10]}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
