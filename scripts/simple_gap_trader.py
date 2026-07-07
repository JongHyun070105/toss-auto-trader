#!/usr/bin/env python3
"""
TOSS API 연동 갭 하락 반등 실전/모의 자동매매 봇
- 오전 09:01 실행: 코스닥 지수 가드 체크 -> robust 갭하락 종목 스캔 -> 시가 매수 주문
- 장중 실행: 보유 종목 손절/익절 모니터링
- 오후 15:20 실행: 보유 종목 전량 종가 매도
"""
import argparse
import json
import os
import sqlite3
import re
import subprocess
import urllib.request
import urllib.parse
import sys
import time
from datetime import datetime
from pathlib import Path

# src 디렉토리 추가
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from toss_auto_trader.config import Settings
from toss_auto_trader import paper_reentry_watch
from toss_auto_trader.discord_notify import MonitorExitAlert, format_monitor_exit_alert, send_discord_message
from toss_auto_trader.paper_exit_messages import format_paper_event
from toss_auto_trader.toss_client import TossInvestClient, TossApiError

DB_PATH = "data/edge_research_universe_15y.sqlite3"
PAPER_REENTRY_LOG = Path("logs") / "simple_gap_reentry_watch.jsonl"
MAX_BUY_AMOUNT_KRW = 0  # 0 또는 미설정이면 Toss cashBuyingPower 전체 사용. TOSS_MAX_BUY_AMOUNT_KRW로 선택 상한 가능.
MIN_PRICE = 1000
MAX_PRICE = 8000
GAP_THRESHOLD = -0.05
PREV_VOL_RATIO_MAX = 0.8
STOP_LOSS_PCT = 0.0225
TAKE_PROFIT_PCT = 0.12
KOSDAQ_SMA5_BUY_RATIO = 0.99
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
    """선택 상한. 기본값은 None=계좌 매수가능금액 전체 사용."""
    raw = os.getenv("TOSS_MAX_BUY_AMOUNT_KRW", str(MAX_BUY_AMOUNT_KRW)).strip().replace(",", "")
    if not raw:
        return None
    value = float(raw)
    return value if value > 0 else None


def fetch_kosdaq_index() -> list[float]:
    """네이버 증권 API로부터 최근 코스닥 지수 일봉 종가 가져오기"""
    today_str = datetime.now().strftime("%Y%m%d")
    query = urllib.parse.urlencode({'startDateTime': '202601010000', 'endDateTime': f'{today_str}2359'})
    url = f'https://api.stock.naver.com/chart/domestic/index/KOSDAQ/day?{query}'
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0', 'Referer': 'https://finance.naver.com/'})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode('utf-8'))
        closes = []
        for row in data or []:
            closes.append(float(str(row['closePrice']).replace(',', '')))
        return closes
    except Exception as e:
        print(f"[경고] 네이버 지수 API 호출 실패: {e}")
        return []


def check_market_gate() -> bool:
    closes = fetch_kosdaq_index()
    if len(closes) < 5:
        print("[주의] 지수 데이터 부족으로 지수 가드를 건너뜁니다.")
        return True

    current_index = closes[-1]
    sma5 = sum(closes[-5:]) / 5.0
    buy_line = sma5 * KOSDAQ_SMA5_BUY_RATIO

    print(f"현재 KOSDAQ 지수: {current_index:.2f} | 5일 이평선: {sma5:.2f} | 매수 허용선: {buy_line:.2f}")
    if current_index > buy_line:
        print("🚨 [시장 가드 발동] KOSDAQ이 5일선보다 1% 이상 아래가 아니므로 오늘 매매는 정지합니다.")
        return False

    print("✅ 지수 가드 통과: KOSDAQ이 5일선보다 1% 이상 아래인 눌림 국면입니다.")
    return True


def get_base_stocks_from_db():
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


def get_actual_budget(client: TossInvestClient, settings: Settings) -> float:
    """실제 예수금을 API로 조회하여 실제 사용 가능 금액 반환.

    기본은 Toss cashBuyingPower 전체 사용. 필요하면 TOSS_MAX_BUY_AMOUNT_KRW로 별도 상한을 건다.
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


def run_buy(client: TossInvestClient, settings: Settings, force: bool = False):
    """오전 9시 갭하락 종목 매수 로직"""
    if not force:
        if not check_market_gate():
            return
    else:
        print("⚠️ [디버그 옵션] 지수 가드를 무시하고 매수 로직을 강제 실행합니다.")

    base_stocks = get_base_stocks_from_db()
    if not base_stocks:
        print(f"스크리닝 조건({MIN_PRICE:,}원~{MAX_PRICE:,}원)을 통과한 종목이 없습니다.")
        return

    # 실제 예수금 조회 (안전 상한 MAX_BUY_AMOUNT_KRW와 비교)
    remaining_budget = get_actual_budget(client, settings)
    if remaining_budget < MIN_PRICE:
        print(f"[중단] 예수금({remaining_budget:,.0f}원)이 최소 주가({MIN_PRICE:,}원)보다 적어 매수 불가합니다.")
        return

    # 100개씩 나눠서 실시간 시세 조회
    chunk_size = 100
    base_map = {s['symbol']: s for s in base_stocks}
    symbols = list(base_map.keys())
    chunks = [symbols[i:i + chunk_size] for i in range(0, len(symbols), chunk_size)]

    triggered = []
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
                if provisional_gap > GAP_THRESHOLD:
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
        print("매수 진입 조건을 통과한 최종 종목이 없습니다.")
        return

    print("\n=== 최종 진입 대기 종목 (상위 5개) ===")
    for f in triggered[:5]:
        print(f"  [{f['symbol']}] {f['name']} | 갭률: {f['gap_pct']:.2f}% | 시가: {f['open_price']:,}원 | 현재가: {f['last_price']:,}원 | 전일종가: {f['prev_close']:,}원")

    # 1종목 집중 매수: 최상위 1종목에 예산 전액 투입.
    # 단, Toss 매수 유의사항(투자경고/단기과열/VI 등)은 주문 전 fail-closed로 제외.
    orders_to_send = []
    for target in triggered:
        limit_price = int(float(target['open_price']))  # 백테스트 진입가와 일치: 당일 시가 기준 지정가
        if remaining_budget < limit_price:
            print(f"  ⏭️ [{target['symbol']}] {target['name']} 시가 지정가 {limit_price:,}원이 예산 {remaining_budget:,.0f}원 초과로 제외")
            continue

        warnings = blocking_warnings_for_symbol(client, target['symbol'])
        if warnings:
            print(f"  ⛔ [{target['symbol']}] {target['name']} 매수 유의사항 필터 제외: {', '.join(warnings)}")
            time.sleep(0.25)
            continue
        time.sleep(0.25)

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
        payload = build_limit_quantity_order(target['symbol'], "BUY", qty, limit_price)
        try:
            print(
                f"  🚀 [{target['name']}] {qty}주 지정가 매수 주문 발송 "
                f"(전략 {STRATEGY_NAME}, 배정금액 {cost:,.0f}원, 지정가 {limit_price:,}원, "
                f"손절가 {stop_price(limit_price):,.0f}원, 익절가 {take_price(limit_price):,.0f}원)..."
            )
            res = client.create_order(settings.account_seq, payload)
            if res.get('dryRun'):
                print(f"  * [모의 실행] 주문 발송 가상 응답: {res['wouldSend']}")
            else:
                print(f"  * [실전 주문] 주문 성공! 주문ID: {extract_order_id(res) or '확인 필요'}")
        except TossApiError as e:
            print(f"  ❌ [{target['name']}] 매수 주문 실패: {e}")
        except Exception as e:
            print(f"  ❌ [{target['name']}] 시스템 에러: {e}")


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
        holdings = get_active_holdings(client, settings)
    except TossApiError as e:
        print(f"[오류] 잔고 조회 실패: {e}")
        return
    except Exception as e:
        print(f"[오류] 시스템 에러: {e}")
        return

    if not holdings:
        print("현재 보유 중인 종목이 없습니다. 장중 모니터링을 종료합니다.")
        return

    print(f"현재 보유 종목 수: {len(holdings)}개. 손절/익절 모니터링을 실행합니다.")
    symbols = [str(h["symbol"]) for h in holdings]
    try:
        prices = current_price_map(client, symbols)
    except Exception as e:
        print(f"[오류] 현재가 조회 실패, 모니터링 중단: {e}")
        return

    for h in holdings:
        symbol = str(h["symbol"])
        name = h.get("name", symbol)
        qty = holding_quantity(h)
        entry = holding_average_price(h)
        last_price = prices.get(symbol)
        if qty <= 0:
            continue
        if entry is None:
            print(f"  ⚠️ [{symbol}] {name} 평균단가 확인 실패 → 손절/익절 판단 보류")
            continue
        if last_price is None:
            print(f"  ⚠️ [{symbol}] {name} 현재가 확인 실패 → 손절/익절 판단 보류")
            continue

        stop = stop_price(entry)
        take = take_price(entry)
        ret_pct = (last_price - entry) / entry * 100.0
        print(
            f"  - [{symbol}] {name} {qty}주 | 진입가 {entry:,.0f}원 | 현재가 {last_price:,.0f}원 | "
            f"손절가 {stop:,.0f}원 | 익절가 {take:,.0f}원 | 수익률 {ret_pct:+.2f}%"
        )

        trigger = None
        trigger_price = None
        if last_price <= stop:
            trigger = "손절"
            trigger_price = stop
        elif last_price >= take:
            trigger = "익절"
            trigger_price = take
        if trigger is None:
            continue

        open_sell = has_open_sell_order(client, settings, symbol)
        if open_sell is True:
            print(f"  ⏸️ [{symbol}] {name} 열린 SELL 주문 존재 → 중복 매도 보류")
            continue
        if open_sell is None:
            print(f"  ⏸️ [{symbol}] {name} 열린 주문 확인 불가 → 중복 방지를 위해 매도 보류")
            continue

        limit_price = best_limit_price(client, symbol, "SELL", last_price)
        if limit_price <= 0:
            print(f"  ❌ [{symbol}] {name} 매도 지정가 산출 실패, 안전상 매도 주문 중단")
            continue
        expected_amount = limit_price * qty
        payload = build_limit_quantity_order(symbol, "SELL", qty, limit_price)
        try:
            print(
                f"  🚨 [{name}] {qty}주 {trigger} 매도 주문 발송 "
                f"(진입가 {entry:,.0f}원, 현재가 {last_price:,.0f}원, 트리거 {trigger_price:,.0f}원, "
                f"지정가 {limit_price:,.0f}원, 예상금액 {expected_amount:,.0f}원)..."
            )
            res = client.create_order(settings.account_seq, payload)
            if res.get('dryRun'):
                print(f"  * [모의 실행] 모니터 매도 주문 가상 응답: {res['wouldSend']}")
            else:
                order_id = extract_order_id(res)
                print(f"  * [실전 주문] 모니터 매도 주문 성공! 주문ID: {order_id or '확인 필요'}")
                occurred_at = datetime.now()
                notify_monitor_exit(
                    MonitorExitAlert(
                        strategy_name=STRATEGY_NAME,
                        trigger=trigger,
                        symbol=symbol,
                        name=name,
                        qty=qty,
                        entry_price=entry,
                        last_price=last_price,
                        trigger_price=trigger_price,
                        limit_price=limit_price,
                        expected_amount=expected_amount,
                        return_pct=ret_pct,
                        order_id=order_id,
                        occurred_at=occurred_at,
                    )
                )
                if trigger == "손절":
                    paper_reentry_watch.record_stop_exit(
                        PAPER_REENTRY_LOG,
                        symbol=symbol,
                        name=name,
                        qty=qty,
                        entry_price=entry,
                        stop_price=stop,
                        observed_price=last_price,
                        exit_limit_price=float(limit_price),
                        order_id=order_id,
                        now=occurred_at,
                    )
                    print(f"  📝 [paper-only] [{symbol}] {name} 손절 후 재진입 관찰 시작 | 실주문 없음")
                elif trigger == "익절":
                    paper_reentry_watch.record_take_profit_exit(
                        PAPER_REENTRY_LOG,
                        symbol=symbol,
                        name=name,
                        qty=qty,
                        entry_price=entry,
                        take_price=take,
                        observed_price=last_price,
                        exit_limit_price=float(limit_price),
                        order_id=order_id,
                        now=occurred_at,
                    )
                    print(f"  📝 [paper-only] [{symbol}] {name} 익절 후 추가상승 관찰 시작 | 실주문 없음")
        except TossApiError as e:
            print(f"  ❌ [{name}] 모니터 매도 주문 실패: {e}")
        except Exception as e:
            print(f"  ❌ [{name}] 모니터 매도 에러: {e}")


def run_sell(client: TossInvestClient, settings: Settings):
    """오후 3시 15분 보유 종목 일괄 종가 매도"""
    update_paper_reentry_watch(client)
    print("계좌 잔고 조회 중...")

    try:
        active_holdings = get_active_holdings(client, settings)
    except TossApiError as e:
        print(f"[오류] 잔고 조회 실패: {e}")
        return
    except Exception as e:
        print(f"[오류] 시스템 에러: {e}")
        return

    if not active_holdings:
        print("현재 보유 중인 종목이 없습니다. 당일 매도를 종료합니다.")
        return

    print(f"현재 보유 종목 수: {len(active_holdings)}개. 전량 지정가 종가 매도를 실행합니다.")

    # 매도 보고/손익 추정을 위해 주문 직전 현재가를 남긴다.
    price_map = {}
    try:
        symbols = [h["symbol"] for h in active_holdings]
        prices_resp = client.get_prices(symbols)
        for p in prices_resp.get("result", []) or []:
            last_price = float(p.get("lastPrice", "0") or 0)
            if last_price > 0:
                price_map[p["symbol"]] = last_price
    except Exception as e:
        print(f"[경고] 매도 직전 현재가 조회 실패, 예상 매도금액 없이 주문 진행: {e}")

    for h in active_holdings:
        symbol = h["symbol"]
        name = h.get("name", symbol)
        qty_int = holding_quantity(h)
        open_sell = has_open_sell_order(client, settings, symbol)
        if open_sell is True:
            print(f"  ⏸️ [{symbol}] {name} 열린 SELL 주문 존재 → 15:20 중복 매도 보류")
            continue
        if open_sell is None:
            print(f"  ⏸️ [{symbol}] {name} 열린 주문 확인 불가 → 중복 방지를 위해 15:20 매도 보류")
            continue
        raw_expected_price = price_map.get(symbol)
        limit_price = best_limit_price(client, symbol, "SELL", raw_expected_price or 0)
        if limit_price <= 0:
            print(f"  ❌ [{name}] 매도 지정가 산출 실패, 안전상 매도 주문 중단")
            continue
        expected_price = float(limit_price)
        expected_amount = expected_price * qty_int if expected_price else None

        payload = build_limit_quantity_order(symbol, "SELL", qty_int, limit_price)
        try:
            if expected_price:
                print(f"  🚀 [{name}] {qty_int}주 지정가 매도 주문 발송 (지정가 {expected_price:,.0f}원, 예상금액 {expected_amount:,.0f}원)...")
            else:
                print(f"  🚀 [{name}] {qty_int}주 지정가 매도 주문 발송...")
            res = client.create_order(settings.account_seq, payload)
            if res.get('dryRun'):
                print(f"  * [모의 실행] 매도 주문 가상 응답: {res['wouldSend']}")
            else:
                print(f"  * [실전 주문] 매도 주문 성공! 주문ID: {extract_order_id(res) or '확인 필요'}")
        except TossApiError as e:
            print(f"  ❌ [{name}] 매도 주문 실패: {e}")
        except Exception as e:
            print(f"  ❌ [{name}] 매도 에러: {e}")


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

    if args.action == "buy":
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
