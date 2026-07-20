#!/usr/bin/env python3
"""
TOSS API 연동 갭 하락 반등 실전/모의 자동매매 봇
- 오전 09:01 실행: 코스닥 지수 가드 체크 -> robust 갭하락 종목 스캔 -> 제한 추격 지정가 매수 주문
- 장중 실행: 보유 종목 손절/익절 모니터링
- 오후 15:20 실행: 전략 소유 잔여 수량 시장가 청산
"""
import argparse
import fcntl
import json
import os
import sqlite3
import re
import subprocess
import urllib.request
import urllib.parse
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, time as clock_time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

# src 디렉토리 추가
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from toss_auto_trader.config import Settings
from toss_auto_trader import breadth_shadow
from toss_auto_trader import paper_reentry_watch
from toss_auto_trader import simple_gap_state
from toss_auto_trader.discord_notify import MonitorExitAlert, format_monitor_exit_alert, send_discord_message
from toss_auto_trader.paper_exit_messages import format_paper_event
from toss_auto_trader.toss_client import TossInvestClient, TossApiError

DB_PATH = "data/edge_research_universe_15y.sqlite3"
PAPER_REENTRY_LOG = Path("logs") / "simple_gap_reentry_watch.jsonl"
STRATEGY_STATE_PATH = Path("logs") / "simple_gap_trader_state.json"
STRATEGY_EVENT_LOG = Path("logs") / "simple_gap_trader_events.jsonl"
STRATEGY_LOCK_PATH = Path("logs") / "simple_gap_trader.lock"
BREADTH_SHADOW_LOG = Path("logs") / "simple_gap_breadth_shadow.jsonl"
MAX_BUY_AMOUNT_KRW = 10000
MIN_PRICE = 1000
MAX_PRICE = 8000
GAP_THRESHOLD = -0.05
PREV_VOL_RATIO_MAX = 0.8
STOP_LOSS_PCT = 0.0225
TAKE_PROFIT_PCT = 0.12
KOSDAQ_SMA5_BUY_RATIO = 0.99
MAX_BUY_CHASE_PCT = 0.005
MARKET_DATA_MAX_AGE_SECONDS = 300
MARKET_PRICE_CROSSCHECK_MAX_PCT = 0.001
BUY_ORDER_MAX_WAIT_SECONDS = 30
ORDER_IDEMPOTENCY_WINDOW_SECONDS = 600
LIVE_BUY_WINDOW_START = clock_time(9, 0)
LIVE_BUY_WINDOW_END = clock_time(9, 5)
KST = ZoneInfo("Asia/Seoul")
STRATEGY_NAME = "robust_gap5_stop0225_take12"
BLOCKED_WARNING_TYPES = {
    "LIQUIDATION_TRADING",     # 정리매매
    "OVERHEATED",              # 단기과열
    "INVESTMENT_WARNING",      # 투자경고
    "INVESTMENT_RISK",         # 투자위험
    "VI_STATIC_AND_DYNAMIC",   # VI 동시 발동
    "VI_STATIC",
    "VI_DYNAMIC",
    "STOCK_WARRANTS",          # 신주인수권
}
NAVER_BLOCKED_BADGES = {
    "투자주의",
    "투자경고",
    "투자위험",
    "단기과열",
    "관리종목",
    "거래정지",
}


@dataclass(frozen=True, slots=True)
class MarketGateSnapshot:
    current_index: float
    open_price: float
    sma5: float
    buy_line: float
    timestamp: str
    previous_business_day: str
    freshness_source: str = "indicator_timestamp"


class AmbiguousOrderSubmission(RuntimeError):
    """The request may have reached Toss, but no reliable orderId was observed."""


@contextmanager
def strategy_process_lock(path: Path = STRATEGY_LOCK_PATH):
    """Prevent overlapping cron invocations from entering an order critical section."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as handle:
        acquired = False
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            acquired = True
        except BlockingIOError:
            pass
        try:
            yield acquired
        finally:
            if acquired:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def build_client_order_id(side: str, symbol: str, *, now: datetime | None = None) -> str:
    """Short idempotency key accepted by Toss: alnum, '-' and '_' only, max 36 chars."""
    ts = (now or datetime.now()).strftime("%Y%m%d%H%M")
    side_code = "B" if side.upper() == "BUY" else "S"
    safe_symbol = "".join(ch for ch in str(symbol) if ch.isalnum())[:10]
    return f"sg-{ts}-{side_code}-{safe_symbol}"[:36]


def build_market_quantity_order(symbol: str, side: str, quantity: int | str, *, now: datetime | None = None) -> dict:
    """Official Toss quantity-based MARKET order payload.

    Open API v1.1.x requires `orderType`; MARKET orders must not include `price`.
    """
    qty_int = int(float(quantity))
    if qty_int <= 0:
        raise ValueError("quantity must be positive")
    return {
        "clientOrderId": build_client_order_id(side, symbol, now=now),
        "symbol": str(symbol),
        "side": side.upper(),
        "orderType": "MARKET",
        "timeInForce": "DAY",
        "quantity": str(qty_int),
    }


def build_limit_quantity_order(symbol: str, side: str, quantity: int | str, price: int | float | str, *, now: datetime | None = None) -> dict:
    """Official Toss quantity-based LIMIT order payload for KR stocks."""
    qty_int = int(float(quantity))
    price_int = int(float(str(price).replace(",", "")))
    if qty_int <= 0:
        raise ValueError("quantity must be positive")
    if price_int <= 0:
        raise ValueError("price must be positive")
    return {
        "clientOrderId": build_client_order_id(side, symbol, now=now),
        "symbol": str(symbol),
        "side": side.upper(),
        "orderType": "LIMIT",
        "timeInForce": "DAY",
        "quantity": str(qty_int),
        "price": str(price_int),
    }


def extract_blocking_warnings(warnings_resp: dict) -> list[str]:
    warnings = warnings_resp.get("result", []) if isinstance(warnings_resp, dict) else []
    blocked = []
    for item in warnings or []:
        if not isinstance(item, dict):
            continue
        warning_type = str(item.get("warningType") or "").strip()
        if warning_type in BLOCKED_WARNING_TYPES:
            blocked.append(warning_type)
    return blocked


def naver_warning_badges(symbol: str) -> list[str]:
    """Read Naver/KRX badge labels not exposed by Toss warnings, e.g. 투자주의."""
    url = f"https://finance.naver.com/item/main.naver?code={urllib.parse.quote(str(symbol))}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=6) as resp:
        html = resp.read().decode("utf-8", "ignore")
    # Badge near the stock header: <em class="caution"><span class="blind">투자주의</span></em>
    badges = []
    for m in re.finditer(r'<em[^>]*class="[^"]*caution[^"]*"[^>]*>.*?<span[^>]*class="blind"[^>]*>(.*?)</span>.*?</em>', html, re.S):
        label = re.sub(r"\s+", "", m.group(1) or "")
        if label in NAVER_BLOCKED_BADGES and label not in badges:
            badges.append(label)
    return badges


def blocking_warnings_for_symbol(client: TossInvestClient, symbol: str) -> list[str]:
    """Return active buy-warning types; fail closed if warnings cannot be checked."""
    blocked = []
    try:
        blocked.extend(extract_blocking_warnings(client.get_stock_warnings(symbol)))
    except Exception as e:
        blocked.append(f"TOSS_WARNING_CHECK_FAILED:{type(e).__name__}:{str(e)[:120]}")
    try:
        for badge in naver_warning_badges(symbol):
            blocked.append(f"NAVER_BADGE:{badge}")
    except Exception as e:
        blocked.append(f"NAVER_BADGE_CHECK_FAILED:{type(e).__name__}:{str(e)[:120]}")
    return blocked


def best_limit_price(client: TossInvestClient, symbol: str, side: str, fallback_price: float) -> int:
    """Use best ask for BUY and best bid for SELL. Fallback to known current price."""
    try:
        ob = client.get_orderbook(symbol).get("result", {})
        if side.upper() == "BUY":
            prices = [float(level.get("price", 0) or 0) for level in ob.get("asks", [])]
            valid = [p for p in prices if p > 0]
            if valid:
                return int(min(valid))
        else:
            prices = [float(level.get("price", 0) or 0) for level in ob.get("bids", [])]
            valid = [p for p in prices if p > 0]
            if valid:
                return int(max(valid))
    except Exception as e:
        print(f"[경고] {symbol} 호가 조회 실패, 현재가 기준 지정가 사용: {e}")
    return int(float(fallback_price))


def acceptable_buy_limit_price(client: TossInvestClient, target: dict) -> int | None:
    open_price = float(target['open_price'])
    quote_price = best_limit_price(client, target['symbol'], "BUY", target['last_price'])
    max_allowed = open_price * (1.0 + MAX_BUY_CHASE_PCT)
    if quote_price > max_allowed:
        drift_pct = (quote_price - open_price) / open_price * 100.0
        print(
            f"  ⏭️ [{target['symbol']}] {target['name']} 매수 호가가 시가 대비 너무 높아 제외 "
            f"(시가 {open_price:,.0f}원, 매수호가 {quote_price:,.0f}원, 이탈 {drift_pct:.2f}%, "
            f"허용 {MAX_BUY_CHASE_PCT * 100:.2f}%)"
        )
        return None
    return quote_price


def provisional_gap_threshold() -> float:
    """Broad current-price prefilter that cannot exclude a chase-eligible open gap."""
    return (1.0 + GAP_THRESHOLD) * (1.0 + MAX_BUY_CHASE_PCT) - 1.0


def parse_positive_float(raw) -> float | None:
    if raw is None:
        return None
    try:
        value = float(str(raw).replace(",", "").strip())
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def normalize_order_id(raw) -> str | None:
    if raw is None:
        return None
    value = str(raw).strip()
    if not value or value.lower() in {"none", "null"} or value == "확인 필요":
        return None
    return value


def extract_order_id(response: dict) -> str | None:
    order_id = normalize_order_id(response.get("orderId") or response.get("id"))
    if order_id is not None:
        return order_id
    result = response.get("result")
    if isinstance(result, dict):
        return normalize_order_id(result.get("orderId") or result.get("id"))
    return None


def submission_error_is_ambiguous(exc: Exception) -> bool:
    """Return True when Toss may have accepted the order despite the local error."""
    if isinstance(exc, AmbiguousOrderSubmission):
        return True
    if isinstance(exc, TossApiError):
        return exc.status == 0 or exc.status in {408, 409, 429} or exc.status >= 500
    if isinstance(exc, ValueError):
        return False
    return True


def submit_order_with_idempotent_replay(
    client: TossInvestClient,
    settings: Settings,
    payload: dict,
) -> tuple[dict, str | None]:
    """Submit once, replaying the exact payload only when a 2xx response lacks orderId."""
    exact_payload = dict(payload)
    response = client.create_order(settings.account_seq, exact_payload)
    if response.get("dryRun"):
        return response, None
    order_id = extract_order_id(response)
    if order_id:
        return response, order_id

    print("  ⚠️ 주문 응답에 orderId가 없어 동일 clientOrderId와 동일 본문으로 한 번 재조회합니다.")
    try:
        replayed = client.create_order(settings.account_seq, dict(exact_payload))
    except Exception as exc:
        raise AmbiguousOrderSubmission(f"idempotent replay failed: {exc}") from exc
    order_id = extract_order_id(replayed)
    if not order_id:
        raise AmbiguousOrderSubmission("idempotent replay returned no orderId")
    return replayed, order_id


def _within_idempotency_window(raw_submitted_at, *, now: datetime) -> bool:
    try:
        submitted_at = datetime.fromisoformat(str(raw_submitted_at).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return False
    if submitted_at.tzinfo is None:
        return False
    age = (now.astimezone(submitted_at.tzinfo) - submitted_at).total_seconds()
    return -5 <= age < ORDER_IDEMPOTENCY_WINDOW_SECONDS


def _buy_order_payload_from_state(state: dict) -> dict | None:
    buy = state.get("buy", {})
    payload = buy.get("order_payload")
    if isinstance(payload, dict):
        return dict(payload)
    client_order_id = str(buy.get("client_order_id") or "").strip()
    symbol = str(state.get("symbol") or "").strip()
    quantity = int(buy.get("requested_quantity") or 0)
    limit_price = int(float(buy.get("limit_price") or 0))
    if not client_order_id or not symbol or quantity <= 0 or limit_price <= 0:
        return None
    return {
        "clientOrderId": client_order_id,
        "symbol": symbol,
        "side": "BUY",
        "orderType": "LIMIT",
        "timeInForce": "DAY",
        "quantity": str(quantity),
        "price": str(limit_price),
    }


def _sell_order_payload_from_state(state: dict, sell_order: dict) -> dict | None:
    payload = sell_order.get("order_payload")
    if isinstance(payload, dict):
        return dict(payload)
    client_order_id = str(sell_order.get("client_order_id") or "").strip()
    symbol = str(state.get("symbol") or "").strip()
    quantity = int(sell_order.get("requested_quantity") or 0)
    if not client_order_id or not symbol or quantity <= 0:
        return None
    return {
        "clientOrderId": client_order_id,
        "symbol": symbol,
        "side": "SELL",
        "orderType": "MARKET",
        "timeInForce": "DAY",
        "quantity": str(quantity),
    }


def first_positive_float(row: dict, keys: tuple[str, ...]) -> float | None:
    for key in keys:
        value = parse_positive_float(row.get(key))
        if value is not None:
            return value
    return None


def holding_quantity(row: dict) -> int:
    value = parse_positive_float(row.get("quantity"))
    return int(value or 0)


def holding_average_price(row: dict) -> float | None:
    return first_positive_float(
        row,
        (
            "averagePrice",
            "averagePurchasePrice",
            "avgPrice",
            "averageUnitPrice",
            "purchasePrice",
            "buyPrice",
        ),
    )


def stop_price(entry_price: float) -> float:
    return entry_price * (1.0 - STOP_LOSS_PCT)


def take_price(entry_price: float) -> float:
    return entry_price * (1.0 + TAKE_PROFIT_PCT)


def has_open_sell_order(client: TossInvestClient, settings: Settings, symbol: str) -> bool | None:
    try:
        resp = client.get_orders(settings.account_seq, status="OPEN", symbol=symbol)
    except Exception as e:
        print(f"  ⚠️ [{symbol}] 열린 매도 주문 확인 실패: {e}")
        return None
    result = resp.get("result", {}) if isinstance(resp, dict) else {}
    if isinstance(result, dict):
        orders = result.get("orders", [])
    elif isinstance(result, list):
        orders = result
    else:
        orders = []
    for order in orders or []:
        if not isinstance(order, dict):
            continue
        if str(order.get("side") or "").upper() == "SELL":
            return True
    return False


def configured_max_buy_amount_krw() -> float | None:
    """매수 상한. 기본값은 10,000원이며 빈 값이면 계좌 매수가능금액 전체를 사용한다."""
    raw = os.getenv("TOSS_MAX_BUY_AMOUNT_KRW", str(MAX_BUY_AMOUNT_KRW)).strip().replace(",", "")
    if not raw:
        return None
    value = float(raw)
    return value if value > 0 else None


def fetch_naver_kosdaq_closes() -> list[float]:
    """Historical compatibility helper for research scripts, not the live gate."""
    today_str = datetime.now().strftime("%Y%m%d")
    query = urllib.parse.urlencode({'startDateTime': '202601010000', 'endDateTime': f'{today_str}2359'})
    url = f'https://api.stock.naver.com/chart/domestic/index/KOSDAQ/day?{query}'
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0', 'Referer': 'https://finance.naver.com/'})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode('utf-8'))
        return [float(str(row['closePrice']).replace(',', '')) for row in data or []]
    except Exception as e:
        print(f"[경고] 네이버 지수 API 호출 실패: {e}")
        return []


def fetch_kosdaq_index() -> list[float]:
    """기존 연구 스크립트 호환용 최근 코스닥 종가 목록."""
    return fetch_naver_kosdaq_closes()


def _aware_now(now: datetime | None = None) -> datetime:
    value = now or datetime.now().astimezone()
    if value.tzinfo is None:
        value = value.astimezone()
    return value


def live_buy_window_allows(settings: Settings, now: datetime | None = None) -> bool:
    live_submission = bool(getattr(settings, "live_trading", False) and not getattr(settings, "dry_run", True))
    if not live_submission:
        return True
    current = _aware_now(now).astimezone(KST).time()
    return LIVE_BUY_WINDOW_START <= current < LIVE_BUY_WINDOW_END


def fetch_kosdaq_market_data(
    client: TossInvestClient,
    *,
    now: datetime | None = None,
) -> MarketGateSnapshot | None:
    """Build a fail-closed live KOSDAQ snapshot from official Toss endpoints."""
    checked_at = _aware_now(now)
    today = checked_at.date().isoformat()
    try:
        calendar_resp = client.get_market_calendar("KR", date=today)
        calendar = calendar_resp.get("result", {}) if isinstance(calendar_resp, dict) else {}
        today_row = calendar.get("today", {}) if isinstance(calendar, dict) else {}
        previous_row = calendar.get("previousBusinessDay", {}) if isinstance(calendar, dict) else {}
        integrated = today_row.get("integrated") if isinstance(today_row, dict) else None
        regular_market = integrated.get("regularMarket") if isinstance(integrated, dict) else None
        previous_business_day = str(previous_row.get("date") or "") if isinstance(previous_row, dict) else ""
        if today_row.get("date") != today or not isinstance(regular_market, dict) or not previous_business_day:
            print("[시장 가드 차단] 오늘이 정상 영업일인지 확인할 수 없습니다.")
            return None
        regular_start_raw = str(regular_market.get("startTime") or "")
        regular_end_raw = str(regular_market.get("endTime") or "")
        if not regular_start_raw or not regular_end_raw:
            print("[시장 가드 차단] Toss 정규장 시작·종료 시각이 비어 있습니다.")
            return None
        regular_start = datetime.fromisoformat(regular_start_raw.replace("Z", "+00:00"))
        regular_end = datetime.fromisoformat(regular_end_raw.replace("Z", "+00:00"))
        if regular_start.tzinfo is None or regular_end.tzinfo is None:
            print("[시장 가드 차단] Toss 정규장 시각에 타임존이 없습니다.")
            return None
        checked_in_market_tz = checked_at.astimezone(regular_start.tzinfo)
        strategy_window_end = min(regular_end, regular_start + timedelta(minutes=5))
        if not (regular_start <= checked_in_market_tz < strategy_window_end):
            print(
                f"[시장 가드 차단] 현재 시각이 오늘 정규장 시작 후 5분 이내가 아닙니다. "
                f"(현재 {checked_in_market_tz.isoformat()}, 정규장 {regular_start_raw}~{regular_end_raw})"
            )
            return None

        prices_resp = client.get_market_indicator_prices(["KOSDAQ"])
        price_rows = prices_resp.get("result", []) if isinstance(prices_resp, dict) else []
        matches = [row for row in price_rows or [] if str(row.get("symbol") or "").upper() == "KOSDAQ"]
        if len(matches) != 1:
            print("[시장 가드 차단] Toss KOSDAQ 현재가가 정확히 1건 수신되지 않았습니다.")
            return None
        price_row = matches[0]
        current_index = parse_positive_float(price_row.get("lastPrice"))
        indicator_timestamp = str(price_row.get("timestamp") or "").strip()
        if current_index is None:
            print("[시장 가드 차단] Toss KOSDAQ 현재가가 비어 있습니다.")
            return None
        freshness_source = "indicator_timestamp"
        if indicator_timestamp:
            market_at = datetime.fromisoformat(indicator_timestamp.replace("Z", "+00:00"))
            if market_at.tzinfo is None:
                print("[시장 가드 차단] Toss KOSDAQ 현재가 시각에 타임존이 없습니다.")
                return None
            age_seconds = (checked_at.astimezone(market_at.tzinfo) - market_at).total_seconds()
            if market_at.date().isoformat() != today or age_seconds < -60 or age_seconds > MARKET_DATA_MAX_AGE_SECONDS:
                print(
                    f"[시장 가드 차단] Toss KOSDAQ 현재가가 당일 최신값이 아닙니다. "
                    f"(지수시각 {indicator_timestamp}, age={age_seconds:.0f}s)"
                )
                return None

        candles_resp = client.get_market_indicator_candles("KOSDAQ", "1d", count=10)
        result = candles_resp.get("result", {}) if isinstance(candles_resp, dict) else {}
        candles = result.get("candles", []) if isinstance(result, dict) else []
        by_date: dict[str, dict] = {}
        for candle in candles or []:
            date = str(candle.get("timestamp") or "")[:10]
            if not date or date in by_date:
                print("[시장 가드 차단] KOSDAQ 일봉 날짜가 비어 있거나 중복됐습니다.")
                return None
            by_date[date] = candle
        today_candle = by_date.get(today)
        if not isinstance(today_candle, dict):
            print("[시장 가드 차단] Toss KOSDAQ 당일 일봉이 아직 생성되지 않았습니다.")
            return None
        open_price = parse_positive_float(today_candle.get("openPrice"))
        candle_close = parse_positive_float(today_candle.get("closePrice"))
        candle_timestamp = str(today_candle.get("timestamp") or "").strip()
        if not indicator_timestamp:
            if candle_close is None or not candle_timestamp:
                print(
                    "[시장 가드 차단] Toss KOSDAQ 현재가 시각이 없고 "
                    "당일 일봉 종가로도 최신성을 교차검증할 수 없습니다."
                )
                return None
            price_gap = abs(current_index - candle_close) / max(current_index, candle_close)
            if price_gap > MARKET_PRICE_CROSSCHECK_MAX_PCT:
                print(
                    "[시장 가드 차단] Toss KOSDAQ 현재가 시각이 없고 당일 일봉 종가와 값이 다릅니다. "
                    f"(현재가 {current_index:.2f}, 일봉종가 {candle_close:.2f}, 차이 {price_gap * 100:.3f}%)"
                )
                return None
            current_index = max(current_index, candle_close)
            indicator_timestamp = candle_timestamp
            freshness_source = "today_candle_close_crosscheck"
            print(
                "[시장 가드 최신성 대체] 현재가 timestamp 누락을 "
                "당일 일봉 존재와 종가 일치로 교차검증했습니다."
            )
        previous_dates = sorted(date for date in by_date if date < today)
        if open_price is None or len(previous_dates) < 4 or previous_dates[-1] != previous_business_day:
            print("[시장 가드 차단] KOSDAQ 당일 시가 또는 직전 4영업일 종가를 검증할 수 없습니다.")
            return None
        previous_closes = [parse_positive_float(by_date[date].get("closePrice")) for date in previous_dates[-4:]]
        if any(value is None for value in previous_closes):
            print("[시장 가드 차단] KOSDAQ 직전 4영업일 종가에 결측치가 있습니다.")
            return None
        sma5 = (current_index + sum(float(value) for value in previous_closes)) / 5.0
        return MarketGateSnapshot(
            current_index=current_index,
            open_price=open_price,
            sma5=sma5,
            buy_line=sma5 * KOSDAQ_SMA5_BUY_RATIO,
            timestamp=indicator_timestamp,
            previous_business_day=previous_business_day,
            freshness_source=freshness_source,
        )
    except Exception as e:
        print(f"[시장 가드 차단] Toss KOSDAQ/장운영 데이터 조회 실패: {type(e).__name__}: {e}")
        return None


def evaluate_market_gate(snapshot: MarketGateSnapshot | None) -> bool:
    if snapshot is None:
        return False

    print(
        f"현재 KOSDAQ 지수: {snapshot.current_index:.2f} | 당일 시가: {snapshot.open_price:.2f} | "
        f"5일 이평선: {snapshot.sma5:.2f} | 매수 허용선: {snapshot.buy_line:.2f} | "
        f"지수 시각: {snapshot.timestamp} | 최신성 검증: {snapshot.freshness_source}"
    )
    if snapshot.current_index > snapshot.buy_line:
        print("🚨 [시장 가드 발동] KOSDAQ이 5일선보다 1% 이상 아래가 아니므로 오늘 매매는 정지합니다.")
        return False

    print("✅ 지수 가드 통과: KOSDAQ이 5일선보다 1% 이상 아래인 눌림 국면입니다.")
    return True


def check_market_gate(client: TossInvestClient, *, now: datetime | None = None) -> bool:
    return evaluate_market_gate(fetch_kosdaq_market_data(client, now=now))


def get_base_stocks_from_db(*, expected_date: str | None = None):
    """로컬 15년 DB에서 어제 종가/전일거래량/20일평균거래량 로드"""
    if not Path(DB_PATH).exists():
        print(f"[오류] 데이터베이스 파일이 존재하지 않습니다: {DB_PATH}")
        sys.exit(1)

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # 1. 가장 최근 영업일 날짜 구하기
    cur.execute("SELECT max(substring(timestamp, 1, 10)) FROM candle_cache")
    latest_date = cur.fetchone()[0]
    print(f"최근 데이터 영업일: {latest_date}")
    if not latest_date:
        conn.close()
        print("[오류] 캔들 DB에 기준일 데이터가 없어 매수를 차단합니다.")
        return []
    if expected_date is not None and latest_date != expected_date:
        conn.close()
        print(
            f"[오류] 캔들 DB 기준일 불일치로 매수를 차단합니다. "
            f"(필요 {expected_date}, 실제 {latest_date})"
        )
        return []

    cur.execute("""
        SELECT symbol, close_price, volume
        FROM candle_cache
        WHERE substring(timestamp, 1, 10) = ?
        AND cast(close_price as integer) >= ?
        AND cast(close_price as integer) <= ?
    """, (latest_date, MIN_PRICE, MAX_PRICE))

    candidates = []
    rows = cur.fetchall()

    for symbol, close_price, prev_volume in rows:
        # 3. 20일 평균 거래량: latest_date 이전 20일 기준
        #    (날짜 상한선으로 DB에 당일 데이터가 들어와도 항상 정확한 직전 20일만 조회)
        cur.execute("""
            SELECT volume FROM candle_cache
            WHERE symbol = ? AND substring(timestamp, 1, 10) < ?
            ORDER BY timestamp DESC LIMIT 20
        """, (symbol, latest_date))
        vols = [int(v[0]) for v in cur.fetchall()]
        if len(vols) >= 20:
            avg_vol = sum(vols) / 20.0
            candidates.append({
                'symbol': symbol,
                'prev_close': float(close_price),
                'prev_vol': int(prev_volume),  # 전일 확정 하루 거래량
                'avg_vol': avg_vol             # 전일 제외 직전 20일 평균 거래량
            })

    conn.close()
    print(f"로컬 스크리닝 필터 통과 종목 수: {len(candidates)}개 ({MIN_PRICE:,}원~{MAX_PRICE:,}원)")
    return candidates


def get_breadth_reference_prices_from_db(*, expected_date: str) -> dict[str, float]:
    """Load the broad 500-30,000 won reference universe for paper-only logging."""
    connection = sqlite3.connect(DB_PATH)
    try:
        rows = connection.execute(
            """
            WITH ordered AS (
              SELECT
                symbol,
                substring(timestamp,1,10) AS date,
                CAST(close_price AS REAL) AS close_price,
                AVG(CAST(volume AS REAL)) OVER (
                  PARTITION BY symbol ORDER BY timestamp
                  ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING
                ) AS avg_prior20_volume,
                AVG(
                  (CAST(high_price AS REAL)-CAST(low_price AS REAL)) /
                  NULLIF(CAST(close_price AS REAL),0)
                ) OVER (
                  PARTITION BY symbol ORDER BY timestamp
                  ROWS BETWEEN 19 PRECEDING AND CURRENT ROW
                ) AS avg_range20,
                COUNT(*) OVER (
                  PARTITION BY symbol ORDER BY timestamp
                  ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING
                ) AS prior_count
              FROM candle_cache
              WHERE interval='1d'
            )
            SELECT symbol, close_price
            FROM ordered
            WHERE date=? AND prior_count=20
              AND close_price BETWEEN ? AND ?
              AND avg_prior20_volume > 0
              AND avg_range20 > 0
            """,
            (
                expected_date,
                breadth_shadow.MIN_REFERENCE_PRICE,
                breadth_shadow.MAX_REFERENCE_PRICE,
            ),
        ).fetchall()
    finally:
        connection.close()
    return {
        str(symbol): float(close_price)
        for symbol, close_price in rows
        if symbol and float(close_price or 0) > 0
    }


def record_breadth_shadow_skipped(trade_date: str, reason: str) -> None:
    """Best-effort paper log. A logging failure must never alter live trading."""
    try:
        breadth_shadow.append_event(
            BREADTH_SHADOW_LOG,
            {
                "event": "breadth_shadow_open_snapshot",
                "phase": "09:01",
                "date": trade_date,
                "rule": breadth_shadow.SHADOW_RULE,
                "threshold": breadth_shadow.SHADOW_THRESHOLD,
                "status": "not_evaluated",
                "reason": reason,
                "applied_to_live_order": False,
            },
        )
        print(f"[섀도 breadth4] 미실행: {reason} / 실매매 미적용")
    except Exception as error:
        print(f"[섀도 breadth4 경고] 미실행 기록 실패: {type(error).__name__}: {error}")


def collect_breadth_shadow_snapshot(
    client: TossInvestClient,
    *,
    trade_date: str,
    previous_business_day: str,
    base_symbols: set[str],
    base_quote_rows: list[dict],
) -> dict | None:
    """Collect a current-price proxy without changing any buy decision."""
    try:
        reference_prices = get_breadth_reference_prices_from_db(
            expected_date=previous_business_day
        )
        quote_rows = list(base_quote_rows)
        extra_symbols = sorted(set(reference_prices) - base_symbols)
        failed_chunks = 0
        for offset in range(0, len(extra_symbols), 100):
            chunk = extra_symbols[offset : offset + 100]
            try:
                response = client.get_prices(chunk)
                quote_rows.extend(response.get("result", []) or [])
            except Exception as error:
                failed_chunks += 1
                print(
                    f"[섀도 breadth4 경고] 추가 시세 청크 실패 "
                    f"(첫종목 {chunk[0]}): {type(error).__name__}: {error}"
                )
            time.sleep(0.1)
        gap_count, quoted = breadth_shadow.provisional_gap_count(
            reference_prices, quote_rows
        )
        coverage = quoted / len(reference_prices) if reference_prices else 0.0
        status = "pass" if gap_count >= breadth_shadow.SHADOW_THRESHOLD else "below_threshold"
        event = {
            "event": "breadth_shadow_open_snapshot",
            "phase": "09:01",
            "date": trade_date,
            "reference_date": previous_business_day,
            "rule": breadth_shadow.SHADOW_RULE,
            "threshold": breadth_shadow.SHADOW_THRESHOLD,
            "status": status,
            "provisional_gap5_count": gap_count,
            "reference_symbols": len(reference_prices),
            "quoted_symbols": quoted,
            "quote_coverage": coverage,
            "failed_chunks": failed_chunks,
            "definition": "09:01 current-price proxy; official open reconciled after close",
            "applied_to_live_order": False,
        }
        breadth_shadow.append_event(BREADTH_SHADOW_LOG, event)
        print(
            f"[섀도 breadth4] 09:01 현재가 기준 -5% 갭: {gap_count}개 / "
            f"기준: {breadth_shadow.SHADOW_THRESHOLD}개 / 모집단: {len(reference_prices)}개 / "
            f"시세수신: {quoted}개 / 상태: {status} / 실매매 미적용"
        )
        return event
    except Exception as error:
        print(f"[섀도 breadth4 경고] 수집 실패, 실매매는 계속: {type(error).__name__}: {error}")
        return None


def get_actual_budget(client: TossInvestClient, settings: Settings) -> float:
    """실제 예수금을 API로 조회하여 실제 사용 가능 금액 반환.

    기본은 10,000원 상한이며 TOSS_MAX_BUY_AMOUNT_KRW로 조정할 수 있다.
    """
    try:
        resp = client.get_buying_power(settings.account_seq)
        # Toss API 응답은 환경/버전에 따라 cashBuyingPower 또는 amount를 줄 수 있다.
        res_data = resp.get("result", {})
        amount_str = res_data.get("cashBuyingPower") or res_data.get("amount") or "0"
        actual = float(str(amount_str).replace(",", ""))
        cap = configured_max_buy_amount_krw()
        budget = actual if cap is None else min(actual, cap)
        cap_label = "계좌 매수가능금액 전체" if cap is None else f"상한 {cap:,.0f}원"
        print(f"실제 예수금: {actual:,.0f}원 | 이번 매수 사용 예산: {budget:,.0f}원 ({cap_label})")
        return budget
    except Exception as e:
        print(f"[오류] 예수금 조회 실패, 매수 안전 중단(예산 0원 처리): {e}")
        return 0.0


def get_today_open_price(client: TossInvestClient, symbol: str, *, today: str | None = None) -> float | None:
    """Return today's official daily-candle open price.

    Toss /prices does not reliably include openPrice. Do not fall back to lastPrice,
    because that breaks the backtest entry assumption.
    """
    target_date = today or datetime.now().strftime("%Y-%m-%d")
    resp = client.get_candles(symbol, "1d", count=3)
    result = resp.get("result", {}) if isinstance(resp, dict) else {}
    candles = result.get("candles", []) if isinstance(result, dict) else []
    for candle in candles or []:
        if str(candle.get("timestamp", ""))[:10] != target_date:
            continue
        raw = candle.get("openPrice") or candle.get("open_price")
        try:
            open_price = float(str(raw).replace(",", ""))
        except Exception:
            return None
        return open_price if open_price > 0 else None
    return None


def load_strategy_state() -> dict | None:
    return simple_gap_state.load_state(STRATEGY_STATE_PATH, strategy_name=STRATEGY_NAME)


def save_strategy_state(state: dict, *, event: str | None = None) -> None:
    simple_gap_state.save_state(STRATEGY_STATE_PATH, state)
    if event:
        simple_gap_state.append_event(
            STRATEGY_STATE_PATH.with_name(STRATEGY_EVENT_LOG.name),
            {
                "timestamp": datetime.now().astimezone().isoformat(),
                "event": event,
                "strategy_name": STRATEGY_NAME,
                "trade_date": state.get("trade_date"),
                "symbol": state.get("symbol"),
                "status": state.get("status"),
                "state": state,
            },
        )


def reconcile_strategy_state(
    client: TossInvestClient,
    settings: Settings,
    state: dict,
    *,
    now: datetime | None = None,
) -> tuple[dict, bool]:
    checked_at = _aware_now(now)
    updated = state
    safe = True
    changed = False

    buy = updated.get("buy", {})
    buy_status = str(buy.get("status") or "").upper()
    buy_order_id = normalize_order_id(buy.get("order_id"))
    if not buy_order_id and buy_status in {"SUBMITTING", "UNTRACKED"}:
        payload = _buy_order_payload_from_state(updated)
        submitted_at = buy.get("submitted_at") or state.get("updated_at")
        can_replay = bool(getattr(settings, "live_trading", False) and not getattr(settings, "dry_run", True))
        if can_replay and payload and _within_idempotency_window(submitted_at, now=checked_at):
            try:
                _, recovered_order_id = submit_order_with_idempotent_replay(client, settings, payload)
                if not recovered_order_id:
                    raise AmbiguousOrderSubmission("buy replay returned no orderId")
                updated = simple_gap_state.apply_buy_submission(
                    updated,
                    order_id=recovered_order_id,
                    now=checked_at,
                )
                changed = True
                print(f"  ♻️ [{state.get('symbol')}] 동일 clientOrderId 재전송으로 매수 주문ID 복구: {recovered_order_id}")
            except Exception as exc:
                if submission_error_is_ambiguous(exc):
                    print(f"  ⚠️ [{state.get('symbol')}] 매수 주문 응답이 여전히 불명확합니다: {exc}")
                else:
                    updated = simple_gap_state.mark_buy_submission_status(updated, status="REJECTED", now=checked_at)
                    changed = True
                    print(f"  ❌ [{state.get('symbol')}] 매수 주문 확정 거절: {exc}")
                safe = False
        else:
            if buy_status != "UNTRACKED":
                updated = simple_gap_state.mark_buy_submission_status(updated, status="UNTRACKED", now=checked_at)
                changed = True
            print(
                f"  ⚠️ [{state.get('symbol')}] 매수 주문ID를 멱등성 유효시간 안에 복구할 수 없어 "
                "수동 확인 전 추가 주문을 차단합니다."
            )
            safe = False

    buy = updated.get("buy", {})
    buy_status = str(buy.get("status") or "").upper()
    buy_order_id = normalize_order_id(buy.get("order_id"))
    if buy_order_id and buy_status in simple_gap_state.ACTIVE_ORDER_STATUSES | {"SUBMITTED"}:
        try:
            snapshot = simple_gap_state.order_snapshot(client.get_order(buy_order_id, settings.account_seq))
            updated = simple_gap_state.apply_buy_snapshot(updated, snapshot, now=checked_at)
            changed = True
        except Exception as e:
            print(f"  ⚠️ [{state.get('symbol')}] 매수 주문 체결 조회 실패: {e}")
            safe = False

    for sell_order in list(simple_gap_state.active_sell_orders(updated)):
        status = str(sell_order.get("status") or "").upper()
        order_id = normalize_order_id(sell_order.get("order_id"))
        if order_id:
            continue
        if status not in {"SUBMITTING", "UNTRACKED"}:
            print(f"  ⚠️ [{state.get('symbol')}] 추적 중인 매도 주문ID가 없어 체결 판단을 중단합니다.")
            safe = False
            continue

        payload = _sell_order_payload_from_state(updated, sell_order)
        submitted_at = sell_order.get("submitted_at") or state.get("updated_at")
        can_replay = bool(getattr(settings, "live_trading", False) and not getattr(settings, "dry_run", True))
        client_order_id = str(sell_order.get("client_order_id") or "")
        if can_replay and payload and _within_idempotency_window(submitted_at, now=checked_at):
            try:
                _, recovered_order_id = submit_order_with_idempotent_replay(client, settings, payload)
                if not recovered_order_id:
                    raise AmbiguousOrderSubmission("sell replay returned no orderId")
                updated = simple_gap_state.apply_sell_submission(
                    updated,
                    client_order_id=client_order_id,
                    order_id=recovered_order_id,
                    now=checked_at,
                )
                changed = True
                print(f"  ♻️ [{state.get('symbol')}] 동일 clientOrderId 재전송으로 매도 주문ID 복구: {recovered_order_id}")
            except Exception as exc:
                if submission_error_is_ambiguous(exc):
                    print(f"  ⚠️ [{state.get('symbol')}] 매도 주문 응답이 여전히 불명확합니다: {exc}")
                else:
                    updated = simple_gap_state.mark_sell_submission_status(
                        updated,
                        client_order_id=client_order_id,
                        status="REJECTED",
                        now=checked_at,
                    )
                    changed = True
                    print(f"  ❌ [{state.get('symbol')}] 매도 주문 확정 거절: {exc}")
                safe = False
        else:
            if status != "UNTRACKED":
                updated = simple_gap_state.mark_sell_submission_status(
                    updated,
                    client_order_id=client_order_id,
                    status="UNTRACKED",
                    now=checked_at,
                )
                changed = True
            print(
                f"  ⚠️ [{state.get('symbol')}] 매도 주문ID를 멱등성 유효시간 안에 복구할 수 없어 "
                "수동 확인 전 추가 매도를 차단합니다."
            )
            safe = False

    for sell_order in list(simple_gap_state.active_sell_orders(updated)):
        order_id = normalize_order_id(sell_order.get("order_id"))
        if not order_id:
            safe = False
            continue
        try:
            snapshot = simple_gap_state.order_snapshot(client.get_order(order_id, settings.account_seq))
            updated = simple_gap_state.apply_sell_snapshot(updated, snapshot, now=checked_at)
            changed = True
        except Exception as e:
            print(f"  ⚠️ [{state.get('symbol')}] 매도 주문 {order_id} 체결 조회 실패: {e}")
            safe = False

    if changed:
        save_strategy_state(updated, event="order_reconciled")
    return updated, safe


def cancel_stale_buy_order(
    client: TossInvestClient,
    settings: Settings,
    state: dict,
    *,
    now: datetime | None = None,
) -> bool:
    buy = state.get("buy", {})
    status = str(buy.get("status") or "").upper()
    order_id = normalize_order_id(buy.get("order_id"))
    if status not in simple_gap_state.ACTIVE_ORDER_STATUSES or not order_id:
        return False
    if buy.get("cancel_requested_at"):
        print(f"  ⏳ [{state.get('symbol')}] 매수 미체결분 취소 처리 대기 중입니다.")
        return True
    raw_time = buy.get("ordered_at") or state.get("updated_at")
    try:
        submitted_at = datetime.fromisoformat(str(raw_time).replace("Z", "+00:00"))
        age = (_aware_now(now).astimezone(submitted_at.tzinfo) - submitted_at).total_seconds()
    except (TypeError, ValueError):
        age = BUY_ORDER_MAX_WAIT_SECONDS
    if age < BUY_ORDER_MAX_WAIT_SECONDS:
        print(f"  ⏳ [{state.get('symbol')}] 매수 주문 체결 대기 중입니다. ({age:.0f}s)")
        return True
    try:
        response = client.cancel_order(settings.account_seq, order_id)
    except Exception as e:
        print(f"  ❌ [{state.get('symbol')}] {BUY_ORDER_MAX_WAIT_SECONDS}초 초과 매수 주문 취소 실패: {e}")
        return True
    if response.get("dryRun"):
        print(f"  * [모의 실행] 매수 미체결분 취소 대상: {order_id}")
        return True
    state["buy"]["cancel_requested_at"] = _aware_now(now).isoformat()
    state["updated_at"] = _aware_now(now).isoformat()
    save_strategy_state(state, event="buy_cancel_requested")
    print(f"  🛑 [{state.get('symbol')}] {BUY_ORDER_MAX_WAIT_SECONDS}초 초과 매수 미체결분 취소 요청 완료")
    return True


def tracked_holding(holdings: list[dict], state: dict) -> dict | None:
    symbol = str(state.get("symbol") or "")
    matches = [holding for holding in holdings if str(holding.get("symbol") or "") == symbol]
    return matches[0] if len(matches) == 1 else None


def finalize_filled_exit(state: dict, *, now: datetime | None = None) -> dict:
    if state.get("status") != "CLOSED" or state.get("exit_recorded"):
        return state
    sell_orders = [order for order in state.get("sell_orders", []) if int(order.get("filled_quantity") or 0) > 0]
    if not sell_orders:
        return state
    filled_qty = sum(int(order.get("filled_quantity") or 0) for order in sell_orders)
    filled_amounts = [float(order.get("filled_amount") or 0) for order in sell_orders]
    if sum(filled_amounts) > 0:
        fill_price = sum(filled_amounts) / filled_qty
        filled_amount = sum(filled_amounts)
    else:
        fill_price = sum(
            int(order.get("filled_quantity") or 0) * float(order.get("average_filled_price") or 0)
            for order in sell_orders
        ) / filled_qty
        filled_amount = fill_price * filled_qty
    trigger_order = next((order for order in sell_orders if order.get("trigger") in {"손절", "익절"}), sell_orders[-1])
    trigger = str(trigger_order.get("trigger") or "청산")
    entry = float(state.get("position", {}).get("entry_price") or state.get("buy", {}).get("limit_price") or 0)
    if entry <= 0 or fill_price <= 0:
        print(f"  ⚠️ [{state.get('symbol')}] 실제 체결가는 확인됐지만 진입가를 확인할 수 없어 종료 기록을 보류합니다.")
        return state
    observed_price = float(trigger_order.get("observed_price") or fill_price)
    trigger_price = float(trigger_order.get("trigger_price") or fill_price)
    occurred_at = _aware_now(now)
    return_pct = (fill_price - entry) / entry * 100.0
    alert = MonitorExitAlert(
        strategy_name=STRATEGY_NAME,
        trigger=trigger,
        symbol=str(state.get("symbol")),
        name=str(state.get("name") or state.get("symbol")),
        qty=filled_qty,
        entry_price=entry,
        last_price=observed_price,
        trigger_price=trigger_price,
        limit_price=int(round(fill_price)),
        expected_amount=filled_amount,
        return_pct=return_pct,
        order_id=normalize_order_id(trigger_order.get("order_id")),
        occurred_at=occurred_at,
    )
    notify_monitor_exit(alert)
    if trigger == "손절":
        paper_reentry_watch.record_stop_exit(
            PAPER_REENTRY_LOG,
            symbol=str(state.get("symbol")),
            name=str(state.get("name") or state.get("symbol")),
            qty=filled_qty,
            entry_price=entry,
            stop_price=trigger_price,
            observed_price=observed_price,
            exit_limit_price=fill_price,
            order_id=alert.order_id,
            now=occurred_at,
        )
    elif trigger == "익절":
        paper_reentry_watch.record_take_profit_exit(
            PAPER_REENTRY_LOG,
            symbol=str(state.get("symbol")),
            name=str(state.get("name") or state.get("symbol")),
            qty=filled_qty,
            entry_price=entry,
            take_price=trigger_price,
            observed_price=observed_price,
            exit_limit_price=fill_price,
            order_id=alert.order_id,
            now=occurred_at,
        )
    state["exit_recorded"] = True
    state["exit"] = {
        "trigger": trigger,
        "filled_quantity": filled_qty,
        "average_filled_price": fill_price,
        "filled_amount": filled_amount,
        "return_pct": return_pct,
        "recorded_at": occurred_at.isoformat(),
    }
    state["updated_at"] = occurred_at.isoformat()
    save_strategy_state(state, event="exit_filled")
    print(
        f"  ✅ [{state.get('symbol')}] {trigger} 실제 체결 확인: "
        f"{filled_qty}주 @ {fill_price:,.0f}원 / 수익률 {return_pct:+.2f}%"
    )
    return state


def submit_strategy_market_sell(
    client: TossInvestClient,
    settings: Settings,
    state: dict,
    *,
    quantity: int,
    trigger: str,
    observed_price: float,
    trigger_price: float | None,
    now: datetime | None = None,
) -> dict:
    submitted_at = _aware_now(now)
    symbol = str(state.get("symbol") or "")
    name = str(state.get("name") or symbol)
    payload = build_market_quantity_order(symbol, "SELL", quantity, now=submitted_at)
    client_order_id = str(payload["clientOrderId"])
    live_submission = bool(getattr(settings, "live_trading", False) and not getattr(settings, "dry_run", True))
    original_state = state
    if live_submission:
        state = simple_gap_state.add_sell_order(
            state,
            order_id=None,
            client_order_id=client_order_id,
            trigger=trigger,
            requested_quantity=quantity,
            observed_price=observed_price,
            trigger_price=trigger_price,
            now=submitted_at,
            order_payload=payload,
        )
        save_strategy_state(state, event="sell_submitting")
    print(f"  🚨 [{name}] {quantity}주 {trigger} 시장가 매도 주문 발송...")
    try:
        response, order_id = submit_order_with_idempotent_replay(client, settings, payload)
    except Exception as e:
        if live_submission:
            if submission_error_is_ambiguous(e):
                save_strategy_state(state, event="sell_submit_ambiguous")
            else:
                state = simple_gap_state.mark_sell_submission_status(
                    state,
                    client_order_id=client_order_id,
                    status="REJECTED",
                    now=submitted_at,
                )
                save_strategy_state(state, event="sell_submit_rejected")
        print(f"  ❌ [{symbol}] {trigger} 시장가 매도 주문 실패: {e}")
        return state
    if response.get("dryRun"):
        print(f"  * [모의 실행] {trigger} 시장가 매도 주문 가상 응답: {response['wouldSend']}")
        return original_state
    if not order_id:
        raise AssertionError("live order response must include orderId after idempotent replay")
    if live_submission:
        state = simple_gap_state.apply_sell_submission(
            state,
            client_order_id=client_order_id,
            order_id=order_id,
            now=submitted_at,
        )
    else:
        state = simple_gap_state.add_sell_order(
            state,
            order_id=order_id,
            client_order_id=client_order_id,
            trigger=trigger,
            requested_quantity=quantity,
            observed_price=observed_price,
            trigger_price=trigger_price,
            now=submitted_at,
            order_payload=payload,
        )
    save_strategy_state(state, event="sell_submitted")
    print(f"  * [실전 주문] {trigger} 시장가 매도 주문 접수! 주문ID: {order_id}")
    try:
        snapshot = simple_gap_state.order_snapshot(client.get_order(order_id, settings.account_seq))
        state = simple_gap_state.apply_sell_snapshot(state, snapshot, now=submitted_at)
        save_strategy_state(state, event="sell_immediate_reconcile")
    except Exception as e:
        print(f"  ⚠️ [{symbol}] 매도 주문 즉시 체결 조회 실패, 다음 모니터에서 재확인: {e}")
        return state
    return finalize_filled_exit(state, now=submitted_at)


def run_buy(
    client: TossInvestClient,
    settings: Settings,
    force: bool = False,
    *,
    now: datetime | None = None,
):
    """오전 9시 갭하락 종목 매수 로직"""
    entry_now = _aware_now(now).astimezone(KST)
    live_submission = bool(getattr(settings, "live_trading", False) and not getattr(settings, "dry_run", True))
    if not live_buy_window_allows(settings, entry_now):
        print(
            f"[안전 중단] 실전 매수 허용 시간은 09:00 이상 09:05 미만입니다. "
            f"현재 {entry_now.strftime('%H:%M:%S')}"
        )
        return
    trade_date = entry_now.date().isoformat()
    try:
        existing_state = load_strategy_state()
    except simple_gap_state.StrategyStateError as e:
        print(f"[안전 중단] 전략 원장을 읽을 수 없어 신규 매수를 차단합니다: {e}")
        return
    if not simple_gap_state.state_allows_new_buy(existing_state, trade_date=trade_date):
        print(
            f"[안전 중단] 오늘 이미 진입했거나 이전 전략 주문/포지션이 아직 종료되지 않았습니다. "
            f"(거래일 {existing_state.get('trade_date')}, 상태 {existing_state.get('status')}, "
            f"종목 {existing_state.get('symbol')})"
        )
        return
    if force and live_submission:
        print("[안전 중단] --force는 실전 매매에서 사용할 수 없습니다.")
        return

    market_snapshot = fetch_kosdaq_market_data(client, now=entry_now)
    if market_snapshot is None:
        return
    if force:
        print("⚠️ [모의 디버그 옵션] 시장 비율 조건만 무시합니다. 날짜·최신성 검증은 유지합니다.")
        evaluate_market_gate(market_snapshot)
    elif not evaluate_market_gate(market_snapshot):
        record_breadth_shadow_skipped(trade_date, "시장 가드 차단")
        return

    base_stocks = get_base_stocks_from_db(expected_date=market_snapshot.previous_business_day)
    if not base_stocks:
        record_breadth_shadow_skipped(trade_date, "기준 종목 스크리닝 미실행")
        print(f"스크리닝 조건({MIN_PRICE:,}원~{MAX_PRICE:,}원)을 통과한 종목이 없습니다.")
        return

    # 실제 예수금 조회 (안전 상한 MAX_BUY_AMOUNT_KRW와 비교)
    remaining_budget = get_actual_budget(client, settings)
    if remaining_budget < MIN_PRICE:
        record_breadth_shadow_skipped(trade_date, "예수금 부족")
        print(f"[중단] 예수금({remaining_budget:,.0f}원)이 최소 주가({MIN_PRICE:,}원)보다 적어 매수 불가합니다.")
        return

    # 100개씩 나눠서 실시간 시세 조회
    chunk_size = 100
    base_map = {s['symbol']: s for s in base_stocks}
    symbols = list(base_map.keys())
    chunks = [symbols[i:i + chunk_size] for i in range(0, len(symbols), chunk_size)]

    triggered = []
    base_quote_rows = []
    perf = {
        'price_chunks': 0,
        'price_rows': 0,
        'provisional_gap_hits': 0,
        'daily_open_calls': 0,
        'daily_open_missing': 0,
        'daily_open_confirmed_hits': 0,
    }
    scan_started = time.perf_counter()
    print("실시간 현재가 수집 및 갭 하락 검사 시작...")

    for chunk in chunks:
        try:
            perf['price_chunks'] += 1
            prices_resp = client.get_prices(chunk)
            prices = prices_resp.get("result", [])
            base_quote_rows.extend(prices or [])
            perf['price_rows'] += len(prices or [])
            for p in prices:
                sym = p["symbol"]
                last_price = float(p.get("lastPrice", "0"))
                if last_price <= 0:
                    continue

                prev_close = base_map[sym]['prev_close']
                if prev_close <= 0:
                    continue

                # 거래량 필터: 전일 확정 거래량 vs 전일 제외 직전 20일 평균 (백테스트 조건과 일치)
                prev_vol_avg = base_map[sym]['avg_vol']
                if prev_vol_avg <= 0:
                    continue
                prev_vol_ratio = base_map[sym]['prev_vol'] / prev_vol_avg
                if prev_vol_ratio >= PREV_VOL_RATIO_MAX:
                    continue

                # /prices는 openPrice를 주지 않을 수 있다. lastPrice는 API 부하 절감용 provisional gate로만 쓴다.
                provisional_gap = (last_price - prev_close) / prev_close
                if provisional_gap > provisional_gap_threshold():
                    continue
                perf['provisional_gap_hits'] += 1

                # 최종 갭 계산/주문가는 당일 일봉 시가 기준 (백테스트 조건과 일치). lastPrice로 폴백 금지.
                perf['daily_open_calls'] += 1
                open_price = get_today_open_price(client, sym)
                if open_price is None:
                    perf['daily_open_missing'] += 1
                    print(f"  ⏭️ [{sym}] 당일 일봉 시가 확인 실패 → 백테스트 불일치 방지를 위해 제외")
                    continue

                gap = (open_price - prev_close) / prev_close

                if gap <= GAP_THRESHOLD:
                    perf['daily_open_confirmed_hits'] += 1
                    triggered.append({
                        'symbol': sym,
                        'name': p.get('name', sym),
                        'open_price': open_price,
                        'last_price': last_price,
                        'prev_close': prev_close,
                        'gap_pct': gap * 100.0,
                    })
        except Exception as e:
            print(f"[경고] 시세 조회 실패 청크 (첫종목: {chunk[0]}): {e}")
            continue
        time.sleep(0.5)

    scan_elapsed = time.perf_counter() - scan_started
    print(
        "성능 측정: "
        f"price_chunks={perf['price_chunks']} "
        f"price_rows={perf['price_rows']} "
        f"provisional_gap_hits={perf['provisional_gap_hits']} "
        f"daily_open_calls={perf['daily_open_calls']} "
        f"daily_open_missing={perf['daily_open_missing']} "
        f"daily_open_confirmed_hits={perf['daily_open_confirmed_hits']} "
        f"scan_elapsed={scan_elapsed:.2f}s"
    )
    print(f"갭 하락 {abs(GAP_THRESHOLD) * 100:.1f}% 돌파 종목 수: {len(triggered)}개")

    triggered.sort(key=lambda x: (x['open_price'], x['symbol']))

    if not triggered:
        collect_breadth_shadow_snapshot(
            client,
            trade_date=trade_date,
            previous_business_day=market_snapshot.previous_business_day,
            base_symbols=set(base_map),
            base_quote_rows=base_quote_rows,
        )
        print("매수 진입 조건을 통과한 최종 종목이 없습니다.")
        return

    print("\n=== 최종 진입 대기 종목 (상위 5개) ===")
    for f in triggered[:5]:
        print(f"  [{f['symbol']}] {f['name']} | 갭률: {f['gap_pct']:.2f}% | 시가: {f['open_price']:,}원 | 현재가: {f['last_price']:,}원 | 전일종가: {f['prev_close']:,}원")

    # 1종목 집중 매수: 최상위 1종목에 예산 전액 투입.
    # 단, Toss 매수 유의사항(투자경고/단기과열/VI 등)은 주문 전 fail-closed로 제외.
    orders_to_send = []
    for target in triggered:
        warnings = blocking_warnings_for_symbol(client, target['symbol'])
        if warnings:
            print(f"  ⛔ [{target['symbol']}] {target['name']} 매수 유의사항 필터 제외: {', '.join(warnings)}")
            time.sleep(0.25)
            continue
        time.sleep(0.25)

        limit_price = acceptable_buy_limit_price(client, target)
        if limit_price is None:
            continue
        if remaining_budget < limit_price:
            print(f"  ⏭️ [{target['symbol']}] {target['name']} 매수 지정가 {limit_price:,}원이 예산 {remaining_budget:,.0f}원 초과로 제외")
            continue

        qty = int(remaining_budget // limit_price)
        if qty > 0:
            cost = qty * limit_price
            remaining_budget -= cost
            target['limit_price'] = limit_price
            orders_to_send.append((target, qty, cost))
            break  # 최상위 1종목만 매수하고 종료

    print(f"\n최종 매수 대상 종목 수: {len(orders_to_send)}개 (남은 예수금: {remaining_budget:,.0f}원)")

    for target, qty, cost in orders_to_send:
        limit_price = int(target.get('limit_price') or target['last_price'])
        submitted_at = datetime.now().astimezone(KST)
        if not live_buy_window_allows(settings, submitted_at):
            print(
                f"[안전 중단] 스캔 중 09:05가 지나 실전 매수 주문을 보내지 않습니다. "
                f"현재 {submitted_at.strftime('%H:%M:%S')}"
            )
            record_breadth_shadow_skipped(trade_date, "09:05 주문 마감 우선")
            return
        payload = build_limit_quantity_order(target['symbol'], "BUY", qty, limit_price, now=submitted_at)
        state = None
        if settings.live_trading and not settings.dry_run:
            state = simple_gap_state.new_buy_state(
                strategy_name=STRATEGY_NAME,
                trade_date=submitted_at.date().isoformat(),
                symbol=target["symbol"],
                name=target["name"],
                client_order_id=str(payload["clientOrderId"]),
                requested_quantity=qty,
                limit_price=limit_price,
                now=submitted_at,
                order_payload=payload,
            )
            save_strategy_state(state, event="buy_submitting")
        try:
            print(
                f"  🚀 [{target['name']}] {qty}주 지정가 매수 주문 발송 "
                f"(전략 {STRATEGY_NAME}, 배정금액 {cost:,.0f}원, 지정가 {limit_price:,}원, "
                f"손절가 {stop_price(limit_price):,.0f}원, 익절가 {take_price(limit_price):,.0f}원)..."
            )
            res, order_id = submit_order_with_idempotent_replay(client, settings, payload)
            if res.get('dryRun'):
                print(f"  * [모의 실행] 주문 발송 가상 응답: {res['wouldSend']}")
            else:
                assert state is not None
                if not order_id:
                    raise AssertionError("live order response must include orderId after idempotent replay")
                state = simple_gap_state.apply_buy_submission(
                    state,
                    order_id=order_id,
                    now=datetime.now().astimezone(),
                )
                save_strategy_state(state, event="buy_submitted")
                print(f"  * [실전 주문] 매수 주문 접수! 주문ID: {order_id}")
                try:
                    snapshot = simple_gap_state.order_snapshot(client.get_order(order_id, settings.account_seq))
                    state = simple_gap_state.apply_buy_snapshot(state, snapshot, now=datetime.now().astimezone())
                    save_strategy_state(state, event="buy_immediate_reconcile")
                    print(
                        f"  * [체결 상태] {snapshot.status} / "
                        f"{snapshot.filled_quantity}주 @ {snapshot.average_filled_price or 0:,.0f}원"
                    )
                except Exception as e:
                    print(f"  ⚠️ 매수 주문 즉시 체결 조회 실패, 다음 모니터에서 재확인: {e}")
        except Exception as e:
            if state is not None:
                if submission_error_is_ambiguous(e):
                    save_strategy_state(state, event="buy_submit_ambiguous")
                    print(f"  ❌ [{target['name']}] 매수 주문 응답 불명확, 동일 멱등키 복구 대기: {e}")
                else:
                    state = simple_gap_state.mark_buy_submission_status(
                        state,
                        status="REJECTED",
                        now=datetime.now().astimezone(),
                    )
                    save_strategy_state(state, event="buy_submit_rejected")
                    print(f"  ❌ [{target['name']}] 매수 주문 확정 거절: {e}")
            else:
                print(f"  ❌ [{target['name']}] 주문 전 시스템 에러: {e}")

    # Research-only API calls always run after the live order path.
    collect_breadth_shadow_snapshot(
        client,
        trade_date=trade_date,
        previous_business_day=market_snapshot.previous_business_day,
        base_symbols=set(base_map),
        base_quote_rows=base_quote_rows,
    )


def get_active_holdings(client: TossInvestClient, settings: Settings) -> list[dict]:
    holdings_resp = client.get_holdings(settings.account_seq)
    result = holdings_resp.get("result", {}) if isinstance(holdings_resp, dict) else {}
    holdings = []
    if isinstance(result, dict):
        holdings = result.get("holdings") or result.get("items") or []
    return [h for h in holdings if holding_quantity(h) > 0]


def current_price_map(client: TossInvestClient, symbols: list[str]) -> dict[str, float]:
    prices_resp = client.get_prices(symbols)
    prices: dict[str, float] = {}
    for row in prices_resp.get("result", []) or []:
        symbol = str(row.get("symbol") or "")
        price = parse_positive_float(row.get("lastPrice"))
        if symbol and price is not None:
            prices[symbol] = price
    return prices


def update_paper_reentry_watch(client: TossInvestClient, *, now: datetime | None = None) -> None:
    checked_at = now or datetime.now()
    symbols = paper_reentry_watch.active_symbols(PAPER_REENTRY_LOG, checked_at)
    if not symbols:
        return
    try:
        prices = current_price_map(client, symbols)
        events = paper_reentry_watch.update_watch(PAPER_REENTRY_LOG, prices, checked_at)
    except (TossApiError, OSError, TypeError, ValueError, KeyError, AttributeError) as e:
        print(f"[경고] 매도 후 paper-only 관찰 현재가 조회 실패: {e}")
        return
    for event in events:
        message = format_paper_event(event)
        if message:
            print(message)


def notify_monitor_exit(alert: MonitorExitAlert) -> None:
    try:
        sent = send_discord_message(format_monitor_exit_alert(alert))
    except (OSError, subprocess.SubprocessError) as e:
        print(f"  ⚠️ Discord 장중 {alert.trigger} 알림 실패: {e}")
        return
    if sent:
        print(f"  📣 Discord 장중 {alert.trigger} 알림 전송 완료")
    else:
        print(f"  ⚠️ Discord 장중 {alert.trigger} 알림 건너뜀: TOSS_MONITOR_DISCORD_TARGET 또는 TOSS_DISCORD_TARGET 미설정")


def run_monitor(client: TossInvestClient, settings: Settings):
    print(
        f"전략: {STRATEGY_NAME} | 손절 {STOP_LOSS_PCT * 100:.2f}% | 익절 {TAKE_PROFIT_PCT * 100:.2f}%"
    )
    update_paper_reentry_watch(client)
    try:
        state = load_strategy_state()
    except simple_gap_state.StrategyStateError as e:
        print(f"[안전 중단] 전략 원장이 손상되어 계좌 보유분을 건드리지 않습니다: {e}")
        return
    if state is None:
        print("추적 중인 전략 주문/포지션이 없습니다. 계좌의 다른 보유 종목은 건드리지 않습니다.")
        return
    state, reconcile_safe = reconcile_strategy_state(client, settings, state)
    state = finalize_filled_exit(state)
    if state.get("status") in simple_gap_state.TERMINAL_STATE_STATUSES:
        print(f"전략 포지션이 종료 상태입니다. ({state.get('status')})")
        return
    if state.get("status") in {"BUY_UNTRACKED", "BUY_SUBMIT_FAILED", "EXIT_UNTRACKED"}:
        print(f"[안전 중단] 주문 추적 상태가 {state.get('status')}여서 추가 주문을 차단합니다.")
        return
    if not reconcile_safe:
        print("[안전 중단] 주문 체결 상태를 확인하지 못해 중복 주문을 차단합니다.")
        return
    if cancel_stale_buy_order(client, settings, state):
        return
    if simple_gap_state.active_sell_orders(state):
        print(f"  ⏳ [{state.get('symbol')}] 기존 매도 주문 체결을 기다립니다. 추가 매도는 보내지 않습니다.")
        return
    if state.get("status") != "POSITION_OPEN":
        print(f"전략 포지션이 아직 모니터링 가능한 상태가 아닙니다. ({state.get('status')})")
        return

    try:
        holdings = get_active_holdings(client, settings)
    except Exception as e:
        print(f"[오류] 잔고 조회 실패: {e}")
        return
    holding = tracked_holding(holdings, state)
    ignored = [h for h in holdings if str(h.get("symbol") or "") != str(state.get("symbol") or "")]
    if ignored:
        print(f"계좌의 비전략 보유 종목 {len(ignored)}개는 모니터링·매도 대상에서 제외합니다.")
    if holding is None:
        print(f"[안전 중단] 전략 원장에는 {state.get('symbol')} 포지션이 있지만 계좌 보유분을 확인할 수 없습니다.")
        return
    owned_qty = int(state.get("position", {}).get("remaining_quantity") or 0)
    account_qty = holding_quantity(holding)
    qty = min(owned_qty, account_qty)
    entry = parse_positive_float(state.get("position", {}).get("entry_price"))
    symbol = str(state.get("symbol"))
    name = str(state.get("name") or symbol)
    if qty <= 0 or entry is None:
        print(f"[안전 중단] 전략 소유 수량 또는 실제 진입가를 확인할 수 없습니다. (owned={owned_qty}, account={account_qty})")
        return
    try:
        last_price = current_price_map(client, [symbol]).get(symbol)
    except Exception as e:
        print(f"[오류] 현재가 조회 실패, 모니터링 중단: {e}")
        return
    if last_price is None:
        print(f"  ⚠️ [{symbol}] {name} 현재가 확인 실패 → 손절/익절 판단 보류")
        return
    stop = stop_price(entry)
    take = take_price(entry)
    ret_pct = (last_price - entry) / entry * 100.0
    print(
        f"  - [{symbol}] {name} 전략소유 {qty}주(계좌 {account_qty}주) | 진입가 {entry:,.0f}원 | "
        f"현재가 {last_price:,.0f}원 | 손절가 {stop:,.0f}원 | 익절가 {take:,.0f}원 | 수익률 {ret_pct:+.2f}%"
    )
    trigger = "손절" if last_price <= stop else "익절" if last_price >= take else None
    trigger_price = stop if trigger == "손절" else take if trigger == "익절" else None
    if trigger is None:
        return
    open_sell = has_open_sell_order(client, settings, symbol)
    if open_sell is True:
        print(f"  ⏸️ [{symbol}] 원장에 없는 열린 SELL 주문 존재 → 중복 방지를 위해 매도 보류")
        return
    if open_sell is None:
        print(f"  ⏸️ [{symbol}] 열린 주문 확인 불가 → 중복 방지를 위해 매도 보류")
        return
    submit_strategy_market_sell(
        client,
        settings,
        state,
        quantity=qty,
        trigger=trigger,
        observed_price=last_price,
        trigger_price=trigger_price,
    )


def run_sell(client: TossInvestClient, settings: Settings):
    """15:20 전략 소유 잔여 수량만 시장가 청산하고 체결을 추적한다."""
    update_paper_reentry_watch(client)
    try:
        state = load_strategy_state()
    except simple_gap_state.StrategyStateError as e:
        print(f"[안전 중단] 전략 원장이 손상되어 계좌 보유분을 건드리지 않습니다: {e}")
        return
    if state is None:
        print("추적 중인 전략 포지션이 없습니다. 계좌의 다른 보유 종목은 매도하지 않습니다.")
        return
    state, reconcile_safe = reconcile_strategy_state(client, settings, state)
    state = finalize_filled_exit(state)
    if state.get("status") in simple_gap_state.TERMINAL_STATE_STATUSES:
        print(f"전략 포지션이 이미 종료됐습니다. ({state.get('status')})")
        return
    if not reconcile_safe:
        print("[안전 중단] 주문 체결 상태를 확인하지 못해 중복 청산 주문을 차단합니다.")
        return
    if cancel_stale_buy_order(client, settings, state):
        print("매수 미체결분 취소 확인 후 다음 실행에서 잔여 체결 수량을 청산합니다.")
        return
    if simple_gap_state.active_sell_orders(state):
        print(f"  ⏳ [{state.get('symbol')}] 기존 시장가 매도 주문 체결을 기다립니다.")
        return
    if state.get("status") != "POSITION_OPEN":
        print(f"[안전 중단] 전략 상태가 {state.get('status')}여서 15:20 청산 주문을 차단합니다.")
        return
    try:
        holdings = get_active_holdings(client, settings)
    except Exception as e:
        print(f"[오류] 잔고 조회 실패: {e}")
        return
    holding = tracked_holding(holdings, state)
    ignored = [h for h in holdings if str(h.get("symbol") or "") != str(state.get("symbol") or "")]
    if ignored:
        print(f"계좌의 비전략 보유 종목 {len(ignored)}개는 15:20 청산 대상에서 제외합니다.")
    if holding is None:
        print(f"[안전 중단] 전략 원장에는 {state.get('symbol')} 잔여 수량이 있지만 계좌 보유분을 확인할 수 없습니다.")
        return
    owned_qty = int(state.get("position", {}).get("remaining_quantity") or 0)
    qty = min(owned_qty, holding_quantity(holding))
    if qty <= 0:
        print("전략 소유 잔여 수량이 없습니다.")
        return
    symbol = str(state.get("symbol"))
    try:
        observed_price = current_price_map(client, [symbol]).get(symbol)
    except Exception as e:
        print(f"[경고] 15:20 현재가 조회 실패, 시장가 청산은 계속 진행합니다: {e}")
        observed_price = None
    observed_price = observed_price or float(state.get("position", {}).get("entry_price") or 0)
    open_sell = has_open_sell_order(client, settings, symbol)
    if open_sell is True:
        print(f"  ⏸️ [{symbol}] 원장에 없는 열린 SELL 주문 존재 → 중복 방지를 위해 15:20 청산 보류")
        return
    if open_sell is None:
        print(f"  ⏸️ [{symbol}] 열린 주문 확인 불가 → 중복 방지를 위해 15:20 청산 보류")
        return
    submit_strategy_market_sell(
        client,
        settings,
        state,
        quantity=qty,
        trigger="종가청산",
        observed_price=observed_price,
        trigger_price=None,
    )


def main():
    ap = argparse.ArgumentParser(description="TOSS API Simple Gap-Down Auto Trader")
    ap.add_argument("--action", required=True, choices=["buy", "monitor", "sell"], help="buy (09:01), monitor, or sell (15:20)")
    ap.add_argument("--force", action="store_true", help="Ignore market gate (debug only)")
    args = ap.parse_args()

    settings = Settings.from_env()
    client = TossInvestClient(settings)

    started_at = datetime.now()
    started_perf = time.perf_counter()
    print(f"실행 시간: {started_at.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"모드: {'실전 매매' if settings.live_trading else '모의 매매 (DRY RUN)'}")
    print("=" * 60)

    with strategy_process_lock() as lock_acquired:
        if not lock_acquired:
            print("[중복 실행 차단] 다른 simple_gap_trader 프로세스가 주문 상태를 처리 중입니다.")
        elif args.action == "buy":
            run_buy(client, settings, force=args.force)
        elif args.action == "monitor":
            run_monitor(client, settings)
        elif args.action == "sell":
            run_sell(client, settings)

    ended_at = datetime.now()
    elapsed = time.perf_counter() - started_perf
    print("=" * 60)
    print(f"프로그램 종료: {ended_at.strftime('%Y-%m-%d %H:%M:%S')} / 총 실행시간: {elapsed:.2f}초")


if __name__ == "__main__":
    main()
