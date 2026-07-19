#!/usr/bin/env python3
"""Validate the reproducible artifacts for the foreign-method research mission."""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "kr_foreign_microstructure_research"
REPORT = ROOT / "docs" / "KR_FOREIGN_MICROSTRUCTURE_RESEARCH_2026-07-19.md"
RUNS = {
    "base": DATA
    / "base_new_hypotheses"
    / "kr_foreign_microstructure_research.json",
    "merged_all": DATA
    / "merged_all_run"
    / "kr_foreign_microstructure_research.json",
    "merged_pre60": DATA
    / "merged_pre60_run"
    / "kr_foreign_microstructure_research.json",
}
COMPARISON = DATA / "run_comparison.json"
LIVE_PATHS = (
    "scripts/simple_gap_trader.py",
    "scripts/toss_discord_report.py",
    "src/toss_auto_trader/simple_gap_state.py",
)
EXPECTED_COSTS = {
    "base": 0.0035,
    "realistic": 0.0075,
    "harsh": 0.0135,
    "extreme": 0.0245,
}
RESEARCH_SCRIPT = ROOT / "scripts" / "kr_foreign_microstructure_research.py"
EXTERNAL_SCRIPT = ROOT / "scripts" / "kr_external_method_research.py"


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_run(label: str, payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if int(payload.get("methods_tested", 0)) < 21:
        errors.append(f"{label}: fewer than 20 alternative methods")
    if len(payload.get("sources", [])) < 12:
        errors.append(f"{label}: fewer than 12 primary/official sources")
    if len(payload.get("families", [])) < 3:
        errors.append(f"{label}: fewer than 3 method families")
    config = payload.get("run_configuration", {})
    if config.get("selection_window") != "2011-01-01~2023-12-31":
        errors.append(f"{label}: selection window changed")
    if not str(config.get("reused_diagnostic_window", "")).startswith(
        "2024-01-01~"
    ):
        errors.append(f"{label}: reused diagnostic window missing")
    if config.get("cost_profiles") != EXPECTED_COSTS:
        errors.append(f"{label}: cost profiles changed")
    if payload.get("decision", {}).get("live_change_accepted") is not False:
        errors.append(f"{label}: live change must remain rejected")
    expected_influence_window = {
        "start": "2011-01-01",
        "end": "2023-12-31",
    }
    influence_rows = payload.get("decision", {}).get(
        "paired_influence_robustness", {}
    )
    if not influence_rows or any(
        row.get("window") != expected_influence_window
        for row in influence_rows.values()
    ):
        errors.append(f"{label}: paired influence leaked outside selection window")
    if payload.get("official_warning_interval_audit", {}).get(
        "selection_2011_2023_filter_complete"
    ) is not True:
        errors.append(f"{label}: official warning history incomplete in selection")
    reachability = payload.get("execution_reachability_audit", {}).get(
        "anchor", {}
    )
    for window in ("selection_2011_2023", "reused_recent_2024_plus"):
        if reachability.get(window, {}).get("same_open_fill_observed") is not False:
            errors.append(f"{label}: same-open execution limitation missing")
    stability = payload.get("selection_functional_block_stability", {})
    if not stability.get("available") or int(stability.get("samples", 0)) < 50:
        errors.append(f"{label}: selection-functional bootstrap incomplete")
    return errors


def validate_fingerprints(runs: dict[str, dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    keys = (
        "script_sha256",
        "external_script_sha256",
        "method_manifest_sha256",
        "kosdaq_index_sha256",
    )
    for key in keys:
        values = {
            payload.get("source_fingerprints", {}).get(key)
            for payload in runs.values()
        }
        if None in values or len(values) != 1:
            errors.append(f"run fingerprint mismatch: {key}")
    method_orders = {
        tuple(row["method"]["name"] for row in payload.get("evaluations", []))
        for payload in runs.values()
    }
    if len(method_orders) != 1:
        errors.append("method order differs across runs")
    current_hashes = {
        "script_sha256": hashlib.sha256(RESEARCH_SCRIPT.read_bytes()).hexdigest(),
        "external_script_sha256": hashlib.sha256(
            EXTERNAL_SCRIPT.read_bytes()
        ).hexdigest(),
    }
    for key, current_hash in current_hashes.items():
        if any(
            payload.get("source_fingerprints", {}).get(key) != current_hash
            for payload in runs.values()
        ):
            errors.append(f"run fingerprint is stale: {key}")
    return errors


def validate_live_paths() -> list[str]:
    result = subprocess.run(
        ["git", "diff", "--quiet", "HEAD", "--", *LIVE_PATHS],
        cwd=ROOT,
        check=False,
    )
    return [] if result.returncode == 0 else ["live trading paths were modified"]


def main() -> int:
    errors: list[str] = []
    missing = [str(path.relative_to(ROOT)) for path in RUNS.values() if not path.exists()]
    if not COMPARISON.exists():
        missing.append(str(COMPARISON.relative_to(ROOT)))
    if not REPORT.exists():
        missing.append(str(REPORT.relative_to(ROOT)))
    if missing:
        errors.append("missing artifacts: " + ", ".join(missing))
    else:
        runs = {label: read_json(path) for label, path in RUNS.items()}
        for label, payload in runs.items():
            errors.extend(validate_run(label, payload))
        errors.extend(validate_fingerprints(runs))
        comparison = read_json(COMPARISON)
        if comparison.get("comparability", {}).get("passed") is not True:
            errors.append("cross-run comparability failed")
        for label, audit in comparison.get("comparability", {}).get(
            "merge_audits", {}
        ).items():
            if not audit.get("integrity_passed") or int(
                audit.get("duplicate_symbol_dates", -1)
            ) != 0:
                errors.append(f"{label}: merged database integrity failed")
        report = REPORT.read_text(encoding="utf-8")
        if len(re.findall(r"https?://", report)) < 12:
            errors.append("final report has fewer than 12 direct source links")
        for phrase in (
            "동일 시가 체결",
            "생존편향",
            "다중검정",
            "실전 전략 유지",
        ):
            if phrase not in report:
                errors.append(f"final report omits required limitation: {phrase}")
    errors.extend(validate_live_paths())
    result = {
        "passed": not errors,
        "errors": errors,
        "runs": [str(path.relative_to(ROOT)) for path in RUNS.values()],
        "report": str(REPORT.relative_to(ROOT)),
        "live_paths_unchanged": "live trading paths were modified" not in errors,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
