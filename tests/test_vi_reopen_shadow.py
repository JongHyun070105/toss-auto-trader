import json
import tempfile
import unittest
from pathlib import Path

from toss_auto_trader.vi_reopen_shadow import load_vi_events, simulate_vi_reopen_event


def candle(timestamp, open_price, high, low, close, volume):
    return {
        "timestamp": timestamp,
        "openPrice": str(open_price),
        "highPrice": str(high),
        "lowPrice": str(low),
        "closePrice": str(close),
        "volume": str(volume),
    }


class ViReopenShadowTests(unittest.TestCase):
    def test_load_vi_events_joins_candidate_price_and_warning_capture(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "audit.jsonl"
            path.write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "trade_date": "2026-07-30",
                                "symbol": "A",
                                "decision": "candidate",
                                "first_minute_open": 100,
                            }
                        ),
                        json.dumps(
                            {
                                "trade_date": "2026-07-30",
                                "symbol": "A",
                                "decision": "excluded_warning",
                                "candidate_rank": 1,
                                "captured_at": "2026-07-30T09:01:37+09:00",
                                "warnings": ["VI_DYNAMIC"],
                            }
                        ),
                        json.dumps(
                            {
                                "trade_date": "2026-07-30",
                                "symbol": "B",
                                "decision": "excluded_warning",
                                "warnings": ["INVESTMENT_WARNING"],
                            }
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            result = load_vi_events(path, "2026-07-30")

        self.assertEqual(len(result["events"]), 1)
        self.assertEqual(result["events"][0]["symbol"], "A")
        self.assertEqual(result["events"][0]["first_minute_open"], 100.0)
        self.assertEqual(result["events"][0]["candidate_rank"], 1)

    def test_reopen_starts_next_full_minute_and_rejects_zero_volume_candle(self):
        event = {
            "trade_date": "2026-07-30",
            "symbol": "A",
            "candidate_rank": 1,
            "warning_captured_at": "2026-07-30T09:01:37+09:00",
            "first_minute_open": 100,
        }
        candles = [
            candle("2026-07-30T09:01:00+09:00", 100, 100, 100, 100, 10),
            candle("2026-07-30T09:02:00+09:00", 100, 100, 100, 100, 0),
            candle("2026-07-30T09:03:00+09:00", 106, 108, 104, 107, 20),
            candle("2026-07-30T15:30:00+09:00", 107, 108, 106, 107, 5),
        ]

        result = simulate_vi_reopen_event(event, candles, roundtrip_cost_pct=0.0)

        self.assertEqual(result["status"], "simulated")
        self.assertEqual(result["observation_start"], "2026-07-30T09:02:00+09:00")
        self.assertEqual(result["reopen_timestamp"], "2026-07-30T09:03:00+09:00")
        self.assertEqual(result["reopen_price"], 106.0)
        self.assertFalse(result["opening_limit_fillable_before_cancel"])
        self.assertEqual(result["exit_reason"], "close")

    def test_stop_is_conservative_when_stop_and_take_share_minute(self):
        event = {
            "trade_date": "2026-07-30",
            "symbol": "A",
            "warning_captured_at": "2026-07-30T09:01:10+09:00",
            "first_minute_open": 100,
        }
        candles = [
            candle("2026-07-30T09:02:00+09:00", 100, 100, 100, 100, 1),
            candle("2026-07-30T09:03:00+09:00", 100, 113, 97, 110, 1),
        ]

        result = simulate_vi_reopen_event(event, candles, roundtrip_cost_pct=0.0)

        self.assertEqual(result["exit_reason"], "stop")
        self.assertAlmostEqual(result["exit_price"], 97.75)
        self.assertTrue(result["opening_limit_fillable_before_cancel"])
        self.assertTrue(result["paper_only"])
        self.assertFalse(result["order_sent"])
        self.assertFalse(result["live_order_allowed"])

    def test_warning_at_exact_minute_still_starts_on_following_minute(self):
        event = {
            "trade_date": "2026-07-30",
            "symbol": "A",
            "warning_captured_at": "2026-07-30T09:01:00+09:00",
            "first_minute_open": 100,
        }
        candles = [
            candle("2026-07-30T09:01:00+09:00", 100, 100, 100, 100, 1),
            candle("2026-07-30T09:02:00+09:00", 105, 106, 104, 105, 1),
        ]

        result = simulate_vi_reopen_event(event, candles, roundtrip_cost_pct=0.0)

        self.assertEqual(result["observation_start"], "2026-07-30T09:02:00+09:00")
        self.assertEqual(result["reopen_price"], 105.0)


if __name__ == "__main__":
    unittest.main()
