#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
from decimal import Decimal
from pathlib import Path
from statistics import mean


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


def d(x) -> Decimal:
    return Decimal(str(x or '0'))


def test_symbol(candles: list[dict], *, symbol: str, vol_mult: Decimal, lookback: int, horizons: list[int], cost_pct: Decimal) -> dict:
    rows = []
    max_h = max(horizons)
    for i in range(lookback, len(candles) - max_h):
        c = candles[i]
        prev = candles[i - lookback:i]
        avg_vol = sum(d(x['volume']) for x in prev) / Decimal(lookback)
        if avg_vol <= 0:
            continue
        open_p, close_p = d(c['open_price']), d(c['close_price'])
        vol = d(c['volume'])
        if close_p > open_p and vol >= avg_vol * vol_mult:
            item = {'timestamp': c['timestamp'], 'volume_multiple': float(vol / avg_vol), 'entry_close': float(close_p), 'returns': {}}
            for h in horizons:
                fut = d(candles[i + h]['close_price'])
                raw = (fut - close_p) / close_p if close_p > 0 else Decimal('0')
                item['returns'][str(h)] = float(raw - cost_pct)
            rows.append(item)
    by_h = {}
    for h in horizons:
        vals = [r['returns'][str(h)] for r in rows]
        by_h[str(h)] = {
            'signals': len(vals),
            'avg_net_return_after_cost': mean(vals) if vals else None,
            'win_rate_after_cost': (sum(1 for v in vals if v > 0) / len(vals)) if vals else None,
            'edge_ok': len(vals) >= 5 and bool(vals) and mean(vals) > 0 and (sum(1 for v in vals if v > 0) / len(vals)) >= 0.5,
        }
    return {'symbol': symbol, 'lookback': lookback, 'volume_multiple_threshold': str(vol_mult), 'horizons': by_h, 'recent_signals': rows[-10:]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--source-db', default='data/low_kr_backtest.sqlite3')
    ap.add_argument('--symbols', default='336570,204620,073240,032620,462860')
    ap.add_argument('--out', default='data/volume_shock_hypothesis_latest.json')
    ap.add_argument('--vol-mult', default='3')
    ap.add_argument('--lookback', type=int, default=20)
    ap.add_argument('--horizons', default='1,3,5')
    # Includes approximate buy/sell fees, tax, and rough slippage; research-only default.
    ap.add_argument('--cost-pct', default='0.006')
    args = ap.parse_args()
    horizons = [int(x) for x in args.horizons.split(',') if x]
    rows = []
    for sym in [x.strip() for x in args.symbols.split(',') if x.strip()]:
        rows.append(test_symbol(cached_candles_readonly(args.source_db, sym), symbol=sym, vol_mult=Decimal(args.vol_mult), lookback=args.lookback, horizons=horizons, cost_pct=Decimal(args.cost_pct)))
    report = {
        'hypothesis': 'volume_shock_positive_candle_continuation',
        'definition': f'volume >= {args.vol_mult}x previous {args.lookback}d average and close > open; measure forward net return after cost',
        'cost_pct': args.cost_pct,
        'rows': rows,
        'edge_ok_symbols': [r['symbol'] for r in rows if any(h['edge_ok'] for h in r['horizons'].values())],
    }
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
