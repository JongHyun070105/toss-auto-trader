import json
import sqlite3
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from toss_auto_trader import breadth_shadow


class BreadthShadowTests(unittest.TestCase):
    def test_provisional_count_uses_current_price_without_affecting_orders(self):
        count, quoted = breadth_shadow.provisional_gap_count(
            {"A": 1000.0, "B": 2000.0, "C": 3000.0},
            [
                {"symbol": "A", "lastPrice": "940"},
                {"symbol": "A", "lastPrice": "930"},
                {"symbol": "B", "lastPrice": "1,920"},
                {"symbol": "C", "lastPrice": "0"},
            ],
        )
        self.assertEqual(count, 1)
        self.assertEqual(quoted, 2)

    def test_official_open_breadth_matches_research_definition(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "candles.sqlite3"
            connection = sqlite3.connect(db_path)
            connection.execute(
                "CREATE TABLE candle_cache (symbol TEXT, timestamp TEXT, interval TEXT, "
                "open_price REAL, high_price REAL, low_price REAL, close_price REAL, volume REAL)"
            )
            start = date(2026, 1, 1)
            rows = []
            for offset in range(23):
                day = (start + timedelta(days=offset)).isoformat()
                for symbol in ("GAP", "FLAT"):
                    open_price = 900.0 if symbol == "GAP" and offset == 22 else 1000.0
                    rows.append((symbol, day, "1d", open_price, 1010.0, 890.0, 1000.0, 100.0))
            connection.executemany("INSERT INTO candle_cache VALUES (?,?,?,?,?,?,?,?)", rows)
            connection.commit()
            connection.close()

            result = breadth_shadow.official_open_breadth(
                db_path, (start + timedelta(days=22)).isoformat()
            )

        self.assertEqual(result["eligible_symbols"], 2)
        self.assertEqual(result["official_gap5_count"], 1)
        self.assertFalse(result["shadow_pass"])

    def test_reconciliation_is_deduplicated_by_date(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "candles.sqlite3"
            log_path = Path(tmp) / "shadow.jsonl"
            connection = sqlite3.connect(db_path)
            connection.execute(
                "CREATE TABLE candle_cache (symbol TEXT, timestamp TEXT, interval TEXT, "
                "open_price REAL, high_price REAL, low_price REAL, close_price REAL, volume REAL)"
            )
            start = date(2026, 1, 1)
            connection.executemany(
                "INSERT INTO candle_cache VALUES (?,?,?,?,?,?,?,?)",
                [
                    (
                        "A",
                        (start + timedelta(days=offset)).isoformat(),
                        "1d",
                        1000.0,
                        1010.0,
                        990.0,
                        1000.0,
                        100.0,
                    )
                    for offset in range(23)
                ],
            )
            connection.commit()
            connection.close()
            target_date = (start + timedelta(days=22)).isoformat()

            breadth_shadow.record_official_reconciliation(db_path, log_path, target_date)
            breadth_shadow.record_official_reconciliation(db_path, log_path, target_date)
            lines = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]

        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0]["date"], target_date)


if __name__ == "__main__":
    unittest.main()
