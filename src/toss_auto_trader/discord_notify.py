from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TARGET_ENV = "TOSS_DISCORD_TARGET"
MONITOR_TARGET_ENV = "TOSS_MONITOR_DISCORD_TARGET"


@dataclass(frozen=True, slots=True)
class MonitorExitAlert:
    strategy_name: str
    trigger: str
    symbol: str
    name: str
    qty: int
    entry_price: float
    last_price: float
    trigger_price: float
    limit_price: int
    expected_amount: float
    return_pct: float
    order_id: str | None
    occurred_at: datetime


def money(value: int | float | None) -> str:
    if value is None:
        return "확인 필요"
    return f"{value:,.0f}원"


def pct(value: float | None) -> str:
    if value is None:
        return "확인 필요"
    return f"{value:+.2f}%"


def configured_discord_target() -> str | None:
    for key in (MONITOR_TARGET_ENV, DEFAULT_TARGET_ENV):
        value = os.getenv(key, "").strip()
        if value:
            return value
    return None


def format_monitor_exit_alert(alert: MonitorExitAlert) -> str:
    order_id = alert.order_id or "확인 필요"
    return "\n".join(
        [
            f"[Toss 자동매매] {alert.occurred_at:%Y-%m-%d %H:%M} 장중 {alert.trigger} 체결 알림",
            f"- 전략: {alert.strategy_name}",
            f"- 종목: {alert.name}({alert.symbol})",
            f"- 수량: {alert.qty:,}주",
            f"- 진입가: {money(alert.entry_price)} / 현재가: {money(alert.last_price)} / 수익률: {pct(alert.return_pct)}",
            f"- {alert.trigger} 기준가: {money(alert.trigger_price)} / 실제 체결가: {money(alert.limit_price)}",
            f"- 실제 매도금액: {money(alert.expected_amount)}",
            f"- 주문ID: {order_id}",
            "- 후속 처리: live 재진입 없음 / 손절·익절인 경우 paper-only 관찰 기록",
        ]
    )


def send_discord_message(message: str, *, target: str | None = None) -> bool:
    final_target = target or configured_discord_target()
    if not final_target:
        return False

    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, suffix=".md") as file:
        file.write(message)
        path = file.name

    hermes_bin = os.getenv("HERMES_BIN") or shutil.which("hermes") or str(Path.home() / ".local" / "bin" / "hermes")
    try:
        subprocess.run([hermes_bin, "send", "--quiet", "--to", final_target, "--file", path], check=True, cwd=str(ROOT), timeout=60)
    finally:
        try:
            Path(path).unlink()
        except FileNotFoundError:
            pass
    return True
