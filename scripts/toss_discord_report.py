#!/usr/bin/env python3
"""Deterministic Discord reports for simple_gap_trader macOS cron.

No LLM/agent loop. This script is intended for macOS crontab:
- read local buy/sell logs
- fetch KOSDAQ close when requested
- run Toss candle updater when requested
- send a concise Korean Markdown report through `hermes send`

Keep the Discord target out of git: pass `--to discord:<channel_id>` from crontab
or set TOSS_DISCORD_TARGET locally.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from toss_auto_trader.config import Settings
from toss_auto_trader.toss_client import TossApiError, TossInvestClient

BUY_LOG = ROOT / "logs" / "simple_gap_trader_buy.log"
SELL_LOG = ROOT / "logs" / "simple_gap_trader_sell.log"
REPORT_LOG = ROOT / "logs" / "toss_discord_report.log"
DB_PATH = ROOT / "data" / "edge_research_universe_15y.sqlite3"
DEFAULT_TARGET_ENV = "TOSS_DISCORD_TARGET"


def today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def tail_lines(path: Path, n: int = 60) -> list[str]:
    if not path.exists():
        return []
    return path.read_text(encoding="utf-8", errors="replace").splitlines()[-n:]


def split_sessions(path: Path) -> list[list[str]]:
    if not path.exists():
        return []
    sessions: list[list[str]] = []
    cur: list[str] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("실행 시간:"):
            if cur:
                sessions.append(cur)
            cur = [line]
        elif cur:
            cur.append(line)
    if cur:
        sessions.append(cur)
    return sessions


def latest_session_for_date(path: Path, date: str | None = None, *, fallback_latest: bool = False) -> list[str]:
    date = date or today()
    sessions = split_sessions(path)
    for sess in reversed(sessions):
        if sess and date in sess[0]:
            return sess
    return sessions[-1] if (fallback_latest and sessions) else []


def clean_int(raw: str | None) -> int | None:
    if raw is None:
        return None
    digits = str(raw).replace(",", "").strip()
    try:
        return int(float(digits))
    except ValueError:
        return None


def clean_float(raw: str | None) -> float | None:
    if raw is None:
        return None
    try:
        return float(str(raw).replace(",", "").strip())
    except ValueError:
        return None


def money(value: int | float | None) -> str:
    if value is None:
        return "확인 필요"
    return f"{value:,.0f}원"


def pct(value: float | None, digits: int = 2) -> str:
    if value is None:
        return "확인 필요"
    return f"{value:+.{digits}f}%"


def decimal_value(raw: Any) -> Decimal | None:
    if raw is None:
        return None
    text = str(raw).replace(",", "").strip()
    if not text:
        return None
    try:
        return Decimal(text)
    except (InvalidOperation, ValueError):
        return None


def money_decimal(value: Decimal | int | float | None) -> str:
    if value is None:
        return "확인 필요"
    try:
        dec = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError):
        return "확인 필요"
    return f"{dec:,.0f}원"


def qty_decimal(value: Decimal | int | float | None) -> str:
    if value is None:
        return "확인 필요"
    try:
        dec = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError):
        return "확인 필요"
    if dec == dec.to_integral_value():
        return f"{dec:,.0f}주"
    return f"{dec.normalize()}주"


def unwrap_result(resp: dict[str, Any]) -> dict[str, Any]:
    result = resp.get("result")
    return result if isinstance(result, dict) else resp


def order_execution(order_resp: dict[str, Any] | None) -> dict[str, Any] | None:
    if not order_resp:
        return None
    order = unwrap_result(order_resp)
    execution = order.get("execution") or {}
    if not isinstance(execution, dict):
        execution = {}
    return {
        "order_id": order.get("orderId"),
        "symbol": order.get("symbol"),
        "side": order.get("side"),
        "status": order.get("status"),
        "ordered_at": order.get("orderedAt"),
        "quantity": decimal_value(order.get("quantity")),
        "filled_quantity": decimal_value(execution.get("filledQuantity")),
        "average_filled_price": decimal_value(execution.get("averageFilledPrice")),
        "filled_amount": decimal_value(execution.get("filledAmount")),
        "commission": decimal_value(execution.get("commission")),
        "tax": decimal_value(execution.get("tax")),
        "filled_at": execution.get("filledAt"),
        "settlement_date": execution.get("settlementDate"),
    }


def build_toss_client() -> TossInvestClient:
    settings = Settings.from_env(str(ROOT / ".env"))
    return TossInvestClient(settings)


def fetch_order_details(order_ids: list[str]) -> dict[str, dict[str, Any]]:
    """Fetch official Toss order detail for order IDs.

    Read-only. Returns per-order records with either {ok, raw, execution} or {ok=False, error}.
    """
    result: dict[str, dict[str, Any]] = {}
    unique_order_ids = [oid for i, oid in enumerate(order_ids) if oid and oid not in order_ids[:i]]
    if not unique_order_ids:
        return result
    try:
        client = build_toss_client()
    except Exception as e:
        return {oid: {"ok": False, "error": f"client-init {type(e).__name__}: {e}"} for oid in unique_order_ids}
    for oid in unique_order_ids:
        try:
            raw = client.get_order(oid)
            result[oid] = {"ok": True, "raw": raw, "execution": order_execution(raw)}
        except TossApiError as e:
            result[oid] = {"ok": False, "error": f"TossApiError {e.status}: {e}"}
        except Exception as e:
            result[oid] = {"ok": False, "error": f"{type(e).__name__}: {e}"}
    return result


def execution_lines(label: str, detail: dict[str, Any] | None) -> list[str]:
    if not detail:
        return [f"  - {label} 실제 체결: 상세조회 없음"]
    if not detail.get("ok"):
        return [f"  - {label} 실제 체결: 상세조회 실패 ({detail.get('error')})"]
    ex = detail.get("execution") or {}
    status = ex.get("status") or "확인 필요"
    filled_qty = ex.get("filled_quantity")
    avg_price = ex.get("average_filled_price")
    filled_amount = ex.get("filled_amount")
    commission = ex.get("commission")
    tax = ex.get("tax")
    filled_at = ex.get("filled_at") or "확인 필요"
    settlement = ex.get("settlement_date") or "확인 필요"
    lines = [
        f"  - {label} 실제 체결: {status} / {qty_decimal(filled_qty)} @ {money_decimal(avg_price)} / 체결금액 {money_decimal(filled_amount)}",
        f"    수수료 {money_decimal(commission)} / 세금 {money_decimal(tax)} / 체결시각 {filled_at} / 결제예정 {settlement}",
    ]
    if filled_qty is not None and ex.get("quantity") is not None and filled_qty < ex["quantity"]:
        lines.append(f"    주의: 주문수량 {qty_decimal(ex.get('quantity'))} 중 부분체결")
    return lines


def realized_pnl_from_details(buy_detail: dict[str, Any] | None, sell_detail: dict[str, Any] | None) -> tuple[Decimal, Decimal] | None:
    if not buy_detail or not sell_detail or not buy_detail.get("ok") or not sell_detail.get("ok"):
        return None
    b = buy_detail.get("execution") or {}
    s = sell_detail.get("execution") or {}
    buy_amount = b.get("filled_amount")
    sell_amount = s.get("filled_amount")
    if buy_amount is None or sell_amount is None or buy_amount <= 0:
        return None
    buy_cost = buy_amount + (b.get("commission") or Decimal("0")) + (b.get("tax") or Decimal("0"))
    sell_net = sell_amount - (s.get("commission") or Decimal("0")) - (s.get("tax") or Decimal("0"))
    pnl = sell_net - buy_cost
    ret = (pnl / buy_cost) * Decimal("100")
    return pnl, ret


def pct_decimal(value: Decimal | None, digits: int = 2) -> str:
    if value is None:
        return "확인 필요"
    return f"{value:+.{digits}f}%"


def parse_buy_session(lines: list[str]) -> dict[str, Any]:
    info: dict[str, Any] = {
        "datetime": None,
        "mode": None,
        "kosdaq": None,
        "sma5": None,
        "guard": None,
        "latest_db_date": None,
        "scan_total": None,
        "actual_cash": None,
        "budget": None,
        "gap_count": None,
        "candidates": [],
        "order": None,
        "order_success": None,
        "order_id": None,
        "reason": None,
        "raw_tail": lines[-12:],
    }
    for line in lines:
        m = re.search(r"실행 시간: (.+)", line)
        if m:
            info["datetime"] = m.group(1).strip()
        m = re.search(r"모드: (.+)", line)
        if m:
            info["mode"] = m.group(1).strip()
        m = re.search(r"현재 KOSDAQ 지수: ([\d.]+) \| 5일 이평선: ([\d.]+)", line)
        if m:
            info["kosdaq"] = clean_float(m.group(1))
            info["sma5"] = clean_float(m.group(2))
        if "시장 하락 가드 발동" in line:
            info["guard"] = "차단"
            info["reason"] = "KOSDAQ 지수가 5일선 아래라 시장 가드 차단"
        if "지수 가드 통과" in line:
            info["guard"] = "통과"
        m = re.search(r"최근 데이터 영업일: (\d{4}-\d{2}-\d{2})", line)
        if m:
            info["latest_db_date"] = m.group(1)
        m = re.search(r"로컬 스크리닝 필터 통과 종목 수: (\d+)개", line)
        if m:
            info["scan_total"] = int(m.group(1))
        m = re.search(r"실제 예수금: ([\d,]+)원 \| 이번 매수 사용 예산: ([\d,]+)원", line)
        if m:
            info["actual_cash"] = clean_int(m.group(1))
            info["budget"] = clean_int(m.group(2))
        m = re.search(r"예수금\(([\d,]+)원\).*매수 불가", line)
        if m:
            info["reason"] = f"예수금 {m.group(1)}원으로 최소 주가 미달"
        m = re.search(r"갭 하락 3% 돌파 종목 수: (\d+)개", line)
        if m:
            info["gap_count"] = int(m.group(1))
        if "매수 진입 조건을 통과한 최종 종목이 없습니다" in line:
            info["reason"] = "갭하락 -3% + 전일 거래량 필터 통과 종목 없음"
        m = re.search(r"\[(\w+)\] (.+?) \| 갭률: ([-\d.]+)% \| 시가: ([\d,]+)원 \| 현재가: ([\d,]+)원 \| 전일종가: ([\d,]+)원", line)
        if m and len(info["candidates"]) < 5:
            info["candidates"].append(
                {
                    "symbol": m.group(1),
                    "name": m.group(2),
                    "gap_pct": clean_float(m.group(3)),
                    "open_price": clean_int(m.group(4)),
                    "last_price": clean_int(m.group(5)),
                    "prev_close": clean_int(m.group(6)),
                }
            )
        m = re.search(r"\[(.+?)\] (\d+)주 매수 주문 발송 \(배정금액 ([\d,]+)원, 예상단가 ([\d,]+)원\)", line)
        if m:
            info["order"] = {
                "name": m.group(1),
                "qty": int(m.group(2)),
                "amount": clean_int(m.group(3)),
                "expected_price": clean_int(m.group(4)),
            }
        m = re.search(r"주문 성공! 주문ID: (.+)", line)
        if m:
            info["order_success"] = True
            info["order_id"] = m.group(1).strip()
        if "매수 주문 실패" in line or "시스템 에러" in line:
            info["order_success"] = False
            info["reason"] = line.strip()
    if info["order"] and info["reason"] is None:
        info["reason"] = "KOSDAQ 가드 통과 + 전일 종가 5천~5만원 + 전일 거래량<20일 평균 + 당일 시가 갭하락 -3% 이하 중 최상위"
    return info


def parse_sell_session(lines: list[str]) -> dict[str, Any]:
    info: dict[str, Any] = {
        "datetime": None,
        "mode": None,
        "no_holdings": False,
        "holding_count": None,
        "orders": [],
        "raw_tail": lines[-12:],
    }
    current_order: dict[str, Any] | None = None
    for line in lines:
        m = re.search(r"실행 시간: (.+)", line)
        if m:
            info["datetime"] = m.group(1).strip()
        m = re.search(r"모드: (.+)", line)
        if m:
            info["mode"] = m.group(1).strip()
        if "현재 보유 중인 종목이 없습니다" in line:
            info["no_holdings"] = True
        m = re.search(r"현재 보유 종목 수: (\d+)개", line)
        if m:
            info["holding_count"] = int(m.group(1))
        m = re.search(r"\[(.+?)\] (\d+)주 매도 주문 발송 \(예상단가 ([\d,]+)원, 예상금액 ([\d,]+)원\)", line)
        if m:
            current_order = {
                "name": m.group(1),
                "qty": int(m.group(2)),
                "expected_price": clean_int(m.group(3)),
                "expected_amount": clean_int(m.group(4)),
                "success": None,
                "order_id": None,
            }
            info["orders"].append(current_order)
            continue
        m = re.search(r"\[(.+?)\] (\d+)주 매도 주문 발송", line)
        if m:
            current_order = {
                "name": m.group(1),
                "qty": int(m.group(2)),
                "expected_price": None,
                "expected_amount": None,
                "success": None,
                "order_id": None,
            }
            info["orders"].append(current_order)
            continue
        m = re.search(r"매도 주문 성공! 주문ID: (.+)", line)
        if m and current_order is not None:
            current_order["success"] = True
            current_order["order_id"] = m.group(1).strip()
        if "매도 주문 실패" in line or "매도 에러" in line:
            if current_order is not None:
                current_order["success"] = False
                current_order["error"] = line.strip()
    return info


def buy_report(date: str | None = None) -> str:
    date = date or today()
    sess = latest_session_for_date(BUY_LOG, date)
    if not sess:
        return f"[Toss 자동매매] {date} 09:01 매수 로그 없음\n- 로그 파일: {BUY_LOG}"
    b = parse_buy_session(sess)
    order_id = b.get("order_id")
    order_details = fetch_order_details([order_id]) if isinstance(order_id, str) and order_id else {}
    lines = [
        f"[Toss 자동매매] {date} 09:01 매수 보고",
        f"- 실행: {b.get('datetime') or '확인 필요'} / {b.get('mode') or '모드 확인 필요'}",
        f"- KOSDAQ: {b.get('kosdaq') if b.get('kosdaq') is not None else '확인 필요'} / SMA5: {b.get('sma5') if b.get('sma5') is not None else '확인 필요'} / 가드: {b.get('guard') or '확인 필요'}",
        f"- DB 기준일: {b.get('latest_db_date') or '확인 필요'} / 스크리닝: {b.get('scan_total') if b.get('scan_total') is not None else '확인 필요'}개 / 갭 후보: {b.get('gap_count') if b.get('gap_count') is not None else '확인 필요'}개",
        f"- 예수금: {money(b.get('actual_cash'))} / 사용예산: {money(b.get('budget'))}",
    ]
    if b.get("candidates"):
        lines.append("- 상위 후보:")
        for c in b["candidates"][:5]:
            lines.append(f"  - {c['name']}({c['symbol']}): 갭 {pct(c['gap_pct'])}, 시가 {money(c['open_price'])}, 현재 {money(c['last_price'])}, 전일종가 {money(c['prev_close'])}")
    order = b.get("order")
    if order:
        status = "성공" if b.get("order_success") else "실패/확인 필요"
        lines += [
            f"- 매수: {status}",
            f"  - 종목: {order['name']}",
            f"  - 수량/예상단가/배정: {order['qty']}주 / {money(order['expected_price'])} / {money(order['amount'])}",
            f"  - 주문ID: {b.get('order_id') or '확인 필요'}",
            f"  - 매수 이유: {b.get('reason')}",
        ]
        lines.extend(execution_lines("매수", order_details.get(order_id) if isinstance(order_id, str) else None))
    else:
        lines.append(f"- 매수: 없음")
        lines.append(f"- 이유: {b.get('reason') or '조건 미충족 또는 로그 추가 확인 필요'}")
    return "\n".join(lines)


def estimate_buy_from_log(date: str) -> dict[str, Any] | None:
    sess = latest_session_for_date(BUY_LOG, date)
    if not sess:
        return None
    return parse_buy_session(sess)


def sell_report(date: str | None = None) -> str:
    date = date or today()
    sess = latest_session_for_date(SELL_LOG, date)
    buy = estimate_buy_from_log(date)
    if not sess:
        return f"[Toss 자동매매] {date} 15:20 매도 로그 없음\n- 로그 파일: {SELL_LOG}"
    s = parse_sell_session(sess)

    buy_order_id = buy.get("order_id") if buy else None
    sell_order_ids = [o.get("order_id") for o in s.get("orders", []) if isinstance(o.get("order_id"), str) and o.get("order_id")]
    detail_ids = []
    if isinstance(buy_order_id, str) and buy_order_id:
        detail_ids.append(buy_order_id)
    detail_ids.extend(str(oid) for oid in sell_order_ids)
    order_details = fetch_order_details(detail_ids)

    lines = [
        f"[Toss 자동매매] {date} 15:20 매도/당일 결과 보고",
        f"- 실행: {s.get('datetime') or '확인 필요'} / {s.get('mode') or '모드 확인 필요'}",
    ]
    if buy and buy.get("order"):
        bo = buy["order"]
        lines.append(f"- 오전 매수: {bo['name']} {bo['qty']}주 @ {money(bo['expected_price'])}, 배정 {money(bo['amount'])}, 주문ID {buy_order_id or '확인 필요'}")
        lines.extend(execution_lines("매수", order_details.get(buy_order_id) if isinstance(buy_order_id, str) else None))
    elif buy:
        lines.append(f"- 오전 매수: 없음 / 이유: {buy.get('reason') or '조건 미충족'}")
    else:
        lines.append("- 오전 매수: 로그 없음")
    if s.get("no_holdings"):
        lines.append("- 매도: 보유 종목 없음 → 매도 없음")
        lines.append("- 오늘 결과: 미거래 또는 오전 체결 없음")
        return "\n".join(lines)
    if s.get("orders"):
        lines.append("- 매도 주문:")
        for o in s["orders"]:
            status = "성공" if o.get("success") else "실패/확인 필요"
            order_id = o.get("order_id")
            lines.append(f"  - {o['name']} {o['qty']}주 / 예상단가 {money(o.get('expected_price'))} / 예상금액 {money(o.get('expected_amount'))} / {status} / 주문ID {order_id or '확인 필요'}")
            lines.extend(execution_lines("매도", order_details.get(order_id) if isinstance(order_id, str) else None))
        actual = None
        if isinstance(buy_order_id, str) and s["orders"]:
            first_sell_id = s["orders"][0].get("order_id")
            actual = realized_pnl_from_details(order_details.get(buy_order_id), order_details.get(first_sell_id) if isinstance(first_sell_id, str) else None)
        if actual:
            pnl, ret = actual
            lines.append(f"- 실제 당일 손익: {money_decimal(pnl)} ({pct_decimal(ret)}) — 체결금액/수수료/세금 반영")
        elif buy and buy.get("order") and s["orders"]:
            bo = buy["order"]
            first_sell = s["orders"][0]
            if first_sell.get("expected_price") and bo.get("expected_price"):
                pnl = (first_sell["expected_price"] - bo["expected_price"]) * min(int(bo["qty"]), int(first_sell["qty"]))
                ret = (first_sell["expected_price"] - bo["expected_price"]) / bo["expected_price"] * 100
                lines.append(f"- 추정 당일 손익: {money(pnl)} ({pct(ret)}) — 실제 체결 상세조회 실패/미체결 시 fallback")
            else:
                lines.append("- 당일 손익: 실제 체결가/예상가 확인 필요")
    else:
        lines.append("- 매도: 주문 로그 없음 / 잔고 조회 또는 API 결과 확인 필요")
    return "\n".join(lines)


def fetch_kosdaq_close() -> dict[str, Any]:
    today_str = datetime.now().strftime("%Y%m%d")
    q = urllib.parse.urlencode({"startDateTime": "202601010000", "endDateTime": f"{today_str}2359"})
    url = f"https://api.stock.naver.com/chart/domestic/index/KOSDAQ/day?{q}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://finance.naver.com/"})
    with urllib.request.urlopen(req, timeout=15) as r:
        data = json.loads(r.read().decode("utf-8"))
    closes = [float(str(row["closePrice"]).replace(",", "")) for row in data]
    row = data[-1]
    return {
        "date": row["localDate"],
        "close": float(str(row["closePrice"]).replace(",", "")),
        "open": float(str(row.get("openPrice", "0")).replace(",", "")),
        "sma5": sum(closes[-5:]) / 5,
        "guard": closes[-1] >= sum(closes[-5:]) / 5,
        "rows": len(data),
    }


def kosdaq_close_report() -> str:
    try:
        k = fetch_kosdaq_close()
        return "\n".join(
            [
                "[Toss 자동매매] KOSDAQ 종가 기록",
                f"- 날짜: {k['date']}",
                f"- 종가: {k['close']:,.2f}",
                f"- 시가: {k['open']:,.2f}",
                f"- 5일 이평선: {k['sma5']:,.2f}",
                f"- 내일 가드 기준: {'통과 기준 위' if k['guard'] else '차단 기준 아래'}",
                "- 09:01 로그의 KOSDAQ 값과 비교할 기준값으로 기록",
            ]
        )
    except Exception as e:
        return f"[Toss 자동매매] KOSDAQ 종가 기록 실패\n- 오류: {type(e).__name__}: {e}"


def db_summary() -> dict[str, Any]:
    if not DB_PATH.exists():
        return {"exists": False}
    con = sqlite3.connect(f"file:{DB_PATH.resolve()}?mode=ro", uri=True)
    try:
        cur = con.cursor()
        cur.execute("SELECT COUNT(*), COUNT(DISTINCT symbol), MAX(substr(timestamp,1,10)) FROM candle_cache")
        rows, symbols, latest = cur.fetchone()
        cur.execute("SELECT COUNT(*) FROM candle_cache WHERE substr(timestamp,1,10)=?", (latest,))
        latest_rows = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM candle_cache WHERE timestamp LIKE '%.000+09:00'")
        bad = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM candle_cache WHERE raw_json LIKE '%\"source\": \"toss\"%' AND substr(timestamp,1,10)=?", (latest,))
        toss_latest = cur.fetchone()[0]
        return {
            "exists": True,
            "rows": rows,
            "symbols": symbols,
            "latest_date": latest,
            "latest_date_rows": latest_rows,
            "latest_toss_rows": toss_latest,
            "bad_timestamp_rows": bad,
        }
    finally:
        con.close()


def run_candle_update(*, dry_run: bool = False, limit: int = 0) -> tuple[int, str, str]:
    cmd = [sys.executable, "scripts/cache_toss_candles_daily.py"]
    if dry_run:
        cmd.append("--dry-run")
    if limit > 0:
        cmd.extend(["--limit", str(limit)])
    proc = subprocess.run(cmd, cwd=str(ROOT), text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=1800)
    return proc.returncode, proc.stdout, proc.stderr


def extract_last_json(text: str) -> dict[str, Any] | None:
    idx = text.rfind("{")
    while idx >= 0:
        try:
            return json.loads(text[idx:])
        except Exception:
            idx = text.rfind("{", 0, idx)
    return None


def candle_update_report(*, dry_run: bool = False, limit: int = 0) -> str:
    before = db_summary()
    code, stdout, stderr = run_candle_update(dry_run=dry_run, limit=limit)
    after = db_summary()
    parsed = extract_last_json(stdout)
    mode = "DRY-RUN 검증" if dry_run else "실제 업데이트"
    lines = [
        f"[Toss 자동매매] 15:40 캔들 DB 업데이트 보고 ({mode})",
        f"- 실행 결과: {'성공' if code == 0 else '실패'} (exit={code})",
        f"- DB before: latest={before.get('latest_date')} rows={before.get('rows'):,} latest_rows={before.get('latest_date_rows'):,}" if before.get("exists") else "- DB before: 없음",
        f"- DB after: latest={after.get('latest_date')} rows={after.get('rows'):,} latest_rows={after.get('latest_date_rows'):,} toss_latest={after.get('latest_toss_rows'):,} bad_ts={after.get('bad_timestamp_rows'):,}" if after.get("exists") else "- DB after: 없음",
    ]
    if parsed:
        lines += [
            f"- 종목 처리: ok={parsed.get('ok_symbols')} failed={parsed.get('failed_symbols')}",
            f"- candles fetched/replaced: {parsed.get('total_fetched')} / {parsed.get('total_inserted_or_replaced')}",
            f"- latest 분포: {parsed.get('latest_distribution_tail')}",
        ]
        if parsed.get("errors_tail"):
            lines.append(f"- 오류 샘플: {parsed.get('errors_tail')}")
    else:
        lines.append("- updater JSON 파싱 실패: stdout tail 확인 필요")
    if stderr.strip():
        lines.append("- stderr tail:\n```\n" + "\n".join(stderr.splitlines()[-8:])[:1500] + "\n```")
    return "\n".join(lines)


def status_report() -> str:
    return "\n".join(
        [
            "[Toss 자동매매] Discord 보고 설정 테스트",
            f"- 시간: {now_text()}",
            "- macOS crontab에서 주문/보고/종가/DB 업데이트를 직접 실행하도록 구성됨",
            "- 이 메시지가 보이면 hermes send → finance-chat 전송 경로 정상",
        ]
    )


def send_message(message: str, target: str, *, print_only: bool = False) -> None:
    if print_only:
        print(message)
        return
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, suffix=".md") as f:
        f.write(message)
        path = f.name
    hermes_bin = os.getenv("HERMES_BIN") or shutil.which("hermes") or str(Path.home() / ".local" / "bin" / "hermes")
    try:
        subprocess.run([hermes_bin, "send", "--quiet", "--to", target, "--file", path], check=True, cwd=str(ROOT), timeout=60)
    finally:
        try:
            Path(path).unlink()
        except FileNotFoundError:
            pass


def build_message(action: str, date: str | None = None, *, dry_run_update: bool = False, update_limit: int = 0) -> str:
    if action == "buy-report":
        return buy_report(date)
    if action == "sell-report":
        return sell_report(date)
    if action == "kosdaq-close":
        return kosdaq_close_report()
    if action == "candle-update":
        return candle_update_report(dry_run=dry_run_update, limit=update_limit)
    if action == "status-test":
        return status_report()
    raise ValueError(f"unknown action: {action}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Send Toss auto trader reports to Discord")
    ap.add_argument("--action", required=True, choices=["buy-report", "sell-report", "kosdaq-close", "candle-update", "status-test"])
    ap.add_argument("--to", default=os.getenv(DEFAULT_TARGET_ENV, ""), help="e.g. discord:1234567890; or set TOSS_DISCORD_TARGET")
    ap.add_argument("--date", default="", help="YYYY-MM-DD, defaults to today")
    ap.add_argument("--print-only", action="store_true", help="Do not send; print report")
    ap.add_argument("--dry-run-update", action="store_true", help="For --action candle-update, fetch/report without writing DB")
    ap.add_argument("--update-limit", type=int, default=0, help="For --action candle-update smoke tests; 0 means all symbols")
    args = ap.parse_args()
    if not args.to and not args.print_only:
        print(f"Missing --to or {DEFAULT_TARGET_ENV}", file=sys.stderr)
        return 2
    REPORT_LOG.parent.mkdir(exist_ok=True)
    try:
        msg = build_message(args.action, args.date or None, dry_run_update=args.dry_run_update, update_limit=args.update_limit)
        send_message(msg, args.to, print_only=args.print_only)
        with REPORT_LOG.open("a", encoding="utf-8") as f:
            f.write(f"{now_text()} action={args.action} status=ok\n")
        return 0
    except Exception as e:
        err = f"[Toss 자동매매] 보고 스크립트 실패\n- action: {args.action}\n- 오류: {type(e).__name__}: {e}"
        if args.to and not args.print_only:
            try:
                send_message(err, args.to, print_only=False)
            except Exception:
                pass
        print(err, file=sys.stderr)
        with REPORT_LOG.open("a", encoding="utf-8") as f:
            f.write(f"{now_text()} action={args.action} status=error error={type(e).__name__}: {e}\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
