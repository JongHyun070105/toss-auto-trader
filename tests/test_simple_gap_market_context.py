import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from simple_gap_market_context import MarketContext, MarketFilter, filter_candidates_by_market
from simple_gap_variant_core import Candidate


class SimpleGapMarketContextTests(unittest.TestCase):
    def test_filter_candidates_by_market_keeps_only_dates_matching_regime(self):
        rows = [
            Candidate("2026-01-02", "A", 1000.0, 950.0, 990.0, 1000.0, 940.0, -0.05, 0.4, (1000.0,)),
            Candidate("2026-01-03", "B", 1000.0, 950.0, 900.0, 970.0, 890.0, -0.05, 0.4, (930.0,)),
        ]
        contexts = {
            "2026-01-02": MarketContext("2026-01-02", 0.01, 0.03, 0.45, 0.018, 0.06, 1800),
            "2026-01-03": MarketContext("2026-01-03", -0.04, -0.05, 0.20, 0.035, 0.12, 1800),
        }
        market_filter = MarketFilter(
            name="calm_rebound",
            market_gap_min=-0.02,
            market_gap_max=0.03,
            prev_market_return_min=0.0,
            prev_market_return_max=0.05,
            prev_breadth_up_min=0.35,
            prev_breadth_up_max=0.65,
            volatility20_max=0.02,
            prev_avg_range_max=0.08,
        )

        filtered = filter_candidates_by_market(rows, contexts, market_filter)

        self.assertEqual([row.symbol for row in filtered], ["A"])

    def test_filter_candidates_by_market_allows_unbounded_filter_fields(self):
        rows = [
            Candidate("2026-01-02", "A", 1000.0, 950.0, 990.0, 1000.0, 940.0, -0.05, 0.4, (1000.0,)),
        ]
        contexts = {
            "2026-01-02": MarketContext("2026-01-02", -0.08, -0.02, 0.10, 0.07, 0.18, 1700),
        }
        market_filter = MarketFilter(name="all")

        filtered = filter_candidates_by_market(rows, contexts, market_filter)

        self.assertEqual(len(filtered), 1)


if __name__ == "__main__":
    unittest.main()
