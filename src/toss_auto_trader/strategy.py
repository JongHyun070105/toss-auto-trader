from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal, Optional

Side = Literal["BUY", "SELL", "HOLD"]


@dataclass(frozen=True)
class Signal:
    symbol: str
    side: Side
    reason: str
    confidence: float = 0.0
    limit_price: Optional[Decimal] = None
    cash_amount: Decimal = Decimal("0")


def moving_average_guarded(symbol: str, prices: list[Decimal], trade_cash: Decimal) -> Signal:
    """Tiny deterministic baseline. Not investment advice.

    Buy when short MA crosses sufficiently above long MA, sell/avoid when below.
    Needs at least 5 samples. It is intentionally conservative for paper trading.
    """
    if len(prices) < 5:
        return Signal(symbol, "HOLD", "not enough price samples", 0.0)
    short = sum(prices[-3:]) / Decimal(3)
    long = sum(prices[-5:]) / Decimal(5)
    last = prices[-1]
    if short > long * Decimal("1.002"):
        return Signal(symbol, "BUY", f"short_ma {short} > long_ma {long} by guard band", 0.55, last, trade_cash)
    if short < long * Decimal("0.998"):
        return Signal(symbol, "SELL", f"short_ma {short} < long_ma {long} by guard band", 0.55, last, Decimal("0"))
    return Signal(symbol, "HOLD", f"no edge: short_ma={short}, long_ma={long}", 0.2, last, Decimal("0"))
