#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
import urllib.parse
import urllib.request
from pathlib import Path


def top_symbols_by_trade_value(db_path: str, limit: int) -> list[dict]:
    con = sqlite3.connect(db_path)
    try:
        rows = con.execute(
            """
            WITH ranked AS (
              SELECT symbol, timestamp,
                     CAST(close_price AS REAL) AS close_price,
                     CAST(volume AS REAL) AS volume,
                     ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY timestamp DESC) AS rn
              FROM candle_cache
              WHERE interval='1d' AND close_price IS NOT NULL AND volume IS NOT NULL
            )
            SELECT symbol, AVG(close_price * volume) AS avg_trade_value, COUNT(*) AS recent_bars
            FROM ranked
            WHERE rn <= 60
            GROUP BY symbol
            HAVING recent_bars >= 40
            ORDER BY avg_trade_value DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    finally:
        con.close()
    return [
        {'symbol': str(symbol), 'avg_trade_value_60d': avg_trade_value, 'recent_bars': recent_bars}
        for symbol, avg_trade_value, recent_bars in rows
    ]


def load_symbols(args) -> list[dict]:
    rows: list[dict] = []
    if args.symbols:
        for sym in args.symbols.split(','):
            sym = sym.strip()
            if sym:
                rows.append({'symbol': sym, 'source': 'explicit'})
    if args.symbols_file:
        for line in Path(args.symbols_file).read_text().splitlines():
            sym = line.strip()
            if sym:
                rows.append({'symbol': sym, 'source': f'file:{args.symbols_file}'})
    if args.top_by_trade_value:
        rows.extend(top_symbols_by_trade_value(args.db_path, args.top_by_trade_value))
    seen = set()
    out = []
    for row in rows:
        sym = row['symbol']
        if sym not in seen:
            seen.add(sym)
            out.append(row)
    return out


def export_symbol(db_path: str, symbol: str, out_dir: Path, *, start: str = '', end: str = '') -> dict:
    where = ["interval='1d'", 'symbol=?']
    params: list = [symbol]
    if start:
        where.append('timestamp >= ?')
        params.append(start)
    if end:
        where.append('timestamp <= ?')
        params.append(end)
    sql = f"""
        SELECT timestamp, open_price, high_price, low_price, close_price, volume
        FROM candle_cache
        WHERE {' AND '.join(where)}
        ORDER BY timestamp ASC
    """
    con = sqlite3.connect(db_path)
    try:
        rows = con.execute(sql, params).fetchall()
    finally:
        con.close()
    out_path = out_dir / f'{symbol}.csv'
    written = 0
    with out_path.open('w') as f:
        f.write('date,open,high,low,close,volume\n')
        for ts, op, hi, lo, cl, vol in rows:
            vals = [op, hi, lo, cl]
            if any(v is None for v in vals):
                continue
            try:
                nums = [float(v) for v in vals]
                volume = float(vol or 0)
            except Exception:
                continue
            if any(v <= 0 for v in nums):
                continue
            f.write(f'{str(ts)[:10]},{nums[0]},{nums[1]},{nums[2]},{nums[3]},{volume}\n')
            written += 1
    return {'symbol': symbol, 'path': str(out_path), 'rows': written}


def fetch_kosdaq_index(out_dir: Path, *, start_yyyymmdd: str, end_yyyymmdd: str) -> dict:
    query = urllib.parse.urlencode({
        'startDateTime': f'{start_yyyymmdd}0000',
        'endDateTime': f'{end_yyyymmdd}0000',
    })
    url = f'https://api.stock.naver.com/chart/domestic/index/KOSDAQ/day?{query}'
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0', 'Referer': 'https://finance.naver.com/'})
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read().decode('utf-8'))
    out_path = out_dir / 'KOSDAQ_INDEX.csv'
    with out_path.open('w') as f:
        f.write('date,open,high,low,close,volume\n')
        written = 0
        for r in data:
            date = str(r.get('localDate') or '')
            if not date:
                continue
            date_fmt = f'{date[:4]}-{date[4:6]}-{date[6:8]}'
            f.write(','.join([
                date_fmt,
                str(float(r['openPrice'])),
                str(float(r['highPrice'])),
                str(float(r['lowPrice'])),
                str(float(r['closePrice'])),
                str(float(r.get('accumulatedTradingVolume') or 0)),
            ]) + '\n')
            written += 1
    return {'symbol': 'KOSDAQ_INDEX', 'path': str(out_path), 'rows': written, 'source': 'naver_stock_index_api'}


def yyyymmdd(date_s: str, default: str) -> str:
    if not date_s:
        return default
    s = date_s[:10].replace('-', '')
    return s if len(s) == 8 else default


def main() -> int:
    ap = argparse.ArgumentParser(description='Export local Toss candle_cache rows to ai-trader-compatible OHLCV CSV files.')
    ap.add_argument('--db-path', default='data/edge_research_universe_long.sqlite3')
    ap.add_argument('--symbols', default='', help='Comma-separated symbols')
    ap.add_argument('--symbols-file', default='')
    ap.add_argument('--top-by-trade-value', type=int, default=0, help='Export top N symbols by recent 60d traded value')
    ap.add_argument('--out-dir', default='data/ai_trader_export')
    ap.add_argument('--start', default='')
    ap.add_argument('--end', default='')
    ap.add_argument('--fetch-kosdaq-index', action='store_true')
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    exported = []
    if args.fetch_kosdaq_index:
        exported.append(fetch_kosdaq_index(
            out_dir,
            start_yyyymmdd=yyyymmdd(args.start, '20201007'),
            end_yyyymmdd=yyyymmdd(args.end, '20260624'),
        ))
    for row in load_symbols(args):
        exported.append(export_symbol(args.db_path, row['symbol'], out_dir, start=args.start, end=args.end) | {'source': row.get('source')})
    report = {
        'mode': 'external_ai_trader_csv_export_no_send',
        'db_path': args.db_path,
        'out_dir': str(out_dir),
        'start': args.start or None,
        'end': args.end or None,
        'exports': exported,
        'example_commands': [
            f'ai-trader quick RiskAverseStrategy {item["path"]} --cash 1000000 --commission 0.0004'
            for item in exported[:5]
        ],
        'license_note': 'ai-trader is GPL-3.0; keep it as an external optional tool unless project licensing is reviewed.',
    }
    (out_dir / 'export_report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
