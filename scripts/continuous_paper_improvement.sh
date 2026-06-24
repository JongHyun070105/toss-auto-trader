#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/.."
CYCLES="${1:-24}"
SLEEP_SECONDS="${2:-3600}"
GRID_WINDOWS="${GRID_WINDOWS:-40,60,80}"
GRID_HORIZONS="${GRID_HORIZONS:-1,3,5}"
SYMBOLS="${SYMBOLS:-336570,204620,073240,032620,462860}"
RUN_WALK_FORWARD="${RUN_WALK_FORWARD:-true}"
RUN_SPREAD_GUARD="${RUN_SPREAD_GUARD:-true}"
RUN_PAPER_OBSERVE="${RUN_PAPER_OBSERVE:-true}"
RUN_ETF_GUARD="${RUN_ETF_GUARD:-true}"
RUN_OBSERVATION_GUARD="${RUN_OBSERVATION_GUARD:-true}"
RUN_TOKEN_HEALTH="${RUN_TOKEN_HEALTH:-true}"
RUN_STRESS_TEST="${RUN_STRESS_TEST:-true}"
RUN_MULTI_CAPITAL="${RUN_MULTI_CAPITAL:-true}"
RUN_DYNAMIC_SLIPPAGE_GRID="${RUN_DYNAMIC_SLIPPAGE_GRID:-true}"
MULTI_CAPITAL_LIMIT="${MULTI_CAPITAL_LIMIT:-4}"
ETF_SYMBOLS="${ETF_SYMBOLS:-069500,411060}"
MAX_SPREAD_BPS="${MAX_SPREAD_BPS:-30}"
LOG="data/continuous_paper_improvement.log"
mkdir -p data

if [ -f .env ]; then
  set -a
  . ./.env
  set +a
fi

# Hard safety gate: this supervisor is paper/read-only only.
export TOSS_DRY_RUN=true
export TOSS_LIVE_TRADING=false
export PYTHONPATH=src

{
  echo "=== continuous_paper_improvement start $(date '+%Y-%m-%dT%H:%M:%S%z') cycles=$CYCLES sleep=$SLEEP_SECONDS ==="
  echo "safety TOSS_DRY_RUN=$TOSS_DRY_RUN TOSS_LIVE_TRADING=$TOSS_LIVE_TRADING"
} >> "$LOG"

for ((i=1; i<=CYCLES; i++)); do
  {
    echo "--- cycle $i/$CYCLES $(date '+%Y-%m-%dT%H:%M:%S%z') ---"
    if [ "$RUN_TOKEN_HEALTH" = "true" ]; then
      python3 scripts/toss_token_health.py || true
    fi
    TOSS_DB_PATH=data/low_kr_backtest.sqlite3 python3 -m toss_auto_trader.cli cache-candles \
      --symbols "$SYMBOLS" --interval 1d --count 200 --pages 1 --sleep-seconds 2 || true
    TOSS_DB_PATH=data/news_context_latest.sqlite3 python3 -m toss_auto_trader.cli news-cycle \
      --providers naver \
      --queries '금호타이어 주가|GC메디아이 주가|글로벌텍스프리 주가|원텍 주가|더즌 주가' \
      --limit 3 || true
    python3 scripts/pair_grid_runner.py \
      --windows "$GRID_WINDOWS" \
      --horizons "$GRID_HORIZONS" \
      --out-dir data/grid_latest
    python3 scripts/pair_grid_runner.py \
      --windows "$GRID_WINDOWS" \
      --horizons "$GRID_HORIZONS" \
      --out-dir data/grid_isolated_latest \
      --isolated-slots
    if [ "$RUN_WALK_FORWARD" = "true" ]; then
      python3 scripts/walk_forward_runner.py \
        --windows "40,60" \
        --horizons "1,3,5" \
        --out-dir data/walk_forward_shared
      python3 scripts/walk_forward_runner.py \
        --windows "40,60" \
        --horizons "1,3,5" \
        --out-dir data/walk_forward_isolated \
        --isolated-slots
    fi
    python3 scripts/update_candidates_from_grid.py
    python3 scripts/strategy_edge_audit.py || true
    python3 scripts/volume_shock_hypothesis_audit.py || true
    python3 scripts/update_candidates_from_grid.py
    if [ "$RUN_SPREAD_GUARD" = "true" ]; then
      python3 scripts/spread_guard_candidates.py --max-spread-bps "$MAX_SPREAD_BPS" || true
      python3 scripts/dynamic_slippage_from_spread.py || true
      if [ "$RUN_DYNAMIC_SLIPPAGE_GRID" = "true" ]; then
        python3 scripts/dynamic_slippage_grid_runner.py --limit "$MULTI_CAPITAL_LIMIT" --windows "40" --horizons "1" || true
      fi
    fi
    if [ "$RUN_PAPER_OBSERVE" = "true" ]; then
      TOSS_DB_PATH=data/paper_observe.sqlite3 python3 scripts/paper_observe_candidates.py --limit 3 --max-spread-bps "$MAX_SPREAD_BPS" || true
    fi
    if [ "$RUN_OBSERVATION_GUARD" = "true" ]; then
      python3 scripts/observation_guard_candidates.py --min-observations 3 || true
    fi
    if [ "$RUN_STRESS_TEST" = "true" ]; then
      python3 scripts/stress_test_candidates.py || true
    fi
    python3 scripts/strategy_edge_guard_candidates.py || true
    if [ "$RUN_MULTI_CAPITAL" = "true" ]; then
      python3 scripts/multi_capital_runner.py --limit "$MULTI_CAPITAL_LIMIT" --windows "40" --horizons "1" || true
    fi
    if [ "$RUN_ETF_GUARD" = "true" ]; then
      python3 scripts/etf_guard_collector.py --symbols "$ETF_SYMBOLS" --max-spread-bps "$MAX_SPREAD_BPS" || true
    fi
    python3 scripts/summarize_improvement_results.py || true
  } >> "$LOG" 2>&1
  if [ "$i" -lt "$CYCLES" ]; then
    sleep "$SLEEP_SECONDS"
  fi
done

{
  echo "=== continuous_paper_improvement done $(date '+%Y-%m-%dT%H:%M:%S%z') ==="
  tail -80 data/grid_latest/summary.md || true
} >> "$LOG"

tail -120 "$LOG"
