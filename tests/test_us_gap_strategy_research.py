import unittest

import us_gap_strategy_research as us


def candle(date, open_, high, low, close, volume=1_000_000):
    return us.Candle(date, open_, high, low, close, volume)


def candidate(**overrides):
    values = {
        "date": "2026-01-02",
        "symbol": "TEST",
        "open": 90.0,
        "high": 105.0,
        "low": 85.0,
        "close": 95.0,
        "prev_close": 100.0,
        "gap": -0.10,
        "prev_vol_ratio": 0.5,
        "avg_dollar_volume20": 50_000_000.0,
        "spy_open_vs_sma5": -0.02,
        "qqq_open_vs_sma5": -0.01,
        "iwm_open_vs_sma5": 0.01,
    }
    values.update(overrides)
    return us.Candidate(**values)


def config(**overrides):
    values = {
        "name": "test",
        "market_proxy": "SPY",
        "market_gate_max": -0.01,
        "gap_max": -0.05,
        "gap_min": -0.15,
        "prev_vol_ratio_max": 0.8,
        "min_dollar_volume": 25_000_000.0,
        "rank": "highest_liquidity",
        "stop_loss": 0.03,
        "take_profit": 0.08,
        "roundtrip_cost": 0.01,
    }
    values.update(overrides)
    return us.StrategyConfig(**values)


class UsGapStrategyResearchTests(unittest.TestCase):
    def test_market_gate_uses_current_open_and_previous_four_closes(self):
        rows = [
            candle("2025-12-26", 100, 101, 99, 100),
            candle("2025-12-29", 100, 101, 99, 100),
            candle("2025-12-30", 100, 101, 99, 100),
            candle("2025-12-31", 100, 101, 99, 100),
            candle("2026-01-02", 95, 96, 94, 95),
        ]

        gate = us.market_gate_map(rows)

        self.assertAlmostEqual(gate["2026-01-02"], 95 / 99 - 1)

    def test_filters_enforce_gap_floor_liquidity_volume_and_market_gate(self):
        cfg = config()
        self.assertTrue(us.passes(candidate(), cfg))
        self.assertFalse(us.passes(candidate(gap=-0.20), cfg))
        self.assertFalse(us.passes(candidate(prev_vol_ratio=0.9), cfg))
        self.assertFalse(us.passes(candidate(avg_dollar_volume20=1_000_000), cfg))
        self.assertFalse(us.passes(candidate(spy_open_vs_sma5=0.0), cfg))
        self.assertTrue(us.passes(candidate(qqq_open_vs_sma5=-0.02), config(market_proxy="QQQ")))

    def test_exit_is_stop_first_when_daily_bar_hits_both(self):
        exit_price, reason, both = us.exit_trade(candidate(open=100, low=95, high=110), config())

        self.assertEqual(reason, "stop")
        self.assertTrue(both)
        self.assertEqual(exit_price, 97)

    def test_fractional_amount_simulation_uses_full_seven_dollars(self):
        trades = us.simulate([candidate(open=90, high=100, low=89, close=99)], config(stop_loss=None, take_profit=None), start="2026-01-01", end="2026-01-31")

        self.assertEqual(len(trades), 1)
        self.assertAlmostEqual(trades[0].gross_return, 0.10)
        self.assertAlmostEqual(trades[0].net_pnl_usd, 7 * 0.09)

    def test_ranking_is_deterministic(self):
        rows = [candidate(symbol="LOW", avg_dollar_volume20=10_000_000), candidate(symbol="HIGH", avg_dollar_volume20=100_000_000)]

        trades = us.simulate(rows, config(), start="2026-01-01", end="2026-01-31")

        self.assertEqual(trades[0].symbol, "HIGH")

    def test_json_safe_removes_non_standard_infinity(self):
        self.assertEqual(us.json_safe({"pf": float("inf"), "rows": [float("nan"), 1.0]}), {"pf": None, "rows": [None, 1.0]})


if __name__ == "__main__":
    unittest.main()
