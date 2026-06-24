# Toss Auto Trader Lab

Toss Invest Open API를 이용해 한국 주식 자동매매를 연구하는 개인 학습용 실험실입니다.

현재 목표는 실주문이 아니라, 전략 후보를 안전하게 검증하는 것입니다.

## 핵심 기능

- Toss API 기반 캔들/호가 read-only 수집
- 페이퍼 트레이딩 및 백테스트
- walk-forward 검증
- 수수료, 세금, 슬리피지 반영
- 5호가 depth / market impact 가드
- stale data / 장중 시간창 가드
- multi-capital 검증
- stress test
- 전략 edge audit

## 안전 원칙

- 기본값은 항상 dry-run / paper-only입니다.
- 실제 주문 전송 경로는 포함하지 않습니다.
- API 키, 계좌 정보, `.env`, DB/runtime 데이터는 커밋하지 않습니다.
- 이 프로젝트는 투자 조언이 아니며, 손실 가능성이 있습니다.

## 테스트

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

## 상태

아직 수익 edge는 확립되지 않았습니다. 현재 시스템은 “수익 시스템”이 아니라 “실주문 전 검증/차단 시스템”입니다.
