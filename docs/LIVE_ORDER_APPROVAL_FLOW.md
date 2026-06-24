# Live order approval flow design — no send path

## Current policy

Real order sending is not implemented in this project flow yet.

Hard gates:

- `order-dry-run` forces `dry_run=True` and `live_trading=False`.
- `data/live_paper_candidates.json` must keep:
  - `live_order_allowed: false`
  - `manual_approval_required: true`
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

Do not directly reuse `order-dry-run`. Add a separate command only after explicit user instruction, e.g. `order-live-send`, with all of these gates:

1. CLI flag `--really-send`.
2. Candidate hash or exact candidate name must match current `live_paper_candidates.json`.
3. Pre-live checklist must pass in the same run.
4. Current orderbook spread must pass.
5. Max notional must be capped at the candidate slot cash.
6. Print final payload and require a second explicit confirmation mechanism.
7. Log a redacted approval record.

Until that separate command exists, this repo cannot send a live order through the candidate flow.
