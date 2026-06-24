#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


def run_grid(out_dir: Path, *, windows: str, horizons: str, max_bars: int, exclude_last_bars: int, isolated_slots: bool) -> dict:
    cmd = [
        'python3', 'scripts/pair_grid_runner.py',
        '--windows', windows,
        '--horizons', horizons,
        '--max-bars', str(max_bars),
        '--exclude-last-bars', str(exclude_last_bars),
        '--out-dir', str(out_dir),
    ]
    if isolated_slots:
        cmd.append('--isolated-slots')
    subprocess.run(cmd, check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=900)
    return json.loads((out_dir / 'summary.json').read_text())


def key(row: dict) -> tuple:
    return (row['pair'], row['branch'], row['window'], row['horizon'], row.get('mode', 'shared_account'))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--out-dir', default='data/walk_forward_latest')
    ap.add_argument('--windows', default='40,60')
    ap.add_argument('--horizons', default='1,3,5')
    ap.add_argument('--train-bars', type=int, default=90)
    ap.add_argument('--validation-bars', type=int, default=90)
    ap.add_argument('--isolated-slots', action='store_true')
    args = ap.parse_args()

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    train = run_grid(out / 'train', windows=args.windows, horizons=args.horizons, max_bars=args.train_bars, exclude_last_bars=args.validation_bars, isolated_slots=args.isolated_slots)
    valid = run_grid(out / 'validation', windows=args.windows, horizons=args.horizons, max_bars=args.validation_bars, exclude_last_bars=0, isolated_slots=args.isolated_slots)

    train_rows = {key(r): r for r in train.get('all', []) if 'pnl' in r and r.get('branch') not in {'observation_first', 'ultra_conservative'}}
    valid_rows = {key(r): r for r in valid.get('all', []) if 'pnl' in r and r.get('branch') not in {'observation_first', 'ultra_conservative'}}
    stable = []
    for k, tr in train_rows.items():
        va = valid_rows.get(k)
        if not va:
            continue
        stable.append({
            'pair': tr['pair'],
            'branch': tr['branch'],
            'window': tr['window'],
            'horizon': tr['horizon'],
            'mode': tr.get('mode', 'isolated_slots' if args.isolated_slots else 'shared_account'),
            'train_pnl': tr['pnl'],
            'validation_pnl': va['pnl'],
            'train_equity': tr['equity'],
            'validation_equity': va['equity'],
            'train_db': tr['db'],
            'validation_db': va['db'],
            'stable_positive': tr['pnl'] > 0 and va['pnl'] > 0,
        })
    stable.sort(key=lambda r: (r['stable_positive'], r['validation_pnl'], r['train_pnl']), reverse=True)
    report = {
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'mode': 'isolated_slots' if args.isolated_slots else 'shared_account',
        'train_bars': args.train_bars,
        'validation_bars': args.validation_bars,
        'windows': [int(x) for x in args.windows.split(',') if x],
        'horizons': [int(x) for x in args.horizons.split(',') if x],
        'top': stable[:20],
        'all': stable,
    }
    (out / 'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
    lines = ['# Walk-forward summary', '', f"Generated: {report['generated_at']}", '', '| rank | stable | pair | mode | window | horizon | branch | train pnl | validation pnl |', '|---:|---|---|---|---:|---:|---|---:|---:|']
    for i, r in enumerate(report['top'], 1):
        lines.append(f"| {i} | {str(r['stable_positive']).lower()} | `{r['pair']}` | `{r['mode']}` | {r['window']} | {r['horizon']} | `{r['branch']}` | {r['train_pnl']:.2f} | {r['validation_pnl']:.2f} |")
    (out / 'summary.md').write_text('\n'.join(lines) + '\n')
    print(json.dumps({'out_dir': str(out), 'top': report['top'][:10]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
