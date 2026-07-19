import sqlite3
import tempfile
import unittest
from pathlib import Path

import build_delisted_merged_research_db as builder
import naver_delisted_candle_research as naver


def create_base(path: Path) -> None:
    connection = sqlite3.connect(path)
    naver.initialize_database(connection)
    connection.execute(
        "INSERT INTO candle_cache VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        ("LIVE", "1d", "2026-01-02", "1", "1", "1", "1", "1", "KRW", "{}", "now"),
    )
    connection.execute(
        "INSERT INTO candle_cache VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (
            "OLD",
            "1d",
            "2020-01-01T00:00:00+09:00",
            "10",
            "10",
            "10",
            "10",
            "10",
            "KRW",
            "{}",
            "now",
        ),
    )
    connection.commit()
    connection.close()


def create_supplement(path: Path) -> None:
    connection = sqlite3.connect(path)
    naver.initialize_database(connection)
    connection.executemany(
        "INSERT INTO candle_cache VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        [
            ("OLD", "1d", "2020-01-01", "1", "1", "1", "1", "1", "KRW", "{}", "now"),
            ("OLD", "1d", "2020-02-20", "1", "1", "1", "1", "1", "KRW", "{}", "now"),
            ("OLD", "1d", "2019-12-31", "1", "1", "1", "1", "0", "KRW", "{}", "now"),
        ],
    )
    connection.execute(
        "INSERT INTO delisted_source_metadata VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            "OLD",
            "OLD",
            "Old Corp",
            "distress_or_enforcement",
            "2010-01-01",
            "2020-03-01",
            "test",
            "ok",
            2,
            0,
            0,
            "now",
        ),
    )
    connection.commit()
    connection.close()


class BuildDelistedMergedResearchDbTests(unittest.TestCase):
    def test_builds_isolated_db_and_applies_pre_delisting_buffer(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "base.sqlite3"
            supplement = Path(tmp) / "supplement.sqlite3"
            output = Path(tmp) / "merged.sqlite3"
            create_base(base)
            create_supplement(supplement)

            result = builder.build_merged_database(
                str(base),
                str(supplement),
                str(output),
                exclude_calendar_days_before_delisting=30,
            )
            connection = sqlite3.connect(output)
            rows = connection.execute(
                "SELECT symbol,timestamp FROM candle_cache ORDER BY symbol,timestamp"
            ).fetchall()
            connection.close()

        self.assertEqual(
            rows,
            [
                ("LIVE", "2026-01-02"),
                ("OLD", "2020-01-01T00:00:00+09:00"),
            ],
        )
        self.assertEqual(result["inserted_rows"], 0)
        self.assertEqual(result["same_date_supplement_rows_skipped"], 1)
        self.assertEqual(result["zero_volume_suspension_rows_excluded"], 1)
        self.assertEqual(result["duplicate_symbol_dates"], 0)
        self.assertTrue(result["integrity_passed"])
        self.assertEqual(result["old_only_symbols"], 1)
        self.assertFalse(result["live_database_modified"])

    def test_refuses_to_overwrite_a_source_database(self):
        with self.assertRaises(ValueError):
            builder.build_merged_database("a.sqlite3", "b.sqlite3", "a.sqlite3")


if __name__ == "__main__":
    unittest.main()
