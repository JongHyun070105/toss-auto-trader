from __future__ import annotations

import json
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo


KST = ZoneInfo("Asia/Seoul")
STRATEGY_NAME = "robust_gap5_vi_reopen_shadow_v1"


def _positive_float(value: object) -> float | None:
    try:
        parsed = float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _nonnegative_float(value: object) -> float | None:
    try:
        parsed = float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def parse_timestamp(value: object) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=KST)
    return parsed.astimezone(KST)


def load_vi_events(path: Path, trade_date: str | None = None) -> dict[str, Any]:
    """Join candidate price rows with later VI warning rows from the audit ledger."""
    if not path.exists():
        return {"events": [], "audit_file_exists": False, "audit_lines": 0, "parse_errors": 0}

    price_rows: dict[tuple[str, str], dict[str, Any]] = {}
    warning_rows: dict[tuple[str, str], dict[str, Any]] = {}
    audit_lines = 0
    parse_errors = 0
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        if not raw_line.strip():
            continue
        audit_lines += 1
        try:
            row = json.loads(raw_line)
        except json.JSONDecodeError:
            parse_errors += 1
            continue
        if not isinstance(row, dict):
            parse_errors += 1
            continue
        row_date = str(row.get("trade_date") or "")
        symbol = str(row.get("symbol") or "").strip()
        if not row_date or not symbol or (trade_date and row_date != trade_date):
            continue
        key = (row_date, symbol)
        if _positive_float(row.get("first_minute_open")) is not None:
            price_rows[key] = {**price_rows.get(key, {}), **row}
        warnings = {str(item) for item in (row.get("warnings") or [])}
        if row.get("decision") == "excluded_warning" and "VI_DYNAMIC" in warnings:
            warning_rows[key] = row

    events: list[dict[str, Any]] = []
    for key, warning in warning_rows.items():
        base = price_rows.get(key, {})
        event = {**base, **warning}
        event["trade_date"], event["symbol"] = key
        event["warning_captured_at"] = warning.get("captured_at")
        event["first_minute_open"] = _positive_float(
            warning.get("first_minute_open") or base.get("first_minute_open")
        )
        events.append(event)
    events.sort(
        key=lambda row: (
            str(row.get("trade_date") or ""),
            int(row.get("candidate_rank") or 999999),
            str(row.get("symbol") or ""),
        )
    )
    return {
        "events": events,
        "audit_file_exists": True,
        "audit_lines": audit_lines,
        "parse_errors": parse_errors,
    }


def normalize_minute_candles(candles: Iterable[dict[str, Any]], trade_date: str) -> list[dict[str, Any]]:
    normalized: dict[str, dict[str, Any]] = {}
    for candle in candles:
        candle_at = parse_timestamp(candle.get("timestamp"))
        if candle_at is None or candle_at.date().isoformat() != trade_date:
            continue
        open_price = _positive_float(candle.get("openPrice") or candle.get("open_price"))
        high_price = _positive_float(candle.get("highPrice") or candle.get("high_price"))
        low_price = _positive_float(candle.get("lowPrice") or candle.get("low_price"))
        close_price = _positive_float(candle.get("closePrice") or candle.get("close_price"))
        volume = _nonnegative_float(candle.get("volume"))
        if None in {open_price, high_price, low_price, close_price, volume}:
            continue
        normalized[candle_at.isoformat()] = {
            "timestamp": candle_at.isoformat(),
            "at": candle_at,
            "open": open_price,
            "high": high_price,
            "low": low_price,
            "close": close_price,
            "volume": volume,
        }
    return sorted(normalized.values(), key=lambda row: row["at"])


def _next_full_minute(value: datetime) -> datetime:
    floored = value.replace(second=0, microsecond=0)
    return floored + timedelta(minutes=1)


def _exit_from_candles(
    candles: list[dict[str, Any]],
    entry_price: float,
    *,
    stop_loss: float,
    take_profit: float,
) -> tuple[float, str, str]:
    stop_price = entry_price * (1.0 - stop_loss)
    take_price = entry_price * (1.0 + take_profit)
    for candle in candles:
        stop_hit = candle["low"] <= stop_price
        take_hit = candle["high"] >= take_price
        if stop_hit:
            # Minute bars cannot resolve an intrabar stop/take tie, so use stop first.
            return min(candle["open"], stop_price), "stop", candle["timestamp"]
        if take_hit:
            return max(candle["open"], take_price), "take", candle["timestamp"]
    last = candles[-1]
    return last["close"], "close", last["timestamp"]


def simulate_vi_reopen_event(
    event: dict[str, Any],
    candles: Iterable[dict[str, Any]],
    *,
    capital_krw: float = 10_000.0,
    roundtrip_cost_pct: float = 1.35,
    stop_loss_pct: float = 2.25,
    take_profit_pct: float = 12.0,
    opening_limit_cancel_time: time = time(9, 5),
) -> dict[str, Any]:
    trade_date = str(event.get("trade_date") or "")
    symbol = str(event.get("symbol") or "").strip()
    warning_at = parse_timestamp(event.get("warning_captured_at") or event.get("captured_at"))
    base = {
        "strategy_name": STRATEGY_NAME,
        "trade_date": trade_date,
        "symbol": symbol,
        "candidate_rank": event.get("candidate_rank"),
        "warning_captured_at": warning_at.isoformat() if warning_at else None,
        "paper_only": True,
        "order_sent": False,
        "live_order_allowed": False,
        "roundtrip_cost_pct": roundtrip_cost_pct,
    }
    if not trade_date or not symbol or warning_at is None:
        return {**base, "status": "invalid_event"}

    rows = normalize_minute_candles(candles, trade_date)
    observation_start = _next_full_minute(warning_at)
    regular_close = datetime.combine(warning_at.date(), time(15, 30), tzinfo=KST)
    eligible = [row for row in rows if observation_start <= row["at"] <= regular_close]
    traded = [row for row in eligible if row["volume"] > 0]
    if not traded:
        return {
            **base,
            "status": "no_post_warning_trade",
            "observation_start": observation_start.isoformat(),
            "minute_candles": len(eligible),
        }

    entry = traded[0]
    entry_price = entry["open"]
    quantity = int(capital_krw // entry_price)
    if quantity <= 0:
        return {
            **base,
            "status": "insufficient_capital",
            "reopen_timestamp": entry["timestamp"],
            "reopen_price": entry_price,
        }

    opening_price = _positive_float(event.get("first_minute_open"))
    cancel_at = datetime.combine(warning_at.date(), opening_limit_cancel_time, tzinfo=KST)
    limit_window = [row for row in traded if row["at"] < cancel_at]
    opening_limit_fillable = bool(
        opening_price is not None
        and any(row["low"] <= opening_price <= row["high"] for row in limit_window)
    )
    path = [row for row in rows if entry["at"] <= row["at"] <= regular_close and row["volume"] > 0]
    exit_price, exit_reason, exit_timestamp = _exit_from_candles(
        path,
        entry_price,
        stop_loss=stop_loss_pct / 100.0,
        take_profit=take_profit_pct / 100.0,
    )
    invested = quantity * entry_price
    gross_pnl = quantity * (exit_price - entry_price)
    estimated_cost = invested * (roundtrip_cost_pct / 100.0)
    net_pnl = gross_pnl - estimated_cost
    return {
        **base,
        "status": "simulated",
        "observation_start": observation_start.isoformat(),
        "original_open_price": opening_price,
        "opening_limit_cancel_at": cancel_at.isoformat(),
        "opening_limit_fillable_before_cancel": opening_limit_fillable,
        "reopen_timestamp": entry["timestamp"],
        "reopen_price": entry_price,
        "reopen_premium_to_open_pct": (
            (entry_price / opening_price - 1.0) * 100.0 if opening_price else None
        ),
        "quantity": quantity,
        "invested_krw": invested,
        "exit_timestamp": exit_timestamp,
        "exit_price": exit_price,
        "exit_reason": exit_reason,
        "gross_return_pct": (exit_price / entry_price - 1.0) * 100.0,
        "estimated_cost_krw": estimated_cost,
        "net_pnl_krw": net_pnl,
        "net_return_on_invested_pct": net_pnl / invested * 100.0,
    }


def summarize_simulations(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    all_rows = list(rows)
    simulated = [row for row in all_rows if row.get("status") == "simulated"]
    net_values = [float(row["net_pnl_krw"]) for row in simulated]
    return {
        "events": len(all_rows),
        "simulated": len(simulated),
        "wins": sum(value > 0 for value in net_values),
        "losses": sum(value < 0 for value in net_values),
        "total_net_pnl_krw": sum(net_values),
        "average_net_pnl_krw": sum(net_values) / len(net_values) if net_values else None,
        "opening_limit_fillable_before_cancel": sum(
            bool(row.get("opening_limit_fillable_before_cancel")) for row in simulated
        ),
        "exit_reasons": {
            reason: sum(row.get("exit_reason") == reason for row in simulated)
            for reason in ("stop", "take", "close")
        },
        "strategy_alpha_claim": False,
    }
