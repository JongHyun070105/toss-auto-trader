#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import time
from pathlib import Path


def report_complete(path: Path) -> bool:
    if not path.exists():
        return False
    data = json.loads(path.read_text())
    done = int(data.get('ok_count') or 0) + int(data.get('skipped_existing_count') or 0) + int(data.get('failed_count') or 0)
    return done >= int(data.get('requested_symbols') or 10**12)


def db_summary(db_path: str) -> dict:
    if not Path(db_path).exists():
        return {'exists': False}
    con = sqlite3.connect(db_path)
    try:
        row = con.execute("SELECT COUNT(*), COUNT(DISTINCT symbol), MIN(timestamp), MAX(timestamp) FROM candle_cache WHERE interval='1d'").fetchone()
        counts = con.execute("SELECT MIN(c), AVG(c), MAX(c) FROM (SELECT COUNT(*) c FROM candle_cache WHERE interval='1d' GROUP BY symbol)").fetchone()
        return {'exists': True, 'count': row[0], 'symbols': row[1], 'min_timestamp': row[2], 'max_timestamp': row[3], 'per_symbol_min_avg_max': counts}
    finally:
        con.close()


def run_cmd(cmd: list[str], timeout: int = 1800) -> dict:
    env = os.environ.copy()
    env['PYTHONPATH'] = 'src'
    proc = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, timeout=timeout)
    return {'cmd': cmd, 'returncode': proc.returncode, 'stdout_tail': proc.stdout[-4000:], 'stderr_tail': proc.stderr[-4000:]}


def compact_json(path: str) -> dict:
    if not Path(path).exists():
        return {'exists': False}
    d = json.loads(Path(path).read_text())
    if 'equal_weight_universe_buy_hold' in d:
        return {
            'exists': True,
            'cash_baseline': d.get('cash_baseline'),
            'kosdaq_index_baseline': d.get('kosdaq_index_baseline'),
            'equal_weight_universe_buy_hold': d.get('equal_weight_universe_buy_hold'),
        }
    if 'candidate_count' in d and 'candidates' in d:
        return {
            'exists': True,
            'mode': d.get('mode'),
            'live_order_allowed': d.get('live_order_allowed'),
            'hypothesis_id': d.get('hypothesis_id'),
            'candidate_count': d.get('candidate_count'),
            'symbols_scanned': d.get('symbols_scanned'),
            'skipped': d.get('skipped'),
            'top_candidates': d.get('candidates', [])[:5],
        }
    if 'resolved_stats_all_outcomes' in d:
        return {
            'exists': True,
            'mode': d.get('mode'),
            'live_order_allowed': d.get('live_order_allowed'),
            'hypothesis_id': d.get('hypothesis_id'),
            'observations_seen': d.get('observations_seen'),
            'new_outcomes': d.get('new_outcomes'),
            'pending_count': d.get('pending_count'),
            'skipped': d.get('skipped'),
            'resolved_stats_all_outcomes': d.get('resolved_stats_all_outcomes'),
        }
    if d.get('mode') == 'research_only_no_send_relative_strength_horizon_audit':
        return {
            'exists': True,
            'mode': d.get('mode'),
            'hypothesis_id': d.get('hypothesis_id'),
            'live_order_allowed': d.get('live_order_allowed'),
            'edge_ok_same_history_only': d.get('edge_ok_same_history_only'),
            'symbols_loaded': d.get('symbols_loaded'),
            'rebalance_months': d.get('rebalance_months'),
            'blockers': d.get('blockers'),
            'evaluation': d.get('evaluation'),
            'concentration': d.get('concentration'),
        }
    if d.get('mode') == 'research_only_no_send_event_liquidity_reaction_audit':
        return {
            'exists': True,
            'mode': d.get('mode'),
            'hypothesis_id': d.get('hypothesis_id'),
            'live_order_allowed': d.get('live_order_allowed'),
            'edge_ok_same_history_only': d.get('edge_ok_same_history_only'),
            'news_source_rows': d.get('news_source_rows'),
            'mapped_news_events': d.get('mapped_news_events'),
            'evaluable_event_signals': d.get('evaluable_event_signals'),
            'pending_future_event_signals': d.get('pending_future_event_signals'),
            'unique_event_symbols': d.get('unique_event_symbols'),
            'blockers': d.get('blockers'),
            'evaluation': d.get('evaluation'),
        }
    if d.get('mode') == 'research_only_no_send_regime_exposure_gate_audit':
        return {
            'exists': True,
            'mode': d.get('mode'),
            'hypothesis_id': d.get('hypothesis_id'),
            'live_order_allowed': d.get('live_order_allowed'),
            'index_rows': d.get('index_rows'),
            'horizons': d.get('horizons'),
            'gate_reports': [
                {
                    'gate': g.get('gate'),
                    'candidate_ok_same_history_only': g.get('candidate_ok_same_history_only'),
                    'blockers': g.get('blockers'),
                    'h20_locked_test': (g.get('forward_by_horizon') or {}).get('h20', {}).get('locked_test'),
                    'equity_locked_test': (g.get('daily_equity_sim') or {}).get('locked_test'),
                }
                for g in d.get('gate_reports', [])
            ],
        }
    if d.get('mode') == 'research_only_no_send_regime_first_diagnostic':
        return {
            'exists': True,
            'mode': d.get('mode'),
            'live_order_allowed': d.get('live_order_allowed'),
            'signals_loaded': d.get('signals_loaded'),
            'strategy_summary': d.get('strategy_summary'),
            'gate_diagnostics': d.get('gate_diagnostics', [])[:4],
            'next_policy': d.get('next_policy'),
        }
    if 'summary' in d and 'aggregate' in d['summary']:
        a = d['summary']['aggregate']
        return {
            'exists': True,
            'edge_ok': d['summary'].get('edge_ok'),
            'blockers': d['summary'].get('blockers'),
            'all': a.get('all'),
            'locked_test': a.get('locked_test'),
            'distribution': a.get('distribution'),
        }
    if 'locked_test' in d and 'all' in d:
        return {'exists': True, 'all': d.get('all'), 'locked_test': d.get('locked_test')}
    return {'exists': True, 'keys': list(d)[:20]}


def main() -> int:
    ap = argparse.ArgumentParser(description='Wait for long cache, then run no-send research audits.')
    ap.add_argument('--cache-report', default='data/universe_cache_long_latest.json')
    ap.add_argument('--db-path', default='data/edge_research_universe_long.sqlite3')
    ap.add_argument('--poll-seconds', type=int, default=60)
    ap.add_argument('--out', default='data/post_collection_research_summary.json')
    args = ap.parse_args()

    while not report_complete(Path(args.cache_report)):
        time.sleep(max(10, args.poll_seconds))

    commands = [
        ['python3', 'scripts/market_baseline_report.py', '--source-db', args.db_path, '--fetch-naver-kosdaq', '--out', 'data/market_baseline_latest.json'],
        ['python3', 'scripts/volume_shock_hypothesis_audit.py', '--source-db', args.db_path, '--symbols', 'cached', '--strategy', 'breakout', '--horizon', '3', '--min-symbols', '100', '--min-signal-symbols', '100', '--min-total-signals', '300', '--min-test-signals', '100', '--max-symbol-signal-share', '0.05', '--max-month-signal-share', '0.35', '--require-baseline-outperformance', '--require-locked-test-median-nonnegative', '--require-equal-weight-positive', '--out', 'data/volume_shock_long_preregistered.json', '--symbols-dist-out', 'data/volume_shock_long_preregistered_dist.csv', '--signals-out', 'data/volume_shock_long_preregistered_signals.csv'],
        ['python3', 'scripts/volume_shock_portfolio_backtest.py', '--source-db', args.db_path, '--symbols', 'cached', '--strategy', 'breakout', '--horizon', '3', '--initial-cash', '1000000', '--max-positions', '5', '--position-fraction', '0.20', '--max-daily-entries', '3', '--out', 'data/volume_shock_long_portfolio.json'],
        ['python3', 'scripts/pullback_after_trend_audit.py', '--source-db', args.db_path, '--symbols', 'cached', '--require-baseline-outperformance', '--require-locked-test-median-nonnegative', '--require-equal-weight-positive', '--out', 'data/pullback_after_trend_long.json', '--symbols-dist-out', 'data/pullback_after_trend_long_dist.csv', '--signals-out', 'data/pullback_after_trend_long_signals.csv'],
        ['python3', 'scripts/volume_shock_reversal_audit.py', '--source-db', args.db_path, '--symbols', 'cached', '--long-entry-strategy', 'continuation', '--horizon', '3', '--min-symbols', '100', '--min-signal-symbols', '100', '--min-total-signals', '300', '--min-test-signals', '100', '--max-symbol-signal-share', '0.05', '--max-month-signal-share', '0.35', '--require-baseline-outperformance', '--require-locked-test-median-nonnegative', '--require-equal-weight-positive', '--out', 'data/volume_shock_reversal_posthoc.json', '--symbols-dist-out', 'data/volume_shock_reversal_posthoc_dist.csv'],
        ['python3', 'scripts/rsi_bbands_mean_reversion_audit.py', '--source-db', args.db_path, '--symbols', 'cached', '--require-locked-test-median-nonnegative', '--require-equal-weight-positive', '--out', 'data/rsi_bbands_mean_reversion_h20_v1.json', '--signals-out', 'data/rsi_bbands_mean_reversion_h20_v1_signals.csv'],
        ['python3', 'scripts/rsi_bbands_mean_reversion_audit.py', '--source-db', args.db_path, '--symbols', 'cached', '--hypothesis-id', 'RSI_BBANDS_MEAN_REVERSION_H20_V3_BBZ_VOLUME_GUARD', '--hypothesis-status', 'post_hoc_guard_candidate_from_trade_diagnostics_requires_future_holdout', '--min-bb-z', '-2.5', '--max-volume-multiple', '2.5', '--require-locked-test-median-nonnegative', '--require-equal-weight-positive', '--out', 'data/rsi_bbands_mean_reversion_h20_v3_bbz_volume_guard.json', '--signals-out', 'data/rsi_bbands_mean_reversion_h20_v3_bbz_volume_guard_signals.csv'],
        ['python3', 'scripts/market_regime_signal_audit.py', '--signals', 'RSI_BBANDS_H20_V1=data/rsi_bbands_mean_reversion_h20_v1_signals.csv', '--signals', 'RSI_BBANDS_H20_V3=data/rsi_bbands_mean_reversion_h20_v3_bbz_volume_guard_signals.csv', '--signals', 'VOLUME_SHOCK_BREAKOUT_H3=data/volume_shock_long_preregistered_signals.csv', '--signals', 'PULLBACK_TREND_H5=data/pullback_after_trend_long_signals.csv', '--out', 'data/market_regime_signal_audit_latest.json', '--rows-out', 'data/market_regime_signal_audit_rows.csv'],
        ['python3', 'scripts/market_regime_exposure_gate_audit.py', '--out', 'data/market_regime_exposure_gate_latest.json', '--rows-out', 'data/market_regime_exposure_gate_rows.csv'],
        ['python3', 'scripts/relative_strength_horizon_audit.py', '--source-db', args.db_path, '--out', 'data/relative_strength_horizon_latest.json', '--baskets-out', 'data/relative_strength_horizon_baskets.csv', '--signals-out', 'data/relative_strength_horizon_signals.csv'],
        ['python3', 'scripts/event_liquidity_reaction_audit.py', '--source-db', args.db_path, '--news-db', 'data/news_context_latest.sqlite3', '--symbol-map', 'research/news_event_symbol_map.csv', '--allowed-markets', 'KOSDAQ', '--out', 'data/event_liquidity_reaction_latest.json', '--rows-out', 'data/event_liquidity_reaction_rows.csv', '--pending-out', 'data/event_liquidity_reaction_pending.jsonl'],
        ['python3', 'scripts/rsi_bbands_v3_forward_watch.py', '--source-db', args.db_path, '--symbols', 'cached', '--limit', '50', '--out', 'data/rsi_bbands_v3_forward_candidates_latest.json', '--ledger', 'data/rsi_bbands_v3_forward_observations.jsonl'],
        ['python3', 'scripts/rsi_bbands_v3_forward_outcome_update.py', '--source-db', args.db_path, '--ledger', 'data/rsi_bbands_v3_forward_observations.jsonl', '--outcomes', 'data/rsi_bbands_v3_forward_outcomes.jsonl', '--out', 'data/rsi_bbands_v3_forward_outcome_latest.json'],
    ]

    steps = []
    for cmd in commands:
        steps.append(run_cmd(cmd))
    summary = {
        'mode': 'research_only_no_send',
        'db': db_summary(args.db_path),
        'steps': steps,
        'market_baseline': compact_json('data/market_baseline_latest.json'),
        'volume_shock_long': compact_json('data/volume_shock_long_preregistered.json'),
        'volume_shock_portfolio_long': compact_json('data/volume_shock_long_portfolio.json'),
        'pullback_long': compact_json('data/pullback_after_trend_long.json'),
        'volume_shock_reversal_posthoc': compact_json('data/volume_shock_reversal_posthoc.json'),
        'market_regime_signal_audit': compact_json('data/market_regime_signal_audit_latest.json'),
        'market_regime_exposure_gate': compact_json('data/market_regime_exposure_gate_latest.json'),
        'relative_strength_horizon': compact_json('data/relative_strength_horizon_latest.json'),
        'event_liquidity_reaction': compact_json('data/event_liquidity_reaction_latest.json'),
        'rsi_bbands_v3_forward_watch': compact_json('data/rsi_bbands_v3_forward_candidates_latest.json'),
        'rsi_bbands_v3_forward_outcomes': compact_json('data/rsi_bbands_v3_forward_outcome_latest.json'),
    }
    Path(args.out).write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
