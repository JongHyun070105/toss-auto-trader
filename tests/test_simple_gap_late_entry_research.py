import unittest

from simple_gap_late_entry_research import EntryConfig, current_strategy_config, entry_price, exit_price
from simple_gap_variant_core import Candidate


def sample_candidate(**overrides):
    values = {
        "date": "2026-01-02",
        "symbol": "123456",
        "prev_close": 2000.0,
        "open_price": 1800.0,
        "close_price": 1760.0,
        "high_price": 2050.0,
        "low_price": 1740.0,
        "gap_return": -0.10,
        "prev_vol_ratio": 0.5,
        "future_closes": (),
    }
    values.update(overrides)
    return Candidate(**values)


class SimpleGapLateEntryResearchTests(unittest.TestCase):
    def test_pullback_entry_requires_daily_low_to_reach_price(self):
        config = EntryConfig("late", current_strategy_config(), "pullback", 0.01)

        self.assertEqual(entry_price(sample_candidate(low_price=1780.0), config), 1782.0)
        self.assertIsNone(entry_price(sample_candidate(low_price=1783.0), config))

    def test_exit_uses_stop_first_when_daily_ohlc_is_ambiguous(self):
        config = current_strategy_config()
        entry = EntryConfig("late", config, "pullback", 0.01, "high")
        candidate = sample_candidate(low_price=1730.0, high_price=2050.0, close_price=1900.0)

        price, reason = exit_price(candidate, 1782.0, entry, config)

        self.assertEqual(reason, "stop")
        self.assertAlmostEqual(price, 1782.0 * (1.0 - 0.0225))

    def test_close_take_policy_requires_close_to_reach_take_profit(self):
        config = current_strategy_config()
        entry = EntryConfig("late", config, "pullback", 0.01, "close")
        candidate = sample_candidate(low_price=1780.0, high_price=2100.0, close_price=1900.0)

        price, reason = exit_price(candidate, 1782.0, entry, config)

        self.assertEqual(reason, "close")
        self.assertEqual(price, 1900.0)


if __name__ == "__main__":
    unittest.main()
