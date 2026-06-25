#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import urllib.parse
import urllib.request
from decimal import Decimal
from pathlib import Path

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


def std(vals: list[Decimal]) -> Decimal:
    if len(vals) < 2:
        return Decimal('0')
    mu = avg(vals)
    return avg([(v - mu) * (v - mu) for v in vals]).sqrt()


def pct_change(a: Decimal, b: Decimal) -> Decimal:
    return (b - a) / a if a > 0 else Decimal('0')


def rsi(closes: list[Decimal], period: int) -> Decimal | None:
    if len(closes) < period + 1:
        return None
    gains = []
    losses = []
    for i in range(len(closes) - period, len(closes)):
        chg = closes[i] - closes[i - 1]
        gains.append(max(chg, Decimal('0')))
        losses.append(max(-chg, Decimal('0')))
    avg_gain = avg(gains)
    avg_loss = avg(losses)
    if avg_loss == 0:
        return Decimal('100')
    rs = avg_gain / avg_loss
    return Decimal('100') - (Decimal('100') / (Decimal('1') + rs))


def cached_candles_readonly(db_path: str, symbol: str) -> list[dict]:
    if not Path(db_path).exists():
        return []
    con = sqlite3.connect(f'file:{db_path}?mode=ro', uri=True)
    cur = None
    try:
        cur = con.execute(
            """
            SELECT timestamp, open_price, high_price, low_price, close_price, volume
            FROM candle_cache
            WHERE symbol=? AND interval='1d'
            ORDER BY timestamp ASC
            """,
            (symbol,),
        )
        rows = cur.fetchall()
    finally:
        if cur is not None:
            cur.close()
        con.close()
    candles = []
    for row in rows:
        try:
            timestamp, open_price, high_price, low_price, close_price, volume = row
            c = {
                'timestamp': str(timestamp)[:10],
                'open_price': d(open_price),
                'high_price': d(high_price),
                'low_price': d(low_price),
                'close_price': d(close_price),
                'volume': d(volume),
            }
        except Exception:
            continue
        if c['open_price'] > 0 and c['high_price'] > 0 and c['low_price'] > 0 and c['close_price'] > 0:
            candles.append(c)
    return candles


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
            rows.append({'timestamp': f'{date[:4]}-{date[4:6]}-{date[6:8]}', 'close_price': d(row['closePrice'])})
        except Exception:
            continue
    return rows


def market_guard_map(index_rows: list[dict], *, min_20d_return: Decimal, max_ann_vol: Decimal | None = None) -> dict[str, dict]:
    out = {}
    closes = [r['close_price'] for r in index_rows]
    sqrt252 = Decimal('15.874507866387544')
    for i, row in enumerate(index_rows):
        if i < 20:
            out[row['timestamp']] = {'ok': False, 'reason': 'insufficient_market_history'}
            continue
        ret20 = pct_change(closes[i - 20], closes[i])
        rets20 = [pct_change(closes[j - 1], closes[j]) for j in range(i - 19, i + 1)]
        ann_vol = std(rets20) * sqrt252
        ok = ret20 >= min_20d_return and (max_ann_vol is None or ann_vol <= max_ann_vol)
        if ret20 < min_20d_return:
            reason = 'market_crash_guard'
        elif max_ann_vol is not None and ann_vol > max_ann_vol:
            reason = 'market_high_vol_guard'
        else:
            reason = 'market_not_crashing'
        out[row['timestamp']] = {
            'ok': ok,
            'kosdaq_20d_return': float(ret20),
            'kosdaq_20d_ann_vol': float(ann_vol),
            'reason': reason,
        }
    return out


def signal_meta(candles: list[dict], i: int, market: dict[str, dict], args) -> tuple[bool, dict]:
    c = candles[i]
    m = market.get(c['timestamp'], {'ok': False, 'reason': 'market_date_missing'})
    if not m.get('ok'):
        return False, {'blocker': m.get('reason')}
    need = max(args.rsi_period + 1, args.bb_period, args.volume_lookback, args.min_price_history)
    if i < need:
        return False, {'blocker': 'insufficient_symbol_history'}
    closes = [x['close_price'] for x in candles]
    bb_window = closes[i - args.bb_period + 1:i + 1]
    mid = avg(bb_window)
    sigma = std(bb_window)
    lower = mid - Decimal(args.bb_dev) * sigma
    upper = mid + Decimal(args.bb_dev) * sigma
    r = rsi(closes[:i + 1], args.rsi_period)
    if r is None:
        return False, {'blocker': 'rsi_unavailable'}
    if not (r <= Decimal(args.oversold) and c['close_price'] <= lower):
        return False, {'blocker': 'no_oversold_bband_signal'}
    bb_z = (c['close_price'] - mid) / sigma if sigma > 0 else Decimal('0')
    if args.min_bb_z and bb_z < Decimal(args.min_bb_z):
        return False, {'blocker': 'bb_z_too_extreme', 'bb_z': float(bb_z)}
    vols = [x['volume'] for x in candles]
    avg_vol = avg(vols[i - args.volume_lookback:i])
    volume_multiple = c['volume'] / avg_vol if avg_vol > 0 else Decimal('99')
    if volume_multiple > Decimal(args.max_volume_multiple):
        return False, {'blocker': 'volume_shock_avoided', 'volume_multiple': float(volume_multiple)}
    if c['close_price'] < Decimal(args.min_close_price):
        return False, {'blocker': 'too_low_price'}
    prior_5d_return = pct_change(closes[i - 5], closes[i]) if i >= 5 else Decimal('0')
    prior_20d_return = pct_change(closes[i - 20], closes[i]) if i >= 20 else Decimal('0')
    prior_60d_return = pct_change(closes[i - 60], closes[i]) if i >= 60 else Decimal('0')
    avg_trade_value_20d = avg([candles[j]['close_price'] * candles[j]['volume'] for j in range(i - 20, i)]) if i >= 20 else Decimal('0')
    signal_trade_value = c['close_price'] * c['volume']
    prev_high_20d = max([candles[j]['high_price'] for j in range(i - 20, i)]) if i >= 20 else c['high_price']
    prev_low_20d = min([candles[j]['low_price'] for j in range(i - 20, i)]) if i >= 20 else c['low_price']
    range_20d_pct = (prev_high_20d - prev_low_20d) / prev_low_20d if prev_low_20d > 0 else Decimal('99')
    return True, {
        'rsi': float(r),
        'bb_mid': float(mid),
        'bb_lower': float(lower),
        'bb_upper': float(upper),
        'bb_z': float(bb_z),
        'volume_multiple': float(volume_multiple),
        'prior_5d_return': float(prior_5d_return),
        'prior_20d_return': float(prior_20d_return),
        'prior_60d_return': float(prior_60d_return),
        'avg_trade_value_20d': float(avg_trade_value_20d),
        'signal_trade_value': float(signal_trade_value),
        'range_20d_pct': float(range_20d_pct),
        'kosdaq_20d_return': m.get('kosdaq_20d_return'),
        'kosdaq_20d_ann_vol': m.get('kosdaq_20d_ann_vol'),
    }


def simulate_trade(candles: list[dict], i: int, meta: dict, args) -> dict | None:
    if i + 1 >= len(candles):
        return None
    signal_close = candles[i]['close_price']
    entry_day = candles[i + 1]
    entry = entry_day['open_price']
    gap = entry / signal_close - 1 if signal_close > 0 else Decimal('99')
    if gap < Decimal(args.max_gap_down_pct):
        return None
    if gap > Decimal(args.max_gap_up_pct):
        return None
    stop = entry * (Decimal('1') - Decimal(args.stop_pct))
    max_j = min(i + 1 + args.horizon, len(candles) - 1)
    exit_price = candles[max_j]['close_price']
    exit_ts = candles[max_j]['timestamp']
    exit_reason = 'horizon_close'
    closes = [x['close_price'] for x in candles]
    for j in range(i + 1, max_j + 1):
        day = candles[j]
        if day['low_price'] <= stop:
            exit_price = stop
            exit_ts = day['timestamp']
            exit_reason = 'stop_loss'
            break
        if j >= args.bb_period and j + 1 < len(candles):
            bb_window = closes[j - args.bb_period + 1:j + 1]
            mid = avg(bb_window)
            r = rsi(closes[:j + 1], args.rsi_period)
            if day['close_price'] >= mid or (r is not None and r >= Decimal(args.exit_rsi)):
                exit_price = candles[j + 1]['open_price']
                exit_ts = candles[j + 1]['timestamp']
                exit_reason = 'mean_reversion_exit_next_open'
                break
    raw = (exit_price - entry) / entry if entry > 0 else Decimal('0')
    net = raw - Decimal(args.roundtrip_cost_pct)
    return {
        'entry_timestamp': entry_day['timestamp'],
        'exit_timestamp': exit_ts,
        'entry_price': float(entry),
        'exit_price': float(exit_price),
        'gap_from_signal_close': float(gap),
        'raw_return': float(raw),
        'net_return_after_cost': float(net),
        'abs_net_return_after_cost': float(abs(raw) - Decimal(args.roundtrip_cost_pct)),
        'exit_reason': exit_reason,
    }


def test_symbol(candles: list[dict], *, symbol: str, market: dict[str, dict], args) -> dict:
    signals = []
    next_available_idx = 0
    start_i = max(args.rsi_period + 1, args.bb_period, args.volume_lookback, args.min_price_history)
    for i in range(start_i, len(candles) - args.horizon - 2):
        if i < next_available_idx:
            continue
        ok, meta = signal_meta(candles, i, market, args)
        if not ok:
            continue
        trade = simulate_trade(candles, i, meta, args)
        if trade is None:
            continue
        signals.append({
            'symbol': symbol,
            'timestamp': candles[i]['timestamp'],
            'signal_close': float(candles[i]['close_price']),
            **meta,
            **trade,
        })
        next_available_idx = i + 1 + args.cooldown_days
    vals = [s['net_return_after_cost'] for s in signals]
    return {'symbol': symbol, 'candles': len(candles), 'stats': stats(vals), 'recent_signals': signals[-5:], '_signals': signals}


def write_signals_csv(path: str, signals: list[dict]) -> None:
    if not path:
        return
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    keys: list[str] = []
    for row in signals:
        for key in row:
            if key not in keys:
                keys.append(key)
    with out.open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader()
        writer.writerows(signals)


def run(args) -> dict:
    market = market_guard_map(
        fetch_kosdaq_index(args.index_start, args.index_end),
        min_20d_return=Decimal(args.market_min_20d_return),
        max_ann_vol=Decimal(args.market_max_ann_vol) if args.market_max_ann_vol else None,
    )
    symbols = load_symbols(argparse.Namespace(symbols=args.symbols, symbols_file=args.symbols_file, source_db=args.source_db))
    rows = []
    all_signals = []
    for sym in symbols:
        row = test_symbol(cached_candles_readonly(args.source_db, sym), symbol=sym, market=market, args=args)
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
    eq = {'all': equal_weight_by_symbol_stats(all_signals), 'locked_test': equal_weight_by_symbol_stats(test_signals)}
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
    exit_counts = {}
    for s in all_signals:
        exit_counts[s['exit_reason']] = exit_counts.get(s['exit_reason'], 0) + 1
    report = {
        'mode': 'research_only_no_send',
        'live_order_allowed': False,
        'hypothesis_id': args.hypothesis_id,
        'hypothesis_status': args.hypothesis_status,
        'config': vars(args),
        'summary': {
            'edge_ok': aggregate['edge_ok'],
            'blockers': aggregate['blockers'],
            'aggregate': aggregate,
            'distribution': distribution_metrics(all_signals),
            'equal_weight_by_symbol': eq,
            'exit_counts': exit_counts,
            'future_holdout_required_for_any_promotion': True,
            'external_hint_source': 'ai_trader_bounded_30:RsiBollingerBandsStrategy',
        },
        'rows': rows,
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    write_signals_csv(args.signals_out, all_signals)
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description='Audit RSI + Bollinger lower-band mean-reversion hypothesis. Research-only/no-send.')
    ap.add_argument('--source-db', default='data/edge_research_universe_long.sqlite3')
    ap.add_argument('--symbols', default='cached')
    ap.add_argument('--symbols-file', default='')
    ap.add_argument('--out', default='data/rsi_bbands_mean_reversion_h20_v1.json')
    ap.add_argument('--signals-out', default='', help='Optional CSV path for every generated trade signal')
    ap.add_argument('--hypothesis-id', default='RSI_BBANDS_MEAN_REVERSION_H20_V1')
    ap.add_argument('--hypothesis-status', default='new_fixed_hypothesis_after_external_sweep_hint_requires_future_holdout')
    ap.add_argument('--index-start', default='20200101')
    ap.add_argument('--index-end', default='20260625')
    ap.add_argument('--market-min-20d-return', default='-0.12')
    ap.add_argument('--market-max-ann-vol', default='', help='Optional KOSDAQ 20d annualized volatility ceiling, e.g. 0.40')
    ap.add_argument('--rsi-period', type=int, default=14)
    ap.add_argument('--bb-period', type=int, default=20)
    ap.add_argument('--bb-dev', default='2')
    ap.add_argument('--min-bb-z', default='', help='Optional lower bound for BB z-score, e.g. -2.5 to avoid extreme falling knives')
    ap.add_argument('--oversold', default='30')
    ap.add_argument('--exit-rsi', default='55')
    ap.add_argument('--volume-lookback', type=int, default=20)
    ap.add_argument('--max-volume-multiple', default='3')
    ap.add_argument('--min-close-price', default='1000')
    ap.add_argument('--min-price-history', type=int, default=60)
    ap.add_argument('--max-gap-down-pct', default='-0.10')
    ap.add_argument('--max-gap-up-pct', default='0.08')
    ap.add_argument('--horizon', type=int, default=20)
    ap.add_argument('--cooldown-days', type=int, default=20)
    ap.add_argument('--stop-pct', default='0.10')
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
