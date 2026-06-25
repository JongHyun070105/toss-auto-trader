# AI Trader external sweep

## Purpose

Use `whchien/ai-trader` as an external Backtrader-based validation engine for exploratory strategy sweeps.

This is **research-only/no-send**. It must not approve live orders.

## License boundary

`whchien/ai-trader` is GPL-3.0.

Private/internal cloning and modification is generally fine while there is no distribution, but mixing GPL code into this repo can create future distribution obligations. Therefore:

- keep cloned ai-trader repos under ignored paths such as `external/ai-trader/`, `ai-trader/`, or `/tmp/ai-trader-eval`.
- do not vendor/copy ai-trader source into `src/`.
- use it through an isolated venv, CLI, or explicit `--ai-trader-repo` import path.
- output CSV/JSON reports are fine to keep as research artifacts under `data/`.

## Setup

```bash
git clone https://github.com/whchien/ai-trader.git external/ai-trader
cd external/ai-trader
uv venv --python python3.11 .venv
. .venv/bin/activate
uv pip install -e .
```

The repo can also live at `/tmp/ai-trader-eval`; pass the path with `--ai-trader-repo`.

## Export CSV for manual CLI use

```bash
PYTHONPATH=src python3 scripts/export_ai_trader_data.py \
  --db-path data/edge_research_universe_long.sqlite3 \
  --fetch-kosdaq-index \
  --top-by-trade-value 20 \
  --out-dir data/ai_trader_export \
  --start 2020-10-07 \
  --end 2026-06-24
```

Example external CLI run:

```bash
external/ai-trader/.venv/bin/ai-trader quick CrossSMAStrategy \
  data/ai_trader_export/KOSDAQ_INDEX.csv \
  --cash 1000000 \
  --commission 0.0004 \
  --start-date 2020-10-07 \
  --end-date 2026-06-24
```

## As-of universe sweep

The main sweep script is:

```text
scripts/ai_trader_universe_sweep.py
```

It does these things:

1. Selects the universe **as of each window start** using only candles before the window.
2. Applies a KR cost model:
   - buy commission bps
   - sell commission bps
   - sell tax bps
   - slippage bps
   - half-spread bps
3. Runs ai-trader classic strategies.
4. Reports:
   - full/yearly/rolling windows
   - KOSDAQ excess return
   - return/MDD
   - return/volatility
   - positive universe share
   - data quality proxies for limit moves, huge gaps, and missing/sparse data

Small smoke:

```bash
external/ai-trader/.venv/bin/python scripts/ai_trader_universe_sweep.py \
  --db-path data/edge_research_universe_long.sqlite3 \
  --ai-trader-repo external/ai-trader \
  --out data/ai_trader_sweep/smoke.json \
  --start 2021-01-01 \
  --end 2023-12-31 \
  --include-full \
  --rolling-years 1 \
  --max-symbols-per-window 3 \
  --strategies BuyHoldStrategy,CrossSMAStrategy
```

All classic strategies smoke:

```bash
external/ai-trader/.venv/bin/python scripts/ai_trader_universe_sweep.py \
  --db-path data/edge_research_universe_long.sqlite3 \
  --ai-trader-repo external/ai-trader \
  --out data/ai_trader_sweep/all_strategies_smoke.json \
  --start 2022-01-01 \
  --end 2023-12-31 \
  --include-full \
  --no-years \
  --rolling-years '' \
  --max-symbols-per-window 2 \
  --strategies all
```

Broader exploratory run:

```bash
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

## Anti-overfit rule

Do not pick the best historical row and promote it.

Allowed loop:

1. Exploratory sweep on historical data.
2. Convert top patterns into a named hypothesis.
3. Freeze the hypothesis and parameters.
4. Validate on an unseen future/paper-only window.
5. If it fails, mark it failed. If it passes, require pre-live no-send checklist.

Disallowed loop:

```text
run all strategies → pick top → tweak params → rerun same data → repeat until pretty equity curve
```

That is p-hacking, not edge discovery.

## Current caveats

- Delisted symbols absent from the local DB can still create survivorship bias.
- Limit-up/down, halts, and orderbook depth are measured as risk proxies, not fully simulated fills.
- The sweep uses classic single-symbol strategies first. Portfolio strategy support should be added separately after the single-symbol engine is stable.
- Any result remains `exploratory_only_requires_future_holdout` until forward/paper validation exists.
