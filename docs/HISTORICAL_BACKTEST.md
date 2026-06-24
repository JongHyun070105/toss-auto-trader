# Historical Toss candle backtest

## Purpose

합성 데이터는 시장 경우의 수가 제한적이라 전략 평가가 왜곡된다. 이제 우선순위는 Toss API에서 실제 historical candles를 한 번에 가져와 bounded cache에 저장하고, 그 캐시를 과거→현재 순서로 replay하여 `decision_events`를 쌓는 것이다.

## New commands

### 1. Cache candles

```bash
TOSS_DB_PATH=data/toss_historical_backtest.sqlite3 \
PYTHONPATH=src python3 -m toss_auto_trader.cli cache-candles \
  --symbols 005930 \
  --interval 1d \
  --count 200 \
  --pages 1
```

- Toss API call: one candle request per symbol per page.
- Stores into `candle_cache`.
- No real orders.

### 2. Replay historical backtest

```bash
TOSS_DB_PATH=data/toss_historical_backtest.sqlite3 \
PYTHONPATH=src python3 -m toss_auto_trader.cli historical-backtest \
  --symbols 005930 \
  --interval 1d \
  --window 60 \
  --horizon 1 \
  --max-bars 180 \
  --initial-cash 1000000 \
  --trade-cash 300000 \
  --max-order 300000
```

- Reads only cached candles; no additional API calls.
- Evaluates windows from past to today.
- Stores decisions/outcomes/loss into `decision_events`.
- Branch paper accounts are isolated by `hist:<symbol>:<branch>`.

## Important modeling fixes

### Historical daily order limit

Runtime `daily_max_orders` uses today's date. In historical replay, many past candles are evaluated during one runtime day, so the normal daily cap caused false `REJECTED_DAILY_ORDER_LIMIT`. Historical mode now sets a very high cap by default via `--historical-daily-max-orders`.

### Exit logic

Before evaluating new BUY decisions, historical replay checks existing branch position:

- Stop-loss: `current <= avg * (1 - stop_loss_pct)`
- Take-profit: `current >= avg * (1 + take_profit_pct)`

If triggered, it logs a SELL decision first and skips same-day re-entry.

## 005930 result, 200 daily candles cached

DB: `data/toss_historical_backtest_v2.sqlite3`

| branch | events | buy signals | buys | sells | rejects | avg_loss |
|---|---:|---:|---:|---:|---:|---:|
| balanced_momentum_v2 | 119 | 79 | 60 | 21 | 19 | -0.00950 |
| balanced_momentum | 119 | 87 | 63 | 19 | 24 | -0.00712 |
| technical_aggressive | 119 | 96 | 66 | 23 | 30 | -0.00654 |
| conservative_guarded | 119 | 50 | 32 | 16 | 18 | -0.00365 |
| observation_first | 119 | 0 | 0 | 0 | 0 | 0.00883 |

Interpretation: on this 005930 historical slice, `balanced_momentum_v2` performed best by average loss. Lower is better; negative loss means positive fee-adjusted next-step return under the current scoring.

Caveat: 005930 was too expensive relative to tiny capital late in the period, causing `REJECTED_TOO_SMALL`. For realistic 10,000 KRW experiments, use lower-priced KR stocks/ETFs or US fractional support if the brokerage/API supports it.

## US large-cap result, 200 daily candles each

DB: `data/us_historical_backtest.sqlite3`
Symbols: AAPL, MSFT, NVDA

Top findings by symbol:

- AAPL: `technical_aggressive` was best, avg_loss -0.00012.
- NVDA: `technical_aggressive` was best among active branches, avg_loss 0.00084; conservative was safer than balanced.
- MSFT: `conservative_guarded` was best among active branches, avg_loss 0.00195.

Interpretation: one branch is not universally best. Symbol-specific branch selection is needed.

## Next efficient path

1. Use Toss candle cache/backtest as the primary experiment loop.
2. Add symbol-specific branch ranking.
3. Add lower-priced KR universe selection; 005930 is not suitable for 10,000 KRW integer-share testing.
4. Add news_context into `market_context_json` for event-aware decisions.
5. Run low-frequency live paper ticks only after cached historical backtest selects candidate symbols/branches.
