from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
from typing import Any, Iterable

from .orderbook_utils import best_spread_from_orderbook, market_impact_from_orderbook, timestamp_staleness

ACK_PREFIX = "I_UNDERSTAND_LIVE_ORDER_RISK:"


@dataclass(frozen=True)
class LiveOrderValidation:
    ok: bool
    errors: list[str]
    warnings: list[str]
    fingerprint: str
    required_confirm: str


def _dec(value: Any, default: str = "0") -> Decimal:
    if value is None or value == "":
        return Decimal(default)
    return Decimal(str(value))


def parse_pair_slots(pair: str) -> list[tuple[str, Decimal]]:
    slots: list[tuple[str, Decimal]] = []
    for part in str(pair or "").split("+"):
        raw = part.strip()
        if not raw:
            continue
        if ":" not in raw:
            raise ValueError(f"invalid pair slot: {raw}")
        symbol, cash = raw.split(":", 1)
        slots.append((symbol.strip(), _dec(cash.strip())))
    return slots


def candidate_fingerprint(candidate: dict[str, Any]) -> str:
    """Stable short hash for the exact candidate evidence being approved."""
    material = {
        "name": candidate.get("name"),
        "pair": candidate.get("pair"),
        "branch": candidate.get("branch"),
        "window": candidate.get("window"),
        "horizon": candidate.get("horizon"),
        "mode": candidate.get("mode"),
        "source": candidate.get("source"),
        "validation_pnl_krw": candidate.get("validation_pnl_krw"),
        "status": candidate.get("status"),
        "edge_guard": candidate.get("edge_guard"),
        "observation_guard": candidate.get("observation_guard"),
        "spread_guard": {
            "max_spread_bps_allowed": (candidate.get("spread_guard") or {}).get("max_spread_bps_allowed"),
            "max_impact_bps_allowed": (candidate.get("spread_guard") or {}).get("max_impact_bps_allowed"),
        },
    }
    raw = json.dumps(material, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def required_confirmation(candidate: dict[str, Any]) -> str:
    return f"{ACK_PREFIX}{candidate_fingerprint(candidate)}"


def _stress_ok_for_pair(candidate: dict[str, Any], stress_report: dict[str, Any] | None) -> bool | None:
    if stress_report is None:
        return None
    pair = candidate.get("pair")
    for row in stress_report.get("rows", []):
        if row.get("pair") == pair:
            return bool(row.get("ok"))
    return False


def validate_candidate_for_live(
    candidate_file: dict[str, Any],
    candidate: dict[str, Any],
    *,
    require_spread_ok: bool = True,
    require_observation_ok: bool = True,
    require_stress_ok: bool = True,
    require_edge_ok: bool = True,
    stress_report: dict[str, Any] | None = None,
) -> LiveOrderValidation:
    errors: list[str] = []
    warnings: list[str] = []

    if candidate_file.get("live_order_allowed") is not True:
        errors.append("candidate_file_live_order_allowed_must_be_true")
    if candidate_file.get("manual_approval_required") is not True:
        errors.append("candidate_file_manual_approval_required_must_be_true")
    if candidate.get("source") != "walk_forward":
        errors.append("candidate_source_must_be_walk_forward")
    if not candidate.get("stable_positive"):
        errors.append("candidate_stable_positive_must_be_true")
    if _dec(candidate.get("validation_pnl_krw")) <= 0:
        errors.append("candidate_validation_pnl_must_be_positive")

    status = str(candidate.get("status", ""))
    if status.startswith("blocked_"):
        errors.append(f"candidate_status_blocked:{status}")
    elif status not in {"watchlist_not_live_order", "spread_checked_watchlist_not_live_order", "pre_live_review_ok"}:
        warnings.append(f"candidate_status_unrecognized:{status}")

    spread = candidate.get("spread_guard")
    if require_spread_ok and not (isinstance(spread, dict) and spread.get("ok")):
        errors.append("spread_guard_ok_required")
    obs = candidate.get("observation_guard")
    if require_observation_ok and not (isinstance(obs, dict) and obs.get("ok")):
        errors.append("observation_guard_ok_required")
    if require_edge_ok:
        edge_guard = candidate.get("edge_guard")
        edge = candidate.get("edge_audit")
        if isinstance(edge_guard, dict) and not edge_guard.get("ok"):
            errors.append(f"edge_guard_ok_required:{edge_guard.get('reason')}")
        elif not isinstance(edge, dict) or not edge.get("edge_ok"):
            errors.append("edge_audit_edge_ok_required")
    if require_stress_ok:
        stress_ok = _stress_ok_for_pair(candidate, stress_report)
        if stress_ok is None:
            errors.append("stress_report_required")
        elif not stress_ok:
            errors.append("stress_guard_ok_required")

    fp = candidate_fingerprint(candidate)
    return LiveOrderValidation(
        ok=not errors,
        errors=errors,
        warnings=warnings,
        fingerprint=fp,
        required_confirm=f"{ACK_PREFIX}{fp}",
    )


def validate_fresh_orderbooks(
    candidate: dict[str, Any],
    orderbooks: dict[str, dict[str, Any]],
    *,
    max_stale_ms: int = 500,
    market_impact_levels: int = 5,
) -> tuple[list[str], list[str], dict[str, Any]]:
    errors: list[str] = []
    warnings: list[str] = []
    details: dict[str, Any] = {}
    spread_guard = candidate.get("spread_guard") or {}
    max_spread_bps = _dec(spread_guard.get("max_spread_bps_allowed"), "30")
    max_impact_bps = _dec(spread_guard.get("max_impact_bps_allowed"), "30")
    slots = parse_pair_slots(candidate.get("pair", ""))
    for symbol, cash in slots:
        payload = orderbooks.get(symbol)
        if not payload:
            errors.append(f"orderbook_missing:{symbol}")
            continue
        spread = best_spread_from_orderbook(payload)
        stale = timestamp_staleness(payload, max_stale_ms=max_stale_ms)
        impact = market_impact_from_orderbook(payload, buy_cash_krw=cash, levels=market_impact_levels)
        row = {"spread": spread, "staleness": stale, "impact": impact}
        details[symbol] = row
        if not spread.get("available"):
            errors.append(f"spread_unavailable:{symbol}")
        elif _dec(spread.get("spread_bps")) > max_spread_bps:
            errors.append(f"spread_too_wide:{symbol}:{spread.get('spread_bps')}bps")
        if stale.get("available") and not stale.get("ok"):
            errors.append(f"orderbook_stale:{symbol}:{stale.get('stale_ms')}ms")
        elif not stale.get("available"):
            warnings.append(f"orderbook_timestamp_missing:{symbol}")
        if not impact.get("available"):
            errors.append(f"market_impact_unavailable:{symbol}")
        elif not impact.get("full_fill_within_levels"):
            errors.append(f"market_impact_not_fillable:{symbol}")
        elif _dec(impact.get("impact_bps")) > max_impact_bps:
            errors.append(f"market_impact_too_high:{symbol}:{impact.get('impact_bps')}bps")
    return errors, warnings, details


def build_buy_limit_payloads(
    candidate: dict[str, Any],
    orderbooks: dict[str, dict[str, Any]],
    *,
    client_order_id_prefix: str,
    limit_buffer_bps: Decimal = Decimal("0"),
) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    fp = candidate_fingerprint(candidate)
    for idx, (symbol, slot_cash) in enumerate(parse_pair_slots(candidate.get("pair", "")), start=1):
        payload = orderbooks.get(symbol)
        if not payload:
            raise ValueError(f"orderbook missing for {symbol}")
        spread = best_spread_from_orderbook(payload)
        if not spread.get("available"):
            raise ValueError(f"spread unavailable for {symbol}")
        best_ask = _dec(spread.get("best_ask"))
        if best_ask <= 0:
            raise ValueError(f"best ask unavailable for {symbol}")
        limit_price = (best_ask * (Decimal("1") + limit_buffer_bps / Decimal("10000"))).to_integral_value(rounding=ROUND_CEILING)
        quantity = (slot_cash / limit_price).to_integral_value(rounding=ROUND_FLOOR)
        if quantity <= 0:
            raise ValueError(f"slot cash cannot buy one share for {symbol}: cash={slot_cash} limit={limit_price}")
        payloads.append(
            {
                "clientOrderId": f"{client_order_id_prefix}-{fp}-{idx}",
                "symbol": symbol,
                "side": "BUY",
                "orderType": "LIMIT",
                "quantity": str(quantity),
                "price": str(limit_price),
                "slotCashKrw": str(slot_cash),
                "estimatedNotionalKrw": str(quantity * limit_price),
            }
        )
    return payloads


def redact_order_result(result: Any) -> Any:
    if isinstance(result, dict):
        redacted = {}
        for key, value in result.items():
            lk = key.lower()
            if "account" in lk or "token" in lk or "secret" in lk:
                redacted[key] = "[REDACTED]"
            else:
                redacted[key] = redact_order_result(value)
        return redacted
    if isinstance(result, list):
        return [redact_order_result(v) for v in result]
    return result
