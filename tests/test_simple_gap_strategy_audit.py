import importlib.util
import unittest
from pathlib import Path


def load_audit():
    path = Path(__file__).resolve().parents[1] / "scripts" / "simple_gap_strategy_audit.py"
    spec = importlib.util.spec_from_file_location("simple_gap_strategy_audit", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SimpleGapStrategyAuditTests(unittest.TestCase):
    def setUp(self):
        self.mod = load_audit()

    def test_fixed_capital_accounts_for_idle_cash_and_integer_qty(self):
        trades = [
            {"date": "2026-01-02", "symbol": "000001", "open_price": 6000, "close_price": 6600, "raw_return": 0.10, "gap_return": -0.03, "prev_vol_ratio": 0.5},
        ]
        summary = self.mod.summarize_capital_trades(trades, capital=10_000, roundtrip_cost=0.0)
        self.assertEqual(summary["trades"], 1)
        # One share only: 600 KRW pnl over 10,000 KRW account = 6%, not 10% invested return.
        self.assertAlmostEqual(summary["avg_net_return_on_capital"], 0.06)
        self.assertAlmostEqual(summary["avg_cash_used_pct"], 0.60)

    def test_select_daily_top_skips_unaffordable_largest_gap(self):
        rows = [
            {"date": "2026-01-02", "symbol": "A", "open_price": 50_000, "close_price": 49_000, "gap_return": -0.05, "raw_return": -0.02, "prev_vol_ratio": 0.5},
            {"date": "2026-01-02", "symbol": "B", "open_price": 9_000, "close_price": 10_000, "gap_return": -0.04, "raw_return": 0.1111, "prev_vol_ratio": 0.5},
        ]
        selected, skipped = self.mod.select_daily_top(rows, capital=10_000)
        self.assertEqual(skipped, 0)
        self.assertEqual(selected[0]["symbol"], "B")

    def test_capital_summary_handles_no_affordable_trade(self):
        trades = [{"date": "2026-01-02", "symbol": "A", "open_price": 50_000, "close_price": 55_000, "raw_return": 0.1}]
        summary = self.mod.summarize_capital_trades(trades, capital=10_000, roundtrip_cost=0.0)
        self.assertEqual(summary["trades"], 0)
        self.assertIsNone(summary["avg_net_return_on_capital"])


if __name__ == "__main__":
    unittest.main()
