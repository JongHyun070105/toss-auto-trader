from __future__ import annotations

import json
from datetime import datetime, time
from pathlib import Path
from typing import Final, TypedDict


class PaperEvent(TypedDict, total=False):
    event: str
    watch_id: str
    threshold_id: str
    date: str
    timestamp: str
    symbol: str
    name: str
    horizon: str
    qty: int
    entry_price: float
    stop_price: float
    take_price: float
    trigger_price: float
    exit_reason: str
    observed_price: float
    exit_limit_price: float
    order_id: str
    drop_pct: float
    rise_pct: float
    base_exit_price: float
    paper_entry_price: float
    paper_hold_price: float
    outcome_price: float
    outcome_return_pct: float
    missed_upside_pct: float
    return_from_exit_pct: float
    return_from_entry_pct: float
    minutes_since_exit: float
    source_event: str
    paper_only: bool
    live_order_allowed: bool


DROP_THRESHOLDS: Final = (0.03, 0.05, 0.07)
RISE_THRESHOLDS: Final = (0.03, 0.05, 0.07)
OUTCOME_MINUTES: Final = (10, 30)
CLOSE_TIME: Final = time(15, 20)
EXIT_EVENTS: Final = ("stop_exit", "take_profit_exit")
THRESHOLD_EVENTS: Final = ("paper_reentry_threshold", "paper_missed_upside_threshold")


def read_events(log_path: Path) -> list[PaperEvent]:
    if not log_path.exists():
        return []
    events: list[PaperEvent] = []
    for line in log_path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            events.append(event)
    return events


def append_event(log_path: Path, event: PaperEvent) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as fp:
        fp.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")


def event_time(event: PaperEvent) -> datetime | None:
    raw = event.get("timestamp")
    if not isinstance(raw, str) or not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def numeric(event: PaperEvent, key: str) -> float | None:
    raw = event.get(key)
    try:
        value = float(str(raw).replace(",", ""))
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def now_iso(now: datetime) -> str:
    return now.replace(microsecond=0).isoformat()


def watch_id(symbol: str, now: datetime) -> str:
    return f"{now.strftime('%Y%m%d%H%M')}-{symbol}"


def record_stop_exit(
    log_path: Path,
    *,
    symbol: str,
    name: str,
    qty: int,
    entry_price: float,
    stop_price: float,
    observed_price: float,
    exit_limit_price: float,
    order_id: str | None,
    now: datetime,
) -> PaperEvent:
    event: PaperEvent = {
        "event": "stop_exit",
        "watch_id": watch_id(symbol, now),
        "date": now.date().isoformat(),
        "timestamp": now_iso(now),
        "symbol": symbol,
        "name": name,
        "qty": qty,
        "exit_reason": "stop_loss",
        "entry_price": entry_price,
        "stop_price": stop_price,
        "trigger_price": stop_price,
        "observed_price": observed_price,
        "exit_limit_price": exit_limit_price,
        "order_id": order_id or "",
        "paper_only": True,
        "live_order_allowed": False,
    }
    append_event(log_path, event)
    return event


def record_take_profit_exit(
    log_path: Path,
    *,
    symbol: str,
    name: str,
    qty: int,
    entry_price: float,
    take_price: float,
    observed_price: float,
    exit_limit_price: float,
    order_id: str | None,
    now: datetime,
) -> PaperEvent:
    event: PaperEvent = {
        "event": "take_profit_exit",
        "watch_id": watch_id(symbol, now),
        "date": now.date().isoformat(),
        "timestamp": now_iso(now),
        "symbol": symbol,
        "name": name,
        "qty": qty,
        "exit_reason": "take_profit",
        "entry_price": entry_price,
        "take_price": take_price,
        "trigger_price": take_price,
        "observed_price": observed_price,
        "exit_limit_price": exit_limit_price,
        "order_id": order_id or "",
        "paper_only": True,
        "live_order_allowed": False,
    }
    append_event(log_path, event)
    return event
