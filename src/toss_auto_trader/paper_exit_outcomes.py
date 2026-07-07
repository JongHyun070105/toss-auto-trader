from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Mapping

from toss_auto_trader.paper_exit_models import (
    CLOSE_TIME,
    OUTCOME_MINUTES,
    PaperEvent,
    append_event,
    event_time,
    now_iso,
    numeric,
)


def add_outcomes(
    log_path: Path,
    added: list[PaperEvent],
    threshold_events: list[PaperEvent],
    outcome_keys: set[tuple[str, str, str, str]],
    current_prices: Mapping[str, float],
    now: datetime,
) -> None:
    for threshold in threshold_events:
        symbol = str(threshold.get("symbol"))
        current = current_prices.get(symbol)
        reference_price = numeric(threshold, "paper_entry_price") or numeric(threshold, "paper_hold_price")
        started_at = event_time(threshold)
        if current is None or reference_price is None or started_at is None:
            continue
        elapsed_minutes = (now - started_at).total_seconds() / 60.0
        for minutes in OUTCOME_MINUTES:
            add_outcome_once(
                log_path,
                added,
                outcome_keys,
                threshold,
                current,
                reference_price,
                now,
                f"{minutes}m",
                elapsed_minutes >= minutes,
            )
        add_outcome_once(
            log_path,
            added,
            outcome_keys,
            threshold,
            current,
            reference_price,
            now,
            "close",
            now.time() >= CLOSE_TIME,
        )


def add_outcome_once(
    log_path: Path,
    added: list[PaperEvent],
    outcome_keys: set[tuple[str, str, str, str]],
    threshold: PaperEvent,
    current: float,
    reference_price: float,
    now: datetime,
    horizon: str,
    can_add: bool,
) -> None:
    event_name = outcome_event_name(threshold)
    key = (event_name, str(threshold.get("watch_id")), str(threshold.get("threshold_id")), horizon)
    if key in outcome_keys or not can_add:
        return
    outcome = build_outcome(threshold, current, reference_price, now, horizon)
    append_event(log_path, outcome)
    added.append(outcome)
    outcome_keys.add(key)


def build_snapshot(exit_event: PaperEvent, current_prices: Mapping[str, float], now: datetime) -> PaperEvent | None:
    symbol = str(exit_event.get("symbol") or "")
    current = current_prices.get(symbol)
    exit_price = numeric(exit_event, "exit_limit_price") or numeric(exit_event, "observed_price")
    entry_price = numeric(exit_event, "entry_price")
    exited_at = event_time(exit_event)
    if current is None or exit_price is None or entry_price is None or exited_at is None:
        return None
    return {
        "event": "paper_exit_price_snapshot",
        "watch_id": exit_event.get("watch_id"),
        "date": now.date().isoformat(),
        "timestamp": now_iso(now),
        "symbol": symbol,
        "name": exit_event.get("name") or symbol,
        "exit_reason": str(exit_event.get("exit_reason") or ""),
        "horizon": "close" if now.time() >= CLOSE_TIME else "live",
        "exit_limit_price": exit_price,
        "outcome_price": current,
        "return_from_exit_pct": (current - exit_price) / exit_price * 100.0,
        "return_from_entry_pct": (current - entry_price) / entry_price * 100.0,
        "minutes_since_exit": (now - exited_at).total_seconds() / 60.0,
        "paper_only": True,
        "live_order_allowed": False,
    }


def outcome_event_name(threshold: PaperEvent) -> str:
    if threshold.get("event") == "paper_missed_upside_threshold":
        return "paper_missed_upside_outcome"
    return "paper_reentry_outcome"


def build_outcome(
    threshold: PaperEvent,
    current: float,
    reference_price: float,
    now: datetime,
    horizon: str,
) -> PaperEvent:
    event_name = outcome_event_name(threshold)
    outcome: PaperEvent = {
        "event": event_name,
        "source_event": str(threshold.get("event") or ""),
        "watch_id": threshold.get("watch_id"),
        "threshold_id": threshold.get("threshold_id"),
        "date": now.date().isoformat(),
        "timestamp": now_iso(now),
        "symbol": threshold.get("symbol"),
        "name": threshold.get("name"),
        "exit_reason": str(threshold.get("exit_reason") or ""),
        "horizon": horizon,
        "outcome_price": current,
        "outcome_return_pct": (current - reference_price) / reference_price * 100.0,
        "paper_only": True,
        "live_order_allowed": False,
    }
    if event_name == "paper_missed_upside_outcome":
        outcome["paper_hold_price"] = reference_price
        base = numeric(threshold, "base_exit_price")
        if base is not None:
            outcome["return_from_exit_pct"] = (current - base) / base * 100.0
        return outcome
    outcome["paper_entry_price"] = reference_price
    return outcome
