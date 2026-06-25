#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import math
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from statistics import mean, median


def d(x) -> Decimal:
    return Decimal(str(x or '0'))


def avg(vals: list[Decimal]) -> Decimal:
    return sum(vals) / Decimal(len(vals)) if vals else Decimal('0')


def std(vals: list[Decimal]) -> Decimal:
    if len(vals) < 2:
        return Decimal('0')
    mu = avg(vals)
    return avg([(v - mu) * (v - mu) for v in vals]).sqrt()


def pct_change(a: Decimal, b: Decimal) -> Decimal:
    return (b - a) / a if a > 0 else Decimal('0')


def fetch_kosdaq_index(start_yyyymmdd: str = '20200101', end_yyyymmdd: str = '20260625') -> list[dict]:
    query = urllib.parse.urlencode({'startDateTime': f'{start_yyyymmdd}0000', 'endDateTime': f'{end_yyyymmdd}0000'})
    url = f'https://api.stock.naver.com/chart/domestic/index/KOSDAQ/day?{query}'
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0', 'Referer': 'https://finance.naver.com/'})
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read().decode('utf-8'))
    rows = []
    for row in data or []:
        try:
            date = str(row['localDate'])
            rows.append({'timestamp': f'{date[:4]}-{date[4:6]}-{date[6:8]}', 'close_price': d(row['closePrice'])})
        except Exception:
            continue
    return rows


def regime_features(index_rows: list[dict]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    closes = [r['close_price'] for r in index_rows]
    sqrt252 = Decimal('15.874507866387544')
    for i, row in enumerate(index_rows):
        feats: dict[str, object] = {'timestamp': row['timestamp'], 'close_price': float(row['close_price'])}
        for n in (5, 20, 60, 120):
            if i >= n:
                feats[f'ret_{n}d'] = float(pct_change(closes[i - n], closes[i]))
            else:
                feats[f'ret_{n}d'] = None
        if i >= 20:
            rets20 = [pct_change(closes[j - 1], closes[j]) for j in range(i - 19, i + 1)]
            feats['ann_vol_20d'] = float(std(rets20) * sqrt252)
        else:
            feats['ann_vol_20d'] = None
        feats['regime'] = classify_regime(feats)
        out[row['timestamp']] = feats
    return out


def classify_regime(feats: dict) -> str:
    r20 = feats.get('ret_20d')
    r60 = feats.get('ret_60d')
    vol = feats.get('ann_vol_20d')
    if r20 is None or r60 is None or vol is None:
        return 'insufficient_index_history'
    if r20 <= -0.08:
        return 'crash_20d'
    if r20 <= -0.04:
        return 'drawdown_20d'
    if vol >= 0.45 and r20 < 0:
        return 'high_vol_down'
    if r20 >= 0.04 and r60 >= 0:
        return 'uptrend'
    if r60 >= 0 and r20 >= -0.02:
        return 'constructive_flat'
    if r60 < 0 and r20 < 0.02:
        return 'weak_or_downtrend'
    return 'mixed'


def nearest_prior_regime(regimes: dict[str, dict], ts: str) -> dict | None:
    if ts in regimes:
        return regimes[ts]
    # signals should use trading days; fallback for timestamp variants.
    keys = sorted(k for k in regimes if k <= ts[:10])
    if not keys:
        return None
    return regimes[keys[-1]]


def f(row: dict, key: str) -> float | None:
    try:
        value = row.get(key)
        if value in ('', None):
            return None
        out = float(value)
        if math.isnan(out) or math.isinf(out):
            return None
        return out
    except Exception:
        return None


def load_signal_rows(paths: list[str]) -> list[dict]:
    rows = []
    for spec in paths:
        if '=' in spec:
            name, raw_path = spec.split('=', 1)
        else:
            raw_path = spec
            name = Path(spec).stem
        path = Path(raw_path)
        if not path.exists():
            continue
        with path.open() as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                ts = row.get('timestamp') or row.get('signal_date') or row.get('entry_timestamp')
                ret = f(row, 'net_return_after_cost')
                if ts is None or ret is None:
                    continue
                rows.append({'strategy': name, 'timestamp': str(ts)[:10], 'net_return_after_cost': ret, 'symbol': row.get('symbol', ''), **row})
    return rows


def summarize(vals: list[float]) -> dict:
    if not vals:
        return {'signals': 0, 'avg': None, 'median': None, 'win_rate': None}
    return {
        'signals': len(vals),
        'avg': mean(vals),
        'median': median(vals),
        'win_rate': sum(1 for v in vals if v > 0) / len(vals),
    }


def bucket_report(rows: list[dict]) -> dict:
    by_strategy_regime: dict[tuple[str, str], list[float]] = defaultdict(list)
    by_strategy: dict[str, list[float]] = defaultdict(list)
    by_month: dict[tuple[str, str], list[float]] = defaultdict(list)
    for row in rows:
        strat = row['strategy']
        regime = row.get('regime', 'missing_regime')
        val = float(row['net_return_after_cost'])
        by_strategy[strat].append(val)
        by_strategy_regime[(strat, regime)].append(val)
        by_month[(strat, row['timestamp'][:7])].append(val)
    return {
        'strategy_summary': {k: summarize(v) for k, v in sorted(by_strategy.items())},
        'strategy_by_regime': [
            {'strategy': strat, 'regime': regime, **summarize(vals)}
            for (strat, regime), vals in sorted(by_strategy_regime.items())
        ],
        'worst_months': [
            {'strategy': strat, 'month': month, **summarize(vals)}
            for (strat, month), vals in sorted(by_month.items(), key=lambda kv: summarize(kv[1])['avg'] or 0)[:20]
        ],
    }


def evaluate_gates(rows: list[dict], gate_rules: list[tuple[str, callable]]) -> list[dict]:
    out = []
    total_vals = [float(r['net_return_after_cost']) for r in rows]
    total = summarize(total_vals)
    for label, pred in gate_rules:
        kept = [r for r in rows if pred(r)]
        blocked = [r for r in rows if not pred(r)]
        kept_summary = summarize([float(r['net_return_after_cost']) for r in kept])
        blocked_summary = summarize([float(r['net_return_after_cost']) for r in blocked])
        out.append({
            'gate': label,
            'status': 'diagnostic_only_not_approval',
            'kept': kept_summary,
            'blocked': blocked_summary,
            'coverage_kept': (kept_summary['signals'] / total['signals']) if total['signals'] else None,
            'delta_avg_vs_all': (kept_summary['avg'] - total['avg']) if kept_summary['avg'] is not None and total['avg'] is not None else None,
            'warning': 'Same-history diagnostic. Passing a gate here does not approve trading; freeze and forward-test first.',
        })
    return out


def run(args) -> dict:
    regimes = regime_features(fetch_kosdaq_index(args.index_start, args.index_end))
    rows = []
    missing_regime = 0
    for row in load_signal_rows(args.signals):
        reg = nearest_prior_regime(regimes, row['timestamp'])
        if not reg:
            missing_regime += 1
            continue
        enriched = dict(row)
        enriched['regime'] = reg['regime']
        for key in ('ret_5d', 'ret_20d', 'ret_60d', 'ret_120d', 'ann_vol_20d'):
            enriched[f'kosdaq_{key}'] = reg.get(key)
        rows.append(enriched)

    gate_rules = [
        ('avoid_crash_drawdown_high_vol_down', lambda r: r.get('regime') not in {'crash_20d', 'drawdown_20d', 'high_vol_down'}),
        ('only_uptrend_or_constructive_flat', lambda r: r.get('regime') in {'uptrend', 'constructive_flat'}),
        ('avoid_negative_20d_return', lambda r: (r.get('kosdaq_ret_20d') is not None and float(r.get('kosdaq_ret_20d')) >= 0)),
        ('avoid_negative_60d_return', lambda r: (r.get('kosdaq_ret_60d') is not None and float(r.get('kosdaq_ret_60d')) >= 0)),
    ]
    report = {
        'mode': 'research_only_no_send_regime_first_diagnostic',
        'live_order_allowed': False,
        'premise': 'Stop asking which stock will rise in 3 days; first test whether market regime permits any long exposure.',
        'signals_loaded': len(rows),
        'missing_regime': missing_regime,
        'index_start': args.index_start,
        'index_end': args.index_end,
        **bucket_report(rows),
        'gate_diagnostics': evaluate_gates(rows, gate_rules),
        'next_policy': {
            'blocked': 'Do not create another short-horizon stock-selection hypothesis until regime gate has forward evidence.',
            'allowed': ['Regime-first exposure gate', '20d/60d horizon research', 'event-data track with separate data collection'],
        },
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    if args.rows_out:
        Path(args.rows_out).parent.mkdir(parents=True, exist_ok=True)
        if rows:
            keys = []
            for row in rows:
                for key in row:
                    if key not in keys:
                        keys.append(key)
            with Path(args.rows_out).open('w', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=keys)
                writer.writeheader()
                writer.writerows(rows)
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description='Market-regime-first diagnostic for failed short-horizon stock-selection signals. No orders are sent.')
    ap.add_argument('--signals', action='append', required=True, help='strategy_name=path.csv or path.csv. CSV must have timestamp/signal_date and net_return_after_cost.')
    ap.add_argument('--index-start', default='20200101')
    ap.add_argument('--index-end', default=datetime.now().strftime('%Y%m%d'))
    ap.add_argument('--out', default='data/market_regime_signal_audit_latest.json')
    ap.add_argument('--rows-out', default='data/market_regime_signal_audit_rows.csv')
    args = ap.parse_args()
    report = run(args)
    print(json.dumps({
        'out': args.out,
        'rows_out': args.rows_out,
        'signals_loaded': report['signals_loaded'],
        'live_order_allowed': False,
        'top_gate_diagnostics': report['gate_diagnostics'][:4],
    }, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
