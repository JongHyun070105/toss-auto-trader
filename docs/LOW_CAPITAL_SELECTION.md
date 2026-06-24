# 10,000 KRW low-capital stock selection

## Goal

초기자금 10,000원으로 실주문 전 paper/live-read 실험을 하려면 삼성전자 같은 고가 종목보다 다음을 우선한다.

1. 국내 저가 종목: 1주 가격이 10,000원 이하, 가능하면 6,000원 이하 + 4,000원 이하 조합.
2. 저가 ETF: 단, 거래량만 보지 말고 기초자산 유동성/NAV 괴리/LP 호가를 확인해야 한다.
3. 미국 소수점 거래 지원 확인: 지원되면 AAPL/MSFT/NVDA 같은 우량주도 1만원 단위 paper/live 테스트 가능.
4. 소수점 미지원이면 paper fractional 모드는 연구용으로만 분리한다.

## Blog-derived ETF rule

사용자가 언급한 ETF 유동성 글의 핵심을 정책화한다.

- 거래량 많은 ETF가 반드시 좋은 ETF는 아니다.
- ETF의 진짜 유동성은 기초자산 유동성에서 나온다.
- 확인할 것: 거래량, 호가 스프레드, NAV 괴리, LP 호가, 기초자산 거래 시간.
- 해외형 ETF는 국내 장중에 기초자산 시장이 닫혀 있을 수 있으므로 괴리/스프레드 위험이 크다.

Current implementation cannot yet read NAV/spread/LP data, so ETFs are only candidates, not auto-approved buys.

## New command

```bash
TOSS_DB_PATH=data/low_kr_screen.sqlite3 \
PYTHONPATH=src python3 -m toss_auto_trader.cli screen-low-kr \
  --seed-csv data/naver_low_price_candidates.csv \
  --seed-limit 20 \
  --max-candidates 12 \
  --news-limit 2
```

Inputs:

- `data/naver_low_price_candidates.csv`: scraped low-price KR stock candidates from Naver Finance market-cap pages.
- Toss `/prices`: current price.
- Toss `/stocks`: market/security/status.
- Toss `/stocks/{symbol}/warnings`: investment warning / overheated / VI risk.
- Toss candles: recent volume/technical features.
- Naver Search News: recent headlines.

Scoring:

- 4,000원 이하 bucket gets strongest small-capital fit.
- 6,000원 이하 bucket gets second fit.
- Average candle volume adds liquidity proxy.
- RSI/MA features add technical bonus/penalty.
- News presence adds small context bonus.
- Active Toss warnings apply large penalty.
- Warning symbols are excluded from 6/4 pair suggestions.

## Current top candidates, seed-limit 20

| rank | symbol | name | price | note |
|---:|---|---|---:|---|
| 1 | 336570 | 원텍 | 5,940 | top score; no active warnings |
| 2 | 204620 | 글로벌텍스프리 | 4,735 | positive technical/news context |
| 3 | 073240 | 금호타이어 | 4,435 | KOSPI, no active warnings |
| 4 | 036620 | 감성코퍼레이션 | 4,205 | no active warnings |
| 5 | 484590 | 삼양컴텍 | 7,390 | over 6k, still under 10k |
| 6 | 006910 | 보성파워텍 | 7,270 | over 6k, still under 10k |
| 7 | 019010 | 베뉴지 | 5,050 | lower liquidity |
| 8 | 462860 | 더즌 | 2,080 | 4k bucket candidate |

## Current 6/4 pair suggestions

| pair | total | remaining |
|---|---:|---:|
| 원텍 + 더즌 | 8,020 | 1,980 |
| 원텍 + GC메디아이 | 8,765 | 1,235 |
| 글로벌텍스프리 + 더즌 | 6,815 | 3,185 |
| 금호타이어 + 더즌 | 6,515 | 3,485 |
| 글로벌텍스프리 + GC메디아이 | 7,560 | 2,440 |

These are not buy recommendations. They are paper-trading candidates that fit the 10,000 KRW constraint.

## Strategy registry

New table:

```text
strategy_registry(symbol, selected_branch, avg_loss, events, evidence_json, updated_at)
```

Command:

```bash
TOSS_DB_PATH=data/toss_historical_backtest_v2.sqlite3 \
PYTHONPATH=src python3 -m toss_auto_trader.cli select-best-branches --min-events 50
```

Current registry:

- 005930 → `balanced_momentum_v2`
- AAPL → `technical_aggressive`
- NVDA → `technical_aggressive`
- MSFT → `conservative_guarded`

## News context integration

`execute_paper_decision()` now stores latest `news_context` items in `market_context_json.latest_news`, so future paper/live-read decisions carry both technical signals and recent macro/news context.

## ETF data source notes

KRX Data Marketplace exposes ETF-related screens under:

- 기본 통계 > 증권상품 > ETF > 개별종목 종합정보
- ETF > 괴리율 추이
- ETF > 장마감 괴리율 추이
- ETF > PDF(Portfolio Deposit File)
- 이슈 통계 > 주식 시장조성자 관련통계 > 종목별 주식 시장조성자 및 ETF LP 계약 현황

Policy: until NAV/disparity/spread/LP data is collected, ETF candidates remain screen-only and are not auto-approved for live/paper buy candidates.

## Next work

1. Expand seed universe beyond first 20 Naver market-cap rows.
2. Add timestamp-intersection pair replay to all mixed-market tests if US/KR pairs are ever mixed.
3. Add KRX ETF NAV/disparity/LP collector before ETF auto-selection.
4. Check Toss US fractional-order support before treating US large caps as 10,000 KRW live candidates.
