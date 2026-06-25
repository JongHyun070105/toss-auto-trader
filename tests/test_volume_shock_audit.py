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

    def test_concentration_blockers_flag_symbol_and_month_dominance(self):
        signals = []
        for i in range(8):
            signals.append({"symbol": "AAA", "timestamp": f"2026-01-{i+1:02d}", "net_return_after_cost": 0.03})
        for i in range(2):
            signals.append({"symbol": "BBB", "timestamp": f"2026-02-{i+1:02d}", "net_return_after_cost": 0.03})

        agg = volume_audit.evaluate_aggregate(
            signals,
            min_total_signals=1,
            min_test_signals=1,
            min_win_rate=Decimal("0"),
            min_avg_net_return=Decimal("-1"),
            train_fraction=Decimal("0.50"),
            min_signal_symbols=3,
            max_symbol_signal_share=Decimal("0.50"),
            max_month_signal_share=Decimal("0.60"),
        )
        self.assertFalse(agg["edge_ok"])
        self.assertIn("insufficient_signal_symbols", agg["blockers"])
        self.assertIn("top_symbol_signal_share_too_high", agg["blockers"])
        self.assertIn("top_month_signal_share_too_high", agg["blockers"])
        self.assertEqual(agg["distribution"]["symbols_with_signals"], 2)

    def test_positive_candle_baseline_removes_only_volume_threshold(self):
        candles = []
        for i in range(12):
            candles.append({
                "timestamp": f"2026-01-{i+1:02d}",
                "open_price": "100",
                "high_price": "103",
                "low_price": "99",
                "close_price": "102",
                "volume": "1000",
            })
        candles[4]["volume"] = "4000"
        row = volume_audit.test_symbol(
            candles,
            symbol="TEST",
            vol_mult=Decimal("3"),
            lookback=3,
            horizon=1,
            cost_pct=Decimal("0.006"),
        )
        self.assertEqual(row["stats"]["signals"], 1)
        self.assertGreater(len(row["_baseline_signals"]), len(row["_signals"]))

        comparison = volume_audit.benchmark_comparison(
            row["_signals"],
            row["_baseline_signals"],
            train_fraction=Decimal("0.50"),
        )
        self.assertEqual(comparison["baseline"], "positive_candle_without_volume_threshold")

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
            if i == 22:
                close_price = "200"  # entry is at i=21. i=22 (h=1) close is high, must be ignored.
            if i == 24:
                close_price = "90"   # entry at i=21 open(100), exit at i=24 close(90) -> negative return.
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
