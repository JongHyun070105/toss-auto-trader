#!/usr/bin/env python3
"""Build a research-only delisted-candle supplement from Naver chart data."""
from __future__ import annotations

import argparse
import json
import math
import sqlite3
import statistics
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_KIND_AUDIT = (
    "data/kr_foreign_microstructure_research/"
    "krx_kind_delisted_universe_audit.json"
)
DEFAULT_DB = (
    "data/kr_foreign_microstructure_research/"
    "naver_delisted_candles.sqlite3"
)
DEFAULT_AUDIT = (
    "data/kr_foreign_microstructure_research/"
    "naver_delisted_candle_audit.json"
)
DEFAULT_BASE_DB = "data/edge_research_universe_15y.sqlite3"
CHART_URL = "https://fchart.stock.naver.com/sise.nhn"


def parse_chart_xml(payload: bytes) -> tuple[dict[str, str], list[dict[str, Any]]]:
    text = payload.decode("euc-kr", errors="replace")
    declaration_end = text.find("?>")
    if text.lstrip().startswith("<?xml") and declaration_end >= 0:
        text = text[declaration_end + 2 :]
    root = ET.fromstring(text)
    chart = root.find("chartdata")
    if chart is None:
        raise ValueError("chartdata element is missing")
    metadata = {key: str(value) for key, value in chart.attrib.items()}
    rows: list[dict[str, Any]] = []
    for item in chart.findall("item"):
        parts = str(item.attrib.get("data", "")).split("|")
        if len(parts) != 6:
            continue
        date, open_price, high_price, low_price, close_price, volume = parts
        try:
            rows.append(
                {
                    "date": f"{date[:4]}-{date[4:6]}-{date[6:8]}",
                    "open": float(open_price),
                    "high": float(high_price),
                    "low": float(low_price),
                    "close": float(close_price),
                    "volume": float(volume),
                }
            )
        except ValueError:
            continue
    return metadata, rows


def normalize_row(row: dict[str, Any]) -> tuple[dict[str, Any] | None, bool]:
    values = {key: float(row[key]) for key in ("open", "high", "low", "close", "volume")}
    if not all(math.isfinite(value) for value in values.values()):
        return None, False
    if values["close"] <= 0 or values["volume"] < 0:
        return None, False
    normalized = False
    if (
        values["volume"] == 0
        and values["open"] == 0
        and values["high"] == 0
        and values["low"] == 0
    ):
        values["open"] = values["close"]
        values["high"] = values["close"]
        values["low"] = values["close"]
        normalized = True
    if (
        values["open"] <= 0
        or values["low"] <= 0
        or values["high"] < max(values["open"], values["close"])
        or values["low"] > min(values["open"], values["close"])
    ):
        return None, normalized
    return {"date": str(row["date"]), **values}, normalized


class NaverChartClient:
    def __init__(self, *, timeout: float = 30.0) -> None:
        self.timeout = timeout

    def fetch(self, ticker: str, *, count: int = 6000, retries: int = 3) -> bytes:
        query = urllib.parse.urlencode(
            {
                "symbol": ticker,
                "timeframe": "day",
                "count": str(count),
                "requestType": "0",
            }
        )
        request = urllib.request.Request(
            f"{CHART_URL}?{query}",
            headers={"User-Agent": "toss-auto-trader-lab research audit/1.0"},
        )
        last_error: Exception | None = None
        for attempt in range(retries):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    return response.read()
            except (urllib.error.URLError, TimeoutError) as exc:
                last_error = exc
                if attempt + 1 < retries:
                    time.sleep(0.5 * (attempt + 1))
        raise RuntimeError(f"Naver chart request failed for {ticker}") from last_error


def initialize_database(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS candle_cache (
          symbol TEXT NOT NULL,
          interval TEXT NOT NULL,
          timestamp TEXT NOT NULL,
          open_price TEXT NOT NULL,
          high_price TEXT NOT NULL,
          low_price TEXT NOT NULL,
          close_price TEXT NOT NULL,
          volume TEXT NOT NULL,
          currency TEXT NOT NULL,
          raw_json TEXT NOT NULL,
          fetched_at TEXT NOT NULL,
          PRIMARY KEY(symbol, interval, timestamp)
        );
        CREATE INDEX IF NOT EXISTS idx_candle_cache_symbol_interval_time
          ON candle_cache(symbol, interval, timestamp);
        CREATE TABLE IF NOT EXISTS delisted_source_metadata (
          symbol TEXT PRIMARY KEY,
          issuer_code TEXT NOT NULL,
          company_name TEXT NOT NULL,
          category TEXT NOT NULL,
          listed_date TEXT NOT NULL,
          delisting_date TEXT NOT NULL,
          source_name TEXT NOT NULL,
          status TEXT NOT NULL,
          fetched_rows INTEGER NOT NULL,
          normalized_suspension_rows INTEGER NOT NULL,
          rejected_rows INTEGER NOT NULL,
          fetched_at TEXT NOT NULL
        );
        """
    )


def _number_text(value: float) -> str:
    return str(int(value)) if value.is_integer() else format(value, ".12g")


def store_symbol(
    connection: sqlite3.Connection,
    registry_row: dict[str, Any],
    chart_metadata: dict[str, str],
    chart_rows: list[dict[str, Any]],
    *,
    start: str,
    fetched_at: str,
) -> dict[str, Any]:
    ticker = str(registry_row["ticker"])
    delisting_date = str(registry_row["delisting_date"])
    accepted: list[tuple[str, ...]] = []
    normalized_count = 0
    rejected_count = 0
    for raw in chart_rows:
        if not (start <= str(raw["date"]) <= delisting_date):
            continue
        normalized, was_normalized = normalize_row(raw)
        if normalized is None:
            rejected_count += 1
            continue
        normalized_count += was_normalized
        accepted.append(
            (
                ticker,
                "1d",
                normalized["date"],
                _number_text(normalized["open"]),
                _number_text(normalized["high"]),
                _number_text(normalized["low"]),
                _number_text(normalized["close"]),
                _number_text(normalized["volume"]),
                "KRW",
                json.dumps(
                    {
                        "source": "naver_fchart",
                        "normalized_suspension_ohlc": was_normalized,
                    },
                    ensure_ascii=False,
                ),
                fetched_at,
            )
        )
    connection.execute("DELETE FROM candle_cache WHERE symbol=?", (ticker,))
    connection.executemany(
        "INSERT INTO candle_cache VALUES (?,?,?,?,?,?,?,?,?,?,?)", accepted
    )
    status = "ok" if accepted else "empty"
    connection.execute(
        """
        INSERT OR REPLACE INTO delisted_source_metadata VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            ticker,
            str(registry_row["issuer_code"]),
            str(registry_row["company_name"]),
            str(registry_row["category"]),
            str(registry_row.get("listed_date") or chart_metadata.get("origintime") or ""),
            delisting_date,
            "naver_fchart_with_kind_registry_bounds",
            status,
            len(accepted),
            normalized_count,
            rejected_count,
            fetched_at,
        ),
    )
    return {
        "status": status,
        "rows": len(accepted),
        "normalized": normalized_count,
        "rejected": rejected_count,
    }


def mark_skipped_reuse(
    connection: sqlite3.Connection, registry_row: dict[str, Any], fetched_at: str
) -> None:
    connection.execute(
        "INSERT OR REPLACE INTO delisted_source_metadata VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            str(registry_row["ticker"]),
            str(registry_row["issuer_code"]),
            str(registry_row["company_name"]),
            str(registry_row["category"]),
            str(registry_row.get("listed_date") or ""),
            str(registry_row["delisting_date"]),
            "naver_fchart_with_kind_registry_bounds",
            "skipped_ticker_reuse",
            0,
            0,
            0,
            fetched_at,
        ),
    )


def overlap_quality(
    supplement_db: str, base_db: str
) -> dict[str, Any]:
    connection = sqlite3.connect(supplement_db)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("ATTACH DATABASE ? AS base", (str(Path(base_db).resolve()),))
        rows = connection.execute(
            """
            SELECT s.symbol,substr(s.timestamp,1,10) AS date,
              CAST(s.open_price AS REAL) AS s_open,
              CAST(s.high_price AS REAL) AS s_high,
              CAST(s.low_price AS REAL) AS s_low,
              CAST(s.close_price AS REAL) AS s_close,
              CAST(s.volume AS REAL) AS s_volume,
              CAST(b.open_price AS REAL) AS b_open,
              CAST(b.high_price AS REAL) AS b_high,
              CAST(b.low_price AS REAL) AS b_low,
              CAST(b.close_price AS REAL) AS b_close,
              CAST(b.volume AS REAL) AS b_volume
            FROM candle_cache s
            JOIN base.candle_cache b
              ON b.symbol=s.symbol AND b.interval=s.interval
              AND substr(b.timestamp,1,10)=substr(s.timestamp,1,10)
            WHERE s.interval='1d'
            ORDER BY s.symbol,date
            """
        ).fetchall()
    finally:
        connection.close()
    price_exact = 0
    volume_exact = 0
    volume_relative_errors: list[float] = []
    return_absolute_differences: list[float] = []
    gap_absolute_differences: list[float] = []
    symbols: set[str] = set()
    previous: dict[str, tuple[float, float]] = {}
    for row in rows:
        symbol = str(row["symbol"])
        symbols.add(symbol)
        price_exact += all(
            float(row[f"s_{field}"]) == float(row[f"b_{field}"])
            for field in ("open", "high", "low", "close")
        )
        volume_exact += float(row["s_volume"]) == float(row["b_volume"])
        denominator = max(1.0, float(row["b_volume"]))
        volume_relative_errors.append(
            abs(float(row["s_volume"]) - float(row["b_volume"])) / denominator
        )
        if symbol in previous:
            previous_s, previous_b = previous[symbol]
            if previous_s > 0 and previous_b > 0:
                return_absolute_differences.append(
                    abs(
                        float(row["s_close"]) / previous_s
                        - float(row["b_close"]) / previous_b
                    )
                )
                gap_absolute_differences.append(
                    abs(
                        float(row["s_open"]) / previous_s
                        - float(row["b_open"]) / previous_b
                    )
                )
        previous[symbol] = (float(row["s_close"]), float(row["b_close"]))

    def percentile(values: list[float], probability: float) -> float | None:
        if not values:
            return None
        ordered = sorted(values)
        return ordered[min(len(ordered) - 1, int(probability * len(ordered)))]

    return {
        "overlap_rows": len(rows),
        "overlap_symbols": len(symbols),
        "exact_ohlc_share": price_exact / len(rows) if rows else None,
        "exact_volume_share": volume_exact / len(rows) if rows else None,
        "median_volume_relative_error": statistics.median(volume_relative_errors)
        if volume_relative_errors
        else None,
        "p90_volume_relative_error": percentile(volume_relative_errors, 0.9),
        "mean_return_absolute_difference": statistics.fmean(
            return_absolute_differences
        )
        if return_absolute_differences
        else None,
        "p90_return_absolute_difference": percentile(
            return_absolute_differences, 0.9
        ),
        "mean_gap_absolute_difference": statistics.fmean(gap_absolute_differences)
        if gap_absolute_differences
        else None,
        "p90_gap_absolute_difference": percentile(gap_absolute_differences, 0.9),
        "same_vendor_claim": False,
    }


def summarize_database(db_path: str, base_db: str) -> dict[str, Any]:
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    try:
        statuses = connection.execute(
            "SELECT status,COUNT(*) AS count FROM delisted_source_metadata GROUP BY status"
        ).fetchall()
        categories = connection.execute(
            """
            SELECT category,COUNT(*) AS symbols,SUM(fetched_rows) AS rows
            FROM delisted_source_metadata WHERE status='ok' GROUP BY category
            """
        ).fetchall()
        totals = connection.execute(
            """
            SELECT COUNT(DISTINCT symbol) AS symbols,COUNT(*) AS rows,
              MIN(substr(timestamp,1,10)) AS first_date,
              MAX(substr(timestamp,1,10)) AS last_date
            FROM candle_cache WHERE interval='1d'
            """
        ).fetchone()
        normalization = connection.execute(
            """
            SELECT SUM(normalized_suspension_rows) AS normalized,
              SUM(rejected_rows) AS rejected FROM delisted_source_metadata
            """
        ).fetchone()
    finally:
        connection.close()
    return {
        "source": {
            "candle_url": CHART_URL,
            "registry": "KRX KIND delisted company registry",
        },
        "statuses": {str(row["status"]): int(row["count"]) for row in statuses},
        "categories": {
            str(row["category"]): {
                "symbols": int(row["symbols"]),
                "rows": int(row["rows"] or 0),
            }
            for row in categories
        },
        "symbols": int(totals["symbols"] or 0),
        "rows": int(totals["rows"] or 0),
        "first_date": totals["first_date"],
        "last_date": totals["last_date"],
        "normalized_suspension_rows": int(normalization["normalized"] or 0),
        "rejected_rows": int(normalization["rejected"] or 0),
        "overlap_quality_vs_toss_cache": overlap_quality(db_path, base_db),
        "sufficient_to_remove_survivorship_bias": False,
        "limits": [
            "Naver is a secondary source and may revise adjusted prices or volumes.",
            "Historical KRX warning, VI, halt reason, and executable 09:01 quotes remain unavailable.",
            "Ticker reuse is excluded rather than guessed.",
            "This supplement is research-only and is never read by the live trader.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Research-only Naver delisted candle supplement"
    )
    parser.add_argument("--kind-audit", default=DEFAULT_KIND_AUDIT)
    parser.add_argument("--db-path", default=DEFAULT_DB)
    parser.add_argument("--audit-out", default=DEFAULT_AUDIT)
    parser.add_argument("--base-db", default=DEFAULT_BASE_DB)
    parser.add_argument("--start", default="2010-01-01")
    parser.add_argument("--symbol-limit", type=int, default=0)
    parser.add_argument("--request-delay", type=float, default=0.15)
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()

    registry = json.loads(Path(args.kind_audit).read_text(encoding="utf-8"))
    rows = list(registry["rows"])
    if args.symbol_limit > 0:
        rows = rows[: args.symbol_limit]
    db_path = Path(args.db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    initialize_database(connection)
    completed = {
        str(row[0])
        for row in connection.execute(
            "SELECT symbol FROM delisted_source_metadata WHERE status IN ('ok','empty','skipped_ticker_reuse')"
        )
    }
    client = NaverChartClient()
    failures: list[dict[str, str]] = []
    fetched = 0
    for registry_row in rows:
        ticker = str(registry_row["ticker"])
        if registry_row.get("ticker_reuse_suspected"):
            mark_skipped_reuse(
                connection, registry_row, datetime.now().astimezone().isoformat()
            )
            connection.commit()
            continue
        if ticker in completed and not args.refresh:
            continue
        try:
            metadata, chart_rows = parse_chart_xml(client.fetch(ticker))
            if metadata.get("symbol") != ticker:
                raise ValueError("chart symbol mismatch")
            store_symbol(
                connection,
                registry_row,
                metadata,
                chart_rows,
                start=args.start,
                fetched_at=datetime.now().astimezone().isoformat(),
            )
            connection.commit()
            fetched += 1
        except (RuntimeError, ValueError, ET.ParseError) as exc:
            failures.append({"ticker": ticker, "error": str(exc)})
        if fetched and fetched < len(rows):
            time.sleep(max(0.0, args.request_delay))
    connection.close()

    audit = summarize_database(str(db_path), args.base_db)
    audit["generated_at"] = datetime.now().astimezone().isoformat()
    audit["kind_registry_total"] = registry.get("registry_total")
    audit["request_failures"] = failures
    audit_path = Path(args.audit_out)
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    audit_path.write_text(
        json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "db": str(db_path),
                "symbols": audit["symbols"],
                "rows": audit["rows"],
                "fetched_this_run": fetched,
                "failures": len(failures),
                "audit": str(audit_path),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
