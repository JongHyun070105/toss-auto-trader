#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from rsi_bbands_mean_reversion_audit import (  # noqa: E402
    cached_candles_readonly,
    fetch_kosdaq_index,
    market_guard_map,
    signal_meta,
)
from volume_shock_hypothesis_audit import load_symbols  # noqa: E402

KST = ZoneInfo('Asia/Seoul')


def load_seen_signal_ids(path: Path) -> set[str]:
    if not path.exists():
        return set()
    out: set[str] = set()
    for line in path.read_text().splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        sid = row.get('signal_id')
        if sid:
            out.add(str(sid))
    return out


def latest_market_date(index_rows: list[dict]) -> str:
    return index_rows[-1]['timestamp'] if index_rows else ''


def build_signal_args(args: argparse.Namespace) -> argparse.Namespace:
    return argparse.Namespace(
        rsi_period=args.rsi_period,
        bb_period=args.bb_period,
        bb_dev=args.bb_dev,
        min_bb_z=args.min_bb_z,
        oversold=args.oversold,
        volume_lookback=args.volume_lookback,
        max_volume_multiple=args.max_volume_multiple,
        min_close_price=args.min_close_price,
        min_price_history=args.min_price_history,
    )


def scan(args: argparse.Namespace) -> dict:
    observed_at = datetime.now(KST).isoformat()
    index_rows = fetch_kosdaq_index(args.index_start, args.index_end)
    market = market_guard_map(
        index_rows,
        min_20d_return=args.market_min_20d_return_dec,
        max_ann_vol=args.market_max_ann_vol_dec,
    )
    symbols = load_symbols(argparse.Namespace(symbols=args.symbols, symbols_file=args.symbols_file, source_db=args.source_db))
    signal_args = build_signal_args(args)
    seen = load_seen_signal_ids(Path(args.ledger))
    candidates = []
    skipped = {'no_candles': 0, 'insufficient_history': 0, 'no_signal': 0, 'duplicate': 0}

    for symbol in symbols:
        candles = cached_candles_readonly(args.source_db, symbol)
        if not candles:
            skipped['no_candles'] += 1
            continue
        i = len(candles) - 1
        if i < args.min_price_history:
            skipped['insufficient_history'] += 1
            continue
        ok, meta = signal_meta(candles, i, market, signal_args)
        if not ok:
            skipped['no_signal'] += 1
            continue
        signal_date = candles[i]['timestamp']
        signal_id = f'{args.hypothesis_id}:{symbol}:{signal_date}'
        if signal_id in seen:
            skipped['duplicate'] += 1
            continue
        row = {
            'signal_id': signal_id,
            'observed_at_kst': observed_at,
            'mode': 'paper_only_forward_observation_no_send',
            'hypothesis_id': args.hypothesis_id,
            'hypothesis_status': 'post_hoc_guard_candidate_requires_future_holdout',
            'symbol': symbol,
            'signal_date': signal_date,
            'signal_close': float(candles[i]['close_price']),
            'paper_only': True,
            'order_sent': False,
            'live_order_allowed': False,
            'status': 'forward_watch_candidate_not_live_order',
            'next_step': 'observe_future_outcome_after_horizon_without_sending_order',
            'horizon_days': args.horizon,
            'entry_plan': 'next_trading_day_open_for_paper_label_only',
            'risk_note': 'same-history V3 did not pass train gates; this is only forward evidence collection',
            'features': meta,
            'market_latest_date': latest_market_date(index_rows),
        }
        candidates.append(row)
        if len(candidates) >= args.limit:
            break
    return {
        'observed_at_kst': observed_at,
        'mode': 'paper_only_forward_observation_no_send',
        'live_order_allowed': False,
        'hypothesis_id': args.hypothesis_id,
        'source_db': args.source_db,
        'symbols_scanned': len(symbols),
        'candidates': candidates,
        'candidate_count': len(candidates),
        'skipped': skipped,
        'market_latest_date': latest_market_date(index_rows),
        'manual_approval_required': True,
    }


def append_ledger(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a') as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, default=str) + '\n')


def main() -> int:
    ap = argparse.ArgumentParser(description='Scan latest cached candles for RSI+Bollinger V3 forward watch candidates. No orders are sent.')
    ap.add_argument('--source-db', default='data/edge_research_universe_long.sqlite3')
    ap.add_argument('--symbols', default='cached')
    ap.add_argument('--symbols-file', default='')
    ap.add_argument('--out', default='data/rsi_bbands_v3_forward_candidates_latest.json')
    ap.add_argument('--ledger', default='data/rsi_bbands_v3_forward_observations.jsonl')
    ap.add_argument('--limit', type=int, default=50)
    ap.add_argument('--hypothesis-id', default='RSI_BBANDS_MEAN_REVERSION_H20_V3_BBZ_VOLUME_GUARD')
    ap.add_argument('--index-start', default='20200101')
    ap.add_argument('--index-end', default='20260625')
    ap.add_argument('--market-min-20d-return', default='-0.12')
    ap.add_argument('--market-max-ann-vol', default='')
    ap.add_argument('--rsi-period', type=int, default=14)
    ap.add_argument('--bb-period', type=int, default=20)
    ap.add_argument('--bb-dev', default='2')
    ap.add_argument('--min-bb-z', default='-2.5')
    ap.add_argument('--oversold', default='30')
    ap.add_argument('--volume-lookback', type=int, default=20)
    ap.add_argument('--max-volume-multiple', default='2.5')
    ap.add_argument('--min-close-price', default='1000')
    ap.add_argument('--min-price-history', type=int, default=60)
    ap.add_argument('--horizon', type=int, default=20)
    args = ap.parse_args()

    from decimal import Decimal
    args.market_min_20d_return_dec = Decimal(args.market_min_20d_return)
    args.market_max_ann_vol_dec = Decimal(args.market_max_ann_vol) if args.market_max_ann_vol else None

    report = scan(args)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    append_ledger(Path(args.ledger), report['candidates'])
    print(json.dumps({
        'out': args.out,
        'ledger': args.ledger,
        'candidate_count': report['candidate_count'],
        'symbols_scanned': report['symbols_scanned'],
        'skipped': report['skipped'],
        'live_order_allowed': False,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
