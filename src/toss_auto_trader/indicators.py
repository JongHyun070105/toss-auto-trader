from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from statistics import mean
from typing import Any


def d(value: Any, default: str = "0") -> Decimal:
    try:
        return Decimal(str(value))
    except Exception:
        return Decimal(default)


def close_prices(candles: list[dict[str, Any]]) -> list[Decimal]:
    ordered = list(reversed(candles))  # Toss latest first -> oldest first
    return [d(c.get("closePrice")) for c in ordered if c.get("closePrice") is not None]


def sma(values: list[Decimal], window: int) -> Decimal | None:
    if len(values) < window:
        return None
    return sum(values[-window:]) / Decimal(window)


def rsi(values: list[Decimal], period: int = 14) -> Decimal | None:
    if len(values) <= period:
        return None
    gains: list[Decimal] = []
    losses: list[Decimal] = []
    for prev, cur in zip(values[-period - 1 : -1], values[-period:]):
        diff = cur - prev
        gains.append(max(diff, Decimal("0")))
        losses.append(abs(min(diff, Decimal("0"))))
    avg_gain = sum(gains) / Decimal(period)
    avg_loss = sum(losses) / Decimal(period)
    if avg_loss == 0:
        return Decimal("100")
    rs = avg_gain / avg_loss
    return Decimal("100") - (Decimal("100") / (Decimal("1") + rs))


def atr(candles: list[dict[str, Any]], period: int = 14) -> Decimal | None:
    ordered = list(reversed(candles))
    if len(ordered) <= period:
        return None
    trs: list[Decimal] = []
    prev_close: Decimal | None = None
    for c in ordered[-period:]:
        high = d(c.get("highPrice"))
        low = d(c.get("lowPrice"))
        close = d(c.get("closePrice"))
        if prev_close is None:
            tr = high - low
        else:
            tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        trs.append(tr)
        prev_close = close
    return sum(trs) / Decimal(len(trs))


def macd(values: list[Decimal]) -> dict[str, Decimal | None]:
    # Lightweight approximation: short/long SMA spread, not full EMA MACD.
    short = sma(values, 12)
    long = sma(values, 26)
    if short is None or long is None:
        return {"macd": None, "signal": None}
    return {"macd": short - long, "signal": None}


def build_technical_features(candles: list[dict[str, Any]]) -> dict[str, Any]:
    prices = close_prices(candles)
    last = prices[-1] if prices else None
    ma5 = sma(prices, 5)
    ma20 = sma(prices, 20)
    ma60 = sma(prices, 60)
    out = {
        "last_close": str(last) if last is not None else None,
        "rsi14": str(rsi(prices, 14)) if rsi(prices, 14) is not None else None,
        "sma5": str(ma5) if ma5 is not None else None,
        "sma20": str(ma20) if ma20 is not None else None,
        "sma60": str(ma60) if ma60 is not None else None,
        "atr14": str(atr(candles, 14)) if atr(candles, 14) is not None else None,
        "ma_alignment": "unknown",
    }
    if ma5 is not None and ma20 is not None and ma60 is not None:
        out["ma_alignment"] = "bullish" if ma5 > ma20 > ma60 else "bearish" if ma5 < ma20 < ma60 else "mixed"
    if last is not None and ma20:
        out["sma20_gap_pct"] = str((last - ma20) / ma20)
    out.update({k: str(v) if v is not None else None for k, v in macd(prices).items()})
    return out
