# Toss Auto Trader Lab

Toss Invest Open API를 이용해 한국 주식 자동매매 전략을 검증하고 운용 보조 자동화를 관리하는 개인 연구용 프로젝트입니다.

현재 메인 운용 코드는 `scripts/simple_gap_trader.py`입니다. 전략 탐색/백테스트 산출물을 바탕으로 보수적으로 고정한 갭하락 반등 전략을 소액 실전 계좌에서 돌리고, 손절/익절 이후 가격 흐름은 paper-only 로그로 계속 쌓습니다.

## 현재 메인 전략

전략명: `robust_gap5_stop0225_take12`

매수 진입은 09:01에 한 번만 실행합니다. 실전 주문은 KST 09:00 이상 09:05 미만에만 허용하며, 스캔이 길어지면 주문 직전에 시각을 다시 확인해 09:05 이후 주문을 차단합니다.

- 시장 가드: Toss 시장지표 API의 KOSDAQ 현재값이 실시간 5일선의 `0.99` 이하일 때만 매수
- 종목 가격: 전일 종가 `1,000원~8,000원`
- 전일 거래량: 직전 20일 평균의 `0.8배` 미만
- 갭 조건: 당일 일봉 시가 기준 전일 종가 대비 `-5%` 이하
- 후보 선택: 조건 통과 종목 중 시가가 가장 낮은 1종목
- 제외 조건: Toss/Naver 경고, 단기과열, 투자경고/위험, VI, 정리매매 등
- 장중 청산: monitor가 `-2.25%` 손절 또는 `+12%` 익절 조건을 만족하면 시장가 매도
- 마감 정리: 15:20까지 장중 청산되지 않고 남아 있는 전략 보유분만 시장가 매도

시장지표 시각이 5분 이상 지연되거나, Toss 장 캘린더의 정규장 시작 후 5분 이내가 아니거나, 거래일/전 영업일/일봉 데이터가 서로 맞지 않거나, API 조회에 실패하면 매수하지 않습니다. 매수·매도 주문 접수만으로 체결로 간주하지 않으며 Toss 주문 상세의 실제 체결 수량을 확인한 뒤 상태와 결과를 확정합니다.

주문 응답이 유실되면 종목·방향·수량이 같은 계좌 주문을 추정해 연결하지 않습니다. 저장해 둔 동일 `clientOrderId`와 동일 주문 본문만 Toss의 10분 멱등성 유효시간 안에서 다시 보내 주문ID를 복구합니다. 유효시간 안에 복구하지 못하면 수동 확인 전까지 해당 전략의 추가 주문을 차단합니다.

장중 손절 후 같은 종목을 다시 사는 live 재진입은 하지 않습니다. 대신 손절/익절 이후 가격 흐름만 `paper-only`로 기록해 다음 백테스트와 조건 개선에 사용합니다.

## 주요 파일

- `scripts/simple_gap_trader.py`: 09:01 매수, 장중 손절/익절 monitor, 15:20 잔여 보유분 정리
- `scripts/toss_discord_report.py`: buy/sell/KOSDAQ/candle-update Discord 보고
- `src/toss_auto_trader/simple_gap_state.py`: 전략 주문·체결·잔여 수량 상태를 원자적으로 저장하고 복구
- `src/toss_auto_trader/paper_reentry_watch.py`: 손절/익절 이후 관찰 로그 호환 진입점
- `src/toss_auto_trader/paper_exit_models.py`: paper-only exit event 모델과 기록 함수
- `src/toss_auto_trader/paper_exit_update.py`: 손절 후 추가하락, 익절 후 추가상승 감시
- `src/toss_auto_trader/paper_exit_outcomes.py`: 10분/30분/종가 outcome 계산
- `src/toss_auto_trader/paper_exit_messages.py`: monitor 로그 출력 문구 포맷
- `data/edge_research_universe_15y.sqlite3`: 메인 스크리닝용 장기 일봉 DB

## 로그

운영 로그는 `logs/` 아래에 남습니다.

- `logs/simple_gap_trader_buy.log`: 09:01 매수 실행 로그
- `logs/simple_gap_trader_monitor.log`: 장중 손절/익절 monitor 로그
- `logs/simple_gap_trader_sell.log`: 15:20 잔여 보유분 정리 로그
- `logs/simple_gap_trader_state.json`: 이 전략이 실제로 보유한 수량과 주문 체결 상태
- `logs/simple_gap_trader_events.jsonl`: 주문·체결 상태 전이 감사 로그
- `logs/simple_gap_trader.lock`: buy/monitor/sell 프로세스 중복 실행 방지 잠금 파일
- `logs/toss_discord_report.log`: Discord 보고 및 candle update 로그
- `logs/simple_gap_reentry_watch.jsonl`: 손절/익절 이후 paper-only 관찰 로그
- `logs/simple_gap_breadth_shadow.jsonl`: breadth4의 09:01 현재가 대리값과 15:40 공식 시가 사후확정

`simple_gap_reentry_watch.jsonl`의 주요 이벤트:

- `stop_exit`: 손절 매도 성공 시점
- `paper_reentry_threshold`: 손절 후 추가 하락 `-3%/-5%/-7%`
- `paper_reentry_outcome`: 손절 후 가상 재진입의 10분/30분/종가 결과
- `take_profit_exit`: 익절 매도 성공 시점
- `paper_exit_price_snapshot`: 매도 후 현재가, 매도가 대비, 진입가 대비 변화
- `paper_missed_upside_threshold`: 익절 후 추가 상승 `+3%/+5%/+7%`
- `paper_missed_upside_outcome`: 익절 후 계속 보유 가설의 10분/30분/종가 결과

## 공개 일일 결과

GitHub에는 raw 로그 대신 [RESULTS.md](RESULTS.md)에 공개 가능한 일일 요약만 남깁니다.

포함 항목:

- 날짜
- 매수 종목과 기준가
- 장중 손절/익절 또는 15:20 정리 가격
- 실제 체결 수익률(Toss 주문상세 조회 가능 시)
- API 상세조회 실패 또는 주문ID 누락 시 예상가 기준 수익률
- 간단한 비고

제외 항목:

- 주문ID
- 계좌번호, 예수금, 계좌 평가액
- raw 로그 전문
- `data/`, `logs/`, `.env`, DB 파일

생성/갱신:

```bash
PYTHONPATH=src:scripts .venv/bin/python3 scripts/daily_result_markdown.py --date 2026-07-07
```

확인만 할 때:

```bash
PYTHONPATH=src:scripts .venv/bin/python3 scripts/daily_result_markdown.py --date 2026-07-07 --print-only
```

Toss 주문상세 API를 쓰지 않고 로그 예상가 기준으로만 확인하려면:

```bash
PYTHONPATH=src:scripts .venv/bin/python3 scripts/daily_result_markdown.py --date 2026-07-07 --print-only --no-api
```

## 설치

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
cp .env.example .env
```

`.env`에는 실제 Toss API 값을 넣고 Git에 커밋하지 않습니다.

필수 환경 변수:

```text
TOSS_CLIENT_ID=...
TOSS_CLIENT_SECRET=...
TOSS_ACCOUNT_SEQ=...
TOSS_DRY_RUN=true
TOSS_LIVE_TRADING=false
```

실전 주문을 보낼 때만 `TOSS_DRY_RUN=false`, `TOSS_LIVE_TRADING=true`로 둡니다.

## 수동 실행

```bash
PYTHONPATH=src:scripts .venv/bin/python3 scripts/simple_gap_trader.py --action buy
PYTHONPATH=src:scripts .venv/bin/python3 scripts/simple_gap_trader.py --action monitor
PYTHONPATH=src:scripts .venv/bin/python3 scripts/simple_gap_trader.py --action sell
```

Discord 보고 dry-run:

```bash
PYTHONPATH=src:scripts .venv/bin/python3 scripts/toss_discord_report.py --action buy-report --print-only
PYTHONPATH=src:scripts .venv/bin/python3 scripts/toss_discord_report.py --action sell-report --print-only
PYTHONPATH=src:scripts .venv/bin/python3 scripts/toss_discord_report.py --action kosdaq-close --print-only
PYTHONPATH=src:scripts .venv/bin/python3 scripts/toss_discord_report.py --action candle-update --dry-run-update --update-limit 3 --print-only
```

주의: `--action candle-update`는 기본적으로 실제 DB 업데이트를 실행합니다. 검증만 할 때는 `--dry-run-update`를 붙입니다.

## Cron 운영

현재 macOS crontab 운용 기준:

```cron
PATH=/Users/macintosh/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin
TOSS_MONITOR_DISCORD_TARGET=discord:<channel_id>

1 9 * * 1-5 cd /Users/macintosh/IdeaProjects/toss-auto-trader-lab && .venv/bin/python3 scripts/simple_gap_trader.py --action buy >> logs/simple_gap_trader_buy.log 2>&1
5 9 * * 1-5 cd /Users/macintosh/IdeaProjects/toss-auto-trader-lab && .venv/bin/python3 scripts/toss_discord_report.py --action buy-report --to discord:<channel_id> >> logs/toss_discord_report.log 2>&1
2-59 9 * * 1-5 cd /Users/macintosh/IdeaProjects/toss-auto-trader-lab && .venv/bin/python3 scripts/simple_gap_trader.py --action monitor >> logs/simple_gap_trader_monitor.log 2>&1
* 10-14 * * 1-5 cd /Users/macintosh/IdeaProjects/toss-auto-trader-lab && .venv/bin/python3 scripts/simple_gap_trader.py --action monitor >> logs/simple_gap_trader_monitor.log 2>&1
0-19 15 * * 1-5 cd /Users/macintosh/IdeaProjects/toss-auto-trader-lab && .venv/bin/python3 scripts/simple_gap_trader.py --action monitor >> logs/simple_gap_trader_monitor.log 2>&1
20-31 15 * * 1-5 cd /Users/macintosh/IdeaProjects/toss-auto-trader-lab && .venv/bin/python3 scripts/simple_gap_trader.py --action sell >> logs/simple_gap_trader_sell.log 2>&1
33 15 * * 1-5 cd /Users/macintosh/IdeaProjects/toss-auto-trader-lab && .venv/bin/python3 scripts/toss_discord_report.py --action sell-report --to discord:<channel_id> >> logs/toss_discord_report.log 2>&1
35 15 * * 1-5 cd /Users/macintosh/IdeaProjects/toss-auto-trader-lab && .venv/bin/python3 scripts/toss_discord_report.py --action kosdaq-close --to discord:<channel_id> >> logs/toss_discord_report.log 2>&1
40 15 * * 1-5 cd /Users/macintosh/IdeaProjects/toss-auto-trader-lab && .venv/bin/python3 scripts/toss_discord_report.py --action candle-update --to discord:<channel_id> >> logs/toss_discord_report.log 2>&1
```

장중 monitor 손절/익절 즉시 알림은 `TOSS_MONITOR_DISCORD_TARGET` 또는 `TOSS_DISCORD_TARGET`이 설정되어 있을 때만 전송합니다. monitor 전용 채널을 따로 쓰려면 `TOSS_MONITOR_DISCORD_TARGET=discord:<channel_id>`를 추가합니다.

`simple_gap_trader.py`는 전체 buy/monitor/sell 처리 구간에 파일 잠금을 사용합니다. 앞선 실행이 끝나지 않은 상태에서 다음 cron이 겹치면 뒤 실행은 주문을 보내지 않고 종료하므로, 15:20~15:31 반복 실행이 중복 매도를 만들지 않습니다.

`RESULTS.md`를 장마감 후 자동 갱신만 하려면 다음 작업을 추가합니다. Git push는 수동으로 검토 후 실행합니다.

```cron
34 15 * * 1-5 cd /Users/macintosh/IdeaProjects/toss-auto-trader-lab && PYTHONPATH=src:scripts .venv/bin/python3 scripts/daily_result_markdown.py >> logs/daily_result_markdown.log 2>&1
```

등록 확인:

```bash
crontab -l | grep -E 'simple_gap_trader|toss_discord_report'
```

macOS 사용자 crontab은 재부팅 후에도 등록 자체는 유지됩니다. 다만 장 시작 전에는 컴퓨터 전원, 네트워크, 터미널 권한, `.env`, 가상환경 경로가 정상인지 확인해야 합니다.

## 백테스트/분석 스크립트

전략 후보 검증과 리스크 점검용 스크립트는 `scripts/` 아래에 있습니다. 결과 JSON/CSV는 보통 `data/` 아래에 남기고 커밋하지 않습니다.

국내 전략의 2026-07-18 폭넓은 조건 재검증 결과는
`docs/KR_STRATEGY_BROAD_RESEARCH_2026-07-18.md`에 정리되어 있습니다. 현재 실전
전략은 변경하지 않았고, `-5% 이하 갭 종목 4개 이상` 조건만 섀도 관찰 후보로
분류했습니다. 09:01에는 20일 유효 이력을 갖춘 500~30,000원 모집단을 대상으로
주문 처리 후 현재가 기준 개수를 기록하고, 15:40 실제 캔들 업데이트가 완료되면
공식 일봉 시가와 OHLC 유효성 기준 개수를 같은 로컬 JSONL에 사후 확정합니다.
두 값 모두 실매매 주문 조건에는 사용하지 않습니다.

ATR 정규화 갭, 종목별 갭 z-score, KOSDAQ 잔차 갭, 252일 가격 위치,
갭 메우기·ATR 적응형 청산처럼 기존 그리드에 없던 기법의 후속 결과는
`docs/KR_NOVEL_FEATURE_RESEARCH_2026-07-18.md`에 있습니다. 32개 가설을
추가로 검사했지만 실전 교체 조건을 통과한 후보는 없어 live trader는 유지했습니다.

국내 논문과 공개 자동매매 구현에서 가져온 beta 잔차 갭, 저변동성, MAX,
Amihud, 50일 표준화 거래량, 갭·모멘텀 횡단면 z-score 및 익일 시가 청산의
재현 결과는 `docs/KR_EXTERNAL_METHOD_RESEARCH_2026-07-18.md`에 있습니다.
20개 방법을 추가로 비교했지만 현재 최저시가 1순위와 당일 청산을 교체할 후보는
없었습니다.

해외 미시구조·유동성·변동성 연구를 95개 고정 방법으로 확장하고, KRX 당시
투자주의·경고·위험 이력과 상장폐지 종목 보강 DB까지 대조한 결과는
`docs/KR_FOREIGN_MICROSTRUCTURE_RESEARCH_2026-07-19.md`에 있습니다. 신규
실전 승격 후보는 없었으며 현재 주문 코드와 전략값은 변경하지 않았습니다.

```bash
PYTHONPATH=src:scripts .venv/bin/python3 scripts/simple_gap_strategy_audit.py
PYTHONPATH=src:scripts .venv/bin/python3 scripts/simple_gap_robustness_sweep.py
PYTHONPATH=src:scripts .venv/bin/python3 scripts/simple_gap_market_context.py
PYTHONPATH=src:scripts .venv/bin/python3 scripts/current_strategy_risk_audit.py
PYTHONPATH=src:scripts .venv/bin/python3 scripts/kr_broad_strategy_research.py
PYTHONPATH=src:scripts .venv/bin/python3 scripts/kr_condition_sensitivity.py
PYTHONPATH=src:scripts .venv/bin/python3 scripts/kr_guard_fallback_research.py
PYTHONPATH=src:scripts .venv/bin/python3 scripts/kr_breadth_gate_research.py
PYTHONPATH=src:scripts .venv/bin/python3 scripts/kr_novel_feature_research.py
PYTHONPATH=src:scripts .venv/bin/python3 scripts/kr_external_method_research.py
PYTHONPATH=src:scripts .venv/bin/python3 scripts/kr_foreign_microstructure_research.py
PYTHONPATH=src:scripts .venv/bin/python3 scripts/compare_foreign_research_runs.py
PYTHONPATH=src:scripts .venv/bin/python3 scripts/validate_foreign_research_mission.py
PYTHONPATH=src:scripts .venv/bin/python3 scripts/breadth_shadow_summary.py
```

미국주식 연구 경로도 주문 API를 호출하지 않습니다. 현재 결론과 검증 한계는
`docs/US_MARKET_RESEARCH_2026-07-18.md`에 정리되어 있으며, 미국 전략은 아직
실전 코드나 cron에 연결하지 않습니다.

```bash
PYTHONPATH=src:scripts .venv/bin/python3 scripts/cache_toss_us_research_data.py
PYTHONPATH=src:scripts .venv/bin/python3 scripts/us_gap_strategy_research.py
PYTHONPATH=src:scripts .venv/bin/python3 scripts/us_strategy_family_research.py
PYTHONPATH=src:scripts .venv/bin/python3 scripts/us_etf_strategy_research.py
```

전략 탐색 루프는 주문을 보내지 않습니다.

```bash
PYTHONPATH=src TOSS_DRY_RUN=true TOSS_LIVE_TRADING=false \
.venv/bin/python3 scripts/strategy_discovery_loop.py --audit-pack forward --max-cycles 1
```

## 테스트

전체 테스트:

```bash
PYTHONPATH=src:scripts TOSS_DRY_RUN=true TOSS_LIVE_TRADING=false .venv/bin/python3 -m unittest discover -s tests -v
```

메인 운영 경로 관련 빠른 테스트:

```bash
PYTHONPATH=src:scripts .venv/bin/python3 -m unittest \
  tests.test_simple_gap_trader \
  tests.test_simple_gap_reentry_watch \
  tests.test_paper_reentry_watch \
  tests.test_toss_discord_report
```

문법 확인:

```bash
.venv/bin/python3 -m py_compile scripts/simple_gap_trader.py scripts/toss_discord_report.py
```

## 안전 원칙

- API 키, 계좌 정보, `.env`, DB/runtime 데이터는 커밋하지 않습니다.
- 실전 주문은 `simple_gap_trader.py`의 buy/monitor/sell 경로에서만 제한적으로 실행합니다.
- 계좌 전체 보유분이 아니라 `simple_gap_trader_state.json`에 기록된 전략 보유 수량만 청산합니다.
- 주문 접수 응답은 체결이 아닙니다. 실제 체결 수량을 주문 상세로 확인한 뒤 알림과 수익률 로그를 확정합니다.
- 주문ID 복구는 동일 멱등키·동일 본문 재전송만 사용하며, 계좌의 유사한 수동 주문을 전략 주문으로 간주하지 않습니다.
- buy/monitor/sell은 프로세스 잠금으로 직렬화하며, 겹친 cron 실행은 주문 경로에 진입하지 않습니다.
- 시장 가드 입력이 지연·누락·불일치하면 실패 차단하며, 실전에서 `--force`로 우회할 수 없습니다.
- 손절 후 재진입, 익절 후 추격매수는 live 주문으로 실행하지 않습니다.
- 손절/익절 이후 가격 흐름은 paper-only 로그로만 남깁니다.
- 매매 판단은 백테스트와 실시간 API 제약이 다를 수 있으므로, 실전 로그를 별도 근거로 계속 검증합니다.
- 이 프로젝트는 투자 조언이 아니며 손실 가능성이 있습니다.

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

## 현재 상태

현재 시스템은 수익을 보장하는 시스템이 아니라, 소액 실전 로그를 쌓으며 전략 조건을 검증하는 자동매매 실험 환경입니다. 메인 전략은 고정되어 있지만, 손절/익절 이후 관찰 로그를 통해 청산 조건과 시장 가드 개선 여부를 계속 판단합니다.
