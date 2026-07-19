import unittest

import validate_foreign_research_mission as validator


def payload(script_hash: str = "script"):
    return {
        "methods_tested": 21,
        "sources": [{}] * 12,
        "families": ["a", "b", "c"],
        "run_configuration": {
            "selection_window": "2011-01-01~2023-12-31",
            "reused_diagnostic_window": "2024-01-01~2026-07-16",
            "cost_profiles": validator.EXPECTED_COSTS,
        },
        "decision": {
            "live_change_accepted": False,
            "paired_influence_robustness": {
                "candidate": {
                    "window": {"start": "2011-01-01", "end": "2023-12-31"}
                }
            },
        },
        "official_warning_interval_audit": {
            "selection_2011_2023_filter_complete": True
        },
        "execution_reachability_audit": {
            "anchor": {
                "selection_2011_2023": {"same_open_fill_observed": False},
                "reused_recent_2024_plus": {"same_open_fill_observed": False},
            }
        },
        "selection_functional_block_stability": {
            "available": True,
            "samples": 50,
        },
        "source_fingerprints": {
            "script_sha256": script_hash,
            "external_script_sha256": "external",
            "method_manifest_sha256": "manifest",
            "kosdaq_index_sha256": "kosdaq",
        },
        "evaluations": [{"method": {"name": "anchor"}}],
    }


class ValidateForeignResearchMissionTests(unittest.TestCase):
    def test_valid_payload_and_matching_fingerprints_pass(self):
        current_hash = validator.hashlib.sha256(
            validator.RESEARCH_SCRIPT.read_bytes()
        ).hexdigest()
        external_hash = validator.hashlib.sha256(
            validator.EXTERNAL_SCRIPT.read_bytes()
        ).hexdigest()
        runs = {
            name: payload(current_hash) for name in ("base", "all", "pre60")
        }
        for row in runs.values():
            row["source_fingerprints"]["external_script_sha256"] = external_hash
        self.assertEqual(validator.validate_run("base", runs["base"]), [])
        self.assertEqual(validator.validate_fingerprints(runs), [])

    def test_cost_or_fingerprint_drift_fails(self):
        bad = payload()
        bad["run_configuration"]["cost_profiles"] = {"harsh": 0.0}
        self.assertIn(
            "base: cost profiles changed", validator.validate_run("base", bad)
        )
        runs = {"base": payload(), "all": payload("changed")}
        self.assertIn(
            "run fingerprint mismatch: script_sha256",
            validator.validate_fingerprints(runs),
        )

    def test_current_source_hash_drift_fails(self):
        runs = {name: payload("stale") for name in ("base", "all", "pre60")}
        self.assertIn(
            "run fingerprint is stale: script_sha256",
            validator.validate_fingerprints(runs),
        )

    def test_influence_window_leak_fails(self):
        bad = payload()
        bad["decision"]["paired_influence_robustness"]["candidate"]["window"] = {
            "start": None,
            "end": None,
        }
        self.assertIn(
            "base: paired influence leaked outside selection window",
            validator.validate_run("base", bad),
        )


if __name__ == "__main__":
    unittest.main()
