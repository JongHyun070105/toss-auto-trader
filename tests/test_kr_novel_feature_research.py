import sqlite3
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

import kr_novel_feature_research as novel


def event(**overrides):
    values = {
        "date": "2026-01-02",
        "symbol": "TEST",
        "prev_close": 2000.0,
        "open": 1800.0,
        "high": 2100.0,
        "low": 1700.0,
        "close": 1950.0,
        "gap": -0.10,
        "prev_vol_ratio": 0.5,
        "avg_dollar_volume20": 500_000_000.0,
        "avg_range20": 0.05,
        "atr20": 0.08,
        "prev_return1": -0.01,
        "prev_return2": -0.02,
        "prev_return3": -0.01,
        "prev_return5": -0.05,
        "prev_return20": -0.10,
        "prev_body_return": -0.03,
        "prev_lower_wick_share": 0.45,
        "position20": 0.20,
        "drawdown20": -0.15,
        "sma5_distance": -0.03,
        "sma20_distance": -0.06,
        "range_ratio5_20": 0.70,
        "normalized_gap": -2.0,
        "gap_z60": -3.0,
        "gap_history60": 60,
        "position252": 0.15,
        "history252": 252,
    }
    values.update(overrides)
    return novel.NovelEvent(**values)


def market(**overrides):
    values = {
        "date": "2026-01-02",
        "open_vs_sma5": -0.02,
        "index_gap": -0.01,
        "gap2_count": 20,
        "gap5_count": 5,
    }
    values.update(overrides)
    return novel.Market(**values)


class KrNovelFeatureResearchTests(unittest.TestCase):
    def test_feature_rules_use_prior_features_and_open_market_data(self):
        row = event()
        context = market()
        self.assertTrue(novel.anchor_passes(row, context))
        self.assertTrue(novel.feature_passes(row, context, "gap_z60_3"))
        self.assertTrue(novel.feature_passes(row, context, "position252_bottom20"))
        self.assertTrue(novel.feature_passes(row, context, "market_residual_gap3"))
        self.assertFalse(
            novel.feature_passes(row, market(index_gap=-0.09), "market_residual_gap3")
        )

    def test_gap_z_rule_requires_sufficient_prior_history(self):
        self.assertFalse(
            novel.feature_passes(event(gap_history60=39), market(), "gap_z60_2")
        )

    def test_rank_is_deterministic_and_market_residual_aware(self):
        context = market(index_gap=-0.02)
        shallow = event(symbol="B", gap=-0.06)
        deep = event(symbol="A", gap=-0.08)
        selected = min(
            [shallow, deep], key=lambda row: novel.rank_key(row, "market_residual", context)
        )
        self.assertEqual(selected.symbol, "A")

    def test_gap_fill_exit_uses_stop_first_when_both_touch(self):
        price, reason = novel.exit_for(event(open=100.0, prev_close=110.0, low=95.0, high=112.0), "gap_fill100")
        self.assertAlmostEqual(price, 97.75)
        self.assertEqual(reason, "stop")

    def test_gap_fill_exit_uses_fixed_fraction_of_known_gap(self):
        price, reason = novel.exit_for(event(open=100.0, prev_close=110.0, low=99.0, high=106.0), "gap_fill50")
        self.assertAlmostEqual(price, 105.0)
        self.assertEqual(reason, "gap_fill50")

    def test_atr_exit_is_clamped_and_stop_first(self):
        price, reason = novel.exit_for(
            event(open=100.0, avg_range20=0.02, atr20=0.20, low=94.0, high=130.0),
            "range_half_two",
        )
        self.assertAlmostEqual(price, 96.0)
        self.assertEqual(reason, "stop")

    def test_daily_adverse_proxy_does_not_credit_high_only_target_touch(self):
        price, reason = novel.exit_for(
            event(open=100.0, prev_close=110.0, low=99.0, high=112.0, close=104.0),
            "gap_fill50",
            execution_model="daily_adverse_proxy",
        )
        self.assertAlmostEqual(price, 104.0 * 0.995)
        self.assertEqual(reason, "close_daily_proxy_stress")

    def test_daily_adverse_proxy_applies_adverse_stop_fill(self):
        price, reason = novel.exit_for(
            event(open=100.0, low=97.0, high=101.0),
            "fixed_stop0225_take12",
            execution_model="daily_adverse_proxy",
        )
        self.assertAlmostEqual(price, 97.75 * 0.99)
        self.assertEqual(reason, "stop_daily_adverse_proxy")

    def test_loader_rolling_features_exclude_current_bar(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "candles.sqlite3"
            connection = sqlite3.connect(db_path)
            connection.execute(
                "CREATE TABLE candle_cache (symbol TEXT, timestamp TEXT, interval TEXT, "
                "open_price REAL, high_price REAL, low_price REAL, close_price REAL, volume REAL)"
            )
            start = date(2025, 1, 1)
            rows = []
            for offset in range(301):
                current = start + timedelta(days=offset)
                is_target = offset == 300
                open_price = 900.0 if is_target else (995.0 if offset % 2 else 1005.0)
                high = 1200.0 if is_target else 1010.0
                low = 800.0 if is_target else 990.0
                rows.append(("A", current.isoformat(), "1d", open_price, high, low, 1000.0, 100.0))
            connection.executemany("INSERT INTO candle_cache VALUES (?,?,?,?,?,?,?,?)", rows)
            connection.commit()
            connection.close()
            target = (start + timedelta(days=300)).isoformat()

            loaded = novel.load_events(str(db_path), start=target, end=target)

        self.assertEqual(len(loaded), 1)
        self.assertAlmostEqual(loaded[0].avg_range20, 0.02)
        self.assertAlmostEqual(loaded[0].atr20, 0.02)
        self.assertAlmostEqual(loaded[0].normalized_gap, -5.0)
        self.assertLess(loaded[0].gap_z60, -10.0)
        self.assertEqual(loaded[0].history252, 252)

    def test_hypothesis_names_are_unique(self):
        names = [row.name for row in novel.hypotheses()]
        self.assertEqual(len(names), len(set(names)))


if __name__ == "__main__":
    unittest.main()
