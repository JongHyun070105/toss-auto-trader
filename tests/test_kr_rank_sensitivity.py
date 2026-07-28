import unittest

import kr_rank_sensitivity as sensitivity


def metrics(total_pnl: float, mdd: float, top25_pnl: float) -> dict:
    return {
        "metrics": {"total_pnl": total_pnl, "mdd_on_capital": mdd},
        "top_winners_25pct_removed": {"total_pnl": top25_pnl},
    }


def blocks(total_pnl: float, mdd: float, top25_pnl: float) -> dict:
    return {
        window: metrics(total_pnl, mdd, top25_pnl)
        for window in sensitivity.REQUIRED_WINDOWS + ("full",)
    }


class KrRankSensitivityTests(unittest.TestCase):
    def test_rank_config_rejects_unknown_rank(self):
        with self.assertRaises(ValueError):
            sensitivity.rank_config("unknown")

    def test_promotion_gate_accepts_only_strict_robust_candidate(self):
        anchor = {cost: blocks(100.0, 0.10, 30.0) for cost in sensitivity.COSTS}
        candidate = {cost: blocks(100.0, 0.10, 30.0) for cost in sensitivity.COSTS}

        decision = sensitivity.robust_rank_decision(
            "highest_liquidity", candidate, anchor
        )

        self.assertTrue(decision["accepted"])
        self.assertEqual(decision["status"], "promote_candidate")

    def test_promotion_gate_rejects_post_nxt_mdd_regression(self):
        anchor = {cost: blocks(100.0, 0.10, 30.0) for cost in sensitivity.COSTS}
        candidate = {cost: blocks(100.0, 0.11, 30.0) for cost in sensitivity.COSTS}

        decision = sensitivity.robust_rank_decision(
            "mildest_gap", candidate, anchor
        )

        self.assertFalse(decision["accepted"])
        self.assertIn("harsh:post_nxt_20250304_2026:above_live_mdd", decision["failures"])

    def test_live_rank_is_never_marked_for_automatic_promotion(self):
        anchor = {cost: blocks(100.0, 0.10, 30.0) for cost in sensitivity.COSTS}

        decision = sensitivity.robust_rank_decision("lowest_price", anchor, anchor)

        self.assertFalse(decision["accepted"])
        self.assertEqual(decision["status"], "current_live")


if __name__ == "__main__":
    unittest.main()
