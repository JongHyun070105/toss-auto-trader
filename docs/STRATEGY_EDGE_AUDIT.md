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
- whether at least one symbol in the pair has a positive audited edge,
- whether the pair is a true pair or just an independent long basket.

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


## First concrete hypothesis audit added

`volume_shock_hypothesis_audit.py` tests:

```text
volume >= 3x previous 20d average
close > open
forward net return after cost for 1/3/5 days
```

Latest smoke result:

- `204620`: possible 3-day edge, small sample.
- `073240`: possible 1/3/5-day edge, but current spread/history makes it hard to trade safely.
- `336570`, `032620`, `462860`: not enough post-cost evidence under this hypothesis.

This is research evidence only. It is not wired into live/paper execution yet.
