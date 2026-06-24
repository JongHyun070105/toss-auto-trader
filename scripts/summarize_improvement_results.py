#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path


def load_json(path: str, default):
    p = Path(path)
    if not p.exists():
        return default
    return json.loads(p.read_text())


def count_lines(path: str) -> int:
    p = Path(path)
    return len(p.read_text().splitlines()) if p.exists() else 0


def observation_failure_counts(path: str = 'data/paper_observations.jsonl') -> dict:
    counts = {}
    p = Path(path)
    if not p.exists():
        return counts
    for line in p.read_text().splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        for detail in row.get('block_details', []):
            kind = detail.get('kind', 'unknown')
            counts[kind] = counts.get(kind, 0) + 1
        for reason in row.get('block_reasons', []):
            text = str(reason).lower()
            if 'invalid-token' in text or 'unauthorized' in text:
                counts['token_invalid_or_unauthorized'] = counts.get('token_invalid_or_unauthorized', 0) + 1
            elif 'spread_too_wide' in text:
                counts['spread_too_wide'] = counts.get('spread_too_wide', 0) + 1
            elif 'spread' in text:
                counts['spread_unavailable'] = counts.get('spread_unavailable', 0) + 1
    return counts


def spread_history_summary(path: str = 'data/spread_history.jsonl', window: int = 5) -> dict:
    p = Path(path)
    vals = {}
    if not p.exists():
        return vals
    for line in p.read_text().splitlines():
        try:
            row = json.loads(line)
            sp = row.get('spread', {})
            if sp.get('available') and sp.get('spread_bps') is not None:
                vals.setdefault(row.get('symbol'), []).append(float(sp['spread_bps']))
        except Exception:
            continue
    return {k: {'n': len(v[-window:]), 'avg_spread_bps': sum(v[-window:]) / len(v[-window:]) if v[-window:] else None, 'max_spread_bps': max(v[-window:]) if v[-window:] else None} for k, v in vals.items()}


def main() -> int:
    candidates = load_json('data/live_paper_candidates.json', {'candidates': []})
    etf = load_json('data/etf_guard_latest.json', {'rows': []})
    token_health = load_json('data/toss_token_health_latest.json', {})
    dynamic_costs = load_json('data/dynamic_execution_costs.json', {})
    multi_capital = load_json('data/multi_capital_latest/summary.json', {})
    stress = load_json('data/stress_test_latest.json', {})
    time_window = load_json('data/time_window_guard_latest.json', {})
    edge_audit = load_json('data/strategy_edge_audit_latest.json', {})
    volume_shock = load_json('data/volume_shock_hypothesis_latest.json', {})
    top = candidates.get('candidates', [])[:5]
    spread_ok = [c for c in candidates.get('candidates', []) if c.get('spread_guard', {}).get('ok')]
    observation_ok = [c for c in candidates.get('candidates', []) if c.get('observation_guard', {}).get('ok')]
    blocked = [c for c in candidates.get('candidates', []) if str(c.get('status', '')).startswith('blocked')]
    etf_rows = etf.get('rows', [])
    etf_guard_passed = [r for r in etf_rows if str(r.get('status')) == 'etf_guard_passed_not_live_order']
    blocker_reasons = []
    if blocked:
        blocker_reasons.append('candidate_status_blocked')
    if candidates.get('candidates') and not observation_ok:
        blocker_reasons.append('observation_guard_not_satisfied')
    if etf_rows and any(r.get('warnings') for r in etf_rows):
        blocker_reasons.append('etf_lp_contract_uses_proxy_or_missing')
    if token_health and not token_health.get('ok'):
        blocker_reasons.append(token_health.get('blocker') or 'toss_token_health_failed')
    if stress.get('rows') and not any(r.get('ok') for r in stress.get('rows', [])):
        blocker_reasons.append('stress_test_not_satisfied')
    if time_window.get('time_window_guard') and not time_window['time_window_guard'].get('ok'):
        blocker_reasons.append('outside_kr_observation_window')
    if edge_audit and edge_audit.get('summary', {}).get('edge_ok_count', 0) == 0:
        blocker_reasons.append('strategy_edge_not_established')
    vs_summary = volume_shock.get('summary', {}) if isinstance(volume_shock, dict) else {}
    if vs_summary and not vs_summary.get('edge_ok'):
        blocker_reasons.append('volume_shock_edge_not_established')
        for blocker in vs_summary.get('blockers', []):
            if blocker in {'insufficient_universe_symbols', 'insufficient_total_signals', 'insufficient_locked_test_signals'}:
                blocker_reasons.append(f'volume_shock_{blocker}')
    report = {
        'candidate_count': len(candidates.get('candidates', [])),
        'top_candidates': top,
        'spread_ok_count': len(spread_ok),
        'blocked_candidate_count': len(blocked),
        'observation_ok_count': len(observation_ok),
        'paper_observation_lines': count_lines('data/paper_observations.jsonl'),
        'observation_failure_counts': observation_failure_counts(),
        'spread_history_summary': spread_history_summary(),
        'toss_token_health': token_health,
        'dynamic_execution_costs': dynamic_costs,
        'multi_capital_summary': multi_capital,
        'stress_test_summary': stress,
        'time_window_guard': time_window,
        'strategy_edge_audit': edge_audit,
        'volume_shock_hypothesis': volume_shock,
        'etf_guard_passed_count': len(etf_guard_passed),
        'etf_guard_rows': etf_rows,
        'live_order_allowed': candidates.get('live_order_allowed'),
        'manual_approval_required': candidates.get('manual_approval_required'),
        'blocker_reasons': blocker_reasons,
        'next_decision': 'continue paper/read-only; require spread_ok and observation_ok before any human pre-live review; no live order send path exists',
    }
    Path('data/improvement_summary_latest.json').write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
