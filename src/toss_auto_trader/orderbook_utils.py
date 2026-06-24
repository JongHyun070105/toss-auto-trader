from __future__ import annotations

from datetime import datetime
from decimal import Decimal, ROUND_DOWN
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")


def _dec(value, default: str = "0") -> Decimal:
    try:
        return Decimal(str(value))
    except Exception:
        return Decimal(default)


def _result(payload: dict) -> dict:
    return payload.get("result", payload) if isinstance(payload, dict) else {}


def best_spread_from_orderbook(payload: dict) -> dict:
    result = _result(payload)
    asks = result.get("asks") or []
    bids = result.get("bids") or []
    if not asks or not bids:
        return {"available": False}
    best_ask = min(_dec(x.get("price")) for x in asks)
    best_bid = max(_dec(x.get("price")) for x in bids)
    mid = (best_ask + best_bid) / Decimal("2")
    spread = best_ask - best_bid
    spread_bps = (spread / mid * Decimal("10000")) if mid > 0 else Decimal("0")
    return {
        "available": True,
        "best_bid": str(best_bid),
        "best_ask": str(best_ask),
        "mid": str(mid),
        "spread": str(spread),
        "spread_bps": str(spread_bps),
    }


def timestamp_staleness(payload: dict, *, max_stale_ms: int = 500, now: datetime | None = None) -> dict:
    result = _result(payload)
    raw = result.get("timestamp") or result.get("time") or result.get("datetime")
    if not raw:
        return {"available": False, "ok": False, "max_stale_ms": max_stale_ms, "reason": "timestamp_missing"}
    try:
        ts = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=KST)
        now_dt = now or datetime.now(ts.tzinfo)
        if now_dt.tzinfo is None:
            now_dt = now_dt.replace(tzinfo=KST)
        ms = abs((now_dt.astimezone(ts.tzinfo) - ts).total_seconds() * 1000)
        return {
            "available": True,
            "timestamp": ts.isoformat(),
            "local_time": now_dt.astimezone(ts.tzinfo).isoformat(),
            "stale_ms": round(ms, 3),
            "max_stale_ms": max_stale_ms,
            "ok": ms <= max_stale_ms,
        }
    except Exception as exc:
        return {"available": False, "ok": False, "max_stale_ms": max_stale_ms, "reason": f"timestamp_parse_error:{str(exc)[:120]}"}


def market_impact_from_orderbook(payload: dict, *, buy_cash_krw: Decimal, levels: int = 5) -> dict:
    result = _result(payload)
    asks = sorted(result.get("asks") or [], key=lambda x: _dec(x.get("price")))[:levels]
    if not asks:
        return {"available": False, "side": "BUY", "levels": levels, "reason": "asks_missing"}
    best_price = _dec(asks[0].get("price"))
    if best_price <= 0 or buy_cash_krw <= 0:
        return {"available": False, "side": "BUY", "levels": levels, "reason": "invalid_cash_or_price"}
    target_qty = (buy_cash_krw / best_price).to_integral_value(rounding=ROUND_DOWN)
    remaining = target_qty
    filled = Decimal("0")
    value = Decimal("0")
    level_rows = []
    for i, row in enumerate(asks, 1):
        price = _dec(row.get("price"))
        vol = _dec(row.get("volume"))
        take = min(remaining, vol) if remaining > 0 else Decimal("0")
        filled += take
        value += take * price
        remaining -= take
        level_rows.append({"level": i, "price": str(price), "volume": str(vol), "take_qty": str(take)})
    top_volume = _dec(asks[0].get("volume"))
    full_fill = target_qty <= filled
    weighted_avg = (value / filled) if filled > 0 else best_price
    impact_bps = ((weighted_avg - best_price) / best_price * Decimal("10000")) if best_price > 0 else Decimal("0")
    return {
        "available": True,
        "side": "BUY",
        "levels": levels,
        "requested_cash_krw": str(buy_cash_krw),
        "target_qty": str(target_qty),
        "best_ask": str(best_price),
        "top_level_volume": str(top_volume),
        "target_exceeds_top_level": target_qty > top_volume,
        "cumulative_qty": str(filled),
        "full_fill_within_levels": full_fill,
        "weighted_avg_price": str(weighted_avg),
        "impact_bps": str(impact_bps),
        "levels_detail": level_rows,
    }
