import importlib.util
import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch


def load_simple_gap_trader():
    path = Path(__file__).resolve().parents[1] / "scripts" / "simple_gap_trader.py"
    spec = importlib.util.spec_from_file_location("simple_gap_trader", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeSettings:
    account_seq = "acct"


class FakeClient:
    def __init__(self, response=None, exc=None):
        self.response = response
        self.exc = exc

    def get_buying_power(self, account_seq):
        if self.exc:
            raise self.exc
        return self.response


class FakeMonitorClient:
    def __init__(
        self,
        *,
        holdings,
        prices,
        open_orders=None,
        bid_price="976",
        holdings_key="holdings",
        dry_run=True,
    ):
        self.holdings = holdings
        self.holdings_key = holdings_key
        self.prices = prices
        self.open_orders = open_orders or []
        self.bid_price = bid_price
        self.dry_run = dry_run
        self.created_orders = []

    def get_holdings(self, account_seq):
        return {"result": {self.holdings_key: self.holdings}}

    def get_prices(self, symbols):
        return {"result": [{"symbol": symbol, "lastPrice": self.prices[symbol]} for symbol in symbols]}

    def get_orders(self, account_seq, status="OPEN", symbol=None):
        return {"result": {"orders": self.open_orders}}

    def get_orderbook(self, symbol):
        return {"result": {"bids": [{"price": self.bid_price}], "asks": [{"price": "980"}]}}

    def create_order(self, account_seq, payload):
        self.created_orders.append(payload)
        if self.dry_run:
            return {"dryRun": True, "wouldSend": payload}
        return {"result": {"orderId": "ORD-STOP"}}


class SimpleGapTraderTests(unittest.TestCase):
    def tearDown(self):
        os.environ.pop("TOSS_MAX_BUY_AMOUNT_KRW", None)

    def test_budget_reads_cash_buying_power(self):
        mod = load_simple_gap_trader()
        budget = mod.get_actual_budget(
            FakeClient({"result": {"cashBuyingPower": "12,345"}}),
            FakeSettings(),
        )
        self.assertEqual(budget, 12345.0)

    def test_budget_falls_back_to_amount_field(self):
        mod = load_simple_gap_trader()
        budget = mod.get_actual_budget(
            FakeClient({"result": {"amount": "12,345"}}),
            FakeSettings(),
        )
        self.assertEqual(budget, 12345.0)

    def test_budget_optional_env_cap(self):
        os.environ["TOSS_MAX_BUY_AMOUNT_KRW"] = "10,000"
        mod = load_simple_gap_trader()
        budget = mod.get_actual_budget(
            FakeClient({"result": {"cashBuyingPower": "12,345"}}),
            FakeSettings(),
        )
        self.assertEqual(budget, 10000.0)

    def test_budget_fail_closed_on_api_error(self):
        mod = load_simple_gap_trader()
        budget = mod.get_actual_budget(
            FakeClient(exc=RuntimeError("boom")),
            FakeSettings(),
        )
        self.assertEqual(budget, 0.0)

    def test_limit_order_payload_matches_official_toss_schema(self):
        mod = load_simple_gap_trader()
        payload = mod.build_limit_quantity_order("091590", "BUY", 1, 7660, now=datetime(2026, 7, 1, 9, 1))
        self.assertEqual(payload["symbol"], "091590")
        self.assertEqual(payload["side"], "BUY")
        self.assertEqual(payload["orderType"], "LIMIT")
        self.assertEqual(payload["timeInForce"], "DAY")
        self.assertEqual(payload["quantity"], "1")
        self.assertEqual(payload["price"], "7660")
        self.assertEqual(payload["clientOrderId"], "sg-202607010901-B-091590")
        self.assertNotIn("type", payload)

    def test_extract_order_id_reads_nested_result_and_ignores_none_text(self):
        mod = load_simple_gap_trader()

        self.assertEqual(mod.extract_order_id({"result": {"orderId": "ORD-1"}}), "ORD-1")
        self.assertEqual(mod.extract_order_id({"result": {"id": "ORD-2"}}), "ORD-2")
        self.assertIsNone(mod.extract_order_id({"orderId": None}))
        self.assertIsNone(mod.extract_order_id({"orderId": "None"}))

    def test_live_strategy_constants_match_robust_gap_candidate(self):
        mod = load_simple_gap_trader()
        self.assertEqual(mod.MIN_PRICE, 1000)
        self.assertEqual(mod.MAX_PRICE, 8000)
        self.assertEqual(mod.GAP_THRESHOLD, -0.05)
        self.assertEqual(mod.PREV_VOL_RATIO_MAX, 0.8)
        self.assertEqual(mod.STOP_LOSS_PCT, 0.0225)
        self.assertEqual(mod.TAKE_PROFIT_PCT, 0.12)
        self.assertEqual(mod.KOSDAQ_SMA5_BUY_RATIO, 0.99)

    def test_market_gate_allows_when_kosdaq_is_one_percent_below_sma5(self):
        mod = load_simple_gap_trader()

        with patch.object(mod, "fetch_kosdaq_index", return_value=[100.0, 100.0, 100.0, 100.0, 98.0]):
            self.assertTrue(mod.check_market_gate())

    def test_market_gate_blocks_when_kosdaq_is_not_one_percent_below_sma5(self):
        mod = load_simple_gap_trader()

        with patch.object(mod, "fetch_kosdaq_index", return_value=[100.0, 100.0, 100.0, 100.0, 99.0]):
            self.assertFalse(mod.check_market_gate())

    def test_warning_filter_blocks_investment_warning_and_overheated(self):
        mod = load_simple_gap_trader()
        resp = {"result": [{"warningType": "OVERHEATED"}, {"warningType": "INVESTMENT_WARNING"}]}
        self.assertEqual(mod.extract_blocking_warnings(resp), ["OVERHEATED", "INVESTMENT_WARNING"])

    def test_warning_filter_fail_closed_on_api_error(self):
        mod = load_simple_gap_trader()

        class WarningErrorClient:
            def get_stock_warnings(self, symbol):
                raise RuntimeError("network down")

        with patch.object(mod, "naver_warning_badges", return_value=[]):
            warnings = mod.blocking_warnings_for_symbol(WarningErrorClient(), "000000")
        self.assertTrue(warnings[0].startswith("TOSS_WARNING_CHECK_FAILED:RuntimeError"))

    def test_today_open_price_uses_daily_candle_not_last_price(self):
        mod = load_simple_gap_trader()

        class CandleClient:
            def get_candles(self, symbol, interval="1d", count=100, before=None, adjusted=True):
                return {
                    "result": {
                        "candles": [
                            {"timestamp": "2026-07-01T00:00:00+09:00", "openPrice": "1279", "closePrice": "1066"}
                        ]
                    }
                }

        self.assertEqual(mod.get_today_open_price(CandleClient(), "056090", today="2026-07-01"), 1279)

    def test_today_open_price_returns_none_when_today_missing(self):
        mod = load_simple_gap_trader()

        class CandleClient:
            def get_candles(self, symbol, interval="1d", count=100, before=None, adjusted=True):
                return {"result": {"candles": [{"timestamp": "2026-06-30T00:00:00+09:00", "openPrice": "100"}]}}

        self.assertIsNone(mod.get_today_open_price(CandleClient(), "056090", today="2026-07-01"))
    def test_naver_badge_blocks_investment_caution_missing_from_toss_api(self):
        mod = load_simple_gap_trader()

        class CleanTossClient:
            def get_stock_warnings(self, symbol):
                return {"result": []}

        with patch.object(mod, "naver_warning_badges", return_value=["투자주의"]):
            warnings = mod.blocking_warnings_for_symbol(CleanTossClient(), "217190")
        self.assertEqual(warnings, ["NAVER_BADGE:투자주의"])

    def test_naver_badge_parser_reads_header_caution_only(self):
        mod = load_simple_gap_trader()
        html = b'<html><em class="caution"> <span class="blind">\xed\x88\xac\xec\x9e\x90\xec\xa3\xbc\xec\x9d\x98</span></em><a>\xed\x88\xac\xec\x9e\x90\xec\xa3\xbc\xec\x9d\x98</a></html>'

        class FakeResponse:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def read(self):
                return html

        with patch.object(mod.urllib.request, "urlopen", return_value=FakeResponse()):
            self.assertEqual(mod.naver_warning_badges("217190"), ["투자주의"])

    def test_best_limit_price_uses_ask_for_buy_bid_for_sell(self):
        mod = load_simple_gap_trader()

        class OrderbookClient:
            def get_orderbook(self, symbol):
                return {"result": {"asks": [{"price": "72300"}, {"price": "72100"}], "bids": [{"price": "72000"}, {"price": "71900"}]}}

        self.assertEqual(mod.best_limit_price(OrderbookClient(), "005930", "BUY", 70000), 72100)
        self.assertEqual(mod.best_limit_price(OrderbookClient(), "005930", "SELL", 70000), 72000)

    def test_monitor_sends_stop_loss_sell_when_price_crosses_stop(self):
        mod = load_simple_gap_trader()
        client = FakeMonitorClient(
            holdings=[{"symbol": "123456", "name": "테스트", "quantity": "1", "averagePrice": "1000"}],
            prices={"123456": "977"},
            bid_price="976",
        )

        mod.run_monitor(client, FakeSettings())

        self.assertEqual(len(client.created_orders), 1)
        self.assertEqual(client.created_orders[0]["side"], "SELL")
        self.assertEqual(client.created_orders[0]["symbol"], "123456")
        self.assertEqual(client.created_orders[0]["quantity"], "1")
        self.assertEqual(client.created_orders[0]["price"], "976")

    def test_monitor_sends_discord_alert_after_live_stop_loss_order(self):
        mod = load_simple_gap_trader()
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "reentry.jsonl"
            client = FakeMonitorClient(
                holdings=[{"symbol": "123456", "name": "테스트", "quantity": "1", "averagePrice": "1000"}],
                prices={"123456": "977"},
                bid_price="976",
                dry_run=False,
            )
            sent_messages = []

            def fake_send(message):
                sent_messages.append(message)
                return True

            with (
                patch.object(mod, "PAPER_REENTRY_LOG", log_path),
                patch.object(mod, "send_discord_message", side_effect=fake_send),
            ):
                mod.run_monitor(client, FakeSettings())

        self.assertEqual(len(sent_messages), 1)
        self.assertIn("장중 손절 알림", sent_messages[0])
        self.assertIn("테스트(123456)", sent_messages[0])
        self.assertIn("수익률: -2.30%", sent_messages[0])
        self.assertIn("주문ID: ORD-STOP", sent_messages[0])
        self.assertNotIn("acct", sent_messages[0])

    def test_monitor_does_not_send_discord_alert_for_dry_run_order(self):
        mod = load_simple_gap_trader()
        client = FakeMonitorClient(
            holdings=[{"symbol": "123456", "name": "테스트", "quantity": "1", "averagePrice": "1000"}],
            prices={"123456": "977"},
            bid_price="976",
            dry_run=True,
        )

        with patch.object(mod, "send_discord_message", side_effect=AssertionError("dry-run must not notify")):
            mod.run_monitor(client, FakeSettings())

    def test_monitor_skips_sell_when_open_sell_order_exists(self):
        mod = load_simple_gap_trader()
        client = FakeMonitorClient(
            holdings=[{"symbol": "123456", "name": "테스트", "quantity": "1", "averagePrice": "1000"}],
            prices={"123456": "977"},
            open_orders=[{"side": "SELL"}],
        )

        mod.run_monitor(client, FakeSettings())

        self.assertEqual(client.created_orders, [])

    def test_monitor_reads_toss_items_holdings_shape(self):
        mod = load_simple_gap_trader()
        client = FakeMonitorClient(
            holdings=[{"symbol": "123456", "name": "테스트", "quantity": "1", "averagePurchasePrice": "1000"}],
            prices={"123456": "977"},
            bid_price="976",
            holdings_key="items",
        )

        mod.run_monitor(client, FakeSettings())

        self.assertEqual(len(client.created_orders), 1)
        self.assertEqual(client.created_orders[0]["symbol"], "123456")


if __name__ == "__main__":
    unittest.main()
