#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
from decimal import Decimal
from pathlib import Path
from statistics import mean

from volume_shock_hypothesis_audit import (
    benchmark_comparison,
    cached_candles_readonly,
    d,
    distribution_metrics,
    equal_weight_by_symbol_stats,
    evaluate_aggregate,
    load_symbols,
    split_train_test,
    stats,
    test_symbol as volume_test_symbol,
)


def to_short_proxy(signals: list[dict], *, cost_pct: Decimal) -> list[dict]:
    """Transform long-side volume-shock signals into a research-only short/avoid proxy.

    This is not a live short strategy. It answers: after this signal, did the next-horizon
    move tend to be negative enough that avoiding/penalizing the name would have helped?
    """
    out: list[dict] = []
    for s in signals:
        entry = d(s.get('entry_price'))
        exit_p = d(s.get('exit_price'))
        if entry <= 0:
            continue
        long_raw = (exit_p - entry) / entry
        short_proxy_net = (-long_raw) - cost_pct
        out.append({
            **s,
            'long_raw_return_before_cost': float(long_raw),
            'original_long_net_return_after_cost': s.get('net_return_after_cost'),
            'net_return_after_cost': float(short_proxy_net),
            'abs_net_return_after_cost': float(abs(long_raw) - cost_pct),
            'hypothesis_role': 'post_hoc_short_proxy_not_live_tradable',
            'safe_live_use_first': 'avoid_or_penalize_recent_volume_shock_names',
        })
    return out


def run(args) -> dict:
    symbols = load_symbols(args)
    rows = []
    long_signals: list[dict] = []
    long_baseline_signals: list[dict] = []
    for sym in symbols:
        row = volume_test_symbol(
            cached_candles_readonly(args.source_db, sym),
            symbol=sym,
            vol_mult=Decimal(args.vol_mult),
            lookback=args.lookback,
            horizon=args.horizon,
            cost_pct=Decimal(args.cost_pct),
            strategy=args.long_entry_strategy,
            market_filter=args.market_filter,
        )
        sigs = row.pop('_signals')
        bases = row.pop('_baseline_signals')
        long_signals.extend(sigs)
        long_baseline_signals.extend(bases)
        rows.append(row)

    cost_pct = Decimal(args.cost_pct)
    reversal_signals = to_short_proxy(long_signals, cost_pct=cost_pct)
    reversal_baseline = to_short_proxy(long_baseline_signals, cost_pct=cost_pct)

    aggregate = evaluate_aggregate(
        reversal_signals,
        min_total_signals=args.min_total_signals,
        min_test_signals=args.min_test_signals,
        min_win_rate=Decimal(args.min_win_rate),
        min_avg_net_return=Decimal(args.min_avg_net_return),
        train_fraction=Decimal(args.train_fraction),
        min_signal_symbols=args.min_signal_symbols,
        max_symbol_signal_share=Decimal(args.max_symbol_signal_share),
        max_month_signal_share=Decimal(args.max_month_signal_share),
    )
    benchmarks = benchmark_comparison(reversal_signals, reversal_baseline, train_fraction=Decimal(args.train_fraction))
    if args.require_baseline_outperformance:
        delta = benchmarks['locked_test'].get('avg_delta_vs_baseline')
        if delta is None or delta <= 0:
            aggregate['blockers'].append('locked_test_not_above_reversal_positive_candle_baseline')
            aggregate['edge_ok'] = False
    if args.require_locked_test_median_nonnegative:
        med = aggregate['locked_test'].get('median_net_return_after_cost')
        if med is None or med < 0:
            aggregate['blockers'].append('locked_test_median_net_return_negative')
            aggregate['edge_ok'] = False
    if args.require_equal_weight_positive:
        ew = aggregate['equal_weight_by_symbol']['locked_test'].get('avg_symbol_mean_net_return_after_cost')
        if ew is None or ew <= 0:
            aggregate['blockers'].append('locked_test_equal_weight_symbol_mean_not_positive')
            aggregate['edge_ok'] = False

    long_vals = [s.get('net_return_after_cost', 0.0) for s in long_signals]
    _, long_test = split_train_test(long_signals, Decimal(args.train_fraction))
    long_test_vals = [s.get('net_return_after_cost', 0.0) for s in long_test]
    report = {
        'mode': 'research_only_no_send',
        'live_order_allowed': False,
        'hypothesis_status': 'post_hoc_exploratory_requires_future_holdout',
        'warning': 'Derived from a failed locked-test result; passing this report cannot approve live trading.',
        'safe_first_use': 'avoid_or_penalize_recent_volume_shock_names; not live short selling',
        'config': {
            'source_db': args.source_db,
            'symbols': args.symbols,
            'symbols_file': args.symbols_file,
            'long_entry_strategy': args.long_entry_strategy,
            'vol_mult': args.vol_mult,
            'lookback': args.lookback,
            'horizon': args.horizon,
            'cost_pct': args.cost_pct,
            'train_fraction': args.train_fraction,
        },
        'summary': {
            'edge_ok': False,  # post-hoc hypotheses are never promotable from this dataset alone
            'post_hoc_proxy_edge_ok': aggregate['edge_ok'],
            'blockers': aggregate['blockers'] + ['future_holdout_required_for_any_promotion'],
            'aggregate': aggregate,
            'benchmarks': benchmarks,
            'distribution': distribution_metrics(reversal_signals),
            'equal_weight_by_symbol': {
                'all': equal_weight_by_symbol_stats(reversal_signals),
                'locked_test': equal_weight_by_symbol_stats(split_train_test(reversal_signals, Decimal(args.train_fraction))[1]),
            },
            'original_long_side': {
                'all': stats(long_vals),
                'locked_test': stats(long_test_vals),
            },
        },
        'rows': rows,
    }
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2))
    if args.symbols_dist_out:
        dist = distribution_metrics(reversal_signals)
        with open(args.symbols_dist_out, 'w', newline='') as f:
            w = csv.DictWriter(f, fieldnames=['symbol', 'signals', 'signal_share', 'avg_net_return_after_cost', 'win_rate_after_cost'])
            w.writeheader()
            for row in dist['top_symbols']:
                w.writerow(row)
    return report


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--source-db', default='data/edge_research_universe_long.sqlite3')
    ap.add_argument('--symbols', default='cached')
    ap.add_argument('--symbols-file', default='')
    ap.add_argument('--out', default='data/volume_shock_reversal_posthoc.json')
    ap.add_argument('--symbols-dist-out', default='data/volume_shock_reversal_posthoc_dist.csv')
    ap.add_argument('--long-entry-strategy', default='continuation', choices=['continuation', 'breakout'])
    ap.add_argument('--market-filter', action='store_true')
    ap.add_argument('--vol-mult', default='3')
    ap.add_argument('--lookback', type=int, default=20)
    ap.add_argument('--horizon', type=int, default=3)
    ap.add_argument('--cost-pct', default='0.006')
    ap.add_argument('--min-symbols', type=int, default=100)
    ap.add_argument('--min-total-signals', type=int, default=300)
    ap.add_argument('--min-test-signals', type=int, default=100)
    ap.add_argument('--min-signal-symbols', type=int, default=100)
    ap.add_argument('--max-symbol-signal-share', default='0.05')
    ap.add_argument('--max-month-signal-share', default='0.35')
    ap.add_argument('--require-baseline-outperformance', action='store_true')
    ap.add_argument('--require-locked-test-median-nonnegative', action='store_true')
    ap.add_argument('--require-equal-weight-positive', action='store_true')
    ap.add_argument('--min-win-rate', default='0.52')
    ap.add_argument('--min-avg-net-return', default='0')
    ap.add_argument('--train-fraction', default='0.70')
    args = ap.parse_args()
    report = run(args)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
