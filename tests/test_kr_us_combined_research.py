import unittest

import kr_us_combined_research as combined


class KrUsCombinedResearchTests(unittest.TestCase):
    def test_equal_budget_uses_half_of_each_sleeve(self):
        result = combined.combine_equal_budget({"2026-01-02": 0.10}, {"2026-01-02": -0.02, "2026-01-05": 0.04})

        self.assertAlmostEqual(result["2026-01-02"], 0.04)
        self.assertAlmostEqual(result["2026-01-05"], 0.02)

    def test_sequential_same_cash_compounds_same_date_returns(self):
        result = combined.combine_sequential_same_cash({"2026-01-02": 0.10}, {"2026-01-02": -0.02})

        self.assertAlmostEqual(result["2026-01-02"], 1.10 * 0.98 - 1.0)

    def test_correlation_reports_overlap_and_union(self):
        payload = combined.correlation_payload(
            {"2026-01-02": 0.01, "2026-01-03": -0.01},
            {"2026-01-03": 0.02, "2026-01-04": -0.02},
        )

        self.assertEqual(payload["union_active_dates"], 3)
        self.assertEqual(payload["overlap_dates"], 1)
        self.assertIsNone(payload["same_day_signal_correlation"])

    def test_series_metrics_uses_compounded_drawdown(self):
        metrics = combined.series_metrics({"2026-01-02": 0.10, "2026-01-03": -0.10})

        self.assertAlmostEqual(metrics.compounded_return, -0.01)
        self.assertAlmostEqual(metrics.max_drawdown, 0.10)


if __name__ == "__main__":
    unittest.main()
