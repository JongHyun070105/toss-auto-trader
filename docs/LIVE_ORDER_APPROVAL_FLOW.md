# Live order approval flow design — no send path

## Current policy

A separate `order-live-send` command now exists, but it is **blocked by default** and does not send unless every hard gate passes.

Hard gates:

- `order-dry-run` still forces `dry_run=True` and `live_trading=False`.
- `order-live-send` defaults to plan-only review and requires:
  - `data/live_paper_candidates.json live_order_allowed: true`,
  - `manual_approval_required: true`,
  - walk-forward stable-positive candidate,
  - spread, observation, stress, and strategy-edge gates all passing,
  - exact candidate fingerprint confirmation string,
  - `--really-send`,
  - `TOSS_DRY_RUN=false` and `TOSS_LIVE_TRADING=true`,
  - `--allow-multi-leg` for pair/basket orders.
- Current candidate file still has `live_order_allowed: false`, so current live sending remains blocked.
- Continuous supervisor exports:
  - `TOSS_DRY_RUN=true`
  - `TOSS_LIVE_TRADING=false`

## Pre-live checklist command

This command sends no orders. It only validates that a candidate is ready for human review.

```bash
python3 scripts/pre_live_order_checklist.py \
  --require-spread-ok \
  --ack I_UNDERSTAND_THIS_DOES_NOT_SEND_ORDERS
```

Required pass conditions:

1. Candidate source is `walk_forward`.
2. `stable_positive=true`.
3. `validation_pnl_krw > 0` after fees/tax/slippage.
4. Candidate remains paper-only watchlist status.
5. Spread guard passes at current orderbook threshold.
6. Manual acknowledgement string is provided.

## If user later explicitly approves live-order implementation

Implemented as `order-live-send`, but current data still blocks live sending. The command is intentionally stricter than `order-dry-run`:

```bash
PYTHONPATH=src python3 -m toss_auto_trader.cli order-live-send \
  --path data/live_paper_candidates.json \
  --candidate-index 0
```

This prints a review result and does not send. A real send would additionally require the exact confirmation string printed by that command:

```bash
TOSS_DRY_RUN=false TOSS_LIVE_TRADING=true \
PYTHONPATH=src python3 -m toss_auto_trader.cli order-live-send \
  --candidate-index 0 \
  --really-send \
  --allow-multi-leg \
  --confirm I_UNDERSTAND_LIVE_ORDER_RISK:<candidate_fingerprint>
```

Do not run the real-send form unless the candidate file itself is marked `live_order_allowed=true` and the checklist/edge/observation/stress gates are green in the same run.
