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
from statistics import mean, median


def d(x) -> Decimal:
    return Decimal(str(x or '0'))


def cached_symbols(db_path: str) -> list[str]:
    if not Path(db_path).exists():
        return []
    con = sqlite3.connect(f'file:{db_path}?mode=ro', uri=True)
    try:
        rows = con.execute("SELECT DISTINCT symbol FROM candle_cache WHERE interval='1d' ORDER BY symbol").fetchall()
    finally:
        con.close()
    return [str(r[0]) for r in rows]


def first_last_close(db_path: str, symbol: str, *, start: str = '', end: str = '') -> dict | None:
    con = sqlite3.connect(f'file:{db_path}?mode=ro', uri=True)
    con.row_factory = sqlite3.Row
    try:
        where = ["symbol=?", "interval='1d'", "close_price IS NOT NULL"]
        params: list = [symbol]
        if start:
            where.append('timestamp >= ?')
            params.append(start)
        if end:
            where.append('timestamp <= ?')
            params.append(end)
        sql = 'SELECT timestamp, close_price FROM candle_cache WHERE ' + ' AND '.join(where) + ' ORDER BY timestamp ASC'
        rows = con.execute(sql, params).fetchall()
    finally:
        con.close()
    if len(rows) < 2:
        return None
    first, last = rows[0], rows[-1]
    first_close = d(first['close_price'])
    last_close = d(last['close_price'])
    if first_close <= 0 or last_close <= 0:
        return None
    return {
        'symbol': symbol,
        'bars': len(rows),
        'start_timestamp': first['timestamp'],
        'end_timestamp': last['timestamp'],
        'start_close': first_close,
        'end_close': last_close,
        'return': (last_close - first_close) / first_close,
    }


def summarize_returns(rows: list[dict]) -> dict:
    vals = [float(r['return']) for r in rows]
    return {
        'symbols': len(vals),
        'avg_return': mean(vals) if vals else None,
        'median_return': median(vals) if vals else None,
        'positive_rate': (sum(1 for v in vals if v > 0) / len(vals)) if vals else None,
        'top_return_symbols': [
            {'symbol': r['symbol'], 'return': float(r['return']), 'bars': r['bars']}
            for r in sorted(rows, key=lambda x: x['return'], reverse=True)[:10]
        ],
        'bottom_return_symbols': [
            {'symbol': r['symbol'], 'return': float(r['return']), 'bars': r['bars']}
            for r in sorted(rows, key=lambda x: x['return'])[:10]
        ],
    }


def yyyymmdd(value: str) -> str:
    if not value:
        return ''
    s = value[:10].replace('-', '')
    return s if len(s) == 8 and s.isdigit() else value[:8]


def load_index_csv(path: str) -> dict:
    if not path:
        return {'available': False, 'reason': 'kosdaq_index_csv_not_configured'}
    p = Path(path)
    if not p.exists():
        return {'available': False, 'reason': f'kosdaq_index_csv_not_found:{path}'}
    rows = []
    with p.open() as f:
        reader = csv.DictReader(f)
        for row in reader:
            date = row.get('date') or row.get('timestamp') or row.get('Date')
            close = row.get('close') or row.get('Close') or row.get('close_price')
            if date and close:
                rows.append({'date': date, 'close': d(close)})
    rows = [r for r in rows if r['close'] > 0]
    if len(rows) < 2:
        return {'available': False, 'reason': 'kosdaq_index_csv_has_insufficient_rows'}
    rows.sort(key=lambda x: x['date'])
    ret = (rows[-1]['close'] - rows[0]['close']) / rows[0]['close']
    return {
        'available': True,
        'source': str(p),
        'start': rows[0]['date'],
        'end': rows[-1]['date'],
        'start_close': str(rows[0]['close']),
        'end_close': str(rows[-1]['close']),
        'return': float(ret),
    }


def fetch_naver_kosdaq_index(start: str, end: str) -> dict:
    start_ymd = yyyymmdd(start)
    end_ymd = yyyymmdd(end)
    if not start_ymd or not end_ymd:
        return {'available': False, 'reason': 'naver_kosdaq_window_unavailable'}
    query = urllib.parse.urlencode({'startDateTime': f'{start_ymd}0000', 'endDateTime': f'{end_ymd}0000'})
    url = f'https://api.stock.naver.com/chart/domestic/index/KOSDAQ/day?{query}'
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0', 'Referer': 'https://finance.naver.com/'})
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode('utf-8'))
    except Exception as e:
        return {'available': False, 'source': 'naver_stock_index_api', 'reason': f'{type(e).__name__}: {e}'}
    rows = []
    for r in data or []:
        date = str(r.get('localDate') or '')
        close = d(r.get('closePrice'))
        if date and close > 0:
            rows.append({'date': date, 'close': close})
    rows.sort(key=lambda x: x['date'])
    if len(rows) < 2:
        return {'available': False, 'source': 'naver_stock_index_api', 'reason': 'insufficient_rows'}
    ret = (rows[-1]['close'] - rows[0]['close']) / rows[0]['close']
    return {
        'available': True,
        'source': 'naver_stock_index_api',
        'symbol': 'KOSDAQ',
        'rows': len(rows),
        'start': rows[0]['date'],
        'end': rows[-1]['date'],
        'start_close': str(rows[0]['close']),
        'end_close': str(rows[-1]['close']),
        'return': float(ret),
    }


def kosdaq_index_baseline(args, observed_start: str, observed_end: str) -> dict:
    csv_result = load_index_csv(args.kosdaq_index_csv)
    if csv_result.get('available') or args.kosdaq_index_csv:
        return csv_result
    if args.fetch_naver_kosdaq:
        return fetch_naver_kosdaq_index(args.start or observed_start, args.end or observed_end)
    return csv_result


def run(args) -> dict:
    symbols = cached_symbols(args.source_db)
    rows = []
    skipped = 0
    for sym in symbols:
        row = first_last_close(args.source_db, sym, start=args.start, end=args.end)
        if not row or row['bars'] < args.min_bars:
            skipped += 1
            continue
        rows.append(row)
    dates = sorted({r['start_timestamp'] for r in rows} | {r['end_timestamp'] for r in rows})
    observed_start = dates[0] if dates else ''
    observed_end = dates[-1] if dates else ''
    report = {
        'mode': 'research_baseline_no_send',
        'source_db': args.source_db,
        'window': {
            'requested_start': args.start or None,
            'requested_end': args.end or None,
            'observed_min_max_timestamp': [observed_start or None, observed_end or None],
        },
        'cash_baseline': {'return': 0.0},
        'kosdaq_index_baseline': kosdaq_index_baseline(args, observed_start, observed_end),
        'equal_weight_universe_buy_hold': summarize_returns(rows),
        'skipped_symbols': skipped,
        'notes': [
            'KOSDAQ index baseline is fail-closed unless --kosdaq-index-csv is supplied.',
            'Equal-weight universe baseline uses local candle_cache symbols and is not a cap-weighted index.',
        ],
    }
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    return report


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--source-db', default='data/edge_research_universe_long.sqlite3')
    ap.add_argument('--start', default='')
    ap.add_argument('--end', default='')
    ap.add_argument('--min-bars', type=int, default=200)
    ap.add_argument('--kosdaq-index-csv', default='')
    ap.add_argument('--fetch-naver-kosdaq', action='store_true', help='Fetch KOSDAQ index candles from Naver Stock API when no CSV is supplied')
    ap.add_argument('--out', default='data/market_baseline_latest.json')
    args = ap.parse_args()
    report = run(args)
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
