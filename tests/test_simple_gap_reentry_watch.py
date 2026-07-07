import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from tests.test_simple_gap_trader import FakeMonitorClient, FakeSettings, load_simple_gap_trader


class SimpleGapReentryWatchTests(unittest.TestCase):
    def test_monitor_records_paper_watch_after_live_stop_loss_sell(self):
        mod = load_simple_gap_trader()
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "reentry.jsonl"
            client = FakeMonitorClient(
                holdings=[{"symbol": "123456", "name": "테스트", "quantity": "1", "averagePrice": "1000"}],
                prices={"123456": "977"},
                bid_price="976",
                dry_run=False,
            )

            with (
                patch.object(mod, "PAPER_REENTRY_LOG", log_path),
                patch.object(mod, "send_discord_message", return_value=False),
            ):
                mod.run_monitor(client, FakeSettings())

            events = mod.paper_reentry_watch.read_events(log_path)
            self.assertEqual(events[0]["event"], "stop_exit")
            self.assertEqual(events[0]["symbol"], "123456")
            self.assertEqual(events[0]["exit_limit_price"], 976)
            self.assertTrue(events[0]["paper_only"])
            self.assertIs(events[0]["live_order_allowed"], False)

    def test_monitor_records_paper_watch_after_live_take_profit_sell(self):
        mod = load_simple_gap_trader()
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "reentry.jsonl"
            client = FakeMonitorClient(
                holdings=[{"symbol": "123456", "name": "테스트", "quantity": "1", "averagePrice": "1000"}],
                prices={"123456": "1120"},
                bid_price="1118",
                dry_run=False,
            )

            with (
                patch.object(mod, "PAPER_REENTRY_LOG", log_path),
                patch.object(mod, "send_discord_message", return_value=False),
            ):
                mod.run_monitor(client, FakeSettings())

            events = mod.paper_reentry_watch.read_events(log_path)
            self.assertEqual(events[0]["event"], "take_profit_exit")
            self.assertEqual(events[0]["exit_reason"], "take_profit")
            self.assertEqual(events[0]["symbol"], "123456")
            self.assertEqual(events[0]["exit_limit_price"], 1118)

    def test_paper_watch_update_uses_prices_without_creating_orders(self):
        mod = load_simple_gap_trader()
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "reentry.jsonl"
            mod.paper_reentry_watch.record_stop_exit(
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
            client = FakeMonitorClient(holdings=[], prices={"321370": "1670"})

            with patch.object(mod, "PAPER_REENTRY_LOG", log_path):
                mod.update_paper_reentry_watch(client, now=datetime(2026, 7, 7, 9, 16))

            events = mod.paper_reentry_watch.read_events(log_path)
            thresholds = [event for event in events if event["event"] == "paper_reentry_threshold"]
            self.assertEqual(client.created_orders, [])
            self.assertEqual(thresholds[0]["threshold_id"], "3pct")

    def test_sell_updates_paper_watch_before_returning_without_holdings(self):
        mod = load_simple_gap_trader()
        client = FakeMonitorClient(holdings=[], prices={})
        calls = []

        def fake_update_paper_reentry_watch(seen_client):
            calls.append(seen_client)

        with patch.object(mod, "update_paper_reentry_watch", side_effect=fake_update_paper_reentry_watch):
            mod.run_sell(client, FakeSettings())

        self.assertEqual(calls, [client])
        self.assertEqual(client.created_orders, [])


if __name__ == "__main__":
    unittest.main()
