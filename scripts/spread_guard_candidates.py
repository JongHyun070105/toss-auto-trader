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

from toss_auto_trader.orderbook_utils import best_spread_from_orderbook, market_impact_from_orderbook, timestamp_staleness
from toss_auto_trader.config import Settings
from toss_auto_trader.toss_client import TossInvestClient


def pair_cash_map(pair: str) -> dict[str, Decimal]:
    out = {}
    for part in str(pair).split('+'):
        if ':' in part:
            sym, cash = part.split(':', 1)
            out[sym.strip()] = Decimal(str(cash.strip()))
    return out


def scale_cash_map(cash: dict[str, Decimal], capital: Decimal) -> dict[str, Decimal]:
    base = sum(cash.values()) or Decimal('1')
    return {sym: (capital * amount / base) for sym, amount in cash.items()}


def unique_symbols(candidates: list[dict], limit: int) -> list[str]:
    out: list[str] = []
    for c in candidates[:limit]:
        for s in c.get('symbols') or []:
            if s not in out:
                out.append(s)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--path', default='data/live_paper_candidates.json')
    ap.add_argument('--max-spread-bps', default=os.getenv('MAX_SPREAD_BPS', '30'))
    ap.add_argument('--candidate-limit', type=int, default=10)
    ap.add_argument('--history', default='data/spread_history.jsonl')
    ap.add_argument('--history-window', type=int, default=5)
    ap.add_argument('--market-impact-levels', type=int, default=5)
    ap.add_argument('--max-impact-bps', default=os.getenv('MAX_IMPACT_BPS', '30'))
    ap.add_argument('--max-stale-ms', type=int, default=int(os.getenv('MAX_STALE_MS', '500')))
    ap.add_argument('--enforce-stale', action='store_true')
    ap.add_argument('--impact-capitals', default='10000,100000,1000000')
    args = ap.parse_args()

    path = Path(args.path)
    data = json.loads(path.read_text())
    threshold = Decimal(str(args.max_spread_bps))
    impact_threshold = Decimal(str(args.max_impact_bps))
    candidates = data.get('candidates', [])
    symbols = unique_symbols(candidates, args.candidate_limit)
    settings = Settings.from_env()
    client = TossInvestClient(settings)
    spreads: dict[str, dict] = {}
    payloads: dict[str, dict] = {}
    for symbol in symbols:
        try:
            payload = client.get_orderbook(symbol)
            payloads[symbol] = payload
            spread = best_spread_from_orderbook(payload)
            spread['staleness'] = timestamp_staleness(payload, max_stale_ms=args.max_stale_ms)
            if spread.get('available'):
                spread['ok'] = Decimal(str(spread['spread_bps'])) <= threshold
            spreads[symbol] = spread
        except Exception as exc:
            spreads[symbol] = {'available': False, 'ok': False, 'error': str(exc)[:300]}

    hist_path = Path(args.history)
    hist_path.parent.mkdir(parents=True, exist_ok=True)
    with open(hist_path, 'a') as f:
        for sym, spread in spreads.items():
            f.write(json.dumps({'observed_at': datetime.now(timezone.utc).isoformat(), 'symbol': sym, 'spread': spread}, ensure_ascii=False, default=str) + '\n')

    history: dict[str, list[Decimal]] = {}
    if hist_path.exists():
        for line in hist_path.read_text().splitlines():
            try:
                row = json.loads(line)
                sp = row.get('spread', {})
                if sp.get('available') and sp.get('spread_bps') is not None:
                    history.setdefault(row.get('symbol'), []).append(Decimal(str(sp['spread_bps'])))
            except Exception:
                continue

    for c in candidates:
        c_spreads = {s: spreads.get(s, {'available': False, 'ok': False}) for s in c.get('symbols', [])}
        cash_by_symbol = pair_cash_map(c.get('pair', ''))
        max_seen = None
        max_impact = None
        ok = True
        hist_stats = {}
        impact_stats = {}
        for s, sp in c_spreads.items():
            vals = history.get(s, [])[-args.history_window:]
            avg_seen = (sum(vals) / Decimal(len(vals))) if vals else None
            max_hist = max(vals) if vals else None
            hist_stats[s] = {'n': len(vals), 'avg_spread_bps': str(avg_seen) if avg_seen is not None else None, 'max_spread_bps': str(max_hist) if max_hist is not None else None}
            if not sp.get('available') or not sp.get('ok'):
                ok = False
            if args.enforce_stale and sp.get('staleness') and not sp['staleness'].get('ok'):
                ok = False
            if max_hist is not None and max_hist > threshold:
                ok = False
            if sp.get('available'):
                val = Decimal(str(sp['spread_bps']))
                max_seen = val if max_seen is None else max(max_seen, val)
            if s in payloads:
                impact = market_impact_from_orderbook(payloads[s], buy_cash_krw=cash_by_symbol.get(s, Decimal('0')), levels=args.market_impact_levels)
                impact_stats[s] = impact
                if impact.get('available'):
                    imp = Decimal(str(impact.get('impact_bps', '0')))
                    max_impact = imp if max_impact is None else max(max_impact, imp)
                    if imp > impact_threshold or not impact.get('full_fill_within_levels'):
                        ok = False
        capital_impact = {}
        for cap_raw in [x.strip() for x in args.impact_capitals.split(',') if x.strip()]:
            cap = Decimal(cap_raw)
            scaled = scale_cash_map(cash_by_symbol, cap)
            cap_impacts = {}
            cap_max = None
            for sym, cash_amt in scaled.items():
                if sym in payloads:
                    imp_row = market_impact_from_orderbook(payloads[sym], buy_cash_krw=cash_amt, levels=args.market_impact_levels)
                    cap_impacts[sym] = imp_row
                    if imp_row.get('available'):
                        val = Decimal(str(imp_row.get('impact_bps', '0')))
                        cap_max = val if cap_max is None else max(cap_max, val)
            capital_impact[str(cap)] = {'max_impact_bps': str(cap_max) if cap_max is not None else None, 'symbols': cap_impacts}
        c['spread_guard'] = {
            'max_spread_bps_allowed': str(threshold),
            'max_spread_bps_seen': str(max_seen) if max_seen is not None else None,
            'history_window': args.history_window,
            'history': hist_stats,
            'market_impact_levels': args.market_impact_levels,
            'max_impact_bps_allowed': str(impact_threshold),
            'max_impact_bps_seen': str(max_impact) if max_impact is not None else None,
            'impact': impact_stats,
            'capital_impact': capital_impact,
            'symbols': c_spreads,
            'ok': ok,
        }
        if not ok:
            c['status'] = 'blocked_spread_or_orderbook_unavailable'
        else:
            c['status'] = 'spread_checked_watchlist_not_live_order'

    data['spread_guard_updated'] = True
    data['spread_guard_threshold_bps'] = str(threshold)
    data['live_order_allowed'] = False
    data['manual_approval_required'] = True
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    print(json.dumps({'updated': str(path), 'threshold_bps': str(threshold), 'spreads': spreads, 'top_status': [c.get('status') for c in candidates[:3]]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
