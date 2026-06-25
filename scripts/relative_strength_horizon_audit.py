#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import math
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean, median

from market_regime_signal_audit import fetch_kosdaq_index, regime_features


def norm_date(ts: str) -> str:
    return str(ts)[:10]


def safe_float(x) -> float | None:
    try:
        v = float(x)
        if math.isnan(v) or math.isinf(v):
            return None
        return v
    except Exception:
        return None


def pct(a: float, b: float) -> float:
    return (b - a) / a if a and a > 0 else 0.0


def summarize(vals: list[float]) -> dict:
    if not vals:
        return {'n': 0, 'avg': None, 'median': None, 'win_rate': None}
    return {
        'n': len(vals),
        'avg': mean(vals),
        'median': median(vals),
        'win_rate': sum(1 for v in vals if v > 0) / len(vals),
    }


def max_drawdown(curve: list[float]) -> float:
    if not curve:
        return 0.0
    peak = curve[0]
    worst = 0.0
    for v in curve:
        peak = max(peak, v)
        if peak > 0:
            worst = min(worst, v / peak - 1.0)
    return worst


def split_train_test(rows: list[dict], train_fraction: float) -> tuple[list[dict], list[dict]]:
    ordered = sorted(rows, key=lambda r: (r['rebalance_date'], r.get('horizon', 0)))
    if not ordered:
        return [], []
    cut = int(len(ordered) * train_fraction)
    if len(ordered) > 1:
        cut = min(max(cut, 1), len(ordered) - 1)
    return ordered[:cut], ordered[cut:]


def load_candle_map(db_path: str, *, start: str, end: str) -> dict[str, list[dict]]:
    by_symbol: dict[str, list[dict]] = defaultdict(list)
    con = sqlite3.connect(f'file:{db_path}?mode=ro', uri=True)
    cur = None
    try:
        cur = con.execute(
            """
            SELECT symbol, timestamp, open_price, close_price, volume
            FROM candle_cache
            WHERE interval='1d'
              AND substr(timestamp, 1, 10) >= ?
              AND substr(timestamp, 1, 10) <= ?
            ORDER BY symbol, timestamp
            """,
            (start, end),
        )
        for sym, ts, open_p, close_p, volume in cur:
            op = safe_float(open_p)
            cp = safe_float(close_p)
            vol = safe_float(volume)
            if op is None or cp is None or vol is None or op <= 0 or cp <= 0:
                continue
            by_symbol[str(sym)].append({'date': norm_date(ts), 'open': op, 'close': cp, 'volume': vol})
    finally:
        if cur is not None:
            cur.close()
        con.close()
    return {sym: rows for sym, rows in by_symbol.items() if len(rows) >= 140}


def first_trading_day_by_month(index_rows: list[dict]) -> list[str]:
    seen = set()
    out = []
    for row in sorted(index_rows, key=lambda r: r['timestamp']):
        month = row['timestamp'][:7]
        if month not in seen:
            seen.add(month)
            out.append(row['timestamp'])
    return out


def rolling_avg_turnover(rows: list[dict], idx: int, window: int) -> float | None:
    if idx + 1 < window:
        return None
    vals = [rows[j]['close'] * rows[j]['volume'] for j in range(idx - window + 1, idx + 1)]
    return mean(vals) if vals else None


def sma(rows: list[dict], idx: int, window: int) -> float | None:
    if idx + 1 < window:
        return None
    return mean(rows[j]['close'] for j in range(idx - window + 1, idx + 1))


def index_maps(index_rows: list[dict]) -> tuple[dict[str, int], dict[str, float]]:
    return ({r['timestamp']: i for i, r in enumerate(index_rows)}, {r['timestamp']: float(r['close_price']) for r in index_rows})


def build_basket_rows(
    by_symbol: dict[str, list[dict]],
    index_rows: list[dict],
    regimes: dict[str, dict],
    *,
    formation_days: int,
    horizons: list[int],
    top_n: int,
    rebalance_dates: list[str],
    min_price: float,
    min_avg_turnover_20d: float,
    roundtrip_cost_pct: float,
    require_positive_index_60d: bool,
) -> tuple[list[dict], list[dict], dict]:
    idx_by_date, idx_close = index_maps(index_rows)
    signal_rows: list[dict] = []
    basket_rows: list[dict] = []
    skip = Counter()
    symbol_maps: dict[str, dict[str, int]] = {sym: {r['date']: i for i, r in enumerate(rows)} for sym, rows in by_symbol.items()}
    total_eligible_by_date = {}

    for date in rebalance_dates:
        if date not in idx_by_date or idx_by_date[date] < formation_days:
            skip['index_insufficient_formation'] += 1
            continue
        index_ret_formation = pct(float(index_rows[idx_by_date[date] - formation_days]['close_price']), float(index_rows[idx_by_date[date]]['close_price']))
        feats = regimes.get(date, {})
        if require_positive_index_60d and (feats.get('ret_60d') is None or feats.get('ret_60d') <= 0):
            skip['index_60d_not_positive'] += 1
            continue
        candidates: list[dict] = []
        for sym, rows in by_symbol.items():
            pos = symbol_maps[sym].get(date)
            if pos is None:
                skip['symbol_missing_rebalance_candle'] += 1
                continue
            if pos < max(formation_days, 120):
                skip['symbol_insufficient_formation'] += 1
                continue
            if rows[pos]['close'] < min_price:
                skip['price_below_min'] += 1
                continue
            turn = rolling_avg_turnover(rows, pos, 20)
            if turn is None or turn < min_avg_turnover_20d:
                skip['turnover_below_min'] += 1
                continue
            sma120 = sma(rows, pos, 120)
            if sma120 is None:
                skip['sma120_unavailable'] += 1
                continue
            stock_ret = pct(rows[pos - formation_days]['close'], rows[pos]['close'])
            rel_strength = stock_ret - index_ret_formation
            # Frozen V1 quality guard: use relative strength, but require price not below long SMA to avoid pure dead-cat bounces.
            if rows[pos]['close'] < sma120:
                skip['below_sma120'] += 1
                continue
            candidates.append({
                'symbol': sym,
                'rebalance_date': date,
                'score': rel_strength,
                'stock_ret_formation': stock_ret,
                'index_ret_formation': index_ret_formation,
                'avg_turnover_20d': turn,
                'close': rows[pos]['close'],
                'pos': pos,
            })
        total_eligible_by_date[date] = len(candidates)
        if len(candidates) < max(top_n * 3, 50):
            skip['eligible_universe_too_small'] += 1
            continue
        candidates.sort(key=lambda r: r['score'], reverse=True)
        rank_by_symbol = {c['symbol']: rank + 1 for rank, c in enumerate(candidates)}
        top_symbols = {c['symbol'] for c in candidates[:top_n]}

        for horizon in horizons:
            if idx_by_date[date] + horizon >= len(index_rows):
                skip['index_future_horizon_missing'] += 1
                continue
            index_forward = pct(float(index_rows[idx_by_date[date]]['close_price']), float(index_rows[idx_by_date[date] + horizon]['close_price'])) - roundtrip_cost_pct
            per_symbol = []
            top_rets = []
            universe_rets = []
            for c in candidates:
                rows = by_symbol[c['symbol']]
                entry_idx = c['pos'] + 1
                exit_idx = entry_idx + horizon
                if exit_idx >= len(rows):
                    skip['symbol_future_horizon_missing'] += 1
                    continue
                entry = rows[entry_idx]['open']
                exit_p = rows[exit_idx]['close']
                ret = pct(entry, exit_p) - roundtrip_cost_pct
                universe_rets.append(ret)
                is_top = c['symbol'] in top_symbols
                if is_top:
                    top_rets.append(ret)
                row = {
                    'hypothesis_id': 'RELATIVE_STRENGTH_H60_H20_H60_V1',
                    'paper_only': True,
                    'order_sent': False,
                    'live_order_allowed': False,
                    'symbol': c['symbol'],
                    'rebalance_date': date,
                    'entry_date': rows[entry_idx]['date'],
                    'exit_date': rows[exit_idx]['date'],
                    'horizon': horizon,
                    'rank': rank_by_symbol[c['symbol']],
                    'selected_top_n': is_top,
                    'score_rel_strength': c['score'],
                    'stock_ret_formation': c['stock_ret_formation'],
                    'index_ret_formation': c['index_ret_formation'],
                    'avg_turnover_20d': c['avg_turnover_20d'],
                    'net_return_after_cost': ret,
                    'kosdaq_forward_after_cost': index_forward,
                    'excess_vs_kosdaq': ret - index_forward,
                    'regime': feats.get('regime'),
                    'kosdaq_ret_20d': feats.get('ret_20d'),
                    'kosdaq_ret_60d': feats.get('ret_60d'),
                }
                signal_rows.append(row)
                per_symbol.append(row)
            if len(top_rets) < top_n // 2 or len(universe_rets) < max(top_n * 3, 50):
                skip['future_return_sample_too_small'] += 1
                continue
            top_avg = mean(top_rets)
            universe_avg = mean(universe_rets)
            basket_rows.append({
                'hypothesis_id': 'RELATIVE_STRENGTH_H60_H20_H60_V1',
                'paper_only': True,
                'order_sent': False,
                'live_order_allowed': False,
                'rebalance_date': date,
                'horizon': horizon,
                'top_n': top_n,
                'eligible_universe': len(candidates),
                'returned_universe': len(universe_rets),
                'returned_top_n': len(top_rets),
                'top_avg_return_after_cost': top_avg,
                'top_median_return_after_cost': median(top_rets),
                'top_win_rate': sum(1 for v in top_rets if v > 0) / len(top_rets),
                'eligible_universe_avg_return_after_cost': universe_avg,
                'eligible_universe_median_return_after_cost': median(universe_rets),
                'kosdaq_forward_after_cost': index_forward,
                'excess_vs_eligible_universe': top_avg - universe_avg,
                'excess_vs_kosdaq': top_avg - index_forward,
                'regime': feats.get('regime'),
                'top_symbols': ','.join(sorted(top_symbols)),
            })
    meta = {'skip': dict(skip), 'eligible_universe_by_date': total_eligible_by_date}
    return signal_rows, basket_rows, meta


def evaluate_baskets(rows: list[dict], train_fraction: float) -> dict:
    def part_stats(part: list[dict]) -> dict:
        top = [float(r['top_avg_return_after_cost']) for r in part]
        universe = [float(r['eligible_universe_avg_return_after_cost']) for r in part]
        kosdaq = [float(r['kosdaq_forward_after_cost']) for r in part]
        excess_u = [float(r['excess_vs_eligible_universe']) for r in part]
        excess_k = [float(r['excess_vs_kosdaq']) for r in part]
        if not part:
            return {'baskets': 0}
        curve_top = [1.0]
        curve_universe = [1.0]
        curve_kosdaq = [1.0]
        for r in sorted(part, key=lambda x: x['rebalance_date']):
            curve_top.append(curve_top[-1] * max(0.0, 1.0 + float(r['top_avg_return_after_cost'])))
            curve_universe.append(curve_universe[-1] * max(0.0, 1.0 + float(r['eligible_universe_avg_return_after_cost'])))
            curve_kosdaq.append(curve_kosdaq[-1] * max(0.0, 1.0 + float(r['kosdaq_forward_after_cost'])))
        return {
            'baskets': len(part),
            'top': summarize(top),
            'eligible_universe': summarize(universe),
            'kosdaq': summarize(kosdaq),
            'excess_vs_eligible_universe': summarize(excess_u),
            'excess_vs_kosdaq': summarize(excess_k),
            'compounded_top_return': curve_top[-1] - 1.0,
            'compounded_universe_return': curve_universe[-1] - 1.0,
            'compounded_kosdaq_return': curve_kosdaq[-1] - 1.0,
            'top_mdd': max_drawdown(curve_top),
            'universe_mdd': max_drawdown(curve_universe),
            'kosdaq_mdd': max_drawdown(curve_kosdaq),
            'avg_eligible_universe': mean(float(r['eligible_universe']) for r in part),
        }

    by_horizon: dict[str, dict] = {}
    for horizon in sorted({int(r['horizon']) for r in rows}):
        hrows = [r for r in rows if int(r['horizon']) == horizon]
        train, test = split_train_test(hrows, train_fraction)
        by_horizon[f'h{horizon}'] = {'all': part_stats(hrows), 'train': part_stats(train), 'locked_test': part_stats(test)}
    return by_horizon


def concentration(signal_rows: list[dict], basket_rows: list[dict], *, top_n: int) -> dict:
    selected = [r for r in signal_rows if r.get('selected_top_n')]
    sym_counts = Counter(r['symbol'] for r in selected)
    month_counts = Counter(r['rebalance_date'][:7] for r in selected)
    total = len(selected)
    top_symbols = sym_counts.most_common(10)
    return {
        'selected_signals': total,
        'unique_selected_symbols': len(sym_counts),
        'top_symbols': top_symbols,
        'max_symbol_share': (top_symbols[0][1] / total) if total and top_symbols else None,
        'rebalance_months': len(month_counts),
        'max_month_share': (max(month_counts.values()) / total) if total and month_counts else None,
        'expected_signals_per_month': top_n,
        'basket_rows': len(basket_rows),
    }


def blockers(evaluation: dict, conc: dict, *, min_locked_baskets: int) -> list[str]:
    out = ['same_history_diagnostic_requires_future_holdout']
    for h, parts in evaluation.items():
        lt = parts['locked_test']
        if lt.get('baskets', 0) < min_locked_baskets:
            out.append(f'{h}_locked_test_baskets_too_small')
            continue
        if (lt['top']['avg'] is None) or lt['top']['avg'] <= 0:
            out.append(f'{h}_locked_top_avg_not_positive')
        if (lt['excess_vs_eligible_universe']['avg'] is None) or lt['excess_vs_eligible_universe']['avg'] <= 0:
            out.append(f'{h}_locked_not_above_eligible_universe')
        if (lt['excess_vs_kosdaq']['avg'] is None) or lt['excess_vs_kosdaq']['avg'] <= 0:
            out.append(f'{h}_locked_not_above_kosdaq')
        if lt.get('compounded_top_return') is None or lt['compounded_top_return'] <= max(lt.get('compounded_universe_return', -999), lt.get('compounded_kosdaq_return', -999)):
            out.append(f'{h}_locked_compounded_not_best_baseline')
        train = parts['train']
        if train.get('baskets', 0) and ((train['excess_vs_eligible_universe']['avg'] or -999) <= 0 or (train['excess_vs_kosdaq']['avg'] or -999) <= 0):
            out.append(f'{h}_train_excess_not_positive')
    if conc.get('unique_selected_symbols', 0) < 50:
        out.append('selected_symbol_breadth_too_low')
    if conc.get('max_symbol_share') is not None and conc['max_symbol_share'] > 0.05:
        out.append('single_symbol_concentration_too_high')
    out.append('delisted_symbol_universe_bias_unresolved_current_cache_only')
    return sorted(set(out))


def run(args) -> dict:
    index_rows = fetch_kosdaq_index(args.index_start, args.index_end)
    regimes = regime_features(index_rows)
    by_symbol = load_candle_map(args.source_db, start=args.index_start_fmt, end=args.index_end_fmt)
    rebalance_dates = first_trading_day_by_month(index_rows)
    horizons = [int(x) for x in args.horizons.split(',') if x.strip()]
    signals, baskets, meta = build_basket_rows(
        by_symbol,
        index_rows,
        regimes,
        formation_days=int(args.formation_days),
        horizons=horizons,
        top_n=int(args.top_n),
        rebalance_dates=rebalance_dates,
        min_price=float(args.min_price),
        min_avg_turnover_20d=float(args.min_avg_turnover_20d),
        roundtrip_cost_pct=float(args.roundtrip_cost_pct),
        require_positive_index_60d=bool(args.require_positive_index_60d),
    )
    evaluation = evaluate_baskets(baskets, float(args.train_fraction))
    conc = concentration(signals, baskets, top_n=int(args.top_n))
    blks = blockers(evaluation, conc, min_locked_baskets=int(args.min_locked_baskets))
    report = {
        'mode': 'research_only_no_send_relative_strength_horizon_audit',
        'hypothesis_id': args.hypothesis_id,
        'hypothesis_status': 'frozen_question_shift_longer_horizon_requires_future_holdout',
        'paper_only': True,
        'order_sent': False,
        'live_order_allowed': False,
        'premise': 'Change the question from 3d stock prediction to monthly as-of 60d relative-strength baskets evaluated over 20d/60d against eligible universe and KOSDAQ baselines.',
        'source_db': args.source_db,
        'index_source': 'Naver Stock API KOSDAQ day chart',
        'index_rows': len(index_rows),
        'symbols_loaded': len(by_symbol),
        'rebalance_months': len(rebalance_dates),
        'fixed_parameters': {
            'formation_days': int(args.formation_days),
            'horizons': horizons,
            'top_n': int(args.top_n),
            'rebalance': 'first KOSDAQ trading day of each month',
            'entry_model': 'next symbol open after rebalance close signal',
            'exit_model': 'symbol close after horizon trading days from entry',
            'score': 'stock formation return minus KOSDAQ formation return',
            'filters': {
                'min_price': float(args.min_price),
                'min_avg_turnover_20d': float(args.min_avg_turnover_20d),
                'close_must_be_above_sma120': True,
                'require_positive_index_60d': bool(args.require_positive_index_60d),
            },
            'roundtrip_cost_pct': float(args.roundtrip_cost_pct),
            'train_fraction': float(args.train_fraction),
        },
        'evaluation': evaluation,
        'concentration': conc,
        'blockers': blks,
        'edge_ok_same_history_only': blks == ['same_history_diagnostic_requires_future_holdout', 'delisted_symbol_universe_bias_unresolved_current_cache_only'],
        'skip': meta['skip'],
        'data_bias_notes': [
            'Universe is as-of by historical candle/turnover availability and does not use future liquidity, but the local symbol list may omit delisted names.',
            'Top-N basket is compared with the full eligible universe and KOSDAQ baseline; symbol-level winners are diagnostics only.',
        ],
        'policy': {
            'not_live_approval': 'Passing same-history gates would only create a frozen forward-watch candidate, never a live-order approval.',
            'next_if_fail': ['sector/theme/event data collection', 'fundamental/event horizon research', 'do not keep retuning public OHLCV short-horizon rules'],
        },
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    if args.baskets_out:
        Path(args.baskets_out).parent.mkdir(parents=True, exist_ok=True)
        keys = []
        for row in baskets:
            for key in row:
                if key not in keys:
                    keys.append(key)
        with Path(args.baskets_out).open('w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=keys)
            writer.writeheader()
            writer.writerows(baskets)
    if args.signals_out:
        Path(args.signals_out).parent.mkdir(parents=True, exist_ok=True)
        keys = []
        for row in signals:
            for key in row:
                if key not in keys:
                    keys.append(key)
        with Path(args.signals_out).open('w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=keys)
            writer.writeheader()
            writer.writerows(signals)
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description='Frozen no-send 20d/60d relative-strength horizon audit.')
    ap.add_argument('--hypothesis-id', default='RELATIVE_STRENGTH_H60_H20_H60_V1')
    ap.add_argument('--source-db', default='data/edge_research_universe_long.sqlite3')
    ap.add_argument('--index-start', default='20201007')
    ap.add_argument('--index-end', default='20260625')
    ap.add_argument('--index-start-fmt', default='2020-10-07')
    ap.add_argument('--index-end-fmt', default='2026-06-25')
    ap.add_argument('--formation-days', default='60')
    ap.add_argument('--horizons', default='20,60')
    ap.add_argument('--top-n', default='20')
    ap.add_argument('--min-price', default='1000')
    ap.add_argument('--min-avg-turnover-20d', default='50000000')
    ap.add_argument('--roundtrip-cost-pct', default='0.0046')
    ap.add_argument('--train-fraction', default='0.70')
    ap.add_argument('--min-locked-baskets', default='10')
    ap.add_argument('--require-positive-index-60d', action='store_true')
    ap.add_argument('--out', default='data/relative_strength_horizon_latest.json')
    ap.add_argument('--baskets-out', default='data/relative_strength_horizon_baskets.csv')
    ap.add_argument('--signals-out', default='data/relative_strength_horizon_signals.csv')
    args = ap.parse_args()
    report = run(args)
    print(json.dumps({
        'out': args.out,
        'mode': report['mode'],
        'hypothesis_id': report['hypothesis_id'],
        'live_order_allowed': False,
        'symbols_loaded': report['symbols_loaded'],
        'rebalance_months': report['rebalance_months'],
        'edge_ok_same_history_only': report['edge_ok_same_history_only'],
        'blockers': report['blockers'],
        'evaluation': report['evaluation'],
        'concentration': report['concentration'],
    }, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
