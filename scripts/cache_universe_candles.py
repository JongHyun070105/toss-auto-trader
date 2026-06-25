#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
import time
from dataclasses import replace
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from toss_auto_trader import db
from toss_auto_trader.config import Settings
from toss_auto_trader.toss_client import TossApiError, TossInvestClient


def load_symbols(path: str, *, limit: int | None = None, offset: int = 0) -> list[str]:
    symbols = []
    for raw in Path(path).read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        # Accept either one-symbol-per-line or CSV-ish first column.
        sym = line.split(',')[0].strip()
        if sym:
            symbols.append(sym)
    symbols = symbols[offset:]
    return symbols[:limit] if limit else symbols


def cached_candle_count(db_path: str, symbol: str, interval: str) -> int:
    p = Path(db_path)
    if not p.exists():
        return 0
    con = sqlite3.connect(f'file:{db_path}?mode=ro', uri=True)
    try:
        row = con.execute(
            "SELECT COUNT(*) FROM candle_cache WHERE symbol=? AND interval=?",
            (symbol, interval),
        ).fetchone()
        return int(row[0] or 0)
    except sqlite3.Error:
        return 0
    finally:
        con.close()


def write_report(path: str, report: dict) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(report, ensure_ascii=False, indent=2))


def main() -> int:
    ap = argparse.ArgumentParser(description='Rate-limited candle cache for broad universe edge research. Paper/read-only only.')
    ap.add_argument('--symbols-file', required=True, help='One symbol per line, e.g. KOSDAQ universe exported from KRX/Toss/etc.')
    ap.add_argument('--db-path', default='data/edge_research_universe.sqlite3')
    ap.add_argument('--interval', default='1d')
    ap.add_argument('--count', type=int, default=200)
    ap.add_argument('--pages', type=int, default=1)
    ap.add_argument('--sleep-seconds', type=float, default=2.0)
    ap.add_argument('--limit', type=int, default=0)
    ap.add_argument('--offset', type=int, default=0)
    ap.add_argument('--out', default='data/universe_cache_latest.json')
    ap.add_argument('--failed-out', default='data/universe_cache_failed_symbols.txt')
    ap.add_argument('--skip-existing-min-candles', type=int, default=0, help='Skip symbols that already have at least N cached candles in db-path')
    args = ap.parse_args()

    settings = replace(Settings.from_env(), db_path=args.db_path, dry_run=True, live_trading=False)
    db.init_db(args.db_path)
    client = TossInvestClient(settings)
    symbols = load_symbols(args.symbols_file, limit=args.limit or None, offset=args.offset)
    rows = []
    report = {
        'symbols_file': args.symbols_file,
        'db_path': args.db_path,
        'interval': args.interval,
        'count': args.count,
        'pages': args.pages,
        'requested_symbols': len(symbols),
        'ok_count': 0,
        'skipped_existing_count': 0,
        'failed_count': 0,
        'rows': rows,
        'note': 'Use this to build a broad KOSDAQ/universe cache before trusting any volume-shock edge audit.',
    }
    for idx, symbol in enumerate(symbols, start=1):
        existing = cached_candle_count(args.db_path, symbol, args.interval)
        if args.skip_existing_min_candles and existing >= args.skip_existing_min_candles:
            rows.append({
                'index': idx + args.offset,
                'symbol': symbol,
                'status': 'skipped_existing',
                'existing_candles': existing,
                'inserted_or_replaced': 0,
                'pages': [],
                'error': None,
            })
            report['skipped_existing_count'] = sum(1 for r in rows if r['status'] == 'skipped_existing')
            write_report(args.out, report)
            continue
        before = None
        inserted_total = 0
        status = 'ok'
        error = None
        pages = []
        try:
            for page in range(args.pages):
                resp = client.get_candles(symbol, args.interval, min(args.count, 200), before=before)
                result = resp.get('result', {})
                candles = result.get('candles', [])
                inserted = db.insert_candles(args.db_path, symbol, args.interval, candles)
                inserted_total += inserted
                before = result.get('nextBefore')
                pages.append({'page': page + 1, 'fetched': len(candles), 'inserted_or_replaced': inserted, 'nextBefore': before})
                if not candles or not before:
                    break
                time.sleep(max(0, args.sleep_seconds))
        except TossApiError as e:
            status = 'api_error'
            error = {'status': e.status, 'message': str(e)[:500]}
        except Exception as e:
            status = 'error'
            error = {'message': str(e)[:500]}
        rows.append({'index': idx + args.offset, 'symbol': symbol, 'status': status, 'existing_candles_before': existing, 'inserted_or_replaced': inserted_total, 'pages': pages, 'error': error})
        report['ok_count'] = sum(1 for r in rows if r['status'] == 'ok')
        report['failed_count'] = sum(1 for r in rows if r['status'] not in {'ok', 'skipped_existing'})
        write_report(args.out, report)
        time.sleep(max(0, args.sleep_seconds))
    failed = [r['symbol'] for r in rows if r['status'] not in {'ok', 'skipped_existing'}]
    Path(args.failed_out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.failed_out).write_text('\n'.join(failed) + ('\n' if failed else ''))
    report['ok_count'] = sum(1 for r in rows if r['status'] == 'ok')
    report['skipped_existing_count'] = sum(1 for r in rows if r['status'] == 'skipped_existing')
    report['failed_count'] = len(failed)
    write_report(args.out, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
