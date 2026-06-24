import importlib.util
import unittest
from decimal import Decimal
from pathlib import Path


spec = importlib.util.spec_from_file_location(
    "volume_shock_hypothesis_audit",
    Path(__file__).resolve().parents[1] / "scripts" / "volume_shock_hypothesis_audit.py",
)
volume_audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(volume_audit)


class VolumeShockAuditTests(unittest.TestCase):
    def test_small_sample_never_establishes_global_edge(self):
        signals = [
            {"timestamp": "2026-01-01", "net_return_after_cost": 0.01},
            {"timestamp": "2026-01-02", "net_return_after_cost": 0.02},
            {"timestamp": "2026-01-03", "net_return_after_cost": 0.03},
        ]
        agg = volume_audit.evaluate_aggregate(
            signals,
            min_total_signals=100,
            min_test_signals=30,
            min_win_rate=Decimal("0.52"),
            min_avg_net_return=Decimal("0"),
            train_fraction=Decimal("0.70"),
        )
        self.assertFalse(agg["edge_ok"])
        self.assertIn("insufficient_total_signals", agg["blockers"])
        self.assertIn("insufficient_locked_test_signals", agg["blockers"])

    def test_symbol_audit_uses_locked_single_horizon(self):
        candles = []
        for i in range(30):
            # Day 20 triggers the volume shock. Horizon=3 should use day 23 only.
            volume = "1000"
            open_price = "100"
            close_price = "101"
            if i == 20:
                volume = "4000"
                open_price = "100"
                close_price = "110"
            if i == 21:
                close_price = "200"  # would look great at h=1, but must be ignored for h=3.
            if i == 23:
                close_price = "100"  # h=3 after cost is negative.
            candles.append({
                "timestamp": f"2026-01-{i+1:02d}",
                "open_price": open_price,
                "close_price": close_price,
                "volume": volume,
            })
        row = volume_audit.test_symbol(
            candles,
            symbol="TEST",
            vol_mult=Decimal("3"),
            lookback=20,
            horizon=3,
            cost_pct=Decimal("0.006"),
        )
        self.assertEqual(row["horizon"], 3)
        self.assertEqual(row["stats"]["signals"], 1)
        self.assertLess(row["stats"]["avg_net_return_after_cost"], 0)


if __name__ == "__main__":
    unittest.main()
