import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from toss_auto_trader import paper_reentry_watch


class PaperReentryWatchTests(unittest.TestCase):
    def test_threshold_events_record_additional_drops_after_stop_exit(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "reentry.jsonl"
            paper_reentry_watch.record_stop_exit(
                log_path,
                symbol="321370",
                name="센서뷰",
                qty=5,
                entry_price=1782.0,
                stop_price=1741.9,
                observed_price=1730.0,
                exit_limit_price=1726.0,
                order_id="ORD-1",
                now=datetime(2026, 7, 7, 9, 14),
            )

            added = paper_reentry_watch.update_watch(
                log_path,
                {"321370": 1625.0},
                datetime(2026, 7, 7, 9, 20),
            )

            thresholds = [event for event in added if event["event"] == "paper_reentry_threshold"]
            self.assertEqual([event["threshold_id"] for event in thresholds], ["3pct", "5pct"])
            self.assertTrue(all(event["paper_only"] for event in added))
            self.assertTrue(all(event["live_order_allowed"] is False for event in added))

    def test_outcomes_record_once_for_each_horizon(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "reentry.jsonl"
            paper_reentry_watch.record_stop_exit(
                log_path,
                symbol="321370",
                name="센서뷰",
                qty=5,
                entry_price=1782.0,
                stop_price=1741.9,
                observed_price=1730.0,
                exit_limit_price=1726.0,
                order_id=None,
                now=datetime(2026, 7, 7, 9, 14),
            )
            paper_reentry_watch.update_watch(log_path, {"321370": 1670.0}, datetime(2026, 7, 7, 9, 15))

            first = paper_reentry_watch.update_watch(log_path, {"321370": 1685.0}, datetime(2026, 7, 7, 9, 25))
            second = paper_reentry_watch.update_watch(log_path, {"321370": 1685.0}, datetime(2026, 7, 7, 9, 25))
            close = paper_reentry_watch.update_watch(log_path, {"321370": 1700.0}, datetime(2026, 7, 7, 15, 20))

            first_outcomes = [event for event in first if event["event"] == "paper_reentry_outcome"]
            close_outcomes = [event for event in close if event["event"] == "paper_reentry_outcome"]
            self.assertEqual([event["horizon"] for event in first_outcomes], ["10m"])
            self.assertEqual(second, [])
            self.assertEqual([event["horizon"] for event in close_outcomes], ["30m", "close"])

    def test_take_profit_exit_records_missed_upside_and_snapshots(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "reentry.jsonl"
            paper_reentry_watch.record_take_profit_exit(
                log_path,
                symbol="321370",
                name="센서뷰",
                qty=5,
                entry_price=1000.0,
                take_price=1120.0,
                observed_price=1125.0,
                exit_limit_price=1124.0,
                order_id="ORD-TP",
                now=datetime(2026, 7, 7, 9, 30),
            )

            first = paper_reentry_watch.update_watch(log_path, {"321370": 1160.0}, datetime(2026, 7, 7, 9, 35))
            second = paper_reentry_watch.update_watch(log_path, {"321370": 1180.0}, datetime(2026, 7, 7, 9, 45))

            first_events = [event["event"] for event in first]
            second_events = [event["event"] for event in second]
            self.assertIn("paper_exit_price_snapshot", first_events)
            self.assertIn("paper_missed_upside_threshold", first_events)
            self.assertIn("paper_missed_upside_outcome", second_events)
            missed = [event for event in first if event["event"] == "paper_missed_upside_threshold"][0]
            self.assertEqual(missed["exit_reason"], "take_profit")
            self.assertEqual(missed["threshold_id"], "3pct")


if __name__ == "__main__":
    unittest.main()
