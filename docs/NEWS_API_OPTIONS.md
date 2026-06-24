# News / macro data API candidates

목표: GPT/에이전트에 거시경제·시장 뉴스 맥락을 주되, API 호출 제한을 넘지 않도록 캐시/쿼터를 먼저 설계한다.

## 후보

| 후보 | 장점 | 주의점 |
|---|---|---|
| Finnhub Market News | 금융 뉴스, 회사/시장 뉴스, 문서상 429와 rate-limit 명시. 검색 결과 기준 플랜 외 30 calls/sec 상한 언급 | 무료/유료 플랜별 월/분 제한 확인 필요 |
| Marketaux | 글로벌 주식/금융 뉴스 + sentiment 제공 | 무료 플랜 제한/한국 커버리지 확인 필요 |
| Alpha Vantage News & Sentiment | 주식/암호화폐/경제 뉴스 sentiment API 제공 | 무료 플랜 분당/일일 제한이 낮을 수 있음 |
| EODHD Financial News | ticker/date/type 필터 가능 | 검색 결과 기준 free는 20 calls/day 언급, 실험용으로는 제한적 |
| Alpaca News API | 실시간 주식/크립토 뉴스, 검색 결과 기준 일부 플랜 200 calls/min 언급 | 계정/플랜 필요, 한국 주식과 직접 연결성 낮을 수 있음 |
| Naver Search API | 한국어 뉴스 검색에 유리 | 금융 특화 sentiment/정규화 부족, 네이버 개발자 키 필요 |

## 권장 시작안

1. 한국어 뉴스: Naver Search API 또는 일반 웹 검색 캐시
2. 글로벌/미국 거시 뉴스: Finnhub 또는 Alpha Vantage
3. sentiment 포함이 필요하면 Marketaux/Alpha Vantage 비교

## 호출 제한 원칙

- 뉴스는 매 tick 호출 금지.
- 장 시작 전 1회, 장중 60~120분 간격, 장 마감 후 리포트 1회 정도로 제한.
- 같은 cycle 안에서는 `CycleCache`로 재사용.
- DB에는 기사 전문을 저장하지 말고 headline/source/url/published_at/sentiment/summary 정도만 저장.
- 429 발생 시 해당 provider는 cool-down 상태로 두고 다음 cycle까지 호출하지 않음.

## 1시간/72시간 루프 적용

- 1시간 합성 루프: 뉴스 API 호출하지 않음. rate-limit 없는 구조 검증용.
- 실 Toss API 루프: market-calendar가 장중일 때만 가격/캔들 호출.
- 뉴스 API 루프: 별도 TTL, 기본 3600초 이상.

## 다음 구현 후보

- `news_context` 테이블: provider, query, title, url, source, published_at, sentiment, cached_at
- `news` config: provider, ttl_seconds, max_calls_per_day, max_calls_per_minute
- `RateLimiter` 공통 모듈: provider별 min_interval/cooldown 관리
