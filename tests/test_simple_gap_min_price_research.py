import importlib.util
import unittest
from pathlib import Path


def load_research():
    path = Path(__file__).resolve().parents[1] / "scripts" / "simple_gap_min_price_research.py"
    spec = importlib.util.spec_from_file_location("simple_gap_min_price_research", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SimpleGapMinPriceResearchTests(unittest.TestCase):
    def test_select_live_candidate_skips_unaffordable_and_warning_names(self):
        mod = load_research()
        candidates = [
            {"symbol": "A", "name": "too_expensive", "open_price": 20_000, "gap_return": -0.08},
            {"symbol": "B", "name": "warning", "open_price": 6_000, "gap_return": -0.07},
            {"symbol": "C", "name": "clean", "open_price": 4_000, "gap_return": -0.06},
        ]
        selected, warnings, skipped = mod.select_live_candidate(
            candidates,
            capital=10_000,
            warning_lookup=lambda symbol: ["NAVER_BADGE:투자주의"] if symbol == "B" else [],
        )
        self.assertEqual(skipped, 1)
        self.assertEqual(warnings[0]["symbol"], "B")
        self.assertEqual(selected["symbol"], "C")
        self.assertEqual(selected["limit_price"], 4000)
        self.assertEqual(selected["quantity"], 2)

    def test_format_snapshot_marks_live_min_price_unchanged(self):
        mod = load_research()
        record = {
            "generated_at": "2026-07-01 10:00:00",
            "capital_krw": 10_000,
            "live_min_price_unchanged": 5_000,
            "kosdaq_gate": {"ok": True},
            "rows": [
                {"min_price": 1000, "candidate_count": 3, "selected": {"symbol": "C", "name": "clean", "limit_price": 4000}, "warning_exclusions": [], "skipped_unaffordable_before_warning": 1}
            ],
        }
        text = mod.format_snapshot(record)
        self.assertIn("live MIN_PRICE unchanged: 5,000원", text)
        self.assertIn("clean(C)", text)


if __name__ == "__main__":
    unittest.main()
