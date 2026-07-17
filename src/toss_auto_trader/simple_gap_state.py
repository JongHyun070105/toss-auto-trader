from __future__ import annotations

import copy
import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


ACTIVE_ORDER_STATUSES = {"PENDING", "PENDING_CANCEL", "PENDING_REPLACE", "PARTIAL_FILLED"}
TERMINAL_ORDER_STATUSES = {
    "FILLED",
    "CANCELED",
    "REJECTED",
    "CANCEL_REJECTED",
    "REPLACE_REJECTED",
    "REPLACED",
}
KNOWN_ORDER_STATUSES = ACTIVE_ORDER_STATUSES | TERMINAL_ORDER_STATUSES
SYNTHETIC_SELL_STATUSES = {"SUBMITTING", "UNTRACKED"}
TERMINAL_STATE_STATUSES = {"CLOSED", "CLOSED_NO_FILL"}


class StrategyStateError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class OrderSnapshot:
    order_id: str
    symbol: str
    side: str
    status: str
    quantity: int
    filled_quantity: int
    average_filled_price: float | None
    filled_amount: float | None
    ordered_at: str | None


def _positive_int(raw: Any) -> int:
    try:
        value = int(float(str(raw).replace(",", "")))
    except (TypeError, ValueError):
        return 0
    return max(0, value)


def _positive_float(raw: Any) -> float | None:
    try:
        value = float(str(raw).replace(",", ""))
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def order_snapshot(response: dict[str, Any]) -> OrderSnapshot:
    result = response.get("result") if isinstance(response, dict) else None
    order = result if isinstance(result, dict) else response
    if not isinstance(order, dict):
        raise StrategyStateError("order detail response is not an object")
    execution = order.get("execution")
    execution = execution if isinstance(execution, dict) else {}
    order_id = str(order.get("orderId") or "").strip()
    symbol = str(order.get("symbol") or "").strip()
    side = str(order.get("side") or "").strip().upper()
    status = str(order.get("status") or "").strip().upper()
    if not order_id or not symbol or side not in {"BUY", "SELL"} or not status:
        raise StrategyStateError("order detail is missing orderId, symbol, side, or status")
    return OrderSnapshot(
        order_id=order_id,
        symbol=symbol,
        side=side,
        status=status,
        quantity=_positive_int(order.get("quantity")),
        filled_quantity=_positive_int(execution.get("filledQuantity")),
        average_filled_price=_positive_float(execution.get("averageFilledPrice")),
        filled_amount=_positive_float(execution.get("filledAmount")),
        ordered_at=str(order.get("orderedAt") or "").strip() or None,
    )


def new_buy_state(
    *,
    strategy_name: str,
    trade_date: str,
    symbol: str,
    name: str,
    client_order_id: str,
    requested_quantity: int,
    limit_price: float,
    now: datetime,
    order_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "version": 1,
        "strategy_name": strategy_name,
        "trade_date": trade_date,
        "status": "BUY_SUBMITTING",
        "symbol": str(symbol),
        "name": str(name),
        "buy": {
            "order_id": None,
            "client_order_id": client_order_id,
            "requested_quantity": int(requested_quantity),
            "limit_price": float(limit_price),
            "order_payload": copy.deepcopy(order_payload) if order_payload is not None else None,
            "submitted_at": now.isoformat(),
            "status": "SUBMITTING",
            "filled_quantity": 0,
            "average_filled_price": None,
            "cancel_requested_at": None,
        },
        "position": {
            "opened_quantity": 0,
            "remaining_quantity": 0,
            "entry_price": None,
        },
        "sell_orders": [],
        "exit_recorded": False,
        "updated_at": now.isoformat(),
    }


def _validate_state(state: dict[str, Any], strategy_name: str | None = None) -> None:
    if state.get("version") != 1:
        raise StrategyStateError("unsupported strategy state version")
    if strategy_name is not None and state.get("strategy_name") != strategy_name:
        raise StrategyStateError("strategy state belongs to another strategy")
    if not str(state.get("symbol") or "").strip():
        raise StrategyStateError("strategy state is missing symbol")
    if not isinstance(state.get("buy"), dict) or not isinstance(state.get("position"), dict):
        raise StrategyStateError("strategy state is missing buy or position section")
    if not isinstance(state.get("sell_orders"), list):
        raise StrategyStateError("strategy state sell_orders must be a list")


def load_state(path: Path, *, strategy_name: str | None = None) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StrategyStateError(f"cannot read strategy state: {exc}") from exc
    if not isinstance(state, dict):
        raise StrategyStateError("strategy state root must be an object")
    _validate_state(state, strategy_name)
    return state


def save_state(path: Path, state: dict[str, Any]) -> None:
    _validate_state(state)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        json.dump(state, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def append_event(path: Path, event: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")


def _recompute_position(state: dict[str, Any]) -> None:
    buy = state["buy"]
    position = state["position"]
    opened = _positive_int(buy.get("filled_quantity"))
    sold = sum(_positive_int(order.get("filled_quantity")) for order in state["sell_orders"] if isinstance(order, dict))
    remaining = max(0, opened - sold)
    position["opened_quantity"] = opened
    position["remaining_quantity"] = remaining
    if buy.get("average_filled_price"):
        position["entry_price"] = float(buy["average_filled_price"])
    elif opened > 0 and not position.get("entry_price"):
        position["entry_price"] = float(buy.get("limit_price") or 0) or None

    buy_status = str(buy.get("status") or "").upper()
    sell_statuses = [str(order.get("status") or "").upper() for order in state["sell_orders"] if isinstance(order, dict)]
    active_sell = any(status in ACTIVE_ORDER_STATUSES for status in sell_statuses)
    unknown_sell = any(status not in KNOWN_ORDER_STATUSES | SYNTHETIC_SELL_STATUSES for status in sell_statuses)
    untracked_sell = any(status == "UNTRACKED" for status in sell_statuses)
    submitting_sell = any(status == "SUBMITTING" for status in sell_statuses)
    synthetic_buy_statuses = {"SUBMITTING", "SUBMITTED", "SUBMIT_FAILED", "UNTRACKED"}
    unknown_buy = buy_status not in KNOWN_ORDER_STATUSES | synthetic_buy_statuses
    if untracked_sell:
        state["status"] = "EXIT_UNTRACKED"
    elif unknown_sell:
        state["status"] = "EXIT_STATUS_UNKNOWN"
    elif unknown_buy:
        state["status"] = "BUY_STATUS_UNKNOWN"
    elif submitting_sell:
        state["status"] = "EXIT_SUBMITTING"
    elif active_sell:
        state["status"] = "EXIT_PENDING"
    elif opened > 0 and buy_status in ACTIVE_ORDER_STATUSES:
        state["status"] = "BUY_PARTIAL_PENDING"
    elif opened > 0 and remaining == 0:
        state["status"] = "CLOSED"
    elif opened > 0:
        state["status"] = "POSITION_OPEN"
    elif buy_status in ACTIVE_ORDER_STATUSES or buy_status in {"SUBMITTING", "SUBMITTED"}:
        state["status"] = "BUY_PENDING"
    elif buy_status in TERMINAL_ORDER_STATUSES or buy_status == "SUBMIT_FAILED":
        state["status"] = "CLOSED_NO_FILL"
    elif buy_status == "UNTRACKED":
        state["status"] = "BUY_UNTRACKED"


def apply_buy_snapshot(state: dict[str, Any], snapshot: OrderSnapshot, *, now: datetime) -> dict[str, Any]:
    if snapshot.side != "BUY" or snapshot.symbol != state.get("symbol"):
        raise StrategyStateError("buy order detail does not match strategy state")
    updated = copy.deepcopy(state)
    buy = updated["buy"]
    buy["order_id"] = snapshot.order_id
    buy["status"] = snapshot.status
    buy["filled_quantity"] = snapshot.filled_quantity
    buy["average_filled_price"] = snapshot.average_filled_price
    buy["ordered_at"] = snapshot.ordered_at
    _recompute_position(updated)
    updated["updated_at"] = now.isoformat()
    return updated


def apply_buy_submission(
    state: dict[str, Any],
    *,
    order_id: str,
    now: datetime,
) -> dict[str, Any]:
    updated = copy.deepcopy(state)
    updated["buy"]["order_id"] = str(order_id)
    updated["buy"]["status"] = "SUBMITTED"
    _recompute_position(updated)
    updated["updated_at"] = now.isoformat()
    return updated


def add_sell_order(
    state: dict[str, Any],
    *,
    order_id: str | None,
    client_order_id: str,
    trigger: str,
    requested_quantity: int,
    observed_price: float,
    trigger_price: float | None,
    now: datetime,
    order_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    updated = copy.deepcopy(state)
    updated["sell_orders"].append(
        {
            "order_id": str(order_id) if order_id else None,
            "client_order_id": client_order_id,
            "trigger": trigger,
            "requested_quantity": int(requested_quantity),
            "order_payload": copy.deepcopy(order_payload) if order_payload is not None else None,
            "status": "PENDING" if order_id else "SUBMITTING",
            "filled_quantity": 0,
            "average_filled_price": None,
            "filled_amount": None,
            "observed_price": float(observed_price),
            "trigger_price": float(trigger_price) if trigger_price is not None else None,
            "submitted_at": now.isoformat(),
        }
    )
    _recompute_position(updated)
    updated["updated_at"] = now.isoformat()
    return updated


def apply_sell_submission(
    state: dict[str, Any],
    *,
    client_order_id: str,
    order_id: str | None,
    now: datetime,
) -> dict[str, Any]:
    updated = copy.deepcopy(state)
    matches = [order for order in updated["sell_orders"] if order.get("client_order_id") == client_order_id]
    if len(matches) != 1:
        raise StrategyStateError("sell submission intent is not tracked exactly once")
    order = matches[0]
    order["order_id"] = str(order_id) if order_id else None
    order["status"] = "PENDING" if order_id else "UNTRACKED"
    _recompute_position(updated)
    updated["updated_at"] = now.isoformat()
    return updated


def mark_buy_submission_status(
    state: dict[str, Any],
    *,
    status: str,
    now: datetime,
) -> dict[str, Any]:
    updated = copy.deepcopy(state)
    updated["buy"]["status"] = str(status).upper()
    _recompute_position(updated)
    updated["updated_at"] = now.isoformat()
    return updated


def mark_sell_submission_status(
    state: dict[str, Any],
    *,
    client_order_id: str,
    status: str,
    now: datetime,
) -> dict[str, Any]:
    updated = copy.deepcopy(state)
    matches = [order for order in updated["sell_orders"] if order.get("client_order_id") == client_order_id]
    if len(matches) != 1:
        raise StrategyStateError("sell submission intent is not tracked exactly once")
    matches[0]["status"] = str(status).upper()
    _recompute_position(updated)
    updated["updated_at"] = now.isoformat()
    return updated


def apply_sell_snapshot(state: dict[str, Any], snapshot: OrderSnapshot, *, now: datetime) -> dict[str, Any]:
    if snapshot.side != "SELL" or snapshot.symbol != state.get("symbol"):
        raise StrategyStateError("sell order detail does not match strategy state")
    updated = copy.deepcopy(state)
    matches = [order for order in updated["sell_orders"] if str(order.get("order_id")) == snapshot.order_id]
    if len(matches) != 1:
        raise StrategyStateError("sell order detail is not tracked exactly once")
    order = matches[0]
    order["status"] = snapshot.status
    order["filled_quantity"] = snapshot.filled_quantity
    order["average_filled_price"] = snapshot.average_filled_price
    order["filled_amount"] = snapshot.filled_amount
    order["ordered_at"] = snapshot.ordered_at
    _recompute_position(updated)
    updated["updated_at"] = now.isoformat()
    return updated


def active_sell_orders(state: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        order
        for order in state.get("sell_orders", [])
        if isinstance(order, dict) and str(order.get("status") or "").upper() not in TERMINAL_ORDER_STATUSES
    ]


def state_allows_new_buy(state: dict[str, Any] | None, *, trade_date: str | None = None) -> bool:
    if state is None:
        return True
    if str(state.get("status") or "") not in TERMINAL_STATE_STATUSES:
        return False
    return trade_date is None or str(state.get("trade_date") or "") != trade_date
