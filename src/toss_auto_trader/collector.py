from __future__ import annotations

from decimal import Decimal
from typing import Iterable

from . import db
from .config import Settings
from .strategy import moving_average_guarded
from .toss_client import TossInvestClient


def collect_prices(settings: Settings, symbols: Iterable[str], *, persist_snapshot: bool = False) -> dict:
    client = TossInvestClient(settings)
    response = client.get_prices(symbols)
    for item in response.get("result", []):
        db.insert_price(settings.db_path, item, source="toss")
    db.prune_prices(settings.db_path, keep_per_symbol=500)
    if persist_snapshot:
        db.insert_snapshot(settings.db_path, "/api/v1/prices", response, {"symbols": list(symbols)})
    return response


def get_candles_on_demand(
    settings: Settings,
    symbol: str,
    interval: str = "1d",
    count: int = 100,
    before: str | None = None,
    adjusted: bool = True,
    *,
    persist_snapshot: bool = False,
) -> dict:
    client = TossInvestClient(settings)
    response = client.get_candles(symbol, interval=interval, count=count, before=before, adjusted=adjusted)
    if persist_snapshot:
        db.insert_snapshot(
            settings.db_path,
            "/api/v1/candles",
            response,
            {"symbol": symbol, "interval": interval, "count": count, "before": before, "adjusted": adjusted},
        )
    return response


def collect_exchange_rate(settings: Settings, base_currency: str = "USD", quote_currency: str = "KRW") -> dict:
    client = TossInvestClient(settings)
    response = client.get_exchange_rate(base_currency, quote_currency)
    db.insert_snapshot(
        settings.db_path,
        "/api/v1/exchange-rate",
        response,
        {"baseCurrency": base_currency, "quoteCurrency": quote_currency},
    )
    return response


def collect_account_snapshot(settings: Settings, account_seq: str | None = None, currency: str = "KRW") -> dict:
    client = TossInvestClient(settings)
    seq = account_seq or settings.account_seq
    out = {}
    if not seq:
        accounts = client.get_accounts()
        db.insert_snapshot(settings.db_path, "/api/v1/accounts", accounts)
        out["accounts"] = accounts
        results = accounts.get("result", [])
        if results:
            seq = str(results[0].get("accountSeq"))
    else:
        out["accountSeq"] = seq
    if seq:
        holdings = client.get_holdings(seq)
        buying_power = client.get_buying_power(seq, currency)
        db.insert_snapshot(settings.db_path, "/api/v1/holdings", holdings, {"accountSeq": seq})
        db.insert_snapshot(settings.db_path, "/api/v1/buying-power", buying_power, {"accountSeq": seq, "currency": currency})
        out.update({"accountSeq": seq, "holdings": holdings, "buyingPower": buying_power})
    return out


def decide_from_recent_prices(db_path: str, symbol: str, trade_cash_krw: Decimal = Decimal("1000")):
    prices = db.recent_prices(db_path, symbol, limit=20)
    signal = moving_average_guarded(symbol, prices, trade_cash_krw)
    db.log_decision(db_path, signal.symbol, signal.side, signal.confidence, signal.reason, signal.limit_price, signal.cash_amount)
    return signal
