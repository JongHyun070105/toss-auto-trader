"""Data-integrity rules for raw previous-close to opening-price gaps."""

from __future__ import annotations


# KRX's ordinary daily limit is +/-30% of the day's base price. A one percentage
# point buffer allows tick rounding while flagging raw gaps that compare unlike
# bases or belong to a special regime such as liquidation trading.
MIN_RAW_ENTRY_GAP = -0.31


def is_noncomparable_base_gap(
    raw_gap: float, *, minimum_gap: float = MIN_RAW_ENTRY_GAP
) -> bool:
    """Return True when a raw gap is outside the ordinary comparable-base band."""
    return raw_gap < minimum_gap
