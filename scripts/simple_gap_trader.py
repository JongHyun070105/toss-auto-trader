#!/usr/bin/env python3
"""
TOSS API 연동 갭 하락 3% 반등 실전/모의 자동매매 봇
- 오전 09:01 실행: 코스닥 지수 가드 체크 -> 갭하락 종목 스캔 -> 시가 매수 주문
- 오후 15:15 실행: 보유 종목 전량 종가 매도
"""
import argparse
import json
import os
import sqlite3
import urllib.request
import urllib.parse
import sys
import time
from datetime import datetime
from pathlib import Path

# src 디렉토리 추가
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from toss_auto_trader.config import Settings
from toss_auto_trader.toss_client import TossInvestClient, TossApiError

DB_PATH = "data/edge_research_universe_15y.sqlite3"
MAX_BUY_AMOUNT_KRW = 0  # 0 또는 미설정이면 Toss cashBuyingPower 전체 사용. TOSS_MAX_BUY_AMOUNT_KRW로 선택 상한 가능.
MIN_PRICE = 5000
MAX_PRICE = 50000


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
    """5일 지수 이동평균선(SMA) 가드 체크"""
    closes = fetch_kosdaq_index()
    if len(closes) < 5:
        print("[주의] 지수 데이터 부족으로 지수 가드를 건너뜁니다.")
        return True

    current_index = closes[-1]
    sma5 = sum(closes[-5:]) / 5.0

    print(f"현재 KOSDAQ 지수: {current_index:.2f} | 5일 이평선: {sma5:.2f}")
    if current_index < sma5:
        print("🚨 [시장 하락 가드 발동] 현재 지수가 5일 이평선 아래에 있으므로 오늘 매매는 정지합니다.")
        return False

    print("✅ 지수 가드 통과: 현재 상승/횡보세 국면입니다.")
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

    # 2. 최근 영업일 기준 5,000원 ~ 50,000원 사이 종목 + 전일 거래량 함께 로드
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
    print(f"로컬 스크리닝 필터 통과 종목 수: {len(candidates)}개")
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


def run_buy(client: TossInvestClient, settings: Settings, force: bool = False):
    """오전 9시 갭하락 종목 매수 로직"""
    if not force:
        if not check_market_gate():
            return
    else:
        print("⚠️ [디버그 옵션] 지수 가드를 무시하고 매수 로직을 강제 실행합니다.")

    base_stocks = get_base_stocks_from_db()
    if not base_stocks:
        print("스크리닝 조건(5,000원~50,000원)을 통과한 종목이 없습니다.")
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
    print("실시간 현재가 수집 및 갭 하락 검사 시작...")

    for chunk in chunks:
        try:
            prices_resp = client.get_prices(chunk)
            prices = prices_resp.get("result", [])
            for p in prices:
                sym = p["symbol"]
                last_price = float(p.get("lastPrice", "0"))
                if last_price <= 0:
                    continue

                # 갭 계산: 9시 확정 시가(openPrice) 기준 (백테스트 조건과 일치)
                open_price = float(p.get("openPrice", "0"))
                if open_price <= 0:
                    open_price = last_price  # 시가 데이터 누락 시 현재가로 폴백

                prev_close = base_map[sym]['prev_close']
                gap = (open_price - prev_close) / prev_close

                # 거래량 필터: 전일 확정 거래량 vs 전일 제외 직전 20일 평균 (백테스트 조건과 일치)
                prev_vol_ratio = base_map[sym]['prev_vol'] / base_map[sym]['avg_vol']
                if prev_vol_ratio >= 1.0:
                    continue  # 전일 거래량이 이미 평균 초과 → 투매 신호, 제외

                # 갭 하락 3% 이하 종목 탐색
                if gap <= -0.03:
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

    print(f"갭 하락 3% 돌파 종목 수: {len(triggered)}개")

    # 갭 하락률이 큰 순서로 정렬 (가장 크게 빠진 종목 우선)
    triggered.sort(key=lambda x: x['gap_pct'])

    if not triggered:
        print("매수 진입 조건을 통과한 최종 종목이 없습니다.")
        return

    print("\n=== 최종 진입 대기 종목 (상위 5개) ===")
    for f in triggered[:5]:
        print(f"  [{f['symbol']}] {f['name']} | 갭률: {f['gap_pct']:.2f}% | 시가: {f['open_price']:,}원 | 현재가: {f['last_price']:,}원 | 전일종가: {f['prev_close']:,}원")

    # 1종목 집중 매수: 최상위 1종목에 예산 전액 투입
    orders_to_send = []
    for target in triggered:
        price = target['last_price']
        if remaining_budget < price:
            continue  # 1주도 살 수 없으면 패스

        qty = int(remaining_budget // price)
        if qty > 0:
            cost = qty * price
            remaining_budget -= cost
            orders_to_send.append((target, qty, cost))
            break  # 최상위 1종목만 매수하고 종료

    print(f"\n최종 매수 대상 종목 수: {len(orders_to_send)}개 (남은 예수금: {remaining_budget:,.0f}원)")

    for target, qty, cost in orders_to_send:
        payload = build_market_quantity_order(target['symbol'], "BUY", qty)
        try:
            print(f"  🚀 [{target['name']}] {qty}주 매수 주문 발송 (배정금액 {cost:,.0f}원, 예상단가 {target['last_price']:,}원)...")
            res = client.create_order(settings.account_seq, payload)
            if res.get('dryRun'):
                print(f"  * [모의 실행] 주문 발송 가상 응답: {res['wouldSend']}")
            else:
                print(f"  * [실전 주문] 주문 성공! 주문ID: {res.get('orderId')}")
        except TossApiError as e:
            print(f"  ❌ [{target['name']}] 매수 주문 실패: {e}")
        except Exception as e:
            print(f"  ❌ [{target['name']}] 시스템 에러: {e}")


def run_sell(client: TossInvestClient, settings: Settings):
    """오후 3시 15분 보유 종목 일괄 종가 매도"""
    print("계좌 잔고 조회 중...")

    try:
        holdings_resp = client.get_holdings(settings.account_seq)
        holdings = holdings_resp.get("result", {}).get("holdings", [])
        active_holdings = [h for h in holdings if int(h.get("quantity", "0")) > 0]
    except TossApiError as e:
        print(f"[오류] 잔고 조회 실패: {e}")
        return
    except Exception as e:
        print(f"[오류] 시스템 에러: {e}")
        return

    if not active_holdings:
        print("현재 보유 중인 종목이 없습니다. 당일 매도를 종료합니다.")
        return

    print(f"현재 보유 종목 수: {len(active_holdings)}개. 전량 시장가 종가 매도를 실행합니다.")

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
        qty = h["quantity"]
        name = h.get("name", symbol)
        qty_int = int(qty)
        expected_price = price_map.get(symbol)
        expected_amount = expected_price * qty_int if expected_price else None

        payload = build_market_quantity_order(symbol, "SELL", qty)
        try:
            if expected_price:
                print(f"  🚀 [{name}] {qty}주 매도 주문 발송 (예상단가 {expected_price:,.0f}원, 예상금액 {expected_amount:,.0f}원)...")
            else:
                print(f"  🚀 [{name}] {qty}주 매도 주문 발송...")
            res = client.create_order(settings.account_seq, payload)
            if res.get('dryRun'):
                print(f"  * [모의 실행] 매도 주문 가상 응답: {res['wouldSend']}")
            else:
                print(f"  * [실전 주문] 매도 주문 성공! 주문ID: {res.get('orderId')}")
        except TossApiError as e:
            print(f"  ❌ [{name}] 매도 주문 실패: {e}")
        except Exception as e:
            print(f"  ❌ [{name}] 매도 에러: {e}")


def main():
    ap = argparse.ArgumentParser(description="TOSS API Simple Gap-Down 3% Auto Trader")
    ap.add_argument("--action", required=True, choices=["buy", "sell"], help="buy (09:01) or sell (15:15)")
    ap.add_argument("--force", action="store_true", help="Ignore market gate (debug only)")
    args = ap.parse_args()

    settings = Settings.from_env()
    client = TossInvestClient(settings)

    print(f"실행 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"모드: {'실전 매매' if settings.live_trading else '모의 매매 (DRY RUN)'}")
    print("=" * 60)

    if args.action == "buy":
        run_buy(client, settings, force=args.force)
    elif args.action == "sell":
        run_sell(client, settings)

    print("=" * 60)
    print("프로그램 종료")


if __name__ == "__main__":
    main()
