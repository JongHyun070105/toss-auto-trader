import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from toss_auto_trader import entry_price_audit


class EntryPriceAuditTests(unittest.TestCase):
    def test_reconcile_entry_prices_reports_ok_only_with_positive_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "candles.sqlite3"
            audit_path = root / "entry-price.jsonl"
            connection = sqlite3.connect(db_path)
            connection.execute(
                "CREATE TABLE candle_cache (symbol TEXT, interval TEXT, timestamp TEXT, "
                "open_price REAL, close_price REAL)"
            )
            connection.execute(
                "INSERT INTO candle_cache VALUES (?,?,?,?,?)",
                ("MATCH", "1d", "2026-07-28T00:00:00+09:00", 1980, 1852),
            )
            connection.commit()
            connection.close()
            audit_path.write_text(
                json.dumps(
                    {
                        "trade_date": "2026-07-28",
                        "symbol": "MATCH",
                        "first_minute_open": 1980,
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            result = entry_price_audit.reconcile_entry_prices(
                db_path, audit_path, "2026-07-28"
            )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["reference_symbols"], 1)
        self.assertEqual(result["matched_symbols"], 1)

    def test_reconcile_entry_prices_reports_match_and_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "candles.sqlite3"
            audit_path = root / "entry-price.jsonl"
            connection = sqlite3.connect(db_path)
            connection.execute(
                "CREATE TABLE candle_cache (symbol TEXT, interval TEXT, timestamp TEXT, "
                "open_price REAL, close_price REAL)"
            )
            connection.executemany(
                "INSERT INTO candle_cache VALUES (?,?,?,?,?)",
                [
                    ("MATCH", "1d", "2026-07-28T00:00:00+09:00", 1980, 1852),
                    ("DIFF", "1d", "2026-07-28T00:00:00+09:00", 1000, 950),
                ],
            )
            connection.commit()
            connection.close()
            audit_path.write_text(
                "\n".join(
                    [
                        json.dumps({"trade_date": "2026-07-28", "symbol": "MATCH", "first_minute_open": 1980}),
                        json.dumps({"trade_date": "2026-07-28", "symbol": "DIFF", "first_minute_open": 990}),
                        json.dumps({"trade_date": "2026-07-27", "symbol": "OLD", "first_minute_open": 100}),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            result = entry_price_audit.reconcile_entry_prices(db_path, audit_path, "2026-07-28")

        self.assertEqual(result["reference_symbols"], 2)
        self.assertEqual(result["status"], "mismatch")
        self.assertEqual(result["matched_symbols"], 1)
        self.assertEqual(result["mismatch_symbols"], ["DIFF"])
        self.assertEqual(result["missing_symbols"], [])
        self.assertAlmostEqual(result["max_diff_pct"], 1.0)

    def test_reconcile_entry_prices_reports_missing_official_candle(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "candles.sqlite3"
            audit_path = root / "entry-price.jsonl"
            connection = sqlite3.connect(db_path)
            connection.execute(
                "CREATE TABLE candle_cache (symbol TEXT, interval TEXT, timestamp TEXT, "
                "open_price REAL, close_price REAL)"
            )
            connection.commit()
            connection.close()
            audit_path.write_text(
                json.dumps({"trade_date": "2026-07-28", "symbol": "MISSING", "first_minute_open": 1000}) + "\n",
                encoding="utf-8",
            )

            result = entry_price_audit.reconcile_entry_prices(db_path, audit_path, "2026-07-28")

        self.assertEqual(result["matched_symbols"], 0)
        self.assertEqual(result["status"], "missing_official")
        self.assertEqual(result["missing_symbols"], ["MISSING"])

    def test_reconcile_entry_prices_distinguishes_missing_corrupt_and_empty_audit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "missing-db.sqlite3"
            audit_path = root / "entry-price.jsonl"

            missing = entry_price_audit.reconcile_entry_prices(
                db_path, audit_path, "2026-07-28"
            )

            audit_path.write_text("not-json\n", encoding="utf-8")
            corrupt = entry_price_audit.reconcile_entry_prices(
                db_path, audit_path, "2026-07-28"
            )

            audit_path.write_text(
                json.dumps(
                    {
                        "trade_date": "2026-07-27",
                        "symbol": "OLD",
                        "first_minute_open": 1000,
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            no_reference = entry_price_audit.reconcile_entry_prices(
                db_path, audit_path, "2026-07-28"
            )

        self.assertEqual(missing["status"], "missing_audit_file")
        self.assertFalse(missing["audit_file_exists"])
        self.assertEqual(corrupt["status"], "audit_parse_error")
        self.assertEqual(corrupt["audit_parse_errors"], 1)
        self.assertEqual(no_reference["status"], "no_reference")
        self.assertEqual(no_reference["audit_parse_errors"], 0)
