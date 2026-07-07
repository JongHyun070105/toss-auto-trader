import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from simple_gap_variant_core import Candidate, VariantConfig, simulate_variant


class SimpleGapVariantCoreTests(unittest.TestCase):
    def test_simulate_variant_uses_integer_quantity_and_idle_cash(self):
        rows = [
            Candidate("2026-01-02", "A", 10000.0, 6000.0, 6600.0, 6700.0, 5900.0, -0.04, 0.5, (6500.0,)),
            Candidate("2026-01-02", "B", 10000.0, 9000.0, 9900.0, 10000.0, 8500.0, -0.05, 0.5, (9800.0,)),
        ]
        cfg = VariantConfig(
            name="unit",
            capital=10000.0,
            min_price=1000.0,
            max_price=10000.0,
            gap_threshold=-0.03,
            prev_vol_ratio_min=0.0,
            prev_vol_ratio_max=1.0,
            exit_offset=0,
            top_n=1,
            rank="largest_gap",
            roundtrip_cost=0.0,
            slippage=0.0,
        )

        result = simulate_variant(rows, cfg)

        self.assertEqual(result.trades, 1)
        self.assertEqual(result.active_days, 1)
        self.assertAlmostEqual(result.compounded_return, 0.09)
        self.assertEqual(result.sample_trades[0].symbol, "B")

    def test_simulate_variant_can_use_next_close_exit(self):
        rows = [
            Candidate("2026-01-02", "A", 10000.0, 5000.0, 4900.0, 5050.0, 4800.0, -0.04, 0.5, (5500.0,)),
        ]
        cfg = VariantConfig(
            name="unit",
            capital=10000.0,
            min_price=1000.0,
            max_price=10000.0,
            gap_threshold=-0.03,
            prev_vol_ratio_min=0.0,
            prev_vol_ratio_max=1.0,
            exit_offset=1,
            top_n=1,
            rank="largest_gap",
            roundtrip_cost=0.0,
            slippage=0.0,
        )

        result = simulate_variant(rows, cfg)

        self.assertEqual(result.trades, 1)
        self.assertAlmostEqual(result.compounded_return, 0.10)


if __name__ == "__main__":
    unittest.main()
