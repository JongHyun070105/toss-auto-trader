#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
from decimal import Decimal
from pathlib import Path
from statistics import mean
from typing import Optional

from volume_shock_hypothesis_audit import (
    benchmark_comparison,
    cached_candles_readonly,
    distribution_metrics,
    d,
    equal_weight_by_symbol_stats,
    evaluate_aggregate,
    load_symbols,
    split_train_test,
    stats,
)


def sma(vals: list[Decimal]) -> Decimal:
    return sum(vals) / Decimal(len(vals)) if vals else Decimal('0')


def rsi_at(candles: list[dict], i: int, period: int) -> Optional[Decimal]:
    if i < period:
        return None
    gains = Decimal('0')
    losses = Decimal('0')
    for j in range(i - period + 1, i + 1):
        change = d(candles[j]['close_price']) - d(candles[j - 1]['close_price'])
        if change > 0:
            gains += change
        else:
            losses += -change
    avg_gain = gains / Decimal(period)
    avg_loss = losses / Decimal(period)
    if avg_loss == 0:
        return Decimal('100')
    rs = avg_gain / avg_loss
    return Decimal('100') - (Decimal('100') / (Decimal('1') + rs))


def pullback_signal(candles: list[dict], i: int, *, fast: int, slow: int, pullback_days: int, touch_pct: Decimal, max_below_sma: Decimal, rsi_period: int, rsi_min: Decimal, rsi_max: Decimal) -> tuple[bool, dict]:
    fast_vals = [d(x['close_price']) for x in candles[i - fast + 1:i + 1]]
    slow_vals = [d(x['close_price']) for x in candles[i - slow + 1:i + 1]]
    fast_sma = sma(fast_vals)
    slow_sma = sma(slow_vals)
    close_p = d(candles[i]['close_price'])
    low_p = d(candles[i]['low_price'])
    down_days = 0
    for j in range(i - pullback_days + 1, i + 1):
        if d(candles[j]['close_price']) < d(candles[j - 1]['close_price']):
            down_days += 1
    rsi = rsi_at(candles, i, rsi_period)
    checks = {
        'sma_fast': float(fast_sma),
        'sma_slow': float(slow_sma),
        'down_days': down_days,
        'rsi': float(rsi) if rsi is not None else None,
        'trend_ok': fast_sma > slow_sma and close_p > slow_sma,
        'pullback_days_ok': down_days >= 2,
        'touch_ok': low_p <= fast_sma * (Decimal('1') + touch_pct),
        'not_broken_ok': close_p >= fast_sma * (Decimal('1') - max_below_sma),
        'rsi_ok': rsi is not None and rsi_min <= rsi <= rsi_max,
    }
    ok = all(bool(checks[k]) for k in ['trend_ok', 'pullback_days_ok', 'touch_ok', 'not_broken_ok', 'rsi_ok'])
    return ok, checks


def signal_return(candles: list[dict], i: int, *, horizon: int, cost_pct: Decimal) -> tuple[float, float, Decimal, Decimal]:
    entry_p = d(candles[i + 1]['open_price'])
    exit_p = d(candles[i + 1 + horizon]['close_price'])
    if entry_p <= 0:
        return float(-cost_pct), float(-cost_pct), entry_p, exit_p
    raw = (exit_p - entry_p) / entry_p
    return float(raw - cost_pct), float(abs(raw) - cost_pct), entry_p, exit_p


def test_symbol(candles: list[dict], *, symbol: str, fast: int, slow: int, pullback_days: int, horizon: int, touch_pct: Decimal, max_below_sma: Decimal, rsi_period: int, rsi_min: Decimal, rsi_max: Decimal, cost_pct: Decimal) -> dict:
    signals = []
    baseline_signals = []
    next_available_idx = 0
    baseline_next_available_idx = 0
    start = max(slow, rsi_period + 1, fast, pullback_days + 1)
    for i in range(start, len(candles) - 1 - horizon):
        ok, checks = pullback_signal(
            candles,
            i,
            fast=fast,
            slow=slow,
            pullback_days=pullback_days,
            touch_pct=touch_pct,
            max_below_sma=max_below_sma,
            rsi_period=rsi_period,
            rsi_min=rsi_min,
            rsi_max=rsi_max,
        )
        # Baseline: same trend + RSI filter, without pullback/touch requirements.
        if i >= baseline_next_available_idx and checks['trend_ok'] and checks['rsi_ok']:
            net, abs_net, entry_p, exit_p = signal_return(candles, i, horizon=horizon, cost_pct=cost_pct)
            baseline_signals.append({
                'symbol': symbol,
                'timestamp': candles[i]['timestamp'],
                'entry_timestamp': candles[i + 1]['timestamp'],
                'exit_timestamp': candles[i + 1 + horizon]['timestamp'],
                'entry_price': float(entry_p),
                'exit_price': float(exit_p),
                'net_return_after_cost': net,
                'abs_net_return_after_cost': abs_net,
                'baseline': 'trend_rsi_without_pullback',
            })
            baseline_next_available_idx = i + 1 + horizon
        if not ok or i < next_available_idx:
            continue
        net, abs_net, entry_p, exit_p = signal_return(candles, i, horizon=horizon, cost_pct=cost_pct)
        signals.append({
            'symbol': symbol,
            'timestamp': candles[i]['timestamp'],
            'entry_timestamp': candles[i + 1]['timestamp'],
            'exit_timestamp': candles[i + 1 + horizon]['timestamp'],
            'entry_price': float(entry_p),
            'exit_price': float(exit_p),
            'net_return_after_cost': net,
            'abs_net_return_after_cost': abs_net,
            'checks': checks,
        })
        next_available_idx = i + 1 + horizon
    vals = [s['net_return_after_cost'] for s in signals]
    return {
        'symbol': symbol,
        'stats': {**stats(vals), 'avg_abs_return_after_cost': mean([s['abs_net_return_after_cost'] for s in signals]) if signals else None},
        'recent_signals': signals[-10:],
        '_signals': signals,
        '_baseline_signals': baseline_signals,
    }


def run(args) -> dict:
    symbols = load_symbols(args)
    rows = []
    all_signals = []
    baseline_signals = []
    for sym in symbols:
        row = test_symbol(
            cached_candles_readonly(args.source_db, sym),
            symbol=sym,
            fast=args.fast_sma,
            slow=args.slow_sma,
            pullback_days=args.pullback_days,
            horizon=args.horizon,
            touch_pct=Decimal(args.touch_pct),
            max_below_sma=Decimal(args.max_below_sma),
            rsi_period=args.rsi_period,
            rsi_min=Decimal(args.rsi_min),
            rsi_max=Decimal(args.rsi_max),
            cost_pct=Decimal(args.cost_pct),
        )
        all_signals.extend(row.pop('_signals'))
        baseline_signals.extend(row.pop('_baseline_signals'))
        rows.append(row)
    aggregate = evaluate_aggregate(
        all_signals,
        min_total_signals=args.min_total_signals,
        min_test_signals=args.min_test_signals,
        min_win_rate=Decimal(args.min_win_rate),
        min_avg_net_return=Decimal(args.min_avg_net_return),
        train_fraction=Decimal(args.train_fraction),
        min_signal_symbols=args.min_signal_symbols,
        max_symbol_signal_share=Decimal(args.max_symbol_signal_share),
        max_month_signal_share=Decimal(args.max_month_signal_share),
    )
    benchmarks = benchmark_comparison(all_signals, baseline_signals, train_fraction=Decimal(args.train_fraction))
    if args.require_baseline_outperformance:
        delta = benchmarks['locked_test'].get('avg_delta_vs_baseline')
        if delta is None or delta <= 0:
            aggregate['blockers'].append('locked_test_not_above_trend_rsi_baseline')
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
    universe_blockers = []
    if len(symbols) < args.min_symbols:
        universe_blockers.append('insufficient_universe_symbols')
    return {
        'hypothesis': 'pullback_after_trend_v1',
        'mode': 'research_only_no_send',
        'definition': f'SMA{args.fast_sma}>SMA{args.slow_sma}; close>SMA{args.slow_sma}; >=2 down closes over {args.pullback_days}d; low within +{args.touch_pct} of SMA{args.fast_sma}; close not below SMA{args.fast_sma} by more than {args.max_below_sma}; RSI{args.rsi_period} {args.rsi_min}~{args.rsi_max}; next-open entry; horizon={args.horizon}; cost={args.cost_pct}',
        'universe': {'source_db': args.source_db, 'symbol_count': len(symbols), 'min_symbols': args.min_symbols, 'blockers': universe_blockers},
        'summary': {
            'edge_ok': aggregate['edge_ok'] and not universe_blockers,
            'blockers': universe_blockers + aggregate['blockers'],
            'aggregate': aggregate,
            'benchmarks': benchmarks,
            'distribution': distribution_metrics(all_signals),
            'equal_weight_by_symbol': {
                'all': equal_weight_by_symbol_stats(all_signals),
                'locked_test': equal_weight_by_symbol_stats(split_train_test(all_signals, Decimal(args.train_fraction))[1]),
            },
        },
        'rows': rows,
        '_signals': all_signals,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description='Research-only pullback-after-trend hypothesis audit.')
    ap.add_argument('--source-db', default='data/edge_research_universe.sqlite3')
    ap.add_argument('--symbols', default='cached')
    ap.add_argument('--symbols-file', default='')
    ap.add_argument('--out', default='data/pullback_after_trend_latest.json')
    ap.add_argument('--symbols-dist-out', default='data/pullback_after_trend_symbol_distribution.csv')
    ap.add_argument('--signals-out', default='', help='Optional CSV path for every generated signal with timestamps')
    ap.add_argument('--fast-sma', type=int, default=20)
    ap.add_argument('--slow-sma', type=int, default=60)
    ap.add_argument('--pullback-days', type=int, default=3)
    ap.add_argument('--horizon', type=int, default=5)
    ap.add_argument('--touch-pct', default='0.01')
    ap.add_argument('--max-below-sma', default='0.03')
    ap.add_argument('--rsi-period', type=int, default=14)
    ap.add_argument('--rsi-min', default='35')
    ap.add_argument('--rsi-max', default='60')
    ap.add_argument('--cost-pct', default='0.006')
    ap.add_argument('--train-fraction', default='0.70')
    ap.add_argument('--min-symbols', type=int, default=100)
    ap.add_argument('--min-signal-symbols', type=int, default=80)
    ap.add_argument('--min-total-signals', type=int, default=200)
    ap.add_argument('--min-test-signals', type=int, default=60)
    ap.add_argument('--max-symbol-signal-share', default='0.05')
    ap.add_argument('--max-month-signal-share', default='0.35')
    ap.add_argument('--min-win-rate', default='0.52')
    ap.add_argument('--min-avg-net-return', default='0')
    ap.add_argument('--require-baseline-outperformance', action='store_true')
    ap.add_argument('--require-locked-test-median-nonnegative', action='store_true')
    ap.add_argument('--require-equal-weight-positive', action='store_true')
    args = ap.parse_args()

    report = run(args)
    export_signals = report.pop('_signals', [])
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    with Path(args.symbols_dist_out).open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=['symbol', 'signals', 'win_rate', 'avg_net_return', 'median_net_return', 'avg_abs_return'])
        writer.writeheader()
        for r in report['rows']:
            st = r['stats']
            writer.writerow({
                'symbol': r['symbol'],
                'signals': st['signals'],
                'win_rate': st['win_rate_after_cost'] or 0.0,
                'avg_net_return': st['avg_net_return_after_cost'] or 0.0,
                'median_net_return': st['median_net_return_after_cost'] or 0.0,
                'avg_abs_return': st.get('avg_abs_return_after_cost') or 0.0,
            })
    if args.signals_out:
        signals_path = Path(args.signals_out)
        signals_path.parent.mkdir(parents=True, exist_ok=True)
        keys = []
        for s in export_signals:
            for key in s:
                if key not in keys:
                    keys.append(key)
        with signals_path.open('w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=keys)
            writer.writeheader()
            writer.writerows(export_signals)
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
