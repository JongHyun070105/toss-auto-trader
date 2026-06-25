import argparse
import importlib.util
import json
import sqlite3
import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


def load_script(name: str):
    path = SCRIPTS_DIR / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


portfolio = load_script("volume_shock_portfolio_backtest")
pullback = load_script("pullback_after_trend_audit")
volume = load_script("volume_shock_hypothesis_audit")
reversal = load_script("volume_shock_reversal_audit")
ai_sweep = load_script("ai_trader_universe_sweep")
rsi_bbands = load_script("rsi_bbands_mean_reversion_audit")
forward_watch = load_script("rsi_bbands_v3_forward_watch")
forward_outcome = load_script("rsi_bbands_v3_forward_outcome_update")
market_regime = load_script("market_regime_signal_audit")
regime_exposure = load_script("market_regime_exposure_gate_audit")
relative_strength = load_script("relative_strength_horizon_audit")
event_reaction = load_script("event_liquidity_reaction_audit")


class ResearchHypothesisScriptTests(unittest.TestCase):
    def test_portfolio_simulator_respects_max_positions(self):
        signals = [
            {
                "symbol": "AAA",
                "timestamp": "2026-01-01",
                "entry_timestamp": "2026-01-02",
                "exit_timestamp": "2026-01-05",
                "volume_multiple": 5,
                "net_return_after_cost": 0.10,
                "entry_price": 100,
                "exit_price": 110,
            },
            {
                "symbol": "BBB",
                "timestamp": "2026-01-01",
                "entry_timestamp": "2026-01-02",
                "exit_timestamp": "2026-01-05",
                "volume_multiple": 4,
                "net_return_after_cost": 0.10,
                "entry_price": 100,
                "exit_price": 110,
            },
        ]
        result = portfolio.simulate_portfolio(
            signals,
            initial_cash=Decimal("1000"),
            max_positions=1,
            position_fraction=Decimal("0.50"),
            max_daily_entries=3,
        )
        self.assertEqual(result["filled_entries"], 1)
        self.assertEqual(result["rejected_entries"], 1)
        self.assertAlmostEqual(result["final_equity"], 1050.0)

    def test_pullback_signal_return_uses_next_open_and_locked_exit(self):
        candles = []
        for i in range(10):
            candles.append({
                "timestamp": f"2026-01-{i+1:02d}",
                "open_price": "100",
                "high_price": "105",
                "low_price": "95",
                "close_price": "100",
                "volume": "1000",
            })
        candles[6]["open_price"] = "100"
        candles[8]["close_price"] = "110"
        net, abs_net, entry, exit_price = pullback.signal_return(candles, 5, horizon=2, cost_pct=Decimal("0.006"))
        self.assertEqual(entry, Decimal("100"))
        self.assertEqual(exit_price, Decimal("110"))
        self.assertAlmostEqual(net, 0.094)
        self.assertAlmostEqual(abs_net, 0.094)

    def test_breakout_gap_fill_uses_next_open_not_yesterday_trigger(self):
        candles = []
        for i in range(30):
            candles.append({
                "timestamp": f"2026-01-{i+1:02d}",
                "open_price": "100",
                "high_price": "103",
                "low_price": "95",
                "close_price": "101",
                "volume": "1000",
            })
        candles[20].update({"open_price": "100", "high_price": "110", "close_price": "105", "volume": "4000"})
        candles[21].update({"open_price": "120", "high_price": "125", "close_price": "121"})
        candles[24]["close_price"] = "120"
        row = volume.test_symbol(
            candles,
            symbol="TEST",
            vol_mult=Decimal("3"),
            lookback=20,
            horizon=3,
            cost_pct=Decimal("0.006"),
            strategy="breakout",
        )
        self.assertEqual(row["stats"]["signals"], 1)
        sig = row["_signals"][0]
        self.assertEqual(sig["entry_price"], 120.0)
        self.assertEqual(sig["entry_model"], "gap_fill_next_open")
        self.assertAlmostEqual(sig["net_return_after_cost"], -0.006)

    def test_reversal_proxy_is_research_only_short_transform(self):
        transformed = reversal.to_short_proxy(
            [{"symbol": "AAA", "timestamp": "2026-01-01", "entry_price": "100", "exit_price": "90", "net_return_after_cost": -0.106}],
            cost_pct=Decimal("0.006"),
        )
        self.assertEqual(transformed[0]["hypothesis_role"], "post_hoc_short_proxy_not_live_tradable")
        self.assertAlmostEqual(transformed[0]["net_return_after_cost"], 0.094)

    def test_ai_trader_asof_universe_does_not_use_future_liquidity(self):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "candles.sqlite3"
            con = sqlite3.connect(db)
            con.execute(
                "CREATE TABLE candle_cache (symbol TEXT, timestamp TEXT, interval TEXT, close_price TEXT, volume TEXT)"
            )
            # OLD has enough pre-2021 liquidity. FUTURE only becomes liquid after 2021 start and must not be selected.
            rows = []
            for day in range(1, 71):
                rows.append(("OLD", f"2020-12-{min(day, 28):02d}", "1d", "100", "1000000"))
                rows.append(("FUTURE", f"2021-02-{min(day, 28):02d}", "1d", "100", "9999999"))
            con.executemany("INSERT INTO candle_cache VALUES (?,?,?,?,?)", rows)
            con.commit()
            con.close()
            selected = ai_sweep.asof_universe(str(db), "2021-01-01", lookback_bars=60, limit=5, min_bars=40)
            self.assertEqual([row["symbol"] for row in selected], ["OLD"])

    def test_ai_trader_windows_include_year_and_rolling(self):
        windows = ai_sweep.build_windows("2020-10-07", "2023-12-31", include_full=True, include_years=True, rolling_years=[2])
        labels = {w["label"] for w in windows}
        self.assertIn("full", labels)
        self.assertIn("year_2021", labels)
        self.assertIn("rolling2y_2021_2022", labels)

    def test_rsi_bbands_rsi_extremes_are_deterministic(self):
        rising = [Decimal(str(i)) for i in range(1, 17)]
        falling = [Decimal(str(i)) for i in range(16, 0, -1)]
        self.assertEqual(rsi_bbands.rsi(rising, 14), Decimal("100"))
        self.assertEqual(rsi_bbands.rsi(falling, 14), Decimal("0"))

    def test_rsi_bbands_market_crash_guard_blocks_weak_index(self):
        rows = []
        price = Decimal("100")
        for i in range(25):
            price -= Decimal("1")
            rows.append({"timestamp": f"2026-01-{i+1:02d}", "close_price": price})
        guard = rsi_bbands.market_guard_map(rows, min_20d_return=Decimal("-0.05"))
        self.assertFalse(guard["2026-01-25"]["ok"])
        self.assertEqual(guard["2026-01-25"]["reason"], "market_crash_guard")

    def test_rsi_bbands_min_bb_z_blocks_extreme_falling_knife(self):
        candles = []
        for i in range(61):
            close = Decimal("10000") if i < 60 else Decimal("5000")
            candles.append({
                "timestamp": f"2026-03-{(i % 28) + 1:02d}",
                "open_price": close,
                "high_price": close,
                "low_price": close,
                "close_price": close,
                "volume": Decimal("1000"),
            })
        args = argparse.Namespace(
            rsi_period=14,
            bb_period=20,
            bb_dev="2",
            min_bb_z="-2.5",
            oversold="30",
            volume_lookback=20,
            max_volume_multiple="3",
            min_close_price="1000",
            min_price_history=20,
        )
        market = {"2026-03-05": {"ok": True, "kosdaq_20d_return": 0.0, "kosdaq_20d_ann_vol": 0.1}}
        ok, meta = rsi_bbands.signal_meta(candles, 60, market, args)
        self.assertFalse(ok)
        self.assertEqual(meta["blocker"], "bb_z_too_extreme")

    def test_v3_forward_watch_never_sends_orders(self):
        old = {
            "fetch_kosdaq_index": forward_watch.fetch_kosdaq_index,
            "market_guard_map": forward_watch.market_guard_map,
            "load_symbols": forward_watch.load_symbols,
            "cached_candles_readonly": forward_watch.cached_candles_readonly,
            "signal_meta": forward_watch.signal_meta,
            "load_seen_signal_ids": forward_watch.load_seen_signal_ids,
        }
        try:
            forward_watch.fetch_kosdaq_index = lambda start, end: [{"timestamp": "2026-01-31", "close_price": Decimal("100")}]
            forward_watch.market_guard_map = lambda rows, min_20d_return, max_ann_vol: {"2026-01-31": {"ok": True}}
            forward_watch.load_symbols = lambda ns: ["AAA"]
            forward_watch.cached_candles_readonly = lambda db, symbol: [
                {"timestamp": "2026-01-30", "close_price": Decimal("100"), "open_price": Decimal("100"), "high_price": Decimal("100"), "low_price": Decimal("100"), "volume": Decimal("1000")},
                {"timestamp": "2026-01-31", "close_price": Decimal("90"), "open_price": Decimal("90"), "high_price": Decimal("90"), "low_price": Decimal("90"), "volume": Decimal("1000")},
            ]
            forward_watch.signal_meta = lambda candles, i, market, args: (True, {"rsi": 25, "bb_z": -2.0})
            forward_watch.load_seen_signal_ids = lambda path: set()
            args = argparse.Namespace(
                index_start="20200101",
                index_end="20260625",
                market_min_20d_return_dec=Decimal("-0.12"),
                market_max_ann_vol_dec=None,
                symbols="cached",
                symbols_file="",
                source_db="unused.sqlite3",
                hypothesis_id="TEST_HYP",
                limit=10,
                ledger="unused.jsonl",
                rsi_period=14,
                bb_period=20,
                bb_dev="2",
                min_bb_z="-2.5",
                oversold="30",
                volume_lookback=20,
                max_volume_multiple="2.5",
                min_close_price="1000",
                min_price_history=1,
                horizon=20,
            )
            report = forward_watch.scan(args)
            self.assertEqual(report["candidate_count"], 1)
            cand = report["candidates"][0]
            self.assertFalse(cand["order_sent"])
            self.assertFalse(cand["live_order_allowed"])
            self.assertEqual(cand["status"], "forward_watch_candidate_not_live_order")
        finally:
            for name, value in old.items():
                setattr(forward_watch, name, value)

    def test_v3_forward_outcome_resolves_after_horizon_without_orders(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            candles = []
            for i in range(50):
                price = Decimal("100")
                if i == 41:
                    price = Decimal("105")
                candles.append({
                    "timestamp": f"2026-01-{(i + 1):02d}",
                    "open_price": price,
                    "high_price": price,
                    "low_price": price,
                    "close_price": price,
                    "volume": Decimal("1000"),
                })
            old_loader = forward_outcome.cached_candles_readonly
            forward_outcome.cached_candles_readonly = lambda db, symbol: candles
            try:
                ledger = root / "observations.jsonl"
                obs = {
                    "signal_id": "TEST:AAA:2026-01-21",
                    "hypothesis_id": "TEST",
                    "symbol": "AAA",
                    "signal_date": "2026-01-21",
                    "paper_only": True,
                    "order_sent": False,
                    "live_order_allowed": False,
                    "features": {"rsi": 25, "bb_z": -2.0},
                }
                ledger.write_text(json.dumps(obs) + "\n")
                outcomes = root / "outcomes.jsonl"
                out = root / "summary.json"
                args = argparse.Namespace(
                    source_db="unused.sqlite3",
                    ledger=str(ledger),
                    outcomes=str(outcomes),
                    out=str(out),
                    hypothesis_id="TEST",
                    horizon=20,
                    stop_pct="0.10",
                    roundtrip_cost_pct="0.0046",
                    max_gap_down_pct="-0.10",
                    max_gap_up_pct="0.08",
                    bb_period=20,
                    rsi_period=14,
                    exit_rsi="55",
                )
                report = forward_outcome.update_outcomes(args)
                self.assertEqual(report["new_outcomes"], 1)
                rows = [json.loads(line) for line in outcomes.read_text().splitlines()]
                self.assertEqual(rows[0]["outcome_status"], "resolved")
                self.assertFalse(rows[0]["order_sent"])
                self.assertFalse(rows[0]["live_order_allowed"])
                self.assertIn("net_return_after_cost", rows[0]["outcome"])
            finally:
                forward_outcome.cached_candles_readonly = old_loader

    def test_market_regime_classifier_prioritizes_exposure_question(self):
        self.assertEqual(market_regime.classify_regime({"ret_20d": -0.09, "ret_60d": -0.1, "ann_vol_20d": 0.2}), "crash_20d")
        self.assertEqual(market_regime.classify_regime({"ret_20d": 0.05, "ret_60d": 0.02, "ann_vol_20d": 0.2}), "uptrend")
        rows = [
            {"strategy": "S", "timestamp": "2026-01-01", "net_return_after_cost": 0.01, "regime": "uptrend"},
            {"strategy": "S", "timestamp": "2026-01-02", "net_return_after_cost": -0.02, "regime": "crash_20d"},
        ]
        report = market_regime.bucket_report(rows)
        self.assertIn("S", report["strategy_summary"])
        self.assertEqual(report["strategy_summary"]["S"]["signals"], 2)

    def test_regime_exposure_gate_is_no_send_and_can_hold_cash(self):
        index_rows = []
        for i in range(150):
            close = Decimal("100") + Decimal(i % 30)
            index_rows.append({"timestamp": f"2026-01-{i+1:03d}", "close_price": close})
        feats = {}
        for i, row in enumerate(index_rows):
            if i < 60:
                regime = "insufficient_index_history"
            elif i % 2 == 0:
                regime = "uptrend"
            else:
                regime = "weak_or_downtrend"
            feats[row["timestamp"]] = {"timestamp": row["timestamp"], "regime": regime, "ret_20d": 0.05, "ret_60d": 0.1, "ann_vol_20d": 0.2}
        gate = regime_exposure.gate_rules()["trend_constructive_only"]
        rows = regime_exposure.forward_rows(index_rows, feats, gate_name="trend_constructive_only", gate=gate, horizon=20, cost_pct=0.0046)
        self.assertTrue(any(r["allow_long_exposure"] for r in rows))
        self.assertTrue(any(not r["allow_long_exposure"] and r["gate_forward_return_after_cost_or_cash"] == 0.0 for r in rows))
        report = regime_exposure.evaluate_forward(rows, 0.7)
        self.assertIn("locked_test", report)

    def test_relative_strength_baskets_compare_top_to_full_universe(self):
        rows = [
            {"rebalance_date": "2026-01-01", "horizon": 20, "top_avg_return_after_cost": 0.01, "eligible_universe_avg_return_after_cost": 0.005, "kosdaq_forward_after_cost": 0.0, "excess_vs_eligible_universe": 0.005, "excess_vs_kosdaq": 0.01, "eligible_universe": 100},
            {"rebalance_date": "2026-02-01", "horizon": 20, "top_avg_return_after_cost": -0.02, "eligible_universe_avg_return_after_cost": 0.0, "kosdaq_forward_after_cost": 0.01, "excess_vs_eligible_universe": -0.02, "excess_vs_kosdaq": -0.03, "eligible_universe": 120},
            {"rebalance_date": "2026-03-01", "horizon": 60, "top_avg_return_after_cost": 0.03, "eligible_universe_avg_return_after_cost": 0.02, "kosdaq_forward_after_cost": 0.01, "excess_vs_eligible_universe": 0.01, "excess_vs_kosdaq": 0.02, "eligible_universe": 110},
            {"rebalance_date": "2026-04-01", "horizon": 60, "top_avg_return_after_cost": -0.01, "eligible_universe_avg_return_after_cost": 0.01, "kosdaq_forward_after_cost": 0.02, "excess_vs_eligible_universe": -0.02, "excess_vs_kosdaq": -0.03, "eligible_universe": 130},
        ]
        report = relative_strength.evaluate_baskets(rows, 0.5)
        self.assertIn("h20", report)
        self.assertIn("h60", report)
        self.assertIn("excess_vs_eligible_universe", report["h20"]["locked_test"])
        blks = relative_strength.blockers(report, {"unique_selected_symbols": 10, "max_symbol_share": 0.2}, min_locked_baskets=1)
        self.assertIn("h20_locked_not_above_eligible_universe", blks)
        self.assertIn("selected_symbol_breadth_too_low", blks)

    def test_event_liquidity_reaction_uses_next_open_and_no_send(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source_db = root / "candles.sqlite3"
            news_db = root / "news.sqlite3"
            symbol_map = root / "symbol_map.csv"
            rows = []
            for sym in ["AAA", "BBB"]:
                for i in range(50):
                    close = Decimal("100")
                    volume = Decimal("1000")
                    if sym == "AAA" and i == 24:
                        volume = Decimal("3000")
                    if sym == "AAA" and i == 28:
                        close = Decimal("110")
                    rows.append((sym, "1d", f"2026-01-{i+1:02d}", str(close), str(close), str(volume), "KRW", "{}", "now"))
            con = sqlite3.connect(source_db)
            con.execute("CREATE TABLE candle_cache (symbol TEXT, interval TEXT, timestamp TEXT, open_price TEXT, close_price TEXT, volume TEXT, currency TEXT, raw_json TEXT, fetched_at TEXT)")
            con.executemany("INSERT INTO candle_cache VALUES (?,?,?,?,?,?,?,?,?)", rows)
            con.commit()
            con.close()

            con = sqlite3.connect(news_db)
            con.execute("CREATE TABLE news_context (id INTEGER PRIMARY KEY AUTOINCREMENT, provider TEXT, query TEXT, title TEXT, url TEXT, source TEXT, published_at TEXT, sentiment REAL, summary TEXT, raw_json TEXT, created_at TEXT)")
            con.execute("INSERT INTO news_context(provider, query, title, url, source, published_at, sentiment, summary, raw_json, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                        ("naver", "AAA 주가", "AAA 공급계약 수주", "https://example.com/a", "unit", "Sun, 25 Jan 2026 10:00:00 +0900", None, "대형 공급계약 체결", "{}", "2026-01-25T01:00:00+00:00"))
            con.commit()
            con.close()
            symbol_map.write_text("query,symbol,name\nAAA 주가,AAA,AAA\n")
            args = argparse.Namespace(
                source_db=str(source_db),
                news_db=str(news_db),
                symbol_map=str(symbol_map),
                out=str(root / "out.json"),
                rows_out=str(root / "rows.csv"),
                hypothesis_id="TEST_EVENT",
                horizon=3,
                lookback=20,
                roundtrip_cost_pct="0.0046",
                min_volume_multiple="1.5",
                min_avg_turnover_20d="1",
                min_close_price="1",
                train_fraction="0.5",
                min_total_events=1,
                min_event_symbols=1,
                min_locked_events=1,
                news_limit=0,
            )
            report = event_reaction.run(args)
            self.assertFalse(report["live_order_allowed"])
            self.assertFalse(report["order_sent"])
            self.assertEqual(report["evaluable_event_signals"], 1)
            sig = report["sample_signals"][0]
            self.assertEqual(sig["entry_date"], "2026-01-26")
            self.assertEqual(sig["exit_date"], "2026-01-29")
            self.assertAlmostEqual(sig["volume_multiple"], 3.0)
            self.assertAlmostEqual(sig["net_return_after_cost"], 0.0954)
            self.assertGreater(sig["excess_vs_eligible_universe"], 0)
            self.assertTrue(Path(args.rows_out).exists())

    def test_event_liquidity_reaction_tracks_pending_future_and_market_filter(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source_db = root / "candles.sqlite3"
            news_db = root / "news.sqlite3"
            symbol_map = root / "symbol_map.csv"
            rows = []
            for i in range(50):
                close = Decimal("100")
                volume = Decimal("1000")
                if i == 48:
                    volume = Decimal("3000")
                rows.append(("AAA", "1d", f"2026-01-{i+1:02d}", str(close), str(close), str(volume), "KRW", "{}", "now"))
            con = sqlite3.connect(source_db)
            con.execute("CREATE TABLE candle_cache (symbol TEXT, interval TEXT, timestamp TEXT, open_price TEXT, close_price TEXT, volume TEXT, currency TEXT, raw_json TEXT, fetched_at TEXT)")
            con.executemany("INSERT INTO candle_cache VALUES (?,?,?,?,?,?,?,?,?)", rows)
            con.commit()
            con.close()

            con = sqlite3.connect(news_db)
            con.execute("CREATE TABLE news_context (id INTEGER PRIMARY KEY AUTOINCREMENT, provider TEXT, query TEXT, title TEXT, url TEXT, source TEXT, published_at TEXT, sentiment REAL, summary TEXT, raw_json TEXT, created_at TEXT)")
            con.execute("INSERT INTO news_context(provider, query, title, url, source, published_at, sentiment, summary, raw_json, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                        ("naver", "AAA 주가", "AAA 공급계약 수주", "https://example.com/a", "unit", "Thu, 49 Jan 2026 10:00:00 +0900", None, "대형 공급계약 체결", "{}", "2026-01-49T01:00:00+00:00"))
            con.execute("INSERT INTO news_context(provider, query, title, url, source, published_at, sentiment, summary, raw_json, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                        ("naver", "ZZZ 주가", "ZZZ 공급계약 수주", "https://example.com/z", "unit", "Thu, 49 Jan 2026 10:00:00 +0900", None, "대형 공급계약 체결", "{}", "2026-01-49T01:00:00+00:00"))
            con.commit()
            con.close()
            symbol_map.write_text("query,symbol,name,market\nAAA 주가,AAA,AAA,KOSDAQ\nZZZ 주가,ZZZ,ZZZ,KOSPI\n")
            args = argparse.Namespace(
                source_db=str(source_db),
                news_db=str(news_db),
                symbol_map=str(symbol_map),
                out=str(root / "out.json"),
                rows_out=str(root / "rows.csv"),
                pending_out=str(root / "pending.jsonl"),
                allowed_markets="KOSDAQ",
                hypothesis_id="TEST_EVENT",
                horizon=3,
                lookback=20,
                roundtrip_cost_pct="0.0046",
                min_volume_multiple="1.5",
                min_avg_turnover_20d="1",
                min_close_price="1",
                train_fraction="0.5",
                min_total_events=1,
                min_event_symbols=1,
                min_locked_events=1,
                news_limit=0,
            )
            report = event_reaction.run(args)
            self.assertEqual(report["evaluable_event_signals"], 0)
            self.assertEqual(report["pending_future_event_signals"], 1)
            self.assertEqual(report["skipped"].get("symbol_map_market_excluded"), 1)
            self.assertEqual(report["skipped"].get("pending_future_horizon"), 1)
            pending_rows = [json.loads(line) for line in Path(args.pending_out).read_text().splitlines()]
            self.assertEqual(len(pending_rows), 1)
            self.assertFalse(pending_rows[0]["order_sent"])
            self.assertFalse(pending_rows[0]["live_order_allowed"])

    def test_event_liquidity_reaction_fails_closed_without_news_rows(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            news_db = root / "news.sqlite3"
            symbol_map = root / "symbol_map.csv"
            con = sqlite3.connect(news_db)
            con.execute("CREATE TABLE news_context (id INTEGER PRIMARY KEY AUTOINCREMENT, provider TEXT, query TEXT, title TEXT, url TEXT, source TEXT, published_at TEXT, sentiment REAL, summary TEXT, raw_json TEXT, created_at TEXT)")
            con.commit()
            con.close()
            symbol_map.write_text("query,symbol,name\nAAA 주가,AAA,AAA\n")
            args = argparse.Namespace(
                source_db=str(root / "missing_candles.sqlite3"),
                news_db=str(news_db),
                symbol_map=str(symbol_map),
                out=str(root / "out.json"),
                rows_out=str(root / "rows.csv"),
                hypothesis_id="TEST_EVENT",
                horizon=3,
                lookback=20,
                roundtrip_cost_pct="0.0046",
                min_volume_multiple="1.5",
                min_avg_turnover_20d="1",
                min_close_price="1",
                train_fraction="0.5",
                min_total_events=1,
                min_event_symbols=1,
                min_locked_events=1,
                news_limit=0,
            )
            report = event_reaction.run(args)
            self.assertFalse(report["live_order_allowed"])
            self.assertIn("no_news_context_source_rows", report["blockers"])
            self.assertIn("no_evaluable_event_liquidity_signals", report["blockers"])


if __name__ == "__main__":
    unittest.main()
