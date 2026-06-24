# 가상매매 반복 루프

## 오프라인 테스트

API 연결 전에도 가격을 수동 삽입해 전략/주문 로그를 검증할 수 있다.

```bash
PYTHONPATH=src python3 -m toss_auto_trader.cli init-db
PYTHONPATH=src python3 -m toss_auto_trader.cli seed-price --symbol 005930 --prices 70000,70100,70200,70400,70600
PYTHONPATH=src python3 -m toss_auto_trader.cli paper-tick --symbol 005930 --trade-cash 1000
PYTHONPATH=src python3 -m toss_auto_trader.cli summary
```

## 실시간/준실시간 데이터 축적

API 키 연결 후:

```bash
PYTHONPATH=src python3 -m toss_auto_trader.cli collect-price --symbols 005930,000660
PYTHONPATH=src python3 -m toss_auto_trader.cli paper-tick --symbol 005930 --trade-cash 1000
```

반복하면 SQLite에 다음이 쌓인다.

- `prices`: 시세
- `strategy_decisions`: 매수/매도/보류 판단과 이유
- `paper_orders`: 가상 주문 체결 기록
- `paper_positions`: 가상 보유 종목
- `api_snapshots`: API 원본 응답 스냅샷

## 다음 확장 후보

- 환율 `/api/v1/exchange-rate`를 매크로 피처로 저장
- 시장 캘린더로 장중에만 수집
- 보유 종목 `/api/v1/holdings`와 가상 포지션 비교
- 전략별 성과 테이블 추가
- LLM/AI는 직접 주문자가 아니라 `strategy_decisions` 분석자와 후보 제안자로 제한
