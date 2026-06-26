# Active state compact

Last updated: 2026-06-25

## Safety

- Real orders are still blocked.
- `order-dry-run` now forces `dry_run=True`, `live_trading=False` internally.
- `order-live-send` exists as a separate gated command, but current candidates still block live sending unless `live_order_allowed=true`, all pre-live gates pass, exact fingerprint confirmation is supplied, and live env flags are enabled.
- Long loop exports `TOSS_DRY_RUN=true` and `TOSS_LIVE_TRADING=false`.
- Current live/paper candidate file always marks:
  - `live_order_allowed: false`
  - `manual_approval_required: true`

## Running process

Current long-running paper-only supervisor:

```text
session_id: proc_9ec36692cdec
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
proc_1f1a5d3b2142 superseded/not_found; strict fixed-horizon/sample-size volume-shock audit loop restarted as proc_9ec36692cdec
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
- `scripts/volume_shock_hypothesis_audit.py` now uses a fixed horizon, minimum universe size, minimum total signals, locked test split, signal-symbol/month concentration gates, equal-weight-by-symbol diagnostics, positive-candle baseline comparison, locked-test median/equal-weight blockers, entry/exit timestamps, and gap-aware breakout fills (`gap_fill_next_open` vs `intraday_breakout_trigger_fill`) for portfolio simulation; small-sample symbol positives are diagnostics only.
- `scripts/volume_shock_portfolio_backtest.py` simulates no-send portfolio constraints for locked volume-shock signals: max positions, max daily entries, position sizing, rejection reasons, and locked-test portfolio performance.
- `scripts/volume_shock_reversal_audit.py` tests the failed volume-shock long signal as a post-hoc short/avoid proxy. It is explicitly `post_hoc_exploratory_requires_future_holdout` and cannot approve live trading.
- `scripts/market_baseline_report.py` writes cash, local equal-weight universe buy-and-hold, explicit CSV, or Naver Stock API KOSDAQ index baselines. If the index fetch fails, it reports unavailable fail-closed instead of silently substituting a fake benchmark.
- `scripts/export_ai_trader_data.py` exports local Toss candle cache rows to ai-trader-compatible OHLCV CSV and can fetch KOSDAQ index CSV from Naver. Use ai-trader as an external optional GPL-3.0 engine, not vendored project code.
- `scripts/ai_trader_universe_sweep.py` runs external ai-trader classic strategies over as-of KR universes with KR commission/tax/slippage/spread assumptions, yearly/rolling/full windows, KOSDAQ excess return, return/MDD, and return/volatility metrics. Results are exploratory-only and require future holdout.
- `scripts/regime_low_vol_breakout_audit.py` tests `REGIME_LOW_VOL_BREAKOUT_H10_V1` as a fixed no-send hypothesis: KOSDAQ regime filter + low-volatility close breakout + volume-shock avoidance + next-open entry and stop/take/horizon exits. First long-history validation failed; keep as rejected unless future evidence changes.
- `scripts/rsi_bbands_mean_reversion_audit.py` tests `RSI_BBANDS_MEAN_REVERSION_H20_V1` derived from the external ai-trader bounded sweep hint. It uses RSI14 <= 30 + close <= Bollinger lower band, KR costs, crash/volume/gap guards, next-open entry, stop/mean-reversion/horizon exits. First validation is the strongest clue so far but still fails promotion due to train and equal-weight blockers; post-hoc V2 market guard worsened results. `RSI_BBANDS_MEAN_REVERSION_H20_V3_BBZ_VOLUME_GUARD` adds a post-hoc `bb_z >= -2.5` falling-knife guard and `volume_multiple <= 2.5`; it improves locked-test average but still fails train gates, so it is future-holdout only.
- `scripts/rsi_bbands_trade_diagnostics.py` reads exported RSI+Bollinger signal CSV and writes post-hoc feature bucket/rule diagnostics; results are V3 design clues, never approval evidence.
- `scripts/rsi_bbands_v3_forward_watch.py` scans latest cached candles for `RSI_BBANDS_MEAN_REVERSION_H20_V3_BBZ_VOLUME_GUARD` forward-watch signals and appends only `order_sent=false` / `live_order_allowed=false` observations. Current latest-cache scan over 1,822 symbols found 0 candidates, which is a valid zero-pick outcome.
- `scripts/rsi_bbands_v3_forward_outcome_update.py` resolves V3 forward-watch observations only after enough future candles exist, writes append-only paper outcomes, and keeps `order_sent=false` / `live_order_allowed=false`. Current empty-ledger run saw 0 observations and 0 resolved outcomes.
- `scripts/market_regime_signal_audit.py` is the new regime-first diagnostic track. It loads timestamped signal CSVs from failed public OHLCV hypotheses and asks whether KOSDAQ regime permits long exposure before another 3d/5d stock-selection search. Current 113,881-signal audit says simple "avoid bad market" is not sufficient: RSI+Bollinger mean-reversion is best in crash/drawdown/mixed regimes, while volume-shock breakout and pullback-after-trend remain negative across most regimes. This blocks more unbounded short-horizon OHLCV tuning and redirects next research to regime exposure gates, 20d/60d horizons, or event-data collection.
- `scripts/market_regime_exposure_gate_audit.py` tests `KOSDAQ_REGIME_EXPOSURE_GATE_H20_H60_V1`: no individual stocks, only KOSDAQ index regime features deciding cash vs broad index exposure. Current 1,590-index-row validation found no same-history gate promotable: `trend_constructive_only` underperformed, `rebound_crash_drawdown_mixed` underperformed, and `avoid_weak_downtrend_only` slightly improved H20 forward average but lost to always-long in locked-test daily equity after switch costs. Keep as rejected/diagnostic; do not freeze a gate yet.
- `scripts/relative_strength_horizon_audit.py` tests `RELATIVE_STRENGTH_H60_H20_H60_V1`: monthly top-20 KOSDAQ stocks by 60d relative strength, with as-of price/turnover/SMA120 filters, next-open entry, 20d/60d exits, and full eligible-universe + KOSDAQ baselines. It failed clearly: locked-test H20 top avg -1.98% vs eligible universe +0.72% and KOSDAQ +2.13%; locked-test H60 top avg +3.30% but eligible universe +5.92% and KOSDAQ +7.35%. This blocks more pure OHLCV top-N cross-sectional sweeps unless the universe becomes delisted-inclusive or a new data source is added.
- `scripts/event_liquidity_reaction_audit.py` runs the event/news/liquidity data track: it maps cached `news_context` rows via `research/news_event_symbol_map.csv`, can restrict map rows by `--allowed-markets` (post-collection uses KOSDAQ to avoid KOSPI symbols missing from the KOSDAQ candle cache), requires positive catalyst keywords plus event-day volume >= 1.5x prior 20d average, uses next-open entry and H3 exit, compares to same-date eligible-universe baseline, writes pending future-horizon candidates to `data/event_liquidity_reaction_pending.jsonl`, and always reports `paper_only=true`, `order_sent=false`, `live_order_allowed=false`. Current run after news dedupe and catalyst-query collection: 83 news rows -> 44 mapped events -> 2 evaluable fixed signals, 0 pending future signals. It still fails closed: only 1 unique event symbol and locked-test return/excess are negative.
- `research/strategy_research_policy.json` blocks infinite same-history optimization, blocks new 3d/5d public-price stock-selection hypotheses before regime exposure diagnostics, and requires frozen hypotheses plus unseen/paper-forward validation before any pre-live review.
- `docs/AI_TRADER_EXTERNAL_SWEEP.md` documents the external GPL boundary, setup, as-of sweep commands, and anti-overfit loop.
- `scripts/pullback_after_trend_audit.py` adds the pre-registered pullback-after-trend hypothesis with SMA20/SMA60 trend, 3-day pullback, RSI14 filter, next-open entry, and horizon-5 locked validation.
- `scripts/no_send_market_watch.py` runs a paper-only/no-send market watch loop for spread, paper observation, observation guard, and pre-live checklist. It never sends orders.
- `scripts/strategy_discovery_loop.py` runs a continuous no-send strategy discovery loop: it refreshes/evaluates multiple strategy artifacts, applies `research/strategy_research_policy.json` thresholds, and can only produce `pre_live_review_candidate_not_live_order`; it never calls `order-live-send`.
- `src/toss_auto_trader/live_order.py` and CLI command `order-live-send` implement the separate live-order approval path. Default is plan-only; real send requires candidate-file live approval, green spread/observation/stress/edge gates, exact candidate fingerprint confirmation, `--really-send`, live env flags, and `--allow-multi-leg` for basket orders.
- `scripts/run_post_collection_research.py` waits for the long universe cache and then runs market baseline, locked no-send research audits, full signal exports, market-regime signal audit, market-regime exposure gate audit, relative-strength horizon audit, V3 forward watch, and V3 outcome update automatically.
- `scripts/cache_universe_candles.py` can build a broad read-only candle cache from a KOSDAQ/universe symbol file for real cross-sectional edge research.
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
- No-send pre-live checklist can require spread, observation, stress, and strategy-edge guards; live send is implemented as a separate gated path but current candidates remain blocked.
- Current strict edge audit found 0/10 candidates with all-leg post-cost edge. The long-history volume-shock audit has now failed after gap-aware breakout execution modeling: locked-test average, median, win rate, and equal-weight checks are not promotable. Portfolio simulation after the gap-fill fix is near-total loss, so live trading remains blocked.
- Reversal/avoid research is allowed only as post-hoc exploratory work: `volume_shock_reversal_audit.py` may identify avoid/penalty signals, but any promotion requires future holdout or paper-only forward validation.
- KOSDAQ index baseline is available through Naver Stock API in `market_baseline_report.py`, with CSV override available. If index fetch fails, the script reports unavailable fail-closed and still reports equal-weight universe buy-and-hold as a separate local baseline, not as a cap-weighted KOSDAQ substitute.
- ETF NAV/disparity can be collected from Naver ETF tables; KRX direct endpoint currently returns LOGOUT and KRX MDCSTAT241 LP contract page is identified but direct JSON returns 400/LOGOUT in this environment, so LP contract remains a labeled spread-proxy rather than official contract evidence.
- Candidate readiness uses observation_guard; recent token self-invalidation was fixed by using one Toss client per paper observation run, and remaining blocks are separated into token/spread/candle categories.
- Compact HOLD aggregate counts are stored in `backtest_aggregates`, but no per-candle HOLD detail is retained in compact mode.
- Current watchlist is paper-only; a gated live-send command exists, but current candidates do not pass the required live approval, edge, observation, and stress gates, so live orders remain blocked.
