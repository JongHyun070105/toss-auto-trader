#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from toss_auto_trader import db
from toss_auto_trader.cli import branch_config, load_bot_config
from toss_auto_trader.market import kr_event_day_flags, kr_observation_window_guard
from toss_auto_trader.orderbook_utils import best_spread_from_orderbook, market_impact_from_orderbook, timestamp_staleness
from toss_auto_trader.config import Settings
from toss_auto_trader.decision_engine import evaluate_symbol_from_candles
from toss_auto_trader.toss_client import TossApiError, TossInvestClient


def classify_error(exc: Exception) -> str:
    text = str(exc).lower()
    if isinstance(exc, TossApiError):
        if exc.status == 401 or 'invalid-token' in text or 'unauthorized' in text:
            return 'token_invalid_or_unauthorized'
        if exc.status == 429:
            return 'rate_limited'
        if exc.status == 0:
            return 'network_error'
        return f'http_{exc.status}'
    if 'spread' in text:
        return 'spread_unavailable'
    return 'unknown_error'


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--candidates', default='data/live_paper_candidates.json')
    ap.add_argument('--config', default='config.example.yaml')
    ap.add_argument('--out', default='data/paper_observations.jsonl')
    ap.add_argument('--limit', type=int, default=3)
    ap.add_argument('--count', type=int, default=100)
    ap.add_argument('--interval', default='1d')
    ap.add_argument('--max-spread-bps', default=os.getenv('MAX_SPREAD_BPS', '30'))
    ap.add_argument('--market-impact-levels', type=int, default=5)
    ap.add_argument('--max-impact-bps', default=os.getenv('MAX_IMPACT_BPS', '30'))
    ap.add_argument('--max-stale-ms', type=int, default=int(os.getenv('MAX_STALE_MS', '500')))
    ap.add_argument('--force-time-window', action='store_true', help='debug/smoke only: observe outside 09:05~15:20 KST')
    args = ap.parse_args()

    settings = Settings.from_env()
    db.init_db(settings.db_path)
    client = TossInvestClient(settings)
    cfg_base = load_bot_config(args.config)
    data = json.loads(Path(args.candidates).read_text())
    threshold = Decimal(str(args.max_spread_bps))
    impact_threshold = Decimal(str(args.max_impact_bps))
    time_guard = kr_observation_window_guard()
    event_guard = kr_event_day_flags()
    latest_guard = {'time_window_guard': time_guard, 'event_day_guard': event_guard}
    Path('data/time_window_guard_latest.json').write_text(json.dumps(latest_guard, ensure_ascii=False, indent=2))
    if not args.force_time_window and not time_guard.get('ok'):
        print(json.dumps({'written': 0, 'out': args.out, 'skipped': True, 'reason': time_guard.get('reason'), 'time_window_guard': time_guard}, ensure_ascii=False, indent=2))
        return 0
    rows = []
    for cand in data.get('candidates', [])[:args.limit]:
        if cand.get('source') != 'walk_forward' or not cand.get('stable_positive'):
            continue
        branch = cand.get('branch', 'balanced_momentum')
        cfg = branch_config(cfg_base, branch)
        obs = {
            'observed_at': datetime.now(timezone.utc).isoformat(),
            'candidate': cand,
            'symbols': {},
            'paper_only': True,
            'order_sent': False,
            'time_window_guard': time_guard,
            'event_day_guard': event_guard,
        }
        block_reasons = []
        block_details = []
        for symbol in cand.get('symbols', []):
            payload = None
            try:
                payload = client.get_orderbook(symbol)
                spread = best_spread_from_orderbook(payload)
                spread['staleness'] = timestamp_staleness(payload, max_stale_ms=args.max_stale_ms)
            except Exception as exc:
                kind = classify_error(exc)
                spread = {'available': False, 'ok': False, 'error_kind': kind, 'error': str(exc)[:300]}
            if not spread.get('available'):
                block_reasons.append(f'spread_unavailable:{symbol}:{spread.get("error_kind", "unknown_error")}')
                block_details.append({'symbol': symbol, 'kind': spread.get('error_kind', 'spread_unavailable'), 'stage': 'orderbook'})
            elif Decimal(str(spread.get('spread_bps', '999999'))) > threshold:
                block_reasons.append(f'spread_too_wide:{symbol}:{spread.get("spread_bps")}')
                block_details.append({'symbol': symbol, 'kind': 'spread_too_wide', 'stage': 'orderbook', 'spread_bps': str(spread.get('spread_bps'))})
            if spread.get('staleness') and not spread['staleness'].get('ok'):
                block_reasons.append(f'stale_orderbook:{symbol}:{spread["staleness"].get("stale_ms")}ms')
                block_details.append({'symbol': symbol, 'kind': 'stale_orderbook', 'stage': 'orderbook', 'stale_ms': spread['staleness'].get('stale_ms')})
            if payload is not None:
                cash_map = {p.split(':', 1)[0]: Decimal(p.split(':', 1)[1]) for p in cand.get('pair', '').split('+') if ':' in p}
                impact = market_impact_from_orderbook(payload, buy_cash_krw=cash_map.get(symbol, Decimal('0')), levels=args.market_impact_levels)
                spread['market_impact'] = impact
                if impact.get('available'):
                    imp = Decimal(str(impact.get('impact_bps', '0')))
                    if imp > impact_threshold or not impact.get('full_fill_within_levels'):
                        block_reasons.append(f'market_impact:{symbol}:{impact.get("impact_bps")}')
                        block_details.append({'symbol': symbol, 'kind': 'market_impact', 'stage': 'orderbook', 'impact_bps': str(impact.get('impact_bps'))})
            try:
                candles = client.get_candles(symbol, args.interval, args.count).get('result', {}).get('candles', [])
            except Exception as exc:
                candles = []
                kind = classify_error(exc)
                spread.setdefault('market_data_error_kind', kind)
                spread.setdefault('market_data_error', str(exc)[:300])
                block_details.append({'symbol': symbol, 'kind': kind, 'stage': 'candles'})
            decision = evaluate_symbol_from_candles(settings.db_path, symbol, candles, cfg, Decimal('0')) if candles else {'side': 'HOLD', 'reason': 'no live candles'}
            obs['symbols'][symbol] = {'spread': spread, 'decision': decision}
        obs['status'] = 'blocked_observe_only' if block_reasons else 'observed_watchlist_not_live_order'
        obs['block_reasons'] = block_reasons
        obs['block_details'] = block_details
        obs['failure_summary'] = {k: sum(1 for d in block_details if d.get('kind') == k) for k in sorted({d.get('kind') for d in block_details})}
        rows.append(obs)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, 'a') as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, default=str) + '\n')
    print(json.dumps({'written': len(rows), 'out': args.out, 'statuses': [r['status'] for r in rows]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
