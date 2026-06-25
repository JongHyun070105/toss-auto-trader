import importlib.util
import tempfile
import unittest
from pathlib import Path

from toss_auto_trader.strategy_discovery import evaluate_strategy_artifacts, score_artifact, thresholds_from_policy

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"


def load_script(name: str):
    path = SCRIPTS_DIR / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class StrategyDiscoveryTests(unittest.TestCase):
    def test_good_forward_outcome_only_promotes_to_pre_live_review_not_order(self):
        policy = {"auto_discovery_loop": {"good_strategy_thresholds": {"min_resolved_forward_outcomes": 20}}}
        score = score_artifact("good_forward", "memory.json", {
            "mode": "paper_only_forward_outcome_update_no_send",
            "live_order_allowed": False,
            "pending_count": 0,
            "resolved_stats_all_outcomes": {
                "resolved": 20,
                "avg_net_return_after_cost": 0.031,
                "median_net_return_after_cost": 0.012,
                "win_rate_after_cost": 0.60,
            },
        }, policy)
        self.assertTrue(score.pre_live_review_eligible)
        self.assertFalse(score.order_sent)
        self.assertFalse(score.live_order_allowed)
        self.assertEqual(score.status, "pre_live_review_candidate_not_live_order")

    def test_same_history_pass_still_requires_future_holdout(self):
        score = score_artifact("same_history", "same.json", {
            "mode": "research_only_no_send_relative_strength_horizon_audit",
            "live_order_allowed": False,
            "edge_ok_same_history_only": True,
            "blockers": [],
            "evaluation": {"h60": {"locked_test": {"top_avg_excess_vs_kosdaq": 0.10}}},
        }, None)
        self.assertFalse(score.pre_live_review_eligible)
        self.assertFalse(score.order_sent)
        self.assertIn("future_holdout_required_before_pre_live", score.blockers)

    def test_loop_evaluation_selects_only_forward_proven_candidate(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            good = root / "good.json"
            same = root / "same.json"
            good.write_text('''{
              "mode": "paper_only_forward_outcome_update_no_send",
              "live_order_allowed": false,
              "pending_count": 0,
              "resolved_stats_all_outcomes": {
                "resolved": 22,
                "avg_net_return_after_cost": 0.04,
                "median_net_return_after_cost": 0.01,
                "win_rate_after_cost": 0.59
              }
            }''')
            same.write_text('''{
              "mode": "research_only_no_send_event_liquidity_reaction_audit",
              "live_order_allowed": false,
              "edge_ok_same_history_only": true,
              "blockers": []
            }''')
            report = evaluate_strategy_artifacts([
                ("same_history", same),
                ("good_forward", good),
            ])
            self.assertFalse(report["order_sent"])
            self.assertFalse(report["live_order_allowed"])
            self.assertEqual(report["summary"]["pre_live_review_eligible"], 1)
            self.assertEqual(report["selected"]["name"], "good_forward")
            self.assertEqual(report["selected"]["status"], "pre_live_review_candidate_not_live_order")

    def test_command_packs_never_call_live_order_command(self):
        loop = load_script("strategy_discovery_loop")
        for pack in ["none", "forward", "light", "full"]:
            commands = loop.command_pack(pack, "data/example.sqlite3")
            flat = "\n".join(" ".join(cmd) for cmd in commands)
            self.assertNotIn("order-live-send", flat)
            self.assertNotIn("TOSS_LIVE_TRADING=true", flat)

    def test_policy_thresholds_merge_existing_promotion_gate(self):
        thresholds = thresholds_from_policy({
            "promotion_gates": {"paper_only_forward_days_min": 30},
            "auto_discovery_loop": {"good_strategy_thresholds": {"min_resolved_forward_outcomes": 5}},
        })
        self.assertEqual(thresholds["min_resolved_forward_outcomes"], 30)


if __name__ == "__main__":
    unittest.main()
