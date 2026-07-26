import unittest

import kr_gap_floor_sensitivity as sensitivity
from kr_broad_strategy_research import Event, Market, Trade
from toss_auto_trader.gap_integrity import MIN_RAW_ENTRY_GAP


def trade(gap: float) -> Trade:
    return Trade(
        date="2026-01-02",
        exit_date="2026-01-02",
        symbol=str(gap),
        entry=1000.0,
        exit=1000.0,
        quantity=10,
        invested=10000.0,
        gross_pnl=0.0,
        net_pnl=0.0,
        net_return_on_capital=0.0,
        reason="close",
        gap=gap,
        avg_dollar_volume20=100_000_000.0,
        avg_range20=0.05,
        prev_return5=0.0,
        market_open_vs_sma5=-0.02,
    )


def event(symbol: str, open_price: float, gap: float) -> Event:
    return Event(
        date="2026-01-02",
        symbol=symbol,
        prev_close=open_price / (1.0 + gap),
        open=open_price,
        high=open_price * 1.13,
        low=open_price * 0.97,
        close=open_price * 1.05,
        gap=gap,
        prev_vol_ratio=0.5,
        avg_dollar_volume20=100_000_000.0,
        avg_range20=0.05,
        prev_return1=0.0,
        prev_return5=0.0,
        prev_return20=0.0,
        prev_close_location=0.5,
        future=(),
    )


class KrGapFloorSensitivityTests(unittest.TestCase):
    def test_fixed_matrix_starts_with_old_rule_and_live_integrity_floor(self):
        self.assertIsNone(sensitivity.FIXED_GAP_FLOORS[0])
        self.assertEqual(sensitivity.FIXED_GAP_FLOORS[1], MIN_RAW_ENTRY_GAP)
        self.assertEqual(sensitivity.floor_label(None), "unbounded_old_rule")
        self.assertEqual(sensitivity.floor_label(-0.15), "floor_15pct")

    def test_selected_gap_distribution_counts_large_gap_tail(self):
        result = sensitivity.selected_gap_distribution(
            [trade(-0.06), trade(-0.10), trade(-0.16), trade(-0.32)]
        )

        self.assertEqual(result["minimum"], -0.32)
        self.assertEqual(result["median"], -0.10)
        self.assertEqual(result["thresholds"]["at_or_below_10pct"]["count"], 3)
        self.assertEqual(result["thresholds"]["at_or_below_30pct"]["count"], 1)

    def test_gap_bucket_boundaries_do_not_overlap(self):
        self.assertEqual(sensitivity.gap_bucket_label(-0.06), "5_to_8pct")
        self.assertEqual(sensitivity.gap_bucket_label(-0.08), "8_to_10pct")
        self.assertEqual(sensitivity.gap_bucket_label(-0.10), "10_to_12pct")
        self.assertEqual(sensitivity.gap_bucket_label(-0.30), "30pct_or_more")
        self.assertIsNone(sensitivity.gap_bucket_label(-0.04))

    def test_tighter_floors_replace_old_extreme_selection(self):
        events = [
            event("EXTREME", 900.0, -0.50),
            event("NORMAL10", 1200.0, -0.10),
            event("MILD6", 1400.0, -0.06),
        ]
        markets = {
            "2026-01-02": Market(
                date="2026-01-02",
                open_vs_sma5=-0.02,
                index_gap=-0.01,
                gap2_count=3,
                gap5_count=3,
            )
        }

        result = sensitivity.evaluate_database(events, markets, database="memory")
        by_floor = {row["floor"]: row for row in result["floor_results"]}

        self.assertEqual(
            by_floor[None]["changed_days_vs_old_rule"], 0
        )
        self.assertEqual(
            by_floor[MIN_RAW_ENTRY_GAP]["changed_days"][0]["guarded"]["symbol"],
            "NORMAL10",
        )
        self.assertEqual(
            by_floor[-0.08]["changed_days"][0]["guarded"]["symbol"],
            "MILD6",
        )

        result["database_fingerprint"] = {
            "full_sha256": "db-hash",
            "size_bytes": 123,
            "latest_date": "2026-01-02",
        }
        markdown = sensitivity.render_markdown(
            {
                "generated_at": "2026-01-02T00:00:00+09:00",
                "live_integrity_floor": MIN_RAW_ENTRY_GAP,
                "source_fingerprints": {
                    "kosdaq_index_sha256": "index-hash",
                    "script_sha256": "script-hash",
                },
                "databases": [result],
            }
        )
        self.assertLess(
            markdown.index("## Frozen inputs"),
            markdown.index("## Harsh-cost comparison"),
        )
        self.assertGreater(
            markdown.index("| memory | none |"),
            markdown.index("|---|---:|"),
        )


if __name__ == "__main__":
    unittest.main()
