import importlib.util
import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch


def load_daily_result_markdown():
    root = Path(__file__).resolve().parents[1]
    scripts = root / "scripts"
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    spec = importlib.util.spec_from_file_location("daily_result_markdown", scripts / "daily_result_markdown.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


class DailyResultMarkdownTests(unittest.TestCase):
    def test_rendered_row_keeps_public_trade_summary_without_order_ids(self):
        mod = load_daily_result_markdown()
        buy = {
            "order": {"name": "센서뷰", "qty": 5, "expected_price": 1782},
            "order_id": "ORD-BUY",
            "reason": "조건 충족",
        }
        monitor = {
            "orders": [
                {
                    "name": "센서뷰",
                    "qty": 5,
                    "trigger": "손절",
                    "expected_price": 1726,
                    "success": True,
                    "order_id": "ORD-STOP",
                }
            ]
        }

        result = mod.daily_result_from_parsed("2026-07-07", buy, monitor, None)
        row = mod.render_row(result)

        self.assertIn("센서뷰 @ 1,782원", row)
        self.assertIn("손절 @ 1,726원", row)
        self.assertIn("-3.14%", row)
        self.assertNotIn("ORD-BUY", row)
        self.assertNotIn("ORD-STOP", row)
        self.assertNotIn("5주", row)

    def test_load_daily_result_prefers_toss_actual_return_when_available(self):
        mod = load_daily_result_markdown()
        buy = {
            "order": {"name": "센서뷰", "qty": 5, "expected_price": 1782},
            "order_id": "ORD-BUY",
            "reason": "조건 충족",
        }
        monitor = {
            "orders": [
                {
                    "name": "센서뷰",
                    "qty": 5,
                    "trigger": "손절",
                    "expected_price": 1726,
                    "success": True,
                    "order_id": "ORD-STOP",
                }
            ]
        }

        with (
            patch.object(mod.report, "estimate_buy_from_log", return_value=buy),
            patch.object(mod.report, "estimate_monitor_from_log", return_value=monitor),
            patch.object(mod.report, "latest_session_for_date", return_value=[]),
            patch.object(mod.report, "fetch_order_details", return_value={"ORD-BUY": {}, "ORD-STOP": {}}) as fetch,
            patch.object(
                mod.report,
                "realized_pnl_from_details",
                return_value=(Decimal("-241"), Decimal("-2.70")),
            ),
        ):
            result = mod.load_daily_result("2026-07-07")

        row = mod.render_row(result)
        fetch.assert_called_once_with(["ORD-BUY", "ORD-STOP"])
        self.assertIn("-2.70%", row)
        self.assertIn("실제 체결 기준", row)
        self.assertNotIn("ORD-BUY", row)
        self.assertNotIn("ORD-STOP", row)

    def test_upsert_replaces_same_date_without_duplicate_rows(self):
        mod = load_daily_result_markdown()
        first = mod.DailyResult("2026-07-07", "센서뷰 @ 1,782원", "손절 @ 1,726원", -3.14, "장중 monitor 청산")
        second = mod.DailyResult("2026-07-07", "센서뷰 @ 1,782원", "15:20 정리 @ 1,800원", 1.01, "15:20 잔여 보유분 정리")

        markdown = mod.upsert_result("", first)
        markdown = mod.upsert_result(markdown, second)

        self.assertEqual(markdown.count("| 2026-07-07 |"), 1)
        self.assertIn("15:20 정리 @ 1,800원", markdown)
        self.assertNotIn("손절 @ 1,726원", markdown)

    def test_successful_close_sell_wins_over_failed_monitor_order(self):
        mod = load_daily_result_markdown()
        buy = {"order": {"name": "테스트", "expected_price": 1000}, "reason": "조건 충족"}
        monitor = {"orders": [{"name": "테스트", "trigger": "손절", "expected_price": 970, "success": False}]}
        sell = {"orders": [{"name": "테스트", "expected_price": 1020, "success": True}]}

        result = mod.daily_result_from_parsed("2026-07-08", buy, monitor, sell)

        self.assertEqual(result.exit, "15:20 정리 @ 1,020원")
        self.assertEqual(result.return_pct, 2.0)

    def test_cli_writes_results_file_from_log_parsers(self):
        mod = load_daily_result_markdown()
        with tempfile.TemporaryDirectory() as td:
            output = Path(td) / "RESULTS.md"
            buy = {"order": {"name": "테스트", "expected_price": 1000}, "reason": "조건 충족"}
            sell = {"orders": [{"name": "테스트", "expected_price": 1030, "success": True}]}

            result = mod.daily_result_from_parsed("2026-07-08", buy, None, sell)
            mod.write_result(output, result)

            text = output.read_text(encoding="utf-8")
            self.assertIn("| 2026-07-08 | 테스트 @ 1,000원 | 15:20 정리 @ 1,030원 | +3.00% |", text)


if __name__ == "__main__":
    unittest.main()
