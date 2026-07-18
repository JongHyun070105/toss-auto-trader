"""Paper-only breadth observations for the Korean gap strategy."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


SHADOW_RULE = "gap5_count_at_least_4"
SHADOW_THRESHOLD = 4
MIN_REFERENCE_PRICE = 500.0
MAX_REFERENCE_PRICE = 30_000.0
GAP_THRESHOLD = -0.05


def provisional_gap_count(
    reference_prices: dict[str, float], quote_rows: Iterable[dict[str, Any]]
) -> tuple[int, int]:
    """Count current-price gaps using only symbols with a valid quote and reference."""
    quoted = 0
    gap_count = 0
    seen_symbols: set[str] = set()
    for row in quote_rows:
        symbol = str(row.get("symbol") or "")
        if not symbol or symbol in seen_symbols:
            continue
        previous_close = float(reference_prices.get(symbol) or 0)
        try:
            last_price = float(str(row.get("lastPrice") or "0").replace(",", ""))
        except (TypeError, ValueError):
            continue
        if previous_close <= 0 or last_price <= 0:
            continue
        seen_symbols.add(symbol)
        quoted += 1
        gap_count += last_price / previous_close - 1.0 <= GAP_THRESHOLD
    return gap_count, quoted


def official_open_breadth(db_path: str | Path, date: str) -> dict[str, Any]:
    """Calculate the research definition after the official daily candle is cached."""
    sql = """
    WITH ordered AS (
      SELECT
        symbol,
        substr(timestamp,1,10) AS date,
        CAST(open_price AS REAL) AS open_price,
        CAST(high_price AS REAL) AS high_price,
        CAST(low_price AS REAL) AS low_price,
        CAST(close_price AS REAL) AS close_price,
        LAG(CAST(close_price AS REAL),1) OVER w AS prev_close,
        AVG(CAST(volume AS REAL)) OVER (
          PARTITION BY symbol ORDER BY timestamp ROWS BETWEEN 21 PRECEDING AND 2 PRECEDING
        ) AS avg_prev20_volume,
        AVG((CAST(high_price AS REAL)-CAST(low_price AS REAL))/NULLIF(CAST(close_price AS REAL),0)) OVER (
          PARTITION BY symbol ORDER BY timestamp ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING
        ) AS avg_range20,
        COUNT(*) OVER (
          PARTITION BY symbol ORDER BY timestamp ROWS BETWEEN 21 PRECEDING AND 2 PRECEDING
        ) AS prev_count
      FROM candle_cache
      WHERE interval='1d'
      WINDOW w AS (PARTITION BY symbol ORDER BY timestamp)
    )
    SELECT
      COUNT(*) AS eligible_symbols,
      COALESCE(SUM(CASE WHEN open_price/prev_close-1.0 <= ? THEN 1 ELSE 0 END),0) AS gap5_count
    FROM ordered
    WHERE date=? AND prev_count=20
      AND prev_close BETWEEN ? AND ?
      AND open_price > 0
      AND high_price >= MAX(open_price,close_price)
      AND low_price <= MIN(open_price,close_price)
      AND avg_prev20_volume > 0
      AND avg_range20 > 0
    """
    connection = sqlite3.connect(f"file:{Path(db_path).resolve()}?mode=ro", uri=True)
    try:
        row = connection.execute(
            sql,
            (GAP_THRESHOLD, date, MIN_REFERENCE_PRICE, MAX_REFERENCE_PRICE),
        ).fetchone()
    finally:
        connection.close()
    eligible = int(row[0] or 0)
    count = int(row[1] or 0)
    return {
        "date": date,
        "eligible_symbols": eligible,
        "official_gap5_count": count,
        "shadow_pass": count >= SHADOW_THRESHOLD,
        "rule": SHADOW_RULE,
        "threshold": SHADOW_THRESHOLD,
    }


def append_event(
    path: str | Path,
    event: dict[str, Any],
    *,
    dedupe_fields: tuple[str, ...] = (),
) -> bool:
    """Append one local JSONL event, optionally skipping an existing identity."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if dedupe_fields and target.exists():
        for line in target.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                existing = json.loads(line)
            except json.JSONDecodeError:
                continue
            if all(existing.get(field) == event.get(field) for field in dedupe_fields):
                return False
    payload = dict(event)
    payload.setdefault("recorded_at", datetime.now().astimezone().isoformat())
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
    return True


def record_official_reconciliation(
    db_path: str | Path, log_path: str | Path, date: str
) -> dict[str, Any]:
    result = official_open_breadth(db_path, date)
    event = {
        "event": "breadth_shadow_official_reconciliation",
        "phase": "after_close",
        **result,
    }
    append_event(log_path, event, dedupe_fields=("event", "date"))
    return event
