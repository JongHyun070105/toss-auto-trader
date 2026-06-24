# Toss API 연결 방법

## 1. 시크릿 저장

`.env.example`을 복사해서 `.env`를 만든다.

```bash
cp .env.example .env
```

`.env`에 실제 값을 넣는다.

```dotenv
TOSS_CLIENT_ID=c_...
TOSS_CLIENT_SECRET=s_...
TOSS_DRY_RUN=true
TOSS_LIVE_TRADING=false
```

주의: 대화/로그에 API 키를 붙여넣었다면 작업 후 재발급한다.

## 2. DB 초기화

```bash
PYTHONPATH=src python3 -m toss_auto_trader.cli init-db
```

## 3. 계좌 + 현재가 read-only 테스트

```bash
PYTHONPATH=src python3 -m toss_auto_trader.cli api-smoke --symbols 005930
```

이 명령은 다음만 수행한다.

- `/oauth2/token` 토큰 발급
- `/api/v1/accounts` 계좌 목록 조회
- `/api/v1/prices` 현재가 조회
- 응답을 SQLite `api_snapshots`, `prices`에 저장

## 4. 실주문 안전장치

`order-dry-run`은 기본적으로 실제 주문을 보내지 않고 payload만 보여준다.

```bash
PYTHONPATH=src python3 -m toss_auto_trader.cli order-dry-run \
  --account-seq 1 \
  --client-order-id test-001 \
  --symbol 005930 \
  --side BUY \
  --quantity 1 \
  --price 70000
```

실제 주문은 `.env`에서 아래 둘을 모두 바꿔야만 가능하게 설계했다.

```dotenv
TOSS_DRY_RUN=false
TOSS_LIVE_TRADING=true
```

그래도 첫 실거래 전에는 반드시 별도 검토한다.
