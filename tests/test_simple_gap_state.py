import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from toss_auto_trader import simple_gap_state


KST = timezone(timedelta(hours=9))
NOW = datetime(2026, 7, 17, 9, 2, tzinfo=KST)


def order_detail(*, order_id, side, status, quantity, filled_quantity, average_price=None):
    return {
        "result": {
            "orderId": order_id,
            "symbol": "123456",
            "side": side,
            "status": status,
            "quantity": str(quantity),
            "orderedAt": "2026-07-17T09:01:20+09:00",
            "execution": {
                "filledQuantity": str(filled_quantity),
                "averageFilledPrice": str(average_price) if average_price is not None else None,
                "filledAmount": str(filled_quantity * average_price) if average_price is not None else None,
            },
        }
    }


class SimpleGapStateTests(unittest.TestCase):
    def new_state(self):
        state = simple_gap_state.new_buy_state(
            strategy_name="robust_gap5_stop0225_take12",
            trade_date="2026-07-17",
            symbol="123456",
            name="테스트",
            client_order_id="sg-202607170901-B-123456",
            requested_quantity=5,
            limit_price=1000,
            order_payload={
                "clientOrderId": "sg-202607170901-B-123456",
                "symbol": "123456",
                "side": "BUY",
                "orderType": "LIMIT",
                "timeInForce": "DAY",
                "quantity": "5",
                "price": "1000",
            },
            now=NOW,
        )
        state["buy"]["order_id"] = "BUY-1"
        state["buy"]["status"] = "SUBMITTED"
        return state

    def test_state_round_trip_and_corruption_fail_closed(self):
        state = self.new_state()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.json"
            simple_gap_state.save_state(path, state)
            self.assertEqual(simple_gap_state.load_state(path, strategy_name=state["strategy_name"]), state)
            path.write_text("{broken", encoding="utf-8")
            with self.assertRaises(simple_gap_state.StrategyStateError):
                simple_gap_state.load_state(path, strategy_name=state["strategy_name"])

    def test_partial_buy_fill_is_owned_but_remains_pending(self):
        state = self.new_state()
        snapshot = simple_gap_state.order_snapshot(
            order_detail(order_id="BUY-1", side="BUY", status="PARTIAL_FILLED", quantity=5, filled_quantity=2, average_price=1001)
        )

        state = simple_gap_state.apply_buy_snapshot(state, snapshot, now=NOW)

        self.assertEqual(state["status"], "BUY_PARTIAL_PENDING")
        self.assertEqual(state["position"]["opened_quantity"], 2)
        self.assertEqual(state["position"]["remaining_quantity"], 2)
        self.assertEqual(state["position"]["entry_price"], 1001)

    def test_partial_and_full_sell_reconciliation_updates_only_owned_quantity(self):
        state = self.new_state()
        buy = simple_gap_state.order_snapshot(
            order_detail(order_id="BUY-1", side="BUY", status="FILLED", quantity=5, filled_quantity=5, average_price=1000)
        )
        state = simple_gap_state.apply_buy_snapshot(state, buy, now=NOW)
        state = simple_gap_state.add_sell_order(
            state,
            order_id="SELL-1",
            client_order_id="sg-202607170902-S-123456",
            trigger="손절",
            requested_quantity=5,
            observed_price=970,
            trigger_price=977.5,
            order_payload={
                "clientOrderId": "sg-202607170902-S-123456",
                "symbol": "123456",
                "side": "SELL",
                "orderType": "MARKET",
                "timeInForce": "DAY",
                "quantity": "5",
            },
            now=NOW,
        )
        partial = simple_gap_state.order_snapshot(
            order_detail(order_id="SELL-1", side="SELL", status="PARTIAL_FILLED", quantity=5, filled_quantity=2, average_price=969)
        )
        state = simple_gap_state.apply_sell_snapshot(state, partial, now=NOW)

        self.assertEqual(state["status"], "EXIT_PENDING")
        self.assertEqual(state["position"]["remaining_quantity"], 3)

        full = simple_gap_state.order_snapshot(
            order_detail(order_id="SELL-1", side="SELL", status="FILLED", quantity=5, filled_quantity=5, average_price=968)
        )
        state = simple_gap_state.apply_sell_snapshot(state, full, now=NOW)

        self.assertEqual(state["status"], "CLOSED")
        self.assertEqual(state["position"]["remaining_quantity"], 0)

    def test_only_terminal_state_allows_next_buy(self):
        state = self.new_state()
        self.assertFalse(simple_gap_state.state_allows_new_buy(state))
        state["status"] = "CLOSED_NO_FILL"
        self.assertTrue(simple_gap_state.state_allows_new_buy(state))
        self.assertFalse(simple_gap_state.state_allows_new_buy(state, trade_date="2026-07-17"))
        self.assertTrue(simple_gap_state.state_allows_new_buy(state, trade_date="2026-07-20"))
        self.assertTrue(simple_gap_state.state_allows_new_buy(None))

    def test_unknown_sell_status_fails_closed_and_stays_trackable(self):
        state = self.new_state()
        buy = simple_gap_state.order_snapshot(
            order_detail(order_id="BUY-1", side="BUY", status="FILLED", quantity=5, filled_quantity=5, average_price=1000)
        )
        state = simple_gap_state.apply_buy_snapshot(state, buy, now=NOW)
        state = simple_gap_state.add_sell_order(
            state,
            order_id="SELL-UNKNOWN",
            client_order_id="sg-202607170902-S-123456",
            trigger="손절",
            requested_quantity=5,
            observed_price=970,
            trigger_price=977.5,
            order_payload={
                "clientOrderId": "sg-202607170902-S-123456",
                "symbol": "123456",
                "side": "SELL",
                "orderType": "MARKET",
                "timeInForce": "DAY",
                "quantity": "5",
            },
            now=NOW,
        )
        unknown = simple_gap_state.order_snapshot(
            order_detail(order_id="SELL-UNKNOWN", side="SELL", status="BROKER_REVIEW", quantity=5, filled_quantity=0)
        )

        state = simple_gap_state.apply_sell_snapshot(state, unknown, now=NOW)

        self.assertEqual(state["status"], "EXIT_STATUS_UNKNOWN")
        self.assertEqual([row["order_id"] for row in simple_gap_state.active_sell_orders(state)], ["SELL-UNKNOWN"])


if __name__ == "__main__":
    unittest.main()
