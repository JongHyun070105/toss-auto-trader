import math
import unittest

import kr_breadth_gate_research as breadth


class KrBreadthGateResearchTests(unittest.TestCase):
    def test_thresholds_cover_anchor_and_one_through_twenty(self):
        configs = breadth.threshold_configs()
        self.assertEqual(len(configs), 21)
        self.assertIsNone(configs[0].gap5_count_min)
        self.assertEqual([config.gap5_count_min for config in configs[1:]], list(range(1, 21)))

    def test_pretest_selection_ignores_failed_score(self):
        rows = [
            {"threshold": 0, "selection_score": -math.inf},
            {"threshold": 5, "selection_score": 3.0},
            {"threshold": 10, "selection_score": 2.0},
        ]
        self.assertEqual(breadth.select_pretest(rows)["threshold"], 5)


if __name__ == "__main__":
    unittest.main()
