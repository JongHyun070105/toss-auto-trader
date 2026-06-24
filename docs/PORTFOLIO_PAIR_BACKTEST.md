# Portfolio pair backtest

## Purpose

10,000 KRW live/paper test needs portfolio-level evaluation, not single-symbol testing. This command replays cached Toss candles for 6/4 budget pairs.

## Command

```bash
TOSS_DB_PATH=data/pair_backtest.sqlite3 \
PYTHONPATH=src python3 -m toss_auto_trader.cli portfolio-pair-backtest \
  --pairs '336570:6000+462860:4000,204620:6000+462860:4000,073240:6000+032620:4000' \
  --window 60 \
  --max-bars 180
```

Pair syntax:

```text
SYMBOL:SLOT_CASH+SYMBOL:SLOT_CASH
```

Example:

```text
336570:6000+462860:4000
```

## Current tested pairs

Used cached Toss candles only. No API calls during replay.

DB: `data/pair_backtest.sqlite3`

| pair id | pair | best branch | avg_loss | notes |
|---:|---|---|---:|---|
| 2 | 글로벌텍스프리 6k + 더즌 4k | technical_aggressive | 0.001819 | best tested pair |
| 1 | 원텍 6k + 더즌 4k | technical_aggressive | 0.002972 | second |
| 3 | 금호타이어 6k + GC메디아이 4k | observation_first | 0.003076 | active branches often rejected/no cash |

## Timestamp-aligned rerun for selected pair

DB: `data/pair_backtest_aligned.sqlite3`
Pair: `204620:6000+462860:4000`

The replay now uses timestamp intersection, not raw candle index alignment.

| branch | final equity | PnL |
|---|---:|---:|
| technical_aggressive | 11,470 | +1,470 |
| balanced_momentum | 8,315 | -1,685 |
| conservative_guarded | 10,000 | 0 |
| observation_first | 10,000 | 0 |

Current paper candidate file: `data/live_paper_candidates.json`.

## Implemented together with Ponytail

- `agy plugin install https://github.com/DietrichGebert/ponytail` completed.
- Codex Ponytail marketplace already added; current Codex CLI exposes marketplace only, install is UI `/plugins` path.
- Hermes local `ponytail` skill installed and loaded for this work.

## Agy review pitfalls

- Historical daily order cap must be disabled or raised during replay. Current CLI uses `--historical-daily-max-orders 1000000`.
- Pair account cash is shared, so no-cash rejections are meaningful at portfolio level.
- Existing paper broker does not deduct fees from cash; loss scoring includes fees, so cash balance and loss metric are not identical.
- Backtests must use cached `news_context`; do not call news APIs per bar.
- ETF screening cannot be auto-approved until NAV/spread/LP checks are available.

## Current model caveat

Pair replay now aligns symbols by timestamp intersection. Remaining caveats:

- Paper cash now deducts commission/tax, but historical order timestamps still use runtime time, not simulated trade date.
- Pair allocation uses one shared 10,000 KRW account with slot-specific BUY cash. This models a real tiny account, but not strict independent 6k/4k sub-ledgers.
- Grid results can overfit. Current guard is full-window + recent-window comparison; next upgrade is proper walk-forward split.
