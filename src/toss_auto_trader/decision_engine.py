from __future__ import annotations

from decimal import Decimal
from typing import Any

from . import db
from .agents import coordinator, fee_analyst, news_analyst, performance_feedback, risk_manager, technical_analyst
from .indicators import build_technical_features
from .paper import PaperBroker, fee_kwargs_from_cfg
from .strategy import Signal


def recent_performance_stats(db_path: str, limit: int = 20) -> dict[str, Any]:
    # MVP: use filled paper orders as activity signal. PnL attribution will be expanded later.
    with db.connect(db_path) as con:
        rows = con.execute(
            "SELECT side, status, reason FROM paper_orders ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    closed = len(rows)
    return {"sample_size": closed, "win_rate": 0, "losing_streak": 0, "recent_order_count": closed}


def evaluate_symbol_from_candles(
    db_path: str,
    symbol: str,
    candles: list[dict[str, Any]],
    cfg: dict[str, Any],
    trade_cash_krw: Decimal,
) -> dict[str, Any]:
    features = build_technical_features(candles)
    stats = recent_performance_stats(db_path)
    latest_news = db.latest_news_items(db_path, limit=5)
    opinions = [
        technical_analyst(features, cfg),
        risk_manager(features, cfg),
        fee_analyst(cfg),
        performance_feedback(stats, cfg),
        news_analyst(latest_news, cfg),
    ]
    decision = coordinator(opinions, cfg)
    decision["symbol"] = symbol
    decision["features"] = features
    decision["recent_performance"] = stats
    decision["trade_cash_krw"] = str(trade_cash_krw)
    return decision


def execute_paper_decision(
    db_path: str,
    decision: dict[str, Any],
    trade_cash_krw: Decimal,
    cfg: dict[str, Any],
    *,
    branch: str = "default",
    broker: PaperBroker | None = None,
    log_event: bool = True,
) -> dict[str, Any]:
    if broker is None:
        broker = PaperBroker(
            db_path,
            account_name=branch,
            initial_cash_krw=Decimal(str(cfg.get("paper", {}).get("initial_cash_krw", 10000))),
            max_order_krw=Decimal(str(cfg.get("paper", {}).get("max_order_krw", 3000))),
            daily_max_orders=int(cfg.get("paper", {}).get("daily_max_orders", 3)),
            simulated_now=cfg.get("paper", {}).get("simulated_now"),
            **fee_kwargs_from_cfg(cfg),
        )
    price = Decimal(str(decision.get("features", {}).get("last_close") or "0"))
    signal = Signal(
        symbol=decision["symbol"],
        side=decision["side"],
        reason=decision["reason"],
        confidence=float(decision.get("confidence", 0)),
        limit_price=price if price > 0 else None,
        cash_amount=trade_cash_krw if decision["side"] == "BUY" else Decimal("0"),
    )
    execution = broker.execute_signal(signal)
    if not log_event:
        return {"execution": execution, "event_id": None}
    event_id = db.log_decision_event(
        db_path,
        symbol=signal.symbol,
        side=signal.side,
        execution=execution,
        reason=signal.reason,
        confidence=signal.confidence,
        price=signal.limit_price,
        cash_amount=signal.cash_amount,
        market_context={"features": decision.get("features"), "opinions": decision.get("opinions"), "latest_news": db.latest_news_items(db_path, limit=5)},
        result={"decision": decision, "execution": execution, "summary": db.summary(db_path)},
        branch=branch,
    )
    return {"execution": execution, "event_id": event_id}


def fee_roundtrip_pct(cfg: dict[str, Any], market: str = "KR") -> Decimal:
    fees = cfg.get("fees", {}).get(market, {})
    return Decimal(str(fees.get("buy_commission_pct", 0.0001))) + Decimal(str(fees.get("sell_commission_pct", 0.0001))) + Decimal(str(fees.get("sell_tax_pct", 0.002)))


def mark_decision_outcome(
    db_path: str,
    event_id: int,
    *,
    side: str,
    entry_price: Decimal,
    future_price: Decimal,
    cfg: dict[str, Any],
) -> dict[str, Any]:
    if entry_price <= 0:
        raw_return = Decimal("0")
    else:
        raw_return = (future_price - entry_price) / entry_price
    net_return = raw_return - fee_roundtrip_pct(cfg) if side == "BUY" else Decimal("0")
    # Loss: lower is better. Penalize bad buys, over-trading, and missed positive move on HOLD lightly.
    if side == "BUY":
        loss = float(-net_return)
    elif side == "HOLD":
        loss = float(max(Decimal("0"), raw_return) * Decimal("0.25"))
    else:
        loss = 0.0
    outcome = {
        "entry_price": str(entry_price),
        "future_price": str(future_price),
        "raw_return": str(raw_return),
        "net_return_after_fee": str(net_return),
        "loss": loss,
    }
    db.update_decision_outcome(db_path, event_id, outcome, loss)
    return outcome
