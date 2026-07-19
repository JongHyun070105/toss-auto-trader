#!/usr/bin/env python3
"""Build an isolated candle DB with a delisted-symbol research supplement."""
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence


DEFAULT_BASE = "data/edge_research_universe_15y.sqlite3"
DEFAULT_SUPPLEMENT = (
    "data/kr_foreign_microstructure_research/naver_delisted_candles.sqlite3"
)


def build_merged_database(
    base_db: str,
    supplement_db: str,
    output_db: str,
    *,
    exclude_calendar_days_before_delisting: int = 0,
    categories: Sequence[str] = (),
    replace: bool = False,
) -> dict[str, Any]:
    base = Path(base_db).resolve()
    supplement = Path(supplement_db).resolve()
    output = Path(output_db).resolve()
    if output in {base, supplement}:
        raise ValueError("output DB must be separate from both source databases")
    if output.exists():
        if not replace:
            raise FileExistsError(f"output already exists: {output}")
        output.unlink()
    output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(base, output)

    connection = sqlite3.connect(output)
    try:
        connection.execute("ATTACH DATABASE ? AS supplement", (str(supplement),))
        # The source vendors encode the same daily session with different
        # timestamp strings. Enforce the research key at calendar-date level.
        connection.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS
              idx_candle_cache_symbol_interval_trade_date
            ON candle_cache(symbol,interval,substr(timestamp,1,10))
            WHERE interval='1d'
            """
        )
        connection.execute("DROP TABLE IF EXISTS research_delisted_source_metadata")
        connection.execute(
            """
            CREATE TABLE research_delisted_source_metadata AS
            SELECT * FROM supplement.delisted_source_metadata
            """
        )
        clauses = ["m.status='ok'"]
        parameters: list[Any] = []
        if exclude_calendar_days_before_delisting > 0:
            clauses.append(
                "date(c.timestamp)<=date(m.delisting_date, ?)"
            )
            parameters.append(f"-{exclude_calendar_days_before_delisting} days")
        if categories:
            placeholders = ",".join("?" for _ in categories)
            clauses.append(f"m.category IN ({placeholders})")
            parameters.extend(categories)
        where = " AND ".join(clauses)
        positive_volume_where = f"{where} AND CAST(c.volume AS REAL)>0"
        eligible_rows = connection.execute(
            f"""
            SELECT COUNT(*) FROM supplement.candle_cache c
            JOIN supplement.delisted_source_metadata m ON m.symbol=c.symbol
            WHERE {positive_volume_where}
            """,
            parameters,
        ).fetchone()[0]
        zero_volume_rows = connection.execute(
            f"""
            SELECT COUNT(*) FROM supplement.candle_cache c
            JOIN supplement.delisted_source_metadata m ON m.symbol=c.symbol
            WHERE {where} AND CAST(c.volume AS REAL)<=0
            """,
            parameters,
        ).fetchone()[0]
        date_overlap_rows = connection.execute(
            f"""
            SELECT COUNT(*) FROM supplement.candle_cache c
            JOIN supplement.delisted_source_metadata m ON m.symbol=c.symbol
            WHERE {positive_volume_where}
              AND EXISTS (
                SELECT 1 FROM candle_cache b
                WHERE b.symbol=c.symbol AND b.interval=c.interval
                  AND substr(b.timestamp,1,10)=substr(c.timestamp,1,10)
              )
            """,
            parameters,
        ).fetchone()[0]
        insertable_symbols = connection.execute(
            f"""
            SELECT COUNT(DISTINCT c.symbol) FROM supplement.candle_cache c
            JOIN supplement.delisted_source_metadata m ON m.symbol=c.symbol
            WHERE {positive_volume_where}
              AND NOT EXISTS (
                SELECT 1 FROM candle_cache b
                WHERE b.symbol=c.symbol AND b.interval=c.interval
                  AND substr(b.timestamp,1,10)=substr(c.timestamp,1,10)
              )
            """,
            parameters,
        ).fetchone()[0]
        before = connection.total_changes
        connection.execute(
            f"""
            INSERT OR IGNORE INTO candle_cache
            SELECT c.* FROM supplement.candle_cache c
            JOIN supplement.delisted_source_metadata m ON m.symbol=c.symbol
            WHERE {positive_volume_where}
            """,
            parameters,
        )
        inserted_rows = connection.total_changes - before
        connection.commit()
        audit = connection.execute(
            """
            SELECT COUNT(*) AS rows,COUNT(DISTINCT symbol) AS symbols,
              MIN(substr(timestamp,1,10)) AS first_date,
              MAX(substr(timestamp,1,10)) AS last_date
            FROM candle_cache WHERE interval='1d'
            """
        ).fetchone()
        old_only = connection.execute(
            """
            SELECT COUNT(*) FROM (
              SELECT symbol FROM candle_cache WHERE interval='1d'
              GROUP BY symbol HAVING MAX(substr(timestamp,1,10))<'2025-01-01'
            )
            """
        ).fetchone()[0]
        duplicate_symbol_dates = connection.execute(
            """
            SELECT COUNT(*) FROM (
              SELECT symbol,interval,substr(timestamp,1,10) AS trade_date,
                COUNT(*) AS row_count
              FROM candle_cache WHERE interval='1d'
              GROUP BY symbol,interval,trade_date HAVING row_count>1
            )
            """
        ).fetchone()[0]
    finally:
        connection.close()
    return {
        "generated_at": datetime.now().astimezone().isoformat(),
        "base_db": str(base),
        "supplement_db": str(supplement),
        "output_db": str(output),
        "exclude_calendar_days_before_delisting": exclude_calendar_days_before_delisting,
        "categories": list(categories),
        "source_precedence": "base DB wins on canonical symbol/interval/trade-date",
        "canonical_daily_key": "symbol, interval, substr(timestamp,1,10)",
        "eligible_positive_volume_supplement_rows": int(eligible_rows),
        "zero_volume_suspension_rows_excluded": int(zero_volume_rows),
        "same_date_supplement_rows_skipped": int(date_overlap_rows),
        "inserted_rows": inserted_rows,
        "eligible_supplement_symbols": int(insertable_symbols),
        "merged_daily_rows": int(audit[0]),
        "merged_symbols": int(audit[1]),
        "first_date": audit[2],
        "last_date": audit[3],
        "old_only_symbols": int(old_only),
        "duplicate_symbol_dates": int(duplicate_symbol_dates),
        "integrity_passed": duplicate_symbol_dates == 0
        and inserted_rows == eligible_rows - date_overlap_rows,
        "live_database_modified": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build an isolated delisted-inclusive research candle DB"
    )
    parser.add_argument("--base-db", default=DEFAULT_BASE)
    parser.add_argument("--supplement-db", default=DEFAULT_SUPPLEMENT)
    parser.add_argument("--output-db", required=True)
    parser.add_argument("--exclude-calendar-days-before-delisting", type=int, default=0)
    parser.add_argument("--categories", default="")
    parser.add_argument("--replace", action="store_true")
    parser.add_argument("--audit-out")
    args = parser.parse_args()
    categories = tuple(value for value in args.categories.split(",") if value)
    payload = build_merged_database(
        args.base_db,
        args.supplement_db,
        args.output_db,
        exclude_calendar_days_before_delisting=args.exclude_calendar_days_before_delisting,
        categories=categories,
        replace=args.replace,
    )
    audit_out = Path(
        args.audit_out or f"{args.output_db}.audit.json"
    )
    audit_out.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
