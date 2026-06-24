#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import os
import sqlite3
import sys
import tempfile
from decimal import Decimal
from pathlib import Path
from statistics import mean

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from toss_auto_trader import db
from toss_auto_trader.cli import branch_config, load_bot_config
from toss_auto_trader.decision_engine import evaluate_symbol_from_candles, fee_roundtrip_pct


def cached_candles_readonly(db_path: str, symbol: str, limit: int | None = None) -> list[dict]:
    if not Path(db_path).exists():
        return []
    con = sqlite3.connect(f'file:{db_path}?mode=ro', uri=True)
    con.row_factory = sqlite3.Row
    try:
        sql = "SELECT timestamp, open_price, high_price, low_price, close_price, volume, currency FROM candle_cache WHERE symbol=? AND interval='1d' ORDER BY timestamp ASC"
        params: list = [symbol]
        if limit:
            sql += " LIMIT ?"
            params.append(limit)
        rows = con.execute(sql, params).fetchall()
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


def parse_pair(pair: str) -> list[str]:
    return [p.split(':', 1)[0] for p in pair.split('+') if ':' in p]


def closes_by_ts(candles: list[dict]) -> dict[str, Decimal]:
    return {c['timestamp']: Decimal(str(c['closePrice'])) for c in candles if c.get('closePrice') is not None}


def returns_for(candles: list[dict]) -> dict[str, Decimal]:
    out = {}
    prev = None
    for c in candles:
        close = Decimal(str(c['closePrice']))
        if prev and prev > 0:
            out[c['timestamp']] = (close - prev) / prev
        prev = close
    return out


def corr(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 5 or len(ys) < 5 or len(xs) != len(ys):
        return None
    mx, my = mean(xs), mean(ys)
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    denx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    deny = math.sqrt(sum((y - my) ** 2 for y in ys))
    if denx == 0 or deny == 0:
        return None
    return num / (denx * deny)


def pair_correlation(pair: str, candles_by_symbol: dict[str, list[dict]]) -> dict:
    syms = parse_pair(pair)
    if len(syms) != 2:
        return {'available': False, 'reason': 'need_two_symbols'}
    r1, r2 = returns_for(candles_by_symbol.get(syms[0], [])), returns_for(candles_by_symbol.get(syms[1], []))
    common = sorted(set(r1) & set(r2))
    xs = [float(r1[t]) for t in common]
    ys = [float(r2[t]) for t in common]
    c = corr(xs, ys)
    if c is None:
        label = 'insufficient_overlap'
    elif abs(c) < 0.3:
        label = 'independent_long_basket_not_true_pair'
    elif c > 0.7:
        label = 'highly_correlated_long_basket'
    else:
        label = 'moderately_correlated_long_basket'
    return {'available': c is not None, 'symbols': syms, 'overlap_days': len(common), 'return_correlation': c, 'label': label}


def signal_stats(*, db_path: str, symbol: str, candles: list[dict], cfg: dict, window: int, horizon: int, min_signals: int) -> dict:
    buys = []
    holds = 0
    fee = fee_roundtrip_pct(cfg) + Decimal(str(cfg.get('execution', {}).get('buy_slippage_pct', 0))) + Decimal(str(cfg.get('execution', {}).get('sell_slippage_pct', 0)))
    with tempfile.NamedTemporaryFile(suffix='.sqlite3', delete=False) as tf:
        tmp = tf.name
    try:
        db.init_db(tmp)
        for idx in range(window, len(candles) - horizon):
            win = list(reversed(candles[idx - window:idx]))
            entry = Decimal(str(candles[idx - 1]['closePrice']))
            future = Decimal(str(candles[idx + horizon]['closePrice']))
            decision = evaluate_symbol_from_candles(tmp, symbol, win, cfg, Decimal('0'))
            if decision.get('side') == 'BUY' and entry > 0:
                raw = (future - entry) / entry
                net = raw - fee
                buys.append(float(net))
            else:
                holds += 1
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass
    avg_net = mean(buys) if buys else None
    win_rate = (sum(1 for x in buys if x > 0) / len(buys)) if buys else None
    edge_ok = len(buys) >= min_signals and avg_net is not None and avg_net > 0 and win_rate is not None and win_rate >= 0.5
    return {
        'symbol': symbol,
        'window': window,
        'horizon': horizon,
        'buy_signals': len(buys),
        'hold_signals': holds,
        'avg_net_return_after_cost': avg_net,
        'win_rate_after_cost': win_rate,
        'min_signals': min_signals,
        'edge_ok': edge_ok,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--source-db', default='data/low_kr_backtest.sqlite3')
    ap.add_argument('--candidates', default='data/live_paper_candidates.json')
    ap.add_argument('--config', default='config.example.yaml')
    ap.add_argument('--out', default='data/strategy_edge_audit_latest.json')
    ap.add_argument('--limit', type=int, default=10)
    ap.add_argument('--min-signals', type=int, default=5)
    args = ap.parse_args()

    cand_data = json.loads(Path(args.candidates).read_text()) if Path(args.candidates).exists() else {'candidates': []}
    candidates = cand_data.get('candidates', [])[:args.limit]
    symbols = sorted({s for c in candidates for s in c.get('symbols', [])})
    candles = {s: cached_candles_readonly(args.source_db, s) for s in symbols}
    base_cfg = load_bot_config(args.config)
    symbol_stats = []
    candidate_edges = []
    for c in candidates:
        cfg = branch_config(base_cfg, c.get('branch', 'balanced_momentum'))
        per_symbol = [signal_stats(db_path=args.source_db, symbol=s, candles=candles.get(s, []), cfg=cfg, window=int(c.get('window') or 40), horizon=int(c.get('horizon') or 1), min_signals=args.min_signals) for s in c.get('symbols', [])]
        symbol_stats.extend(per_symbol)
        total_buys = sum(x['buy_signals'] for x in per_symbol)
        valid_symbols = sum(1 for x in per_symbol if x['edge_ok'])
        avg_net_values = [x['avg_net_return_after_cost'] for x in per_symbol if x['avg_net_return_after_cost'] is not None]
        pc = pair_correlation(c.get('pair', ''), candles)
        # These candidates are long-only baskets, not hedge/coint pairs. Require every leg to
        # show its own post-cost edge; otherwise one weak leg can hide behind the other.
        all_legs_edge_ok = len(per_symbol) > 0 and valid_symbols == len(per_symbol)
        avg_net = mean(avg_net_values) if avg_net_values else None
        candidate_edges.append({
            'pair': c.get('pair'),
            'branch': c.get('branch'),
            'window': c.get('window'),
            'horizon': c.get('horizon'),
            'mode': c.get('mode'),
            'total_buy_signals': total_buys,
            'valid_symbol_edges': valid_symbols,
            'symbol_count': len(per_symbol),
            'avg_symbol_net_return_after_cost': avg_net,
            'edge_ok': total_buys >= args.min_signals and all_legs_edge_ok and avg_net is not None and avg_net > 0,
            'edge_status': 'all_legs_edge_ok' if all_legs_edge_ok else 'partial_or_missing_leg_edge',
            'symbols': per_symbol,
            'pair_correlation': pc,
        })
    current_hypothesis = {
        'name': 'weak_momentum_continuation_with_risk_news_veto',
        'buy_logic_from_code': [
            'technical_analyst: MA bullish alignment adds score; RSI 35~70 adds score; RSI overheat can block',
            'coordinator: BUY only when technical/performance/news do not HOLD and average opinion score/confidence exceed branch thresholds',
            'risk_manager/fee_analyst mostly allow/risk-parameter providers, not standalone alpha',
        ],
        'edge_warning': 'This is a generic momentum/technical continuation hypothesis, not yet a proven market inefficiency. Edge audit must pass before pre-live promotion.',
    }
    report = {
        'current_hypothesis': current_hypothesis,
        'min_signals': args.min_signals,
        'candidate_edges': candidate_edges,
        'symbol_stats': symbol_stats,
        'summary': {
            'candidate_count': len(candidate_edges),
            'edge_ok_count': sum(1 for x in candidate_edges if x['edge_ok']),
            'note': 'Edge_ok is necessary but not sufficient; it checks signal count and post-cost forward returns, not causal proof.',
        },
    }
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
