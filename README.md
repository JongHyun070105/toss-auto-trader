# Toss Auto Trader Lab

Toss Invest Open API를 이용해 한국 주식 자동매매 전략을 검증하고 운용 보조 자동화를 관리하는 개인 연구용 프로젝트입니다.

현재 메인 운용 코드는 `scripts/simple_gap_trader.py`입니다. 전략 탐색/백테스트 산출물을 바탕으로 보수적으로 고정한 갭하락 반등 전략을 소액 실전 계좌에서 돌리고, 손절/익절 이후 가격 흐름은 paper-only 로그로 계속 쌓습니다.

## 현재 메인 전략

전략명: `robust_gap5_stop0225_take12`

매수 진입은 09:01에 한 번만 실행합니다.

- 시장 가드: KOSDAQ 현재값이 5일선의 `0.99` 이하일 때만 매수
- 종목 가격: 전일 종가 `1,000원~8,000원`
- 전일 거래량: 직전 20일 평균의 `0.8배` 미만
- 갭 조건: 당일 일봉 시가 기준 전일 종가 대비 `-5%` 이하
- 후보 선택: 조건 통과 종목 중 시가가 가장 낮은 1종목
- 제외 조건: Toss/Naver 경고, 단기과열, 투자경고/위험, VI, 정리매매 등
- 장중 청산: monitor가 `-2.25%` 손절 또는 `+12%` 익절 조건을 만족하면 지정가 매도
- 마감 정리: 15:20까지 장중 청산되지 않고 남아 있는 보유분만 지정가 매도

장중 손절 후 같은 종목을 다시 사는 live 재진입은 하지 않습니다. 대신 손절/익절 이후 가격 흐름만 `paper-only`로 기록해 다음 백테스트와 조건 개선에 사용합니다.

## 주요 파일

- `scripts/simple_gap_trader.py`: 09:01 매수, 장중 손절/익절 monitor, 15:20 잔여 보유분 정리
- `scripts/toss_discord_report.py`: buy/sell/KOSDAQ/candle-update Discord 보고
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
- `logs/toss_discord_report.log`: Discord 보고 및 candle update 로그
- `logs/simple_gap_reentry_watch.jsonl`: 손절/익절 이후 paper-only 관찰 로그

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
- 예상 수익률
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
1 9 * * 1-5 cd /Users/macintosh/IdeaProjects/toss-auto-trader-lab && .venv/bin/python3 scripts/simple_gap_trader.py --action buy >> logs/simple_gap_trader_buy.log 2>&1
5 9 * * 1-5 cd /Users/macintosh/IdeaProjects/toss-auto-trader-lab && .venv/bin/python3 scripts/toss_discord_report.py --action buy-report --to discord:<channel_id> >> logs/toss_discord_report.log 2>&1
2-59 9 * * 1-5 cd /Users/macintosh/IdeaProjects/toss-auto-trader-lab && .venv/bin/python3 scripts/simple_gap_trader.py --action monitor >> logs/simple_gap_trader_monitor.log 2>&1
*/2 10-14 * * 1-5 cd /Users/macintosh/IdeaProjects/toss-auto-trader-lab && .venv/bin/python3 scripts/simple_gap_trader.py --action monitor >> logs/simple_gap_trader_monitor.log 2>&1
0-18/2 15 * * 1-5 cd /Users/macintosh/IdeaProjects/toss-auto-trader-lab && .venv/bin/python3 scripts/simple_gap_trader.py --action monitor >> logs/simple_gap_trader_monitor.log 2>&1
20 15 * * 1-5 cd /Users/macintosh/IdeaProjects/toss-auto-trader-lab && .venv/bin/python3 scripts/simple_gap_trader.py --action sell >> logs/simple_gap_trader_sell.log 2>&1
25 15 * * 1-5 cd /Users/macintosh/IdeaProjects/toss-auto-trader-lab && .venv/bin/python3 scripts/toss_discord_report.py --action sell-report --to discord:<channel_id> >> logs/toss_discord_report.log 2>&1
32 15 * * 1-5 cd /Users/macintosh/IdeaProjects/toss-auto-trader-lab && .venv/bin/python3 scripts/toss_discord_report.py --action kosdaq-close --to discord:<channel_id> >> logs/toss_discord_report.log 2>&1
40 15 * * 1-5 cd /Users/macintosh/IdeaProjects/toss-auto-trader-lab && .venv/bin/python3 scripts/toss_discord_report.py --action candle-update --to discord:<channel_id> >> logs/toss_discord_report.log 2>&1
```

`RESULTS.md`를 장마감 후 자동 갱신만 하려면 다음 작업을 추가합니다. Git push는 수동으로 검토 후 실행합니다.

```cron
28 15 * * 1-5 cd /Users/macintosh/IdeaProjects/toss-auto-trader-lab && PYTHONPATH=src:scripts .venv/bin/python3 scripts/daily_result_markdown.py >> logs/daily_result_markdown.log 2>&1
```

등록 확인:

```bash
crontab -l | grep -E 'simple_gap_trader|toss_discord_report'
```

macOS 사용자 crontab은 재부팅 후에도 등록 자체는 유지됩니다. 다만 장 시작 전에는 컴퓨터 전원, 네트워크, 터미널 권한, `.env`, 가상환경 경로가 정상인지 확인해야 합니다.

## 백테스트/분석 스크립트

전략 후보 검증과 리스크 점검용 스크립트는 `scripts/` 아래에 있습니다. 결과 JSON/CSV는 보통 `data/` 아래에 남기고 커밋하지 않습니다.

```bash
PYTHONPATH=src:scripts .venv/bin/python3 scripts/simple_gap_strategy_audit.py
PYTHONPATH=src:scripts .venv/bin/python3 scripts/simple_gap_robustness_sweep.py
PYTHONPATH=src:scripts .venv/bin/python3 scripts/simple_gap_market_context.py
PYTHONPATH=src:scripts .venv/bin/python3 scripts/current_strategy_risk_audit.py
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
