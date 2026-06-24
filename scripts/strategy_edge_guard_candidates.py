#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path


def main() -> int:
    path = Path('data/live_paper_candidates.json')
    if not path.exists():
        raise SystemExit('missing data/live_paper_candidates.json')
    data = json.loads(path.read_text())
    for cand in data.get('candidates', []):
        edge = cand.get('edge_audit')
        guard = {
            'required': True,
            'ok': bool(edge and edge.get('edge_ok')),
            'reason': None,
            'edge_status': edge.get('edge_status') if edge else None,
            'total_buy_signals': edge.get('total_buy_signals') if edge else None,
            'valid_symbol_edges': edge.get('valid_symbol_edges') if edge else None,
            'symbol_count': edge.get('symbol_count') if edge else None,
        }
        if not edge:
            guard['reason'] = 'edge_audit_missing'
        elif not edge.get('edge_ok'):
            guard['reason'] = 'strategy_edge_not_established_for_all_legs'
        else:
            guard['reason'] = 'strategy_edge_passed'
        cand['edge_guard'] = guard
        if not guard['ok']:
            cand['status'] = 'blocked_strategy_edge_not_established'
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    print(json.dumps({'updated': str(path), 'top': data.get('candidates', [])[:3]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
