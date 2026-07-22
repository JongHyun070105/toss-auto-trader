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
from toss_auto_trader import breadth_shadow
from toss_auto_trader.toss_client import TossApiError, TossInvestClient

BUY_LOG = ROOT / "logs" / "simple_gap_trader_buy.log"
MONITOR_LOG = ROOT / "logs" / "simple_gap_trader_monitor.log"
SELL_LOG = ROOT / "logs" / "simple_gap_trader_sell.log"
REPORT_LOG = ROOT / "logs" / "toss_discord_report.log"
BREADTH_SHADOW_LOG = ROOT / "logs" / "simple_gap_breadth_shadow.jsonl"
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


def normalize_order_id(raw: Any) -> str | None:
    if raw is None:
        return None
    value = str(raw).strip()
    if not value or value.lower() in {"none", "null"} or value == "확인 필요":
        return None
    return value


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
    clean_order_ids = [oid for oid in (normalize_order_id(raw) for raw in order_ids) if oid is not None]
    unique_order_ids = [oid for i, oid in enumerate(clean_order_ids) if oid not in clean_order_ids[:i]]
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


def order_status_label(acked: bool | None, detail: dict[str, Any] | None) -> str:
    if acked is not True:
        return "실패/미확인"
    if not detail:
        return "주문 접수(체결 상세 없음)"
    if not detail.get("ok"):
        return "주문 접수(상세조회 실패)"
    execution = detail.get("execution") or {}
    status = str(execution.get("status") or "").upper()
    filled = execution.get("filled_quantity") or Decimal("0")
    quantity = execution.get("quantity")
    if status == "FILLED" or (quantity is not None and quantity > 0 and filled >= quantity):
        return "체결 완료"
    if filled > 0:
        return "부분체결"
    if status in {"CANCELED", "REJECTED", "CANCEL_REJECTED", "REPLACE_REJECTED", "REPLACED"}:
        return f"주문 종료({status}, 미체결)"
    return f"주문 접수({status or '상태 미확인'})"


def realized_pnl_from_details(buy_detail: dict[str, Any] | None, sell_detail: dict[str, Any] | None) -> tuple[Decimal, Decimal] | None:
    if not buy_detail or not sell_detail or not buy_detail.get("ok") or not sell_detail.get("ok"):
        return None
    b = buy_detail.get("execution") or {}
    s = sell_detail.get("execution") or {}
    buy_amount = b.get("filled_amount")
    sell_amount = s.get("filled_amount")
    buy_qty = b.get("filled_quantity")
    sell_qty = s.get("filled_quantity")
    if (
        buy_amount is None
        or sell_amount is None
        or buy_amount <= 0
        or buy_qty is None
        or sell_qty is None
        or buy_qty <= 0
        or sell_qty != buy_qty
    ):
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
        "end_datetime": None,
        "total_elapsed_sec": None,
        "mode": None,
        "kosdaq": None,
        "kosdaq_open": None,
        "sma5": None,
        "buy_line": None,
        "market_timestamp": None,
        "market_freshness": None,
        "guard": None,
        "latest_db_date": None,
        "scan_total": None,
        "actual_cash": None,
        "budget": None,
        "gap_count": None,
        "breadth_shadow": None,
        "perf": {},
        "candidates": [],
        "warning_exclusions": [],
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
        m = re.search(r"프로그램 종료: (.+?) / 총 실행시간: ([\d.]+)초", line)
        if m:
            info["end_datetime"] = m.group(1).strip()
            info["total_elapsed_sec"] = clean_float(m.group(2))
        m = re.search(r"모드: (.+)", line)
        if m:
            info["mode"] = m.group(1).strip()
        m = re.search(r"현재 KOSDAQ 지수: ([\d.]+)", line)
        if m:
            info["kosdaq"] = clean_float(m.group(1))
        m = re.search(r"당일 시가: ([\d.]+)", line)
        if m:
            info["kosdaq_open"] = clean_float(m.group(1))
        m = re.search(r"5일 이평선: ([\d.]+)", line)
        if m:
            info["sma5"] = clean_float(m.group(1))
        m = re.search(r"매수 허용선: ([\d.]+)", line)
        if m:
            info["buy_line"] = clean_float(m.group(1))
        m = re.search(r"지수 시각: (\S+)", line)
        if m:
            info["market_timestamp"] = m.group(1)
        m = re.search(r"최신성 검증: (\S+)", line)
        if m:
            info["market_freshness"] = m.group(1)
        if "시장 가드 발동" in line or "시장 하락 가드 발동" in line:
            info["guard"] = "차단"
            info["reason"] = "KOSDAQ이 5일선보다 1% 이상 아래가 아니라 시장 가드 차단"
        if "[시장 가드 차단]" in line:
            info["guard"] = "차단"
            info["reason"] = line.split("]", 1)[-1].strip()
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
        m = re.search(r"갭 하락 [\d.]+% 돌파 종목 수: (\d+)개", line)
        if m:
            info["gap_count"] = int(m.group(1))
        m = re.search(
            r"\[섀도 breadth4\] 09:01 현재가 기준 -5% 갭: (\d+)개 / 기준: (\d+)개 / "
            r"모집단: (\d+)개 / 시세수신: (\d+)개 / 상태: (\w+) / 실매매 미적용",
            line,
        )
        if m:
            info["breadth_shadow"] = {
                "provisional_gap5_count": int(m.group(1)),
                "threshold": int(m.group(2)),
                "reference_symbols": int(m.group(3)),
                "quoted_symbols": int(m.group(4)),
                "status": m.group(5),
                "applied_to_live_order": False,
            }
        m = re.search(r"\[섀도 breadth4\] 미실행: (.+?) / 실매매 미적용", line)
        if m:
            info["breadth_shadow"] = {
                "status": "not_evaluated",
                "reason": m.group(1).strip(),
                "applied_to_live_order": False,
            }
        m = re.search(
            r"성능 측정: .*?price_chunks=(\d+) .*?price_rows=(\d+) .*?provisional_gap_hits=(\d+) .*?daily_open_calls=(\d+) .*?daily_open_missing=(\d+) .*?daily_open_confirmed_hits=(\d+) .*?scan_elapsed=([\d.]+)s",
            line,
        )
        if m:
            info["perf"] = {
                "price_chunks": int(m.group(1)),
                "price_rows": int(m.group(2)),
                "provisional_gap_hits": int(m.group(3)),
                "daily_open_calls": int(m.group(4)),
                "daily_open_missing": int(m.group(5)),
                "daily_open_confirmed_hits": int(m.group(6)),
                "scan_elapsed_sec": clean_float(m.group(7)),
            }
        if "매수 진입 조건을 통과한 최종 종목이 없습니다" in line:
            info["reason"] = "robust 갭하락 + 전일 거래량 필터 통과 종목 없음"
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
        m = re.search(r"\[(\w+)\] (.+?) 매수 유의사항 필터 제외: (.+)", line)
        if m:
            info["warning_exclusions"].append({"symbol": m.group(1), "name": m.group(2), "warnings": m.group(3).strip()})
        m = re.search(r"\[(.+?)\] (\d+)주 (?:지정가 )?매수 주문 발송 \(.*?배정금액 ([\d,]+)원, (?:예상단가|지정가) ([\d,]+)원", line)
        if m:
            info["order"] = {
                "name": m.group(1),
                "qty": int(m.group(2)),
                "amount": clean_int(m.group(3)),
                "expected_price": clean_int(m.group(4)),
            }
        m = re.search(r"(?:주문 성공|매수 주문 접수)! 주문ID: (.+)", line)
        if m:
            info["order_success"] = True
            info["order_id"] = normalize_order_id(m.group(1))
        if "매수 주문 실패" in line or "시스템 에러" in line or "[안전 중단]" in line:
            info["order_success"] = False
            info["reason"] = line.strip()
    if info["order"] and info["reason"] is None:
        info["reason"] = "KOSDAQ 5일선 대비 -1% 이하 가드 통과 + 전일 종가 1천~8천원 + 전일 거래량<20일 평균 0.8배 + 당일 시가 갭하락 -5% 이하 중 최저가"
    if not info["order"] and info["reason"] is None and info.get("warning_exclusions"):
        info["reason"] = "매수 유의사항 필터로 위험 종목 제외"
    return info


def aggregate_buy_sessions_for_date(path: Path, date: str) -> dict[str, Any] | None:
    sessions = [sess for sess in split_sessions(path) if sess and date in sess[0]]
    if not sessions:
        fallback = latest_session_for_date(path, date)
        sessions = [fallback] if fallback else []
    if not sessions:
        return None

    parsed = [parse_buy_session(session) for session in sessions]
    latest = dict(parsed[-1])
    actual = next(
        (
            item
            for item in parsed
            if item.get("order") and (item.get("order_success") is True or item.get("order_id"))
        ),
        None,
    )
    latest["session_count"] = len(parsed)
    latest["latest_reason"] = latest.get("reason")
    if actual is None:
        return latest

    for key in ("order", "order_success", "order_id", "reason"):
        latest[key] = actual.get(key)
    for key in (
        "kosdaq",
        "kosdaq_open",
        "sma5",
        "buy_line",
        "market_timestamp",
        "market_freshness",
        "guard",
        "latest_db_date",
        "scan_total",
        "actual_cash",
        "budget",
        "gap_count",
        "breadth_shadow",
        "perf",
        "candidates",
        "warning_exclusions",
    ):
        if latest.get(key) in (None, [], {}):
            latest[key] = actual.get(key)
    latest["order_session_datetime"] = actual.get("datetime")
    latest["order_session_end_datetime"] = actual.get("end_datetime")
    return latest


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
        if "현재 보유 중인 종목이 없습니다" in line or "추적 중인 전략 포지션이 없습니다" in line or "전략 포지션이 이미 종료" in line:
            info["no_holdings"] = True
        m = re.search(r"현재 보유 종목 수: (\d+)개", line)
        if m:
            info["holding_count"] = int(m.group(1))
        m = re.search(r"\[(.+?)\] (\d+)주 (?:지정가 )?매도 주문 발송 \((?:예상단가|지정가) ([\d,]+)원, 예상금액 ([\d,]+)원\)", line)
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
        m = re.search(r"\[(.+?)\] (\d+)주 (손절|익절|종가청산) 시장가 매도 주문 발송", line)
        if m:
            current_order = {
                "name": m.group(1),
                "qty": int(m.group(2)),
                "trigger": m.group(3),
                "expected_price": None,
                "expected_amount": None,
                "success": None,
                "order_id": None,
            }
            info["orders"].append(current_order)
            continue
        m = re.search(r"(?:매도 주문 성공|(?:손절|익절|종가청산) 시장가 매도 주문 접수)! 주문ID: (.+)", line)
        if m and current_order is not None:
            current_order["success"] = True
            current_order["order_id"] = normalize_order_id(m.group(1))
        m = re.search(r"\[(\w+)\] (손절|익절|종가청산) 실제 체결 확인: (\d+)주 @ ([\d,]+)원 / 수익률 ([-+\d.]+)%", line)
        if m and current_order is not None:
            current_order["filled_quantity"] = int(m.group(3))
            current_order["filled_price"] = clean_int(m.group(4))
            current_order["return_pct"] = clean_float(m.group(5))
        if "매도 주문 실패" in line or "매도 에러" in line:
            if current_order is not None:
                current_order["success"] = False
                current_order["error"] = line.strip()
    return info


def parse_monitor_session(lines: list[str]) -> dict[str, Any]:
    info: dict[str, Any] = {
        "datetime": None,
        "mode": None,
        "no_holdings": False,
        "holding_count": None,
        "orders": [],
        "raw_tail": lines[-12:],
    }
    current_order: dict[str, Any] | None = None
    position_context: dict[str, Any] = {}
    for line in lines:
        m = re.search(r"실행 시간: (.+)", line)
        if m:
            info["datetime"] = m.group(1).strip()
        m = re.search(r"모드: (.+)", line)
        if m:
            info["mode"] = m.group(1).strip()
        if "현재 보유 중인 종목이 없습니다" in line or "추적 중인 전략 주문/포지션이 없습니다" in line:
            info["no_holdings"] = True
        m = re.search(r"현재 보유 종목 수: (\d+)개", line)
        if m:
            info["holding_count"] = int(m.group(1))
        m = re.search(
            r"\[(.+?)\] (\d+)주 (손절|익절) 매도 주문 발송 "
            r"\(진입가 ([\d,]+)원, 현재가 ([\d,]+)원, 트리거 ([\d,]+)원, 지정가 ([\d,]+)원, 예상금액 ([\d,]+)원\)",
            line,
        )
        if m:
            current_order = {
                "name": m.group(1),
                "qty": int(m.group(2)),
                "trigger": m.group(3),
                "entry_price": clean_int(m.group(4)),
                "last_price": clean_int(m.group(5)),
                "trigger_price": clean_int(m.group(6)),
                "expected_price": clean_int(m.group(7)),
                "expected_amount": clean_int(m.group(8)),
                "success": None,
                "order_id": None,
            }
            info["orders"].append(current_order)
            continue
        m = re.search(
            r"\[(\w+)\] (.+?) 전략소유 (\d+)주\(계좌 (\d+)주\) \| 진입가 ([\d,]+)원 \| "
            r"현재가 ([\d,]+)원 \| 손절가 ([\d,]+)원 \| 익절가 ([\d,]+)원",
            line,
        )
        if m:
            position_context = {
                "symbol": m.group(1),
                "name": m.group(2),
                "qty": int(m.group(3)),
                "entry_price": clean_int(m.group(5)),
                "last_price": clean_int(m.group(6)),
                "stop_price": clean_int(m.group(7)),
                "take_price": clean_int(m.group(8)),
            }
            continue
        m = re.search(r"\[(.+?)\] (\d+)주 (손절|익절) 시장가 매도 주문 발송", line)
        if m:
            trigger = m.group(3)
            current_order = {
                "name": position_context.get("name") or m.group(1),
                "symbol": position_context.get("symbol"),
                "qty": int(m.group(2)),
                "trigger": trigger,
                "entry_price": position_context.get("entry_price"),
                "last_price": position_context.get("last_price"),
                "trigger_price": position_context.get("stop_price") if trigger == "손절" else position_context.get("take_price"),
                "expected_price": None,
                "expected_amount": None,
                "success": None,
                "order_id": None,
            }
            info["orders"].append(current_order)
            continue
        m = re.search(r"(?:모니터 매도 주문 성공|(?:손절|익절) 시장가 매도 주문 접수)! 주문ID: (.+)", line)
        if m and current_order is not None:
            current_order["success"] = True
            current_order["order_id"] = normalize_order_id(m.group(1))
        m = re.search(r"\[(\w+)\] (손절|익절) 실제 체결 확인: (\d+)주 @ ([\d,]+)원 / 수익률 ([-+\d.]+)%", line)
        if m and current_order is not None:
            current_order["filled_quantity"] = int(m.group(3))
            current_order["filled_price"] = clean_int(m.group(4))
            current_order["return_pct"] = clean_float(m.group(5))
        if "모니터 매도 주문 실패" in line or "모니터 매도 에러" in line:
            if current_order is not None:
                current_order["success"] = False
                current_order["error"] = line.strip()
    return info


def buy_report(date: str | None = None) -> str:
    date = date or today()
    b = aggregate_buy_sessions_for_date(BUY_LOG, date)
    if not b:
        return f"[Toss 자동매매] {date} 09:01 매수 로그 없음\n- 로그 파일: {BUY_LOG}"
    order_id = b.get("order_id")
    order_details = fetch_order_details([order_id]) if isinstance(order_id, str) and order_id else {}
    guard_blocked = b.get("guard") == "차단"
    db_date = b.get("latest_db_date") or ("미조회(시장 가드 차단)" if guard_blocked else "로그 미기록")
    scan_total = f"{b['scan_total']}개" if b.get("scan_total") is not None else "미실행"
    gap_count = f"{b['gap_count']}개" if b.get("gap_count") is not None else "미실행"
    cash = money(b.get("actual_cash")) if b.get("actual_cash") is not None else "미조회"
    budget = money(b.get("budget")) if b.get("budget") is not None else "미산정"
    kosdaq_open = b.get("kosdaq_open") if b.get("kosdaq_open") is not None else "미기록"
    buy_line = b.get("buy_line") if b.get("buy_line") is not None else "미기록"
    lines = [
        f"[Toss 자동매매] {date} 09:01 매수 보고",
        f"- 실행: {b.get('datetime') or '확인 필요'} / {b.get('mode') or '모드 확인 필요'}",
        f"- 종료: {b.get('end_datetime') or '확인 필요'} / 총 실행시간: {b.get('total_elapsed_sec') if b.get('total_elapsed_sec') is not None else '확인 필요'}초",
        f"- KOSDAQ: {b.get('kosdaq') if b.get('kosdaq') is not None else '확인 필요'} / 시가: {kosdaq_open} / SMA5: {b.get('sma5') if b.get('sma5') is not None else '확인 필요'} / 매수 허용선: {buy_line} / 가드: {b.get('guard') or '확인 필요'}",
        f"- DB 기준일: {db_date} / 스크리닝: {scan_total} / 갭 후보: {gap_count}",
        f"- 예수금: {cash} / 사용예산: {budget}",
    ]
    if int(b.get("session_count") or 0) > 1:
        lines.append(
            f"- 당일 매수 실행 로그: {b['session_count']}회 / "
            f"실제 주문 세션: {b.get('order_session_datetime') or '없음'}"
        )
    if b.get("market_freshness") == "today_candle_close_crosscheck":
        candle_date = str(b.get("market_timestamp") or "미기록").split("T", 1)[0]
        lines.append(
            f"- 지수 최신성: Toss 당일 일봉 종가 교차검증 / 일봉 기준일: {candle_date}"
        )
    elif b.get("market_timestamp"):
        lines.append(f"- 지수 데이터 시각: {b['market_timestamp']}")
    # Timing gate for the 09:01 open-price strategy: finish before 09:05, preferably well under 240s.
    if b.get("datetime") and b.get("end_datetime"):
        timing_status = "확인 필요"
        try:
            end_dt = datetime.strptime(str(b["end_datetime"]), "%Y-%m-%d %H:%M:%S")
            cutoff = end_dt.replace(hour=9, minute=5, second=0, microsecond=0)
            elapsed = b.get("total_elapsed_sec")
            ok = end_dt <= cutoff and (elapsed is None or float(elapsed) <= 240.0)
            timing_status = "OK(09:05 전 종료)" if ok else "주의(09:05 초과 또는 240초 초과)"
        except Exception:
            pass
        lines.append(f"- 09:01 실행시간 판정: {timing_status}")
    perf = b.get("perf") or {}
    if perf:
        lines.append(
            "- API 성능: "
            f"prices {perf.get('price_chunks')}회/{perf.get('price_rows')}행, "
            f"provisional 후보 {perf.get('provisional_gap_hits')}개, "
            f"daily open candle {perf.get('daily_open_calls')}회, "
            f"open 누락 {perf.get('daily_open_missing')}개, "
            f"scan {perf.get('scan_elapsed_sec')}초"
        )
    shadow = b.get("breadth_shadow") or {}
    if shadow.get("status") == "not_evaluated":
        lines.append(
            f"- breadth4 섀도: 미실행({shadow.get('reason') or '사유 미기록'}) / 실매매 미적용"
        )
    elif shadow:
        lines.append(
            f"- breadth4 섀도: 09:01 현재가 기준 {shadow.get('provisional_gap5_count')}개 / "
            f"기준 {shadow.get('threshold')}개 / 상태 {shadow.get('status')} / "
            f"시세 {shadow.get('quoted_symbols')}/{shadow.get('reference_symbols')} / 실매매 미적용"
        )
    if b.get("candidates"):
        lines.append("- 상위 후보:")
        for c in b["candidates"][:5]:
            lines.append(f"  - {c['name']}({c['symbol']}): 갭 {pct(c['gap_pct'])}, 시가 {money(c['open_price'])}, 현재 {money(c['last_price'])}, 전일종가 {money(c['prev_close'])}")
    if b.get("warning_exclusions"):
        lines.append("- 매수 유의사항 제외:")
        for x in b["warning_exclusions"][:5]:
            lines.append(f"  - {x['name']}({x['symbol']}): {x['warnings']}")
    order = b.get("order")
    if order:
        detail = order_details.get(order_id) if isinstance(order_id, str) else None
        status = order_status_label(b.get("order_success"), detail)
        lines += [
            f"- 매수: {status}",
            f"  - 종목: {order['name']}",
            f"  - 수량/지정가/배정: {order['qty']}주 / {money(order['expected_price'])} / {money(order['amount'])}",
            f"  - 주문ID: {b.get('order_id') or '확인 필요'}",
            f"  - 매수 이유: {b.get('reason')}",
        ]
        lines.extend(execution_lines("매수", detail))
    else:
        lines.append(f"- 매수: 없음")
        lines.append(f"- 이유: {b.get('reason') or '조건 미충족 또는 로그 추가 확인 필요'}")
    return "\n".join(lines)


def estimate_buy_from_log(date: str) -> dict[str, Any] | None:
    return aggregate_buy_sessions_for_date(BUY_LOG, date)


def estimate_monitor_from_log(date: str) -> dict[str, Any] | None:
    sessions = [sess for sess in split_sessions(MONITOR_LOG) if sess and date in sess[0]]
    if not sessions:
        return None
    parsed_sessions = [parse_monitor_session(sess) for sess in sessions]
    orders: list[dict[str, Any]] = []
    for parsed in parsed_sessions:
        orders.extend(parsed.get("orders", []))
    latest = parsed_sessions[-1]
    return {
        "datetime": latest.get("datetime"),
        "mode": latest.get("mode"),
        "no_holdings": latest.get("no_holdings"),
        "holding_count": latest.get("holding_count"),
        "orders": orders,
        "session_count": len(parsed_sessions),
    }


def sell_report(date: str | None = None) -> str:
    date = date or today()
    sell_sessions = [sess for sess in split_sessions(SELL_LOG) if sess and date in sess[0]]
    buy = estimate_buy_from_log(date)
    monitor = estimate_monitor_from_log(date)
    if not sell_sessions:
        return f"[Toss 자동매매] {date} 15:20 매도 로그 없음\n- 로그 파일: {SELL_LOG}"
    parsed_sell_sessions = [parse_sell_session(sess) for sess in sell_sessions]
    s = parsed_sell_sessions[-1]
    s["orders"] = [order for parsed in parsed_sell_sessions for order in parsed.get("orders", [])]

    buy_order_id = buy.get("order_id") if buy else None
    monitor_orders = monitor.get("orders", []) if monitor else []
    monitor_order_ids = [o.get("order_id") for o in monitor_orders if isinstance(o.get("order_id"), str) and o.get("order_id")]
    sell_order_ids = [o.get("order_id") for o in s.get("orders", []) if isinstance(o.get("order_id"), str) and o.get("order_id")]
    detail_ids = []
    if isinstance(buy_order_id, str) and buy_order_id:
        detail_ids.append(buy_order_id)
    detail_ids.extend(str(oid) for oid in monitor_order_ids)
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
    if monitor_orders:
        lines.append(f"- 장중 손절/익절 주문: {len(monitor_orders)}건")
        for o in monitor_orders:
            order_id = o.get("order_id")
            detail = order_details.get(order_id) if isinstance(order_id, str) else None
            status = order_status_label(o.get("success"), detail)
            trigger = o.get("trigger") or "청산"
            lines.append(
                f"  - {o['name']} {o['qty']}주 / {trigger} / 진입 {money(o.get('entry_price'))} / 현재 {money(o.get('last_price'))} / "
                f"트리거 {money(o.get('trigger_price'))} / 지정가 {money(o.get('expected_price'))} / 예상금액 {money(o.get('expected_amount'))} / "
                f"{status} / 주문ID {order_id or '확인 필요'}"
            )
            lines.extend(execution_lines(f"장중 {trigger}", detail))
    if s.get("no_holdings") and not s.get("orders"):
        if monitor_orders:
            lines.append("- 15:20 매도: 보유 종목 없음 → 장중 손절/익절 후 15:20 보유 없음")
            actual = None
            if isinstance(buy_order_id, str):
                first_monitor_id = monitor_orders[0].get("order_id")
                actual = realized_pnl_from_details(order_details.get(buy_order_id), order_details.get(first_monitor_id) if isinstance(first_monitor_id, str) else None)
            if actual:
                pnl, ret = actual
                lines.append(f"- 실제 당일 손익: {money_decimal(pnl)} ({pct_decimal(ret)}) — 체결금액/수수료/세금 반영")
            elif buy and buy.get("order"):
                bo = buy["order"]
                first_monitor = monitor_orders[0]
                if first_monitor.get("expected_price") and bo.get("expected_price"):
                    pnl = (first_monitor["expected_price"] - bo["expected_price"]) * min(int(bo["qty"]), int(first_monitor["qty"]))
                    ret = (first_monitor["expected_price"] - bo["expected_price"]) / bo["expected_price"] * 100
                    lines.append(f"- 추정 당일 손익: {money(pnl)} ({pct(ret)}) — 실제 체결 상세조회 실패/미체결 시 fallback")
                else:
                    lines.append("- 당일 손익: 실제 체결가/예상가 확인 필요")
        else:
            lines.append("- 매도: 보유 종목 없음 → 매도 없음")
            lines.append("- 오늘 결과: 미거래 또는 오전 체결 없음")
        return "\n".join(lines)
    if s.get("orders"):
        lines.append("- 매도 주문:")
        for o in s["orders"]:
            order_id = o.get("order_id")
            detail = order_details.get(order_id) if isinstance(order_id, str) else None
            status = order_status_label(o.get("success"), detail)
            lines.append(f"  - {o['name']} {o['qty']}주 / 예상단가 {money(o.get('expected_price'))} / 예상금액 {money(o.get('expected_amount'))} / {status} / 주문ID {order_id or '확인 필요'}")
            lines.extend(execution_lines("매도", detail))
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


def _normalized_session_date(value: object) -> str | None:
    raw = str(value or "").strip()
    if len(raw) >= 10 and raw[4] == "-" and raw[7] == "-":
        return raw[:10]
    digits = "".join(ch for ch in raw if ch.isdigit())
    if len(digits) >= 8:
        return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}"
    return None


def latest_kosdaq_session_date() -> str:
    latest = _normalized_session_date(fetch_kosdaq_close().get("date"))
    if not latest:
        raise ValueError("KOSDAQ 최신 거래일 형식을 해석할 수 없습니다")
    return latest


def candle_update_report(
    *,
    dry_run: bool = False,
    limit: int = 0,
    only_if_stale: bool = False,
    expected_latest_date: str | None = None,
) -> str:
    before = db_summary()
    expected_error: str | None = None
    if expected_latest_date is None and not dry_run and limit == 0:
        try:
            expected_latest_date = latest_kosdaq_session_date()
        except Exception as error:
            expected_error = f"{type(error).__name__}: {error}"
    before_latest = before.get("latest_date") if before.get("exists") else None
    if (
        only_if_stale
        and expected_latest_date
        and before_latest
        and str(before_latest) >= expected_latest_date
    ):
        return "\n".join(
            [
                "[Toss 자동매매] 캔들 DB 개장 전 최신성 점검",
                "- 실행 결과: 이미 최신이라 API 업데이트 생략",
                f"- 기대 최신 거래일: {expected_latest_date}",
                f"- DB 최신일: {before_latest}",
            ]
        )
    code, stdout, stderr = run_candle_update(dry_run=dry_run, limit=limit)
    after = db_summary()
    parsed = extract_last_json(stdout)
    mode = "DRY-RUN 검증" if dry_run else "실제 업데이트"
    after_latest = after.get("latest_date") if after.get("exists") else None
    if expected_error:
        latest_is_fresh: bool | None = None
    elif expected_latest_date is None:
        latest_is_fresh = True
    else:
        latest_is_fresh = after_latest is not None and str(after_latest) >= expected_latest_date

    if code != 0:
        result_label = "실패"
    elif latest_is_fresh is None:
        result_label = "최신성 확인 실패"
    elif latest_is_fresh:
        result_label = "성공"
    else:
        result_label = "지연"
    heading = (
        f"[Toss 자동매매] 개장 전 캔들 DB 복구 보고 ({mode})"
        if only_if_stale
        else f"[Toss 자동매매] 15:40 캔들 DB 업데이트 보고 ({mode})"
    )
    lines = [
        heading,
        f"- 실행 결과: {result_label} (exit={code})",
        f"- DB before: latest={before.get('latest_date')} rows={before.get('rows'):,} latest_rows={before.get('latest_date_rows'):,}" if before.get("exists") else "- DB before: 없음",
        f"- DB after: latest={after.get('latest_date')} rows={after.get('rows'):,} latest_rows={after.get('latest_date_rows'):,} toss_latest={after.get('latest_toss_rows'):,} bad_ts={after.get('bad_timestamp_rows'):,}" if after.get("exists") else "- DB after: 없음",
    ]
    if expected_latest_date:
        lines.append(f"- KOSDAQ 기대 최신 거래일: {expected_latest_date}")
        if latest_is_fresh is False:
            lines.append(
                "- ⚠️ 최신 거래일 캔들이 아직 DB에 반영되지 않았습니다. "
                "09:01 매수는 기준일 불일치로 자동 차단되며 개장 전 재시도가 필요합니다."
            )
    elif expected_error:
        lines.append(f"- KOSDAQ 기대 거래일 조회 실패: {expected_error}")
    if parsed:
        known_unsupported = parsed.get("known_unsupported_skipped_symbols", 0)
        newly_recorded = parsed.get("newly_recorded_unsupported_symbols") or []
        lines += [
            f"- 종목 처리: ok={parsed.get('ok_symbols')} known_unsupported={known_unsupported} soft_skipped={parsed.get('soft_skipped_symbols', 0)} hard_failed={parsed.get('failed_symbols')}",
            f"- candles fetched/replaced: {parsed.get('total_fetched')} / {parsed.get('total_inserted_or_replaced')}",
            f"- latest 분포: {parsed.get('latest_distribution_tail')}",
        ]
        stale_count = int(parsed.get("stale_latest_symbols_count") or 0)
        if stale_count:
            lines.append(f"- 최신 캔들 지연/상폐 의심: count={stale_count} sample={parsed.get('stale_latest_symbols_tail')}")
        if newly_recorded:
            lines.append(f"- 새 Toss 미지원 종목 기록: {newly_recorded}")
        if parsed.get("soft_errors_tail"):
            lines.append(f"- 이번 실행 미지원 응답 샘플: {parsed.get('soft_errors_tail')}")
        if parsed.get("errors_tail"):
            lines.append(f"- hard 오류 샘플: {parsed.get('errors_tail')}")
    else:
        lines.append("- updater JSON 파싱 실패: stdout tail 확인 필요")
    if stderr.strip():
        lines.append("- stderr tail:\n```\n" + "\n".join(stderr.splitlines()[-8:])[:1500] + "\n```")
    latest_date = after.get("latest_date") if after.get("exists") else None
    if code == 0 and not dry_run and limit == 0 and latest_date == today():
        try:
            reconciliation = breadth_shadow.record_official_reconciliation(
                DB_PATH, BREADTH_SHADOW_LOG, str(latest_date)
            )
            status = "통과" if reconciliation["shadow_pass"] else "기준 미달"
            lines.append(
                f"- breadth4 사후확정: 공식 시가 -5% 갭 "
                f"{reconciliation['official_gap5_count']}개 / 기준 "
                f"{reconciliation['threshold']}개 / {status} / 실매매 미적용"
            )
        except Exception as error:
            lines.append(
                f"- breadth4 사후확정 실패: {type(error).__name__}: {error} / 실매매 영향 없음"
            )
    return "\n".join(lines)


def status_report() -> str:
    return "\n".join(
        [
            "[Toss 자동매매] Discord 보고 설정 테스트",
            f"- 시간: {now_text()}",
            "- macOS crontab에서 매수/장중 monitor/15:20 매도/보고/종가/DB 업데이트를 직접 실행하도록 구성됨",
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


def build_message(
    action: str,
    date: str | None = None,
    *,
    dry_run_update: bool = False,
    update_limit: int = 0,
    only_if_stale: bool = False,
) -> str:
    if action == "buy-report":
        return buy_report(date)
    if action == "sell-report":
        return sell_report(date)
    if action == "kosdaq-close":
        return kosdaq_close_report()
    if action == "candle-update":
        return candle_update_report(
            dry_run=dry_run_update,
            limit=update_limit,
            only_if_stale=only_if_stale,
        )
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
    ap.add_argument("--only-if-stale", action="store_true", help="For --action candle-update, skip API calls when DB already has the latest KOSDAQ session")
    args = ap.parse_args()
    if not args.to and not args.print_only:
        print(f"Missing --to or {DEFAULT_TARGET_ENV}", file=sys.stderr)
        return 2
    REPORT_LOG.parent.mkdir(exist_ok=True)
    try:
        msg = build_message(
            args.action,
            args.date or None,
            dry_run_update=args.dry_run_update,
            update_limit=args.update_limit,
            only_if_stale=args.only_if_stale,
        )
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
