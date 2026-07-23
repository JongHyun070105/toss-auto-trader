import unittest

import kr_gap_integrity_audit as audit
from kr_broad_strategy_research import Event, Market, Trade
from toss_auto_trader.gap_integrity import (
    MIN_RAW_ENTRY_GAP,
    is_noncomparable_base_gap,
)


def trade(date: str, symbol: str, pnl: float, gap: float) -> Trade:
    return Trade(
        date=date,
        exit_date=date,
        symbol=symbol,
        entry=1000.0,
        exit=1100.0,
        quantity=10,
        invested=10000.0,
        gross_pnl=pnl,
        net_pnl=pnl,
        net_return_on_capital=pnl / 10000.0,
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


class KrGapIntegrityAuditTests(unittest.TestCase):
    def test_gap_floor_keeps_limit_down_buffer_and_rejects_extreme_raw_gap(self):
        self.assertEqual(MIN_RAW_ENTRY_GAP, -0.31)
        self.assertFalse(is_noncomparable_base_gap(-0.305))
        self.assertTrue(is_noncomparable_base_gap(-0.311))

    def test_changed_trade_days_reports_replacement_and_pnl_delta(self):
        baseline = [trade("2026-01-02", "EXTREME", 1000.0, -0.50)]
        guarded = [trade("2026-01-02", "NORMAL", -200.0, -0.10)]

        rows = audit.changed_trade_days(baseline, guarded)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["baseline"]["symbol"], "EXTREME")
        self.assertEqual(rows[0]["guarded"]["symbol"], "NORMAL")
        self.assertEqual(rows[0]["net_pnl_delta"], -1200.0)

    def test_recent_changed_selection_does_not_block_safety_recommendation(self):
        baseline = {
            "full": {"metrics": {"total_pnl": 1000.0, "mdd_on_capital": 0.10}},
            "post_nxt_20250304_2026": {
                "metrics": {"total_pnl": 200.0, "mdd_on_capital": 0.08}
            },
        }
        guarded = {
            "full": {"metrics": {"total_pnl": 900.0, "mdd_on_capital": 0.10}},
            "post_nxt_20250304_2026": {
                "metrics": {"total_pnl": 300.0, "mdd_on_capital": 0.07}
            },
        }

        decision = audit.safety_guard_decision(
            extreme_event_count=1,
            positive_required_windows=True,
            post_nxt_trade_selection_changed=True,
            harsh_baseline_windows=baseline,
            harsh_guarded_windows=guarded,
        )

        self.assertTrue(decision["live_safety_guard_recommended"])
        self.assertTrue(decision["post_nxt_trade_selection_changed"])
        self.assertFalse(decision["recent_selection_change_blocks_recommendation"])
        self.assertEqual(decision["harsh_full_pnl_delta"], -100.0)
        self.assertEqual(decision["harsh_post_nxt_pnl_delta"], 100.0)
        self.assertFalse(decision["strategy_alpha_claim"])

    def test_audit_replaces_extreme_low_price_candidate_without_alpha_claim(self):
        events = [
            event("EXTREME", 900.0, -0.50),
            event("NORMAL", 1200.0, -0.10),
        ]
        markets = {
            "2026-01-02": Market(
                date="2026-01-02",
                open_vs_sma5=-0.02,
                index_gap=-0.01,
                gap2_count=2,
                gap5_count=2,
            )
        }

        result = audit.audit_events(events, markets, database="memory")

        self.assertEqual(result["eligible_extreme_event_count"], 1)
        self.assertEqual(
            result["harsh_changed_days"][0]["baseline"]["symbol"], "EXTREME"
        )
        self.assertEqual(
            result["harsh_changed_days"][0]["guarded"]["symbol"], "NORMAL"
        )
        self.assertFalse(result["decision"]["strategy_alpha_claim"])


if __name__ == "__main__":
    unittest.main()
