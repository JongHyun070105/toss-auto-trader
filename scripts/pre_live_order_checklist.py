#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--path', default='data/live_paper_candidates.json')
    ap.add_argument('--candidate-index', type=int, default=0)
    ap.add_argument('--require-spread-ok', action='store_true')
    ap.add_argument('--require-observation-ok', action='store_true')
    ap.add_argument('--require-stress-ok', action='store_true')
    ap.add_argument('--require-edge-ok', action='store_true')
    ap.add_argument('--ack', default='', help='must equal I_UNDERSTAND_THIS_DOES_NOT_SEND_ORDERS')
    args = ap.parse_args()

    data = json.loads(Path(args.path).read_text())
    candidates = data.get('candidates', [])
    errors: list[str] = []
    warnings: list[str] = []
    if data.get('live_order_allowed') is not False:
        errors.append('candidate file must keep live_order_allowed=false until a separate live-order flow exists')
    if data.get('manual_approval_required') is not True:
        errors.append('manual_approval_required must be true')
    if not candidates:
        errors.append('no candidates')
        candidate = {}
    else:
        candidate = candidates[args.candidate_index]
    if candidate:
        if candidate.get('source') != 'walk_forward':
            errors.append('candidate must come from walk_forward validation, not raw grid only')
        if not candidate.get('stable_positive'):
            errors.append('candidate must be stable_positive=true')
        if (candidate.get('validation_pnl_krw') or 0) <= 0:
            errors.append('validation_pnl_krw must be positive')
        if not str(candidate.get('status', '')).endswith('not_live_order'):
            errors.append(f"candidate status is not paper-only watchlist: {candidate.get('status')}")
        spread = candidate.get('spread_guard')
        if args.require_spread_ok and not (spread and spread.get('ok')):
            errors.append('spread_guard.ok must be true')
        if not spread:
            warnings.append('spread_guard missing; run scripts/spread_guard_candidates.py first')
        obs_guard = candidate.get('observation_guard')
        if args.require_observation_ok and not (obs_guard and obs_guard.get('ok')):
            errors.append('observation_guard.ok must be true over recent observations')
        if not obs_guard:
            warnings.append('observation_guard missing; run scripts/observation_guard_candidates.py first')
        if args.require_stress_ok:
            stress_path = Path('data/stress_test_latest.json')
            if not stress_path.exists():
                errors.append('stress_test_latest.json missing; run scripts/stress_test_candidates.py first')
            else:
                stress = json.loads(stress_path.read_text())
                row = next((r for r in stress.get('rows', []) if r.get('pair') == candidate.get('pair')), None)
                if not row or not row.get('ok'):
                    errors.append('stress test must pass for candidate pair')
        if args.require_edge_ok:
            edge_guard = candidate.get('edge_guard')
            edge = candidate.get('edge_audit')
            if edge_guard and not edge_guard.get('ok'):
                errors.append(f"edge_guard must pass: {edge_guard.get('reason')}")
            elif not edge:
                errors.append('edge_audit missing; run scripts/strategy_edge_audit.py then update candidates')
            elif not edge.get('edge_ok'):
                errors.append('edge_audit.edge_ok must be true')
    if args.ack != 'I_UNDERSTAND_THIS_DOES_NOT_SEND_ORDERS':
        errors.append('ack string missing; this checklist intentionally does not send orders')

    report = {
        'ok': not errors,
        'candidate': candidate,
        'errors': errors,
        'warnings': warnings,
        'next_step_if_ok': 'manual human review only; implement a separate --really-send flow later if explicitly requested',
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not errors else 2


if __name__ == '__main__':
    raise SystemExit(main())
