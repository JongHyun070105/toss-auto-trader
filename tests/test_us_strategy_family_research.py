import unittest

import us_strategy_family_research as family


def event(**overrides):
    values = {
        "date": "2026-01-02",
        "symbol": "TEST",
        "open": 90.0,
        "close": 95.0,
        "gap": -0.10,
        "prev_vol_ratio": 0.5,
        "avg_dollar_volume20": 100_000_000.0,
        "spy_open_vs_sma5": -0.02,
        "qqq_open_vs_sma5": -0.03,
        "future": (("2026-01-05", 96.0, 97.0), ("2026-01-06", 98.0, 99.0), ("2026-01-07", 100.0, 101.0)),
    }
    values.update(overrides)
    return family.Event(**values)


def config(**overrides):
    values = {
        "name": "test",
        "direction": "down",
        "entry_timing": "close",
        "exit_timing": "open",
        "hold_days": 1,
        "gap_threshold": 0.05,
        "extreme_cap": 0.15,
        "prev_vol_ratio_max": 0.8,
        "min_dollar_volume": 25_000_000.0,
        "rank": "highest_liquidity",
        "market_proxy": "SPY",
        "market_gate": -0.01,
        "roundtrip_cost": 0.01,
    }
    values.update(overrides)
    return family.FamilyConfig(**values)


class UsStrategyFamilyResearchTests(unittest.TestCase):
    def test_down_and_up_market_gates_have_opposite_directions(self):
        self.assertTrue(family.passes(event(), config()))
        self.assertFalse(family.passes(event(spy_open_vs_sma5=0.01), config()))
        up = event(gap=0.10, spy_open_vs_sma5=0.02)
        self.assertTrue(family.passes(up, config(direction="up", market_gate=0.01)))

    def test_close_to_next_open_uses_expected_prices(self):
        entry, exit_price, exit_date = family.entry_exit(event(), config())
        self.assertEqual((entry, exit_price, exit_date), (95.0, 96.0, "2026-01-05"))

    def test_future_close_uses_requested_holding_period(self):
        cfg = config(entry_timing="open", exit_timing="close", hold_days=3)
        entry, exit_price, exit_date = family.entry_exit(event(), cfg)
        self.assertEqual((entry, exit_price, exit_date), (90.0, 101.0, "2026-01-07"))

    def test_simulation_skips_overlapping_signals_for_one_cash_sleeve(self):
        first = event()
        second = event(date="2026-01-05", symbol="SECOND")
        third = event(date="2026-01-06", symbol="THIRD", future=(("2026-01-07", 96.0, 97.0),))
        trades = family.simulate([first, second, third], config(), start="2026-01-01", end="2026-01-31")
        self.assertEqual([trade.symbol for trade in trades], ["TEST", "THIRD"])
        self.assertEqual(trades[0].signal_date, "2026-01-02")
        self.assertEqual(trades[0].date, "2026-01-05")

    def test_roundtrip_cost_is_deducted_from_full_fractional_amount(self):
        trades = family.simulate([event()], config(), start="2026-01-01", end="2026-01-31")
        self.assertAlmostEqual(trades[0].net_return, 96 / 95 - 1 - 0.01)
        self.assertAlmostEqual(trades[0].net_pnl_usd, 7 * trades[0].net_return)


if __name__ == "__main__":
    unittest.main()
