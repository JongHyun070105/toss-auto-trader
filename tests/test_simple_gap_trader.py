import importlib.util
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from toss_auto_trader.toss_client import TossApiError


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


class LiveSettings:
    account_seq = "acct"
    live_trading = True
    dry_run = False


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
        created_order_status="FILLED",
    ):
        self.holdings = holdings
        self.holdings_key = holdings_key
        self.prices = prices
        self.open_orders = open_orders or []
        self.bid_price = bid_price
        self.dry_run = dry_run
        self.created_order_status = created_order_status
        self.created_orders = []
        self.order_details = {}
        self.cancelled_orders = []
        self.modified_orders = []

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
        order_id = "ORD-STOP"
        filled_quantity = payload["quantity"] if self.created_order_status == "FILLED" else "0"
        self.order_details[order_id] = {
            "result": {
                "orderId": order_id,
                "symbol": payload["symbol"],
                "side": payload["side"],
                "status": self.created_order_status,
                "quantity": payload["quantity"],
                "orderedAt": "2026-07-17T09:02:00+09:00",
                "execution": {
                    "filledQuantity": filled_quantity,
                    "averageFilledPrice": self.bid_price if filled_quantity != "0" else None,
                    "filledAmount": str(int(float(self.bid_price)) * int(float(filled_quantity))) if filled_quantity != "0" else None,
                },
            }
        }
        return {"result": {"orderId": order_id}}

    def get_order(self, order_id, account_seq=None):
        return self.order_details[order_id]

    def cancel_order(self, account_seq, order_id):
        self.cancelled_orders.append(order_id)
        return {"result": {"orderId": f"CANCEL-{order_id}"}}

    def modify_order(self, account_seq, order_id, payload):
        self.modified_orders.append((order_id, payload))
        return {"result": {"orderId": f"MOD-{order_id}"}}


KST = timezone(timedelta(hours=9))


def open_position_state(*, symbol="123456", name="테스트", quantity=1, entry_price=1000.0):
    return {
        "version": 1,
        "strategy_name": "robust_gap5_stop0225_take12",
        "trade_date": "2026-07-17",
        "status": "POSITION_OPEN",
        "symbol": symbol,
        "name": name,
        "buy": {
            "order_id": "BUY-1",
            "client_order_id": "sg-202607170901-B-123456",
            "requested_quantity": quantity,
            "limit_price": entry_price,
            "status": "FILLED",
            "filled_quantity": quantity,
            "average_filled_price": entry_price,
        },
        "position": {
            "opened_quantity": quantity,
            "remaining_quantity": quantity,
            "entry_price": entry_price,
        },
        "sell_orders": [],
        "exit_recorded": False,
        "updated_at": "2026-07-17T09:02:00+09:00",
    }


def write_state(path: Path, state: dict) -> None:
    path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")


class FakeMarketClient:
    def __init__(
        self,
        *,
        current="98",
        timestamp="2026-07-17T09:01:00+09:00",
        include_today=True,
        trading_day=True,
        regular_start="2026-07-17T09:00:00+09:00",
        candle_current=None,
        open_price="98",
        minute_close=None,
        include_first_minute=True,
    ):
        self.current = current
        self.timestamp = timestamp
        self.include_today = include_today
        self.trading_day = trading_day
        self.regular_start = regular_start
        self.candle_current = candle_current
        self.open_price = open_price
        self.minute_close = current if minute_close is None else minute_close
        self.include_first_minute = include_first_minute

    def get_market_calendar(self, country="KR", date=None):
        return {
            "result": {
                "today": {
                    "date": "2026-07-17",
                    "integrated": {
                        "regularMarket": {
                            "startTime": self.regular_start,
                            "endTime": "2026-07-17T15:30:00+09:00",
                        }
                    } if self.trading_day else None,
                },
                "previousBusinessDay": {"date": "2026-07-16", "integrated": {}},
            }
        }

    def get_market_indicator_prices(self, symbols):
        return {"result": [{"symbol": "KOSDAQ", "timestamp": self.timestamp, "lastPrice": self.current}]}

    def get_market_indicator_candles(self, symbol, interval="1d", count=100, before=None):
        if interval == "1m":
            if not self.include_first_minute:
                return {"result": {"candles": []}}
            return {
                "result": {
                    "candles": [
                        {
                            "timestamp": "2026-07-17T09:01:00+09:00",
                            "openPrice": self.open_price,
                            "closePrice": self.minute_close,
                        }
                    ]
                }
            }
        candles = [
            {"timestamp": "2026-07-16T09:00:00+09:00", "openPrice": "100", "closePrice": "100"},
            {"timestamp": "2026-07-15T09:00:00+09:00", "openPrice": "100", "closePrice": "100"},
            {"timestamp": "2026-07-14T09:00:00+09:00", "openPrice": "100", "closePrice": "100"},
            {"timestamp": "2026-07-13T09:00:00+09:00", "openPrice": "100", "closePrice": "100"},
            {"timestamp": "2026-07-10T09:00:00+09:00", "openPrice": "100", "closePrice": "100"},
        ]
        if self.include_today:
            close_price = self.current if self.candle_current is None else self.candle_current
            candles.insert(
                0,
                {
                    "timestamp": "2026-07-17T09:00:00+09:00",
                    "openPrice": self.open_price,
                    "closePrice": close_price,
                },
            )
        return {"result": {"candles": candles}}


class SimpleGapTraderTests(unittest.TestCase):
    def tearDown(self):
        os.environ.pop("TOSS_MAX_BUY_AMOUNT_KRW", None)

    def test_budget_reads_cash_buying_power(self):
        mod = load_simple_gap_trader()
        budget = mod.get_actual_budget(
            FakeClient({"result": {"cashBuyingPower": "12,345"}}),
            FakeSettings(),
        )
        self.assertEqual(budget, 10000.0)

    def test_budget_falls_back_to_amount_field(self):
        mod = load_simple_gap_trader()
        budget = mod.get_actual_budget(
            FakeClient({"result": {"amount": "12,345"}}),
            FakeSettings(),
        )
        self.assertEqual(budget, 10000.0)

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

    def test_request_in_progress_is_ambiguous_not_rejected(self):
        mod = load_simple_gap_trader()
        exc = TossApiError(
            409,
            "Conflict",
            '{"error":{"code":"request-in-progress","message":"processing"}}',
        )

        self.assertTrue(mod.submission_error_is_ambiguous(exc))

    def test_live_strategy_constants_match_robust_gap_candidate(self):
        mod = load_simple_gap_trader()
        self.assertEqual(mod.MIN_PRICE, 1000)
        self.assertEqual(mod.MAX_PRICE, 8000)
        self.assertEqual(mod.GAP_THRESHOLD, -0.05)
        self.assertEqual(mod.MIN_RAW_ENTRY_GAP, -0.31)
        self.assertEqual(mod.PREV_VOL_RATIO_MAX, 0.8)
        self.assertEqual(mod.STOP_LOSS_PCT, 0.0225)
        self.assertEqual(mod.TAKE_PROFIT_PCT, 0.12)
        self.assertEqual(mod.KOSDAQ_SMA5_BUY_RATIO, 0.99)
        self.assertEqual(mod.MAX_BUY_CHASE_PCT, 0.005)
        self.assertEqual(mod.PREVIOUS_CLOSE_BASIS_MAX_PCT, 0.001)
        self.assertEqual(mod.MAX_BUY_AMOUNT_KRW, 10000)

    def test_market_gate_allows_when_kosdaq_is_one_percent_below_sma5(self):
        mod = load_simple_gap_trader()
        now = datetime(2026, 7, 17, 9, 1, tzinfo=KST)

        self.assertTrue(mod.check_market_gate(FakeMarketClient(current="98"), now=now))

    def test_market_gate_blocks_when_kosdaq_open_is_not_one_percent_below_sma5(self):
        mod = load_simple_gap_trader()
        now = datetime(2026, 7, 17, 9, 1, tzinfo=KST)

        self.assertFalse(mod.check_market_gate(FakeMarketClient(current="99", open_price="99"), now=now))

    def test_market_gate_uses_open_and_keeps_current_value_as_shadow(self):
        mod = load_simple_gap_trader()
        now = datetime(2026, 7, 17, 9, 1, tzinfo=KST)

        snapshot = mod.fetch_kosdaq_market_data(
            FakeMarketClient(current="95", open_price="99"),
            now=now,
        )

        self.assertIsNotNone(snapshot)
        self.assertFalse(mod.evaluate_market_gate(snapshot))
        self.assertGreater(snapshot.open_price, snapshot.buy_line)
        self.assertLessEqual(snapshot.current_index, snapshot.current_buy_line)

    def test_fetch_kosdaq_index_keeps_closes_only_compatibility(self):
        mod = load_simple_gap_trader()

        with patch.object(mod, "fetch_naver_kosdaq_closes", return_value=[98.0, 99.0]):
            self.assertEqual(mod.fetch_kosdaq_index(), [98.0, 99.0])

    def test_market_gate_blocks_stale_or_missing_today_data(self):
        mod = load_simple_gap_trader()
        now = datetime(2026, 7, 17, 9, 1, tzinfo=KST)

        self.assertFalse(mod.check_market_gate(FakeMarketClient(timestamp="2026-07-16T15:30:00+09:00"), now=now))
        self.assertFalse(mod.check_market_gate(FakeMarketClient(include_today=False), now=now))
        self.assertFalse(mod.check_market_gate(FakeMarketClient(include_first_minute=False), now=now))

    def test_market_gate_accepts_missing_indicator_timestamp_after_candle_crosscheck(self):
        mod = load_simple_gap_trader()
        now = datetime(2026, 7, 17, 9, 1, tzinfo=KST)

        snapshot = mod.fetch_kosdaq_market_data(
            FakeMarketClient(current="98", timestamp=None),
            now=now,
        )

        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot.current_index, 98.0)
        self.assertEqual(snapshot.freshness_source, "today_candle_close_crosscheck")

    def test_market_gate_blocks_missing_timestamp_when_candle_price_disagrees(self):
        mod = load_simple_gap_trader()
        now = datetime(2026, 7, 17, 9, 1, tzinfo=KST)

        self.assertIsNone(
            mod.fetch_kosdaq_market_data(
                FakeMarketClient(current="98", timestamp=None, candle_current="97"),
                now=now,
            )
        )

    def test_market_gate_blocks_on_holiday_or_api_error(self):
        mod = load_simple_gap_trader()
        now = datetime(2026, 7, 17, 9, 1, tzinfo=KST)

        self.assertFalse(mod.check_market_gate(FakeMarketClient(trading_day=False), now=now))
        broken = FakeMarketClient()
        broken.get_market_indicator_prices = lambda symbols: (_ for _ in ()).throw(RuntimeError("boom"))
        self.assertFalse(mod.check_market_gate(broken, now=now))

    def test_market_gate_blocks_before_calendar_regular_open(self):
        mod = load_simple_gap_trader()
        now = datetime(2026, 7, 17, 9, 1, tzinfo=KST)

        self.assertFalse(
            mod.check_market_gate(
                FakeMarketClient(regular_start="2026-07-17T10:00:00+09:00"),
                now=now,
            )
        )

    def test_live_buy_is_blocked_outside_0900_to_0905_window(self):
        mod = load_simple_gap_trader()
        late = datetime(2026, 7, 17, 9, 5, tzinfo=KST)

        with (
            patch.object(mod, "load_strategy_state", return_value=None),
            patch.object(mod, "fetch_kosdaq_market_data", side_effect=AssertionError("late live buy must stop before market lookup")),
        ):
            mod.run_buy(FakeMarketClient(), LiveSettings(), now=late)

        self.assertTrue(mod.live_buy_window_allows(LiveSettings(), datetime(2026, 7, 17, 9, 4, 59, tzinfo=KST)))
        self.assertFalse(mod.live_buy_window_allows(LiveSettings(), late))

    def test_market_gate_snapshot_uses_first_minute_open_and_previous_four_closes(self):
        mod = load_simple_gap_trader()
        now = datetime(2026, 7, 17, 9, 1, tzinfo=KST)

        snapshot = mod.fetch_kosdaq_market_data(FakeMarketClient(current="98"), now=now)

        self.assertIsNotNone(snapshot)
        self.assertAlmostEqual(snapshot.current_index, 98.0)
        self.assertAlmostEqual(snapshot.sma5, 99.6)
        self.assertAlmostEqual(snapshot.buy_line, 98.604)
        self.assertAlmostEqual(snapshot.current_sma5, 99.6)
        self.assertAlmostEqual(snapshot.current_buy_line, 98.604)
        self.assertEqual(snapshot.open_timestamp, "2026-07-17T09:01:00+09:00")
        self.assertEqual(snapshot.previous_business_day, "2026-07-16")

    def test_provisional_gap_prefilter_keeps_candidates_that_can_pass_chase_guard(self):
        mod = load_simple_gap_trader()

        self.assertAlmostEqual(mod.provisional_gap_threshold(), -0.04525)

    def test_breadth_shadow_collects_extra_symbols_without_changing_live_rule(self):
        mod = load_simple_gap_trader()

        class QuoteOnlyClient:
            def get_prices(self, symbols):
                self.requested = list(symbols)
                return {"result": [{"symbol": "B", "lastPrice": "1,880"}]}

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "candles.sqlite3"
            log_path = Path(tmp) / "breadth.jsonl"
            connection = sqlite3.connect(db_path)
            connection.execute(
                "CREATE TABLE candle_cache (symbol TEXT, timestamp TEXT, interval TEXT, "
                "open_price REAL, high_price REAL, low_price REAL, close_price REAL, volume REAL)"
            )
            target_day = datetime(2026, 7, 16)
            connection.executemany(
                "INSERT INTO candle_cache VALUES (?,?,?,?,?,?,?,?)",
                [
                    (
                        symbol,
                        (target_day - timedelta(days=20 - offset)).date().isoformat(),
                        "1d",
                        close_price,
                        close_price * 1.01,
                        close_price * 0.99,
                        close_price,
                        100.0,
                    )
                    for offset in range(21)
                    for symbol, close_price in (("A", 1000.0), ("B", 2000.0))
                ],
            )
            connection.commit()
            connection.close()
            client = QuoteOnlyClient()

            with (
                patch.object(mod, "DB_PATH", str(db_path)),
                patch.object(mod, "BREADTH_SHADOW_LOG", log_path),
                patch.object(mod.time, "sleep"),
            ):
                result = mod.collect_breadth_shadow_snapshot(
                    client,
                    trade_date="2026-07-17",
                    previous_business_day="2026-07-16",
                    base_symbols={"A"},
                    base_quote_rows=[{"symbol": "A", "lastPrice": "940"}],
                )

            event = json.loads(log_path.read_text(encoding="utf-8"))

        self.assertEqual(result["provisional_gap5_count"], 2)
        self.assertEqual(event["reference_symbols"], 2)
        self.assertFalse(event["applied_to_live_order"])
        self.assertEqual(client.requested, ["B"])

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

    def test_entry_price_snapshot_uses_first_minute_open_and_same_basis_previous_close(self):
        mod = load_simple_gap_trader()

        class CandleClient:
            def __init__(self):
                self.calls = []

            def get_candles(self, symbol, interval="1d", count=100, before=None, adjusted=True):
                self.calls.append((symbol, interval, count, before, adjusted))
                if interval == "1d":
                    return {
                        "result": {
                            "candles": [
                                {"timestamp": "2026-07-28T00:00:00+09:00", "openPrice": "1941", "closePrice": "1941"},
                                {"timestamp": "2026-07-27T00:00:00+09:00", "openPrice": "2100", "closePrice": "2095"},
                            ]
                        }
                    }
                return {
                    "result": {
                        "candles": [
                            {
                                "timestamp": "2026-07-28T09:01:00+09:00",
                                "openPrice": "1980",
                                "highPrice": "1980",
                                "lowPrice": "1920",
                                "closePrice": "1941",
                                "volume": "1455",
                            },
                            {"timestamp": "2026-07-27T15:30:00+09:00", "openPrice": "2095", "closePrice": "2095"},
                        ]
                    }
                }

        client = CandleClient()
        snapshot = mod.get_entry_price_snapshot(
            client,
            "274400",
            today="2026-07-28",
            previous_business_day="2026-07-27",
        )

        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot.open_price, 1980)
        self.assertEqual(snapshot.daily_open_price, 1941)
        self.assertEqual(snapshot.previous_close, 2095)
        self.assertEqual(snapshot.open_timestamp, "2026-07-28T09:01:00+09:00")
        self.assertEqual(snapshot.open_volume, 1455)
        self.assertEqual(snapshot.close_price, 1941)
        self.assertEqual(snapshot.high_price, 1980)
        self.assertEqual(snapshot.low_price, 1920)
        self.assertEqual(client.calls[0], ("274400", "1d", 5, None, True))
        self.assertEqual(client.calls[1], ("274400", "1m", 5, "2026-07-28T09:01:59+09:00", True))

    def test_stock_chart_requests_are_paced_below_five_tps(self):
        mod = load_simple_gap_trader()

        class CandleClient:
            def __init__(self):
                self.calls = 0

            def get_candles(self, symbol, interval="1d", count=100, before=None, adjusted=True):
                self.calls += 1
                return {"result": {"candles": []}}

        client = CandleClient()
        with (
            patch.object(mod.time, "monotonic", side_effect=[10.0, 10.0, 10.05, 10.22]),
            patch.object(mod.time, "sleep") as sleep,
        ):
            mod.get_stock_candles_paced(client, "274400", "1d", count=5)
            mod.get_stock_candles_paced(client, "274400", "1m", count=5)

        self.assertEqual(client.calls, 2)
        sleep.assert_called_once()
        self.assertAlmostEqual(sleep.call_args.args[0], 0.17, places=6)

    def test_run_buy_blocks_when_price_basis_changed_overnight(self):
        mod = load_simple_gap_trader()

        class PriceClient:
            def get_prices(self, symbols):
                return {"result": [{"symbol": "321370", "lastPrice": "1782"}]}

        market = mod.MarketGateSnapshot(
            current_index=98,
            open_price=98,
            sma5=100,
            buy_line=99,
            current_sma5=100,
            current_buy_line=99,
            timestamp="2026-07-28T09:01:00+09:00",
            open_timestamp="2026-07-28T09:01:00+09:00",
            daily_open_price=98,
            previous_business_day="2026-07-27",
        )
        entry = mod.EntryPriceSnapshot(
            open_price=1782,
            open_timestamp="2026-07-28T09:01:00+09:00",
            previous_close=1851,
            previous_close_timestamp="2026-07-27T00:00:00+09:00",
            daily_open_price=1782,
        )
        audit_rows = []
        with (
            patch.object(mod, "live_buy_window_allows", return_value=True),
            patch.object(mod, "load_strategy_state", return_value=None),
            patch.object(mod, "fetch_kosdaq_market_data", return_value=market),
            patch.object(mod, "evaluate_market_gate", return_value=True),
            patch.object(
                mod,
                "get_base_stocks_from_db",
                return_value=[
                    {
                        "symbol": "321370",
                        "name": "센서뷰",
                        "prev_close": 2040,
                        "prev_vol": 100,
                        "avg_vol": 1000,
                    }
                ],
            ),
            patch.object(mod, "get_actual_budget", return_value=10000),
            patch.object(mod, "get_entry_price_snapshot", return_value=entry),
            patch.object(mod, "append_entry_price_audit", side_effect=audit_rows.append),
            patch.object(mod, "collect_breadth_shadow_snapshot", return_value=None),
            patch("builtins.print"),
        ):
            mod.run_buy(
                PriceClient(),
                LiveSettings(),
                now=datetime(2026, 7, 28, 9, 1, tzinfo=KST),
            )

        self.assertTrue(
            any(row.get("decision") == "excluded_previous_close_basis_mismatch" for row in audit_rows)
        )

    def test_run_buy_aborts_partial_scan_at_order_deadline(self):
        mod = load_simple_gap_trader()

        class PriceClient:
            def get_prices(self, symbols):
                return {"result": [{"symbol": "274400", "lastPrice": "1900"}]}

        market = mod.MarketGateSnapshot(
            current_index=98,
            open_price=98,
            sma5=100,
            buy_line=99,
            current_sma5=100,
            current_buy_line=99,
            timestamp="2026-07-28T09:01:00+09:00",
            open_timestamp="2026-07-28T09:01:00+09:00",
            daily_open_price=98,
            previous_business_day="2026-07-27",
        )
        with (
            patch.object(mod, "live_buy_window_allows", side_effect=[True, False]),
            patch.object(mod, "load_strategy_state", return_value=None),
            patch.object(mod, "fetch_kosdaq_market_data", return_value=market),
            patch.object(mod, "evaluate_market_gate", return_value=True),
            patch.object(
                mod,
                "get_base_stocks_from_db",
                return_value=[
                    {
                        "symbol": "274400",
                        "name": "이노시뮬레이션",
                        "prev_close": 2095,
                        "prev_vol": 100,
                        "avg_vol": 1000,
                    }
                ],
            ),
            patch.object(mod, "get_actual_budget", return_value=10000),
            patch.object(mod, "get_entry_price_snapshot") as snapshot,
            patch.object(mod, "record_breadth_shadow_skipped") as skipped,
            patch("builtins.print"),
        ):
            mod.run_buy(
                PriceClient(),
                LiveSettings(),
                now=datetime(2026, 7, 28, 9, 1, tzinfo=KST),
            )

        snapshot.assert_not_called()
        skipped.assert_called_with("2026-07-28", "09:05 진입가격 검증 마감")

    def test_run_buy_blocks_after_exhausted_chart_rate_limit(self):
        mod = load_simple_gap_trader()

        class PriceClient:
            def get_prices(self, symbols):
                return {"result": [{"symbol": "274400", "lastPrice": "1900"}]}

        market = mod.MarketGateSnapshot(
            current_index=98,
            open_price=98,
            sma5=100,
            buy_line=99,
            current_sma5=100,
            current_buy_line=99,
            timestamp="2026-07-28T09:01:00+09:00",
            open_timestamp="2026-07-28T09:01:00+09:00",
            daily_open_price=98,
            previous_business_day="2026-07-27",
        )
        audit_rows = []
        with (
            patch.object(mod, "live_buy_window_allows", return_value=True),
            patch.object(mod, "load_strategy_state", return_value=None),
            patch.object(mod, "fetch_kosdaq_market_data", return_value=market),
            patch.object(mod, "evaluate_market_gate", return_value=True),
            patch.object(
                mod,
                "get_base_stocks_from_db",
                return_value=[
                    {
                        "symbol": "274400",
                        "name": "이노시뮬레이션",
                        "prev_close": 2095,
                        "prev_vol": 100,
                        "avg_vol": 1000,
                    }
                ],
            ),
            patch.object(mod, "get_actual_budget", return_value=10000),
            patch.object(
                mod,
                "get_entry_price_snapshot",
                side_effect=TossApiError(429, "Too Many Requests", '{"code":"rate-limit-exceeded"}'),
            ),
            patch.object(mod, "append_entry_price_audit", side_effect=audit_rows.append),
            patch.object(mod, "collect_breadth_shadow_snapshot", return_value=None),
            patch.object(mod, "blocking_warnings_for_symbol") as warnings,
            patch("builtins.print") as printer,
        ):
            mod.run_buy(
                PriceClient(),
                LiveSettings(),
                now=datetime(2026, 7, 28, 9, 1, tzinfo=KST),
            )

        warnings.assert_not_called()
        self.assertTrue(
            any(row.get("decision") == "excluded_entry_reference_error" for row in audit_rows)
        )
        self.assertTrue(
            any("모든 잠정 후보" in str(call.args[0]) for call in printer.call_args_list)
        )

    def test_run_buy_excludes_zero_volume_open_without_reaching_warning_or_order_checks(self):
        mod = load_simple_gap_trader()

        class PriceClient:
            def get_prices(self, symbols):
                return {"result": [{"symbol": "017250", "lastPrice": "1019"}]}

        market = mod.MarketGateSnapshot(
            current_index=98,
            open_price=98,
            sma5=100,
            buy_line=99,
            current_sma5=100,
            current_buy_line=99,
            timestamp="2026-06-22T09:01:00+09:00",
            open_timestamp="2026-06-22T09:01:00+09:00",
            daily_open_price=98,
            previous_business_day="2026-06-19",
        )
        audit_rows = []
        with (
            patch.object(mod, "live_buy_window_allows", return_value=True),
            patch.object(mod, "load_strategy_state", return_value=None),
            patch.object(mod, "fetch_kosdaq_market_data", return_value=market),
            patch.object(mod, "evaluate_market_gate", return_value=True),
            patch.object(
                mod,
                "get_base_stocks_from_db",
                return_value=[
                    {
                        "symbol": "017250",
                        "name": "인터엠",
                        "prev_close": 1070,
                        "prev_vol": 100,
                        "avg_vol": 1000,
                    }
                ],
            ),
            patch.object(mod, "get_actual_budget", return_value=10000),
            patch.object(
                mod,
                "get_entry_price_snapshot",
                side_effect=mod.NoRegularOpeningTrade("09:01 first-minute candle has zero volume"),
            ),
            patch.object(mod, "append_entry_price_audit", side_effect=audit_rows.append),
            patch.object(mod, "collect_breadth_shadow_snapshot", return_value=None),
            patch.object(mod, "blocking_warnings_for_symbol") as warnings,
            patch("builtins.print") as printer,
        ):
            mod.run_buy(
                PriceClient(),
                LiveSettings(),
                now=datetime(2026, 6, 22, 9, 1, tzinfo=KST),
            )

        warnings.assert_not_called()
        self.assertTrue(
            any(row.get("decision") == "excluded_no_regular_opening_trade" for row in audit_rows)
        )
        self.assertTrue(
            any("거래량이 0" in str(call.args[0]) for call in printer.call_args_list)
        )

    def test_run_buy_aborts_when_entry_audit_write_fails(self):
        mod = load_simple_gap_trader()

        class PriceClient:
            def get_prices(self, symbols):
                return {"result": [{"symbol": "274400", "lastPrice": "1900"}]}

        market = mod.MarketGateSnapshot(
            current_index=98,
            open_price=98,
            sma5=100,
            buy_line=99,
            current_sma5=100,
            current_buy_line=99,
            timestamp="2026-07-28T09:01:00+09:00",
            open_timestamp="2026-07-28T09:01:00+09:00",
            daily_open_price=98,
            previous_business_day="2026-07-27",
        )
        entry = mod.EntryPriceSnapshot(
            open_price=1980,
            open_timestamp="2026-07-28T09:01:00+09:00",
            previous_close=2095,
            previous_close_timestamp="2026-07-27T00:00:00+09:00",
            daily_open_price=1980,
        )
        with (
            patch.object(mod, "live_buy_window_allows", return_value=True),
            patch.object(mod, "load_strategy_state", return_value=None),
            patch.object(mod, "fetch_kosdaq_market_data", return_value=market),
            patch.object(mod, "evaluate_market_gate", return_value=True),
            patch.object(
                mod,
                "get_base_stocks_from_db",
                return_value=[
                    {
                        "symbol": "274400",
                        "name": "이노시뮬레이션",
                        "prev_close": 2095,
                        "prev_vol": 100,
                        "avg_vol": 1000,
                    }
                ],
            ),
            patch.object(mod, "get_actual_budget", return_value=10000),
            patch.object(mod, "get_entry_price_snapshot", return_value=entry),
            patch.object(mod.simple_gap_state, "append_event", side_effect=OSError("disk full")),
            patch.object(mod, "blocking_warnings_for_symbol") as warnings,
            patch("builtins.print") as printer,
        ):
            with self.assertRaises(OSError):
                mod.run_buy(
                    PriceClient(),
                    LiveSettings(),
                    now=datetime(2026, 7, 28, 9, 1, tzinfo=KST),
                )

        warnings.assert_not_called()
        self.assertTrue(
            any("진입가격 감사로그 실패" in str(call.args[0]) for call in printer.call_args_list)
        )

    def test_entry_price_snapshot_returns_none_when_first_minute_missing(self):
        mod = load_simple_gap_trader()

        class CandleClient:
            def get_candles(self, symbol, interval="1d", count=100, before=None, adjusted=True):
                if interval == "1d":
                    return {
                        "result": {
                            "candles": [
                                {"timestamp": "2026-07-28T00:00:00+09:00", "openPrice": "1941", "closePrice": "1941"},
                                {"timestamp": "2026-07-27T00:00:00+09:00", "closePrice": "2095"},
                            ]
                        }
                    }
                return {"result": {"candles": [{"timestamp": "2026-07-27T15:30:00+09:00", "openPrice": "2095"}]}}

        self.assertIsNone(
            mod.get_entry_price_snapshot(
                CandleClient(),
                "274400",
                today="2026-07-28",
                previous_business_day="2026-07-27",
            )
        )

    def test_entry_price_snapshot_rejects_zero_volume_stale_candle(self):
        mod = load_simple_gap_trader()

        class CandleClient:
            def get_candles(self, symbol, interval="1d", count=100, before=None, adjusted=True):
                if interval == "1d":
                    return {
                        "result": {
                            "candles": [
                                {"timestamp": "2026-06-22T00:00:00+09:00", "openPrice": "961", "closePrice": "1007"},
                                {"timestamp": "2026-06-19T00:00:00+09:00", "closePrice": "1019"},
                            ]
                        }
                    }
                return {
                    "result": {
                        "candles": [
                            {
                                "timestamp": "2026-06-22T09:01:00+09:00",
                                "openPrice": "1019",
                                "closePrice": "1019",
                                "volume": "0",
                            }
                        ]
                    }
                }

        with self.assertRaisesRegex(mod.NoRegularOpeningTrade, "zero volume"):
            mod.get_entry_price_snapshot(
                CandleClient(),
                "017250",
                today="2026-06-22",
                previous_business_day="2026-06-19",
            )

    def test_entry_price_snapshot_treats_missing_volume_as_missing_data(self):
        mod = load_simple_gap_trader()

        class CandleClient:
            def get_candles(self, symbol, interval="1d", count=100, before=None, adjusted=True):
                if interval == "1d":
                    return {
                        "result": {
                            "candles": [
                                {"timestamp": "2026-07-28T00:00:00+09:00", "openPrice": "1000"},
                                {"timestamp": "2026-07-27T00:00:00+09:00", "closePrice": "1100"},
                            ]
                        }
                    }
                return {
                    "result": {
                        "candles": [
                            {
                                "timestamp": "2026-07-28T09:01:00+09:00",
                                "openPrice": "1000",
                            }
                        ]
                    }
                }

        self.assertIsNone(
            mod.get_entry_price_snapshot(
                CandleClient(),
                "123456",
                today="2026-07-28",
                previous_business_day="2026-07-27",
            )
        )

    def test_previous_close_basis_check_detects_adjustment_rewrite(self):
        mod = load_simple_gap_trader()

        mismatch_pct = mod.previous_close_basis_diff_pct(2040, 1851)

        self.assertAlmostEqual(mismatch_pct, 10.2107, places=3)
        self.assertGreater(mismatch_pct, mod.PREVIOUS_CLOSE_BASIS_MAX_PCT * 100.0)
        self.assertEqual(mod.previous_close_basis_diff_pct(2095, 2095), 0.0)

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

    def test_acceptable_buy_limit_price_blocks_far_above_open(self):
        mod = load_simple_gap_trader()

        class OrderbookClient:
            def get_orderbook(self, symbol):
                return {"result": {"asks": [{"price": "1500"}]}}

        target = {"symbol": "054220", "name": "테스트", "open_price": 1372, "last_price": 1498}

        self.assertIsNone(mod.acceptable_buy_limit_price(OrderbookClient(), target))

    def test_acceptable_buy_limit_price_uses_near_open_ask(self):
        mod = load_simple_gap_trader()

        class OrderbookClient:
            def get_orderbook(self, symbol):
                return {"result": {"asks": [{"price": "1374"}]}}

        target = {"symbol": "054220", "name": "테스트", "open_price": 1372, "last_price": 1373}

        self.assertEqual(mod.acceptable_buy_limit_price(OrderbookClient(), target), 1374)
        self.assertEqual(target["observed_buy_quote"], 1374)
        self.assertAlmostEqual(target["buy_quote_drift_pct"], 0.1457726, places=6)

    def test_acceptable_buy_limit_price_rejects_stale_ask_below_recent_price(self):
        mod = load_simple_gap_trader()

        class OrderbookClient:
            def get_orderbook(self, symbol):
                return {"result": {"asks": [{"price": "1372"}]}}

        target = {"symbol": "054220", "name": "테스트", "open_price": 1372, "last_price": 1498}

        self.assertIsNone(mod.acceptable_buy_limit_price(OrderbookClient(), target))

    def test_base_screen_ignores_non_daily_candles(self):
        mod = load_simple_gap_trader()

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "candles.sqlite3"
            connection = sqlite3.connect(db_path)
            connection.execute(
                "CREATE TABLE candle_cache (symbol TEXT, timestamp TEXT, interval TEXT, "
                "open_price REAL, high_price REAL, low_price REAL, close_price REAL, volume REAL)"
            )
            connection.executemany(
                "INSERT INTO candle_cache VALUES (?,?,?,?,?,?,?,?)",
                [
                    (
                        "054220",
                        (datetime(2026, 7, 16) - timedelta(days=20 - offset)).date().isoformat(),
                        "1d",
                        2000.0,
                        2010.0,
                        1990.0,
                        2000.0,
                        100.0,
                    )
                    for offset in range(21)
                ]
                + [
                    ("054220", "2026-07-17T09:01:00+09:00", "1m", 1.0, 1.0, 1.0, 1.0, 999999.0)
                ],
            )
            connection.commit()
            connection.close()

            with patch.object(mod, "DB_PATH", str(db_path)):
                candidates = mod.get_base_stocks_from_db(expected_date="2026-07-16")

        self.assertEqual([row["symbol"] for row in candidates], ["054220"])
        self.assertEqual(candidates[0]["prev_vol"], 100)

    def test_monitor_sends_stop_loss_sell_when_price_crosses_stop(self):
        mod = load_simple_gap_trader()
        client = FakeMonitorClient(
            holdings=[{"symbol": "123456", "name": "테스트", "quantity": "1", "averagePrice": "1000"}],
            prices={"123456": "977"},
            bid_price="976",
        )

        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "state.json"
            write_state(state_path, open_position_state())
            with patch.object(mod, "STRATEGY_STATE_PATH", state_path):
                mod.run_monitor(client, FakeSettings())

        self.assertEqual(len(client.created_orders), 1)
        self.assertEqual(client.created_orders[0]["side"], "SELL")
        self.assertEqual(client.created_orders[0]["orderType"], "MARKET")
        self.assertEqual(client.created_orders[0]["symbol"], "123456")
        self.assertEqual(client.created_orders[0]["quantity"], "1")
        self.assertNotIn("price", client.created_orders[0])

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
                patch.object(mod, "STRATEGY_STATE_PATH", Path(tmp) / "state.json"),
                patch.object(mod, "PAPER_REENTRY_LOG", log_path),
                patch.object(mod, "send_discord_message", side_effect=fake_send),
            ):
                write_state(mod.STRATEGY_STATE_PATH, open_position_state())
                mod.run_monitor(client, FakeSettings())

        self.assertEqual(len(sent_messages), 1)
        self.assertIn("장중 손절 체결 알림", sent_messages[0])
        self.assertIn("테스트(123456)", sent_messages[0])
        self.assertIn("수익률: -2.40%", sent_messages[0])
        self.assertIn("주문ID: ORD-STOP", sent_messages[0])
        self.assertIn("실제 체결가: 976원", sent_messages[0])
        self.assertNotIn("acct", sent_messages[0])

    def test_monitor_does_not_send_discord_alert_for_dry_run_order(self):
        mod = load_simple_gap_trader()
        client = FakeMonitorClient(
            holdings=[{"symbol": "123456", "name": "테스트", "quantity": "1", "averagePrice": "1000"}],
            prices={"123456": "977"},
            bid_price="976",
            dry_run=True,
        )

        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "state.json"
            write_state(state_path, open_position_state())
            with (
                patch.object(mod, "STRATEGY_STATE_PATH", state_path),
                patch.object(mod, "send_discord_message", side_effect=AssertionError("dry-run must not notify")),
            ):
                mod.run_monitor(client, FakeSettings())

    def test_monitor_skips_sell_when_open_sell_order_exists(self):
        mod = load_simple_gap_trader()
        client = FakeMonitorClient(
            holdings=[{"symbol": "123456", "name": "테스트", "quantity": "1", "averagePrice": "1000"}],
            prices={"123456": "977"},
            open_orders=[{"side": "SELL"}],
        )

        state = open_position_state()
        state["sell_orders"] = [
            {
                "order_id": "SELL-OPEN",
                "client_order_id": "sg-202607170902-S-123456",
                "trigger": "손절",
                "requested_quantity": 1,
                "status": "PENDING",
                "filled_quantity": 0,
                "average_filled_price": None,
                "submitted_at": "2026-07-17T09:02:00+09:00",
            }
        ]
        client.order_details["SELL-OPEN"] = {
            "result": {
                "orderId": "SELL-OPEN",
                "symbol": "123456",
                "side": "SELL",
                "status": "PENDING",
                "quantity": "1",
                "orderedAt": "2026-07-17T09:02:00+09:00",
                "execution": {"filledQuantity": "0", "averageFilledPrice": None, "filledAmount": None},
            }
        }
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "state.json"
            write_state(state_path, state)
            with patch.object(mod, "STRATEGY_STATE_PATH", state_path):
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

        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "state.json"
            write_state(state_path, open_position_state())
            with patch.object(mod, "STRATEGY_STATE_PATH", state_path):
                mod.run_monitor(client, FakeSettings())

        self.assertEqual(len(client.created_orders), 1)
        self.assertEqual(client.created_orders[0]["symbol"], "123456")

    def test_monitor_ignores_untracked_account_holdings(self):
        mod = load_simple_gap_trader()
        client = FakeMonitorClient(
            holdings=[{"symbol": "999999", "name": "수동", "quantity": "10", "averagePrice": "1000"}],
            prices={"999999": "900"},
        )

        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(mod, "STRATEGY_STATE_PATH", Path(tmp) / "missing.json"):
                mod.run_monitor(client, FakeSettings())

        self.assertEqual(client.created_orders, [])

    def test_monitor_caps_sell_to_strategy_owned_quantity(self):
        mod = load_simple_gap_trader()
        client = FakeMonitorClient(
            holdings=[{"symbol": "123456", "name": "혼합", "quantity": "10", "averagePrice": "1000"}],
            prices={"123456": "970"},
        )
        state = open_position_state(quantity=2)

        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "state.json"
            write_state(state_path, state)
            with patch.object(mod, "STRATEGY_STATE_PATH", state_path):
                mod.run_monitor(client, FakeSettings())

        self.assertEqual(client.created_orders[0]["quantity"], "2")

    def test_sell_order_ack_without_fill_does_not_record_completed_exit(self):
        mod = load_simple_gap_trader()
        client = FakeMonitorClient(
            holdings=[{"symbol": "123456", "name": "테스트", "quantity": "1", "averagePrice": "1000"}],
            prices={"123456": "970"},
            dry_run=False,
            created_order_status="PENDING",
        )

        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "state.json"
            watch_path = Path(tmp) / "watch.jsonl"
            write_state(state_path, open_position_state())
            with (
                patch.object(mod, "STRATEGY_STATE_PATH", state_path),
                patch.object(mod, "PAPER_REENTRY_LOG", watch_path),
                patch.object(mod, "send_discord_message", side_effect=AssertionError("pending order is not a completed exit")),
            ):
                mod.run_monitor(client, FakeSettings())
            saved = json.loads(state_path.read_text(encoding="utf-8"))

        self.assertEqual(saved["status"], "EXIT_PENDING")
        self.assertFalse(saved["exit_recorded"])
        self.assertFalse(watch_path.exists())

    def test_ambiguous_sell_submit_is_persisted_and_never_retried(self):
        mod = load_simple_gap_trader()
        client = FakeMonitorClient(
            holdings=[{"symbol": "123456", "name": "테스트", "quantity": "1", "averagePrice": "1000"}],
            prices={"123456": "970"},
            dry_run=False,
        )

        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "state.json"
            write_state(state_path, open_position_state())
            with (
                patch.object(mod, "STRATEGY_STATE_PATH", state_path),
                patch.object(client, "create_order", side_effect=TimeoutError("response lost")) as create_order,
            ):
                mod.run_monitor(client, LiveSettings())
            saved = json.loads(state_path.read_text(encoding="utf-8"))

        self.assertEqual(create_order.call_count, 1)
        self.assertEqual(saved["status"], "EXIT_SUBMITTING")
        self.assertEqual(saved["sell_orders"][0]["status"], "SUBMITTING")

    def test_crash_before_buy_ack_recovers_with_exact_idempotent_payload(self):
        mod = load_simple_gap_trader()
        payload = mod.build_limit_quantity_order("123456", "BUY", 2, 1000, now=datetime(2026, 7, 17, 9, 1, tzinfo=KST))
        state = mod.simple_gap_state.new_buy_state(
            strategy_name=mod.STRATEGY_NAME,
            trade_date="2026-07-17",
            symbol="123456",
            name="테스트",
            client_order_id=payload["clientOrderId"],
            requested_quantity=2,
            limit_price=1000,
            order_payload=payload,
            now=datetime(2026, 7, 17, 9, 1, tzinfo=KST),
        )

        class RecoveryClient:
            def __init__(self):
                self.replayed = []

            def create_order(self, account_seq, replayed_payload):
                self.replayed.append(replayed_payload)
                return {"result": {"orderId": "BUY-RECOVERED"}}

            def get_order(self, order_id, account_seq=None):
                return {
                    "result": {
                        "orderId": order_id,
                        "symbol": "123456",
                        "side": "BUY",
                        "status": "FILLED",
                        "quantity": "2",
                        "orderedAt": "2026-07-17T09:01:00+09:00",
                        "execution": {"filledQuantity": "2", "averageFilledPrice": "1000", "filledAmount": "2000"},
                    }
                }

        client = RecoveryClient()
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(mod, "STRATEGY_STATE_PATH", Path(tmp) / "state.json"):
                recovered, safe = mod.reconcile_strategy_state(
                    client,
                    LiveSettings(),
                    state,
                    now=datetime(2026, 7, 17, 9, 2, tzinfo=KST),
                )

        self.assertTrue(safe)
        self.assertEqual(client.replayed, [payload])
        self.assertEqual(recovered["buy"]["order_id"], "BUY-RECOVERED")
        self.assertEqual(recovered["status"], "POSITION_OPEN")

    def test_buy_ack_recovery_stops_after_ten_minute_idempotency_window(self):
        mod = load_simple_gap_trader()
        payload = mod.build_limit_quantity_order("123456", "BUY", 2, 1000, now=datetime(2026, 7, 17, 9, 1, tzinfo=KST))
        state = mod.simple_gap_state.new_buy_state(
            strategy_name=mod.STRATEGY_NAME,
            trade_date="2026-07-17",
            symbol="123456",
            name="테스트",
            client_order_id=payload["clientOrderId"],
            requested_quantity=2,
            limit_price=1000,
            order_payload=payload,
            now=datetime(2026, 7, 17, 9, 1, tzinfo=KST),
        )

        class NoReplayClient:
            def create_order(self, *args, **kwargs):
                raise AssertionError("expired idempotency key must never be replayed")

        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(mod, "STRATEGY_STATE_PATH", Path(tmp) / "state.json"):
                recovered, safe = mod.reconcile_strategy_state(
                    NoReplayClient(),
                    LiveSettings(),
                    state,
                    now=datetime(2026, 7, 17, 9, 11, 1, tzinfo=KST),
                )

        self.assertFalse(safe)
        self.assertEqual(recovered["status"], "BUY_UNTRACKED")

    def test_crash_before_sell_ack_recovers_with_exact_idempotent_payload(self):
        mod = load_simple_gap_trader()
        submitted_at = datetime(2026, 7, 17, 9, 2, tzinfo=KST)
        payload = mod.build_market_quantity_order("123456", "SELL", 1, now=submitted_at)
        state = mod.simple_gap_state.add_sell_order(
            open_position_state(),
            order_id=None,
            client_order_id=payload["clientOrderId"],
            trigger="손절",
            requested_quantity=1,
            observed_price=970,
            trigger_price=977.5,
            order_payload=payload,
            now=submitted_at,
        )

        class RecoveryClient:
            def __init__(self):
                self.replayed = []

            def create_order(self, account_seq, replayed_payload):
                self.replayed.append(replayed_payload)
                return {"result": {"orderId": "SELL-RECOVERED"}}

            def get_order(self, order_id, account_seq=None):
                return {
                    "result": {
                        "orderId": order_id,
                        "symbol": "123456",
                        "side": "SELL",
                        "status": "PENDING",
                        "quantity": "1",
                        "orderedAt": "2026-07-17T09:02:00+09:00",
                        "execution": {"filledQuantity": "0", "averageFilledPrice": None, "filledAmount": None},
                    }
                }

        client = RecoveryClient()
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(mod, "STRATEGY_STATE_PATH", Path(tmp) / "state.json"):
                recovered, safe = mod.reconcile_strategy_state(
                    client,
                    LiveSettings(),
                    state,
                    now=datetime(2026, 7, 17, 9, 3, tzinfo=KST),
                )

        self.assertTrue(safe)
        self.assertEqual(client.replayed, [payload])
        self.assertEqual(recovered["status"], "EXIT_PENDING")
        self.assertEqual(recovered["sell_orders"][0]["order_id"], "SELL-RECOVERED")

    def test_missing_order_id_replays_exact_payload_without_claiming_open_order(self):
        mod = load_simple_gap_trader()
        state = open_position_state()

        class ReplayClient(FakeMonitorClient):
            def __init__(self):
                super().__init__(holdings=[], prices={}, dry_run=False, created_order_status="PENDING")
                self.responses = [
                    {"result": {"clientOrderId": "same"}},
                    {"result": {"orderId": "SELL-IDEMPOTENT"}},
                ]

            def create_order(self, account_seq, payload):
                self.created_orders.append(dict(payload))
                response = self.responses.pop(0)
                if "orderId" in response.get("result", {}):
                    order_id = response["result"]["orderId"]
                    self.order_details[order_id] = {
                        "result": {
                            "orderId": order_id,
                            "symbol": payload["symbol"],
                            "side": payload["side"],
                            "status": "PENDING",
                            "quantity": payload["quantity"],
                            "orderedAt": "2026-07-17T09:02:00+09:00",
                            "execution": {"filledQuantity": "0", "averageFilledPrice": None, "filledAmount": None},
                        }
                    }
                return response

            def get_orders(self, *args, **kwargs):
                raise AssertionError("manual/open orders must never be claimed as ACK recovery")

        client = ReplayClient()
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(mod, "STRATEGY_STATE_PATH", Path(tmp) / "state.json"):
                result = mod.submit_strategy_market_sell(
                    client,
                    LiveSettings(),
                    state,
                    quantity=1,
                    trigger="손절",
                    observed_price=970,
                    trigger_price=977.5,
                    now=datetime(2026, 7, 17, 9, 2, tzinfo=KST),
                )

        self.assertEqual(len(client.created_orders), 2)
        self.assertEqual(client.created_orders[0], client.created_orders[1])
        self.assertEqual(result["sell_orders"][0]["order_id"], "SELL-IDEMPOTENT")

    def test_confirmed_sell_rejection_keeps_position_open_for_later_retry(self):
        mod = load_simple_gap_trader()
        state = open_position_state()
        client = FakeMonitorClient(holdings=[], prices={}, dry_run=False)

        with tempfile.TemporaryDirectory() as tmp:
            with (
                patch.object(mod, "STRATEGY_STATE_PATH", Path(tmp) / "state.json"),
                patch.object(client, "create_order", side_effect=TossApiError(422, "order rejected")),
            ):
                result = mod.submit_strategy_market_sell(
                    client,
                    LiveSettings(),
                    state,
                    quantity=1,
                    trigger="손절",
                    observed_price=970,
                    trigger_price=977.5,
                    now=datetime(2026, 7, 17, 9, 2, tzinfo=KST),
                )

        self.assertEqual(result["status"], "POSITION_OPEN")
        self.assertEqual(result["sell_orders"][0]["status"], "REJECTED")

    def test_process_lock_allows_only_one_overlapping_process(self):
        mod = load_simple_gap_trader()
        with tempfile.TemporaryDirectory() as tmp:
            lock_path = Path(tmp) / "strategy.lock"
            marker_path = Path(tmp) / "posts.txt"
            code = f"""
import importlib.util
import time
from pathlib import Path
spec = importlib.util.spec_from_file_location('simple_gap_lock_worker', {str(Path(mod.__file__))!r})
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
with module.strategy_process_lock(Path({str(lock_path)!r})) as acquired:
    if acquired:
        with Path({str(marker_path)!r}).open('a', encoding='utf-8') as handle:
            handle.write('POST\\n')
        time.sleep(0.4)
"""
            first = subprocess.Popen([sys.executable, "-c", code])
            time.sleep(0.1)
            second = subprocess.Popen([sys.executable, "-c", code])
            self.assertEqual(first.wait(timeout=5), 0)
            self.assertEqual(second.wait(timeout=5), 0)

            self.assertEqual(marker_path.read_text(encoding="utf-8").splitlines(), ["POST"])

    def test_monitor_cancels_stale_unfilled_buy_before_any_sell(self):
        mod = load_simple_gap_trader()
        client = FakeMonitorClient(holdings=[], prices={}, dry_run=False)
        state = open_position_state(quantity=1)
        state["status"] = "BUY_PENDING"
        state["buy"].update(
            {
                "status": "PENDING",
                "filled_quantity": 0,
                "average_filled_price": None,
                "ordered_at": "2026-07-17T09:01:10+09:00",
                "cancel_requested_at": None,
            }
        )
        state["position"] = {"opened_quantity": 0, "remaining_quantity": 0, "entry_price": None}
        client.order_details["BUY-1"] = {
            "result": {
                "orderId": "BUY-1",
                "symbol": "123456",
                "side": "BUY",
                "status": "PENDING",
                "quantity": "1",
                "orderedAt": "2026-07-17T09:01:10+09:00",
                "execution": {"filledQuantity": "0", "averageFilledPrice": None, "filledAmount": None},
            }
        }

        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "state.json"
            write_state(state_path, state)
            with patch.object(mod, "STRATEGY_STATE_PATH", state_path):
                mod.run_monitor(client, FakeSettings())

        self.assertEqual(client.cancelled_orders, ["BUY-1"])
        self.assertEqual(client.created_orders, [])

    def test_end_of_day_sell_ignores_manual_holdings_and_uses_market_order(self):
        mod = load_simple_gap_trader()
        client = FakeMonitorClient(
            holdings=[
                {"symbol": "123456", "name": "전략", "quantity": "3", "averagePrice": "1000"},
                {"symbol": "999999", "name": "수동", "quantity": "10", "averagePrice": "1000"},
            ],
            prices={"123456": "1010", "999999": "900"},
            dry_run=False,
        )
        state = open_position_state(quantity=2)

        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "state.json"
            write_state(state_path, state)
            with patch.object(mod, "STRATEGY_STATE_PATH", state_path):
                mod.run_sell(client, FakeSettings())

        self.assertEqual(len(client.created_orders), 1)
        self.assertEqual(client.created_orders[0]["symbol"], "123456")
        self.assertEqual(client.created_orders[0]["quantity"], "2")
        self.assertEqual(client.created_orders[0]["orderType"], "MARKET")


if __name__ == "__main__":
    unittest.main()
