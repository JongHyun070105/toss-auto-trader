#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

WATCH_PID="${1:?usage: scripts/after_learning_supervisor.sh <pid>}"
LOG="data/after_learning_supervisor.log"
mkdir -p data

echo "[$(date -Is)] waiting for learning pid ${WATCH_PID}" >> "$LOG"
while kill -0 "$WATCH_PID" 2>/dev/null; do
  sleep 60
done

echo "[$(date -Is)] learning pid finished" >> "$LOG"
TOSS_DB_PATH=data/learning_1h.sqlite3 PYTHONPATH=src python3 -m toss_auto_trader.cli summary >> "$LOG" 2>&1 || true

# Load local secrets only if user created .env. .env is gitignored.
if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

if [[ -n "${TOSS_CLIENT_ID:-}" && -n "${TOSS_CLIENT_SECRET:-}" ]]; then
  echo "[$(date -Is)] starting US Toss API paper ticks" >> "$LOG"
  for i in $(seq 1 12); do
    TOSS_DB_PATH=data/us_api_paper.sqlite3 PYTHONPATH=src python3 -m toss_auto_trader.cli agent-tick \
      --symbols AAPL,MSFT,NVDA \
      --market-country US \
      --interval 1m \
      --count 100 \
      --trade-cash 1000 >> "$LOG" 2>&1 || true
    sleep 300
  done
else
  echo "[$(date -Is)] .env has no Toss credentials; running extended synthetic branch comparison instead" >> "$LOG"
  TOSS_DB_PATH=data/extended_synthetic.sqlite3 PYTHONPATH=src python3 -m toss_auto_trader.cli learning-sim \
    --iterations 24 \
    --sleep-seconds 300 \
    --status-every 3 \
    --symbol SIM_US \
    --trade-cash 3000 >> "$LOG" 2>&1 || true
fi

echo "[$(date -Is)] supervisor done" >> "$LOG"
