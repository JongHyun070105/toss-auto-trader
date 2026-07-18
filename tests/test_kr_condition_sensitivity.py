import unittest

import kr_condition_sensitivity as sensitivity


class KrConditionSensitivityTests(unittest.TestCase):
    def test_families_have_unique_names_and_anchor_variants(self):
        families = sensitivity.condition_families()
        self.assertEqual(set(families), {
            "market_gate", "stock_gap", "price", "prior_volume", "liquidity",
            "prior_5d_return", "prior_close_location", "market_breadth", "rank", "exit",
        })
        for configs in families.values():
            names = [config.name for config in configs]
            self.assertEqual(len(names), len(set(names)))

    def test_market_gate_family_contains_current_rule(self):
        configs = sensitivity.condition_families()["market_gate"]
        anchor = next(config for config in configs if config.name.endswith("below_1pct_anchor"))
        self.assertEqual(anchor.market_max, -0.01)


if __name__ == "__main__":
    unittest.main()
