import json
import math
import sqlite3
import tempfile
import unittest
from dataclasses import asdict
from datetime import date, timedelta
from pathlib import Path

import kr_foreign_microstructure_research as foreign


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
        "beta60": 1.0,
        "ivol60": 0.03,
        "history60": 60,
        "max_return20": 0.08,
        "amihud20": 1e-10,
        "volume_z50": -1.2,
        "prev_low": 1750.0,
        "prev_gap1": -0.01,
        "prev_intraday_return1": 0.02,
        "max_return60": 0.15,
        "prior_close_to_high252": 0.8,
        "feature_history252": 252,
        "prev_return1": -0.03,
        "prev_return10": -0.12,
        "cs_spread20": 0.01,
        "roll_spread60": 0.01,
        "zero_return_share20": 0.05,
        "dollar_volume_cv20": 0.2,
        "downside_semivol60": 0.02,
        "downside_beta60": 0.8,
        "skew60": -0.2,
        "parkinson_vol20": 0.02,
        "yang_zhang_vol20": 0.03,
        "overnight_sum20": -0.1,
        "intraday_sum20": 0.1,
        "historical_gap_z60": -2.5,
        "feature_history60": 60,
        "market_cs_spread_z60": 0.0,
        "market_zero_return_z60": 0.0,
        "market_range_vol_z60": 0.0,
        "market_gap_mean_z60": 0.0,
        "market_gap_breadth_z60": 0.0,
    }
    values.update(overrides)
    return foreign.ForeignEvent(**values)


def market(**overrides):
    values = {
        "date": "2026-01-02",
        "open_vs_sma5": -0.02,
        "index_gap": -0.02,
        "gap2_count": 10,
        "gap5_count": 4,
        "us_session_date": "2026-01-01",
        "qqq_return": -0.02,
        "spy_return": -0.015,
        "qqq_range": 0.03,
        "qqq_vol20": 0.02,
        "us_history20": 20,
        "kosdaq_us_beta60": 0.5,
        "kosdaq_us_residual_gap": -0.01,
        "weekday": 4,
        "trading_day_of_month": 2,
        "trading_days_in_month": 20,
    }
    values.update(overrides)
    return foreign.ForeignMarket(**values)


class KrForeignMicrostructureResearchTests(unittest.TestCase):
    def test_declared_research_scope_is_broad_and_unique(self):
        methods = foreign.methods()
        names = [method.name for method in methods]
        families = {method.family for method in methods if method.family != "anchor"}
        source_keys = {source["key"] for source in foreign.SOURCES}
        self.assertGreaterEqual(len(foreign.SOURCES), 12)
        self.assertGreaterEqual(len(methods) - 1, 20)
        self.assertGreaterEqual(len(families), 3)
        self.assertEqual(len(names), len(set(names)))
        self.assertTrue(
            all(key in source_keys for method in methods for key in method.source_keys)
        )

    def test_filters_use_prior_features_and_fixed_cross_sectional_quantiles(self):
        low = event(symbol="A", cs_spread20=0.01, historical_gap_z60=-3.1)
        middle = event(symbol="B", cs_spread20=0.02, historical_gap_z60=-2.1)
        high = event(symbol="C", cs_spread20=0.03, historical_gap_z60=-1.0)
        self.assertEqual(
            [row.symbol for row in foreign.apply_filter([high, low, middle], "cs_bottom_half")],
            ["A", "B"],
        )
        self.assertEqual(
            [row.symbol for row in foreign.apply_filter([high, low, middle], "gap_z_minus3")],
            ["A"],
        )
        self.assertEqual(
            {
                row.symbol
                for row in foreign.apply_filter(
                    [high, low, middle], "gap_z_above_minus3"
                )
            },
            {"B", "C"},
        )

    def test_composite_rank_is_deterministic(self):
        liquid = event(
            symbol="A",
            cs_spread20=0.01,
            zero_return_share20=0.0,
            roll_spread60=0.01,
            dollar_volume_cv20=0.1,
        )
        costly = event(
            symbol="B",
            cs_spread20=0.04,
            zero_return_share20=0.4,
            roll_spread60=0.05,
            dollar_volume_cv20=1.0,
        )
        ranked = foreign.ranked([costly, liquid], "liquidity_composite")
        self.assertEqual([row.symbol for row in ranked], ["A", "B"])

    def test_global_nonlinearity_rules_are_directional(self):
        self.assertTrue(
            foreign.market_passes(market(qqq_return=-0.011), "qqq_absolute_1pct")
        )
        self.assertTrue(
            foreign.market_passes(market(qqq_return=0.012), "qqq_absolute_1pct")
        )
        self.assertTrue(foreign.market_passes(market(qqq_return=0.012), "qqq_up_1pct"))
        self.assertFalse(
            foreign.market_passes(market(qqq_return=-0.012), "qqq_up_1pct")
        )
        quiet = event(symbol="QUIET", parkinson_vol20=0.01)
        volatile = event(symbol="VOLATILE", parkinson_vol20=0.05)
        self.assertEqual(
            foreign.ranked([volatile, quiet], "high_parkinson")[0].symbol,
            "VOLATILE",
        )

    def test_new_gap_geometry_and_prior_state_rules_are_directional(self):
        partial = event(
            symbol="PARTIAL",
            open=1800.0,
            prev_low=1750.0,
            prev_gap1=0.02,
            prev_intraday_return1=-0.03,
            max_return60=0.10,
        )
        full = event(
            symbol="FULL",
            open=1700.0,
            prev_low=1750.0,
            prev_gap1=-0.02,
            prev_intraday_return1=0.03,
            max_return60=0.50,
        )
        rows = [full, partial]

        self.assertEqual(
            [row.symbol for row in foreign.apply_filter(rows, "partial_gap")],
            ["PARTIAL"],
        )
        self.assertEqual(
            [row.symbol for row in foreign.apply_filter(rows, "full_gap")],
            ["FULL"],
        )
        self.assertEqual(
            [row.symbol for row in foreign.apply_filter(rows, "prior_gap_positive")],
            ["PARTIAL"],
        )
        self.assertEqual(
            [
                row.symbol
                for row in foreign.apply_filter(rows, "prior_intraday_loser")
            ],
            ["PARTIAL"],
        )
        self.assertEqual(
            foreign.ranked(rows, "low_max60")[0].symbol,
            "PARTIAL",
        )
        near_high = event(
            symbol="NEAR_HIGH", prior_close_to_high252=0.98
        )
        far_high = event(
            symbol="FAR_HIGH", prior_close_to_high252=0.40
        )
        self.assertEqual(
            foreign.ranked([far_high, near_high], "near_52w_high")[0].symbol,
            "NEAR_HIGH",
        )
        self.assertEqual(
            [
                row.symbol
                for row in foreign.apply_filter(
                    [far_high, near_high], "near_52w_high"
                )
            ],
            ["NEAR_HIGH"],
        )
        low_beta = event(symbol="LOW_BETA", beta60=0.5)
        high_beta = event(symbol="HIGH_BETA", beta60=1.5)
        self.assertEqual(
            foreign.ranked([high_beta, low_beta], "low_beta")[0].symbol,
            "LOW_BETA",
        )
        self.assertEqual(
            [
                row.symbol
                for row in foreign.apply_filter(
                    [high_beta, low_beta], "beta_top_half"
                )
            ],
            ["HIGH_BETA"],
        )

    def test_official_alert_filters_match_point_in_time_flags(self):
        clean = event(symbol="CLEAN")
        attention = event(symbol="ATTN", official_attention_active=True)
        warning = event(symbol="WARN", official_warning_active=True)
        risk = event(symbol="RISK", official_risk_active=True)
        rows = [clean, attention, warning, risk]

        self.assertEqual(
            [
                row.symbol
                for row in foreign.apply_filter(
                    rows, "exclude_official_warning_risk"
                )
            ],
            ["CLEAN", "ATTN"],
        )
        self.assertEqual(
            [
                row.symbol
                for row in foreign.apply_filter(rows, "exclude_all_official_alerts")
            ],
            ["CLEAN"],
        )
        self.assertEqual(
            [
                row.symbol
                for row in foreign.apply_filter(rows, "official_alert_active")
            ],
            ["ATTN", "WARN", "RISK"],
        )

    def test_warning_interval_loader_uses_designation_and_exclusive_release(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "warnings.json"
            path.write_text(
                json.dumps(
                    {
                        "source": {"name": "KRX KIND"},
                        "rows_collected": 2,
                        "point_in_time_usable_rows": 1,
                        "all_chunk_counts_match": True,
                        "ticker_resolution_complete": False,
                        "point_in_time_filter_complete": False,
                        "unresolved_issuer_codes": ["99999"],
                        "release_boundary_rule": "exclusive release",
                        "rows": [
                            {
                                "ticker": "123450",
                                "category": "warning",
                                "designation_date": "2024-01-02",
                                "release_date": "2024-01-05",
                            },
                            {
                                "ticker": "",
                                "category": "risk",
                                "designation_date": "2024-01-02",
                                "release_date": "2024-01-05",
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )

            intervals, audit = foreign.load_official_warning_intervals(str(path))

        self.assertEqual(
            intervals,
            {"123450": [("warning", "2024-01-02", "2024-01-05")]},
        )
        self.assertEqual(audit["intervals_loaded"], 1)
        self.assertFalse(audit["point_in_time_filter_complete"])
        self.assertEqual(audit["malformed_or_unresolved_rows_skipped"], 2)

    def test_volume_relaxed_universe_is_explicit_and_bounded(self):
        anchor = foreign.ForeignMethod("anchor", "anchor")
        relaxed = foreign.ForeignMethod(
            "relaxed", "volume_reversal", universe="volume_relaxed"
        )
        context = market()
        row = event(prev_vol_ratio=1.2)
        self.assertFalse(foreign.base_passes(row, context, anchor))
        self.assertTrue(foreign.base_passes(row, context, relaxed))
        self.assertFalse(
            foreign.base_passes(event(prev_vol_ratio=2.0), context, relaxed)
        )
        cap_125 = foreign.ForeignMethod(
            "cap125", "volume_sensitivity", universe="volume_cap_125"
        )
        self.assertTrue(
            foreign.base_passes(event(prev_vol_ratio=1.249), context, cap_125)
        )
        self.assertFalse(
            foreign.base_passes(event(prev_vol_ratio=1.25), context, cap_125)
        )

    def test_prior_loss_volume_interactions_use_completed_features(self):
        low_volume = event(
            symbol="LOW", prev_return1=-0.05, prev_return10=-0.20, prev_vol_ratio=0.5
        )
        high_volume = event(
            symbol="HIGH", prev_return1=-0.04, prev_return10=-0.10, prev_vol_ratio=1.5
        )
        winner = event(
            symbol="WIN", prev_return1=0.03, prev_return10=0.05, prev_vol_ratio=1.5
        )
        rows = [winner, low_volume, high_volume]

        self.assertEqual(
            [row.symbol for row in foreign.apply_filter(rows, "prior1_loser")],
            ["LOW", "HIGH"],
        )
        self.assertEqual(
            [
                row.symbol
                for row in foreign.apply_filter(rows, "prior1_high_volume_loser")
            ],
            ["HIGH"],
        )
        self.assertEqual(
            foreign.ranked(rows, "prior1_volume_reversal")[0].symbol, "HIGH"
        )
        self.assertEqual(foreign.ranked(rows, "prior10_loss")[0].symbol, "LOW")
        stressed = event(
            symbol="STRESS", prev_return1=-0.08, market_range_vol_z60=1.2
        )
        calm = event(
            symbol="CALM", prev_return1=-0.04, market_range_vol_z60=0.2
        )
        self.assertEqual(
            [
                row.symbol
                for row in foreign.apply_filter(
                    [calm, stressed], "prior1_loser_market_vol_high"
                )
            ],
            ["STRESS"],
        )
        self.assertEqual(
            foreign.ranked([calm, stressed], "prior1_loss")[0].symbol,
            "STRESS",
        )

    def test_tick_size_and_stress_are_price_band_aware(self):
        self.assertEqual(foreign.tick_size(1999.0), 1.0)
        self.assertEqual(foreign.tick_size(2000.0), 5.0)
        self.assertEqual(foreign.tick_size(5000.0), 10.0)
        self.assertEqual(foreign.tick_size(1500.0, "2023-01-24"), 5.0)
        self.assertEqual(foreign.tick_size(1500.0, "2023-01-25"), 1.0)
        self.assertEqual(foreign.tick_size(15000.0, "2023-01-24"), 50.0)
        self.assertEqual(foreign.tick_size(15000.0, "2023-01-25"), 10.0)
        trade = foreign._tick_stress_trade(
            event(open=2000.0, high=2050.0, low=1990.0, close=2020.0),
            market(),
            roundtrip_cost=0.0,
            adverse_ticks=1,
        )
        self.assertIsNotNone(trade)
        self.assertEqual(trade.entry, 2005.0)
        self.assertEqual(trade.exit, 2015.0)
        old_trade = foreign._tick_stress_trade(
            event(
                date="2023-01-24",
                open=1500.0,
                high=1550.0,
                low=1490.0,
                close=1520.0,
            ),
            market(date="2023-01-24"),
            roundtrip_cost=0.0,
            adverse_ticks=1,
        )
        self.assertIsNotNone(old_trade)
        self.assertEqual(old_trade.entry, 1505.0)
        self.assertEqual(old_trade.exit, 1515.0)
        self.assertIsNone(
            foreign._tick_stress_trade(
                event(open=2000.0, high=2000.0, low=1990.0, close=2000.0),
                market(),
                roundtrip_cost=0.0,
                adverse_ticks=1,
            )
        )

    def test_us_context_uses_strictly_prior_completed_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            us_db = Path(tmp) / "us.sqlite3"
            connection = sqlite3.connect(us_db)
            connection.execute(
                "CREATE TABLE candle_cache (symbol TEXT, timestamp TEXT, interval TEXT, "
                "high_price REAL, low_price REAL, close_price REAL)"
            )
            for symbol in ("SPY", "QQQ"):
                connection.executemany(
                    "INSERT INTO candle_cache VALUES (?,?,?,?,?,?)",
                    [
                        (symbol, "2025-01-08", "1d", 101.0, 99.0, 100.0),
                        (symbol, "2025-01-09", "1d", 100.0, 97.0, 98.0),
                        (symbol, "2025-01-10", "1d", 120.0, 110.0, 115.0),
                    ],
                )
            connection.commit()
            connection.close()
            index_rows = [
                {
                    "date": (date(2025, 1, 1) + timedelta(days=offset)).isoformat(),
                    "open": 100.0,
                    "high": 101.0,
                    "low": 99.0,
                    "close": 100.0,
                }
                for offset in range(10)
            ]
            target = index_rows[-1]["date"]
            contexts = foreign.build_markets(
                [event(date=target)], index_rows, str(us_db)
            )

        self.assertEqual(contexts[target].us_session_date, "2025-01-09")
        self.assertAlmostEqual(contexts[target].qqq_return, -0.02)
        self.assertLess(contexts[target].us_session_date, target)

    def test_feature_loader_excludes_current_bar_from_rolling_features(self):
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
            for offset in range(100):
                current = start + timedelta(days=offset)
                target = offset == 98
                open_price = 900.0 if target else 1000.0
                high = 2000.0 if target else 1010.0
                low = 500.0 if target else 990.0
                close = 1500.0 if target else 1000.0
                volume = 1_000_000.0 if target else 100.0 + offset
                rows.append(
                    ("A", current.isoformat(), "1d", open_price, high, low, close, volume)
                )
                index_rows.append(
                    {"date": current.isoformat(), "open": 100.0, "close": 100.0}
                )
            connection.executemany("INSERT INTO candle_cache VALUES (?,?,?,?,?,?,?,?)", rows)
            connection.commit()
            connection.close()
            target_date = (start + timedelta(days=98)).isoformat()

            loaded = foreign.load_feature_rows(
                str(db_path), index_rows, start=target_date, end=target_date
            )

        row = loaded[(target_date, "A")]
        self.assertGreaterEqual(row["feature_history60"], 40)
        self.assertLess(row["parkinson_vol20"], 0.02)
        self.assertLess(row["yang_zhang_vol20"], 0.05)
        self.assertLess(row["dollar_volume_cv20"], 0.2)
        self.assertTrue(math.isfinite(row["historical_gap_z60"]))
        self.assertEqual(row["prev_low"], 990.0)
        self.assertEqual(row["prev_gap1"], 0.0)
        self.assertEqual(row["prev_intraday_return1"], 0.0)
        self.assertEqual(row["max_return60"], 0.0)
        self.assertGreater(row["prior_close_to_high252"], 0.9)
        self.assertLess(row["prior_close_to_high252"], 1.0)
        self.assertEqual(row["feature_history252"], 97)
        self.assertEqual(row["prev_return1"], 0.0)
        self.assertEqual(row["prev_return10"], 0.0)

    def test_database_universe_audit_detects_survivor_shaped_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "candles.sqlite3"
            connection = sqlite3.connect(db_path)
            connection.execute(
                "CREATE TABLE candle_cache (symbol TEXT, timestamp TEXT, interval TEXT)"
            )
            connection.executemany(
                "INSERT INTO candle_cache VALUES (?,?,?)",
                [
                    ("A", "2011-01-03", "1d"),
                    ("A", "2026-07-16", "1d"),
                    ("B", "2020-01-02", "1d"),
                    ("B", "2026-07-16", "1d"),
                ],
            )
            connection.commit()
            connection.close()

            result = foreign.database_universe_audit(str(db_path))

        self.assertEqual(result["total_symbols"], 2)
        self.assertEqual(result["interval_rows"], {"1d": 4})
        self.assertEqual(result["intraday_rows_available"], 0)
        self.assertEqual(result["symbols_ending_before_2025"], 0)
        self.assertEqual(result["symbols_present_by_end_2011"], 1)
        self.assertTrue(result["survivorship_shape_detected"])
        self.assertIn("current-survivor-shaped", foreign.survivorship_limit(result))

    def test_delisted_metadata_exposure_is_labeled_as_symbol_overlap(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "candles.sqlite3"
            connection = sqlite3.connect(db_path)
            connection.execute(
                "CREATE TABLE research_delisted_source_metadata ("
                "symbol TEXT,company_name TEXT,category TEXT,delisting_date TEXT,status TEXT)"
            )
            connection.execute(
                "INSERT INTO research_delisted_source_metadata VALUES (?,?,?,?,?)",
                ("OLD", "Old Corp", "distress_or_enforcement", "2020-01-31", "ok"),
            )
            connection.commit()
            connection.close()

            def trade(symbol, current, pnl):
                return foreign.Trade(
                    date=current,
                    exit_date=current,
                    symbol=symbol,
                    entry=1000.0,
                    exit=1000.0,
                    quantity=10,
                    invested=10_000.0,
                    gross_pnl=pnl,
                    net_pnl=pnl,
                    net_return_on_capital=pnl / 10_000.0,
                    reason="close_proxy",
                    gap=-0.05,
                    avg_dollar_volume20=1.0,
                    avg_range20=0.01,
                    prev_return5=0.0,
                    market_open_vs_sma5=-0.02,
                )

            result = foreign.delisted_metadata_exposure_audit(
                str(db_path),
                {
                    "anchor": [
                        trade("OLD", "2019-01-02", -100.0),
                        trade("LIVE", "2019-01-03", 50.0),
                        trade("OLD", "2024-01-02", 200.0),
                    ]
                },
                start="2011-01-01",
                end="2023-12-31",
            )

        self.assertTrue(result["available"])
        self.assertIn("not row-level source lineage", result["lineage_warning"])
        anchor = result["methods"]["anchor"]
        self.assertEqual(anchor["trades"], 2)
        self.assertEqual(anchor["metadata_overlap_trades"], 1)
        self.assertEqual(anchor["metadata_overlap_net_pnl"], -100.0)
        self.assertEqual(
            anchor["category_counts"], {"distress_or_enforcement": 1}
        )

    def test_execution_observation_audit_does_not_overstate_small_sample(self):
        with tempfile.TemporaryDirectory() as tmp:
            spread_path = Path(tmp) / "spread.jsonl"
            paper_path = Path(tmp) / "paper.jsonl"
            spread_path.write_text(
                json.dumps(
                    {
                        "observed_at": "2026-01-02T00:01:00+00:00",
                        "symbol": "A",
                        "spread": {"available": True, "spread_bps": "15.0"},
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            paper_path.write_text(
                json.dumps(
                    {
                        "observed_at": "2026-01-02T00:01:00+00:00",
                        "status": "paper_only",
                        "order_sent": False,
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            result = foreign.execution_observation_audit(
                str(spread_path), str(paper_path)
            )

        self.assertEqual(result["spread_history"]["near_0901_observations"], 1)
        self.assertEqual(result["spread_history"]["median_spread_bps"], 15.0)
        self.assertEqual(result["paper_observations"]["orders_sent"], 0)
        self.assertFalse(result["sufficient_to_calibrate_0901_execution"])

    def test_cscv_and_reality_check_use_selection_window(self):
        dates = [f"2011-01-{day:02d}" for day in range(1, 25)]
        anchor = [
            foreign.Trade(
                date=current,
                exit_date=current,
                symbol="A",
                entry=1.0,
                exit=1.0,
                quantity=1,
                invested=1.0,
                gross_pnl=0.0,
                net_pnl=0.0,
                net_return_on_capital=0.0,
                reason="close_proxy",
                gap=-0.05,
                avg_dollar_volume20=1.0,
                avg_range20=0.01,
                prev_return5=0.0,
                market_open_vs_sma5=-0.02,
            )
            for current in dates
        ]
        candidate = [
            foreign.Trade(
                **{
                    **asdict(row),
                    "symbol": "B",
                    "net_pnl": 1.0 if index % 2 == 0 else -0.5,
                    "net_return_on_capital": 0.01 if index % 2 == 0 else -0.005,
                }
            )
            for index, row in enumerate(anchor)
        ]
        trades = {"anchor": anchor, "candidate": candidate}
        pbo = foreign.cscv_pbo_diagnostic(trades, dates)
        reality = foreign.studentized_reality_check(
            trades, dates, samples=50, block_length=4, seed=7
        )
        self.assertTrue(pbo["available"])
        self.assertEqual(pbo["selection_window"], "2011-01-01~2023-12-31")
        self.assertTrue(reality["available"])
        self.assertEqual(reality["selection_window"], "2011-01-01~2023-12-31")

    def test_walk_forward_selection_ends_before_reused_recent_window(self):
        trades = {"anchor": [], "candidate": []}
        for year in range(2011, 2024):
            for day in range(1, 25):
                current = f"{year}-01-{day:02d}"
                anchor = foreign.Trade(
                    date=current,
                    exit_date=current,
                    symbol="A",
                    entry=1.0,
                    exit=1.0,
                    quantity=1,
                    invested=1.0,
                    gross_pnl=0.0,
                    net_pnl=1.0,
                    net_return_on_capital=0.01,
                    reason="close_proxy",
                    gap=-0.05,
                    avg_dollar_volume20=1.0,
                    avg_range20=0.01,
                    prev_return5=0.0,
                    market_open_vs_sma5=-0.02,
                )
                trades["anchor"].append(anchor)
                trades["candidate"].append(
                    foreign.Trade(
                        **{
                            **asdict(anchor),
                            "symbol": "B",
                            "net_pnl": 2.0,
                            "net_return_on_capital": 0.02,
                        }
                    )
                )

        result = foreign.walk_forward_method_selection(trades)

        self.assertEqual(result["selection_data_ends"], "2023-12-31")
        self.assertEqual([row["test_year"] for row in result["years"]], list(range(2016, 2024)))
        self.assertEqual(result["selected_counts"], {"candidate": 8})
        self.assertGreater(result["walk_forward_minus_anchor"], 0.0)

    def test_paired_block_bootstrap_reports_candidate_difference(self):
        dates = [f"2024-01-{day:02d}" for day in range(1, 21)]
        anchor = []
        candidate = []
        for current in dates:
            base = foreign.Trade(
                date=current,
                exit_date=current,
                symbol="A",
                entry=1.0,
                exit=1.0,
                quantity=1,
                invested=1.0,
                gross_pnl=0.0,
                net_pnl=0.0,
                net_return_on_capital=0.0,
                reason="close_proxy",
                gap=-0.05,
                avg_dollar_volume20=1.0,
                avg_range20=0.01,
                prev_return5=0.0,
                market_open_vs_sma5=-0.02,
            )
            anchor.append(base)
            candidate.append(
                foreign.Trade(
                    **{
                        **asdict(base),
                        "symbol": "B",
                        "net_pnl": 1.0,
                        "net_return_on_capital": 0.01,
                    }
                )
            )

        result = foreign.paired_block_bootstrap_difference(
            candidate,
            anchor,
            dates,
            start="2024-01-01",
            end="2024-01-31",
            samples=100,
            block_length=4,
            seed=7,
        )

        self.assertTrue(result["available"])
        self.assertEqual(result["point_estimate_pnl_difference"], 20.0)
        self.assertEqual(result["probability_candidate_beats_anchor"], 1.0)
        self.assertEqual(result["yearly_pnl_difference"], {"2024": 20.0})
        self.assertEqual(result["positive_years"], 1)
        self.assertEqual(result["negative_years"], 0)
        self.assertEqual(result["nonzero_difference_days"], 20)

    def test_paired_selection_audit_exposes_concentration_and_feature_shift(self):
        def trade(symbol, pnl):
            return foreign.Trade(
                date="2022-01-03",
                exit_date="2022-01-03",
                symbol=symbol,
                entry=1000.0,
                exit=1000.0,
                quantity=10,
                invested=10_000.0,
                gross_pnl=pnl,
                net_pnl=pnl,
                net_return_on_capital=pnl / 10_000.0,
                reason="close_proxy",
                gap=-0.05,
                avg_dollar_volume20=1.0,
                avg_range20=0.01,
                prev_return5=0.0,
                market_open_vs_sma5=-0.02,
            )

        result = foreign.paired_selection_change_audit(
            [trade("LOW_MAX", 100.0)],
            [trade("HIGH_MAX", -100.0)],
            [
                event(
                    date="2022-01-03", symbol="LOW_MAX", max_return60=0.10
                ),
                event(
                    date="2022-01-03", symbol="HIGH_MAX", max_return60=0.80
                ),
            ],
            start="2011-01-01",
            end="2023-12-31",
        )

        self.assertEqual(result["changed_selection_dates"], 1)
        self.assertEqual(result["changed_selection_total_pnl_difference"], 200.0)
        self.assertEqual(result["candidate_max60_median_on_changed_dates"], 0.10)
        self.assertEqual(result["anchor_max60_median_on_changed_dates"], 0.80)
        self.assertEqual(
            result["difference_after_removing_top5_positive_changed_dates"], 0.0
        )
        self.assertTrue(result["post_selection_diagnostic_only"])

    def test_path_ambiguity_and_cost_margin_are_explicit(self):
        ambiguous = event(
            open=1000.0,
            low=970.0,
            high=1130.0,
            close=1000.0,
            gap=-0.10,
        )
        path = foreign.daily_bar_path_audit(
            [ambiguous],
            {ambiguous.date: market()},
            foreign.ForeignMethod("anchor", "anchor"),
            start="2026-01-01",
            end="2026-01-31",
        )
        self.assertEqual(path["selected_days"], 1)
        self.assertEqual(path["both_stop_and_take"], 1)
        self.assertFalse(path["intraday_order_is_observed"])
        self.assertGreater(path["optimistic_take_first_uplift_before_cost"], 0.0)

        trade = foreign.Trade(
            date="2026-01-02",
            exit_date="2026-01-02",
            symbol="A",
            entry=100.0,
            exit=110.0,
            quantity=1,
            invested=100.0,
            gross_pnl=10.0,
            net_pnl=8.65,
            net_return_on_capital=0.0865,
            reason="close_proxy",
            gap=-0.05,
            avg_dollar_volume20=1.0,
            avg_range20=0.01,
            prev_return5=0.0,
            market_open_vs_sma5=-0.02,
        )
        cost = foreign.break_even_cost_diagnostic([trade])
        self.assertAlmostEqual(cost["break_even_roundtrip_cost"], 0.10)
        self.assertTrue(cost["not_a_fill_cost_estimate"])

    def test_historical_transaction_tax_schedule_and_cost_application(self):
        self.assertEqual(foreign.kosdaq_transaction_tax_rate("2019-05-29"), 0.0030)
        self.assertEqual(foreign.kosdaq_transaction_tax_rate("2019-05-30"), 0.0025)
        self.assertEqual(foreign.kosdaq_transaction_tax_rate("2021-01-01"), 0.0023)
        self.assertEqual(foreign.kosdaq_transaction_tax_rate("2023-01-01"), 0.0020)
        self.assertEqual(foreign.kosdaq_transaction_tax_rate("2024-01-01"), 0.0018)
        self.assertEqual(foreign.kosdaq_transaction_tax_rate("2025-01-01"), 0.0015)
        self.assertEqual(foreign.kosdaq_transaction_tax_rate("2026-01-01"), 0.0020)

        trade = foreign.Trade(
            date="2018-01-02",
            exit_date="2018-01-02",
            symbol="A",
            entry=100.0,
            exit=110.0,
            quantity=1,
            invested=100.0,
            gross_pnl=10.0,
            net_pnl=10.0,
            net_return_on_capital=0.001,
            reason="close_proxy",
            gap=-0.05,
            avg_dollar_volume20=1.0,
            avg_range20=0.01,
            prev_return5=0.0,
            market_open_vs_sma5=-0.02,
        )
        adjusted = foreign.apply_date_aware_costs(
            [trade], commission_per_side=0.001
        )[0]

        self.assertAlmostEqual(adjusted.net_pnl, 9.46)
        self.assertEqual(trade.net_pnl, 10.0)
        diagnostic = foreign.historical_cost_schedule_diagnostic([trade], [trade])
        json.dumps(diagnostic)
        self.assertEqual(
            diagnostic["sell_tax_schedule"]["through_2019_05_29"], 0.0030
        )

    def test_bootstrap_sensitivity_and_leave_one_year_out_are_reported(self):
        dates = ["2022-01-03", "2022-01-04", "2023-01-03", "2023-01-04"]
        anchor = []
        candidate = []
        for current in dates:
            base = foreign.Trade(
                date=current,
                exit_date=current,
                symbol="A",
                entry=1.0,
                exit=1.0,
                quantity=1,
                invested=1.0,
                gross_pnl=0.0,
                net_pnl=0.0,
                net_return_on_capital=0.0,
                reason="close_proxy",
                gap=-0.05,
                avg_dollar_volume20=1.0,
                avg_range20=0.01,
                prev_return5=0.0,
                market_open_vs_sma5=-0.02,
            )
            anchor.append(base)
            candidate.append(
                foreign.Trade(
                    **{
                        **asdict(base),
                        "symbol": "B",
                        "net_pnl": 1.0,
                        "net_return_on_capital": 0.01,
                    }
                )
            )
        sensitivity = foreign.paired_block_bootstrap_sensitivity(
            candidate,
            anchor,
            dates,
            start="2022-01-01",
            end="2023-12-31",
            samples=20,
            block_lengths=(2, 4),
            seed=7,
        )
        leave_one_out = foreign.leave_one_year_out_difference(
            candidate,
            anchor,
            start="2022-01-01",
            end="2023-12-31",
        )
        leaders = foreign.yearly_method_leaders(
            {"anchor": anchor, "candidate": candidate},
            ("anchor", "candidate"),
            start="2022-01-01",
            end="2023-12-31",
        )

        self.assertEqual(set(sensitivity["results"]), {"2", "4"})
        self.assertTrue(leave_one_out["all_leave_one_year_out_positive"])
        self.assertEqual(leave_one_out["minimum_remaining_difference"], 2.0)
        self.assertEqual(leaders["leader_counts"], {"candidate": 2})
        self.assertTrue(leaders["stable_single_winner"])

    def test_tick_random_rank_benchmark_is_deterministic(self):
        events = [
            event(symbol="LOW", open=1000.0, high=1030.0, low=990.0, close=1020.0),
            event(symbol="HIGH", open=2000.0, high=2050.0, low=1990.0, close=2010.0),
        ]
        markets = {"2026-01-02": market()}

        first = foreign.tick_random_rank_benchmark(
            events,
            markets,
            start="2026-01-01",
            end="2026-01-31",
            samples=100,
            seed=7,
        )
        second = foreign.tick_random_rank_benchmark(
            events,
            markets,
            start="2026-01-01",
            end="2026-01-31",
            samples=100,
            seed=7,
        )

        self.assertEqual(first, second)
        self.assertEqual(first["candidate_days"], 1)
        self.assertEqual(first["samples"], 100)

    def test_selection_never_authorizes_live_change(self):
        decision = foreign.selection_decision(
            [
                {
                    "method": {"name": "anchor"},
                    "pretest_score": 1.0,
                    "pretest_passed": True,
                    "profiles": {},
                    "adverse_harsh": {},
                }
            ]
        )
        self.assertFalse(decision["historical_gate_passed"])
        self.assertFalse(decision["live_change_accepted"])
        self.assertEqual(decision["recommended_research_strategy"], "anchor")

    def test_selection_comparison_aggregates_only_2011_2023_windows(self):
        row = {
            "profiles": {
                "harsh": {
                    "train_2011_2018": {
                        "metrics": {"total_pnl": 10.0, "mdd_on_capital": 0.1},
                        "miss_top_winners_25pct": {"total_pnl": 4.0},
                    },
                    "validation_2019_2023": {
                        "metrics": {"total_pnl": 20.0, "mdd_on_capital": 0.2},
                        "miss_top_winners_25pct": {"total_pnl": 5.0},
                    },
                }
            },
            "adverse_harsh": {
                "train_2011_2018": {"metrics": {"total_pnl": 3.0}},
                "validation_2019_2023": {"metrics": {"total_pnl": 7.0}},
            },
            "tick2_harsh": {
                "train_2011_2018": {"metrics": {"total_pnl": 6.0}},
                "validation_2019_2023": {"metrics": {"total_pnl": 8.0}},
            },
        }

        result = foreign._selection_comparison(row)

        self.assertEqual(result["harsh_total_pnl"], 30.0)
        self.assertEqual(result["adverse_total_pnl"], 10.0)
        self.assertEqual(result["tick2_total_pnl"], 14.0)
        self.assertEqual(result["top25_removed_total_pnl"], 9.0)
        self.assertEqual(result["max_window_mdd"], 0.2)

    def test_influence_gate_rejects_top_five_dependent_difference(self):
        def trade(current, symbol, pnl):
            return foreign.Trade(
                date=current,
                exit_date=current,
                symbol=symbol,
                entry=1.0,
                exit=1.0,
                quantity=1,
                invested=1.0,
                gross_pnl=pnl,
                net_pnl=pnl,
                net_return_on_capital=pnl,
                reason="close_proxy",
                gap=-0.05,
                avg_dollar_volume20=1.0,
                avg_range20=0.01,
                prev_return5=0.0,
                market_open_vs_sma5=-0.02,
            )

        anchor = []
        candidate = []
        for index in range(25):
            current = f"2022-01-{index + 1:02d}"
            anchor.append(trade(current, "A", 0.0))
            candidate.append(
                trade(current, "B", 100.0 if index < 5 else -20.0)
            )

        result = foreign.selection_influence_check(candidate, anchor)

        self.assertEqual(result["changed_dates"], 25)
        self.assertLess(result["difference_after_removing_top5_positive_dates"], 0)
        self.assertFalse(result["passed"])

    def test_influence_gate_honors_selection_window(self):
        def trade(current, pnl):
            return foreign.Trade(
                date=current,
                exit_date=current,
                symbol="A",
                entry=1.0,
                exit=1.0,
                quantity=1,
                invested=1.0,
                gross_pnl=pnl,
                net_pnl=pnl,
                net_return_on_capital=pnl,
                reason="close_proxy",
                gap=-0.05,
                avg_dollar_volume20=1.0,
                avg_range20=0.01,
                prev_return5=0.0,
                market_open_vs_sma5=-0.02,
            )

        anchor = [trade("2023-12-29", 0.0), trade("2024-01-02", 0.0)]
        candidate = [trade("2023-12-29", 10.0), trade("2024-01-02", 1_000.0)]

        result = foreign.selection_influence_check(
            candidate,
            anchor,
            start=foreign.SELECTION_START,
            end=foreign.SELECTION_END,
        )

        self.assertEqual(
            result["window"],
            {"start": foreign.SELECTION_START, "end": foreign.SELECTION_END},
        )
        self.assertEqual(result["changed_dates"], 1)
        self.assertEqual(result["total_pnl_difference"], 10.0)

    def test_selection_functional_stability_replays_fixed_checks(self):
        dates = [
            (date(2011, 1, 3) + timedelta(days=index)).isoformat()
            for index in range(60)
        ] + [
            (date(2019, 1, 2) + timedelta(days=index)).isoformat()
            for index in range(30)
        ]

        def rows(symbol, win_pnl, loss_pnl):
            result = []
            for index, current in enumerate(dates):
                pnl = loss_pnl if index % 10 == 0 else win_pnl
                result.append(
                    foreign.Trade(
                        date=current,
                        exit_date=current,
                        symbol=symbol,
                        entry=1000.0,
                        exit=1000.0,
                        quantity=10,
                        invested=10_000.0,
                        gross_pnl=pnl,
                        net_pnl=pnl,
                        net_return_on_capital=pnl / 10_000.0,
                        reason="close_proxy",
                        gap=-0.05,
                        avg_dollar_volume20=1.0,
                        avg_range20=0.01,
                        prev_return5=0.0,
                        market_open_vs_sma5=-0.02,
                    )
                )
            return result

        profiles = {
            "anchor": rows("A", 50.0, -100.0),
            "candidate": rows("B", 100.0, -20.0),
        }
        result = foreign.selection_functional_block_stability(
            profiles,
            profiles,
            profiles,
            dates,
            observed_selected="candidate",
            samples=10,
            block_length=3,
            seed=7,
        )

        self.assertTrue(result["available"])
        self.assertEqual(result["selected_counts"], {"candidate": 10})
        self.assertEqual(result["probability_any_incremental_passer"], 1.0)
        self.assertEqual(result["probability_observed_selected_passes"], 1.0)
        self.assertIsNone(result["confirmatory_p_value"])


if __name__ == "__main__":
    unittest.main()
