import sqlite3
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

import kr_external_method_research as external


def event(**overrides):
    values = {
        "date": "2026-01-02",
        "symbol": "TEST",
        "prev_close": 2000.0,
        "open": 1800.0,
        "high": 2100.0,
        "low": 1780.0,
        "close": 1950.0,
        "next_date": "2026-01-05",
        "next_open": 2000.0,
        "gap": -0.10,
        "prev_vol_ratio": 0.5,
        "avg_dollar_volume20": 500_000_000.0,
        "prev_return20": -0.10,
        "beta60": 1.5,
        "ivol60": 0.03,
        "history60": 60,
        "max_return20": 0.08,
        "amihud20": 1e-10,
        "volume_z50": -1.2,
    }
    values.update(overrides)
    return external.ResearchEvent(**values)


def market(**overrides):
    values = {
        "date": "2026-01-02",
        "open_vs_sma5": -0.02,
        "index_gap": -0.02,
        "gap2_count": 10,
        "gap5_count": 4,
    }
    values.update(overrides)
    return external.Market(**values)


class KrExternalMethodResearchTests(unittest.TestCase):
    def test_beta_residual_uses_current_market_open_and_prior_beta(self):
        row = event(gap=-0.08, beta60=1.5)
        self.assertAlmostEqual(external.market_residual_gap(row, market(index_gap=-0.02)), -0.05)
        self.assertEqual(
            external.apply_filter([row], market(index_gap=-0.02), "beta_residual_gap5"),
            [row],
        )
        self.assertEqual(
            external.apply_filter([row], market(index_gap=-0.04), "beta_residual_gap3"),
            [],
        )

    def test_cross_sectional_gap_momentum_rank_is_deterministic(self):
        deep_weak = event(symbol="A", gap=-0.12, prev_return20=-0.20)
        shallow_strong = event(symbol="B", gap=-0.06, prev_return20=-0.01)
        ranked = external.ranked([shallow_strong, deep_weak], "gap_momentum_z", market())
        self.assertEqual([row.symbol for row in ranked], ["A", "B"])

    def test_standardized_low_volume_filter_uses_only_prior_volume_feature(self):
        quiet = event(symbol="A", volume_z50=-1.2)
        normal = event(symbol="B", volume_z50=-0.2)
        self.assertEqual(
            external.apply_filter(
                [normal, quiet], market(), "volume_z50_below_minus1"
            ),
            [quiet],
        )

    def test_same_day_bracket_is_stop_first(self):
        result = external.exit_for(
            event(open=100.0, low=95.0, high=120.0),
            "same_day_bracket",
            execution_model="reference",
            last_market_date="2026-12-31",
        )
        self.assertEqual(result, ("2026-01-02", 97.75, "stop"))

    def test_public_overnight_rule_uses_close_confirmed_stop(self):
        stopped = external.exit_for(
            event(open=100.0, low=90.0, close=97.0, next_open=110.0),
            "next_open_close_stop",
            execution_model="reference",
            last_market_date="2026-12-31",
        )
        held = external.exit_for(
            event(open=100.0, low=90.0, close=99.0, next_open=110.0),
            "next_open_close_stop",
            execution_model="reference",
            last_market_date="2026-12-31",
        )
        self.assertEqual(stopped, ("2026-01-02", 97.0, "close_stop"))
        self.assertEqual(held, ("2026-01-05", 110.0, "next_open"))

    def test_missing_next_open_is_not_silently_dropped_before_dataset_end(self):
        result = external.exit_for(
            event(next_date=None, next_open=None, close=100.0, open=100.0),
            "next_open_close_stop",
            execution_model="reference",
            last_market_date="2026-12-31",
        )
        self.assertEqual(result, ("2026-01-02", 0.0, "missing_next_open_total_loss"))

    def test_next_open_exit_allows_new_entry_on_same_open(self):
        rows = [
            event(
                date="2026-01-02",
                symbol="A",
                next_date="2026-01-05",
                next_open=1900.0,
            ),
            event(
                date="2026-01-05",
                symbol="B",
                next_date="2026-01-06",
                next_open=1900.0,
            ),
        ]
        contexts = {
            "2026-01-02": market(date="2026-01-02"),
            "2026-01-05": market(date="2026-01-05"),
            "2026-01-06": market(date="2026-01-06"),
        }
        method = external.Method(
            "overnight", exit_rule="next_open_close_stop"
        )
        trades = external.simulate(
            rows, contexts, method, roundtrip_cost=external.COSTS["harsh"]
        )
        self.assertEqual([trade.date for trade in trades], ["2026-01-02", "2026-01-05"])

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
            index_rows = []
            for offset in range(90):
                current = start + timedelta(days=offset)
                target = offset == 88
                open_price = 900.0 if target else 1000.0
                high = 1200.0 if target else 1010.0
                low = 800.0 if target else 990.0
                close = 1100.0 if target else 1000.0
                volume = 10_000.0 if target else 100.0
                rows.append(
                    ("A", current.isoformat(), "1d", open_price, high, low, close, volume)
                )
                index_rows.append(
                    {"date": current.isoformat(), "open": 100.0, "close": 100.0}
                )
            connection.executemany("INSERT INTO candle_cache VALUES (?,?,?,?,?,?,?,?)", rows)
            connection.commit()
            connection.close()
            target_date = (start + timedelta(days=88)).isoformat()

            loaded = external.load_events(
                str(db_path), index_rows, start=target_date, end=target_date
            )

        self.assertEqual(len(loaded), 1)
        self.assertAlmostEqual(loaded[0].prev_vol_ratio, 1.0)
        self.assertAlmostEqual(loaded[0].max_return20, 0.0)
        self.assertAlmostEqual(loaded[0].ivol60, 0.0)
        self.assertEqual(loaded[0].next_open, 1000.0)

    def test_method_names_are_unique(self):
        names = [method.name for method in external.methods()]
        self.assertEqual(len(names), len(set(names)))

    def test_window_payload_keeps_yearly_pnl_visible(self):
        trade = external.Trade(
            date="2026-01-02",
            exit_date="2026-01-02",
            symbol="A",
            entry=1000.0,
            exit=1100.0,
            quantity=1,
            invested=1000.0,
            gross_pnl=100.0,
            net_pnl=90.0,
            net_return_on_capital=0.009,
            reason="take",
            gap=-0.05,
            avg_dollar_volume20=1_000_000.0,
            avg_range20=0.02,
            prev_return5=-0.01,
            market_open_vs_sma5=-0.02,
        )
        payload = external.window_payload([trade])
        self.assertEqual(payload["recent_2026"]["yearly_pnl"], {"2026": 90.0})
        self.assertEqual(payload["recent_2026"]["exit_reason_counts"], {"take": 1})


if __name__ == "__main__":
    unittest.main()
