# Decision-centric architecture

## 핵심 변경

원본 시세를 무한 저장하지 않는다. 시세/캔들은 API에서 필요할 때 조회하고, SQLite에는 장기 학습에 필요한 **결정 이벤트**를 중심으로 저장한다.

## 저장 원칙

### 장기 저장

- `decision_events`
  - 어떤 종목을 봤는지
  - BUY/SELL/HOLD 판단
  - 실행 결과
  - 판단 이유
  - confidence/score
  - 당시 기술지표/수수료/성과 피드백 요약
- `paper_orders`, `paper_positions`
  - 가상매매 체결과 보유 상태

### 단기 캐시

- `prices`
  - 최근 가격 캐시만 보관
  - 기본 심볼당 500개 초과분 삭제
- candles, market calendar, exchange rate
  - 사이클 내부 메모리 캐시
  - 필요 시 Toss API에서 다시 조회

## API화된 데이터 소스

Toss 공식 API 기준:

- 현재가: `/api/v1/prices`
- 캔들: `/api/v1/candles` — 1분봉/일봉, 최대 200봉
- 환율: `/api/v1/exchange-rate`
- 시장 시간: `/api/v1/market-calendar/KR`, `/api/v1/market-calendar/US`
- 수수료: `/api/v1/commissions`
- 계좌/보유/매수가능금액: `/api/v1/accounts`, `/api/v1/holdings`, `/api/v1/buying-power`

## 멀티 에이전트 구조

- `technical` — RSI, 이동평균 배열, ATR 기반 기술 분석
- `risk` — 동적 손절/익절/트레일링 스톱 제안
- `fee` — 수수료/세금 왕복 비용 반영
- `performance` — 최근 가상매매 성과 피드백
- `coordinator` — 최소 점수/확신도 기준으로 BUY/HOLD 결정

## 관망 원칙

마땅한 종목이 없으면 0개를 고른다. 코드에서도 아래 기준으로 차단한다.

- 평균 점수 미달
- confidence 미달
- technical/performance 에이전트가 HOLD
- 일일 주문 횟수 초과
- 1회 주문 금액 초과
- 장외 API 호출 제한

## 12시간/72시간 학습

현재 구현은 실주문 없는 가상 학습이다.

- `learning-sim`: 합성 시나리오로 decision_events를 쌓아 전략 분기 비교
- `agent-tick`: 실 API 캔들 기반 1회 판단. 장외에는 기본 skip

실 API 기반 72시간 루프는 자격증명을 로컬 `.env`에 넣고 장중 호출 제한을 유지한 뒤 실행해야 한다.
