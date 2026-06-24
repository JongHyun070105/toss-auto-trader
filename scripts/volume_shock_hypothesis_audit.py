#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
from decimal import Decimal
from pathlib import Path
from statistics import mean


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
        'win_rate_after_cost': (sum(1 for v in vals if v > 0) / len(vals)) if vals else None,
    }


def test_symbol(candles: list[dict], *, symbol: str, vol_mult: Decimal, lookback: int, horizon: int, cost_pct: Decimal) -> dict:
    signals = []
    for i in range(lookback, len(candles) - horizon):
        c = candles[i]
        prev = candles[i - lookback:i]
        avg_vol = sum(d(x['volume']) for x in prev) / Decimal(lookback)
        if avg_vol <= 0:
            continue
        open_p, close_p = d(c['open_price']), d(c['close_price'])
        vol = d(c['volume'])
        if close_p > open_p and vol >= avg_vol * vol_mult:
            fut = d(candles[i + horizon]['close_price'])
            raw = (fut - close_p) / close_p if close_p > 0 else Decimal('0')
            signals.append({
                'symbol': symbol,
                'timestamp': c['timestamp'],
                'volume_multiple': float(vol / avg_vol),
                'entry_close': float(close_p),
                'net_return_after_cost': float(raw - cost_pct),
            })
    vals = [s['net_return_after_cost'] for s in signals]
    return {
        'symbol': symbol,
        'lookback': lookback,
        'horizon': horizon,
        'volume_multiple_threshold': str(vol_mult),
        'stats': stats(vals),
        'diagnostic_edge_like': len(vals) >= 30 and bool(vals) and mean(vals) > 0 and (sum(1 for v in vals if v > 0) / len(vals)) >= 0.52,
        'recent_signals': signals[-10:],
        '_signals': signals,
    }


def split_train_test(signals: list[dict], train_fraction: Decimal) -> tuple[list[dict], list[dict]]:
    ordered = sorted(signals, key=lambda x: str(x.get('timestamp', '')))
    if not ordered:
        return [], []
    cut = int(len(ordered) * float(train_fraction))
    cut = min(max(cut, 1), len(ordered) - 1) if len(ordered) > 1 else len(ordered)
    return ordered[:cut], ordered[cut:]


def evaluate_aggregate(signals: list[dict], *, min_total_signals: int, min_test_signals: int, min_win_rate: Decimal, min_avg_net_return: Decimal, train_fraction: Decimal) -> dict:
    train, test = split_train_test(signals, train_fraction)
    train_vals = [s['net_return_after_cost'] for s in train]
    test_vals = [s['net_return_after_cost'] for s in test]
    all_vals = [s['net_return_after_cost'] for s in signals]
    train_stats, test_stats, all_stats = stats(train_vals), stats(test_vals), stats(all_vals)
    blockers = []
    if len(all_vals) < min_total_signals:
        blockers.append('insufficient_total_signals')
    if len(test_vals) < min_test_signals:
        blockers.append('insufficient_locked_test_signals')
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
        'train_fraction': str(train_fraction),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--source-db', default='data/low_kr_backtest.sqlite3')
    ap.add_argument('--symbols', default='cached', help="'cached' uses all cached daily-candle symbols; or comma-separated symbols")
    ap.add_argument('--symbols-file', default='')
    ap.add_argument('--out', default='data/volume_shock_hypothesis_latest.json')
    ap.add_argument('--vol-mult', default='3')
    ap.add_argument('--lookback', type=int, default=20)
    # Locked before validation. Do not choose the best of 1/3/5 after seeing results.
    ap.add_argument('--horizon', type=int, default=3)
    # Includes approximate buy/sell fees, tax, and rough slippage; research-only default.
    ap.add_argument('--cost-pct', default='0.006')
    ap.add_argument('--min-symbols', type=int, default=50)
    ap.add_argument('--min-total-signals', type=int, default=100)
    ap.add_argument('--min-test-signals', type=int, default=30)
    ap.add_argument('--min-win-rate', default='0.52')
    ap.add_argument('--min-avg-net-return', default='0')
    ap.add_argument('--train-fraction', default='0.70')
    args = ap.parse_args()

    symbols = load_symbols(args)
    rows = []
    all_signals = []
    for sym in symbols:
        row = test_symbol(
            cached_candles_readonly(args.source_db, sym),
            symbol=sym,
            vol_mult=Decimal(args.vol_mult),
            lookback=args.lookback,
            horizon=args.horizon,
            cost_pct=Decimal(args.cost_pct),
        )
        all_signals.extend(row.pop('_signals'))
        rows.append(row)
    aggregate = evaluate_aggregate(
        all_signals,
        min_total_signals=args.min_total_signals,
        min_test_signals=args.min_test_signals,
        min_win_rate=Decimal(args.min_win_rate),
        min_avg_net_return=Decimal(args.min_avg_net_return),
        train_fraction=Decimal(args.train_fraction),
    )
    universe_blockers = []
    if len(symbols) < args.min_symbols:
        universe_blockers.append('insufficient_universe_symbols')
    edge_ok = aggregate['edge_ok'] and not universe_blockers
    report = {
        'hypothesis': 'volume_shock_positive_candle_continuation',
        'definition': f'volume >= {args.vol_mult}x previous {args.lookback}d average and close > open; locked horizon={args.horizon}d; measure forward net return after cost',
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
            'min_win_rate': args.min_win_rate,
            'min_avg_net_return': args.min_avg_net_return,
        },
        'summary': {
            'edge_ok': edge_ok,
            'blockers': universe_blockers + aggregate['blockers'],
            'aggregate': aggregate,
            'diagnostic_edge_like_symbols': [r['symbol'] for r in rows if r['diagnostic_edge_like']],
            'note': 'Symbol-level positives are diagnostics only. Global edge requires enough cross-sectional samples and a locked test split.',
        },
        'rows': rows,
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
