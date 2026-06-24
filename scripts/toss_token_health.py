#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from toss_auto_trader.config import Settings
from toss_auto_trader.toss_client import TossApiError, TossInvestClient


def classify_error(exc: Exception) -> str:
    text = str(exc).lower()
    if isinstance(exc, TossApiError):
        if exc.status == 401 or 'invalid-token' in text or 'unauthorized' in text:
            return 'token_invalid_or_unauthorized'
        if exc.status == 429:
            return 'rate_limited'
        if exc.status == 0:
            return 'network_error'
        return f'http_{exc.status}'
    if 'credentials' in text or 'client_id' in text or 'client_secret' in text:
        return 'credentials_missing'
    return 'unknown_error'


def candidate_symbols(path: str = 'data/live_paper_candidates.json') -> list[str]:
    p = Path(path)
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text())
    except json.JSONDecodeError:
        return []
    out = []
    for c in data.get('candidates', [])[:5]:
        for sym in c.get('symbols', []):
            if sym not in out:
                out.append(sym)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--symbols', default='', help='comma separated extra symbols to orderbook-check')
    args = ap.parse_args()
    out_path = Path('data/toss_token_health_latest.json')
    settings = Settings.from_env()
    client = TossInvestClient(settings)
    report = {
        'checked_at': datetime.now(timezone.utc).isoformat(),
        'base_url': settings.base_url,
        'dry_run': settings.dry_run,
        'live_trading': settings.live_trading,
        'ok': False,
        'checks': [],
    }
    try:
        token = client.issue_token()
        report['checks'].append({'name': 'issue_token', 'ok': True, 'expires_at': token.expires_at})
    except Exception as exc:
        report['checks'].append({'name': 'issue_token', 'ok': False, 'kind': classify_error(exc), 'error': str(exc)[:500]})
        report['blocker'] = classify_error(exc)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2))
        with open('data/toss_token_health_history.jsonl', 'a') as f:
            f.write(json.dumps(report, ensure_ascii=False) + '\n')
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    symbols = ['005930']
    symbols.extend([s.strip() for s in args.symbols.split(',') if s.strip()])
    for sym in candidate_symbols():
        if sym not in symbols:
            symbols.append(sym)
    for sym in symbols:
        try:
            ob = client.get_orderbook(sym)
            report['checks'].append({'name': f'orderbook_{sym}', 'ok': True, 'has_result': 'result' in ob or bool(ob)})
        except Exception as exc:
            kind = classify_error(exc)
            report['checks'].append({'name': f'orderbook_{sym}', 'ok': False, 'kind': kind, 'error': str(exc)[:500]})
            report['blocker'] = kind
    report['ok'] = all(c.get('ok') for c in report['checks'])
    if not report['ok'] and 'blocker' not in report:
        report['blocker'] = 'api_check_failed'
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    with open('data/toss_token_health_history.jsonl', 'a') as f:
        f.write(json.dumps(report, ensure_ascii=False) + '\n')
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
