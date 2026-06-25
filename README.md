# Toss Auto Trader

Toss Open API를 이용해 한국 주식 자동매매를 연구하는 개인 학습용 실험실입니다.

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
