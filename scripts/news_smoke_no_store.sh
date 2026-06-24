#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

read -r -p 'Naver Client ID (blank skip): ' NAVER_CLIENT_ID || true
read -r -s -p 'Naver Client Secret (blank skip): ' NAVER_CLIENT_SECRET || true
printf '\n'
read -r -s -p 'Marketaux API token (blank skip): ' MARKETAUX_API_TOKEN || true
printf '\n'
read -r -s -p 'Finnhub API key (blank skip): ' FINNHUB_API_KEY || true
printf '\n'
read -r -s -p 'Alpha Vantage API key (blank skip): ' ALPHAVANTAGE_API_KEY || true
printf '\n'

export NAVER_CLIENT_ID NAVER_CLIENT_SECRET MARKETAUX_API_TOKEN FINNHUB_API_KEY ALPHAVANTAGE_API_KEY
export TOSS_DB_PATH="${TOSS_DB_PATH:-data/toss_lab.sqlite3}"

PROVIDERS="${1:-naver,marketaux,finnhub}"
QUERIES="${2:-KOSPI market macro economy|Samsung Electronics stock Korea market}"

PYTHONPATH=src python3 -m toss_auto_trader.cli news-cycle \
  --providers "$PROVIDERS" \
  --queries "$QUERIES" \
  --limit 3
