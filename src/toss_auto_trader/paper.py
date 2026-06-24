from __future__ import annotations

from decimal import Decimal, ROUND_DOWN
from typing import Optional

from . import db
from .strategy import Signal


class PaperBroker:
    def __init__(
        self,
        db_path: str,
        account_name: str = "default",
        initial_cash_krw: Decimal = Decimal("10000"),
        max_order_krw: Decimal = Decimal("3000"),
        daily_max_orders: int = 3,
        buy_commission_pct: Decimal = Decimal("0"),
        sell_commission_pct: Decimal = Decimal("0"),
        sell_tax_pct: Decimal = Decimal("0"),
        buy_slippage_pct: Decimal = Decimal("0"),
        sell_slippage_pct: Decimal = Decimal("0"),
        simulated_now: str | None = None,
    ) -> None:
        self.db_path = db_path
        self.account_id = db.ensure_paper_account(db_path, account_name, initial_cash_krw)
        self.max_order_krw = max_order_krw
        self.daily_max_orders = daily_max_orders
        self.buy_commission_pct = buy_commission_pct
        self.sell_commission_pct = sell_commission_pct
        self.sell_tax_pct = sell_tax_pct
        self.buy_slippage_pct = buy_slippage_pct
        self.sell_slippage_pct = sell_slippage_pct
        self.simulated_now = simulated_now

    def now(self) -> str:
        return self.simulated_now or db.utc_now()

    def todays_order_count(self) -> int:
        today = self.now()[:10]
        with db.connect(self.db_path) as con:
            row = con.execute(
                "SELECT COUNT(*) AS c FROM paper_orders WHERE account_id = ? AND substr(created_at, 1, 10) = ?",
                (self.account_id, today),
            ).fetchone()
        return int(row["c"])

    def cash(self) -> Decimal:
        with db.connect(self.db_path) as con:
            row = con.execute("SELECT cash_krw FROM paper_accounts WHERE id = ?", (self.account_id,)).fetchone()
        return Decimal(str(row["cash_krw"]))

    def position(self, symbol: str) -> tuple[Decimal, Decimal]:
        with db.connect(self.db_path) as con:
            row = con.execute(
                "SELECT quantity, average_price FROM paper_positions WHERE account_id = ? AND symbol = ?",
                (self.account_id, symbol),
            ).fetchone()
        if not row:
            return Decimal("0"), Decimal("0")
        return Decimal(str(row["quantity"])), Decimal(str(row["average_price"]))

    def execute_signal(self, signal: Signal) -> str:
        if signal.side == "HOLD" or signal.limit_price is None:
            return "HOLD"
        if signal.side == "BUY":
            return self.buy(signal.symbol, signal.limit_price, signal.cash_amount, signal.reason)
        if signal.side == "SELL":
            qty, _ = self.position(signal.symbol)
            if qty <= 0:
                return "NO_POSITION"
            return self.sell(signal.symbol, signal.limit_price, qty, signal.reason)
        return "UNKNOWN"

    def buy(self, symbol: str, price: Decimal, cash_amount: Decimal, reason: Optional[str] = None) -> str:
        if price <= 0 or cash_amount <= 0:
            return "REJECTED_INVALID_BUY"
        if cash_amount > self.max_order_krw:
            return "REJECTED_MAX_ORDER"
        if self.todays_order_count() >= self.daily_max_orders:
            return "REJECTED_DAILY_ORDER_LIMIT"
        exec_price = price * (Decimal("1") + self.buy_slippage_pct)
        quantity = (cash_amount / exec_price).to_integral_value(rounding=ROUND_DOWN)
        if quantity <= 0:
            return "REJECTED_TOO_SMALL"
        amount = quantity * exec_price
        fee = amount * self.buy_commission_pct
        tax = Decimal("0")
        cost = amount + fee
        cash = self.cash()
        if cost > cash:
            return "REJECTED_NO_CASH"
        old_qty, old_avg = self.position(symbol)
        new_qty = old_qty + quantity
        new_avg = ((old_qty * old_avg) + amount) / new_qty
        now = self.now()
        with db.connect(self.db_path) as con:
            con.execute("UPDATE paper_accounts SET cash_krw = ? WHERE id = ?", (str(cash - cost), self.account_id))
            con.execute(
                """INSERT INTO paper_positions(account_id, symbol, quantity, average_price, updated_at)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(account_id, symbol) DO UPDATE SET
                     quantity = excluded.quantity,
                     average_price = excluded.average_price,
                     updated_at = excluded.updated_at""",
                (self.account_id, symbol, str(new_qty), str(new_avg), now),
            )
            con.execute(
                """INSERT INTO paper_orders(account_id, symbol, side, quantity, price, amount, fee_amount, tax_amount, status, reason, created_at)
                   VALUES (?, ?, 'BUY', ?, ?, ?, ?, ?, 'FILLED', ?, ?)""",
                (self.account_id, symbol, str(quantity), str(exec_price), str(amount), str(fee), str(tax), reason, now),
            )
        return "FILLED_BUY"

    def sell(self, symbol: str, price: Decimal, quantity: Decimal, reason: Optional[str] = None) -> str:
        if self.todays_order_count() >= self.daily_max_orders:
            return "REJECTED_DAILY_ORDER_LIMIT"
        held_qty, avg = self.position(symbol)
        if held_qty <= 0:
            return "REJECTED_NO_POSITION"
        sell_qty = min(quantity, held_qty)
        exec_price = price * (Decimal("1") - self.sell_slippage_pct)
        if exec_price <= 0:
            return "REJECTED_INVALID_SELL"
        amount = sell_qty * exec_price
        fee = amount * self.sell_commission_pct
        tax = amount * self.sell_tax_pct
        proceeds = amount - fee - tax
        new_qty = held_qty - sell_qty
        cash = self.cash()
        now = self.now()
        with db.connect(self.db_path) as con:
            con.execute("UPDATE paper_accounts SET cash_krw = ? WHERE id = ?", (str(cash + proceeds), self.account_id))
            if new_qty == 0:
                con.execute("DELETE FROM paper_positions WHERE account_id = ? AND symbol = ?", (self.account_id, symbol))
            else:
                con.execute(
                    "UPDATE paper_positions SET quantity = ?, updated_at = ? WHERE account_id = ? AND symbol = ?",
                    (str(new_qty), now, self.account_id, symbol),
                )
            con.execute(
                """INSERT INTO paper_orders(account_id, symbol, side, quantity, price, amount, fee_amount, tax_amount, status, reason, created_at)
                   VALUES (?, ?, 'SELL', ?, ?, ?, ?, ?, 'FILLED', ?, ?)""",
                (self.account_id, symbol, str(sell_qty), str(exec_price), str(amount), str(fee), str(tax), reason, now),
            )
        return "FILLED_SELL"


def fee_kwargs_from_cfg(cfg: dict, market: str = "KR") -> dict:
    fees = cfg.get("fees", {}).get(market, {})
    execution = cfg.get("execution", {})
    return {
        "buy_commission_pct": Decimal(str(fees.get("buy_commission_pct", 0))),
        "sell_commission_pct": Decimal(str(fees.get("sell_commission_pct", 0))),
        "sell_tax_pct": Decimal(str(fees.get("sell_tax_pct", 0))),
        "buy_slippage_pct": Decimal(str(execution.get("buy_slippage_pct", 0))),
        "sell_slippage_pct": Decimal(str(execution.get("sell_slippage_pct", 0))),
    }
