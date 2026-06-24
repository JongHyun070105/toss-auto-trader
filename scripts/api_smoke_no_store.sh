#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

SYMBOL="${1:-005930}"
ACCOUNT_SEQ="${2:-}"

printf 'TOSS_CLIENT_ID/API KEY: '
IFS= read -r TOSS_CLIENT_ID
printf 'TOSS_CLIENT_SECRET/SECRET KEY: '
stty -echo
IFS= read -r TOSS_CLIENT_SECRET
stty echo
printf '\n'

if [[ -z "${TOSS_CLIENT_ID}" || -z "${TOSS_CLIENT_SECRET}" ]]; then
  echo 'missing credentials' >&2
  exit 2
fi

export TOSS_CLIENT_ID
export TOSS_CLIENT_SECRET
export TOSS_DRY_RUN=true
export TOSS_LIVE_TRADING=false
export TOSS_DB_PATH="${TOSS_DB_PATH:-data/toss_lab.sqlite3}"

PYTHONPATH=src python3 -m toss_auto_trader.cli init-db >/dev/null
# One smoke call: token + accounts + prices. Avoid extra account API calls by default to reduce 429.
PYTHONPATH=src python3 -m toss_auto_trader.cli api-smoke --symbols "${SYMBOL}"

if [[ -n "${ACCOUNT_SEQ}" ]]; then
  sleep 3
  PYTHONPATH=src python3 -m toss_auto_trader.cli account-snapshot --account-seq "${ACCOUNT_SEQ}" --currency KRW
fi
