#!/usr/bin/env python3
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


def edge_audit_map(path: Path = Path('data/strategy_edge_audit_latest.json')) -> dict[tuple, dict]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        return {}
    out = {}
    for row in data.get('candidate_edges', []):
        key = (row.get('pair'), row.get('branch'), row.get('window'), row.get('horizon'), row.get('mode'))
        out[key] = row
    return out


def spread_penalties(path: Path = Path('data/spread_history.jsonl'), window: int = 5, threshold_bps: float = 30.0) -> dict[str, float]:
    vals: dict[str, list[float]] = {}
    if path.exists():
        for line in path.read_text().splitlines():
            try:
                row = json.loads(line)
                sp = row.get('spread', {})
                if sp.get('available') and sp.get('spread_bps') is not None:
                    vals.setdefault(row['symbol'], []).append(float(sp['spread_bps']))
            except Exception:
                continue
    return {sym: max(0.0, max(v[-window:]) - threshold_bps) * 100 for sym, v in vals.items() if v[-window:]}


def observation_penalties(path: Path = Path('data/paper_observations.jsonl'), window: int = 5) -> dict[str, float]:
    rows = []
    if path.exists():
        for line in path.read_text().splitlines():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        pair = row.get('candidate', {}).get('pair')
        if pair:
            grouped.setdefault(pair, []).append(row)
    penalties = {}
    for pair, items in grouped.items():
        recent = items[-window:]
        blocked = sum(1 for r in recent if str(r.get('status', '')).startswith('blocked'))
        token_fail = sum(sum(1 for d in r.get('block_details', []) if d.get('kind') == 'token_invalid_or_unauthorized') for r in recent)
        penalties[pair] = blocked * 5000 + token_fail * 1000
    return penalties


def load_grid_rows(path: Path, fallback_mode: str) -> list[dict]:
    if not path.exists():
        return []
    summary = json.loads(path.read_text())
    rows = []
    for r in summary.get('top', []):
        if r.get('branch') in {'observation_first', 'ultra_conservative'}:
            continue
        item = dict(r)
        item['mode'] = item.get('mode') or summary.get('mode') or fallback_mode
        item['source'] = 'grid'
        item['score_pnl'] = float(item.get('pnl', -10**9))
        rows.append(item)
    return rows


def load_walk_forward_rows(path: Path, fallback_mode: str) -> list[dict]:
    if not path.exists():
        return []
    summary = json.loads(path.read_text())
    rows = []
    for r in summary.get('top', []):
        if not r.get('stable_positive'):
            continue
        item = dict(r)
        item['mode'] = item.get('mode') or summary.get('mode') or fallback_mode
        item['source'] = 'walk_forward'
        item['pnl'] = item.get('validation_pnl', 0)
        item['equity'] = item.get('validation_equity', 10000)
        item['db'] = item.get('validation_db')
        item['score_pnl'] = float(item.get('validation_pnl', -10**9)) + min(float(item.get('train_pnl', 0)), 1000) * 0.1
        rows.append(item)
    return rows


def main() -> int:
    rows = []
    rows.extend(load_walk_forward_rows(Path('data/walk_forward_shared/summary.json'), 'shared_account'))
    rows.extend(load_walk_forward_rows(Path('data/walk_forward_isolated/summary.json'), 'isolated_slots'))
    rows.extend(load_grid_rows(Path('data/grid_latest/summary.json'), 'shared_account'))
    rows.extend(load_grid_rows(Path('data/grid_isolated_latest/summary.json'), 'isolated_slots'))
    penalties = observation_penalties()
    sp_penalties = spread_penalties()
    edge_map = edge_audit_map()
    for r in rows:
        symbols = [part.split(':', 1)[0] for part in r.get('pair', '').split('+') if part]
        r['observation_penalty_score'] = penalties.get(r.get('pair'), 0)
        r['spread_history_penalty_score'] = sum(sp_penalties.get(sym, 0) for sym in symbols)
        edge_key = (r.get('pair'), r.get('branch'), r.get('window'), r.get('horizon'), r.get('mode'))
        r['edge_audit'] = edge_map.get(edge_key)
        r['edge_penalty_score'] = 0 if (r.get('edge_audit') or {}).get('edge_ok') else (20000 if edge_map else 0)
        r['score_pnl_after_observation_penalty'] = float(r.get('score_pnl', -10**9)) - float(r['observation_penalty_score']) - float(r['spread_history_penalty_score']) - float(r['edge_penalty_score'])
    ranked = sorted(rows, key=lambda r: (1 if r.get('source') == 'walk_forward' else 0, float(r.get('score_pnl_after_observation_penalty', -10**9))), reverse=True)
    candidates = []
    seen = set()
    for r in ranked:
        # Keep one best candidate per pair+mode+source to avoid top-N being clones of the same idea.
        key = (r['pair'], r.get('mode'), r.get('source'))
        if key in seen:
            continue
        seen.add(key)
        candidates.append({
            'name': f"{r.get('source', 'grid')}_{r.get('mode', 'grid')}_top_{len(candidates) + 1}",
            'pair': r['pair'],
            'symbols': [part.split(':', 1)[0] for part in r['pair'].split('+')],
            'branch': r['branch'],
            'window': r['window'],
            'horizon': r['horizon'],
            'mode': r.get('mode'),
            'source': r.get('source'),
            'evidence_db': r.get('db') or r.get('validation_db'),
            'equity_krw': r.get('equity'),
            'pnl_krw': r.get('pnl'),
            'train_pnl_krw': r.get('train_pnl'),
            'validation_pnl_krw': r.get('validation_pnl'),
            'stable_positive': r.get('stable_positive'),
            'observation_penalty_score': r.get('observation_penalty_score'),
            'spread_history_penalty_score': r.get('spread_history_penalty_score'),
            'edge_audit': r.get('edge_audit'),
            'edge_penalty_score': r.get('edge_penalty_score'),
            'score_pnl_after_observation_penalty': r.get('score_pnl_after_observation_penalty'),
            'status': 'watchlist_not_live_order',
        })
        if len(candidates) >= 10:
            break
    out = {
        'updated_at': datetime.now(timezone.utc).isoformat(),
        'capital_krw': 10000,
        'mode': 'paper_candidate_only',
        'live_order_allowed': False,
        'manual_approval_required': True,
        'selection_note': 'Auto-updated from fee/tax-aware cached-candle grids and walk-forward validation. No live order without explicit user approval.',
        'candidates': candidates,
    }
    Path('data/live_paper_candidates.json').write_text(json.dumps(out, ensure_ascii=False, indent=2))
    print(json.dumps({'updated': 'data/live_paper_candidates.json', 'top': candidates[:3]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
