import unittest
from decimal import Decimal

from toss_auto_trader.live_order import (
    ACK_PREFIX,
    build_buy_limit_payloads,
    candidate_fingerprint,
    required_confirmation,
    validate_candidate_for_live,
    validate_fresh_orderbooks,
)


def ready_candidate():
    return {
        "name": "ready",
        "pair": "204620:6000+032620:4000",
        "branch": "balanced_momentum",
        "window": 40,
        "horizon": 1,
        "mode": "shared_account",
        "source": "walk_forward",
        "stable_positive": True,
        "validation_pnl_krw": 100,
        "status": "spread_checked_watchlist_not_live_order",
        "spread_guard": {"ok": True, "max_spread_bps_allowed": "30", "max_impact_bps_allowed": "30"},
        "observation_guard": {"ok": True, "recent_observations": 3},
        "edge_guard": {"ok": True},
        "edge_audit": {"edge_ok": True},
    }


class LiveOrderGateTests(unittest.TestCase):
    def test_candidate_file_must_explicitly_allow_live_order(self):
        candidate = ready_candidate()
        validation = validate_candidate_for_live(
            {"live_order_allowed": False, "manual_approval_required": True},
            candidate,
            stress_report={"rows": [{"pair": candidate["pair"], "ok": True}]},
        )
        self.assertFalse(validation.ok)
        self.assertIn("candidate_file_live_order_allowed_must_be_true", validation.errors)

    def test_blocked_edge_candidate_cannot_be_approved(self):
        candidate = ready_candidate()
        candidate["status"] = "blocked_strategy_edge_not_established"
        candidate["edge_guard"] = {"ok": False, "reason": "strategy_edge_not_established_for_all_legs"}
        validation = validate_candidate_for_live(
            {"live_order_allowed": True, "manual_approval_required": True},
            candidate,
            stress_report={"rows": [{"pair": candidate["pair"], "ok": True}]},
        )
        self.assertFalse(validation.ok)
        self.assertIn("candidate_status_blocked:blocked_strategy_edge_not_established", validation.errors)
        self.assertTrue(any(e.startswith("edge_guard_ok_required") for e in validation.errors))

    def test_confirmation_string_binds_to_candidate_fingerprint(self):
        candidate = ready_candidate()
        fp = candidate_fingerprint(candidate)
        self.assertEqual(required_confirmation(candidate), f"{ACK_PREFIX}{fp}")
        mutated = dict(candidate, validation_pnl_krw=101)
        self.assertNotEqual(candidate_fingerprint(mutated), fp)

    def test_fresh_orderbook_and_payload_plan(self):
        candidate = ready_candidate()
        orderbooks = {
            "204620": {"result": {"asks": [{"price": "4695", "volume": "100"}], "bids": [{"price": "4685", "volume": "100"}]}},
            "032620": {"result": {"asks": [{"price": "2800", "volume": "100"}], "bids": [{"price": "2795", "volume": "100"}]}},
        }
        errors, warnings, details = validate_fresh_orderbooks(candidate, orderbooks)
        self.assertEqual(errors, [])
        self.assertTrue(all(w.startswith("orderbook_timestamp_missing") for w in warnings))
        self.assertIn("204620", details)
        payloads = build_buy_limit_payloads(candidate, orderbooks, client_order_id_prefix="test", limit_buffer_bps=Decimal("0"))
        self.assertEqual(payloads[0]["symbol"], "204620")
        self.assertEqual(payloads[0]["quantity"], "1")
        self.assertEqual(payloads[0]["price"], "4695")
        self.assertEqual(payloads[1]["symbol"], "032620")
        self.assertEqual(payloads[1]["quantity"], "1")
        self.assertEqual(payloads[1]["price"], "2800")


if __name__ == "__main__":
    unittest.main()
