import importlib.util
import unittest
from pathlib import Path


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
            "갭 하락 3% 돌파 종목 수: 2개",
            "  [123456] 테스트 | 갭률: -3.20% | 시가: 9,600원 | 현재가: 9,650원 | 전일종가: 10,000원",
            "  🚀 [테스트] 10주 매수 주문 발송 (배정금액 96,500원, 예상단가 9,650원)...",
            "  * [실전 주문] 주문 성공! 주문ID: ORD-1",
        ]
        parsed = self.mod.parse_buy_session(lines)
        self.assertEqual(parsed["guard"], "통과")
        self.assertEqual(parsed["order"]["name"], "테스트")
        self.assertEqual(parsed["order"]["qty"], 10)
        self.assertTrue(parsed["order_success"])
        self.assertIn("갭하락", parsed["reason"])

    def test_parse_sell_session_reads_expected_price(self):
        lines = [
            "실행 시간: 2026-07-01 15:20:00",
            "모드: 실전 매매",
            "현재 보유 종목 수: 1개. 전량 시장가 종가 매도를 실행합니다.",
            "  🚀 [테스트] 10주 매도 주문 발송 (예상단가 10,200원, 예상금액 102,000원)...",
            "  * [실전 주문] 매도 주문 성공! 주문ID: ORD-2",
        ]
        parsed = self.mod.parse_sell_session(lines)
        self.assertEqual(parsed["orders"][0]["expected_price"], 10200)
        self.assertEqual(parsed["orders"][0]["expected_amount"], 102000)
        self.assertTrue(parsed["orders"][0]["success"])

    def test_status_report_has_no_hardcoded_channel_id(self):
        text = Path(__file__).resolve().parents[1].joinpath("scripts", "toss_discord_report.py").read_text()
        self.assertNotIn("1521513150" + "682234900", text)
        self.assertNotIn("BOT_TOKEN", text)


if __name__ == "__main__":
    unittest.main()
