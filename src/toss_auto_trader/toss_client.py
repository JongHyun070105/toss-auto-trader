from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Optional

from .config import Settings


class TossApiError(RuntimeError):
    def __init__(self, status: int, message: str, body: str = "", headers: Optional[Dict[str, str]] = None) -> None:
        super().__init__(f"Toss API error {status}: {message} {body[:500]}")
        self.status = status
        self.body = body
        self.headers = headers or {}


@dataclass
class Token:
    access_token: str
    token_type: str
    expires_at: float


class TossInvestClient:
    """Small stdlib-only Toss Invest Open API client.

    Implemented from official docs v1.1.1:
    - POST /oauth2/token
    - GET /api/v1/accounts
    - GET /api/v1/prices
    - GET /api/v1/orderbook
    - GET /api/v1/stocks
    - GET /api/v1/exchange-rate
    - GET /api/v1/holdings
    - GET /api/v1/buying-power
    - GET /api/v1/orders
    - GET /api/v1/orders/{orderId}
    - POST /api/v1/orders guarded by live_trading flag
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._token: Optional[Token] = None

    def issue_token(self) -> Token:
        self.settings.require_credentials()
        data = urllib.parse.urlencode(
            {
                "grant_type": "client_credentials",
                "client_id": self.settings.client_id,
                "client_secret": self.settings.client_secret,
            }
        ).encode()
        body = self._raw_request(
            "POST",
            "/oauth2/token",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            body=data,
            auth=False,
        )
        result = json.loads(body)
        token = Token(
            access_token=result["access_token"],
            token_type=result.get("token_type", "Bearer"),
            expires_at=time.time() + int(result.get("expires_in", 3600)) - 60,
        )
        self._token = token
        return token

    def _auth_header(self) -> Dict[str, str]:
        if self._token is None or self._token.expires_at <= time.time():
            self.issue_token()
        assert self._token is not None
        return {"Authorization": f"Bearer {self._token.access_token}"}

    def _raw_request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        body: Optional[bytes] = None,
        auth: bool = True,
        max_retries: int = 2,
    ) -> str:
        url = self.settings.base_url.rstrip("/") + path
        if params:
            query = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
            url = f"{url}?{query}"
        for attempt in range(max_retries + 1):
            final_headers = {"accept": "application/json"}
            if auth:
                final_headers.update(self._auth_header())
            if headers:
                final_headers.update(headers)
            req = urllib.request.Request(url, data=body, headers=final_headers, method=method)
            try:
                with urllib.request.urlopen(req, timeout=20) as resp:
                    return resp.read().decode("utf-8")
            except urllib.error.HTTPError as e:
                err_body = e.read().decode("utf-8", errors="replace")
                response_headers = dict(e.headers.items()) if e.headers else {}
                if e.code == 401 and auth and attempt < max_retries:
                    # Toss tokens can be invalidated by another client/token issuance mid-run.
                    # Refresh once and rebuild the Authorization header on the next attempt.
                    self._token = None
                    time.sleep(min(2 ** attempt, 5))
                    continue
                if e.code == 429 and attempt < max_retries:
                    retry_after = response_headers.get("Retry-After") or response_headers.get("retry-after")
                    delay = float(retry_after) if retry_after and retry_after.isdigit() else min(2 ** attempt, 5)
                    time.sleep(delay)
                    continue
                raise TossApiError(e.code, e.reason, err_body, response_headers) from e
            except urllib.error.URLError as e:
                if attempt < max_retries:
                    time.sleep(min(2 ** attempt, 5))
                    continue
                raise TossApiError(0, str(e.reason)) from e
        raise TossApiError(0, "request failed after retries")

    def request_json(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        payload: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        body = None
        final_headers = dict(headers or {})
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            final_headers["Content-Type"] = "application/json"
        raw = self._raw_request(method, path, params=params, headers=final_headers, body=body)
        return json.loads(raw)

    def get_accounts(self) -> Dict[str, Any]:
        return self.request_json("GET", "/api/v1/accounts")

    def get_prices(self, symbols: Iterable[str]) -> Dict[str, Any]:
        return self.request_json("GET", "/api/v1/prices", params={"symbols": ",".join(symbols)})

    def get_orderbook(self, symbol: str) -> Dict[str, Any]:
        return self.request_json("GET", "/api/v1/orderbook", params={"symbol": symbol})

    def get_stocks(self, symbols: Iterable[str]) -> Dict[str, Any]:
        return self.request_json("GET", "/api/v1/stocks", params={"symbols": ",".join(symbols)})

    def get_exchange_rate(self, base_currency: str = "USD", quote_currency: str = "KRW") -> Dict[str, Any]:
        return self.request_json(
            "GET",
            "/api/v1/exchange-rate",
            params={"baseCurrency": base_currency, "quoteCurrency": quote_currency},
        )

    def get_candles(
        self,
        symbol: str,
        interval: str = "1d",
        count: int = 100,
        before: Optional[str] = None,
        adjusted: bool = True,
    ) -> Dict[str, Any]:
        return self.request_json(
            "GET",
            "/api/v1/candles",
            params={
                "symbol": symbol,
                "interval": interval,
                "count": count,
                "before": before,
                "adjusted": str(adjusted).lower(),
            },
        )

    def _account_headers(self, account_seq: Optional[str] = None) -> Dict[str, str]:
        seq = account_seq or self.settings.account_seq
        if not seq:
            raise RuntimeError("account_seq required. Run `toss-lab api-smoke` or set TOSS_ACCOUNT_SEQ.")
        return {"X-Tossinvest-Account": str(seq)}

    def get_holdings(self, account_seq: Optional[str] = None, symbol: Optional[str] = None) -> Dict[str, Any]:
        return self.request_json(
            "GET", "/api/v1/holdings", params={"symbol": symbol}, headers=self._account_headers(account_seq)
        )

    def get_buying_power(self, account_seq: Optional[str] = None, currency: str = "KRW") -> Dict[str, Any]:
        return self.request_json(
            "GET", "/api/v1/buying-power", params={"currency": currency}, headers=self._account_headers(account_seq)
        )

    def get_market_calendar(self, country: str = "KR", date: Optional[str] = None) -> Dict[str, Any]:
        return self.request_json("GET", f"/api/v1/market-calendar/{country.upper()}", params={"date": date})

    def get_commissions(self, account_seq: Optional[str] = None) -> Dict[str, Any]:
        return self.request_json("GET", "/api/v1/commissions", headers=self._account_headers(account_seq))

    def get_stock_warnings(self, symbol: str) -> Dict[str, Any]:
        return self.request_json("GET", f"/api/v1/stocks/{symbol}/warnings")

    def get_orders(self, account_seq: Optional[str] = None, status: str = "OPEN", symbol: Optional[str] = None) -> Dict[str, Any]:
        return self.request_json(
            "GET",
            "/api/v1/orders",
            params={"status": status, "symbol": symbol},
            headers=self._account_headers(account_seq),
        )

    def get_order(self, order_id: str, account_seq: Optional[str] = None) -> Dict[str, Any]:
        return self.request_json(
            "GET",
            f"/api/v1/orders/{urllib.parse.quote(str(order_id), safe='')}",
            headers=self._account_headers(account_seq),
        )

    def create_order(self, account_seq: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        if self.settings.dry_run or not self.settings.live_trading:
            return {"dryRun": True, "wouldSend": payload}
        return self.request_json("POST", "/api/v1/orders", headers=self._account_headers(account_seq), payload=payload)
