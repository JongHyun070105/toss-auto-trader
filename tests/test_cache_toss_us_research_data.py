import tempfile
import unittest
from pathlib import Path

import cache_toss_us_research_data as cache
from toss_auto_trader import db


class TossUsResearchCacheTests(unittest.TestCase):
    def test_merge_rankings_deduplicates_and_keeps_sources(self):
        payloads = [
            ("MARKET_TRADING_AMOUNT", "1y", {"result": {"rankings": [{"rank": 2, "symbol": "AAPL"}]}}),
            ("MARKET_TRADING_VOLUME", "1mo", {"result": {"rankings": [{"rank": 7, "symbol": "aapl"}, {"rank": 1, "symbol": "F"}]}}),
        ]

        merged = cache.merge_ranking_sources(payloads)

        self.assertEqual(set(merged), {"AAPL", "F"})
        self.assertEqual(merged["AAPL"]["best_rank"], 2)
        self.assertEqual(len(merged["AAPL"]["sources"]), 2)

    def test_eligible_common_stocks_excludes_etf_adr_and_inactive(self):
        ranking = {symbol: {"symbol": symbol, "sources": [], "best_rank": 1} for symbol in ["A", "B", "C", "D"]}
        rows = [
            {"symbol": "A", "status": "ACTIVE", "currency": "USD", "securityType": "STOCK", "isCommonShare": True, "market": "NYSE"},
            {"symbol": "B", "status": "ACTIVE", "currency": "USD", "securityType": "ETF", "isCommonShare": True, "market": "AMEX"},
            {"symbol": "C", "status": "ACTIVE", "currency": "USD", "securityType": "DEPOSITARY_RECEIPT", "isCommonShare": True, "market": "NASDAQ"},
            {"symbol": "D", "status": "DELISTED", "currency": "USD", "securityType": "STOCK", "isCommonShare": True, "market": "NYSE"},
        ]

        selected = cache.eligible_common_stocks(rows, ranking)

        self.assertEqual([row["symbol"] for row in selected], ["A"])

    def test_candle_quality_flags_invalid_ohlc(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "us.sqlite3")
            db.init_db(path)
            db.insert_candles(
                path,
                "AAPL",
                "1d",
                [
                    {"timestamp": "2026-01-02T09:30:00-05:00", "openPrice": "100", "highPrice": "105", "lowPrice": "99", "closePrice": "103", "volume": "1000", "currency": "USD"},
                    {"timestamp": "2026-01-05T09:30:00-05:00", "openPrice": "100", "highPrice": "98", "lowPrice": "99", "closePrice": "101", "volume": "1000", "currency": "USD"},
                ],
            )

            quality = cache.candle_quality(path, ["AAPL"])

        self.assertEqual(quality["rows"], 2)
        self.assertEqual(quality["bad_ohlc"], 1)
        self.assertEqual(quality["duplicate_dates"], 0)


if __name__ == "__main__":
    unittest.main()
