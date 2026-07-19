import unittest

import compare_foreign_research_runs as compare


def window(pnl, trades=10, mdd=0.10, top25=None, year="2011"):
    return {
        "metrics": {
            "total_pnl": pnl,
            "trades": trades,
            "mdd_on_capital": mdd,
        },
        "miss_top_winners_25pct": {"total_pnl": pnl if top25 is None else top25},
        "yearly_pnl": {year: pnl},
    }


def evaluation(name="anchor", pnl=100.0, adverse=80.0, tick2=70.0, mdd=0.10):
    return {
        "method": {"name": name, "family": "anchor" if name == "anchor" else "test"},
        "profiles": {
            "harsh": {
                "train_2011_2018": window(pnl, trades=60, mdd=mdd, year="2011"),
                "validation_2019_2023": window(
                    pnl, trades=60, mdd=mdd, year="2019"
                ),
            }
        },
        "adverse_harsh": {
            "train_2011_2018": window(adverse),
            "validation_2019_2023": window(adverse),
            "test_pre_nxt_2024_20250303": window(10.0),
            "post_nxt_20250304_2026": window(20.0),
        },
        "tick2_harsh": {
            "train_2011_2018": window(tick2),
            "validation_2019_2023": window(tick2),
        },
    }


def run(label, anchor, candidate):
    return {
        "label": label,
        "db_path": f"{label}.sqlite3",
        "event_rows": 100,
        "methods_tested": 2,
        "pretest_passed": 1,
        "database_universe_audit": {},
        "decision": {
            "selected_on_2011_2023": "candidate",
            "historical_total_leader": "candidate",
            "near_gate_shadow_candidate": "candidate",
        },
        "methods": {
            "anchor": compare.summarize_evaluation(anchor),
            "candidate": compare.summarize_evaluation(candidate),
        },
    }


def kind_audit():
    return {
        "source": {"list_url": "https://kind.krx.co.kr"},
        "registry_total": 10,
        "absent_from_current_cache": 9,
        "distress_absent_from_current_cache": 4,
        "ticker_reuse_suspected": 1,
        "survivorship_bias_resolved": False,
    }


def naver_audit():
    return {
        "source": {"candle_url": "https://fchart.stock.naver.com"},
        "symbols": 9,
        "rows": 1000,
        "normalized_suspension_rows": 100,
        "rejected_rows": 20,
        "overlap_quality_vs_toss_cache": {"same_vendor_claim": False},
        "sufficient_to_remove_survivorship_bias": False,
    }


class CompareForeignResearchRunsTests(unittest.TestCase):
    def test_summarize_evaluation_combines_locked_windows(self):
        result = compare.summarize_evaluation(
            evaluation(pnl=100.0, adverse=80.0, tick2=70.0, mdd=0.12)
        )

        self.assertEqual(result["selection_trades"], 120)
        self.assertEqual(result["selection_harsh_pnl"], 200.0)
        self.assertEqual(result["selection_adverse_pnl"], 160.0)
        self.assertEqual(result["selection_tick2_pnl"], 140.0)
        self.assertEqual(result["selection_max_subwindow_mdd_pct"], 12.0)
        self.assertEqual(result["reused_recent_adverse_pnl"], 30.0)

    def test_supplement_only_improvement_cannot_authorize_live_change(self):
        anchor = evaluation()
        base_candidate = evaluation(
            name="candidate", pnl=90.0, adverse=70.0, tick2=60.0, mdd=0.09
        )
        stress_candidate = evaluation(
            name="candidate", pnl=150.0, adverse=130.0, tick2=120.0, mdd=0.08
        )
        runs = {
            "base": run("base", anchor, base_candidate),
            "merged_all": run("merged_all", anchor, stress_candidate),
            "merged_pre60": run("merged_pre60", anchor, stress_candidate),
        }

        result = compare.build_comparison(
            runs, kind_audit=kind_audit(), naver_audit=naver_audit()
        )

        self.assertEqual(result["strict_cross_dataset_anchor_dominators"], [])
        self.assertEqual(
            result["supplement_only_protective_candidates"], ["candidate"]
        )
        self.assertFalse(result["decision"]["live_change_accepted"])
        self.assertTrue(result["decision"]["supplement_results_are_stress_bounds"])

    def test_cross_dataset_dominator_without_influence_support_is_not_promoted(self):
        anchor = evaluation()
        candidate = evaluation(
            name="candidate", pnl=150.0, adverse=130.0, tick2=120.0, mdd=0.08
        )
        runs = {
            label: run(label, anchor, candidate)
            for label in ("base", "merged_all", "merged_pre60")
        }
        for current in runs.values():
            current["decision"]["paired_influence_robustness"] = {
                "candidate": {"passed": False, "changed_dates": 5}
            }

        result = compare.build_comparison(
            runs, kind_audit=kind_audit(), naver_audit=naver_audit()
        )

        self.assertEqual(
            result["strict_cross_dataset_anchor_dominators"], ["candidate"]
        )
        self.assertEqual(
            result["strict_dominators_passing_influence_all_runs"], []
        )
        self.assertFalse(result["decision"]["live_change_accepted"])
        self.assertIn("none passes", result["decision"]["reason"])

    def test_comparability_rejects_mismatched_manifest_and_duplicate_dates(self):
        def payload(manifest):
            return {
                "requested_start": "2011-01-01",
                "requested_end": "2026-07-16",
                "methods_tested": 1,
                "source_fingerprints": {
                    "script_sha256": "script",
                    "external_script_sha256": "external",
                    "method_manifest_sha256": manifest,
                    "kosdaq_index_sha256": "index",
                },
                "evaluations": [{"method": {"name": "anchor"}}],
            }

        result = compare.validate_comparability(
            {
                "base": payload("A"),
                "merged_all": payload("B"),
                "merged_pre60": payload("A"),
            },
            {
                "merged_all": {
                    "integrity_passed": False,
                    "duplicate_symbol_dates": 10,
                },
                "merged_pre60": {
                    "integrity_passed": True,
                    "duplicate_symbol_dates": 0,
                },
            },
        )

        self.assertFalse(result["passed"])
        self.assertIn(
            "method_manifest_sha256",
            result["fingerprint_and_manifest_mismatches"],
        )
        self.assertIn("merged_all", result["invalid_merge_audits"])


if __name__ == "__main__":
    unittest.main()
