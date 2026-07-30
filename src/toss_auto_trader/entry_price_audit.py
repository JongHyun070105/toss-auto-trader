from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


DEFAULT_MAX_DIFF_PCT = 0.1


def _positive_float(raw: object) -> float | None:
    try:
        value = float(str(raw).replace(",", ""))
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _diff_pct(left: float, right: float) -> float:
    return abs(left - right) / right * 100.0


def _load_price_reference_records_with_diagnostics(path: Path, trade_date: str) -> dict[str, Any]:
    if not path.exists():
        return {
            "records": {},
            "audit_file_exists": False,
            "audit_lines": 0,
            "audit_parse_errors": 0,
        }
    records: dict[str, dict[str, Any]] = {}
    audit_lines = 0
    audit_parse_errors = 0
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        if not raw_line.strip():
            continue
        audit_lines += 1
        try:
            row = json.loads(raw_line)
        except json.JSONDecodeError:
            audit_parse_errors += 1
            continue
        if not isinstance(row, dict):
            audit_parse_errors += 1
            continue
        if row.get("trade_date") != trade_date:
            continue
        symbol = str(row.get("symbol") or "").strip()
        if symbol and _positive_float(row.get("first_minute_open")) is not None:
            records[symbol] = row
    return {
        "records": records,
        "audit_file_exists": True,
        "audit_lines": audit_lines,
        "audit_parse_errors": audit_parse_errors,
    }


def load_price_reference_records(path: Path, trade_date: str) -> dict[str, dict[str, Any]]:
    return _load_price_reference_records_with_diagnostics(path, trade_date)["records"]


def official_daily_prices(db_path: Path, trade_date: str, symbols: set[str]) -> dict[str, dict[str, float]]:
    if not db_path.exists() or not symbols:
        return {}
    placeholders = ",".join("?" for _ in symbols)
    connection = sqlite3.connect(f"file:{db_path.resolve()}?mode=ro", uri=True)
    try:
        rows = connection.execute(
            f"""
            SELECT symbol, CAST(open_price AS REAL), CAST(close_price AS REAL)
            FROM candle_cache
            WHERE interval = '1d'
              AND substr(timestamp,1,10) = ?
              AND symbol IN ({placeholders})
            """,
            (trade_date, *sorted(symbols)),
        ).fetchall()
    finally:
        connection.close()
    return {
        str(symbol): {"open": float(open_price), "close": float(close_price)}
        for symbol, open_price, close_price in rows
        if float(open_price) > 0 and float(close_price) > 0
    }


def reconcile_entry_prices(
    db_path: Path,
    audit_path: Path,
    trade_date: str,
    *,
    max_diff_pct: float = DEFAULT_MAX_DIFF_PCT,
) -> dict[str, Any]:
    loaded = _load_price_reference_records_with_diagnostics(audit_path, trade_date)
    records = loaded["records"]
    official = official_daily_prices(db_path, trade_date, set(records))
    rows: list[dict[str, Any]] = []
    missing_symbols: list[str] = []
    mismatch_symbols: list[str] = []
    for symbol, record in sorted(records.items()):
        daily = official.get(symbol)
        first_open = _positive_float(record.get("first_minute_open"))
        if daily is None or first_open is None:
            missing_symbols.append(symbol)
            continue
        diff_pct = _diff_pct(first_open, daily["open"])
        status = "match" if diff_pct <= max_diff_pct else "mismatch"
        if status == "mismatch":
            mismatch_symbols.append(symbol)
        rows.append(
            {
                "symbol": symbol,
                "first_minute_open": first_open,
                "official_open": daily["open"],
                "diff_pct": diff_pct,
                "status": status,
            }
        )
    if not loaded["audit_file_exists"]:
        status = "missing_audit_file"
    elif loaded["audit_parse_errors"]:
        status = "audit_parse_error"
    elif not records:
        status = "no_reference"
    elif missing_symbols:
        status = "missing_official"
    elif mismatch_symbols:
        status = "mismatch"
    else:
        status = "ok"
    return {
        "status": status,
        "trade_date": trade_date,
        "audit_file_exists": loaded["audit_file_exists"],
        "audit_lines": loaded["audit_lines"],
        "audit_parse_errors": loaded["audit_parse_errors"],
        "reference_symbols": len(records),
        "official_symbols": len(official),
        "matched_symbols": sum(row["status"] == "match" for row in rows),
        "mismatch_symbols": mismatch_symbols,
        "missing_symbols": missing_symbols,
        "max_diff_pct": max((row["diff_pct"] for row in rows), default=None),
        "threshold_pct": max_diff_pct,
        "rows": rows,
    }
