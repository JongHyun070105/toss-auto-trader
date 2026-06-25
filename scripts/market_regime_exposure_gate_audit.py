#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from decimal import Decimal
from pathlib import Path
from statistics import mean, median
from typing import Callable

from market_regime_signal_audit import fetch_kosdaq_index, regime_features


def pct(a: Decimal, b: Decimal) -> float:
    return float((b - a) / a) if a > 0 else 0.0


def max_drawdown(equity: list[float]) -> float:
    if not equity:
        return 0.0
    peak = equity[0]
    worst = 0.0
    for v in equity:
        if v > peak:
            peak = v
        if peak > 0:
            worst = min(worst, (v / peak) - 1.0)
    return worst


def summarize(vals: list[float]) -> dict:
    if not vals:
        return {'signals': 0, 'avg': None, 'median': None, 'win_rate': None}
    return {
        'signals': len(vals),
        'avg': mean(vals),
        'median': median(vals),
        'win_rate': sum(1 for v in vals if v > 0) / len(vals),
    }


def split_train_test(rows: list[dict], train_fraction: float) -> tuple[list[dict], list[dict]]:
    ordered = sorted(rows, key=lambda r: r['timestamp'])
    if not ordered:
        return [], []
    cut = int(len(ordered) * train_fraction)
    if len(ordered) > 1:
        cut = min(max(cut, 1), len(ordered) - 1)
    return ordered[:cut], ordered[cut:]


def gate_rules() -> dict[str, Callable[[dict], bool]]:
    return {
        'always_long_index_proxy': lambda f: True,
        # Trend-following exposure gate: only hold broad KOSDAQ exposure when recent trend is constructive.
        'trend_constructive_only': lambda f: f.get('regime') in {'uptrend', 'constructive_flat'},
        # Mean-reversion exposure gate: broad exposure only in index drawdown/rebound-style regimes.
        # This is diagnostic only; it was motivated by the RSI+Bollinger regime decomposition and must be forward-tested.
        'rebound_crash_drawdown_mixed': lambda f: f.get('regime') in {'crash_20d', 'drawdown_20d', 'mixed'},
        # Risk-off weak trend gate: avoid persistent weak/down regimes but do not blanket-block crash rebound regimes.
        'avoid_weak_downtrend_only': lambda f: f.get('regime') not in {'weak_or_downtrend'},
        # Conservative gate: avoid both weak trend and high-vol down, while allowing trend and rebound buckets.
        'avoid_weak_and_high_vol_down': lambda f: f.get('regime') not in {'weak_or_downtrend', 'high_vol_down'},
    }


def forward_rows(index_rows: list[dict], feats_by_date: dict[str, dict], *, gate_name: str, gate: Callable[[dict], bool], horizon: int, cost_pct: float) -> list[dict]:
    rows = []
    closes = [r['close_price'] for r in index_rows]
    for i, row in enumerate(index_rows):
        if i + horizon >= len(index_rows):
            continue
        feats = feats_by_date.get(row['timestamp'])
        if not feats or feats.get('regime') == 'insufficient_index_history':
            continue
        allow = bool(gate(feats))
        raw = pct(closes[i], closes[i + horizon])
        gated = (raw - cost_pct) if allow else 0.0
        always = raw - cost_pct
        rows.append({
            'timestamp': row['timestamp'],
            'horizon': horizon,
            'gate': gate_name,
            'regime': feats.get('regime'),
            'allow_long_exposure': allow,
            'index_forward_return_after_cost': always,
            'gate_forward_return_after_cost_or_cash': gated,
            'cash_return': 0.0,
            'excess_vs_always_long': gated - always,
            'excess_vs_cash': gated,
            'kosdaq_ret_20d': feats.get('ret_20d'),
            'kosdaq_ret_60d': feats.get('ret_60d'),
            'kosdaq_ann_vol_20d': feats.get('ann_vol_20d'),
        })
    return rows


def evaluate_forward(rows: list[dict], train_fraction: float) -> dict:
    train, test = split_train_test(rows, train_fraction)

    def part_stats(part: list[dict]) -> dict:
        gated = [float(r['gate_forward_return_after_cost_or_cash']) for r in part]
        always = [float(r['index_forward_return_after_cost']) for r in part]
        excess = [float(r['excess_vs_always_long']) for r in part]
        return {
            'gate': summarize(gated),
            'always_long_index_proxy': summarize(always),
            'excess_vs_always_long': summarize(excess),
            'exposure_rate': (sum(1 for r in part if r['allow_long_exposure']) / len(part)) if part else None,
        }

    return {
        'all': part_stats(rows),
        'train': part_stats(train),
        'locked_test': part_stats(test),
    }


def simulate_equity(index_rows: list[dict], feats_by_date: dict[str, dict], *, gate_name: str, gate: Callable[[dict], bool], one_way_switch_cost_pct: float, train_fraction: float) -> dict:
    sim_rows = []
    prev_exposed = False
    equity = 1.0
    always = 1.0
    cash = 1.0
    closes = [r['close_price'] for r in index_rows]
    for i in range(1, len(index_rows)):
        prev = index_rows[i - 1]
        cur = index_rows[i]
        feats = feats_by_date.get(prev['timestamp'])
        if not feats or feats.get('regime') == 'insufficient_index_history':
            continue
        exposed = bool(gate(feats))
        daily_ret = pct(closes[i - 1], closes[i])
        switch_cost = one_way_switch_cost_pct if exposed != prev_exposed else 0.0
        if exposed:
            equity *= max(0.0, 1.0 + daily_ret - switch_cost)
        else:
            equity *= max(0.0, 1.0 - switch_cost)
        always *= max(0.0, 1.0 + daily_ret)
        sim_rows.append({
            'timestamp': cur['timestamp'],
            'gate': gate_name,
            'regime_used': feats.get('regime'),
            'exposed': exposed,
            'daily_index_return': daily_ret,
            'switch_cost': switch_cost,
            'equity': equity,
            'always_long_equity': always,
            'cash_equity': cash,
        })
        prev_exposed = exposed

    train, test = split_train_test(sim_rows, train_fraction)

    def equity_stats(part: list[dict]) -> dict:
        if not part:
            return {'days': 0, 'total_return': None, 'mdd': None, 'exposure_rate': None, 'switches': 0}
        base_gate = part[0]['equity']
        base_always = part[0]['always_long_equity']
        gate_curve = [r['equity'] / base_gate for r in part]
        always_curve = [r['always_long_equity'] / base_always for r in part]
        return {
            'days': len(part),
            'total_return': gate_curve[-1] - 1.0,
            'always_long_total_return': always_curve[-1] - 1.0,
            'excess_total_return_vs_always_long': (gate_curve[-1] - always_curve[-1]),
            'mdd': max_drawdown(gate_curve),
            'always_long_mdd': max_drawdown(always_curve),
            'exposure_rate': sum(1 for r in part if r['exposed']) / len(part),
            'switches': sum(1 for r in part if r['switch_cost'] > 0),
            'return_to_abs_mdd': ((gate_curve[-1] - 1.0) / abs(max_drawdown(gate_curve))) if max_drawdown(gate_curve) < 0 else None,
        }

    return {
        'all': equity_stats(sim_rows),
        'train': equity_stats(train),
        'locked_test': equity_stats(test),
    }


def blocker_list(forward_h20: dict, equity: dict) -> list[str]:
    blockers = ['same_history_diagnostic_requires_future_holdout']
    lt = forward_h20['locked_test']
    eq = equity['locked_test']
    gate_avg = lt['gate']['avg']
    excess_avg = lt['excess_vs_always_long']['avg']
    if gate_avg is None or gate_avg <= 0:
        blockers.append('locked_test_h20_gate_avg_not_positive')
    if excess_avg is None or excess_avg <= 0:
        blockers.append('locked_test_h20_not_above_always_long')
    if eq['total_return'] is None or eq['total_return'] <= 0:
        blockers.append('locked_test_equity_total_return_not_positive')
    if eq.get('excess_total_return_vs_always_long') is None or eq['excess_total_return_vs_always_long'] <= 0:
        blockers.append('locked_test_equity_not_above_always_long')
    if eq.get('exposure_rate') is None or eq['exposure_rate'] in (0.0, 1.0):
        blockers.append('gate_does_not_actually_gate_exposure')
    return blockers


def run(args) -> dict:
    index_rows = fetch_kosdaq_index(args.index_start, args.index_end)
    feats_by_date = regime_features(index_rows)
    rules = gate_rules()
    horizons = [int(x) for x in args.horizons.split(',') if x.strip()]
    gates = [x.strip() for x in args.gates.split(',') if x.strip()]
    missing = [g for g in gates if g not in rules]
    if missing:
        raise ValueError(f'Unknown gate(s): {missing}; choices={sorted(rules)}')

    gate_reports = []
    all_forward_rows = []
    for gate_name in gates:
        gate = rules[gate_name]
        by_horizon = {}
        for horizon in horizons:
            rows = forward_rows(index_rows, feats_by_date, gate_name=gate_name, gate=gate, horizon=horizon, cost_pct=float(args.roundtrip_cost_pct))
            all_forward_rows.extend(rows)
            by_horizon[f'h{horizon}'] = evaluate_forward(rows, float(args.train_fraction))
        equity = simulate_equity(
            index_rows,
            feats_by_date,
            gate_name=gate_name,
            gate=gate,
            one_way_switch_cost_pct=float(args.roundtrip_cost_pct) / 2.0,
            train_fraction=float(args.train_fraction),
        )
        h20_key = 'h20' if 'h20' in by_horizon else sorted(by_horizon)[0]
        blockers = blocker_list(by_horizon[h20_key], equity)
        gate_reports.append({
            'gate': gate_name,
            'status': 'same_history_diagnostic_not_approval',
            'candidate_ok_same_history_only': blockers == ['same_history_diagnostic_requires_future_holdout'],
            'blockers': blockers,
            'forward_by_horizon': by_horizon,
            'daily_equity_sim': equity,
        })

    report = {
        'mode': 'research_only_no_send_regime_exposure_gate_audit',
        'hypothesis_id': args.hypothesis_id,
        'hypothesis_status': 'new_regime_first_exposure_gate_diagnostic_requires_future_holdout',
        'live_order_allowed': False,
        'order_sent': False,
        'paper_only': True,
        'premise': 'Before selecting individual stocks, test whether KOSDAQ long exposure should be allowed at all.',
        'index_source': 'Naver Stock API domestic index KOSDAQ day chart',
        'index_start': args.index_start,
        'index_end': args.index_end,
        'index_rows': len(index_rows),
        'horizons': horizons,
        'cost_model': {'roundtrip_cost_pct': args.roundtrip_cost_pct, 'equity_switch_cost_one_way_pct': float(args.roundtrip_cost_pct) / 2.0},
        'gate_reports': gate_reports,
        'policy': {
            'not_live_approval': 'Even a passing same-history gate only becomes a frozen candidate for future/no-send forward validation.',
            'next_allowed': ['freeze one regime gate and forward-watch', '20d/60d horizon research under a frozen gate', 'event-data collection'],
        },
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    if args.rows_out:
        import csv
        Path(args.rows_out).parent.mkdir(parents=True, exist_ok=True)
        keys = []
        for row in all_forward_rows:
            for key in row:
                if key not in keys:
                    keys.append(key)
        with Path(args.rows_out).open('w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=keys)
            writer.writeheader()
            writer.writerows(all_forward_rows)
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description='No-send KOSDAQ regime exposure gate audit; no individual stock selection.')
    ap.add_argument('--hypothesis-id', default='KOSDAQ_REGIME_EXPOSURE_GATE_H20_H60_V1')
    ap.add_argument('--index-start', default='20200101')
    ap.add_argument('--index-end', default='20260625')
    ap.add_argument('--horizons', default='20,60')
    ap.add_argument('--gates', default='always_long_index_proxy,trend_constructive_only,rebound_crash_drawdown_mixed,avoid_weak_downtrend_only,avoid_weak_and_high_vol_down')
    ap.add_argument('--roundtrip-cost-pct', default='0.0046')
    ap.add_argument('--train-fraction', default='0.70')
    ap.add_argument('--out', default='data/market_regime_exposure_gate_latest.json')
    ap.add_argument('--rows-out', default='data/market_regime_exposure_gate_rows.csv')
    args = ap.parse_args()
    report = run(args)
    print(json.dumps({
        'out': args.out,
        'rows_out': args.rows_out,
        'mode': report['mode'],
        'live_order_allowed': False,
        'index_rows': report['index_rows'],
        'gate_summaries': [
            {
                'gate': g['gate'],
                'candidate_ok_same_history_only': g['candidate_ok_same_history_only'],
                'blockers': g['blockers'],
                'h20_locked_test': g['forward_by_horizon'].get('h20', {}).get('locked_test'),
                'equity_locked_test': g['daily_equity_sim'].get('locked_test'),
            }
            for g in report['gate_reports']
        ],
    }, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
