from __future__ import annotations

import sqlite3
from pathlib import Path

from simple_gap_variant_core import Candidate


def load_candidates(db_path: str, *, start: str, end: str, broad_gap: float) -> list[Candidate]:
    lead_cols = ",\n".join(
        f"LEAD(CAST(close_price AS REAL), {idx}) OVER (PARTITION BY symbol ORDER BY timestamp) AS close_fwd_{idx}"
        for idx in range(1, 11)
    )
    select_cols = ", ".join(f"close_fwd_{idx}" for idx in range(1, 11))
    params: list[float | str] = [start, end, broad_gap]
    sql = f"""
    WITH enriched AS (
      SELECT
        symbol,
        substr(timestamp,1,10) AS date,
        CAST(open_price AS REAL) AS open_price,
        CAST(high_price AS REAL) AS high_price,
        CAST(low_price AS REAL) AS low_price,
        CAST(close_price AS REAL) AS close_price,
        LAG(CAST(close_price AS REAL)) OVER (PARTITION BY symbol ORDER BY timestamp) AS prev_close,
        LAG(CAST(volume AS REAL)) OVER (PARTITION BY symbol ORDER BY timestamp) AS prev_volume,
        AVG(CAST(volume AS REAL)) OVER (
          PARTITION BY symbol ORDER BY timestamp ROWS BETWEEN 21 PRECEDING AND 2 PRECEDING
        ) AS avg_prev20_volume,
        COUNT(CAST(volume AS REAL)) OVER (
          PARTITION BY symbol ORDER BY timestamp ROWS BETWEEN 21 PRECEDING AND 2 PRECEDING
        ) AS prev_count,
        {lead_cols}
      FROM candle_cache
      WHERE interval='1d'
    )
    SELECT symbol, date, prev_close, open_price, close_price, high_price, low_price,
           ((open_price - prev_close) / prev_close) AS gap_return,
           (prev_volume / avg_prev20_volume) AS prev_vol_ratio,
           {select_cols}
    FROM enriched
    WHERE date >= ?
      AND date <= ?
      AND prev_count = 20
      AND prev_close > 0
      AND open_price > 0
      AND close_price > 0
      AND avg_prev20_volume > 0
      AND ((open_price - prev_close) / prev_close) <= ?
    ORDER BY date ASC, gap_return ASC
    """
    con = sqlite3.connect(f"file:{Path(db_path).resolve()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(sql, params).fetchall()
    finally:
        con.close()
    candidates: list[Candidate] = []
    for row in rows:
        future = tuple(None if row[f"close_fwd_{idx}"] is None else float(row[f"close_fwd_{idx}"]) for idx in range(1, 11))
        candidates.append(
            Candidate(
                date=str(row["date"]),
                symbol=str(row["symbol"]),
                prev_close=float(row["prev_close"]),
                open_price=float(row["open_price"]),
                close_price=float(row["close_price"]),
                high_price=float(row["high_price"]),
                low_price=float(row["low_price"]),
                gap_return=float(row["gap_return"]),
                prev_vol_ratio=float(row["prev_vol_ratio"]),
                future_closes=future,
            )
        )
    return candidates
