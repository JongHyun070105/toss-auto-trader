# Toss Auto Trader Lab

Toss Invest Open API를 이용해 한국 주식 자동매매를 연구하는 개인 학습용 실험실입니다.

현재 목표는 실주문이 아니라, 전략 후보를 안전하게 검증하고 실주문 전 단계에서 차단/승격 조건을 명확히 만드는 것입니다.

## 핵심 기능

- Toss API 기반 캔들/호가 read-only 수집
- 페이퍼 트레이딩 및 백테스트
- walk-forward 검증
- 다중 전략 후보 평가 및 strategy discovery loop
- 수수료, 세금, 슬리피지 반영
- 5호가 depth / market impact 가드
- stale data / 장중 시간창 가드
- multi-capital 검증
- stress test
- 전략 edge audit
- pre-live checklist와 별도 live-order approval gate

## 안전 원칙

- 기본값은 항상 dry-run / paper-only입니다.
- 전략 탐색 루프는 `order_sent=false`, `live_order_allowed=false`를 유지하며 live 주문을 보내지 않습니다.
- `order-live-send` 명령은 별도 승인 경로로 분리되어 있고, 기본은 plan-only입니다.
- 실제 주문 전송은 candidate file approval, spread/observation/stress/edge gate, exact fingerprint confirmation, `TOSS_DRY_RUN=false`, `TOSS_LIVE_TRADING=true`가 모두 필요합니다.
- API 키, 계좌 정보, `.env`, DB/runtime 데이터는 커밋하지 않습니다.
- 이 프로젝트는 투자 조언이 아니며, 손실 가능성이 있습니다.

## 설치

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
cp .env.example .env
```

`.env`에는 실제 Toss API 값을 넣고 Git에 커밋하지 마세요.

## 테스트

```bash
PYTHONPATH=src TOSS_DRY_RUN=true TOSS_LIVE_TRADING=false python3 -m unittest discover -s tests -v
```

## 운영 보조 스크립트

최신 일봉 캐시는 장마감 후 Toss API로 최근 봉만 `INSERT OR REPLACE` 하도록 갱신할 수 있습니다. 기존 장기 DB는 유지하고 최신 구간만 Toss 포맷으로 정규화합니다.

```bash
PYTHONPATH=src python3 scripts/cache_toss_candles_daily.py
```

`simple_gap_trader.py`의 2차 검증은 daily candle 기반 no-send audit으로 실행합니다. 결과 JSON은 로컬 `data/` 아래에 저장되며 커밋하지 않습니다.

```bash
python3 scripts/simple_gap_strategy_audit.py
```

대시보드 HTML은 로컬 로그/DB/audit JSON을 읽어 생성합니다. `logs/dashboard.html`은 런타임 산출물이므로 커밋하지 않습니다.

```bash
python3 scripts/dashboard.py
```

## 전략 탐색 루프

현재 전략 탐색 루프는 여러 전략 산출물을 평가하지만, 주문을 보내지 않습니다.

```bash
PYTHONPATH=src TOSS_DRY_RUN=true TOSS_LIVE_TRADING=false \
python3 scripts/strategy_discovery_loop.py --audit-pack forward --max-cycles 1
```

자세한 설명:

```text
docs/STRATEGY_DISCOVERY_LOOP.md
```

## Live order approval

문서:

```text
docs/LIVE_ORDER_APPROVAL_FLOW.md
```

실주문은 자동 탐색 루프에서 직접 실행하지 않습니다. 좋은 전략이 forward/paper 기준을 통과해도 먼저 `pre_live_review_candidate_not_live_order` 상태로 멈춥니다.

## GitHub 공개/업로드 제외 대상

아래 항목은 로컬 런타임/민감정보라 업로드하지 않습니다.

```text
.env
data/
logs/
graphify-out/
external/
*.sqlite*
*.db
*.log
.venv/
```

## 상태

아직 수익 edge는 확립되지 않았습니다. 현재 시스템은 “수익 시스템”이 아니라 “실주문 전 검증/차단 시스템”입니다.
