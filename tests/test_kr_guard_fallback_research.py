import unittest

import kr_broad_strategy_research as broad
import kr_guard_fallback_research as fallback


def event(date="2026-01-02", symbol="TEST", **overrides):
    values = {
        "date": date,
        "symbol": symbol,
        "prev_close": 2000.0,
        "open": 1800.0,
        "high": 1900.0,
        "low": 1780.0,
        "close": 1850.0,
        "gap": -0.10,
        "prev_vol_ratio": 0.5,
        "avg_dollar_volume20": 500_000_000.0,
        "avg_range20": 0.05,
        "prev_return1": -0.01,
        "prev_return5": -0.05,
        "prev_return20": 0.02,
        "prev_close_location": 0.5,
        "future": (),
    }
    values.update(overrides)
    return broad.Event(**values)


def market(date="2026-01-02", open_vs_sma5=0.0):
    return broad.Market(date, open_vs_sma5, -0.005, 10, 2)


class GuardFallbackResearchTests(unittest.TestCase):
    def test_fallbacks_only_accept_guard_blocked_market(self):
        config = fallback.fallback_configs()[0]
        self.assertTrue(broad.passes(event(), market(open_vs_sma5=0.0), config))
        self.assertFalse(broad.passes(event(), market(open_vs_sma5=-0.02), config))

    def test_primary_trade_wins_on_same_date(self):
        config = broad.replace(
            broad.anchor_config(), market_max=None, stop_loss=None, take_profit=None
        )
        markets = {
            "2026-01-02": market(),
            "2026-01-05": market("2026-01-05"),
        }
        primary = broad.simulate([event(symbol="PRIMARY")], markets, config)
        secondary = broad.simulate(
            [event(symbol="FALLBACK"), event("2026-01-05", "SECOND")], markets, config
        )
        combined = fallback.combine_primary_and_fallback(primary, secondary)
        self.assertEqual([(row.date, row.symbol) for row in combined], [
            ("2026-01-02", "PRIMARY"),
            ("2026-01-05", "SECOND"),
        ])

    def test_failed_fallback_score_is_negative_infinity(self):
        empty = broad.metrics([])
        blocks = {name: empty for name in broad.WINDOWS}
        self.assertEqual(fallback.fallback_score(blocks), float("-inf"))


if __name__ == "__main__":
    unittest.main()
