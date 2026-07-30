import tempfile
import unittest
from pathlib import Path

from toss_auto_trader.news_client import NewsItem
from toss_auto_trader.news_prefetch import (
    append_prefetch_snapshot,
    build_prefetch_snapshot,
    load_latest_prefetch,
)


class NewsPrefetchTests(unittest.TestCase):
    def test_build_snapshot_keeps_safe_metadata_and_stock_code(self):
        item = NewsItem(
            provider="opendart",
            title="유상증자결정",
            url="https://example.com",
            source="FSS OpenDART",
            published_at="2026-07-30",
            summary="테스트전자",
            raw={"stock_code": "123456", "corp_name": "테스트전자", "secret": "drop"},
        )

        snapshot = build_prefetch_snapshot(
            [item],
            trade_date="2026-07-30",
            observed_at="2026-07-30T08:55:00+09:00",
            begin_date="2026-07-27",
            end_date="2026-07-30",
        )

        self.assertEqual(snapshot["items"][0]["stock_code"], "123456")
        self.assertNotIn("raw", snapshot["items"][0])
        self.assertNotIn("secret", snapshot["items"][0])
        self.assertTrue(snapshot["paper_only"])
        self.assertFalse(snapshot["order_sent"])

    def test_loader_uses_latest_complete_snapshot_before_decision(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "prefetch.jsonl"
            for observed_at in (
                "2026-07-30T08:50:00+09:00",
                "2026-07-30T08:55:00+09:00",
                "2026-07-30T09:02:00+09:00",
            ):
                snapshot = build_prefetch_snapshot(
                    [],
                    trade_date="2026-07-30",
                    observed_at=observed_at,
                    begin_date="2026-07-27",
                    end_date="2026-07-30",
                )
                self.assertTrue(append_prefetch_snapshot(path, snapshot))

            loaded = load_latest_prefetch(
                path,
                trade_date="2026-07-30",
                decision_at="2026-07-30T09:01:00+09:00",
            )

        self.assertIsNotNone(loaded)
        self.assertEqual(loaded["observed_at"], "2026-07-30T08:55:00+09:00")


if __name__ == "__main__":
    unittest.main()
