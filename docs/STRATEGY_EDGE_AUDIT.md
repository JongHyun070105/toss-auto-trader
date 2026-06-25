# Strategy edge audit

## Current honest status

This project has strong execution/risk filters, but the alpha/edge is still weak.

Current strategy hypothesis:

```text
weak momentum continuation with RSI/news/risk veto
```

This means:

- prefer symbols where short/mid moving averages are aligned bullishly,
- avoid overheated RSI,
- avoid negative news/warnings,
- require branch score/confidence thresholds,
- subtract fees/tax/slippage later.

This is not a proven market inefficiency. It is a generic technical momentum hypothesis.

## Current code-level buy logic

From `agents.py` / `decision_engine.py`:

1. `technical_analyst`
   - starts at score 50
   - MA bullish alignment adds +15
   - MA bearish alignment subtracts -20
   - RSI 35~70 adds +10
   - RSI > 80 subtracts -15
   - branch-specific RSI overheat block can subtract more
   - technical action becomes BUY only when score >= branch `technical_buy_score`

2. `risk_manager`
   - does not create alpha; it sets dynamic stop/take values from ATR.

3. `fee_analyst`
   - does not create alpha; it records round-trip cost.

4. `performance_feedback`
   - currently weak: recent win-rate data is mostly placeholder/limited.

5. `news_analyst`
   - simple keyword sentiment; useful as a veto, not alpha.

6. `coordinator`
   - BUY only if technical/performance/news do not HOLD/BLOCK and average score/confidence exceed branch thresholds.

## New gate

`strategy_edge_audit.py` checks each candidate for:

- BUY signal count,
- post-cost forward return,
- win rate after cost,
- whether every leg in a long-only basket has a positive audited edge,
- whether the pair is a true pair or just an independent long basket.

Important: passing an audit is not causal proof. The audit is only a blocker/triage layer. It must be strict enough to avoid approving lucky small-sample results.

Outputs:

```text
data/strategy_edge_audit_latest.json
```

The result is now attached to candidate ranking as:

```text
edge_audit
edge_penalty_score
```

If edge is not established, the candidate gets penalized before ranking and can fail pre-live checklist.

## Pair caveat

Most current `A+B` candidates are not statistical pair trades. They are usually independent long baskets split by tiny capital. A real pair trade would need sector/correlation/cointregration rationale. Current pair correlation is diagnostic only.

## Next real alpha work

Do not add more guards before choosing a real hypothesis. Candidate hypotheses to test next:

1. Volume shock continuation
   - yesterday volume >= 3x 20d average
   - candle closes positive
   - next 1~3 days net return after cost positive

2. Pullback after trend
   - 20d/60d trend up
   - 2~3 day pullback to MA20
   - RSI not overheated

3. News/filing catalyst continuation
   - positive catalyst keyword + abnormal volume
   - restrict to liquid names only

Each hypothesis should be tested alone, with a locked train/test split and minimum signal count before touching live orders.


## Statistical guardrails added after review

The first volume-shock version was too loose: it looked at 1/3/5 day horizons and could mark a symbol as interesting from a tiny sample. That creates horizon fishing and small-sample selection bias.

Current rules:

- horizon is fixed before validation; default is `--horizon 3`.
- no “best of 1/3/5” selection is allowed for edge_ok.
- global edge requires enough cross-sectional symbols; default `--min-symbols 50`.
- global edge requires enough aggregate signals; default `--min-total-signals 100`.
- locked chronological test split must have enough signals; default `--min-test-signals 30`.
- optional concentration gates can block symbol/month-dominated results:
  - `--min-signal-symbols N`
  - `--max-symbol-signal-share 0.05`
  - `--max-month-signal-share 0.35`
- `--require-baseline-outperformance` compares the locked-test signal average against a positive-candle baseline with the volume threshold removed. If volume shock does not beat this simple placebo, edge remains unestablished.
- report output includes median return, monthly distribution, top symbol contribution, and equal-weight-by-symbol stats so one lucky symbol/month cannot hide weak global behavior.
- symbol-level positives are diagnostics only, not approval.

Until KOSDAQ-wide or otherwise broad cached candles exist, `volume_shock_hypothesis_audit.py` should normally output `edge_ok=false` with blockers such as `insufficient_universe_symbols` or `insufficient_total_signals`.

To build a broad research cache without live orders:

```bash
# one KOSDAQ/Toss/KRX symbol per line; no secrets in this file
python3 scripts/cache_universe_candles.py \
  --symbols-file research/kosdaq_symbols.txt \
  --db-path data/edge_research_universe.sqlite3 \
  --count 200 \
  --sleep-seconds 2

python3 scripts/volume_shock_hypothesis_audit.py \
  --source-db data/edge_research_universe.sqlite3 \
  --symbols cached \
  --horizon 3 \
  --min-symbols 50 \
  --min-total-signals 100 \
  --min-test-signals 30
```

Stricter research command before promoting any hypothesis:

```bash
python3 scripts/volume_shock_hypothesis_audit.py \
  --source-db data/edge_research_universe.sqlite3 \
  --symbols cached \
  --strategy breakout \
  --horizon 3 \
  --min-symbols 100 \
  --min-signal-symbols 100 \
  --min-total-signals 300 \
  --min-test-signals 100 \
  --max-symbol-signal-share 0.05 \
  --max-month-signal-share 0.35 \
  --require-baseline-outperformance \
  --require-locked-test-median-nonnegative \
  --require-equal-weight-positive
```

Additional no-send research tools:

```bash
# local market baseline; fetches KOSDAQ from Naver when requested, CSV can override
python3 scripts/market_baseline_report.py \
  --source-db data/edge_research_universe.sqlite3 \
  --fetch-naver-kosdaq \
  --out data/market_baseline_latest.json

# portfolio feasibility layer for the locked volume-shock signal
python3 scripts/volume_shock_portfolio_backtest.py \
  --source-db data/edge_research_universe.sqlite3 \
  --symbols cached \
  --strategy breakout \
  --horizon 3 \
  --initial-cash 1000000 \
  --max-positions 5 \
  --position-fraction 0.20 \
  --max-daily-entries 3

# post-hoc reversal/avoid proxy; not a clean pre-registration and not live-tradable
python3 scripts/volume_shock_reversal_audit.py \
  --source-db data/edge_research_universe.sqlite3 \
  --symbols cached \
  --long-entry-strategy continuation \
  --horizon 3 \
  --require-baseline-outperformance \
  --require-locked-test-median-nonnegative \
  --require-equal-weight-positive

# separate pre-registered hypothesis; do not tune after seeing locked results
python3 scripts/pullback_after_trend_audit.py \
  --source-db data/edge_research_universe.sqlite3 \
  --symbols cached \
  --require-baseline-outperformance \
  --require-locked-test-median-nonnegative \
  --require-equal-weight-positive
```

For long-history runs, `scripts/run_post_collection_research.py` can wait for `cache_universe_candles.py` to finish and then run the locked no-send research audits.

External ai-trader engine bridge:

```bash
# Export local Toss candle cache to ai-trader-compatible OHLCV CSV.
# ai-trader itself is GPL-3.0; keep it as an external optional tool unless licensing is reviewed.
python3 scripts/export_ai_trader_data.py \
  --db-path data/edge_research_universe_long.sqlite3 \
  --fetch-kosdaq-index \
  --top-by-trade-value 3 \
  --out-dir data/ai_trader_export \
  --start 2020-10-07 \
  --end 2026-06-24

# Example external run after installing whchien/ai-trader in an isolated venv:
ai-trader quick CrossSMAStrategy data/ai_trader_export/KOSDAQ_INDEX.csv \
  --cash 1000000 \
  --commission 0.0004 \
  --start-date 2020-10-07 \
  --end-date 2026-06-24

# As-of universe sweep with KR cost/tax/slippage assumptions and anti-overfit reporting.
# Run through the external ai-trader venv, not the project venv.
external/ai-trader/.venv/bin/python scripts/ai_trader_universe_sweep.py \
  --db-path data/edge_research_universe_long.sqlite3 \
  --ai-trader-repo external/ai-trader \
  --out data/ai_trader_sweep/latest.json \
  --start 2020-10-07 \
  --end 2026-06-24 \
  --include-full \
  --rolling-years 1,2,3 \
  --max-symbols-per-window 100 \
  --strategies all \
  --buy-commission-bps 4 \
  --sell-commission-bps 4 \
  --sell-tax-bps 18 \
  --slippage-bps 5 \
  --half-spread-bps 5
```

See `docs/AI_TRADER_EXTERNAL_SWEEP.md` and `research/strategy_research_policy.json`. Same-history repeated sweeps produce hypotheses only; they cannot approve live trading.

## First concrete hypothesis audit added

`volume_shock_hypothesis_audit.py` tests:

```text
volume >= 3x previous 20d average
close > open
locked 3-day forward net return after cost
```

Current interpretation after 1,822-symbol long-history validation:

- `RSI_BBANDS_MEAN_REVERSION_H20_V1` is the best clue so far, derived from the external ai-trader bounded sweep where `RsiBollingerBandsStrategy` was the only modestly stable strategy. First validation: locked-test average +0.146%, median +0.395%, win rate 51.70%, but edge remains blocked because train average/win rate fail and locked equal-weight-by-symbol mean is slightly negative. Failure-month diagnostics show strategy monthly return correlates with KOSDAQ monthly return (+0.587), so it is not market-neutral. A post-hoc V2 with stricter KOSDAQ drawdown/volatility guards worsened locked average to -0.148%; do not promote. Trade diagnostics then suggested a post-hoc V3 falling-knife guard (`bb_z >= -2.5`, `volume_multiple <= 2.5`): locked-test average improved to +0.269%, median +0.466%, win rate 52.00%, and locked equal-weight mean turned slightly positive, but train average/win rate still fail. V3 is only a candidate for future/paper holdout, not a same-history approval. `rsi_bbands_v3_forward_watch.py` now records future V3 signals as `order_sent=false`; current latest-cache scan found 0 candidates across 1,822 symbols. `rsi_bbands_v3_forward_outcome_update.py` later resolves those observations after horizon candles exist; current empty-ledger run resolved 0 outcomes.
- `scripts/market_regime_signal_audit.py` is now the pivot after repeated short-horizon public OHLCV failures. It loaded 113,881 timestamped signals from RSI+Bollinger V1/V3, volume-shock breakout H3, and pullback-trend H5. Result: the user's critique is directionally correct (ask market exposure first), but the naive rule "avoid drawdown/crash" is wrong for all strategies. RSI+Bollinger mean-reversion was strongest in crash/drawdown/mixed regimes (V1 crash avg +1.112%, median +2.362%, win 57.17%) and bad in uptrend/weak-downtrend; volume-shock breakout stayed negative in every regime; pullback-trend was worst in uptrend. Therefore do not keep generating 3d/5d public-price stock-selection hypotheses on the same history. Next allowed research tracks are regime exposure gate, 20d/60d horizon, or event-data collection. Same-history regime filters remain diagnostics only.
- `KOSDAQ_REGIME_EXPOSURE_GATE_H20_H60_V1` tested the next question directly: no stock selection, only cash vs broad KOSDAQ index exposure by fixed regime gates. Same-history result does not support freezing a gate yet. `always_long_index_proxy` locked-test H20 avg was +0.786% and daily equity +9.21%; `trend_constructive_only` daily equity was -8.88%; `rebound_crash_drawdown_mixed` daily equity was -6.40%; `avoid_weak_downtrend_only` improved H20 forward avg to +0.859% but locked-test daily equity was only +3.31% vs always-long +9.21% after switch costs. So the market-exposure layer also needs a better question or longer/event-aware features; do not promote any regime gate.
- `RELATIVE_STRENGTH_H60_H20_H60_V1` tested the faster longer-horizon fallback: monthly first-trading-day top-20 stocks by 60d relative strength vs KOSDAQ, with as-of price/turnover/SMA120 filters, next-open entry, 20d/60d exits, and explicit comparisons to full eligible universe and KOSDAQ. It failed: locked-test H20 top avg -1.984%, median -6.635%, win 31.6%, versus eligible universe +0.716% and KOSDAQ +2.132%; locked-test H60 top avg +3.299% but eligible universe +5.925% and KOSDAQ +7.349%, with top basket compounded +17.2% versus universe +166.5% and KOSDAQ +236.0%. This says the top-N OHLCV relative-strength question is also worse than broad baselines, not merely noisy. Remaining caveat: current cache may omit delisted names, so do not do more pure top-N sweeps until the universe is delisted-inclusive or the question adds new data.
- `EVENT_LIQUIDITY_REACTION_H3_V1` runs the event/news/liquidity track. It joins cached `news_context` to cached candles through `research/news_event_symbol_map.csv`, can restrict rows by `--allowed-markets`, requires positive catalyst keywords plus event-day volume >= 1.5x prior 20d average, uses next-open entry and 3-trading-day exit, compares each signal to the same-date eligible-universe baseline, and writes no-send pending future-horizon candidates. The previous data-readiness blockers were fixed by deduping `data/news_context_latest.sqlite3`, excluding KOSPI map rows from KOSDAQ-only post-collection, adding `data/event_liquidity_reaction_pending.jsonl`, and switching default news collection from generic price queries to catalyst queries in `research/event_news_queries.txt`. Current result: 83 cached news rows, 44 mapped events, 2 evaluable signals, 0 pending. This is still not a strategy edge: only one symbol produced signals, locked-test has one event with -13.46% net return and -9.82% excess vs the same-date eligible universe, so live orders remain blocked.
- `REGIME_LOW_VOL_BREAKOUT_H10_V1` failed first validation: locked-test average -0.141%, median -2.00%, win rate 38.51%.
- the breakout long hypothesis is rejected even after realistic gap-aware fill modeling.
- locked-test result after the gap-fill fix: average -1.07%, median -1.95%, win rate 36.17% after cost.
- portfolio simulation after the gap-fill fix is near-total loss; this is not a deployable edge.
- reversal/avoid has a weak post-hoc clue (locked-test median positive and win rate above 53%), but average and equal-weight checks fail and future holdout is mandatory.
- candidate-symbol positives are only diagnostics.
- if sample size is small, the correct output is `edge_ok=false`, not “promising edge”.

This is research evidence only. It is not wired into live/paper execution as an approval signal.
