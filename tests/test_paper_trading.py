import os
import tempfile
import unittest
from decimal import Decimal

from toss_auto_trader import db
from toss_auto_trader.collector import decide_from_recent_prices
from toss_auto_trader.paper import PaperBroker
from toss_auto_trader.strategy import moving_average_guarded
from toss_auto_trader.toss_client import TossInvestClient
from toss_auto_trader.config import Settings


class PaperTradingTests(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".sqlite3")
        os.close(fd)
        os.unlink(self.path)
        db.init_db(self.path)

    def tearDown(self):
        if os.path.exists(self.path):
            os.unlink(self.path)

    def test_moving_average_buy_signal(self):
        signal = moving_average_guarded(
            "005930",
            [Decimal("100"), Decimal("101"), Decimal("102"), Decimal("104"), Decimal("106")],
            Decimal("1000"),
        )
        self.assertEqual(signal.side, "BUY")

    def test_paper_buy_updates_cash_and_position(self):
        broker = PaperBroker(self.path, initial_cash_krw=Decimal("10000"))
        status = broker.buy("005930", Decimal("1000"), Decimal("3000"), "unit test")
        self.assertEqual(status, "FILLED_BUY")
        self.assertEqual(broker.cash(), Decimal("7000"))
        qty, avg = broker.position("005930")
        self.assertEqual(qty, Decimal("3"))
        self.assertEqual(avg, Decimal("1000"))

    def test_paper_buy_respects_max_order(self):
        broker = PaperBroker(self.path, initial_cash_krw=Decimal("10000"), max_order_krw=Decimal("3000"))
        status = broker.buy("005930", Decimal("1000"), Decimal("4000"), "too large")
        self.assertEqual(status, "REJECTED_MAX_ORDER")
        self.assertEqual(broker.cash(), Decimal("10000"))

    def test_paper_buy_respects_daily_order_limit(self):
        broker = PaperBroker(self.path, initial_cash_krw=Decimal("10000"), daily_max_orders=1)
        self.assertEqual(broker.buy("005930", Decimal("1000"), Decimal("1000"), "first"), "FILLED_BUY")
        self.assertEqual(broker.buy("005930", Decimal("1000"), Decimal("1000"), "second"), "REJECTED_DAILY_ORDER_LIMIT")

    def test_paper_uses_simulated_date_for_daily_limit(self):
        broker = PaperBroker(self.path, initial_cash_krw=Decimal("10000"), daily_max_orders=1, simulated_now="2026-01-01T09:00:00+09:00")
        self.assertEqual(broker.buy("005930", Decimal("1000"), Decimal("1000"), "day1"), "FILLED_BUY")
        self.assertEqual(broker.buy("005930", Decimal("1000"), Decimal("1000"), "day1 second"), "REJECTED_DAILY_ORDER_LIMIT")
        broker.simulated_now = "2026-01-02T09:00:00+09:00"
        self.assertEqual(broker.buy("005930", Decimal("1000"), Decimal("1000"), "day2"), "FILLED_BUY")
        with db.connect(self.path) as con:
            days = [r[0][:10] for r in con.execute("SELECT created_at FROM paper_orders ORDER BY id").fetchall()]
        self.assertEqual(days, ["2026-01-01", "2026-01-02"])

    def test_paper_cash_reflects_fees_and_tax(self):
        broker = PaperBroker(
            self.path,
            initial_cash_krw=Decimal("10000"),
            buy_commission_pct=Decimal("0.01"),
            sell_commission_pct=Decimal("0.01"),
            sell_tax_pct=Decimal("0.02"),
        )
        self.assertEqual(broker.buy("005930", Decimal("1000"), Decimal("3000"), "fee buy"), "FILLED_BUY")
        self.assertEqual(broker.cash(), Decimal("6970.00"))
        self.assertEqual(broker.sell("005930", Decimal("1000"), Decimal("3"), "fee sell"), "FILLED_SELL")
        self.assertEqual(broker.cash(), Decimal("9880.00"))
        with db.connect(self.path) as con:
            rows = con.execute("SELECT side, fee_amount, tax_amount FROM paper_orders ORDER BY id").fetchall()
        self.assertEqual(rows[0]["fee_amount"], "30.00")
        self.assertEqual(rows[0]["tax_amount"], "0")
        self.assertEqual(rows[1]["fee_amount"], "30.00")
        self.assertEqual(rows[1]["tax_amount"], "60.00")

    def test_paper_cash_reflects_slippage(self):
        broker = PaperBroker(
            self.path,
            initial_cash_krw=Decimal("10000"),
            buy_slippage_pct=Decimal("0.01"),
            sell_slippage_pct=Decimal("0.01"),
        )
        self.assertEqual(broker.buy("005930", Decimal("1000"), Decimal("3000"), "slip buy"), "FILLED_BUY")
        qty, avg = broker.position("005930")
        self.assertEqual(qty, Decimal("2"))
        self.assertEqual(avg, Decimal("1010.00"))
        self.assertEqual(broker.cash(), Decimal("7980.00"))
        self.assertEqual(broker.sell("005930", Decimal("1000"), Decimal("2"), "slip sell"), "FILLED_SELL")
        self.assertEqual(broker.cash(), Decimal("9960.00"))

    def test_decision_is_logged(self):
        for price in ["100", "101", "102", "104", "106"]:
            db.insert_price(
                self.path,
                {"symbol": "005930", "timestamp": db.utc_now(), "lastPrice": price, "currency": "KRW"},
                source="test",
            )
        signal = decide_from_recent_prices(self.path, "005930", Decimal("1000"))
        self.assertEqual(signal.side, "BUY")
        self.assertEqual(db.summary(self.path)["decision_count"], 1)

    def test_live_order_is_guarded_by_default(self):
        client = TossInvestClient(Settings(dry_run=True, live_trading=False))
        result = client.create_order("1", {"symbol": "005930", "side": "BUY", "orderType": "MARKET", "quantity": "1"})
        self.assertTrue(result["dryRun"])

    def test_order_payload_rejects_legacy_market_shape(self):
        with self.assertRaisesRegex(ValueError, "orderType"):
            TossInvestClient.validate_order_payload({"symbol": "005930", "side": "BUY", "type": "MARKET", "quantity": "1", "price": "0"})
        with self.assertRaisesRegex(ValueError, "must not include price"):
            TossInvestClient.validate_order_payload({"symbol": "005930", "side": "BUY", "orderType": "MARKET", "quantity": "1", "price": "0"})

    def test_get_order_uses_official_order_detail_endpoint(self):
        class FakeClient(TossInvestClient):
            def __init__(self):
                super().__init__(Settings(account_seq="1"))
                self.call = None

            def request_json(self, method, path, *, params=None, headers=None, payload=None):
                self.call = (method, path, params, headers, payload)
                return {"result": {"orderId": "ORD/1"}}

        client = FakeClient()
        result = client.get_order("ORD/1")
        self.assertIsNotNone(client.call)
        assert client.call is not None
        self.assertEqual(result["result"]["orderId"], "ORD/1")
        self.assertEqual(client.call[0], "GET")
        self.assertEqual(client.call[1], "/api/v1/orders/ORD%2F1")
        self.assertEqual(client.call[3], {"X-Tossinvest-Account": "1"})

    def test_market_indicator_methods_use_official_endpoints(self):
        class FakeClient(TossInvestClient):
            def __init__(self):
                super().__init__(Settings(account_seq="1", dry_run=False, live_trading=True))
                self.calls = []

            def request_json(self, method, path, *, params=None, headers=None, payload=None):
                self.calls.append((method, path, params, headers, payload))
                return {"result": []}

        client = FakeClient()
        client.get_market_indicator_prices(["KOSDAQ"])
        client.get_market_indicator_candles("KOSDAQ", "1d", count=6)

        self.assertEqual(client.calls[0][:3], ("GET", "/api/v1/market-indicators/prices", {"symbols": "KOSDAQ"}))
        self.assertEqual(
            client.calls[1][:3],
            ("GET", "/api/v1/market-indicators/KOSDAQ/candles", {"interval": "1d", "count": 6, "before": None}),
        )

    def test_cancel_and_modify_order_use_official_endpoints(self):
        class FakeClient(TossInvestClient):
            def __init__(self):
                super().__init__(Settings(account_seq="1", dry_run=False, live_trading=True))
                self.calls = []

            def request_json(self, method, path, *, params=None, headers=None, payload=None):
                self.calls.append((method, path, params, headers, payload))
                return {"result": {"orderId": "NEW"}}

        client = FakeClient()
        client.cancel_order("1", "ORD/1")
        client.modify_order("1", "ORD/1", {"orderType": "MARKET", "quantity": "2"})

        self.assertEqual(client.calls[0][0:2], ("POST", "/api/v1/orders/ORD%2F1/cancel"))
        self.assertEqual(client.calls[0][3], {"X-Tossinvest-Account": "1"})
        self.assertEqual(client.calls[1][0:2], ("POST", "/api/v1/orders/ORD%2F1/modify"))
        self.assertEqual(client.calls[1][4], {"orderType": "MARKET", "quantity": "2"})


if __name__ == "__main__":
    unittest.main()
