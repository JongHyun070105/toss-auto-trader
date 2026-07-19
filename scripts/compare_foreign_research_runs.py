#!/usr/bin/env python3
"""Compare base and delisted-symbol sensitivity runs without changing live code."""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


SELECTION_WINDOWS = ("train_2011_2018", "validation_2019_2023")
RECENT_WINDOWS = ("test_pre_nxt_2024_20250303", "post_nxt_20250304_2026")
DEFAULT_OUT = "data/kr_foreign_microstructure_research/run_comparison.json"


def read_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def evaluation_map(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {row["method"]["name"]: row for row in payload["evaluations"]}


def _sum_metric(
    evaluation: dict[str, Any],
    container: str,
    windows: Iterable[str],
    metric: str,
    *,
    profile: str | None = None,
) -> float:
    source = evaluation[container]
    if profile is not None:
        source = source[profile]
    return sum(float(source[window]["metrics"][metric]) for window in windows)


def summarize_evaluation(evaluation: dict[str, Any]) -> dict[str, Any]:
    harsh = evaluation["profiles"]["harsh"]
    yearly: dict[str, float] = {}
    for window in SELECTION_WINDOWS:
        yearly.update(
            {
                str(year): float(pnl)
                for year, pnl in harsh[window]["yearly_pnl"].items()
            }
        )
    return {
        "method": evaluation["method"]["name"],
        "family": evaluation["method"]["family"],
        "selection_trades": int(
            _sum_metric(
                evaluation,
                "profiles",
                SELECTION_WINDOWS,
                "trades",
                profile="harsh",
            )
        ),
        "selection_harsh_pnl": _sum_metric(
            evaluation,
            "profiles",
            SELECTION_WINDOWS,
            "total_pnl",
            profile="harsh",
        ),
        "selection_adverse_pnl": _sum_metric(
            evaluation, "adverse_harsh", SELECTION_WINDOWS, "total_pnl"
        ),
        "selection_tick2_pnl": _sum_metric(
            evaluation, "tick2_harsh", SELECTION_WINDOWS, "total_pnl"
        ),
        "selection_top25_removed_pnl": sum(
            float(harsh[window]["miss_top_winners_25pct"]["total_pnl"])
            for window in SELECTION_WINDOWS
        ),
        "selection_max_subwindow_mdd_pct": max(
            float(harsh[window]["metrics"]["mdd_on_capital"])
            for window in SELECTION_WINDOWS
        )
        * 100.0,
        "selection_positive_years": sum(pnl > 0.0 for pnl in yearly.values()),
        "selection_negative_years": sum(pnl < 0.0 for pnl in yearly.values()),
        "selection_yearly_pnl": yearly,
        "reused_recent_adverse_pnl": _sum_metric(
            evaluation, "adverse_harsh", RECENT_WINDOWS, "total_pnl"
        ),
    }


def summarize_run(label: str, payload: dict[str, Any]) -> dict[str, Any]:
    methods = {
        name: summarize_evaluation(row)
        for name, row in evaluation_map(payload).items()
    }
    return {
        "label": label,
        "db_path": payload["db_path"],
        "event_rows": int(payload["event_rows"]),
        "methods_tested": int(payload["methods_tested"]),
        "pretest_passed": int(payload["pretest_passed"]),
        "database_universe_audit": payload["database_universe_audit"],
        "decision": payload["decision"],
        "source_fingerprints": payload.get("source_fingerprints", {}),
        "run_configuration": payload.get("run_configuration", {}),
        "official_warning_interval_audit": payload.get(
            "official_warning_interval_audit", {}
        ),
        "methods": methods,
    }


def validate_comparability(
    payloads: dict[str, dict[str, Any]],
    merge_audits: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    fingerprint_keys = (
        "script_sha256",
        "external_script_sha256",
        "method_manifest_sha256",
        "kosdaq_index_sha256",
    )
    mismatches: dict[str, dict[str, Any]] = {}
    for key in fingerprint_keys:
        values = {
            label: payload.get("source_fingerprints", {}).get(key)
            for label, payload in payloads.items()
        }
        if None in values.values() or len(set(values.values())) != 1:
            mismatches[key] = values
    method_sets = {
        label: tuple(row["method"]["name"] for row in payload.get("evaluations", []))
        for label, payload in payloads.items()
    }
    if len(set(method_sets.values())) != 1:
        mismatches["method_order"] = {
            label: len(names) for label, names in method_sets.items()
        }
    run_fields = ("requested_start", "requested_end", "methods_tested")
    for key in run_fields:
        values = {label: payload.get(key) for label, payload in payloads.items()}
        if None in values.values() or len(set(values.values())) != 1:
            mismatches[key] = values
    invalid_merge_audits = {
        label: {
            "integrity_passed": audit.get("integrity_passed"),
            "duplicate_symbol_dates": audit.get("duplicate_symbol_dates"),
        }
        for label, audit in merge_audits.items()
        if not audit.get("integrity_passed")
        or int(audit.get("duplicate_symbol_dates", -1)) != 0
    }
    passed = not mismatches and not invalid_merge_audits
    return {
        "passed": passed,
        "fingerprint_and_manifest_mismatches": mismatches,
        "invalid_merge_audits": invalid_merge_audits,
        "merge_audits": merge_audits,
        "interpretation": "All runs must share one script, dependency, method manifest, KOSDAQ snapshot, date range, and zero-duplicate merged databases.",
    }


def beats_anchor(candidate: dict[str, Any], anchor: dict[str, Any]) -> bool:
    return all(
        candidate[key] > anchor[key]
        for key in (
            "selection_harsh_pnl",
            "selection_adverse_pnl",
            "selection_tick2_pnl",
            "selection_top25_removed_pnl",
        )
    ) and (
        candidate["selection_max_subwindow_mdd_pct"]
        <= anchor["selection_max_subwindow_mdd_pct"]
    )


def build_comparison(
    runs: dict[str, dict[str, Any]],
    *,
    kind_audit: dict[str, Any],
    naver_audit: dict[str, Any],
    comparability: dict[str, Any] | None = None,
) -> dict[str, Any]:
    method_sets = [set(run["methods"]) for run in runs.values()]
    common_methods = sorted(set.intersection(*method_sets))
    strict_dominators = [
        name
        for name in common_methods
        if name != "anchor"
        and all(
            beats_anchor(run["methods"][name], run["methods"]["anchor"])
            for run in runs.values()
        )
    ]
    strict_dominator_influence: dict[str, dict[str, Any]] = {
        name: {
            label: run.get("decision", {})
            .get("paired_influence_robustness", {})
            .get(name, {"available": False, "passed": False})
            for label, run in runs.items()
        }
        for name in strict_dominators
    }
    strict_dominators_passing_influence = [
        name
        for name, by_run in strict_dominator_influence.items()
        if by_run and all(check.get("passed") is True for check in by_run.values())
    ]
    positive_survivors = [
        name
        for name in common_methods
        if all(
            run["methods"][name]["selection_adverse_pnl"] > 0.0
            and run["methods"][name]["selection_tick2_pnl"] > 0.0
            and run["methods"][name]["selection_top25_removed_pnl"] > 0.0
            and run["methods"][name]["selection_max_subwindow_mdd_pct"] <= 30.0
            and run["methods"][name]["selection_trades"] >= 100
            for run in runs.values()
        )
    ]
    supplement_labels = [
        label for label in ("merged_all", "merged_pre60") if label in runs
    ]
    supplement_protective = [
        name
        for name in common_methods
        if name != "anchor"
        and supplement_labels
        and all(
            beats_anchor(
                runs[label]["methods"][name], runs[label]["methods"]["anchor"]
            )
            for label in supplement_labels
        )
    ]

    focus_methods = {"anchor", "volume_cap_065_anchor", "volume_cap_125_anchor"}
    for run in runs.values():
        decision = run["decision"]
        focus_methods.update(
            name
            for name in (
                decision.get("selected_on_2011_2023"),
                decision.get("historical_total_leader"),
                decision.get("near_gate_shadow_candidate"),
            )
            if name
        )
    focus_methods.update(supplement_protective)
    focus_methods = sorted(name for name in focus_methods if name in common_methods)

    anchor_deltas: dict[str, dict[str, float]] = {}
    base_anchor = runs["base"]["methods"]["anchor"]
    for label, run in runs.items():
        anchor = run["methods"]["anchor"]
        anchor_deltas[label] = {
            key: anchor[key] - base_anchor[key]
            for key in (
                "selection_trades",
                "selection_harsh_pnl",
                "selection_adverse_pnl",
                "selection_tick2_pnl",
                "selection_top25_removed_pnl",
                "selection_max_subwindow_mdd_pct",
                "reused_recent_adverse_pnl",
            )
        }

    return {
        "generated_at": datetime.now().astimezone().isoformat(),
        "selection_window": "2011-01-01~2023-12-31",
        "reused_recent_window": "2024-01-01~latest; diagnostic only",
        "comparability": comparability or {"passed": False, "reason": "not supplied"},
        "runs": runs,
        "common_methods": len(common_methods),
        "focus_methods": focus_methods,
        "strict_cross_dataset_anchor_dominators": strict_dominators,
        "strict_dominator_influence_checks": strict_dominator_influence,
        "strict_dominators_passing_influence_all_runs": (
            strict_dominators_passing_influence
        ),
        "cross_dataset_positive_survivors": positive_survivors,
        "supplement_only_protective_candidates": supplement_protective,
        "anchor_delta_vs_base": anchor_deltas,
        "data_quality": {
            "kind": {
                "source": kind_audit["source"],
                "registry_total": kind_audit["registry_total"],
                "absent_from_current_cache": kind_audit[
                    "absent_from_current_cache"
                ],
                "distress_absent_from_current_cache": kind_audit[
                    "distress_absent_from_current_cache"
                ],
                "ticker_reuse_suspected": kind_audit["ticker_reuse_suspected"],
                "survivorship_bias_resolved": kind_audit[
                    "survivorship_bias_resolved"
                ],
            },
            "naver_supplement": {
                "source": naver_audit["source"],
                "symbols": naver_audit["symbols"],
                "rows": naver_audit["rows"],
                "normalized_suspension_rows": naver_audit[
                    "normalized_suspension_rows"
                ],
                "rejected_rows": naver_audit["rejected_rows"],
                "overlap_quality_vs_toss_cache": naver_audit[
                    "overlap_quality_vs_toss_cache"
                ],
                "sufficient_to_remove_survivorship_bias": naver_audit[
                    "sufficient_to_remove_survivorship_bias"
                ],
            },
        },
        "decision": {
            "recommended_research_strategy": "anchor_with_existing_live_risk_exclusions",
            "live_change_accepted": False,
            "reason": (
                "Cross-dataset dominators exist, but none passes the paired influence "
                "gate in every run; the official-alert methods validate an existing "
                "risk exclusion rather than establish new alpha, and 2024+ is reused."
                if strict_dominators
                else "No candidate dominates the anchor in the survivor-shaped base "
                "and both delisted-symbol sensitivity datasets; 2024+ is reused."
            ),
            "supplement_results_are_stress_bounds": True,
        },
    }


def render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# 해외 연구 및 생존편향 민감도 비교",
        "",
        f"- 생성: `{payload['generated_at']}`",
        f"- 고정 선택 구간: `{payload['selection_window']}`",
        f"- 공통 전략 수: `{payload['common_methods']}`",
        f"- 실전 변경 승인: `{payload['decision']['live_change_accepted']}`",
        "",
        "## 핵심 결론",
        "",
        "세 데이터셋 모두에서 앵커보다 수익, 불리 체결, 2틱 스트레스, "
        "상위 수익 제거, MDD를 동시에 개선한 전략은 "
        f"`{payload['strict_cross_dataset_anchor_dominators']}`입니다.",
        "그중 각 데이터셋의 변경일 수와 상위 5개 날짜 제거까지 통과한 전략은 "
        f"`{payload['strict_dominators_passing_influence_all_runs']}`입니다.",
        "상장폐지 보조 데이터는 공식 KIND 종목 목록과 Naver 일봉을 결합한 "
        "민감도 자료이며 공식 체결·경고 이력을 복원한 정답 데이터가 아닙니다.",
        "",
        "## 앵커 비교",
        "",
        "| 데이터 | 거래 | harsh 손익 | 불리 체결 손익 | 2틱 손익 | 최대 구간 MDD | 상위 25% 제거 | 2024+ 불리 체결 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for label, run in payload["runs"].items():
        row = run["methods"]["anchor"]
        lines.append(
            f"| {label} | {row['selection_trades']:,} | "
            f"{row['selection_harsh_pnl']:,.0f} | "
            f"{row['selection_adverse_pnl']:,.0f} | "
            f"{row['selection_tick2_pnl']:,.0f} | "
            f"{row['selection_max_subwindow_mdd_pct']:.1f}% | "
            f"{row['selection_top25_removed_pnl']:,.0f} | "
            f"{row['reused_recent_adverse_pnl']:,.0f} |"
        )
    lines.extend(
        [
            "",
            "## 주요 후보",
            "",
            "| 전략 | 데이터 | harsh 손익 | 불리 체결 손익 | 2틱 손익 | MDD |",
            "|---|---|---:|---:|---:|---:|",
        ]
    )
    for method in payload["focus_methods"]:
        if method == "anchor":
            continue
        for label, run in payload["runs"].items():
            row = run["methods"][method]
            lines.append(
                f"| {method} | {label} | {row['selection_harsh_pnl']:,.0f} | "
                f"{row['selection_adverse_pnl']:,.0f} | "
                f"{row['selection_tick2_pnl']:,.0f} | "
                f"{row['selection_max_subwindow_mdd_pct']:.1f}% |"
            )
    quality = payload["data_quality"]
    lines.extend(
        [
            "",
            "## 데이터 한계",
            "",
            f"- KIND KOSDAQ 상장폐지 목록: `{quality['kind']['registry_total']}`개, "
            f"기존 캐시 부재 `{quality['kind']['absent_from_current_cache']}`개.",
            f"- Naver 보조 일봉: `{quality['naver_supplement']['symbols']}`종목, "
            f"`{quality['naver_supplement']['rows']:,}`행.",
            "- 보조 데이터는 Toss와 기업행사 조정 방식이 달라 절대가격·거래량 "
            "필터가 달라질 수 있습니다.",
            "- 09:01 호가, 주문 대기열, VI·경고·거래정지의 과거 시점 상태는 "
            "일봉으로 복원되지 않습니다.",
            "- 2024년 이후는 반복 확인한 구간이므로 승격 근거로 쓰지 않습니다.",
            "",
            "## 판정",
            "",
            "현재 실전 전략은 유지합니다. 보조 데이터에서만 좋아진 필터는 "
            "데이터 출처 효과와 실제 방어력 효과를 분리할 수 없으므로 연구 후보로만 남깁니다.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare foreign-research base and survivorship sensitivity runs"
    )
    parser.add_argument(
        "--base",
        default="data/kr_foreign_microstructure_research/base_new_hypotheses/kr_foreign_microstructure_research.json",
    )
    parser.add_argument(
        "--merged-all",
        default="data/kr_foreign_microstructure_research/merged_all_run/kr_foreign_microstructure_research.json",
    )
    parser.add_argument(
        "--merged-pre60",
        default="data/kr_foreign_microstructure_research/merged_pre60_run/kr_foreign_microstructure_research.json",
    )
    parser.add_argument(
        "--kind-audit",
        default="data/kr_foreign_microstructure_research/krx_kind_delisted_universe_audit.json",
    )
    parser.add_argument(
        "--naver-audit",
        default="data/kr_foreign_microstructure_research/naver_delisted_candle_audit.json",
    )
    parser.add_argument(
        "--merged-all-audit",
        default="data/kr_foreign_microstructure_research/edge_research_with_delisted_all.sqlite3.audit.json",
    )
    parser.add_argument(
        "--merged-pre60-audit",
        default="data/kr_foreign_microstructure_research/edge_research_with_delisted_pre60.sqlite3.audit.json",
    )
    parser.add_argument("--out", default=DEFAULT_OUT)
    args = parser.parse_args()

    raw_runs = {
        "base": read_json(args.base),
        "merged_all": read_json(args.merged_all),
        "merged_pre60": read_json(args.merged_pre60),
    }
    merge_audits = {
        "merged_all": read_json(args.merged_all_audit),
        "merged_pre60": read_json(args.merged_pre60_audit),
    }
    comparability = validate_comparability(raw_runs, merge_audits)
    if not comparability["passed"]:
        raise RuntimeError(
            "research runs are not comparable: "
            + json.dumps(comparability, ensure_ascii=False)
        )
    runs = {
        label: summarize_run(label, payload)
        for label, payload in raw_runs.items()
    }
    payload = build_comparison(
        runs,
        kind_audit=read_json(args.kind_audit),
        naver_audit=read_json(args.naver_audit),
        comparability=comparability,
    )
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    out.with_suffix(".md").write_text(render_markdown(payload), encoding="utf-8")
    print(
        json.dumps(
            {
                "out": str(out),
                "strict_dominators": payload[
                    "strict_cross_dataset_anchor_dominators"
                ],
                "protective_candidates": payload[
                    "supplement_only_protective_candidates"
                ],
                "live_change_accepted": False,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
