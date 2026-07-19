import unittest

import krx_kind_historical_warning_audit as audit


LIST_HTML = """
<section><table><tbody>
<tr><td>2</td><td title="테스트A"><img alt="코스닥">
<a onclick="companysummary_open('12345'); return false;" title="테스트A">테스트A</a>
</td><td>2024-12-23</td><td>2024-12-24</td><td>2025-01-10</td></tr>
<tr><td>1</td><td title="테스트B"><img alt="코스닥">
<a onclick="companysummary_open('54321'); return false;" title="테스트B">테스트B</a>
</td><td>2024-12-19</td><td>2024-12-20</td><td></td></tr>
</tbody></table></section>
<div class="info type-00">전체 <em>2</em>건 : <strong>1</strong>/1</div>
"""


class KrxKindHistoricalWarningAuditTests(unittest.TestCase):
    def test_parses_warning_rows_and_total(self):
        rows, total = audit.parse_warning_list(LIST_HTML)

        self.assertEqual(total, 2)
        self.assertEqual(rows[0]["issuer_code"], "12345")
        self.assertEqual(rows[0]["company_name"], "테스트A")
        self.assertEqual(rows[0]["detail_column"], "2024-12-23")
        self.assertEqual(rows[0]["designation_date"], "2024-12-24")
        self.assertEqual(rows[0]["release_date"], "2025-01-10")
        self.assertEqual(rows[1]["release_date"], "")

    def test_attention_detail_is_a_reason_not_an_announcement_date(self):
        row = {
            "issuer_code": "12345",
            "company_name": "테스트A",
            "market": "코스닥",
            "detail_column": "단일계좌거래량",
            "designation_date": "2024-12-24",
            "release_date": "2024-12-25",
        }

        result = audit.annotate_category(row, "attention")

        self.assertEqual(result["designation_reason"], "단일계좌거래량")
        self.assertEqual(result["announcement_date"], "")

    def test_three_year_chunks_do_not_overlap(self):
        self.assertEqual(
            audit.three_year_chunks("2011-01-01", "2017-02-01"),
            [
                ("2011-01-01", "2013-12-31"),
                ("2014-01-01", "2016-12-31"),
                ("2017-01-01", "2017-02-01"),
            ],
        )

    def test_three_year_chunks_handle_leap_day(self):
        self.assertEqual(
            audit.three_year_chunks("2020-02-29", "2023-03-01"),
            [("2020-02-29", "2023-02-27"), ("2023-02-28", "2023-03-01")],
        )

    def test_collect_rows_paginates_and_deduplicates(self):
        class FakeClient:
            def warning_page(self, **kwargs):
                row = {
                    "issuer_code": "12345",
                    "company_name": "테스트A",
                    "market": "코스닥",
                    "announcement_date": "2024-12-23",
                    "designation_reason": "",
                    "designation_date": "2024-12-24",
                    "release_date": "2025-01-10",
                    "category": kwargs["category"],
                    "category_label": "투자경고",
                }
                return [row], 1

        rows, diagnostics = audit.collect_rows(
            FakeClient(),
            start_date="2024-01-01",
            end_date="2024-12-31",
            categories=["warning"],
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(diagnostics[0]["reported_total"], 1)
        self.assertTrue(diagnostics[0]["count_matches"])

    def test_build_audit_marks_unresolved_mapping_incomplete(self):
        rows = [
            {
                "issuer_code": "12345",
                "company_name": "테스트A",
                "market": "코스닥",
                "announcement_date": "2024-12-23",
                "designation_reason": "",
                "designation_date": "2024-12-24",
                "release_date": "2025-01-10",
                "category": "warning",
                "category_label": "투자경고",
                "ticker": "123450",
            },
            {
                "issuer_code": "54321",
                "company_name": "테스트B",
                "market": "코스닥",
                "announcement_date": "2024-12-19",
                "designation_reason": "",
                "designation_date": "2024-12-20",
                "release_date": "",
                "category": "risk",
                "category_label": "투자위험",
            },
        ]
        chunks = [
            {
                "category": "warning",
                "start_date": "2024-01-01",
                "end_date": "2024-12-31",
                "reported_total": 2,
                "rows_collected": 2,
                "pages": 1,
                "count_matches": True,
            }
        ]

        result = audit.build_audit(
            rows,
            chunks,
            [],
            start_date="2024-01-01",
            end_date="2024-12-31",
        )

        self.assertEqual(result["point_in_time_usable_rows"], 1)
        self.assertEqual(result["unresolved_issuer_codes"], ["54321"])
        self.assertFalse(result["point_in_time_filter_complete"])
        self.assertTrue(result["selection_2011_2023_filter_complete"])
        self.assertIn("trade_date < release_date", result["release_boundary_rule"])


if __name__ == "__main__":
    unittest.main()
