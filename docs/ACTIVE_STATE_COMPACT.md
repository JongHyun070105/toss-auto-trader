# Active state compact

Last updated: 2026-06-24

## Safety

- Real orders are still blocked.
- `order-dry-run` now forces `dry_run=True`, `live_trading=False` internally.
- Long loop exports `TOSS_DRY_RUN=true` and `TOSS_LIVE_TRADING=false`.
- Current live/paper candidate file always marks:
  - `live_order_allowed: false`
  - `manual_approval_required: true`

## Running process

Current long-running paper-only supervisor:

```text
session_id: proc_1f1a5d3b2142
command: scripts/continuous_paper_improvement.sh 24 3600
```

Old loops intentionally killed/restarted:

```text
proc_1601a1684268 killed
proc_76b9c7e99ea5 killed
proc_77c80719d618 killed
proc_130f2a9bf894 completed/not_found in later continuation; restarted as proc_da2976773b80
proc_da2976773b80 killed to load observation guard + Naver ETF NAV fallback; restarted as proc_0437165a82cf
proc_0437165a82cf killed to load token health, spread-history/dynamic-slippage, and observation penalty updates; restarted as proc_63f229c67a19
proc_63f229c67a19 ended/not_found; verified depth/time-window/stale/multi-cap/stress loop restarted as proc_7d94042a56b2
proc_7d94042a56b2 ended/not_found; edge-audit/volume-shock hypothesis loop restarted as proc_1f1a5d3b2142
```

## Current candidate policy

Candidate source priority:

1. walk-forward stable-positive results
2. shared/isolated grid results

Latest watchlist file:

```text
data/live_paper_candidates.json
```

Top walk-forward candidate after latest validation:

```text
pair: 204620:6000 + 032620:4000
mode: shared_account
branch: balanced_momentum
window: 40
horizon: 5
train_pnl: +973.219208
validation_pnl: +905.603672
status: watchlist_not_live_order
```

Top isolated-slot walk-forward candidate:

```text
pair: 204620:6000 + 462860:4000
mode: isolated_slots
branch: balanced_momentum
window: 40
horizon: 5
train_pnl: +186.7680335
validation_pnl: +524.3769045
status: watchlist_not_live_order
```

## Implemented

- Ponytail installed for agy; Hermes local `ponytail` skill applied.
- 10,000 KRW low-capital screener.
- Toss candle cache + historical replay.
- `portfolio-pair-backtest`.
- Timestamp intersection alignment.
- Fee/tax cash accounting in `PaperBroker`.
- `paper_orders.fee_amount`, `paper_orders.tax_amount`.
- `news_analyst` added to agent opinions.
- `strategy_registry`.
- Shared-account and `--isolated-slots` pair modes.
- `--compact-events`: skips ordinary HOLD decision_events to reduce DB size.
- `PaperBroker` reuse inside pair backtest loop.
- `--exclude-last-bars` for walk-forward splitting.
- Fixed slippage model via `execution.buy_slippage_pct` and `execution.sell_slippage_pct`.
- Read-only `orderbook --symbol` spread check using Toss `/api/v1/orderbook`.
- `backtest_aggregates` table stores compact HOLD aggregate counts.
- `scripts/spread_guard_candidates.py` updates watchlist status from live orderbook spreads; default block threshold is 30bp.
- `scripts/pre_live_order_checklist.py` verifies candidate readiness without sending any order.
- `scripts/paper_observe_candidates.py` records live/read-only candidate observations to `data/paper_observations.jsonl`; order_sent is always false.
- `scripts/etf_guard_collector.py` writes `data/etf_guard_latest.json`; it collects NAV/disparity from Naver ETF tables when KRX returns LOGOUT, and uses spread as LP proxy while labeling missing LP contract.
- `scripts/observation_guard_candidates.py` requires recent paper-only observations to be stable before human pre-live review.
- `scripts/summarize_improvement_results.py` writes `data/improvement_summary_latest.json`.
- `scripts/pair_grid_runner.py`.
- `scripts/walk_forward_runner.py`.
- `scripts/update_candidates_from_grid.py` now prefers walk-forward stable candidates.
- `scripts/update_candidates_from_grid.py` dedupes candidates by pair+mode+source so top-N is not filled with clones of one idea.
- `scripts/toss_token_health.py` writes `data/toss_token_health_latest.json` and append-only `data/toss_token_health_history.jsonl`, checking token issuance plus candidate-symbol orderbook access.
- `scripts/spread_guard_candidates.py` appends `data/spread_history.jsonl`, gates recent N max/avg spread, computes 5-level market impact/depth, records future capital impact for 10k/100k/1M, and can enforce stale orderbook timestamps.
- `scripts/dynamic_slippage_from_spread.py` writes `data/dynamic_execution_costs.json` from half of recent max spread as a one-way slippage estimate.
- `scripts/paper_observe_candidates.py` classifies token/spread/candle/stale/market-impact failures, uses one client per run, and skips normal observation outside 09:05~15:20 KST.
- `scripts/multi_capital_runner.py` compares 10k/30k/100k/1M+ virtual capitals; `pair_grid_runner.py --capital` scales pair slots from the 6:4 base.
- `scripts/dynamic_slippage_grid_runner.py` regenerates a config from recent spread-derived slippage and reruns grid backtests.
- `scripts/strategy_edge_audit.py` writes `data/strategy_edge_audit_latest.json`; it documents the current weak momentum hypothesis and checks BUY signal count, post-cost forward return, win rate, and pair correlation.
- `scripts/stress_test_candidates.py` writes `data/stress_test_latest.json` with -3/-5/-10% shock and 90d MDD proxy checks.
- `scripts/strategy_edge_guard_candidates.py` blocks candidates whose strict edge audit does not pass.
- `scripts/volume_shock_hypothesis_audit.py` tests a separate volume-shock continuation hypothesis for research.
- `scripts/update_candidates_from_grid.py` applies observation, spread-history, and edge penalties to candidate ranking.
- `scripts/summarize_improvement_results.py` writes explicit blocker_reasons.
- `scripts/continuous_paper_improvement.sh` runs shared grid, isolated grid, shared walk-forward, isolated walk-forward each cycle.

## Key files

```text
src/toss_auto_trader/cli.py
src/toss_auto_trader/decision_engine.py
src/toss_auto_trader/paper.py
src/toss_auto_trader/agents.py
scripts/pair_grid_runner.py
scripts/walk_forward_runner.py
scripts/update_candidates_from_grid.py
scripts/continuous_paper_improvement.sh
docs/CONTINUOUS_PAPER_IMPROVEMENT.md
docs/PORTFOLIO_PAIR_BACKTEST.md
docs/LOW_CAPITAL_SELECTION.md
```

## Known remaining risks

- Historical order timestamps now use candle timestamps via `PaperBroker.simulated_now`.
- Live orderbook spread check exists; historical replay still uses fixed slippage, not historical orderbook.
- No-send pre-live checklist can require spread, observation, stress, and strategy-edge guards; live send path still does not exist.
- Current strict edge audit found 0/10 candidates with all-leg post-cost edge; volume-shock research hypothesis shows possible evidence for 204620 and 073240, but 073240 remains hard to trade because of spread.
- ETF NAV/disparity can be collected from Naver ETF tables; KRX direct endpoint currently returns LOGOUT and KRX MDCSTAT241 LP contract page is identified but direct JSON returns 400/LOGOUT in this environment, so LP contract remains a labeled spread-proxy rather than official contract evidence.
- Candidate readiness uses observation_guard; recent token self-invalidation was fixed by using one Toss client per paper observation run, and remaining blocks are separated into token/spread/candle categories.
- Compact HOLD aggregate counts are stored in `backtest_aggregates`, but no per-candle HOLD detail is retained in compact mode.
- Current watchlist is paper-only; live order requires a separate explicit approval flow. Pre-checklist exists, but no live send path has been implemented.
