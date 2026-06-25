#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from decimal import Decimal
from pathlib import Path
from statistics import mean
from typing import Any

from volume_shock_hypothesis_audit import cached_candles_readonly, load_symbols, split_train_test, test_symbol


def pct(x: Any) -> Decimal:
    return Decimal(str(x))


def collect_signals(args) -> list[dict]:
    symbols = load_symbols(args)
    signals: list[dict] = []
    for sym in symbols:
        row = test_symbol(
            cached_candles_readonly(args.source_db, sym),
            symbol=sym,
            vol_mult=Decimal(args.vol_mult),
            lookback=args.lookback,
            horizon=args.horizon,
            cost_pct=Decimal(args.cost_pct),
            strategy=args.strategy,
            market_filter=args.market_filter,
        )
        signals.extend(row['_signals'])
    return sorted(signals, key=lambda s: (str(s.get('entry_timestamp') or s.get('timestamp')), -float(s.get('volume_multiple', 0)), str(s.get('symbol'))))


def simulate_portfolio(signals: list[dict], *, initial_cash: Decimal, max_positions: int, position_fraction: Decimal, max_daily_entries: int) -> dict:
    cash = initial_cash
    positions: list[dict] = []
    closed: list[dict] = []
    rejected: list[dict] = []
    attempted = 0
    peak_equity = initial_cash
    max_drawdown = Decimal('0')

    by_entry: dict[str, list[dict]] = defaultdict(list)
    for sig in signals:
        by_entry[str(sig.get('entry_timestamp') or sig.get('timestamp'))].append(sig)
    timeline = sorted(set(by_entry) | {str(s.get('exit_timestamp')) for s in signals if s.get('exit_timestamp')})

    for day in timeline:
        still_open = []
        for pos in positions:
            if str(pos['exit_timestamp']) <= day:
                exit_value = pos['cash_invested'] * (Decimal('1') + pct(pos['net_return_after_cost']))
                cash += exit_value
                realized = exit_value - pos['cash_invested']
                closed.append({**pos, 'exit_value': float(exit_value), 'realized_pnl': float(realized)})
            else:
                still_open.append(pos)
        positions = still_open

        daily_entries = 0
        for sig in by_entry.get(day, []):
            attempted += 1
            if len(positions) >= max_positions:
                rejected.append({'symbol': sig['symbol'], 'entry_timestamp': day, 'reason': 'max_positions'})
                continue
            if daily_entries >= max_daily_entries:
                rejected.append({'symbol': sig['symbol'], 'entry_timestamp': day, 'reason': 'max_daily_entries'})
                continue
            target_cash = min(initial_cash * position_fraction, cash)
            if target_cash <= 0:
                rejected.append({'symbol': sig['symbol'], 'entry_timestamp': day, 'reason': 'no_cash'})
                continue
            cash -= target_cash
            daily_entries += 1
            positions.append({
                'symbol': sig['symbol'],
                'signal_timestamp': sig['timestamp'],
                'entry_timestamp': day,
                'exit_timestamp': sig['exit_timestamp'],
                'volume_multiple': sig.get('volume_multiple'),
                'entry_price': sig.get('entry_price'),
                'exit_price': sig.get('exit_price'),
                'net_return_after_cost': sig.get('net_return_after_cost'),
                'cash_invested': target_cash,
            })

        mark_equity = cash + sum(pos['cash_invested'] * (Decimal('1') + pct(pos['net_return_after_cost'])) for pos in positions)
        if mark_equity > peak_equity:
            peak_equity = mark_equity
        if peak_equity > 0:
            dd = (peak_equity - mark_equity) / peak_equity
            if dd > max_drawdown:
                max_drawdown = dd

    # Force close remaining positions at their modeled exit value after the last entry timeline.
    for pos in positions:
        exit_value = pos['cash_invested'] * (Decimal('1') + pct(pos['net_return_after_cost']))
        cash += exit_value
        realized = exit_value - pos['cash_invested']
        closed.append({**pos, 'exit_value': float(exit_value), 'realized_pnl': float(realized), 'forced_close': True})

    pnl = cash - initial_cash
    by_symbol = Counter(p['symbol'] for p in closed)
    pnl_by_symbol: dict[str, float] = defaultdict(float)
    for p in closed:
        pnl_by_symbol[p['symbol']] += float(p['realized_pnl'])
    returns = [float(p['realized_pnl']) / float(p['cash_invested']) for p in closed if float(p['cash_invested']) > 0]
    return {
        'initial_cash': float(initial_cash),
        'final_equity': float(cash),
        'pnl': float(pnl),
        'return_pct': float(pnl / initial_cash) if initial_cash else None,
        'max_drawdown_pct': float(max_drawdown),
        'signals_seen': len(signals),
        'attempted_entries': attempted,
        'filled_entries': len(closed),
        'rejected_entries': len(rejected),
        'avg_trade_return': mean(returns) if returns else None,
        'win_rate': (sum(1 for r in returns if r > 0) / len(returns)) if returns else None,
        'top_symbols_by_trades': by_symbol.most_common(10),
        'top_symbols_by_pnl': sorted(pnl_by_symbol.items(), key=lambda kv: kv[1], reverse=True)[:10],
        'reject_reasons': Counter(r['reason'] for r in rejected),
        'closed_trades_sample': closed[:20],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description='No-send portfolio simulator for locked volume-shock signals.')
    ap.add_argument('--source-db', default='data/edge_research_universe.sqlite3')
    ap.add_argument('--symbols', default='cached')
    ap.add_argument('--symbols-file', default='')
    ap.add_argument('--strategy', default='breakout', choices=['continuation', 'breakout'])
    ap.add_argument('--market-filter', action='store_true')
    ap.add_argument('--vol-mult', default='3')
    ap.add_argument('--lookback', type=int, default=20)
    ap.add_argument('--horizon', type=int, default=3)
    ap.add_argument('--cost-pct', default='0.006')
    ap.add_argument('--train-fraction', default='0.70')
    ap.add_argument('--initial-cash', default='1000000')
    ap.add_argument('--max-positions', type=int, default=5)
    ap.add_argument('--position-fraction', default='0.20')
    ap.add_argument('--max-daily-entries', type=int, default=3)
    ap.add_argument('--out', default='data/volume_shock_portfolio_latest.json')
    args = ap.parse_args()

    all_signals = collect_signals(args)
    train, locked_test = split_train_test(all_signals, Decimal(args.train_fraction))
    sim_args = {
        'initial_cash': Decimal(args.initial_cash),
        'max_positions': args.max_positions,
        'position_fraction': Decimal(args.position_fraction),
        'max_daily_entries': args.max_daily_entries,
    }
    report = {
        'mode': 'research_only_no_send',
        'source_db': args.source_db,
        'signal_definition': f'volume >= {args.vol_mult}x {args.lookback}d avg; positive candle; strategy={args.strategy}; horizon={args.horizon}; cost={args.cost_pct}',
        'portfolio_rules': {
            'initial_cash': args.initial_cash,
            'max_positions': args.max_positions,
            'position_fraction': args.position_fraction,
            'max_daily_entries': args.max_daily_entries,
            'ranking': 'entry day signals sorted by volume_multiple desc, then symbol',
        },
        'all': simulate_portfolio(all_signals, **sim_args),
        'train': simulate_portfolio(train, **sim_args),
        'locked_test': simulate_portfolio(locked_test, **sim_args),
        'note': 'This is a no-send portfolio feasibility simulation. It does not approve live orders.',
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
