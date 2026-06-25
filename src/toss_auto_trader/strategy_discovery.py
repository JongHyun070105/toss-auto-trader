from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from statistics import median
from typing import Any


DEFAULT_THRESHOLDS = {
    "min_resolved_forward_outcomes": 20,
    "min_avg_net_return_after_cost": 0.02,
    "min_median_net_return_after_cost": 0.0,
    "min_win_rate_after_cost": 0.55,
    "max_pending_count": 0,
}


@dataclass(frozen=True)
class StrategyScore:
    name: str
    artifact_path: str
    status: str
    score: float
    blockers: list[str]
    reasons: list[str]
    metrics: dict[str, Any]
    pre_live_review_eligible: bool = False
    order_sent: bool = False
    live_order_allowed: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "artifact_path": self.artifact_path,
            "status": self.status,
            "score": self.score,
            "blockers": self.blockers,
            "reasons": self.reasons,
            "metrics": self.metrics,
            "pre_live_review_eligible": self.pre_live_review_eligible,
            "order_sent": self.order_sent,
            "live_order_allowed": self.live_order_allowed,
        }


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        out = float(value)
        if math.isnan(out) or math.isinf(out):
            return None
        return out
    except Exception:
        return None


def _compact_blockers(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        return [str(x) for x in value]
    if isinstance(value, dict):
        out: list[str] = []
        for key, item in value.items():
            if item:
                out.append(f"{key}:{item}")
        return out
    return [str(value)]


def load_json_or_none(path: str | Path) -> dict[str, Any] | None:
    p = Path(path)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except json.JSONDecodeError:
        return None


def thresholds_from_policy(policy: dict[str, Any] | None) -> dict[str, Any]:
    thresholds = dict(DEFAULT_THRESHOLDS)
    if not policy:
        return thresholds
    loop_policy = policy.get("auto_discovery_loop") or policy.get("auto_discovery_loop_policy") or {}
    values = loop_policy.get("good_strategy_thresholds") or {}
    thresholds.update({k: v for k, v in values.items() if v is not None})
    # Existing policy field is days, but for resolved outcome ledger we use it as a lower bound if larger.
    promotion = policy.get("promotion_gates") or {}
    if promotion.get("paper_only_forward_days_min") is not None:
        thresholds["min_resolved_forward_outcomes"] = max(
            int(thresholds["min_resolved_forward_outcomes"]),
            int(promotion.get("paper_only_forward_days_min") or 0),
        )
    return thresholds


def score_forward_outcomes(name: str, path: str, data: dict[str, Any], thresholds: dict[str, Any]) -> StrategyScore:
    stats = data.get("resolved_stats_all_outcomes") or {}
    resolved = int(stats.get("resolved") or 0)
    avg = _safe_float(stats.get("avg_net_return_after_cost"))
    med = _safe_float(stats.get("median_net_return_after_cost"))
    win = _safe_float(stats.get("win_rate_after_cost"))
    pending = int(data.get("pending_count") or 0)
    blockers: list[str] = []
    reasons: list[str] = ["paper-only forward outcome ledger evaluated"]
    if resolved < int(thresholds["min_resolved_forward_outcomes"]):
        blockers.append("insufficient_forward_outcomes")
    if avg is None or avg < float(thresholds["min_avg_net_return_after_cost"]):
        blockers.append("avg_return_below_threshold")
    if med is None or med < float(thresholds["min_median_net_return_after_cost"]):
        blockers.append("median_return_below_threshold")
    if win is None or win < float(thresholds["min_win_rate_after_cost"]):
        blockers.append("win_rate_below_threshold")
    if pending > int(thresholds["max_pending_count"]):
        blockers.append("pending_outcomes_remaining")
    if data.get("live_order_allowed") is not False:
        blockers.append("artifact_must_remain_no_live")
    eligible = not blockers
    score = 0.0
    if avg is not None:
        score += avg * 100.0
    if med is not None:
        score += med * 50.0
    if win is not None:
        score += (win - 0.5) * 20.0
    score += min(resolved, 100) / 100.0
    status = "pre_live_review_candidate_not_live_order" if eligible else "blocked_or_waiting_forward_evidence"
    if eligible:
        reasons.append("thresholds passed; still requires pre-live candidate construction and manual live gate")
    else:
        reasons.append("not enough verified forward evidence for pre-live review")
    return StrategyScore(
        name=name,
        artifact_path=path,
        status=status,
        score=score,
        blockers=blockers,
        reasons=reasons,
        metrics={
            "resolved": resolved,
            "avg_net_return_after_cost": avg,
            "median_net_return_after_cost": med,
            "win_rate_after_cost": win,
            "pending_count": pending,
            "thresholds": thresholds,
        },
        pre_live_review_eligible=eligible,
        order_sent=False,
        live_order_allowed=False,
    )


def score_forward_watch(name: str, path: str, data: dict[str, Any]) -> StrategyScore:
    count = int(data.get("candidate_count") or 0)
    blockers = [] if count else ["no_current_forward_watch_candidates"]
    return StrategyScore(
        name=name,
        artifact_path=path,
        status="forward_watch_pending_outcomes_not_live_order" if count else "no_signal_zero_pick",
        score=float(count),
        blockers=blockers,
        reasons=["latest candle scan only creates paper-only forward observations"],
        metrics={"candidate_count": count, "symbols_scanned": data.get("symbols_scanned"), "skipped": data.get("skipped")},
        order_sent=False,
        live_order_allowed=False,
    )


def score_same_history_report(name: str, path: str, data: dict[str, Any]) -> StrategyScore:
    blockers = _compact_blockers(data.get("blockers"))
    reasons = ["same-history or locked-test research report evaluated"]
    edge = data.get("edge_ok_same_history_only")
    if edge:
        blockers.append("future_holdout_required_before_pre_live")
        reasons.append("same-history pass is not live approval")
    if data.get("live_order_allowed") is not False:
        blockers.append("artifact_must_remain_no_live")
    # Pull useful nested blocker shapes.
    if data.get("mode") == "research_only_no_send_regime_exposure_gate_audit":
        gate_reports = data.get("gate_reports") or []
        ok_gates = [g for g in gate_reports if g.get("candidate_ok_same_history_only")]
        if not ok_gates:
            blockers.append("no_regime_gate_promotable")
        else:
            blockers.append("regime_gate_future_holdout_required")
        metrics = {"gate_count": len(gate_reports), "same_history_ok_gates": [g.get("gate") for g in ok_gates]}
        score = float(len(ok_gates))
    elif data.get("mode") == "research_only_no_send_relative_strength_horizon_audit":
        evaluation = data.get("evaluation") or {}
        locked = (evaluation.get("h60") or {}).get("locked_test") or (evaluation.get("h20") or {}).get("locked_test") or {}
        excess = _safe_float(locked.get("top_avg_excess_vs_kosdaq")) or _safe_float(locked.get("top_avg_excess_vs_universe")) or 0.0
        metrics = {"locked_test": locked, "edge_ok_same_history_only": edge}
        score = excess * 100.0
    elif data.get("mode") == "research_only_no_send_event_liquidity_reaction_audit":
        evaluation = data.get("evaluation") or {}
        locked = evaluation.get("locked_test") or {}
        avg = _safe_float(locked.get("avg_excess_vs_same_date_universe")) or _safe_float(locked.get("avg_net_return_after_cost")) or 0.0
        metrics = {
            "mapped_news_events": data.get("mapped_news_events"),
            "evaluable_event_signals": data.get("evaluable_event_signals"),
            "unique_event_symbols": data.get("unique_event_symbols"),
            "locked_test": locked,
        }
        score = avg * 100.0
    else:
        summary = data.get("summary") or {}
        aggregate = summary.get("aggregate") or {}
        locked = aggregate.get("locked_test") or data.get("locked_test") or {}
        avg = _safe_float(locked.get("avg_net_return_after_cost")) or _safe_float(locked.get("avg")) or 0.0
        metrics = {"summary": summary, "locked_test": locked}
        score = avg * 100.0
    if not blockers:
        blockers.append("paper_forward_validation_required")
    return StrategyScore(
        name=name,
        artifact_path=path,
        status="research_only_not_live_order",
        score=score,
        blockers=blockers,
        reasons=reasons,
        metrics=metrics,
        order_sent=False,
        live_order_allowed=False,
    )


def score_artifact(name: str, path: str | Path, data: dict[str, Any], policy: dict[str, Any] | None = None) -> StrategyScore:
    path_s = str(path)
    mode = data.get("mode")
    thresholds = thresholds_from_policy(policy)
    if mode == "paper_only_forward_outcome_update_no_send" or "resolved_stats_all_outcomes" in data:
        return score_forward_outcomes(name, path_s, data, thresholds)
    if mode == "paper_only_forward_observation_no_send" or ("candidate_count" in data and "candidates" in data):
        return score_forward_watch(name, path_s, data)
    return score_same_history_report(name, path_s, data)


def default_artifact_specs(root: str | Path = ".") -> list[tuple[str, Path]]:
    base = Path(root)
    return [
        ("rsi_bbands_v3_forward_outcomes", base / "data/rsi_bbands_v3_forward_outcome_latest.json"),
        ("rsi_bbands_v3_forward_watch", base / "data/rsi_bbands_v3_forward_candidates_latest.json"),
        ("relative_strength_horizon", base / "data/relative_strength_horizon_latest.json"),
        ("event_liquidity_reaction", base / "data/event_liquidity_reaction_latest.json"),
        ("market_regime_exposure_gate", base / "data/market_regime_exposure_gate_latest.json"),
        ("market_regime_signal_audit", base / "data/market_regime_signal_audit_latest.json"),
        ("ai_trader_external_sweep_smoke", base / "data/ai_trader_sweep/current_smoke.json"),
    ]


def evaluate_strategy_artifacts(
    specs: list[tuple[str, Path]] | None = None,
    *,
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    specs = specs if specs is not None else default_artifact_specs()
    scores: list[StrategyScore] = []
    missing: list[dict[str, str]] = []
    for name, path in specs:
        data = load_json_or_none(path)
        if data is None:
            missing.append({"name": name, "path": str(path)})
            continue
        score = score_artifact(name, path, data, policy)
        scores.append(score)
    ranked = sorted(scores, key=lambda s: (s.pre_live_review_eligible, s.score), reverse=True)
    eligible = [s for s in ranked if s.pre_live_review_eligible]
    return {
        "mode": "strategy_discovery_evaluation_no_send",
        "live_order_allowed": False,
        "order_sent": False,
        "manual_approval_required": True,
        "scores": [s.as_dict() for s in ranked],
        "missing_artifacts": missing,
        "selected": eligible[0].as_dict() if eligible else None,
        "summary": {
            "evaluated": len(scores),
            "missing": len(missing),
            "pre_live_review_eligible": len(eligible),
            "best_status": ranked[0].status if ranked else "no_artifacts",
            "best_name": ranked[0].name if ranked else None,
            "live_action": "blocked_no_strategy_has_all_forward_and_pre_live_gates",
        },
    }


def append_jsonl(path: str | Path, row: dict[str, Any]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a") as f:
        f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
