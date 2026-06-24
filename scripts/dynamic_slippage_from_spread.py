#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path


def load_spread_history(path: str = 'data/spread_history.jsonl', window: int = 5) -> dict[str, list[float]]:
    p = Path(path)
    out: dict[str, list[float]] = {}
    if not p.exists():
        return out
    for line in p.read_text().splitlines():
        try:
            row = json.loads(line)
            sp = row.get('spread', {})
            if sp.get('available') and sp.get('spread_bps') is not None:
                out.setdefault(row['symbol'], []).append(float(sp['spread_bps']))
        except Exception:
            continue
    return {k: v[-window:] for k, v in out.items()}


def main() -> int:
    hist = load_spread_history()
    symbols = {}
    max_half_spread_bps = 0.0
    for symbol, vals in hist.items():
        if not vals:
            continue
        avg_bps = sum(vals) / len(vals)
        max_bps = max(vals)
        half_max_bps = max_bps / 2
        max_half_spread_bps = max(max_half_spread_bps, half_max_bps)
        symbols[symbol] = {
            'n': len(vals),
            'avg_spread_bps': avg_bps,
            'max_spread_bps': max_bps,
            'suggested_one_way_slippage_bps': half_max_bps,
            'suggested_one_way_slippage_pct': half_max_bps / 10000,
        }
    out = {
        'method': 'half_of_recent_max_bid_ask_spread',
        'history_window': 5,
        'symbols': symbols,
        'portfolio_worst_one_way_slippage_bps': max_half_spread_bps,
        'portfolio_worst_one_way_slippage_pct': max_half_spread_bps / 10000,
        'note': 'Backtests still use config.example.yaml fixed slippage unless regenerated with this value; candidate guards/scoring consume spread history directly.',
    }
    Path('data/dynamic_execution_costs.json').write_text(json.dumps(out, ensure_ascii=False, indent=2))
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
