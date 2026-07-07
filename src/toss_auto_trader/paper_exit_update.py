from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Mapping

from toss_auto_trader.paper_exit_models import (
    DROP_THRESHOLDS,
    EXIT_EVENTS,
    RISE_THRESHOLDS,
    THRESHOLD_EVENTS,
    PaperEvent,
    append_event,
    now_iso,
    numeric,
    read_events,
)
from toss_auto_trader.paper_exit_outcomes import add_outcomes, build_snapshot


def active_symbols(log_path: Path, now: datetime) -> list[str]:
    events = read_events(log_path)
    today = now.date().isoformat()
    exits = {
        str(event["watch_id"]): event
        for event in events
        if event.get("event") in EXIT_EVENTS and event.get("date") == today and event.get("watch_id")
    }
    closed = {
        str(event["watch_id"])
        for event in events
        if event.get("event") == "paper_exit_price_snapshot"
        and event.get("horizon") == "close"
        and event.get("date") == today
    }
    return sorted(
        str(event["symbol"])
        for watch_id, event in exits.items()
        if watch_id not in closed and event.get("symbol")
    )


def update_watch(log_path: Path, current_prices: Mapping[str, float], now: datetime) -> list[PaperEvent]:
    events = read_events(log_path)
    today = now.date().isoformat()
    added: list[PaperEvent] = []
    exits = [event for event in events if is_today_exit(event, today)]
    watch_ids = {str(event["watch_id"]) for event in exits}
    threshold_keys = existing_threshold_keys(events, watch_ids, "paper_reentry_threshold", "drop_pct")
    rise_threshold_keys = existing_threshold_keys(events, watch_ids, "paper_missed_upside_threshold", "rise_pct")
    outcome_keys = existing_outcome_keys(events, watch_ids)
    snapshot_keys = existing_snapshot_keys(events, watch_ids)
    threshold_events = [event for event in events if event.get("event") in THRESHOLD_EVENTS and same_watch(event, watch_ids)]

    for exit_event in exits:
        snapshot = build_snapshot(exit_event, current_prices, now)
        if snapshot is not None:
            add_once(log_path, added, snapshot, snapshot_keys)

    for stop in [event for event in exits if event.get("event") == "stop_exit"]:
        add_stop_thresholds(log_path, added, threshold_events, threshold_keys, stop, current_prices, today, now)

    for take in [event for event in exits if event.get("event") == "take_profit_exit"]:
        add_take_profit_thresholds(
            log_path,
            added,
            threshold_events,
            rise_threshold_keys,
            take,
            current_prices,
            today,
            now,
        )

    add_outcomes(log_path, added, threshold_events, outcome_keys, current_prices, now)
    return added


def is_today_exit(event: PaperEvent, today: str) -> bool:
    return bool(event.get("event") in EXIT_EVENTS and event.get("date") == today and event.get("watch_id"))


def same_watch(event: PaperEvent, watch_ids: set[str]) -> bool:
    return str(event.get("watch_id")) in watch_ids


def existing_threshold_keys(
    events: list[PaperEvent],
    watch_ids: set[str],
    event_name: str,
    pct_key: str,
) -> set[tuple[str, float]]:
    return {
        (str(event.get("watch_id")), float(event.get(pct_key)))
        for event in events
        if event.get("event") == event_name and event.get(pct_key) is not None and same_watch(event, watch_ids)
    }

def existing_outcome_keys(events: list[PaperEvent], watch_ids: set[str]) -> set[tuple[str, str, str, str]]:
    return {
        (str(event.get("event")), str(event.get("watch_id")), str(event.get("threshold_id")), str(event.get("horizon")))
        for event in events
        if event.get("event") in ("paper_reentry_outcome", "paper_missed_upside_outcome")
        and same_watch(event, watch_ids)
    }


def existing_snapshot_keys(events: list[PaperEvent], watch_ids: set[str]) -> set[tuple[str, str]]:
    return {
        (str(event.get("watch_id")), str(event.get("timestamp")))
        for event in events
        if event.get("event") == "paper_exit_price_snapshot" and same_watch(event, watch_ids)
    }


def add_once(
    log_path: Path,
    added: list[PaperEvent],
    snapshot: PaperEvent,
    snapshot_keys: set[tuple[str, str]],
) -> None:
    key = (str(snapshot.get("watch_id")), str(snapshot.get("timestamp")))
    if key in snapshot_keys:
        return
    append_event(log_path, snapshot)
    added.append(snapshot)
    snapshot_keys.add(key)


def add_stop_thresholds(
    log_path: Path,
    added: list[PaperEvent],
    threshold_events: list[PaperEvent],
    threshold_keys: set[tuple[str, float]],
    stop: PaperEvent,
    current_prices: Mapping[str, float],
    today: str,
    now: datetime,
) -> None:
    watch_id = str(stop["watch_id"])
    symbol = str(stop["symbol"])
    current = current_prices.get(symbol)
    base = numeric(stop, "exit_limit_price") or numeric(stop, "observed_price")
    if current is None or base is None:
        return
    for drop_pct in DROP_THRESHOLDS:
        if (watch_id, drop_pct) in threshold_keys or current > base * (1.0 - drop_pct):
            continue
        threshold: PaperEvent = {
            "event": "paper_reentry_threshold",
            "watch_id": watch_id,
            "threshold_id": f"{int(drop_pct * 100)}pct",
            "date": today,
            "timestamp": now_iso(now),
            "symbol": symbol,
            "name": stop.get("name") or symbol,
            "exit_reason": "stop_loss",
            "drop_pct": drop_pct,
            "base_exit_price": base,
            "trigger_price": base * (1.0 - drop_pct),
            "paper_entry_price": current,
            "paper_only": True,
            "live_order_allowed": False,
        }
        append_event(log_path, threshold)
        added.append(threshold)
        threshold_events.append(threshold)
        threshold_keys.add((watch_id, drop_pct))


def add_take_profit_thresholds(
    log_path: Path,
    added: list[PaperEvent],
    threshold_events: list[PaperEvent],
    threshold_keys: set[tuple[str, float]],
    take: PaperEvent,
    current_prices: Mapping[str, float],
    today: str,
    now: datetime,
) -> None:
    watch_id = str(take["watch_id"])
    symbol = str(take["symbol"])
    current = current_prices.get(symbol)
    base = numeric(take, "exit_limit_price") or numeric(take, "observed_price")
    if current is None or base is None:
        return
    for rise_pct in RISE_THRESHOLDS:
        if (watch_id, rise_pct) in threshold_keys or current < base * (1.0 + rise_pct):
            continue
        threshold = build_missed_upside_threshold(take, current, base, rise_pct, today, now)
        append_event(log_path, threshold)
        added.append(threshold)
        threshold_events.append(threshold)
        threshold_keys.add((watch_id, rise_pct))


def build_missed_upside_threshold(
    take: PaperEvent,
    current: float,
    base: float,
    rise_pct: float,
    today: str,
    now: datetime,
) -> PaperEvent:
    return {
        "event": "paper_missed_upside_threshold",
        "watch_id": str(take["watch_id"]),
        "threshold_id": f"{int(rise_pct * 100)}pct",
        "date": today,
        "timestamp": now_iso(now),
        "symbol": str(take["symbol"]),
        "name": take.get("name") or str(take["symbol"]),
        "exit_reason": "take_profit",
        "rise_pct": rise_pct,
        "base_exit_price": base,
        "trigger_price": base * (1.0 + rise_pct),
        "paper_hold_price": current,
        "missed_upside_pct": (current - base) / base * 100.0,
        "paper_only": True,
        "live_order_allowed": False,
    }
