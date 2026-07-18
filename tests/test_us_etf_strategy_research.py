import unittest

import us_etf_strategy_research as etf


def event(**overrides):
    values = {
        "date": "2026-01-02", "symbol": "SPY", "open": 95.0, "close": 97.0,
        "open_vs_sma5": -0.02, "prev_return": -0.01, "gap": -0.01,
        "future": (("2026-01-05", 98.0), ("2026-01-06", 99.0), ("2026-01-07", 100.0)),
    }
    values.update(overrides)
    return etf.EtfEvent(**values)


def config(**overrides):
    values = {
        "name": "test", "symbol": "SPY", "open_vs_sma5_max": -0.01,
        "prev_return_max": 0.0, "gap_max": 0.0, "hold_days": 3, "roundtrip_cost": 0.01,
    }
    values.update(overrides)
    return etf.EtfConfig(**values)


class UsEtfStrategyResearchTests(unittest.TestCase):
    def test_filters_are_known_at_open(self):
        self.assertTrue(etf.passes(event(), config()))
        self.assertFalse(etf.passes(event(open_vs_sma5=0.01), config()))
        self.assertFalse(etf.passes(event(prev_return=0.01), config()))
        self.assertFalse(etf.passes(event(gap=0.01), config()))

    def test_holding_period_uses_future_close_and_exit_date(self):
        trade = etf.simulate([event()], config(), start="2026-01-01", end="2026-01-31")[0]
        self.assertEqual(trade.signal_date, "2026-01-02")
        self.assertEqual(trade.exit_date, "2026-01-07")
        self.assertAlmostEqual(trade.net_return, 100 / 95 - 1 - 0.01)


if __name__ == "__main__":
    unittest.main()
