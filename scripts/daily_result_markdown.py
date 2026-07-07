#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import toss_discord_report as report


ROOT: Final = Path(__file__).resolve().parents[1]
DEFAULT_RESULTS_PATH: Final = ROOT / "RESULTS.md"
TABLE_HEADER: Final = "| Date | Buy | Exit | Return | Note |"
TABLE_SEPARATOR: Final = "|---|---|---|---:|---|"


@dataclass(frozen=True, slots=True)
class DailyResult:
    date: str
    buy: str
    exit: str
    return_pct: float | None
    note: str


def public_text(value: Any) -> str:
    return str(value).replace("|", "/").strip() or "-"


def order_price(order: dict[str, Any] | None) -> int | float | None:
    if not order:
        return None
    raw = order.get("expected_price")
    if isinstance(raw, int | float):
        return raw
    try:
        return int(str(raw).replace(",", ""))
    except (TypeError, ValueError):
        return None


def order_name(order: dict[str, Any] | None) -> str:
    if not order:
        return "-"
    return public_text(order.get("name") or "-")


def public_order_label(order: dict[str, Any] | None, *, prefix: str | None = None) -> str:
    if not order:
        return "-"
    name = order_name(order)
    price = report.money(order_price(order))
    if prefix:
        return f"{public_text(prefix)} @ {price}"
    return f"{name} @ {price}"


def first_public_exit(monitor: dict[str, Any] | None, sell: dict[str, Any] | None) -> tuple[dict[str, Any] | None, str]:
    monitor_orders = monitor.get("orders", []) if monitor else []
    for order in monitor_orders:
        if order.get("success") is True:
            return order, str(order.get("trigger") or "장중 청산")

    sell_orders = sell.get("orders", []) if sell else []
    for order in sell_orders:
        if order.get("success") is True:
            return order, "15:20 정리"
    if monitor_orders:
        order = monitor_orders[0]
        return order, str(order.get("trigger") or "장중 청산 확인 필요")
    if sell_orders:
        return sell_orders[0], "15:20 정리 확인 필요"
    return None, "-"


def return_pct(entry_price: int | float | None, exit_price: int | float | None) -> float | None:
    if entry_price is None or exit_price is None or entry_price <= 0:
        return None
    return (exit_price - entry_price) / entry_price * 100.0


def actual_return_pct_from_api(
    buy: dict[str, Any] | None,
    monitor: dict[str, Any] | None,
    sell: dict[str, Any] | None,
) -> float | None:
    if not buy:
        return None
    exit_order, _ = first_public_exit(monitor, sell)
    buy_order_id = report.normalize_order_id(buy.get("order_id"))
    exit_order_id = report.normalize_order_id(exit_order.get("order_id") if exit_order else None)
    if not buy_order_id or not exit_order_id:
        return None
    details = report.fetch_order_details([buy_order_id, exit_order_id])
    actual = report.realized_pnl_from_details(details.get(buy_order_id), details.get(exit_order_id))
    if actual is None:
        return None
    _, actual_return = actual
    return float(actual_return)


def daily_result_from_parsed(
    date: str,
    buy: dict[str, Any] | None,
    monitor: dict[str, Any] | None,
    sell: dict[str, Any] | None,
    actual_return_pct: float | None = None,
) -> DailyResult:
    if not buy:
        return DailyResult(date, "로그 없음", "-", None, "매수 로그 없음")
    buy_order = buy.get("order")
    if not isinstance(buy_order, dict):
        return DailyResult(date, "없음", "-", None, public_text(buy.get("reason") or "조건 미충족"))

    exit_order, exit_reason = first_public_exit(monitor, sell)
    entry = order_price(buy_order)
    exit_price = order_price(exit_order)
    note = "장중 monitor 청산" if monitor and exit_order in monitor.get("orders", []) else "15:20 잔여 보유분 정리"
    if exit_order is None:
        note = "매도 로그 확인 필요"
    elif actual_return_pct is not None:
        note = f"{note} / 실제 체결 기준"
    else:
        note = f"{note} / 예상가 기준"
    return DailyResult(
        date=date,
        buy=public_order_label(buy_order),
        exit=public_order_label(exit_order, prefix=exit_reason),
        return_pct=actual_return_pct if actual_return_pct is not None else return_pct(entry, exit_price),
        note=note,
    )


def load_daily_result(date: str, *, use_api: bool = True) -> DailyResult:
    buy = report.estimate_buy_from_log(date)
    monitor = report.estimate_monitor_from_log(date)
    sell_lines = report.latest_session_for_date(report.SELL_LOG, date)
    sell = report.parse_sell_session(sell_lines) if sell_lines else None
    actual_return_pct = actual_return_pct_from_api(buy, monitor, sell) if use_api else None
    return daily_result_from_parsed(date, buy, monitor, sell, actual_return_pct)


def default_markdown() -> str:
    return "\n".join(
        [
            "# Trading Results",
            "",
            "Public daily trading summaries generated from local logs.",
            "No order IDs, account identifiers, cash balance, raw logs, or DB/runtime data belong here.",
            "",
            TABLE_HEADER,
            TABLE_SEPARATOR,
            "",
        ]
    )


def render_return(value: float | None) -> str:
    if value is None:
        return "-"
    return report.pct(value)


def render_row(result: DailyResult) -> str:
    return (
        f"| {public_text(result.date)} | {public_text(result.buy)} | {public_text(result.exit)} | "
        f"{render_return(result.return_pct)} | {public_text(result.note)} |"
    )


def upsert_result(existing: str, result: DailyResult) -> str:
    base = existing.rstrip() if existing.strip() else default_markdown().rstrip()
    row = render_row(result)
    lines = base.splitlines()
    row_prefix = f"| {result.date} |"
    for idx, line in enumerate(lines):
        if line.startswith(row_prefix):
            lines[idx] = row
            return "\n".join(lines) + "\n"
    lines.append(row)
    return "\n".join(lines) + "\n"


def write_result(path: Path, result: DailyResult) -> None:
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(upsert_result(existing, result), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate sanitized public daily trading result markdown.")
    parser.add_argument("--date", default=report.today(), help="Trading date in YYYY-MM-DD")
    parser.add_argument("--output", default=str(DEFAULT_RESULTS_PATH), help="Markdown file to update")
    parser.add_argument("--print-only", action="store_true", help="Print the generated row without writing")
    parser.add_argument("--no-api", action="store_true", help="Use log expected prices instead of Toss order details")
    args = parser.parse_args()

    result = load_daily_result(args.date, use_api=not args.no_api)
    if args.print_only:
        print(render_row(result))
        return 0
    output = Path(args.output)
    write_result(output, result)
    print(f"updated {output}: {render_row(result)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
