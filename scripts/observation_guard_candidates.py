#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path


def load_obs(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text().splitlines():
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--candidates', default='data/live_paper_candidates.json')
    ap.add_argument('--observations', default='data/paper_observations.jsonl')
    ap.add_argument('--min-observations', type=int, default=3)
    args = ap.parse_args()
    cpath = Path(args.candidates)
    data = json.loads(cpath.read_text())
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in load_obs(Path(args.observations)):
        pair = row.get('candidate', {}).get('pair')
        if pair:
            grouped[pair].append(row)
    for cand in data.get('candidates', []):
        pair = cand.get('pair')
        recent = grouped.get(pair, [])[-args.min_observations:]
        blocked = [r for r in recent if str(r.get('status', '')).startswith('blocked')]
        guard = {
            'min_observations': args.min_observations,
            'recent_observations': len(recent),
            'blocked_recent': len(blocked),
            'ok': len(recent) >= args.min_observations and not blocked,
        }
        cand['observation_guard'] = guard
        current_status = str(cand.get('status', ''))
        if not guard['ok']:
            cand['status'] = 'blocked_observation_unstable'
        elif guard['ok'] and (current_status == 'blocked_observation_unstable' or not current_status.startswith('blocked_')):
            cand['status'] = 'observation_checked_watchlist_not_live_order'
    data['observation_guard_updated'] = True
    data['live_order_allowed'] = False
    data['manual_approval_required'] = True
    cpath.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    print(json.dumps({'updated': str(cpath), 'pairs': {k: len(v) for k, v in grouped.items()}, 'top_status': [c.get('status') for c in data.get('candidates', [])[:5]]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
