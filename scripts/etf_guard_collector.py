#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from toss_auto_trader.cli import best_spread_from_orderbook
from toss_auto_trader.config import Settings
from toss_auto_trader.toss_client import TossInvestClient


def _dec(text: str) -> Decimal:
    return Decimal(text.replace(',', '').replace('%', '').replace('+', '').strip())


def fetch_naver_etf_nav(symbol: str) -> dict:
    url = f'https://finance.naver.com/item/main.naver?code={symbol}'
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    body = urllib.request.urlopen(req, timeout=20).read().decode('utf-8', 'replace')
    idx = body.find('괴리율')
    if idx < 0:
        return {'available': False, 'error': 'nav_table_not_found'}
    frag = body[idx - 1000:idx + 5000]
    plain = html.unescape(re.sub('<[^>]+>', ' ', frag))
    plain = re.sub(r'\s+', ' ', plain)
    m = re.search(r'(\d{4}\.\d{2}\.\d{2})\s+([\d,]+)\s+([\d,]+(?:\.\d+)?)\s+([+-]?\d+(?:\.\d+)?)%', plain)
    if not m:
        return {'available': False, 'error': 'nav_row_not_found', 'snippet': plain[:500]}
    return {
        'available': True,
        'date': m.group(1),
        'close': str(_dec(m.group(2))),
        'nav': str(_dec(m.group(3))),
        'disparity_pct': str(_dec(m.group(4))),
        'source_url': url,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--symbols', required=True, help='comma separated ETF symbols')
    ap.add_argument('--out', default='data/etf_guard_latest.json')
    ap.add_argument('--max-spread-bps', default=os.getenv('MAX_SPREAD_BPS', '30'))
    ap.add_argument('--max-abs-disparity-pct', default=os.getenv('MAX_ETF_ABS_DISPARITY_PCT', '0.5'))
    args = ap.parse_args()
    settings = Settings.from_env()
    client = TossInvestClient(settings)
    threshold = Decimal(str(args.max_spread_bps))
    max_abs_disparity = Decimal(str(args.max_abs_disparity_pct))
    rows = []
    for symbol in [s.strip() for s in args.symbols.split(',') if s.strip()]:
        row = {
            'symbol': symbol,
            'collected_at': datetime.now(timezone.utc).isoformat(),
            'source': 'toss_orderbook_plus_naver_nav',
            'nav': None,
            'disparity_pct': None,
            'lp_contract': None,
            'lp_contract_source': {
                'primary': 'KRX Data Marketplace MDCSTAT241 / 종목별 주식 시장조성자 및 ETF LP 계약 현황',
                'url': 'https://data.krx.co.kr/contents/MDC/STAT/issue/MDCSTAT241.jsp',
                'status': 'identified_but_direct_json_returns_400_LOGOUT_in_current_environment',
            },
            'lp_proxy': None,
            'underlying_market_open': None,
            'auto_approved': False,
            'block_reasons': [],
            'warnings': [],
        }
        try:
            spread = best_spread_from_orderbook(client.get_orderbook(symbol))
        except Exception as exc:
            spread = {'available': False, 'ok': False, 'error': str(exc)[:300]}
        row['spread'] = spread
        if not spread.get('available'):
            row['block_reasons'].append('spread_unavailable')
        elif Decimal(str(spread.get('spread_bps', '999999'))) > threshold:
            row['block_reasons'].append('spread_too_wide')
        else:
            row['lp_proxy'] = {'method': 'tight_orderbook_spread', 'max_spread_bps': str(threshold), 'passed': True}
        try:
            nav = fetch_naver_etf_nav(symbol)
        except Exception as exc:
            nav = {'available': False, 'error': str(exc)[:300]}
        row['nav_source'] = nav
        if nav.get('available'):
            row['nav'] = nav['nav']
            row['disparity_pct'] = nav['disparity_pct']
            if abs(Decimal(str(nav['disparity_pct']))) > max_abs_disparity:
                row['block_reasons'].append('disparity_too_wide')
        else:
            row['block_reasons'].extend(['nav_not_collected', 'disparity_not_collected'])
        if row['lp_contract'] is None:
            row['warnings'].append('lp_contract_not_collected_using_spread_proxy')
        row['status'] = 'blocked_etf_guard_incomplete' if row['block_reasons'] else 'etf_guard_passed_not_live_order'
        rows.append(row)
    out = {
        'updated_at': datetime.now(timezone.utc).isoformat(),
        'max_spread_bps': str(threshold),
        'max_abs_disparity_pct': str(max_abs_disparity),
        'policy': 'ETF cannot be auto-approved for live order; paper guard may pass with Naver NAV/disparity plus spread-based LP proxy.',
        'rows': rows,
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, ensure_ascii=False, indent=2))
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
