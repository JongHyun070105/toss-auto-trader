#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import sqlite3
from collections import Counter, defaultdict
from decimal import Decimal
from pathlib import Path
from statistics import mean, median
from typing import Optional


def cached_symbols(db_path: str) -> list[str]:
    if not Path(db_path).exists():
        return []
    con = sqlite3.connect(f'file:{db_path}?mode=ro', uri=True)
    try:
        rows = con.execute("SELECT DISTINCT symbol FROM candle_cache WHERE interval='1d' ORDER BY symbol").fetchall()
    finally:
        con.close()
    return [str(r[0]) for r in rows]


def cached_candles_readonly(db_path: str, symbol: str) -> list[dict]:
    if not Path(db_path).exists():
        return []
    con = sqlite3.connect(f'file:{db_path}?mode=ro', uri=True)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(
            "SELECT timestamp, open_price, high_price, low_price, close_price, volume FROM candle_cache WHERE symbol=? AND interval='1d' ORDER BY timestamp ASC",
            (symbol,),
        ).fetchall()
    finally:
        con.close()
    return [dict(r) for r in rows]


def load_symbols(args) -> list[str]:
    if args.symbols_file:
        p = Path(args.symbols_file)
        if p.exists():
            return [line.strip() for line in p.read_text().splitlines() if line.strip() and not line.strip().startswith('#')]
    if args.symbols == 'cached':
        return cached_symbols(args.source_db)
    return [x.strip() for x in args.symbols.split(',') if x.strip()]


def d(x) -> Decimal:
    return Decimal(str(x or '0'))


def stats(vals: list[float]) -> dict:
    return {
        'signals': len(vals),
        'avg_net_return_after_cost': mean(vals) if vals else None,
        'median_net_return_after_cost': median(vals) if vals else None,
        'win_rate_after_cost': (sum(1 for v in vals if v > 0) / len(vals)) if vals else None,
    }


def signal_month(signal: dict) -> str:
    return str(signal.get('timestamp', 'unknown'))[:7]


def distribution_metrics(signals: list[dict]) -> dict:
    total = len(signals)
    if not total:
        return {
            'symbols_with_signals': 0,
            'top_symbol_signal_share': 0.0,
            'top_month_signal_share': 0.0,
            'top_symbols': [],
            'monthly': [],
        }

    by_symbol: dict[str, list[float]] = defaultdict(list)
    by_month: dict[str, list[float]] = defaultdict(list)
    for s in signals:
        by_symbol[str(s.get('symbol', ''))].append(float(s.get('net_return_after_cost', 0.0)))
        by_month[signal_month(s)].append(float(s.get('net_return_after_cost', 0.0)))

    symbol_counts = Counter({k: len(v) for k, v in by_symbol.items()})
    month_counts = Counter({k: len(v) for k, v in by_month.items()})
    top_symbols = []
    for sym, count in symbol_counts.most_common(10):
        vals = by_symbol[sym]
        top_symbols.append({
            'symbol': sym,
            'signals': count,
            'signal_share': count / total,
            'avg_net_return_after_cost': mean(vals) if vals else None,
            'win_rate_after_cost': (sum(1 for v in vals if v > 0) / len(vals)) if vals else None,
        })
    monthly = []
    for month in sorted(by_month):
        vals = by_month[month]
        monthly.append({
            'month': month,
            **stats(vals),
            'signal_share': len(vals) / total,
        })
    return {
        'symbols_with_signals': len(by_symbol),
        'top_symbol_signal_share': (max(symbol_counts.values()) / total) if symbol_counts else 0.0,
        'top_month_signal_share': (max(month_counts.values()) / total) if month_counts else 0.0,
        'top_symbols': top_symbols,
        'monthly': monthly,
    }


def equal_weight_by_symbol_stats(signals: list[dict]) -> dict:
    by_symbol: dict[str, list[float]] = defaultdict(list)
    for s in signals:
        by_symbol[str(s.get('symbol', ''))].append(float(s.get('net_return_after_cost', 0.0)))
    symbol_means = [mean(vals) for vals in by_symbol.values() if vals]
    return {
        'symbols': len(symbol_means),
        'avg_symbol_mean_net_return_after_cost': mean(symbol_means) if symbol_means else None,
        'median_symbol_mean_net_return_after_cost': median(symbol_means) if symbol_means else None,
        'positive_symbol_rate': (sum(1 for v in symbol_means if v > 0) / len(symbol_means)) if symbol_means else None,
    }


def signal_return(candles: list[dict], i: int, *, horizon: int, cost_pct: Decimal, strategy: str) -> Optional[tuple[float, float, Decimal, Decimal, str]]:
    if strategy == 'breakout':
        next_day = candles[i + 1]
        trigger_p = d(candles[i]['high_price'])
        next_open = d(next_day['open_price'])
        next_high = d(next_day['high_price'])
        if trigger_p <= 0 or next_high < trigger_p:
            return None
        if next_open >= trigger_p:
            # Stop/trigger orders cannot fill at yesterday's trigger after a gap-up open.
            # The realistic fill is next open or worse; use next open as the conservative daily-candle proxy.
            entry_p = next_open
            entry_model = 'gap_fill_next_open'
        else:
            entry_p = trigger_p
            entry_model = 'intraday_breakout_trigger_fill'
        exit_p = d(candles[i + 1 + horizon]['close_price'])
    else:
        entry_p = d(candles[i + 1]['open_price'])
        exit_p = d(candles[i + 1 + horizon]['close_price'])
        entry_model = 'next_open'
    if entry_p > 0:
        raw = (exit_p - entry_p) / entry_p
        net_return = float(raw - cost_pct)
        abs_net_return = float(abs(raw) - cost_pct)
    else:
        net_return = float(-cost_pct)
        abs_net_return = float(-cost_pct)
    return net_return, abs_net_return, entry_p, exit_p, entry_model


def test_symbol(candles: list[dict], *, symbol: str, vol_mult: Decimal, lookback: int, horizon: int, cost_pct: Decimal, strategy: str = 'continuation', market_filter: bool = False) -> dict:
    signals = []
    baseline_signals = []
    next_available_idx = 0
    baseline_next_available_idx = 0
    # 익일 시가 진입이므로, i+1일에 진입하고 i+1+horizon일에 청산한다.
    # 따라서 i+1+horizon < len(candles) 여야 하므로 i < len(candles) - 1 - horizon
    for i in range(lookback, len(candles) - 1 - horizon):
        if i < next_available_idx:
            continue
        c = candles[i]
        prev = candles[i - lookback:i]
        avg_vol = sum(d(x['volume']) for x in prev) / Decimal(lookback)
        if avg_vol <= 0:
            continue
        open_p, close_p = d(c['open_price']), d(c['close_price'])
        vol = d(c['volume'])
        
        positive_candle = close_p > open_p
        volume_shock = vol >= avg_vol * vol_mult

        # Positive-candle baseline: volume condition만 제거한 matched benchmark.
        # Edge 판정용이 아니라, "거래량 쇼크가 단순 양봉보다 나은가"를 보기 위한 대조군이다.
        if positive_candle and i >= baseline_next_available_idx:
            baseline_ret = signal_return(candles, i, horizon=horizon, cost_pct=cost_pct, strategy=strategy)
            if baseline_ret is not None:
                base_net, base_abs, base_entry, base_exit, base_entry_model = baseline_ret
                baseline_signals.append({
                    'symbol': symbol,
                    'timestamp': c['timestamp'],
                    'entry_timestamp': candles[i + 1]['timestamp'],
                    'exit_timestamp': candles[i + 1 + horizon]['timestamp'],
                    'volume_multiple': float(vol / avg_vol),
                    'entry_price': float(base_entry),
                    'exit_price': float(base_exit),
                    'entry_model': base_entry_model,
                    'net_return_after_cost': base_net,
                    'abs_net_return_after_cost': base_abs,
                    'baseline': 'positive_candle_without_volume_threshold',
                })
                baseline_next_available_idx = i + 1 + horizon

        # 신호 조건: 당일 양봉 + 당일 거래량이 평균의 vol_mult배 이상
        if positive_candle and volume_shock:
            # 1안: 시장 필터 (20 SMA 필터 - 신호 전일 종가 기준)
            if market_filter:
                sma_20 = sum(d(x['close_price']) for x in prev) / Decimal(lookback)
                prev_close = d(prev[-1]['close_price'])
                if prev_close <= sma_20:
                    continue
            
            # 2안: 진입 및 청산 결정
            ret = signal_return(candles, i, horizon=horizon, cost_pct=cost_pct, strategy=strategy)
            if ret is None:
                # 돌파 실패 (미체결) -> 신호 건너뜀
                continue
            net_return, abs_net_return, entry_p, exit_p, entry_model = ret
                
            signals.append({
                'symbol': symbol,
                'timestamp': c['timestamp'],
                'entry_timestamp': candles[i + 1]['timestamp'],
                'exit_timestamp': candles[i + 1 + horizon]['timestamp'],
                'volume_multiple': float(vol / avg_vol),
                'entry_price': float(entry_p),
                'exit_price': float(exit_p),
                'entry_model': entry_model,
                'net_return_after_cost': net_return,
                'abs_net_return_after_cost': abs_net_return,
            })
            # Cool-down 필터: 신호 진입 시 보유 기간 동안 추가 진입을 차단합니다.
            next_available_idx = i + 1 + horizon
            
    vals = [s['net_return_after_cost'] for s in signals]
    abs_vals = [s['abs_net_return_after_cost'] for s in signals]
    
    return {
        'symbol': symbol,
        'lookback': lookback,
        'horizon': horizon,
        'volume_multiple_threshold': str(vol_mult),
        'stats': {
            **stats(vals),
            'avg_abs_return_after_cost': mean(abs_vals) if abs_vals else None,
        },
        'diagnostic_edge_like': len(vals) >= 30 and bool(vals) and mean(vals) > 0 and (sum(1 for v in vals if v > 0) / len(vals)) >= 0.52,
        'recent_signals': signals[-10:],
        '_signals': signals,
        '_baseline_signals': baseline_signals,
    }


def split_train_test(signals: list[dict], train_fraction: Decimal) -> tuple[list[dict], list[dict]]:
    ordered = sorted(signals, key=lambda x: str(x.get('timestamp', '')))
    if not ordered:
        return [], []
    cut = int(len(ordered) * float(train_fraction))
    cut = min(max(cut, 1), len(ordered) - 1) if len(ordered) > 1 else len(ordered)
    return ordered[:cut], ordered[cut:]


def evaluate_aggregate(
    signals: list[dict],
    *,
    min_total_signals: int,
    min_test_signals: int,
    min_win_rate: Decimal,
    min_avg_net_return: Decimal,
    train_fraction: Decimal,
    min_signal_symbols: int = 0,
    max_symbol_signal_share: Decimal = Decimal('1'),
    max_month_signal_share: Decimal = Decimal('1'),
) -> dict:
    train, test = split_train_test(signals, train_fraction)
    train_vals = [s.get('net_return_after_cost', 0.0) for s in train]
    test_vals = [s.get('net_return_after_cost', 0.0) for s in test]
    all_vals = [s.get('net_return_after_cost', 0.0) for s in signals]
    
    train_abs_vals = [s.get('abs_net_return_after_cost', abs(s.get('net_return_after_cost', 0.0))) for s in train]
    test_abs_vals = [s.get('abs_net_return_after_cost', abs(s.get('net_return_after_cost', 0.0))) for s in test]
    all_abs_vals = [s.get('abs_net_return_after_cost', abs(s.get('net_return_after_cost', 0.0))) for s in signals]
    
    train_stats, test_stats, all_stats = stats(train_vals), stats(test_vals), stats(all_vals)
    train_stats['avg_abs_return_after_cost'] = mean(train_abs_vals) if train_abs_vals else None
    test_stats['avg_abs_return_after_cost'] = mean(test_abs_vals) if test_abs_vals else None
    all_stats['avg_abs_return_after_cost'] = mean(all_abs_vals) if all_abs_vals else None
    dist = distribution_metrics(signals)
    equal_weight = {
        'all': equal_weight_by_symbol_stats(signals),
        'train': equal_weight_by_symbol_stats(train),
        'locked_test': equal_weight_by_symbol_stats(test),
    }
    
    blockers = []
    if len(all_vals) < min_total_signals:
        blockers.append('insufficient_total_signals')
    if len(test_vals) < min_test_signals:
        blockers.append('insufficient_locked_test_signals')
    if dist['symbols_with_signals'] < min_signal_symbols:
        blockers.append('insufficient_signal_symbols')
    if Decimal(str(dist['top_symbol_signal_share'])) > max_symbol_signal_share:
        blockers.append('top_symbol_signal_share_too_high')
    if Decimal(str(dist['top_month_signal_share'])) > max_month_signal_share:
        blockers.append('top_month_signal_share_too_high')
    for label, st in [('train', train_stats), ('locked_test', test_stats)]:
        avg = st.get('avg_net_return_after_cost')
        win = st.get('win_rate_after_cost')
        if avg is None or Decimal(str(avg)) <= min_avg_net_return:
            blockers.append(f'{label}_avg_net_return_not_positive')
        if win is None or Decimal(str(win)) < min_win_rate:
            blockers.append(f'{label}_win_rate_below_threshold')
    return {
        'edge_ok': not blockers,
        'blockers': blockers,
        'all': all_stats,
        'train': train_stats,
        'locked_test': test_stats,
        'distribution': dist,
        'equal_weight_by_symbol': equal_weight,
        'train_fraction': str(train_fraction),
    }


def benchmark_comparison(signals: list[dict], baseline_signals: list[dict], *, train_fraction: Decimal) -> dict:
    _, signal_test = split_train_test(signals, train_fraction)
    _, baseline_test = split_train_test(baseline_signals, train_fraction)
    signal_test_vals = [s.get('net_return_after_cost', 0.0) for s in signal_test]
    baseline_test_vals = [s.get('net_return_after_cost', 0.0) for s in baseline_test]
    signal_all_vals = [s.get('net_return_after_cost', 0.0) for s in signals]
    baseline_all_vals = [s.get('net_return_after_cost', 0.0) for s in baseline_signals]
    signal_test_avg = mean(signal_test_vals) if signal_test_vals else None
    baseline_test_avg = mean(baseline_test_vals) if baseline_test_vals else None
    signal_all_avg = mean(signal_all_vals) if signal_all_vals else None
    baseline_all_avg = mean(baseline_all_vals) if baseline_all_vals else None
    return {
        'baseline': 'positive_candle_without_volume_threshold',
        'all': {
            'signal': stats(signal_all_vals),
            'baseline': stats(baseline_all_vals),
            'avg_delta_vs_baseline': (signal_all_avg - baseline_all_avg) if signal_all_avg is not None and baseline_all_avg is not None else None,
        },
        'locked_test': {
            'signal': stats(signal_test_vals),
            'baseline': stats(baseline_test_vals),
            'avg_delta_vs_baseline': (signal_test_avg - baseline_test_avg) if signal_test_avg is not None and baseline_test_avg is not None else None,
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--source-db', default='data/low_kr_backtest.sqlite3')
    ap.add_argument('--symbols', default='cached', help="'cached' uses all cached daily-candle symbols; or comma-separated symbols")
    ap.add_argument('--symbols-file', default='')
    ap.add_argument('--out', default='data/volume_shock_hypothesis_latest.json')
    ap.add_argument('--symbols-dist-out', default='data/volume_shock_symbol_distribution.csv')
    ap.add_argument('--signals-out', default='', help='Optional CSV path for every generated signal with timestamps')
    ap.add_argument('--strategy', default='continuation', choices=['continuation', 'breakout'], help="continuation (default) or breakout")
    ap.add_argument('--market-filter', action='store_true', help="Apply 20d SMA trend filter on signals")
    ap.add_argument('--vol-mult', default='3')
    ap.add_argument('--lookback', type=int, default=20)
    # Locked before validation. Do not choose the best of 1/3/5 after seeing results.
    ap.add_argument('--horizon', type=int, default=3)
    # Includes approximate buy/sell fees, tax, and rough slippage; research-only default.
    ap.add_argument('--cost-pct', default='0.006')
    ap.add_argument('--min-symbols', type=int, default=50)
    ap.add_argument('--min-total-signals', type=int, default=100)
    ap.add_argument('--min-test-signals', type=int, default=30)
    ap.add_argument('--min-signal-symbols', type=int, default=0, help='Minimum symbols that must actually generate signals')
    ap.add_argument('--max-symbol-signal-share', default='1', help='Block if one symbol contributes more than this signal share')
    ap.add_argument('--max-month-signal-share', default='1', help='Block if one calendar month contributes more than this signal share')
    ap.add_argument('--require-baseline-outperformance', action='store_true', help='Block if locked-test signal average is not above positive-candle baseline')
    ap.add_argument('--require-locked-test-median-nonnegative', action='store_true', help='Block if locked-test median net return is negative')
    ap.add_argument('--require-equal-weight-positive', action='store_true', help='Block if locked-test equal-weight-by-symbol mean is not positive')
    ap.add_argument('--min-win-rate', default='0.52')
    ap.add_argument('--min-avg-net-return', default='0')
    ap.add_argument('--train-fraction', default='0.70')
    args = ap.parse_args()

    symbols = load_symbols(args)
    rows = []
    all_signals = []
    baseline_signals = []
    for sym in symbols:
        row = test_symbol(
            cached_candles_readonly(args.source_db, sym),
            symbol=sym,
            vol_mult=Decimal(args.vol_mult),
            lookback=args.lookback,
            horizon=args.horizon,
            cost_pct=Decimal(args.cost_pct),
            strategy=args.strategy,
            market_filter=args.market_filter,
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
            aggregate['blockers'].append('locked_test_not_above_positive_candle_baseline')
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
    edge_ok = aggregate['edge_ok'] and not universe_blockers
    report = {
        'hypothesis': f'volume_shock_positive_candle_{args.strategy}',
        'definition': f'volume >= {args.vol_mult}x previous {args.lookback}d average and close > open; strategy={args.strategy}; market_filter={args.market_filter}; locked horizon={args.horizon}d; measure forward net return after cost; cool-down applied',
        'horizon_selection_policy': 'fixed_before_validation_no_best_of_multiple_horizons',
        'cost_pct': args.cost_pct,
        'universe': {
            'source_db': args.source_db,
            'symbol_count': len(symbols),
            'min_symbols': args.min_symbols,
            'blockers': universe_blockers,
        },
        'thresholds': {
            'min_total_signals': args.min_total_signals,
            'min_test_signals': args.min_test_signals,
            'min_signal_symbols': args.min_signal_symbols,
            'max_symbol_signal_share': args.max_symbol_signal_share,
            'max_month_signal_share': args.max_month_signal_share,
            'require_baseline_outperformance': args.require_baseline_outperformance,
            'require_locked_test_median_nonnegative': args.require_locked_test_median_nonnegative,
            'require_equal_weight_positive': args.require_equal_weight_positive,
            'min_win_rate': args.min_win_rate,
            'min_avg_net_return': args.min_avg_net_return,
        },
        'summary': {
            'edge_ok': edge_ok,
            'blockers': universe_blockers + aggregate['blockers'],
            'aggregate': aggregate,
            'benchmarks': benchmarks,
            'diagnostic_edge_like_symbols': [r['symbol'] for r in rows if r['diagnostic_edge_like']],
            'note': 'Symbol-level positives are diagnostics only. Global edge requires enough cross-sectional samples and a locked test split.',
        },
        'rows': rows,
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2))
    
    # Write symbol distribution CSV
    dist_path = Path(args.symbols_dist_out)
    dist_path.parent.mkdir(parents=True, exist_ok=True)
    with dist_path.open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=['symbol', 'signals', 'win_rate', 'avg_net_return', 'median_net_return', 'avg_abs_return'])
        writer.writeheader()
        for r in rows:
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
        for s in all_signals:
            for key in s:
                if key not in keys:
                    keys.append(key)
        with signals_path.open('w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=keys)
            writer.writeheader()
            writer.writerows(all_signals)
    print(f"종목별 승률 분포를 {dist_path}에 저장했습니다.")
    
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
