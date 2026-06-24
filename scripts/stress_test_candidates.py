#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sqlite3
from decimal import Decimal, ROUND_DOWN
from pathlib import Path

def cached_candles_readonly(db_path: str, symbol: str, limit: int = 90) -> list[dict]:
    if not Path(db_path).exists():
        return []
    con = sqlite3.connect(f'file:{db_path}?mode=ro', uri=True)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(
            "SELECT timestamp, open_price, high_price, low_price, close_price, volume, currency FROM candle_cache WHERE symbol=? AND interval='1d' ORDER BY timestamp DESC LIMIT ?",
            (symbol, limit),
        ).fetchall()
    finally:
        con.close()
    return [
        {
            'timestamp': r['timestamp'],
            'openPrice': r['open_price'],
            'highPrice': r['high_price'],
            'lowPrice': r['low_price'],
            'closePrice': r['close_price'],
            'volume': r['volume'],
            'currency': r['currency'],
        }
        for r in rows
    ]


def pair_cash_map(pair: str) -> dict[str, Decimal]:
    out = {}
    for part in pair.split('+'):
        if ':' in part:
            sym, cash = part.split(':', 1)
            out[sym.strip()] = Decimal(cash.strip())
    return out


def max_drawdown(closes: list[Decimal]) -> Decimal:
    peak = Decimal('0')
    mdd = Decimal('0')
    for p in closes:
        peak = max(peak, p)
        if peak > 0:
            mdd = min(mdd, (p - peak) / peak)
    return mdd


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--candidates', default='data/live_paper_candidates.json')
    ap.add_argument('--db-path', default=os.getenv('TOSS_DB_PATH', 'data/low_kr_backtest.sqlite3'))
    ap.add_argument('--out', default='data/stress_test_latest.json')
    ap.add_argument('--shocks', default='-0.03,-0.05,-0.10')
    args = ap.parse_args()
    data = json.loads(Path(args.candidates).read_text())
    shocks = [Decimal(x) for x in args.shocks.split(',') if x]
    rows = []
    for cand in data.get('candidates', [])[:10]:
        cash = pair_cash_map(cand.get('pair', ''))
        symbol_rows = {}
        weighted_mdd = Decimal('0')
        total_cash = sum(cash.values()) or Decimal('1')
        for sym, slot in cash.items():
            candles = cached_candles_readonly(args.db_path, sym, limit=90)
            closes = [Decimal(str(c['closePrice'])) for c in reversed(candles[:90])] if candles else []
            last = closes[-1] if closes else Decimal('0')
            qty = (slot / last).to_integral_value(rounding=ROUND_DOWN) if last > 0 else Decimal('0')
            residual = slot - qty * last if last > 0 else slot
            mdd = max_drawdown(closes) if closes else Decimal('0')
            weighted_mdd += mdd * (slot / total_cash)
            symbol_rows[sym] = {'slot_cash': str(slot), 'last_close': str(last), 'qty': str(qty), 'residual_cash': str(residual), 'mdd_90d': str(mdd)}
        shock_results = []
        for shock in shocks:
            pnl = Decimal('0')
            for sym, slot in cash.items():
                last = Decimal(symbol_rows[sym]['last_close'])
                qty = Decimal(symbol_rows[sym]['qty'])
                pnl += qty * last * shock
            shock_results.append({'shock': str(shock), 'pnl_krw': str(pnl), 'pnl_pct_on_total_cash': str(pnl / total_cash if total_cash else Decimal('0'))})
        worst = min(Decimal(r['pnl_pct_on_total_cash']) for r in shock_results) if shock_results else Decimal('0')
        ok = worst > Decimal('-0.08') and weighted_mdd > Decimal('-0.25')
        rows.append({'pair': cand.get('pair'), 'name': cand.get('name'), 'status': 'stress_checked_watchlist_not_live_order' if ok else 'blocked_stress_risk', 'ok': ok, 'weighted_mdd_90d': str(weighted_mdd), 'symbols': symbol_rows, 'shocks': shock_results})
    report = {'shocks': [str(s) for s in shocks], 'rows': rows, 'live_order_allowed': False}
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
