#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from statistics import mean, median
from zoneinfo import ZoneInfo

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from rsi_bbands_mean_reversion_audit import cached_candles_readonly, simulate_trade  # noqa: E402

KST = ZoneInfo('Asia/Seoul')


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def signal_index(candles: list[dict], signal_date: str) -> int | None:
    for i, candle in enumerate(candles):
        if str(candle.get('timestamp', ''))[:10] == signal_date[:10]:
            return i
    return None


def existing_outcome_ids(path: Path) -> set[str]:
    return {str(row.get('signal_id')) for row in load_jsonl(path) if row.get('signal_id')}


def build_sim_args(args: argparse.Namespace) -> argparse.Namespace:
    return argparse.Namespace(
        horizon=args.horizon,
        stop_pct=args.stop_pct,
        roundtrip_cost_pct=args.roundtrip_cost_pct,
        max_gap_down_pct=args.max_gap_down_pct,
        max_gap_up_pct=args.max_gap_up_pct,
        bb_period=args.bb_period,
        rsi_period=args.rsi_period,
        exit_rsi=args.exit_rsi,
    )


def outcome_stats(rows: list[dict]) -> dict:
    vals = []
    for row in rows:
        outcome = row.get('outcome') or {}
        value = outcome.get('net_return_after_cost')
        if value is not None:
            try:
                vals.append(float(value))
            except Exception:
                pass
    if not vals:
        return {'resolved': 0, 'avg_net_return_after_cost': None, 'median_net_return_after_cost': None, 'win_rate_after_cost': None}
    return {
        'resolved': len(vals),
        'avg_net_return_after_cost': mean(vals),
        'median_net_return_after_cost': median(vals),
        'win_rate_after_cost': sum(1 for v in vals if v > 0) / len(vals),
    }


def update_outcomes(args: argparse.Namespace) -> dict:
    observations = load_jsonl(Path(args.ledger))
    completed_ids = existing_outcome_ids(Path(args.outcomes))
    sim_args = build_sim_args(args)
    now = datetime.now(KST).isoformat()
    new_outcomes = []
    pending = []
    skipped = {'already_completed': 0, 'missing_signal_id': 0, 'missing_symbol_or_date': 0, 'signal_date_not_in_db': 0, 'insufficient_future_candles': 0}

    for obs in observations:
        signal_id = obs.get('signal_id')
        if not signal_id:
            skipped['missing_signal_id'] += 1
            continue
        if signal_id in completed_ids:
            skipped['already_completed'] += 1
            continue
        symbol = obs.get('symbol')
        signal_date = obs.get('signal_date')
        if not symbol or not signal_date:
            skipped['missing_symbol_or_date'] += 1
            continue
        candles = cached_candles_readonly(args.source_db, symbol)
        idx = signal_index(candles, str(signal_date))
        if idx is None:
            skipped['signal_date_not_in_db'] += 1
            pending.append({'signal_id': signal_id, 'symbol': symbol, 'signal_date': signal_date, 'status': 'pending_signal_date_not_in_db'})
            continue
        future_bars = len(candles) - 1 - idx
        required_future_bars = 1 + args.horizon
        if future_bars < required_future_bars:
            skipped['insufficient_future_candles'] += 1
            pending.append({
                'signal_id': signal_id,
                'symbol': symbol,
                'signal_date': signal_date,
                'status': 'pending_horizon',
                'future_bars': future_bars,
                'required_future_bars': required_future_bars,
                'last_available_date': candles[-1]['timestamp'] if candles else None,
            })
            continue
        outcome = simulate_trade(candles, idx, obs.get('features') or {}, sim_args)
        if outcome is None:
            row = {
                'signal_id': signal_id,
                'observed_at_kst': now,
                'mode': 'paper_only_forward_outcome_no_send',
                'hypothesis_id': obs.get('hypothesis_id', args.hypothesis_id),
                'symbol': symbol,
                'signal_date': signal_date,
                'paper_only': True,
                'order_sent': False,
                'live_order_allowed': False,
                'outcome_status': 'skipped_entry_gap_filter',
                'reason': 'entry gap filter rejected the paper entry; no trade outcome counted',
                'source_observation': obs,
            }
        else:
            row = {
                'signal_id': signal_id,
                'observed_at_kst': now,
                'mode': 'paper_only_forward_outcome_no_send',
                'hypothesis_id': obs.get('hypothesis_id', args.hypothesis_id),
                'symbol': symbol,
                'signal_date': signal_date,
                'paper_only': True,
                'order_sent': False,
                'live_order_allowed': False,
                'outcome_status': 'resolved',
                'outcome': outcome,
                'source_observation': obs,
            }
        new_outcomes.append(row)
        completed_ids.add(signal_id)

    outcomes_path = Path(args.outcomes)
    outcomes_path.parent.mkdir(parents=True, exist_ok=True)
    outcomes_path.touch(exist_ok=True)
    if new_outcomes:
        with outcomes_path.open('a') as f:
            for row in new_outcomes:
                f.write(json.dumps(row, ensure_ascii=False, default=str) + '\n')

    all_outcomes = load_jsonl(outcomes_path)
    resolved = [row for row in all_outcomes if row.get('outcome_status') == 'resolved']
    report = {
        'observed_at_kst': now,
        'mode': 'paper_only_forward_outcome_update_no_send',
        'live_order_allowed': False,
        'hypothesis_id': args.hypothesis_id,
        'ledger': args.ledger,
        'outcomes': args.outcomes,
        'observations_seen': len(observations),
        'new_outcomes': len(new_outcomes),
        'pending_count': len(pending),
        'pending': pending[:50],
        'skipped': skipped,
        'resolved_stats_all_outcomes': outcome_stats(resolved),
        'manual_approval_required': True,
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description='Resolve V3 forward-watch paper outcomes after enough future candles exist. No orders are sent.')
    ap.add_argument('--source-db', default='data/edge_research_universe_long.sqlite3')
    ap.add_argument('--ledger', default='data/rsi_bbands_v3_forward_observations.jsonl')
    ap.add_argument('--outcomes', default='data/rsi_bbands_v3_forward_outcomes.jsonl')
    ap.add_argument('--out', default='data/rsi_bbands_v3_forward_outcome_latest.json')
    ap.add_argument('--hypothesis-id', default='RSI_BBANDS_MEAN_REVERSION_H20_V3_BBZ_VOLUME_GUARD')
    ap.add_argument('--horizon', type=int, default=20)
    ap.add_argument('--stop-pct', default='0.10')
    ap.add_argument('--roundtrip-cost-pct', default='0.0046')
    ap.add_argument('--max-gap-down-pct', default='-0.10')
    ap.add_argument('--max-gap-up-pct', default='0.08')
    ap.add_argument('--bb-period', type=int, default=20)
    ap.add_argument('--rsi-period', type=int, default=14)
    ap.add_argument('--exit-rsi', default='55')
    args = ap.parse_args()
    report = update_outcomes(args)
    print(json.dumps({
        'out': args.out,
        'outcomes': args.outcomes,
        'observations_seen': report['observations_seen'],
        'new_outcomes': report['new_outcomes'],
        'pending_count': report['pending_count'],
        'resolved_stats_all_outcomes': report['resolved_stats_all_outcomes'],
        'live_order_allowed': False,
    }, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
