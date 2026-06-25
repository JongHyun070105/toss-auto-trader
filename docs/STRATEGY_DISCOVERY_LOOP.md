# Continuous Strategy Discovery Loop

## Purpose

`strategy_discovery_loop.py` continuously folds multiple strategy families into one no-send review report.

It is designed for this workflow:

1. run or refresh no-send research/forward-watch artifacts;
2. evaluate multiple strategy families with one policy;
3. select only strategies with enough paper-forward evidence;
4. stop at `pre_live_review_candidate_not_live_order`;
5. never send an order from the discovery loop.

In short: it **never sends live orders**.

## Safety contract

The loop always reports:

```json
{
  "live_order_allowed": false,
  "order_sent": false,
  "manual_approval_required": true
}
```

Child commands run with:

```bash
TOSS_DRY_RUN=true
TOSS_LIVE_TRADING=false
```

The loop must not call `order-live-send`. Live sending remains a separate command requiring candidate-file approval, green pre-live gates, exact fingerprint confirmation, and live env flags.

## What counts as a good strategy

Policy file:

```text
research/strategy_research_policy.json
```

Current minimum forward evidence:

```text
resolved forward outcomes >= 20
avg net return after cost >= +2%
median net return after cost >= 0%
win rate after cost >= 55%
pending outcomes == 0
```

Same-history or locked-test positives are not enough. They become `future_holdout_required_before_pre_live`.

## Run examples

Evaluate current artifacts only:

```bash
PYTHONPATH=src TOSS_DRY_RUN=true TOSS_LIVE_TRADING=false \
python3 scripts/strategy_discovery_loop.py --audit-pack none --max-cycles 1
```

Refresh forward-watch artifacts and evaluate:

```bash
PYTHONPATH=src TOSS_DRY_RUN=true TOSS_LIVE_TRADING=false \
python3 scripts/strategy_discovery_loop.py --audit-pack forward --max-cycles 1
```

Light recurring loop:

```bash
PYTHONPATH=src TOSS_DRY_RUN=true TOSS_LIVE_TRADING=false \
python3 scripts/strategy_discovery_loop.py --audit-pack forward --interval-seconds 3600 --max-cycles 24
```

## Current latest result

Latest one-cycle run over forward artifacts:

```text
out: data/strategy_discovery_loop_latest.json
evaluated: 7
pre_live_review_eligible: 0
best_name: rsi_bbands_v3_forward_outcomes
best_status: blocked_or_waiting_forward_evidence
order_sent: false
live_order_allowed: false
```

Reason: no forward outcomes are resolved yet and latest RSI/Bollinger V3 scan found zero current candidates.
