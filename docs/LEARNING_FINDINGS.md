# Learning findings

## 2026-06-24 1h synthetic improved run

DB: `data/learning_improved_1h.sqlite3`

Result:

| branch | events | buy signals | fills | rejects | avg_loss | feedback |
|---|---:|---:|---:|---:|---:|---|
| `balanced_momentum` | 13 | 0 | 0 | 0 | 0.000076923 | Stable, but currently too conservative in synthetic data |
| `conservative_guarded` | 13 | 0 | 0 | 0 | 0.000076923 | Safety benchmark |
| `observation_first` | 13 | 0 | 0 | 0 | 0.000076923 | Useful as no-trade baseline |
| `technical_aggressive` | 13 | 8 | 3 | 5 | 0.000469231 | Over-trades; improved after rejected-order outcome fix, but still worse |

Interpretation:

- The synthetic scenario rewarded not trading. That does **not** prove that no-trade is always best; it proves the current synthetic generator is weak for evaluating opportunity capture.
- `technical_aggressive` filled 3 buys and hit daily order limit 5 times. It needs stricter overbought and max-order gates.
- `balanced_momentum` did not differentiate from conservative/observation. Its thresholds are still too conservative for this synthetic signal shape.
- Rejected orders are now evaluated with `effective_side=HOLD`, fixing the earlier false loss attribution.

Next improvements:

1. Add stronger synthetic regimes: breakout, gap-up fade, pullback recovery, volatility crush.
2. Add realized/unrealized PnL mark-to-market per paper position.
3. Add actual Toss candle-based paper simulation for US/KR symbols during market hours.
4. Feed `news_context` into `market_context_json` for agent decisions.
5. Keep `conservative_guarded` as safety baseline and test `balanced_momentum_v2` with slightly lower technical threshold plus RSI-overheat block.

## Marketaux note

Marketaux documentation says `GET https://api.marketaux.com/v1/news/all?api_token=...` is available on all plans. The earlier 403/1010 was not a token or plan problem. It was caused by the default Python urllib User-Agent being blocked. Adding a browser-like `User-Agent` and `Accept: application/json` header returns 200 OK.
