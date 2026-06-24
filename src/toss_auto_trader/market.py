from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timezone, timedelta
from typing import Any, Callable
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")


@dataclass
class CycleCache:
    values: dict[str, Any]

    def __init__(self) -> None:
        self.values = {}

    def get_or_set(self, key: str, fn: Callable[[], Any]) -> Any:
        if key not in self.values:
            self.values[key] = fn()
        return self.values[key]


def now_kst() -> datetime:
    return datetime.now(KST)


def _parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def is_open_from_calendar(calendar: dict[str, Any], *, when: datetime | None = None, country: str = "KR") -> bool:
    when = when or now_kst()
    today = calendar.get("result", {}).get("today", {})
    if country.upper() == "KR":
        integrated = today.get("integrated") or {}
        sessions = [integrated.get("regularMarket")]
    else:
        sessions = [today.get("dayMarket"), today.get("preMarket"), today.get("regularMarket"), today.get("afterMarket")]
    for session in sessions:
        if not session:
            continue
        start = session.get("startTime")
        end = session.get("endTime")
        if not start or not end:
            continue
        if _parse_dt(start) <= when <= _parse_dt(end):
            return True
    return False


def fallback_market_open(*, when: datetime | None = None, country: str = "KR") -> bool:
    when = when or now_kst()
    if when.weekday() >= 5:
        return False
    t = when.time()
    if country.upper() == "KR":
        return time(9, 0) <= t <= time(15, 30)
    # US regular session in KST is often night/early morning; rough fallback only.
    return t >= time(22, 30) or t <= time(5, 0)


def kr_observation_window_guard(*, when: datetime | None = None, start: time = time(9, 5), end: time = time(15, 20)) -> dict:
    """Guard live-read/paper observation away from opening/closing auctions."""
    when = when or now_kst()
    if when.tzinfo is None:
        when = when.replace(tzinfo=KST)
    local = when.astimezone(KST)
    ok = local.weekday() < 5 and start <= local.time() <= end
    return {
        "ok": ok,
        "local_time": local.isoformat(),
        "timezone": "Asia/Seoul",
        "allowed_start": start.isoformat(timespec="minutes"),
        "allowed_end": end.isoformat(timespec="minutes"),
        "reason": None if ok else "outside_kr_continuous_auction_window",
    }


def second_thursday(year: int, month: int) -> datetime:
    d = datetime(year, month, 1, tzinfo=KST)
    while d.weekday() != 3:
        d += timedelta(days=1)
    return d + timedelta(days=7)


def kr_event_day_flags(*, when: datetime | None = None) -> dict:
    """Lightweight deterministic event-day flags; official holiday/ex-date feeds can replace this later."""
    when = (when or now_kst()).astimezone(KST)
    is_monthly_option_expiry = when.date() == second_thursday(when.year, when.month).date()
    is_quarterly_expiry = is_monthly_option_expiry and when.month in {3, 6, 9, 12}
    is_quarter_end = when.month in {3, 6, 9, 12} and when.day >= 25
    is_year_end = when.month == 12 and when.day >= 20
    flags = {
        "monthly_option_expiry_second_thursday": is_monthly_option_expiry,
        "quarterly_futures_options_expiry_proxy": is_quarterly_expiry,
        "quarter_end_window_proxy": is_quarter_end,
        "year_end_dividend_exdate_window_proxy": is_year_end,
    }
    return {"date": when.date().isoformat(), "flags": flags, "event_day": any(flags.values())}
