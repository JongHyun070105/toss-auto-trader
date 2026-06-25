#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
import urllib.parse
import urllib.request
from decimal import Decimal
from pathlib import Path
from statistics import mean

from volume_shock_hypothesis_audit import (
    distribution_metrics,
    equal_weight_by_symbol_stats,
    evaluate_aggregate,
    load_symbols,
    split_train_test,
    stats,
)


def d(x) -> Decimal:
    return Decimal(str(x or '0'))


def avg(vals: list[Decimal]) -> Decimal:
    return sum(vals) / Decimal(len(vals)) if vals else Decimal('0')


def pct_change(a: Decimal, b: Decimal) -> Decimal:
    return (b - a) / a if a > 0 else Decimal('0')


def cached_candles_readonly(db_path: str, symbol: str) -> list[dict]:
    if not Path(db_path).exists():
        return []
    con = sqlite3.connect(f'file:{db_path}?mode=ro', uri=True)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(
            """
            SELECT timestamp, open_price, high_price, low_price, close_price, volume
            FROM candle_cache
            WHERE symbol=? AND interval='1d'
            ORDER BY timestamp ASC
            """,
            (symbol,),
        ).fetchall()
    finally:
        con.close()
    out = []
    for row in rows:
        try:
            out.append({
                'timestamp': str(row['timestamp'])[:10],
                'open_price': d(row['open_price']),
                'high_price': d(row['high_price']),
                'low_price': d(row['low_price']),
                'close_price': d(row['close_price']),
                'volume': d(row['volume']),
            })
        except Exception:
            continue
    return [c for c in out if c['open_price'] > 0 and c['high_price'] > 0 and c['low_price'] > 0 and c['close_price'] > 0]


def fetch_kosdaq_index(start_yyyymmdd: str = '20200101', end_yyyymmdd: str = '20260625') -> list[dict]:
    query = urllib.parse.urlencode({'startDateTime': f'{start_yyyymmdd}0000', 'endDateTime': f'{end_yyyymmdd}0000'})
    url = f'https://api.stock.naver.com/chart/domestic/index/KOSDAQ/day?{query}'
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0', 'Referer': 'https://finance.naver.com/'})
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read().decode('utf-8'))
    rows = []
    for row in data or []:
        try:
            date = str(row['localDate'])
            rows.append({
                'timestamp': f'{date[:4]}-{date[4:6]}-{date[6:8]}',
                'close_price': d(row['closePrice']),
            })
        except Exception:
            continue
    return rows


def market_regime_map(index_rows: list[dict], *, sma_period: int, min_20d_return: Decimal) -> dict[str, dict]:
    out: dict[str, dict] = {}
    closes = [r['close_price'] for r in index_rows]
    for i, row in enumerate(index_rows):
        if i < max(sma_period, 20):
            out[row['timestamp']] = {'ok': False, 'reason': 'insufficient_market_history'}
            continue
        sma = avg(closes[i - sma_period + 1:i + 1])
        ret20 = pct_change(closes[i - 20], closes[i])
        ok = closes[i] > sma and ret20 > min_20d_return
        out[row['timestamp']] = {
            'ok': ok,
            'kosdaq_close': float(closes[i]),
            'kosdaq_sma': float(sma),
            'kosdaq_20d_return': float(ret20),
            'reason': 'market_uptrend' if ok else 'market_regime_blocked',
        }
    return out


def realized_volatility(closes: list[Decimal]) -> Decimal:
    if len(closes) < 2:
        return Decimal('0')
    returns = [pct_change(closes[i - 1], closes[i]) for i in range(1, len(closes)) if closes[i - 1] > 0]
    if not returns:
        return Decimal('0')
    mu = avg(returns)
    var = avg([(r - mu) * (r - mu) for r in returns])
    return var.sqrt()


def signal_ok(
    candles: list[dict],
    i: int,
    regime: dict[str, dict],
    *,
    sma_period: int,
    breakout_lookback: int,
    vol_lookback: int,
    max_daily_vol: Decimal,
    max_range_pct: Decimal,
    max_volume_multiple: Decimal,
    max_sma_extension: Decimal,
) -> tuple[bool, dict]:
    c = candles[i]
    m = regime.get(c['timestamp'], {'ok': False, 'reason': 'market_date_missing'})
    if not m.get('ok'):
        return False, {'blocker': m.get('reason', 'market_blocked')}
    need = max(sma_period, breakout_lookback, vol_lookback)
    if i < need:
        return False, {'blocker': 'insufficient_symbol_history'}
    closes = [x['close_price'] for x in candles]
    highs = [x['high_price'] for x in candles]
    lows = [x['low_price'] for x in candles]
    vols = [x['volume'] for x in candles]
    sma = avg(closes[i - sma_period + 1:i + 1])
    if c['close_price'] <= sma:
        return False, {'blocker': 'symbol_not_above_sma'}
    extension = (c['close_price'] - sma) / sma if sma > 0 else Decimal('99')
    if extension > max_sma_extension:
        return False, {'blocker': 'too_extended_from_sma', 'sma_extension': float(extension)}
    prev_high = max(highs[i - breakout_lookback:i])
    if c['close_price'] <= prev_high:
        return False, {'blocker': 'no_close_breakout'}
    vol = realized_volatility(closes[i - vol_lookback + 1:i + 1])
    if vol > max_daily_vol:
        return False, {'blocker': 'too_volatile', 'daily_volatility': float(vol)}
    range_low = min(lows[i - breakout_lookback:i + 1])
    range_high = max(highs[i - breakout_lookback:i + 1])
    range_pct = (range_high - range_low) / range_low if range_low > 0 else Decimal('99')
    if range_pct > max_range_pct:
        return False, {'blocker': 'range_too_wide', 'range_pct': float(range_pct)}
    avg_vol = avg(vols[i - 20:i])
    volume_multiple = c['volume'] / avg_vol if avg_vol > 0 else Decimal('99')
    if volume_multiple > max_volume_multiple:
        return False, {'blocker': 'volume_shock_avoided', 'volume_multiple': float(volume_multiple)}
    return True, {
        'kosdaq_20d_return': m.get('kosdaq_20d_return'),
        'kosdaq_close': m.get('kosdaq_close'),
        'symbol_sma': float(sma),
        'sma_extension': float(extension),
        'prev_high': float(prev_high),
        'daily_volatility': float(vol),
        'range_pct': float(range_pct),
        'volume_multiple': float(volume_multiple),
    }


def simulate_exit(
    candles: list[dict],
    i: int,
    *,
    horizon: int,
    stop_pct: Decimal,
    take_pct: Decimal,
    max_gap_up_pct: Decimal,
    roundtrip_cost_pct: Decimal,
) -> dict | None:
    if i + 1 >= len(candles):
        return None
    signal_close = candles[i]['close_price']
    entry_day = candles[i + 1]
    entry = entry_day['open_price']
    if signal_close > 0 and (entry / signal_close - 1) > max_gap_up_pct:
        return None
    stop = entry * (Decimal('1') - stop_pct)
    take = entry * (Decimal('1') + take_pct)
    max_j = min(i + 1 + horizon, len(candles) - 1)
    exit_price = candles[max_j]['close_price']
    exit_ts = candles[max_j]['timestamp']
    exit_reason = 'horizon_close'
    for j in range(i + 1, max_j + 1):
        day = candles[j]
        # Conservative OHLC ambiguity: if stop and take are both touched, assume stop first.
        if day['low_price'] <= stop:
            exit_price = stop
            exit_ts = day['timestamp']
            exit_reason = 'stop_loss'
            break
        if day['high_price'] >= take:
            exit_price = take
            exit_ts = day['timestamp']
            exit_reason = 'take_profit'
            break
    raw = (exit_price - entry) / entry if entry > 0 else Decimal('0')
    net = raw - roundtrip_cost_pct
    return {
        'entry_timestamp': entry_day['timestamp'],
        'exit_timestamp': exit_ts,
        'entry_price': float(entry),
        'exit_price': float(exit_price),
        'raw_return': float(raw),
        'net_return_after_cost': float(net),
        'abs_net_return_after_cost': float(abs(raw) - roundtrip_cost_pct),
        'exit_reason': exit_reason,
    }


def test_symbol(candles: list[dict], *, symbol: str, regime: dict[str, dict], args) -> dict:
    signals = []
    next_available_idx = 0
    for i in range(max(args.sma_period, args.breakout_lookback, args.vol_lookback, 20), len(candles) - args.horizon - 1):
        if i < next_available_idx:
            continue
        ok, meta = signal_ok(
            candles,
            i,
            regime,
            sma_period=args.sma_period,
            breakout_lookback=args.breakout_lookback,
            vol_lookback=args.vol_lookback,
            max_daily_vol=Decimal(args.max_daily_vol),
            max_range_pct=Decimal(args.max_range_pct),
            max_volume_multiple=Decimal(args.max_volume_multiple),
            max_sma_extension=Decimal(args.max_sma_extension),
        )
        if not ok:
            continue
        trade = simulate_exit(
            candles,
            i,
            horizon=args.horizon,
            stop_pct=Decimal(args.stop_pct),
            take_pct=Decimal(args.take_pct),
            max_gap_up_pct=Decimal(args.max_gap_up_pct),
            roundtrip_cost_pct=Decimal(args.roundtrip_cost_pct),
        )
        if trade is None:
            continue
        signals.append({
            'symbol': symbol,
            'timestamp': candles[i]['timestamp'],
            'close_price': float(candles[i]['close_price']),
            **meta,
            **trade,
        })
        next_available_idx = i + 1 + args.horizon
    vals = [s['net_return_after_cost'] for s in signals]
    return {
        'symbol': symbol,
        'candles': len(candles),
        'stats': stats(vals),
        'recent_signals': signals[-5:],
        '_signals': signals,
    }


def run(args) -> dict:
    regime = market_regime_map(
        fetch_kosdaq_index(args.index_start, args.index_end),
        sma_period=args.market_sma_period,
        min_20d_return=Decimal(args.market_min_20d_return),
    )
    symbols = load_symbols(argparse.Namespace(symbols=args.symbols, symbols_file=args.symbols_file, source_db=args.source_db))
    rows = []
    all_signals = []
    for sym in symbols:
        row = test_symbol(cached_candles_readonly(args.source_db, sym), symbol=sym, regime=regime, args=args)
        all_signals.extend(row.pop('_signals'))
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
    test_signals = split_train_test(all_signals, Decimal(args.train_fraction))[1]
    eq = {
        'all': equal_weight_by_symbol_stats(all_signals),
        'locked_test': equal_weight_by_symbol_stats(test_signals),
    }
    if args.require_locked_test_median_nonnegative:
        med = aggregate['locked_test'].get('median_net_return_after_cost')
        if med is None or med < 0:
            aggregate['blockers'].append('locked_test_median_net_return_negative')
            aggregate['edge_ok'] = False
    if args.require_equal_weight_positive:
        ew = eq['locked_test'].get('avg_symbol_mean_net_return_after_cost')
        if ew is None or ew <= 0:
            aggregate['blockers'].append('locked_test_equal_weight_symbol_mean_not_positive')
            aggregate['edge_ok'] = False
    exit_counts: dict[str, int] = {}
    for s in all_signals:
        exit_counts[s['exit_reason']] = exit_counts.get(s['exit_reason'], 0) + 1
    report = {
        'mode': 'research_only_no_send',
        'live_order_allowed': False,
        'hypothesis_id': 'REGIME_LOW_VOL_BREAKOUT_H10_V1',
        'hypothesis_status': 'new_fixed_hypothesis_first_validation_same_history_consumed',
        'config': vars(args),
        'summary': {
            'edge_ok': aggregate['edge_ok'],
            'blockers': aggregate['blockers'],
            'aggregate': aggregate,
            'distribution': distribution_metrics(all_signals),
            'equal_weight_by_symbol': eq,
            'exit_counts': exit_counts,
            'future_holdout_required_for_any_promotion': True,
        },
        'rows': rows,
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description='Audit a fixed KOSDAQ-regime low-volatility breakout hypothesis. Research-only/no-send.')
    ap.add_argument('--source-db', default='data/edge_research_universe_long.sqlite3')
    ap.add_argument('--symbols', default='cached')
    ap.add_argument('--symbols-file', default='')
    ap.add_argument('--out', default='data/regime_low_vol_breakout_h10_v1.json')
    ap.add_argument('--index-start', default='20200101')
    ap.add_argument('--index-end', default='20260625')
    ap.add_argument('--market-sma-period', type=int, default=120)
    ap.add_argument('--market-min-20d-return', default='-0.05')
    ap.add_argument('--sma-period', type=int, default=60)
    ap.add_argument('--breakout-lookback', type=int, default=20)
    ap.add_argument('--vol-lookback', type=int, default=20)
    ap.add_argument('--max-daily-vol', default='0.05')
    ap.add_argument('--max-range-pct', default='0.35')
    ap.add_argument('--max-volume-multiple', default='2.5')
    ap.add_argument('--max-sma-extension', default='0.20')
    ap.add_argument('--max-gap-up-pct', default='0.08')
    ap.add_argument('--horizon', type=int, default=10)
    ap.add_argument('--stop-pct', default='0.06')
    ap.add_argument('--take-pct', default='0.12')
    ap.add_argument('--roundtrip-cost-pct', default='0.0046')
    ap.add_argument('--min-total-signals', type=int, default=300)
    ap.add_argument('--min-test-signals', type=int, default=100)
    ap.add_argument('--min-signal-symbols', type=int, default=100)
    ap.add_argument('--max-symbol-signal-share', default='0.05')
    ap.add_argument('--max-month-signal-share', default='0.35')
    ap.add_argument('--min-win-rate', default='0.52')
    ap.add_argument('--min-avg-net-return', default='0')
    ap.add_argument('--train-fraction', default='0.70')
    ap.add_argument('--require-locked-test-median-nonnegative', action='store_true')
    ap.add_argument('--require-equal-weight-positive', action='store_true')
    args = ap.parse_args()
    report = run(args)
    print(json.dumps({
        'hypothesis_id': report['hypothesis_id'],
        'edge_ok': report['summary']['edge_ok'],
        'blockers': report['summary']['blockers'],
        'all': report['summary']['aggregate']['all'],
        'locked_test': report['summary']['aggregate']['locked_test'],
        'exit_counts': report['summary']['exit_counts'],
        'out': args.out,
    }, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
