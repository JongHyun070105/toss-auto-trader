import sqlite3
import tempfile
import unittest
from pathlib import Path

from toss_auto_trader.research_fingerprint import candle_database_fingerprint


class ResearchFingerprintTests(unittest.TestCase):
    def test_candle_database_fingerprint_captures_content_and_latest_date(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "candles.sqlite3"
            connection = sqlite3.connect(db_path)
            try:
                connection.execute(
                    """
                    CREATE TABLE candle_cache (
                        symbol TEXT, interval TEXT, timestamp TEXT
                    )
                    """
                )
                connection.executemany(
                    "INSERT INTO candle_cache VALUES (?,?,?)",
                    [
                        ("A", "1d", "2026-01-02T00:00:00+09:00"),
                        ("B", "1d", "2026-01-05T00:00:00+09:00"),
                        ("A", "1m", "2026-01-05T09:01:00+09:00"),
                    ],
                )
                connection.commit()
            finally:
                connection.close()

            result = candle_database_fingerprint(db_path)

        self.assertEqual(result["daily_rows"], 2)
        self.assertEqual(result["daily_symbols"], 2)
        self.assertEqual(result["first_date"], "2026-01-02")
        self.assertEqual(result["latest_date"], "2026-01-05")
        self.assertEqual(len(result["full_sha256"]), 64)
        self.assertGreater(result["size_bytes"], 0)
