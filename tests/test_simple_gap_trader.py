import importlib.util
import os
import unittest
from datetime import datetime
from pathlib import Path


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

    def test_market_order_payload_matches_official_toss_schema(self):
        mod = load_simple_gap_trader()
        payload = mod.build_market_quantity_order("091590", "BUY", 1, now=datetime(2026, 7, 1, 9, 1))
        self.assertEqual(payload["symbol"], "091590")
        self.assertEqual(payload["side"], "BUY")
        self.assertEqual(payload["orderType"], "MARKET")
        self.assertEqual(payload["timeInForce"], "DAY")
        self.assertEqual(payload["quantity"], "1")
        self.assertEqual(payload["clientOrderId"], "sg-202607010901-B-091590")
        self.assertNotIn("type", payload)
        self.assertNotIn("price", payload)


if __name__ == "__main__":
    unittest.main()
