#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from statistics import mean, median
from typing import Callable


def f(row: dict, key: str) -> float | None:
    value = row.get(key, '')
    if value in ('', None):
        return None
    try:
        return float(value)
    except Exception:
        return None


def load_rows(path: str) -> list[dict]:
    with open(path, newline='') as fp:
        rows = list(csv.DictReader(fp))
    rows.sort(key=lambda r: (r.get('timestamp', ''), r.get('symbol', '')))
    return rows


def trade_stats(rows: list[dict]) -> dict:
    vals = [f(r, 'net_return_after_cost') for r in rows]
    vals = [v for v in vals if v is not None]
    if not vals:
        return {
            'signals': 0,
            'avg_net_return_after_cost': None,
            'median_net_return_after_cost': None,
            'win_rate_after_cost': None,
            'stop_loss_rate': None,
            'mean_reversion_exit_rate': None,
            'horizon_exit_rate': None,
        }
    n = len(vals)
    return {
        'signals': n,
        'avg_net_return_after_cost': mean(vals),
        'median_net_return_after_cost': median(vals),
        'win_rate_after_cost': sum(1 for v in vals if v > 0) / n,
        'stop_loss_rate': sum(1 for r in rows if r.get('exit_reason') == 'stop_loss') / n,
        'mean_reversion_exit_rate': sum(1 for r in rows if r.get('exit_reason') == 'mean_reversion_exit_next_open') / n,
        'horizon_exit_rate': sum(1 for r in rows if r.get('exit_reason') == 'horizon_close') / n,
    }


def split_train_locked(rows: list[dict], train_fraction: float) -> tuple[list[dict], list[dict]]:
    n = int(len(rows) * train_fraction)
    return rows[:n], rows[n:]


def quantile_edges(values: list[float], buckets: int) -> list[float]:
    if not values:
        return []
    xs = sorted(values)
    edges = []
    for i in range(1, buckets):
        idx = min(len(xs) - 1, max(0, int(len(xs) * i / buckets)))
        edges.append(xs[idx])
    return edges


def bucket_label(value: float, edges: list[float]) -> str:
    lo = '-inf'
    for edge in edges:
        if value <= edge:
            return f'{lo}..{edge:.6g}'
        lo = f'{edge:.6g}'
    return f'{lo}..inf'


def bucket_stats(rows: list[dict], feature: str, buckets: int = 5) -> list[dict]:
    vals = [f(r, feature) for r in rows]
    vals = [v for v in vals if v is not None]
    edges = quantile_edges(vals, buckets)
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        value = f(row, feature)
        if value is None:
            label = 'missing'
        else:
            label = bucket_label(value, edges)
        grouped.setdefault(label, []).append(row)
    out = []
    for label, items in grouped.items():
        st = trade_stats(items)
        st.update({'feature': feature, 'bucket': label, 'share': len(items) / len(rows) if rows else 0})
        out.append(st)
    return sorted(out, key=lambda x: x['bucket'])


def evaluate_rule(rows: list[dict], name: str, fn: Callable[[dict], bool], train_fraction: float) -> dict:
    kept = [r for r in rows if fn(r)]
    removed = [r for r in rows if not fn(r)]
    train, locked = split_train_locked(kept, train_fraction)
    removed_train, removed_locked = split_train_locked(removed, train_fraction)
    return {
        'rule': name,
        'kept_share': len(kept) / len(rows) if rows else 0,
        'kept': trade_stats(kept),
        'kept_train': trade_stats(train),
        'kept_locked': trade_stats(locked),
        'removed': trade_stats(removed),
        'removed_train': trade_stats(removed_train),
        'removed_locked': trade_stats(removed_locked),
        'post_hoc_only': True,
    }


def val_ge(key: str, threshold: float) -> Callable[[dict], bool]:
    return lambda r: (f(r, key) is not None) and f(r, key) >= threshold


def val_le(key: str, threshold: float) -> Callable[[dict], bool]:
    return lambda r: (f(r, key) is not None) and f(r, key) <= threshold


def main() -> int:
    ap = argparse.ArgumentParser(description='Post-hoc diagnostics for RSI+Bollinger mean-reversion signals. Research-only.')
    ap.add_argument('--signals', default='data/rsi_bbands_mean_reversion_h20_v1_signals.csv')
    ap.add_argument('--out', default='data/rsi_bbands_mean_reversion_h20_v1_trade_diagnostics.json')
    ap.add_argument('--train-fraction', type=float, default=0.70)
    args = ap.parse_args()

    rows = load_rows(args.signals)
    train, locked = split_train_locked(rows, args.train_fraction)
    features = [
        'signal_close',
        'rsi',
        'bb_z',
        'volume_multiple',
        'prior_5d_return',
        'prior_20d_return',
        'prior_60d_return',
        'avg_trade_value_20d',
        'signal_trade_value',
        'range_20d_pct',
        'gap_from_signal_close',
        'kosdaq_20d_return',
        'kosdaq_20d_ann_vol',
    ]
    buckets = {feature: bucket_stats(rows, feature) for feature in features}

    rules: list[tuple[str, Callable[[dict], bool]]] = []
    for t in [-0.25, -0.20, -0.15, -0.10]:
        rules.append((f'prior_20d_return >= {t}', val_ge('prior_20d_return', t)))
    for t in [-0.20, -0.15, -0.10, -0.05]:
        rules.append((f'prior_5d_return >= {t}', val_ge('prior_5d_return', t)))
    for t in [0.35, 0.50, 0.75, 1.00]:
        rules.append((f'range_20d_pct <= {t}', val_le('range_20d_pct', t)))
    for t in [-0.08, -0.05, -0.03, 0.00]:
        rules.append((f'kosdaq_20d_return >= {t}', val_ge('kosdaq_20d_return', t)))
    for t in [0.30, 0.40, 0.50, 0.60]:
        rules.append((f'kosdaq_20d_ann_vol <= {t}', val_le('kosdaq_20d_ann_vol', t)))
    for t in [1.5, 2.0, 2.5]:
        rules.append((f'volume_multiple <= {t}', val_le('volume_multiple', t)))
    for t in [-0.05, -0.03, 0.0]:
        rules.append((f'gap_from_signal_close >= {t}', val_ge('gap_from_signal_close', t)))
    for t in [2_000, 5_000, 10_000]:
        rules.append((f'signal_close >= {t}', val_ge('signal_close', t)))
    for t in [500_000_000, 1_000_000_000, 2_000_000_000, 5_000_000_000]:
        rules.append((f'avg_trade_value_20d >= {t}', val_ge('avg_trade_value_20d', t)))
    for t in [-3.0, -2.75, -2.5]:
        rules.append((f'bb_z >= {t}', val_ge('bb_z', t)))

    # A few interpretable composites, still post-hoc only.
    rules.extend([
        (
            'falling_knife_guard: prior_20d>=-0.20 and range_20d<=0.75',
            lambda r: (f(r, 'prior_20d_return') is not None and f(r, 'prior_20d_return') >= -0.20 and f(r, 'range_20d_pct') is not None and f(r, 'range_20d_pct') <= 0.75),
        ),
        (
            'liquid_not_extreme: avg_trade_value>=1B and bb_z>=-3 and volume_multiple<=2.5',
            lambda r: (f(r, 'avg_trade_value_20d') is not None and f(r, 'avg_trade_value_20d') >= 1_000_000_000 and f(r, 'bb_z') is not None and f(r, 'bb_z') >= -3 and f(r, 'volume_multiple') is not None and f(r, 'volume_multiple') <= 2.5),
        ),
        (
            'market_soft_guard: kosdaq20>=-0.08 and kosdaq_vol<=0.50',
            lambda r: (f(r, 'kosdaq_20d_return') is not None and f(r, 'kosdaq_20d_return') >= -0.08 and f(r, 'kosdaq_20d_ann_vol') is not None and f(r, 'kosdaq_20d_ann_vol') <= 0.50),
        ),
        (
            'combined_soft: prior20>=-0.20 range<=0.75 kosdaq20>=-0.08 vol<=0.50',
            lambda r: (
                f(r, 'prior_20d_return') is not None and f(r, 'prior_20d_return') >= -0.20
                and f(r, 'range_20d_pct') is not None and f(r, 'range_20d_pct') <= 0.75
                and f(r, 'kosdaq_20d_return') is not None and f(r, 'kosdaq_20d_return') >= -0.08
                and f(r, 'kosdaq_20d_ann_vol') is not None and f(r, 'kosdaq_20d_ann_vol') <= 0.50
            ),
        ),
    ])

    rule_results = [evaluate_rule(rows, name, fn, args.train_fraction) for name, fn in rules]
    viable = [r for r in rule_results if r['kept_locked']['signals'] >= 300 and r['kept']['signals'] >= 1000]
    viable.sort(
        key=lambda r: (
            r['kept_locked']['avg_net_return_after_cost'] if r['kept_locked']['avg_net_return_after_cost'] is not None else -999,
            r['kept_locked']['win_rate_after_cost'] if r['kept_locked']['win_rate_after_cost'] is not None else -999,
        ),
        reverse=True,
    )

    report = {
        'mode': 'post_hoc_diagnostic_only_no_send',
        'source': args.signals,
        'all': trade_stats(rows),
        'train': trade_stats(train),
        'locked': trade_stats(locked),
        'bucket_stats': buckets,
        'rule_results': rule_results,
        'top_viable_rules_by_locked_avg': viable[:20],
        'warnings': [
            'Rules were inspected after seeing H20_V1 results; they are V3 design clues only.',
            'Do not promote a rule from this report without frozen future/paper holdout.',
        ],
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps({
        'out': args.out,
        'all': report['all'],
        'locked': report['locked'],
        'top_viable_rules_by_locked_avg': report['top_viable_rules_by_locked_avg'][:10],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
