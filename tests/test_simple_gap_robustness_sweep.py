import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from simple_gap_robustness_sweep import ResultBundle, config_neighborhood, robust_score
from simple_gap_variant_core import VariantConfig, VariantResult
from simple_gap_variant_search import row_payload


class SimpleGapRobustnessSweepTests(unittest.TestCase):
    def test_config_neighborhood_expands_around_seed_without_duplicates(self):
        seed = VariantConfig("seed", 30000.0, 1000.0, 8000.0, -0.05, 0.0, 0.8, 0, 1, "lowest_price", 0.0035, 0.0, 0.02, 0.12)

        configs = config_neighborhood(seed, limit=40)

        names = [cfg.name for cfg in configs]
        signatures = {(cfg.gap_threshold, cfg.max_price, cfg.prev_vol_ratio_max, cfg.stop_loss, cfg.take_profit) for cfg in configs}
        self.assertEqual(len(signatures), len(configs))
        self.assertIn("seed_n000", names)
        self.assertTrue(any(cfg.gap_threshold == -0.06 for cfg in configs))
        self.assertTrue(any(cfg.take_profit is None for cfg in configs))

    def test_robust_score_penalizes_harsh_drawdown(self):
        calm = self._result(compounded=8.0, drawdown=0.20, trades=120, profit_factor=1.8)
        volatile = self._result(compounded=8.0, drawdown=0.45, trades=120, profit_factor=1.8)

        calm_score = robust_score(ResultBundle(calm, calm, calm, calm, calm))
        volatile_score = robust_score(ResultBundle(calm, calm, calm, calm, volatile))

        self.assertGreater(calm_score, volatile_score)

    def test_row_payload_includes_roundtrip_cost_for_reproducibility(self):
        result = self._result(compounded=8.0, drawdown=0.20, trades=120, profit_factor=1.8)

        payload = row_payload(result, period="test", score=1.0)

        self.assertEqual(payload["roundtrip_cost"], 0.0035)

    def _result(self, *, compounded: float, drawdown: float, trades: int, profit_factor: float) -> VariantResult:
        return VariantResult(
            config=VariantConfig("x", 30000.0, 1000.0, 8000.0, -0.05, 0.0, 0.8, 0, 1, "lowest_price", 0.0035, 0.0, 0.02, 0.12),
            trades=trades,
            active_days=trades,
            avg_day_return=0.01,
            median_day_return=0.005,
            win_rate_days=0.55,
            win_rate_trades=0.55,
            compounded_return=compounded,
            max_drawdown=drawdown,
            profit_factor=profit_factor,
            avg_cash_used_pct=0.95,
            sample_trades=(),
        )


if __name__ == "__main__":
    unittest.main()
