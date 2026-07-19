import sqlite3
import tempfile
import unittest
from pathlib import Path

import naver_delisted_candle_research as naver


XML = b'''<?xml version="1.0" encoding="EUC-KR" ?>
<protocol><chartdata symbol="056200" name="test" count="2" timeframe="day" origintime="20020129">
<item data="20110321|1000|1100|900|950|12345" />
<item data="20110322|0|0|0|950|0" />
</chartdata></protocol>'''


class NaverDelistedCandleResearchTests(unittest.TestCase):
    def test_parses_structured_chart_xml(self):
        metadata, rows = naver.parse_chart_xml(XML)

        self.assertEqual(metadata["symbol"], "056200")
        self.assertEqual(rows[0]["date"], "2011-03-21")
        self.assertEqual(rows[0]["open"], 1000.0)
        self.assertEqual(rows[1]["volume"], 0.0)

    def test_normalizes_only_zero_volume_suspension_ohlc(self):
        normalized, changed = naver.normalize_row(
            {
                "date": "2011-03-22",
                "open": 0.0,
                "high": 0.0,
                "low": 0.0,
                "close": 950.0,
                "volume": 0.0,
            }
        )
        invalid, _ = naver.normalize_row(
            {
                "date": "2011-03-22",
                "open": 0.0,
                "high": 1000.0,
                "low": 900.0,
                "close": 950.0,
                "volume": 10.0,
            }
        )

        self.assertTrue(changed)
        self.assertEqual(normalized["open"], 950.0)
        self.assertIsNone(invalid)

    def test_store_symbol_clips_after_official_delisting_date(self):
        metadata, rows = naver.parse_chart_xml(XML)
        rows.append(
            {
                "date": "2011-03-23",
                "open": 900.0,
                "high": 900.0,
                "low": 900.0,
                "close": 900.0,
                "volume": 1.0,
            }
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "supplement.sqlite3"
            connection = sqlite3.connect(path)
            naver.initialize_database(connection)
            result = naver.store_symbol(
                connection,
                {
                    "ticker": "056200",
                    "issuer_code": "05620",
                    "company_name": "test",
                    "category": "corporate_action",
                    "listed_date": "2002-01-29",
                    "delisting_date": "2011-03-22",
                },
                metadata,
                rows,
                start="2011-01-01",
                fetched_at="2026-07-19T00:00:00+09:00",
            )
            connection.commit()
            stored = connection.execute(
                "SELECT timestamp,open_price,volume FROM candle_cache ORDER BY timestamp"
            ).fetchall()
            connection.close()

        self.assertEqual(result["rows"], 2)
        self.assertEqual(result["normalized"], 1)
        self.assertEqual(stored[-1], ("2011-03-22", "950", "0"))


if __name__ == "__main__":
    unittest.main()
