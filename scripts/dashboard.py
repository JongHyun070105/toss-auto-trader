#!/usr/bin/env python3
"""
TOSS 자동매매 대시보드
사용법: python scripts/dashboard.py
"""
import json
import re
import sqlite3
import sys
import webbrowser
import urllib.request
import urllib.parse
from datetime import datetime
from pathlib import Path

ROOT    = Path(__file__).resolve().parents[1]
BUY_LOG = ROOT / "logs" / "simple_gap_trader_buy.log"
SELL_LOG= ROOT / "logs" / "simple_gap_trader_sell.log"
DB_PATH = ROOT / "data" / "edge_research_universe_15y.sqlite3"
OUT     = ROOT / "logs" / "dashboard.html"

INITIAL_CAPITAL = 10_000  # 1만원

# ──────────────────────────────────────────────
# 로그 파서
# ──────────────────────────────────────────────

def parse_buy_log():
    if not BUY_LOG.exists():
        return []
    sessions, cur = [], None
    for line in BUY_LOG.read_text(encoding="utf-8", errors="ignore").splitlines():
        m = re.match(r"실행 시간: (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", line)
        if m:
            if cur:
                sessions.append(cur)
            cur = {"datetime": m.group(1), "date": m.group(1)[:10],
                   "guard_ok": None, "kosdaq": None, "sma5": None,
                   "gap_stocks": 0, "scan_total": 0, "candidates": [],
                   "buy": None}
            continue
        if cur is None:
            continue
        if "가드 발동" in line:
            cur["guard_ok"] = False
        elif "지수 가드 통과" in line:
            cur["guard_ok"] = True
        m = re.search(r"현재 KOSDAQ 지수: ([\d.]+) \| 5일 이평선: ([\d.]+)", line)
        if m:
            cur["kosdaq"] = float(m.group(1))
            cur["sma5"]   = float(m.group(2))
        m = re.search(r"로컬 스크리닝 필터 통과 종목 수: (\d+)개", line)
        if m:
            cur["scan_total"] = int(m.group(1))
        m = re.search(r"갭 하락 3% 돌파 종목 수: (\d+)개", line)
        if m:
            cur["gap_stocks"] = int(m.group(1))
        # 상위 종목 파싱: [심볼] 이름 | 갭률: X.XX% | 시가: X원 | ...
        m = re.search(r"\[(\w+)\] (.+?) \| 갭률: ([-\d.]+)% \| 시가: ([\d,]+)원", line)
        if m and len(cur["candidates"]) < 5:
            cur["candidates"].append({
                "symbol": m.group(1), "name": m.group(2),
                "gap_pct": float(m.group(3)),
                "open_price": int(m.group(4).replace(",", ""))
            })
        # 매수 주문
        m = re.search(r"🚀 \[(.+?)\] (\d+)주 매수 주문 발송 \(배정금액 ([\d,]+)원, 예상단가 ([\d,]+)원\)", line)
        if m:
            cur["buy"] = {
                "name": m.group(1), "qty": int(m.group(2)),
                "amount": int(m.group(3).replace(",", "")),
                "price": int(m.group(4).replace(",", "")),
                "success": None, "order_id": None,
            }
        if cur.get("buy"):
            m = re.search(r"주문 성공! 주문ID: (.+)", line)
            if m:
                cur["buy"]["success"] = True
                cur["buy"]["order_id"] = m.group(1).strip()
            if "주문 실패" in line or "시스템 에러" in line:
                cur["buy"]["success"] = False
    if cur:
        sessions.append(cur)
    return sessions


def parse_sell_log():
    if not SELL_LOG.exists():
        return {}
    result, cur = {}, None
    for line in SELL_LOG.read_text(encoding="utf-8", errors="ignore").splitlines():
        m = re.match(r"실행 시간: (\d{4}-\d{2}-\d{2})", line)
        if m:
            cur = m.group(1)
            result[cur] = {"sold": False, "no_holdings": False, "items": []}
            continue
        if cur is None:
            continue
        if "보유 중인 종목이 없습니다" in line:
            result[cur]["no_holdings"] = True
        m = re.search(r"🚀 \[(.+?)\] (\d+)주 매도 주문 발송", line)
        if m:
            result[cur]["items"].append({"name": m.group(1), "qty": int(m.group(2)), "success": None})
        if result[cur]["items"] and "매도 주문 성공" in line:
            result[cur]["items"][-1]["success"] = True
            result[cur]["sold"] = True
    return result


def get_close_price(symbol, date_str):
    if not DB_PATH.exists():
        return None
    try:
        conn = sqlite3.connect(str(DB_PATH))
        cur  = conn.cursor()
        cur.execute("""SELECT close_price FROM candle_cache
                       WHERE symbol = ? AND substring(timestamp,1,10) = ? LIMIT 1""",
                    (symbol, date_str))
        row = cur.fetchone()
        conn.close()
        return float(row[0]) if row else None
    except:
        return None


def get_symbol_by_name(name):
    if not DB_PATH.exists():
        return None
    try:
        conn = sqlite3.connect(str(DB_PATH))
        cur  = conn.cursor()
        cur.execute("SELECT DISTINCT symbol FROM candle_cache WHERE name = ? LIMIT 1", (name,))
        row = cur.fetchone()
        conn.close()
        return row[0] if row else None
    except:
        return None


def fetch_kosdaq():
    try:
        today = datetime.now().strftime("%Y%m%d")
        q   = urllib.parse.urlencode({"startDateTime": "202601010000", "endDateTime": f"{today}2359"})
        url = f"https://api.stock.naver.com/chart/domestic/index/KOSDAQ/day?{q}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0",
                                                    "Referer": "https://finance.naver.com/"})
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read().decode())
        closes = [float(str(row["closePrice"]).replace(",", "")) for row in (data or [])]
        if len(closes) >= 5:
            history = []
            for row in (data or [])[-7:]:
                history.append({"date": str(row.get("localDate", ""))[:10],
                                 "close": float(str(row["closePrice"]).replace(",", ""))})
            return {"current": closes[-1], "sma5": sum(closes[-5:]) / 5, "history": history}
    except:
        pass
    return None


# ──────────────────────────────────────────────
# 데이터 조합
# ──────────────────────────────────────────────

def build_data():
    buy_sessions = parse_buy_log()
    sell_map     = parse_sell_log()
    kosdaq       = fetch_kosdaq()

    trades = []
    cumulative_pnl = 0
    max_drawdown   = 0
    peak           = 0
    consecutive_loss = 0
    max_consec_loss  = 0
    tmp_loss = 0

    for s in buy_sessions:
        trade = {
            "date": s["date"], "datetime": s["datetime"],
            "guard_ok": s["guard_ok"],
            "kosdaq": s["kosdaq"], "sma5": s["sma5"],
            "scan_total": s["scan_total"],
            "gap_stocks": s["gap_stocks"],
            "candidates": s["candidates"],
            "buy": s["buy"],
            "sell": sell_map.get(s["date"]),
            "pnl": None, "pnl_pct": None, "sell_price": None,
        }

        if s["buy"] and s["buy"].get("success"):
            sym = None
            # candidates에서 이름으로 심볼 찾기
            for c in s["candidates"]:
                if c["name"] == s["buy"]["name"]:
                    sym = c["symbol"]
                    break
            if not sym:
                sym = get_symbol_by_name(s["buy"]["name"])

            if sym:
                close = get_close_price(sym, s["date"])
                if close:
                    trade["sell_price"] = close
                    pnl = (close - s["buy"]["price"]) * s["buy"]["qty"]
                    pnl_pct = (close - s["buy"]["price"]) / s["buy"]["price"] * 100
                    trade["pnl"]     = round(pnl)
                    trade["pnl_pct"] = round(pnl_pct, 2)
                    cumulative_pnl  += pnl

                    if pnl >= 0:
                        tmp_loss = 0
                    else:
                        tmp_loss += 1
                    max_consec_loss = max(max_consec_loss, tmp_loss)

                    # 최대 낙폭
                    if cumulative_pnl > peak:
                        peak = cumulative_pnl
                    dd = peak - cumulative_pnl
                    if dd > max_drawdown:
                        max_drawdown = dd

        trades.append(trade)

    total_trades = sum(1 for t in trades if t["buy"] and t["buy"].get("success"))
    wins  = sum(1 for t in trades if t["pnl"] is not None and t["pnl"] > 0)
    losses= sum(1 for t in trades if t["pnl"] is not None and t["pnl"] < 0)
    win_rate = (wins / total_trades * 100) if total_trades else 0

    # 오늘 현황
    today_str = datetime.now().strftime("%Y-%m-%d")
    today = next((t for t in reversed(trades) if t["date"] == today_str), None)
    if today is None and trades:
        today = trades[-1]

    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "kosdaq": kosdaq,
        "today": today,
        "trades": list(reversed(trades)),  # 최신 순
        "stats": {
            "total_trades": total_trades,
            "wins": wins,
            "losses": losses,
            "win_rate": round(win_rate, 1),
            "cumulative_pnl": round(cumulative_pnl),
            "cumulative_pct": round(cumulative_pnl / INITIAL_CAPITAL * 100, 2),
            "max_drawdown": round(max_drawdown),
            "max_consec_loss": max_consec_loss,
        },
        "guard_history": [
            {"date": t["date"], "ok": t["guard_ok"],
             "kosdaq": t["kosdaq"], "sma5": t["sma5"]}
            for t in reversed(trades)
        ][-7:],
    }


# ──────────────────────────────────────────────
# HTML 렌더러
# ──────────────────────────────────────────────

def render(data):
    d      = data
    s      = d["stats"]
    today  = d["today"]
    kosdaq = d["kosdaq"]
    trades = d["trades"]

    # 오늘 현황 값
    if today:
        guard_badge = ('<span class="badge badge-green">✅ 통과</span>' if today["guard_ok"]
                       else '<span class="badge badge-red">🚨 차단</span>'
                       if today["guard_ok"] is False
                       else '<span class="badge badge-gray">-</span>')
        if today["buy"] and today["buy"].get("success"):
            b = today["buy"]
            buy_html = f"""
                <div class="buy-card">
                    <div class="buy-name">{b['name']}</div>
                    <div class="buy-meta">
                        <span>{b['qty']}주</span>
                        <span>@{b['price']:,}원</span>
                        <span class="dim">배정 {b['amount']:,}원</span>
                    </div>
                </div>"""
        elif today["guard_ok"] is False:
            buy_html = '<div class="no-trade">시장 가드 발동 — 오늘 미거래</div>'
        elif today["buy"] and today["buy"].get("success") is False:
            buy_html = '<div class="no-trade warn">매수 주문 실패</div>'
        else:
            buy_html = '<div class="no-trade">조건 통과 종목 없음</div>'

        pnl_val = today.get("pnl")
        if pnl_val is not None:
            cls  = "pos" if pnl_val >= 0 else "neg"
            sign = "+" if pnl_val >= 0 else ""
            pnl_html = f'<div class="pnl-val {cls}">{sign}{pnl_val:,}원</div><div class="pnl-pct {cls}">{sign}{today["pnl_pct"]}%</div>'
        else:
            pnl_html = '<div class="pnl-val dim">집계 중</div><div class="pnl-sub dim">당일 종가 확인 필요</div>'

        kosdaq_today = today.get("kosdaq") or (kosdaq["current"] if kosdaq else None)
        sma5_today   = today.get("sma5")   or (kosdaq["sma5"]   if kosdaq else None)
        scan_total   = today.get("scan_total", 0)
        gap_stocks   = today.get("gap_stocks", 0)
    else:
        guard_badge = '<span class="badge badge-gray">데이터 없음</span>'
        buy_html    = '<div class="no-trade">거래 데이터 없음</div>'
        pnl_html    = '<div class="pnl-val dim">-</div>'
        kosdaq_today = kosdaq["current"] if kosdaq else None
        sma5_today   = kosdaq["sma5"]   if kosdaq else None
        scan_total   = 0
        gap_stocks   = 0

    # 코스닥 가드 여유
    if kosdaq_today and sma5_today:
        gap_to_sma = kosdaq_today - sma5_today
        gap_class  = "pos" if gap_to_sma >= 0 else "neg"
        gap_sign   = "+" if gap_to_sma >= 0 else ""
        kosdaq_html = f"""
            <div class="kosdaq-row">
                <div>
                    <div class="kosdaq-val">{kosdaq_today:,.2f}</div>
                    <div class="dim small">현재 코스닥</div>
                </div>
                <div class="kosdaq-arrow">vs</div>
                <div>
                    <div class="kosdaq-val">{sma5_today:,.2f}</div>
                    <div class="dim small">5일 이평선</div>
                </div>
                <div class="kosdaq-gap {gap_class}">
                    {gap_sign}{gap_to_sma:,.2f}<br><span class="small">이격</span>
                </div>
            </div>"""
    else:
        kosdaq_html = '<div class="dim">코스닥 데이터 없음</div>'

    # 가드 이력 (최근 7일)
    guard_hist_html = ""
    for gh in d["guard_history"]:
        ok = gh.get("ok")
        if ok is True:
            dot = '<span class="dot dot-green" title="통과">✓</span>'
        elif ok is False:
            dot = '<span class="dot dot-red" title="차단">✗</span>'
        else:
            dot = '<span class="dot dot-gray">?</span>'
        guard_hist_html += f'<div class="guard-item">{dot}<span class="small dim">{gh["date"][5:]}</span></div>'

    # 연속 손실 경고
    consec = s["max_consec_loss"]
    if consec >= 3:
        risk_html = f'<div class="risk-warn">⚠️ 최대 연속 손실 {consec}회 — 전략 재검토 필요</div>'
    elif consec >= 2:
        risk_html = f'<div class="risk-caution">🔶 연속 손실 {consec}회 — 주의</div>'
    else:
        risk_html = f'<div class="risk-ok">✅ 연속 손실 {consec}회 — 정상</div>'

    # 누적 손익 색상
    cum_pnl = s["cumulative_pnl"]
    cum_cls = "pos" if cum_pnl >= 0 else "neg"
    cum_sign= "+" if cum_pnl >= 0 else ""

    # 거래 내역 테이블
    rows = ""
    for t in trades:
        if not (t["buy"] and t["buy"].get("success")):
            # 미거래 행
            guard_txt = "🚨 차단" if t["guard_ok"] is False else "조건 미충족"
            rows += f"""
            <tr class="no-buy-row">
                <td>{t['date']}</td>
                <td colspan="6" class="dim center">{guard_txt}</td>
            </tr>"""
            continue

        b = t["buy"]
        pnl = t.get("pnl")
        pnl_cls  = "pos" if (pnl is not None and pnl >= 0) else "neg" if (pnl is not None) else ""
        pnl_sign = "+" if (pnl is not None and pnl >= 0) else ""
        pnl_txt  = f"{pnl_sign}{pnl:,}원" if pnl is not None else "집계 중"
        pct_txt  = f"{pnl_sign}{t['pnl_pct']}%" if t.get("pnl_pct") is not None else "-"
        sell_txt = f"{t['sell_price']:,}원" if t.get("sell_price") else "집계 중"
        rows += f"""
            <tr>
                <td>{t['date']}</td>
                <td><strong>{b['name']}</strong></td>
                <td class="right">{b['price']:,}원</td>
                <td class="right">{sell_txt}</td>
                <td class="right">{b['qty']}주</td>
                <td class="right {pnl_cls}">{pnl_txt}</td>
                <td class="right {pnl_cls}">{pct_txt}</td>
            </tr>"""

    if not rows:
        rows = '<tr><td colspan="7" class="center dim">거래 내역 없음 — 첫 거래를 기다리는 중</td></tr>'

    # 스캔 퍼널
    funnel_html = f"""
        <div class="funnel">
            <div class="funnel-item">
                <div class="funnel-num">{scan_total:,}</div>
                <div class="funnel-label">DB 필터 통과</div>
            </div>
            <div class="funnel-arrow">→</div>
            <div class="funnel-item">
                <div class="funnel-num {'pos' if gap_stocks > 0 else ''}">{gap_stocks}</div>
                <div class="funnel-label">갭하락 -3%</div>
            </div>
            <div class="funnel-arrow">→</div>
            <div class="funnel-item">
                <div class="funnel-num">{'1' if (today and today.get('buy') and today['buy'].get('success')) else '0'}</div>
                <div class="funnel-label">최종 매수</div>
            </div>
        </div>"""

    html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>TOSS 자동매매 대시보드</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet">
<style>
:root {{
    --bg:       #080b12;
    --card:     rgba(255,255,255,0.045);
    --border:   rgba(255,255,255,0.07);
    --text:     #e8eaf0;
    --dim:      #6b7280;
    --blue:     #4facfe;
    --green:    #22c55e;
    --red:      #ef4444;
    --yellow:   #f59e0b;
    --radius:   16px;
}}
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{
    background: var(--bg);
    color: var(--text);
    font-family: 'Inter', sans-serif;
    min-height: 100vh;
    background-image: radial-gradient(ellipse 80% 50% at 50% -10%, rgba(79,172,254,0.12) 0%, transparent 60%);
}}
.container {{ max-width: 1200px; margin: 0 auto; padding: 32px 24px; }}
header {{
    display: flex; justify-content: space-between; align-items: center;
    margin-bottom: 36px;
}}
.logo {{ font-size: 22px; font-weight: 800; letter-spacing: -0.5px; }}
.logo span {{ color: var(--blue); }}
.generated {{ font-size: 12px; color: var(--dim); }}
.grid-3 {{ display: grid; grid-template-columns: repeat(3,1fr); gap: 16px; margin-bottom: 20px; }}
.grid-2 {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 20px; }}
.grid-4 {{ display: grid; grid-template-columns: repeat(4,1fr); gap: 16px; margin-bottom: 20px; }}
.card {{
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 22px 24px;
    backdrop-filter: blur(12px);
    transition: border-color .2s;
}}
.card:hover {{ border-color: rgba(79,172,254,0.25); }}
.card-title {{ font-size: 11px; font-weight: 600; letter-spacing: 1px; color: var(--dim); text-transform: uppercase; margin-bottom: 14px; }}
.stat-val {{ font-size: 32px; font-weight: 800; letter-spacing: -1px; line-height: 1; }}
.stat-sub {{ font-size: 12px; color: var(--dim); margin-top: 6px; }}
.pos {{ color: var(--green); }}
.neg {{ color: var(--red); }}
.dim {{ color: var(--dim); }}
.small {{ font-size: 11px; }}
.center {{ text-align: center; }}
.right  {{ text-align: right; }}
.badge {{ display: inline-flex; align-items: center; gap: 6px; padding: 4px 12px; border-radius: 100px; font-size: 12px; font-weight: 600; }}
.badge-green {{ background: rgba(34,197,94,.15); color: var(--green); border: 1px solid rgba(34,197,94,.3); }}
.badge-red   {{ background: rgba(239,68,68,.15);  color: var(--red);   border: 1px solid rgba(239,68,68,.3); }}
.badge-gray  {{ background: rgba(107,114,128,.15); color: var(--dim);  border: 1px solid rgba(107,114,128,.3); }}
.buy-card {{ margin-top: 10px; }}
.buy-name {{ font-size: 18px; font-weight: 700; }}
.buy-meta {{ display: flex; gap: 12px; margin-top: 6px; font-size: 13px; color: var(--dim); }}
.buy-meta span {{ color: var(--text); }}
.no-trade {{ font-size: 14px; color: var(--dim); padding: 12px 0; }}
.no-trade.warn {{ color: var(--red); }}
.pnl-val {{ font-size: 28px; font-weight: 800; margin-top: 8px; }}
.pnl-pct {{ font-size: 14px; margin-top: 4px; }}
.pnl-sub {{ font-size: 12px; }}
.kosdaq-row {{ display: flex; align-items: center; gap: 20px; flex-wrap: wrap; margin-top: 8px; }}
.kosdaq-val {{ font-size: 22px; font-weight: 700; font-family: 'JetBrains Mono', monospace; }}
.kosdaq-arrow {{ color: var(--dim); font-size: 18px; }}
.kosdaq-gap {{ font-size: 18px; font-weight: 700; font-family: 'JetBrains Mono', monospace; margin-left: auto; text-align: right; }}
.guard-row {{ display: flex; gap: 10px; flex-wrap: wrap; margin-top: 12px; }}
.guard-item {{ display: flex; flex-direction: column; align-items: center; gap: 4px; }}
.dot {{ width: 28px; height: 28px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 13px; font-weight: 700; }}
.dot-green {{ background: rgba(34,197,94,.2); color: var(--green); }}
.dot-red   {{ background: rgba(239,68,68,.2);  color: var(--red);   }}
.dot-gray  {{ background: rgba(107,114,128,.2); color: var(--dim);  }}
.risk-ok      {{ padding: 12px 16px; border-radius: 10px; background: rgba(34,197,94,.1); border: 1px solid rgba(34,197,94,.2); font-size: 14px; color: var(--green); }}
.risk-caution {{ padding: 12px 16px; border-radius: 10px; background: rgba(245,158,11,.1); border: 1px solid rgba(245,158,11,.2); font-size: 14px; color: var(--yellow); }}
.risk-warn    {{ padding: 12px 16px; border-radius: 10px; background: rgba(239,68,68,.1);  border: 1px solid rgba(239,68,68,.2);  font-size: 14px; color: var(--red); }}
.funnel {{ display: flex; align-items: center; gap: 12px; margin-top: 12px; flex-wrap: wrap; }}
.funnel-item {{ text-align: center; }}
.funnel-num {{ font-size: 28px; font-weight: 800; font-family: 'JetBrains Mono', monospace; }}
.funnel-label {{ font-size: 11px; color: var(--dim); margin-top: 2px; }}
.funnel-arrow {{ font-size: 20px; color: var(--dim); }}
.capital-bar-wrap {{ margin-top: 14px; }}
.capital-label {{ display: flex; justify-content: space-between; font-size: 12px; color: var(--dim); margin-bottom: 6px; }}
.capital-bar {{ height: 8px; background: rgba(255,255,255,.08); border-radius: 4px; overflow: hidden; }}
.capital-fill {{ height: 100%; border-radius: 4px; background: linear-gradient(90deg, var(--blue), #00f2fe); transition: width .5s; }}
section-title {{ font-size: 13px; font-weight: 600; color: var(--dim); margin: 28px 0 12px; letter-spacing: 0.5px; }}
.section-title {{ font-size: 13px; font-weight: 600; color: var(--dim); margin: 28px 0 12px; letter-spacing: 0.5px; text-transform: uppercase; }}
table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
th {{ font-size: 11px; color: var(--dim); font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; padding: 10px 14px; border-bottom: 1px solid var(--border); text-align: left; }}
td {{ padding: 13px 14px; border-bottom: 1px solid rgba(255,255,255,.04); }}
tr:last-child td {{ border-bottom: none; }}
tr:hover td {{ background: rgba(255,255,255,.025); }}
.no-buy-row td {{ color: var(--dim); font-style: italic; }}
.win-bar {{ display: flex; gap: 2px; margin-top: 10px; }}
.win-seg {{ height: 6px; flex: 1; border-radius: 2px; }}
@media(max-width:768px) {{
    .grid-3,.grid-4 {{ grid-template-columns: 1fr 1fr; }}
    .grid-2 {{ grid-template-columns: 1fr; }}
}}
</style>
</head>
<body>
<div class="container">

  <header>
    <div class="logo">TOSS <span>AutoTrader</span> 대시보드</div>
    <div class="generated">최종 업데이트: {d['generated_at']}</div>
  </header>

  <!-- ① 오늘 현황 -->
  <div class="section-title">📊 오늘 현황</div>
  <div class="grid-3">
    <div class="card">
      <div class="card-title">시장 가드</div>
      {guard_badge}
      <div class="stat-sub" style="margin-top:10px">{kosdaq_html}</div>
    </div>
    <div class="card">
      <div class="card-title">매수 종목</div>
      {buy_html}
    </div>
    <div class="card">
      <div class="card-title">당일 손익 <span class="dim" style="font-size:10px">(추정·종가 기준)</span></div>
      {pnl_html}
    </div>
  </div>

  <!-- ② 누적 성과 -->
  <div class="section-title">📈 누적 성과</div>
  <div class="grid-4">
    <div class="card">
      <div class="card-title">총 거래</div>
      <div class="stat-val">{s['total_trades']}<span style="font-size:16px;color:var(--dim)">회</span></div>
      <div class="stat-sub">{s['wins']}승 {s['losses']}패</div>
    </div>
    <div class="card">
      <div class="card-title">승률</div>
      <div class="stat-val {'pos' if s['win_rate'] >= 50 else 'neg'}">{s['win_rate']}<span style="font-size:16px">%</span></div>
      <div class="win-bar">
        {'<div class="win-seg" style="background:var(--green)"></div>' * s['wins']}{'<div class="win-seg" style="background:var(--red)"></div>' * s['losses']}
      </div>
    </div>
    <div class="card">
      <div class="card-title">누적 수익</div>
      <div class="stat-val {cum_cls}">{cum_sign}{cum_pnl:,}<span style="font-size:14px">원</span></div>
      <div class="stat-sub {cum_cls}">{cum_sign}{s['cumulative_pct']}% (원금 {INITIAL_CAPITAL:,}원 기준)</div>
    </div>
    <div class="card">
      <div class="card-title">최대 낙폭 (MDD)</div>
      <div class="stat-val neg">-{s['max_drawdown']:,}<span style="font-size:14px">원</span></div>
      <div class="stat-sub">원금 대비 -{round(s['max_drawdown']/INITIAL_CAPITAL*100,1)}%</div>
    </div>
  </div>

  <!-- ③ 시장 & 리스크 -->
  <div class="section-title">⚠️ 리스크 모니터링</div>
  <div class="grid-2">
    <div class="card">
      <div class="card-title">최근 7일 가드 이력</div>
      <div class="guard-row">{guard_hist_html if guard_hist_html else '<span class="dim small">데이터 없음</span>'}</div>
    </div>
    <div class="card">
      <div class="card-title">연속 손실 & 잔액</div>
      {risk_html}
      <div class="capital-bar-wrap">
        <div class="capital-label">
          <span>원금 대비 잔액</span>
          <span class="{cum_cls}">{INITIAL_CAPITAL + cum_pnl:,}원</span>
        </div>
        <div class="capital-bar">
          <div class="capital-fill" style="width:{min(100,max(0,(INITIAL_CAPITAL+cum_pnl)/INITIAL_CAPITAL*100)):.1f}%"></div>
        </div>
      </div>
    </div>
  </div>

  <!-- ④ 오늘 스캔 퍼널 -->
  <div class="section-title">🔍 오늘 스캔 퍼널</div>
  <div class="card" style="margin-bottom:20px">
    {funnel_html}
  </div>

  <!-- ⑤ 거래 내역 -->
  <div class="section-title">📋 거래 내역</div>
  <div class="card">
    <table>
      <thead>
        <tr>
          <th>날짜</th><th>종목</th><th class="right">매수가</th>
          <th class="right">매도가(추정)</th><th class="right">수량</th>
          <th class="right">손익</th><th class="right">수익률</th>
        </tr>
      </thead>
      <tbody>{rows}</tbody>
    </table>
  </div>

</div>
</body>
</html>"""
    return html


# ──────────────────────────────────────────────
# 메인
# ──────────────────────────────────────────────

if __name__ == "__main__":
    print("📊 데이터 수집 중...")
    data = build_data()
    print(f"   거래 세션: {len(data['trades'])}개, 실거래: {data['stats']['total_trades']}회")
    html = render(data)
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(html, encoding="utf-8")
    print(f"✅ 대시보드 생성: {OUT}")
    webbrowser.open(f"file://{OUT}")
