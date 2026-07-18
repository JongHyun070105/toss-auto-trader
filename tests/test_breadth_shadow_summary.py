import unittest

import breadth_shadow_summary as summary


class BreadthShadowSummaryTests(unittest.TestCase):
    def test_summary_pairs_latest_open_and_official_observations(self):
        result = summary.summarize([
            {
                "event": "breadth_shadow_open_snapshot",
                "date": "2026-07-17",
                "provisional_gap5_count": 3,
                "threshold": 4,
            },
            {
                "event": "breadth_shadow_official_reconciliation",
                "date": "2026-07-17",
                "official_gap5_count": 5,
                "threshold": 4,
            },
            {
                "event": "breadth_shadow_open_snapshot",
                "date": "2026-07-18",
                "provisional_gap5_count": 6,
                "threshold": 4,
            },
            {
                "event": "breadth_shadow_official_reconciliation",
                "date": "2026-07-18",
                "official_gap5_count": 7,
                "threshold": 4,
            },
        ])

        self.assertEqual(result["paired_dates"], 2)
        self.assertEqual(result["decision_match_rate"], 0.5)
        self.assertEqual(result["mean_count_error"], -1.5)
        self.assertFalse(result["rows"][0]["decision_match"])

    def test_empty_summary_is_explicit(self):
        result = summary.summarize([])
        self.assertEqual(result["paired_dates"], 0)
        self.assertIsNone(result["decision_match_rate"])
        self.assertIn("표본 없음", summary.render(result))


if __name__ == "__main__":
    unittest.main()
