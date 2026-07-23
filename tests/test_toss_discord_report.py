import importlib.util
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch


def load_report():
    path = Path(__file__).resolve().parents[1] / "scripts" / "toss_discord_report.py"
    spec = importlib.util.spec_from_file_location("toss_discord_report", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TossDiscordReportTests(unittest.TestCase):
    def setUp(self):
        self.mod = load_report()

    def test_parse_buy_session_reports_reason_and_order(self):
        lines = [
            "실행 시간: 2026-07-01 09:01:05",
            "모드: 실전 매매",
            "현재 KOSDAQ 지수: 921.09 | 5일 이평선: 898.03",
            "✅ 지수 가드 통과: 현재 상승/횡보세 국면입니다.",
            "최근 데이터 영업일: 2026-06-30",
            "로컬 스크리닝 필터 통과 종목 수: 671개",
            "실제 예수금: 100,000원 | 이번 매수 사용 예산: 100,000원 (계좌 매수가능금액 전체)",
            "성능 측정: price_chunks=7 price_rows=665 provisional_gap_hits=12 daily_open_calls=12 daily_open_missing=1 daily_open_confirmed_hits=2 gap_integrity_exclusions=1 scan_elapsed=18.50s",
            "갭 하락 5.0% 돌파 종목 수: 2개",
            "[섀도 breadth4] 09:01 현재가 기준 -5% 갭: 5개 / 기준: 4개 / 모집단: 1800개 / 시세수신: 1790개 / 상태: pass / 실매매 미적용",
            "  [123456] 테스트 | 갭률: -3.20% | 시가: 9,600원 | 현재가: 9,650원 | 전일종가: 10,000원",
            "  ⛔ [091590] 091590 매수 유의사항 필터 제외: OVERHEATED, INVESTMENT_WARNING",
            "  🚀 [테스트] 10주 지정가 매수 주문 발송 (배정금액 96,500원, 지정가 9,650원)...",
            "  * [실전 주문] 주문 성공! 주문ID: ORD-1",
            "프로그램 종료: 2026-07-01 09:01:24 / 총 실행시간: 19.25초",
        ]
        parsed = self.mod.parse_buy_session(lines)
        self.assertEqual(parsed["guard"], "통과")
        self.assertEqual(parsed["order"]["name"], "테스트")
        self.assertEqual(parsed["order"]["qty"], 10)
        self.assertTrue(parsed["order_success"])
        self.assertEqual(parsed["end_datetime"], "2026-07-01 09:01:24")
        self.assertEqual(parsed["total_elapsed_sec"], 19.25)
        self.assertEqual(parsed["perf"]["daily_open_calls"], 12)
        self.assertEqual(parsed["perf"]["scan_elapsed_sec"], 18.5)
        self.assertEqual(parsed["perf"]["gap_integrity_exclusions"], 1)
        self.assertEqual(parsed["breadth_shadow"]["provisional_gap5_count"], 5)
        self.assertFalse(parsed["breadth_shadow"]["applied_to_live_order"])
        self.assertEqual(parsed["warning_exclusions"][0]["symbol"], "091590")
        self.assertIn("INVESTMENT_WARNING", parsed["warning_exclusions"][0]["warnings"])
        self.assertIn("갭하락", parsed["reason"])

    def test_parse_buy_session_keeps_old_performance_log_compatible(self):
        parsed = self.mod.parse_buy_session(
            [
                "성능 측정: price_chunks=7 price_rows=665 provisional_gap_hits=12 "
                "daily_open_calls=12 daily_open_missing=1 "
                "daily_open_confirmed_hits=2 scan_elapsed=18.50s"
            ]
        )

        self.assertEqual(parsed["perf"]["gap_integrity_exclusions"], 0)
        self.assertEqual(parsed["perf"]["scan_elapsed_sec"], 18.5)

    def test_buy_report_includes_gap_integrity_exclusion_count(self):
        parsed = self.mod.parse_buy_session(
            [
                "실행 시간: 2026-07-23 09:01:00",
                "모드: 실전 매매",
                "성능 측정: price_chunks=12 price_rows=1160 "
                "provisional_gap_hits=3 daily_open_calls=3 "
                "daily_open_missing=0 daily_open_confirmed_hits=2 "
                "gap_integrity_exclusions=1 scan_elapsed=9.11s",
                "프로그램 종료: 2026-07-23 09:01:10 / 총 실행시간: 10.00초",
            ]
        )
        parsed["session_count"] = 1

        with patch.object(
            self.mod, "aggregate_buy_sessions_for_date", return_value=parsed
        ):
            report = self.mod.buy_report("2026-07-23")

        self.assertIn("기준가 비비교 갭 제외 1개", report)

    def test_buy_report_does_not_fetch_detail_for_none_order_id(self):
        lines = [
            "실행 시간: 2026-07-07 09:01:01",
            "모드: 실전 매매",
            "현재 KOSDAQ 지수: 844.31 | 5일 이평선: 871.17 | 매수 허용선: 862.46",
            "✅ 지수 가드 통과: KOSDAQ이 5일선보다 1% 이상 아래인 눌림 국면입니다.",
            "최근 데이터 영업일: 2026-07-06",
            "로컬 스크리닝 필터 통과 종목 수: 1142개",
            "실제 예수금: 10,000원 | 이번 매수 사용 예산: 10,000원 (상한 10,000원)",
            "갭 하락 5.0% 돌파 종목 수: 16개",
            "  🚀 [321370] 5주 지정가 매수 주문 발송 (전략 robust_gap5_stop0225_take12, 배정금액 8,910원, 지정가 1,782원, 손절가 1,742원, 익절가 1,996원)...",
            "  * [실전 주문] 주문 성공! 주문ID: None",
            "프로그램 종료: 2026-07-07 09:01:23 / 총 실행시간: 22.45초",
        ]

        parsed = self.mod.parse_buy_session(lines)
        parsed["session_count"] = 1
        with patch.object(self.mod, "aggregate_buy_sessions_for_date", return_value=parsed):
            with patch.object(self.mod, "fetch_order_details", side_effect=AssertionError("must not fetch None order id")):
                report = self.mod.buy_report("2026-07-07")

        self.assertIn("주문ID: 확인 필요", report)
        self.assertIn("매수 실제 체결: 상세조회 없음", report)
        self.assertNotIn("상세조회 실패", report)

    def test_buy_report_labels_breadth_as_shadow_only(self):
        parsed = self.mod.parse_buy_session([
            "실행 시간: 2026-07-17 09:01:00",
            "모드: 실전 매매",
            "현재 KOSDAQ 지수: 780.00 | 당일 시가: 781.00 | 5일 이평선: 800.00 | 매수 허용선: 792.00",
            "✅ 지수 가드 통과: KOSDAQ이 5일선보다 1% 이상 아래인 눌림 국면입니다.",
            "[섀도 breadth4] 09:01 현재가 기준 -5% 갭: 5개 / 기준: 4개 / 모집단: 1800개 / 시세수신: 1790개 / 상태: pass / 실매매 미적용",
            "프로그램 종료: 2026-07-17 09:01:10 / 총 실행시간: 10.00초",
        ])
        parsed["session_count"] = 1

        with patch.object(self.mod, "aggregate_buy_sessions_for_date", return_value=parsed):
            report = self.mod.buy_report("2026-07-17")

        self.assertIn("breadth4 섀도: 09:01 현재가 기준 5개", report)
        self.assertIn("상태 pass", report)
        self.assertIn("실매매 미적용", report)

    def test_parse_buy_session_reports_new_market_gate_block_reason(self):
        lines = [
            "실행 시간: 2026-07-06 09:01:01",
            "모드: 실전 매매",
            "현재 KOSDAQ 지수: 895.00 | 당일 시가: 896.50 | 5일 이평선: 900.00 | 매수 허용선: 891.00 | 지수 시각: 2026-07-20T00:00:00.000+09:00 | 최신성 검증: today_candle_close_crosscheck",
            "🚨 [시장 가드 발동] KOSDAQ이 5일선보다 1% 이상 아래가 아니므로 오늘 매매는 정지합니다.",
            "프로그램 종료: 2026-07-06 09:01:01 / 총 실행시간: 0.07초",
        ]

        parsed = self.mod.parse_buy_session(lines)

        self.assertEqual(parsed["guard"], "차단")
        self.assertEqual(parsed["kosdaq_open"], 896.5)
        self.assertEqual(parsed["buy_line"], 891.0)
        self.assertEqual(parsed["market_timestamp"], "2026-07-20T00:00:00.000+09:00")
        self.assertEqual(parsed["market_freshness"], "today_candle_close_crosscheck")
        self.assertIn("1% 이상 아래가 아니라", parsed["reason"])

    def test_buy_report_marks_guard_skipped_fields_without_malformed_counts(self):
        lines = [
            "실행 시간: 2026-07-14 09:01:00",
            "모드: 실전 매매",
            "현재 KOSDAQ 지수: 800.17 | 당일 시가: 799.34 | 5일 이평선: 803.19 | 매수 허용선: 795.16 | 지수 시각: 2026-07-14T00:00:00.000+09:00 | 최신성 검증: today_candle_close_crosscheck",
            "🚨 [시장 가드 발동] KOSDAQ이 5일선보다 1% 이상 아래가 아니므로 오늘 매매는 정지합니다.",
            "프로그램 종료: 2026-07-14 09:01:00 / 총 실행시간: 0.06초",
        ]

        parsed = self.mod.parse_buy_session(lines)
        parsed["session_count"] = 1
        with patch.object(self.mod, "aggregate_buy_sessions_for_date", return_value=parsed):
            report = self.mod.buy_report("2026-07-14")

        self.assertIn("KOSDAQ: 800.17 / 시가: 799.34 / SMA5: 803.19 / 매수 허용선: 795.16 / 가드: 차단", report)
        self.assertIn("DB 기준일: 미조회(시장 가드 차단) / 스크리닝: 미실행 / 갭 후보: 미실행", report)
        self.assertIn("예수금: 미조회 / 사용예산: 미산정", report)
        self.assertIn("지수 최신성: Toss 당일 일봉 종가 교차검증 / 일봉 기준일: 2026-07-14", report)
        self.assertNotIn("지수 데이터 시각: 2026-07-14T00:00:00.000+09:00", report)
        self.assertNotIn("확인 필요개", report)

    def test_buy_report_preserves_earlier_successful_order_across_same_day_rerun(self):
        first = [
            "실행 시간: 2026-07-17 09:01:00",
            "모드: 실전 매매",
            "현재 KOSDAQ 지수: 780.00 | 당일 시가: 781.00 | 5일 이평선: 800.00 | 매수 허용선: 792.00",
            "✅ 지수 가드 통과: KOSDAQ이 5일선보다 1% 이상 아래인 눌림 국면입니다.",
            "  🚀 [테스트] 5주 지정가 매수 주문 발송 (전략 robust_gap5_stop0225_take12, 배정금액 9,000원, 지정가 1,800원, 손절가 1,760원, 익절가 2,016원)...",
            "  * [실전 주문] 매수 주문 접수! 주문ID: BUY-FIRST",
            "프로그램 종료: 2026-07-17 09:01:15 / 총 실행시간: 15.00초",
        ]
        rerun = [
            "실행 시간: 2026-07-17 09:03:00",
            "모드: 실전 매매",
            "[안전 중단] 오늘 이미 진입했거나 이전 전략 주문/포지션이 아직 종료되지 않았습니다.",
            "프로그램 종료: 2026-07-17 09:03:00 / 총 실행시간: 0.01초",
        ]
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "buy.log"
            log_path.write_text("\n".join(first + rerun) + "\n", encoding="utf-8")
            with (
                patch.object(self.mod, "BUY_LOG", log_path),
                patch.object(self.mod, "fetch_order_details", return_value={"BUY-FIRST": None}),
            ):
                report = self.mod.buy_report("2026-07-17")
                estimated = self.mod.estimate_buy_from_log("2026-07-17")

        self.assertIn("주문ID: BUY-FIRST", report)
        self.assertIn("당일 매수 실행 로그: 2회", report)
        self.assertEqual(estimated["order_id"], "BUY-FIRST")

    def test_parse_sell_session_reads_expected_price(self):
        lines = [
            "실행 시간: 2026-07-01 15:20:00",
            "모드: 실전 매매",
            "현재 보유 종목 수: 1개. 전량 지정가 종가 매도를 실행합니다.",
            "  🚀 [테스트] 10주 지정가 매도 주문 발송 (지정가 10,200원, 예상금액 102,000원)...",
            "  * [실전 주문] 매도 주문 성공! 주문ID: ORD-2",
        ]
        parsed = self.mod.parse_sell_session(lines)
        self.assertEqual(parsed["orders"][0]["expected_price"], 10200)
        self.assertEqual(parsed["orders"][0]["expected_amount"], 102000)
        self.assertTrue(parsed["orders"][0]["success"])

    def test_parse_monitor_session_reads_trigger_order(self):
        lines = [
            "실행 시간: 2026-07-01 09:07:00",
            "모드: 실전 매매",
            "현재 보유 종목 수: 1개. 손절/익절 모니터링을 실행합니다.",
            "  🚨 [테스트] 1주 손절 매도 주문 발송 (진입가 1,000원, 현재가 977원, 트리거 978원, 지정가 976원, 예상금액 976원)...",
            "  * [실전 주문] 모니터 매도 주문 성공! 주문ID: ORD-MON",
        ]
        parsed = self.mod.parse_monitor_session(lines)
        self.assertEqual(parsed["orders"][0]["trigger"], "손절")
        self.assertEqual(parsed["orders"][0]["entry_price"], 1000)
        self.assertEqual(parsed["orders"][0]["last_price"], 977)
        self.assertEqual(parsed["orders"][0]["expected_price"], 976)
        self.assertEqual(parsed["orders"][0]["order_id"], "ORD-MON")
        self.assertTrue(parsed["orders"][0]["success"])

    def test_parse_new_market_order_and_fill_logs(self):
        monitor_lines = [
            "실행 시간: 2026-07-17 09:07:00",
            "모드: 실전 매매",
            "  - [123456] 테스트 전략소유 2주(계좌 10주) | 진입가 1,000원 | 현재가 970원 | 손절가 978원 | 익절가 1,120원 | 수익률 -3.00%",
            "  🚨 [테스트] 2주 손절 시장가 매도 주문 발송...",
            "  * [실전 주문] 손절 시장가 매도 주문 접수! 주문ID: ORD-MKT",
            "  ✅ [123456] 손절 실제 체결 확인: 2주 @ 968원 / 수익률 -3.20%",
        ]
        sell_lines = [
            "실행 시간: 2026-07-17 15:20:00",
            "모드: 실전 매매",
            "  🚨 [테스트] 2주 종가청산 시장가 매도 주문 발송...",
            "  * [실전 주문] 종가청산 시장가 매도 주문 접수! 주문ID: ORD-CLOSE",
            "  ✅ [123456] 종가청산 실제 체결 확인: 2주 @ 1,010원 / 수익률 +1.00%",
        ]

        monitor = self.mod.parse_monitor_session(monitor_lines)
        sell = self.mod.parse_sell_session(sell_lines)

        self.assertEqual(monitor["orders"][0]["order_id"], "ORD-MKT")
        self.assertEqual(monitor["orders"][0]["filled_price"], 968)
        self.assertEqual(monitor["orders"][0]["entry_price"], 1000)
        self.assertEqual(sell["orders"][0]["trigger"], "종가청산")
        self.assertEqual(sell["orders"][0]["order_id"], "ORD-CLOSE")
        self.assertEqual(sell["orders"][0]["filled_price"], 1010)

    def test_order_execution_parses_official_detail_schema(self):
        detail = {
            "result": {
                "orderId": "ORD-1",
                "symbol": "123456",
                "side": "BUY",
                "status": "FILLED",
                "quantity": "10",
                "orderedAt": "2026-07-01T09:01:05+09:00",
                "execution": {
                    "filledQuantity": "10",
                    "averageFilledPrice": "9650",
                    "filledAmount": "96500",
                    "commission": "0",
                    "tax": "0",
                    "filledAt": "2026-07-01T09:01:06+09:00",
                    "settlementDate": "2026-07-03",
                },
            }
        }
        parsed = self.mod.order_execution(detail)
        self.assertEqual(parsed["status"], "FILLED")
        self.assertEqual(parsed["filled_quantity"], Decimal("10"))
        self.assertEqual(parsed["average_filled_price"], Decimal("9650"))
        self.assertEqual(parsed["filled_amount"], Decimal("96500"))
        lines = self.mod.execution_lines("매수", {"ok": True, "execution": parsed})
        self.assertIn("FILLED", lines[0])
        self.assertIn("9,650원", lines[0])

    def test_realized_pnl_uses_filled_amount_commission_and_tax(self):
        buy = {
            "ok": True,
            "execution": {
                "filled_amount": Decimal("96500"),
                "filled_quantity": Decimal("10"),
                "commission": Decimal("10"),
                "tax": Decimal("0"),
            },
        }
        sell = {
            "ok": True,
            "execution": {
                "filled_amount": Decimal("102000"),
                "filled_quantity": Decimal("10"),
                "commission": Decimal("10"),
                "tax": Decimal("200"),
            },
        }
        pnl, ret = self.mod.realized_pnl_from_details(buy, sell)
        self.assertEqual(pnl, Decimal("5280"))
        self.assertGreater(ret, Decimal("5"))

    def test_sell_report_includes_monitor_exit_when_close_sell_has_no_holdings(self):
        sell_lines = [
            "실행 시간: 2026-07-01 15:20:00",
            "모드: 실전 매매",
            "현재 보유 중인 종목이 없습니다. 당일 매도를 종료합니다.",
        ]
        buy = {
            "order": {"name": "테스트", "qty": 1, "expected_price": 1000, "amount": 1000},
            "order_id": "ORD-BUY",
            "reason": "조건 충족",
        }
        monitor = {
            "orders": [
                {
                    "name": "테스트",
                    "qty": 1,
                    "trigger": "손절",
                    "entry_price": 1000,
                    "last_price": 977,
                    "trigger_price": 978,
                    "expected_price": 976,
                    "expected_amount": 976,
                    "success": True,
                    "order_id": "ORD-MON",
                }
            ]
        }
        with patch.object(self.mod, "split_sessions", return_value=[sell_lines]):
            with patch.object(self.mod, "estimate_buy_from_log", return_value=buy):
                with patch.object(self.mod, "estimate_monitor_from_log", return_value=monitor):
                    with patch.object(self.mod, "fetch_order_details", return_value={}):
                        report = self.mod.sell_report("2026-07-01")

        self.assertIn("장중 손절/익절", report)
        self.assertIn("손절", report)
        self.assertIn("ORD-MON", report)
        self.assertIn("15:20 보유 없음", report)
        self.assertNotIn("미거래 또는 오전 체결 없음", report)

    def test_sell_report_keeps_order_from_earlier_reconcile_session(self):
        submitted = [
            "실행 시간: 2026-07-01 15:20:00",
            "모드: 실전 매매",
            "  🚨 [테스트] 1주 종가청산 시장가 매도 주문 발송...",
            "  * [실전 주문] 종가청산 시장가 매도 주문 접수! 주문ID: SELL-1",
        ]
        reconciled = [
            "실행 시간: 2026-07-01 15:31:00",
            "모드: 실전 매매",
            "전략 포지션이 이미 종료됐습니다. (CLOSED)",
        ]
        details = {
            "SELL-1": {
                "ok": True,
                "execution": {
                    "status": "FILLED",
                    "quantity": Decimal("1"),
                    "filled_quantity": Decimal("1"),
                    "average_filled_price": Decimal("990"),
                    "filled_amount": Decimal("990"),
                },
            }
        }

        with (
            patch.object(self.mod, "split_sessions", return_value=[submitted, reconciled]),
            patch.object(self.mod, "estimate_buy_from_log", return_value=None),
            patch.object(self.mod, "estimate_monitor_from_log", return_value=None),
            patch.object(self.mod, "fetch_order_details", return_value=details),
        ):
            report = self.mod.sell_report("2026-07-01")

        self.assertIn("SELL-1", report)
        self.assertIn("체결 완료", report)
        self.assertNotIn("매도 주문 로그 없음", report)

    def test_status_report_has_no_hardcoded_channel_id(self):
        text = Path(__file__).resolve().parents[1].joinpath("scripts", "toss_discord_report.py").read_text()
        self.assertNotIn("1521513150" + "682234900", text)
        self.assertNotIn("BOT_TOKEN", text)

    def test_candle_update_report_separates_known_unsupported_symbols(self):
        updater_stdout = """
Toss 일봉 캐시 업데이트 완료
{
  "ok_symbols": 1817,
  "known_unsupported_skipped_symbols": 5,
  "soft_skipped_symbols": 0,
  "newly_recorded_unsupported_symbols": [],
  "failed_symbols": 0,
  "total_fetched": 9085,
  "total_inserted_or_replaced": 9085,
  "latest_distribution_tail": {"2026-07-03": 1817},
  "stale_latest_symbols_count": 1,
  "stale_latest_symbols_tail": [{"symbol": "203690", "latest_date": "2026-07-02", "run_latest_date": "2026-07-03"}],
  "soft_errors_tail": [],
  "errors_tail": []
}
"""
        before = {"exists": True, "latest_date": "2026-07-02", "rows": 10, "latest_date_rows": 2, "latest_toss_rows": 2, "bad_timestamp_rows": 0}
        after = {"exists": True, "latest_date": "2026-07-03", "rows": 12, "latest_date_rows": 2, "latest_toss_rows": 2, "bad_timestamp_rows": 0}

        with patch.object(self.mod, "db_summary", side_effect=[before, after]):
            with patch.object(self.mod, "run_candle_update", return_value=(0, updater_stdout, "")):
                report = self.mod.candle_update_report(
                    expected_latest_date="2026-07-03"
                )

        self.assertIn("known_unsupported=5", report)
        self.assertIn("soft_skipped=0", report)
        self.assertIn("hard_failed=0", report)
        self.assertIn("최신 캔들 지연/상폐 의심: count=1", report)
        self.assertIn("203690", report)

    def test_candle_update_report_reconciles_official_breadth_after_full_update(self):
        current_date = "2026-07-17"
        before = {"exists": True, "latest_date": "2026-07-16", "rows": 10, "latest_date_rows": 2, "latest_toss_rows": 2, "bad_timestamp_rows": 0}
        after = {"exists": True, "latest_date": current_date, "rows": 12, "latest_date_rows": 2, "latest_toss_rows": 2, "bad_timestamp_rows": 0}
        reconciliation = {
            "official_gap5_count": 6,
            "threshold": 4,
            "shadow_pass": True,
        }

        with (
            patch.object(self.mod, "today", return_value=current_date),
            patch.object(self.mod, "db_summary", side_effect=[before, after]),
            patch.object(self.mod, "run_candle_update", return_value=(0, "{}", "")),
            patch.object(
                self.mod.breadth_shadow,
                "record_official_reconciliation",
                return_value=reconciliation,
            ) as record,
        ):
            report = self.mod.candle_update_report(
                expected_latest_date=current_date
            )

        record.assert_called_once_with(self.mod.DB_PATH, self.mod.BREADTH_SHADOW_LOG, current_date)
        self.assertIn("breadth4 사후확정: 공식 시가 -5% 갭 6개 / 기준 4개 / 통과", report)
        self.assertIn("실매매 미적용", report)

    def test_candle_update_report_marks_latest_session_lag(self):
        before = {"exists": True, "latest_date": "2026-07-16", "rows": 10, "latest_date_rows": 2, "latest_toss_rows": 2, "bad_timestamp_rows": 0}
        after = {"exists": True, "latest_date": "2026-07-16", "rows": 10, "latest_date_rows": 2, "latest_toss_rows": 2, "bad_timestamp_rows": 0}

        with (
            patch.object(self.mod, "db_summary", side_effect=[before, after]),
            patch.object(self.mod, "run_candle_update", return_value=(0, "{}", "")),
        ):
            report = self.mod.candle_update_report(
                expected_latest_date="2026-07-17"
            )

        self.assertIn("실행 결과: 지연", report)
        self.assertIn("KOSDAQ 기대 최신 거래일: 2026-07-17", report)
        self.assertIn("09:01 매수는 기준일 불일치로 자동 차단", report)

    def test_candle_update_report_does_not_claim_success_when_session_lookup_fails(self):
        summary = {"exists": True, "latest_date": "2026-07-16", "rows": 10, "latest_date_rows": 2, "latest_toss_rows": 2, "bad_timestamp_rows": 0}

        with (
            patch.object(self.mod, "db_summary", side_effect=[summary, summary]),
            patch.object(
                self.mod,
                "latest_kosdaq_session_date",
                side_effect=RuntimeError("index unavailable"),
            ),
            patch.object(self.mod, "run_candle_update", return_value=(0, "{}", "")),
        ):
            report = self.mod.candle_update_report()

        self.assertIn("실행 결과: 최신성 확인 실패", report)
        self.assertIn("KOSDAQ 기대 거래일 조회 실패", report)
        self.assertNotIn("실행 결과: 성공", report)

    def test_latest_kosdaq_session_date_accepts_compact_holiday_previous_date(self):
        with patch.object(
            self.mod,
            "fetch_kosdaq_close",
            return_value={"date": "20260716"},
        ):
            self.assertEqual(self.mod.latest_kosdaq_session_date(), "2026-07-16")

    def test_candle_update_report_skips_api_when_already_fresh(self):
        before = {"exists": True, "latest_date": "2026-07-17", "rows": 10, "latest_date_rows": 2, "latest_toss_rows": 2, "bad_timestamp_rows": 0}

        with (
            patch.object(self.mod, "db_summary", return_value=before),
            patch.object(
                self.mod,
                "run_candle_update",
                side_effect=AssertionError("fresh DB must not call updater"),
            ),
        ):
            report = self.mod.candle_update_report(
                only_if_stale=True,
                expected_latest_date="2026-07-17",
            )

        self.assertIn("이미 최신이라 API 업데이트 생략", report)


if __name__ == "__main__":
    unittest.main()
