import sqlite3
import tempfile
import unittest
from pathlib import Path

import krx_kind_delisted_universe_audit as audit


LIST_HTML = """
<table><tbody><tr>
<td>1</td>
<td><img alt="코스닥"><a onclick="companysummary_open('05620');" title="엠넷미디어">엠넷미디어</a></td>
<td>2011-03-22</td><td>피흡수합병</td><td></td>
</tr></tbody></table>
<div class="info type-00">전체 <em>539</em>건 : <strong>1</strong>/1</div>
"""

SUMMARY_HTML = """
<table><tr><th>표준코드</th><td>KR7056200009</td>
<th>종목코드</th><td>056200</td></tr>
<tr><th>시장구분</th><td>코스닥 상장폐지</td>
<th>상장일</th><td>2002-01-29</td></tr></table>
"""


class KrxKindDelistedUniverseAuditTests(unittest.TestCase):
    def test_parses_official_list_and_total(self):
        rows, total = audit.parse_delisted_list(LIST_HTML)

        self.assertEqual(total, 539)
        self.assertEqual(rows[0]["issuer_code"], "05620")
        self.assertEqual(rows[0]["company_name"], "엠넷미디어")
        self.assertEqual(rows[0]["market"], "코스닥")
        self.assertEqual(rows[0]["delisting_date"], "2011-03-22")

    def test_parses_verified_six_digit_ticker(self):
        result = audit.parse_company_summary(SUMMARY_HTML)

        self.assertEqual(result["ticker"], "056200")
        self.assertEqual(result["isin"], "KR7056200009")
        self.assertEqual(result["listed_date"], "2002-01-29")

    def test_build_audit_detects_missing_and_reused_tickers(self):
        rows = [
            {
                "issuer_code": "05620",
                "company_name": "엠넷미디어",
                "market": "코스닥",
                "delisting_date": "2011-03-22",
                "reason": "피흡수합병",
                "note": "",
                "ticker": "056200",
            },
            {
                "issuer_code": "08802",
                "company_name": "네이쳐글로벌",
                "market": "코스닥",
                "delisting_date": "2011-01-08",
                "reason": "상장폐지기준에 해당한다고 결정",
                "note": "",
                "ticker": "088020",
            },
        ]
        db_symbols = {
            "056200": {"first_date": "2020-01-02", "last_date": "2026-07-16"}
        }

        result = audit.build_audit(
            rows,
            db_symbols,
            registry_total=2,
            from_date="2011-01-01",
            to_date="2026-07-19",
        )

        self.assertEqual(result["absent_from_current_cache"], 1)
        self.assertEqual(result["ticker_reuse_suspected"], 1)
        self.assertEqual(result["distress_absent_from_current_cache"], 1)
        self.assertFalse(result["survivorship_bias_resolved"])

    def test_database_symbols_reads_daily_bounds(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "candles.sqlite3"
            connection = sqlite3.connect(path)
            connection.execute(
                "CREATE TABLE candle_cache (symbol TEXT, timestamp TEXT, interval TEXT)"
            )
            connection.executemany(
                "INSERT INTO candle_cache VALUES (?,?,?)",
                [
                    ("A", "2020-01-02", "1d"),
                    ("A", "2026-07-16", "1d"),
                    ("A", "2026-07-16T09:01:00", "1m"),
                ],
            )
            connection.commit()
            connection.close()

            result = audit.database_symbols(str(path))

        self.assertEqual(
            result["A"],
            {"first_date": "2020-01-02", "last_date": "2026-07-16"},
        )


if __name__ == "__main__":
    unittest.main()
