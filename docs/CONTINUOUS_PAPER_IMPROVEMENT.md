# Continuous paper improvement loop

## Safety

This loop is paper/read-only only.

```bash
export TOSS_DRY_RUN=true
export TOSS_LIVE_TRADING=false
```

It never sends live orders. Candidate output is explicitly marked:

```json
"live_order_allowed": false,
"manual_approval_required": true
```

## What it runs

Script:

```text
scripts/continuous_paper_improvement.sh
```

Every cycle:

1. Run Toss token health and candidate-symbol orderbook health.
2. Refresh Toss daily candle cache for low-capital symbols, if current token works.
3. Refresh Naver news context for tracked symbols.
4. Run shared-account pair grid backtests from cached candles only.
5. Run isolated-slot pair grid backtests from cached candles only.
6. Run shared-account walk-forward validation.
7. Run isolated-slot walk-forward validation.
8. Update `data/live_paper_candidates.json` with walk-forward-first stable candidates plus observation/spread-history ranking penalties.
9. Run spread/depth guard using live orderbook, recent spread history, 5-level market impact, and future-capital impact; write `data/spread_history.jsonl`.
10. Estimate dynamic one-way slippage from recent max spread; write `data/dynamic_execution_costs.json` and run a bounded dynamic-slippage grid smoke.
11. Append paper-only live/read-only observations only inside 09:05~15:20 KST; classify token/spread/candle/stale/market-impact failures.
12. Run observation guard; candidates need recent N paper-only observations with no blocked/API-failure status.
13. Run stress test with -3/-5/-10% shocks and recent MDD proxy.
14. Run bounded multi-capital validation for 10k/30k/100k/1M classes.
15. Run ETF guard collector; NAV/disparity use Naver fallback if KRX returns LOGOUT, while LP contract remains official-data-only or labeled proxy.
16. Write `data/improvement_summary_latest.json`.


Historical/paper replay uses fixed slippage from config:

```yaml
execution:
  buy_slippage_pct: 0.001
  sell_slippage_pct: 0.001
```

Live/read-only spread can be checked with:

```bash
PYTHONPATH=src python3 -m toss_auto_trader.cli orderbook --symbol 204620
```

Candidate spread guard:

```bash
python3 scripts/spread_guard_candidates.py --max-spread-bps 30
```

Pre-live checklist, no order sending:

```bash
python3 scripts/pre_live_order_checklist.py --require-spread-ok --ack I_UNDERSTAND_THIS_DOES_NOT_SEND_ORDERS
```

Default long run:

```bash
scripts/continuous_paper_improvement.sh 24 3600
```

Meaning: 24 cycles, one cycle per hour.

Current background process:

```text
session_id: proc_1601a1684268
```

## Current important result

After cash-level commission/tax accounting, the earlier candidate changed.

Demoted:

```text
204620:6000+462860:4000 / technical_aggressive
```

Reason: after fees/taxes were deducted from paper cash, final PnL became negative in the fee-adjusted rerun.

Latest smoke/live candidate file now favors:

```text
073240:6000+032620:4000 / balanced_momentum / window=40 / horizon=1
```

Still not live-order approved.

## Files

- `scripts/pair_grid_runner.py`: grid backtest runner.
- `scripts/update_candidates_from_grid.py`: updates paper candidate JSON from latest grid.
- `scripts/continuous_paper_improvement.sh`: long-running supervisor.
- `data/grid_latest/summary.md`: latest grid report.
- `data/live_paper_candidates.json`: latest watchlist, not live order list.
- `data/continuous_paper_improvement.log`: cycle log.

## Next fixes

- Add bid/ask spread if Toss exposes quotes/orderbook.
- Add ETF NAV/disparity/LP collector before ETF auto-selection.
- Add walk-forward split rather than only full/recent window comparison.
- If user approves later, add explicit `--really-send` flow; do not reuse `order-dry-run` for live orders.
