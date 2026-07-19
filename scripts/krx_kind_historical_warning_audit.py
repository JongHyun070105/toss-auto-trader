#!/usr/bin/env python3
"""Collect point-in-time KOSDAQ warning intervals from official KRX KIND.

This is a research-only collector. It downloads public designation metadata and
resolves KIND issuer identifiers to six-digit stock codes. It never imports the
live trader and never calls a broker or order endpoint.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import time
from collections import Counter
from datetime import date, datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterable

from krx_kind_delisted_universe_audit import KindClient


LIST_URL = "https://kind.krx.co.kr/investwarn/investattentwarnrisky.do"
MAIN_URL = (
    "https://kind.krx.co.kr/investwarn/"
    "investattentwarnrisky.do?method=investattentwarnriskyMain"
)
DEFAULT_OUT = (
    "data/kr_foreign_microstructure_research/"
    "krx_kind_historical_warning_audit.json"
)
DEFAULT_DETAIL_CACHE = (
    "data/kr_foreign_microstructure_research/"
    "krx_kind_delisted_universe_audit.json"
)
PAGE_SIZE = 3000

CATEGORY_CONFIG = {
    "attention": {
        "menu_index": "1",
        "order_mode": "4",
        "forward": "invstcautnisu_sub",
        "label": "투자주의",
    },
    "warning": {
        "menu_index": "2",
        "order_mode": "3",
        "forward": "invstwarnisu_sub",
        "label": "투자경고",
    },
    "risk": {
        "menu_index": "3",
        "order_mode": "3",
        "forward": "invstriskisu_sub",
        "label": "투자위험",
    },
}


def _clean(parts: list[str]) -> str:
    return " ".join(" ".join(parts).split())


class WarningListParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[dict[str, str]] = []
        self.total_count: int | None = None
        self._in_row = False
        self._in_cell = False
        self._in_info = False
        self._cell_parts: list[str] = []
        self._cells: list[str] = []
        self._issuer_code: str | None = None
        self._company_name: str | None = None
        self._market: str | None = None
        self._info_parts: list[str] = []

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        values = dict(attrs)
        if tag == "tr":
            self._in_row = True
            self._cells = []
            self._issuer_code = None
            self._company_name = None
            self._market = None
        elif tag == "td" and self._in_row:
            self._in_cell = True
            self._cell_parts = []
        elif tag == "a" and self._in_row:
            onclick = values.get("onclick") or ""
            match = re.search(r"companysummary_open\('([^']+)'", onclick)
            if match:
                self._issuer_code = match.group(1)
                self._company_name = values.get("title")
        elif tag == "img" and self._in_row and self._in_cell:
            alt = values.get("alt") or ""
            if alt in {"코스닥", "유가증권", "코넥스"}:
                self._market = alt
        elif tag == "div" and "info" in (values.get("class") or "").split():
            self._in_info = True
            self._info_parts = []

    def handle_data(self, data: str) -> None:
        if self._in_cell:
            self._cell_parts.append(data)
        if self._in_info:
            self._info_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "td" and self._in_cell:
            self._cells.append(_clean(self._cell_parts))
            self._in_cell = False
        elif tag == "tr" and self._in_row:
            if self._issuer_code and len(self._cells) >= 5:
                self.rows.append(
                    {
                        "issuer_code": self._issuer_code,
                        "company_name": self._company_name or self._cells[1],
                        "market": self._market or "unknown",
                        "detail_column": self._cells[-3],
                        "designation_date": self._cells[-2],
                        "release_date": self._cells[-1],
                    }
                )
            self._in_row = False
        elif tag == "div" and self._in_info:
            match = re.search(r"전체\s*([0-9,]+)\s*건", _clean(self._info_parts))
            if match:
                self.total_count = int(match.group(1).replace(",", ""))
            self._in_info = False


def parse_warning_list(html: str) -> tuple[list[dict[str, str]], int | None]:
    parser = WarningListParser()
    parser.feed(html)
    return parser.rows, parser.total_count


def annotate_category(row: dict[str, str], category: str) -> dict[str, str]:
    config = CATEGORY_CONFIG[category]
    result = dict(row)
    detail = result.pop("detail_column", "")
    result["category"] = category
    result["category_label"] = config["label"]
    if category == "attention":
        result["designation_reason"] = detail
        result["announcement_date"] = ""
    else:
        result["announcement_date"] = detail
        result["designation_reason"] = ""
    return result


def _add_years(value: date, years: int) -> date:
    try:
        return value.replace(year=value.year + years)
    except ValueError:
        return value.replace(month=2, day=28, year=value.year + years)


def three_year_chunks(start: str, end: str) -> list[tuple[str, str]]:
    first = date.fromisoformat(start)
    final = date.fromisoformat(end)
    if first > final:
        raise ValueError("start date must not be after end date")
    chunks: list[tuple[str, str]] = []
    cursor = first
    while cursor <= final:
        chunk_end = min(final, _add_years(cursor, 3) - timedelta(days=1))
        chunks.append((cursor.isoformat(), chunk_end.isoformat()))
        cursor = chunk_end + timedelta(days=1)
    return chunks


class HistoricalWarningClient(KindClient):
    def warning_page(
        self,
        *,
        category: str,
        start_date: str,
        end_date: str,
        page_index: int,
        page_size: int = PAGE_SIZE,
        market_type: str = "2",
    ) -> tuple[list[dict[str, str]], int | None]:
        try:
            config = CATEGORY_CONFIG[category]
        except KeyError as exc:
            raise ValueError(f"unknown warning category: {category}") from exc
        html = self.post(
            LIST_URL,
            {
                "method": "investattentwarnriskySub",
                "currentPageSize": str(page_size),
                "pageIndex": str(page_index),
                "orderMode": config["order_mode"],
                "orderStat": "D",
                "menuIndex": config["menu_index"],
                "forward": config["forward"],
                "marketType": market_type,
                "startDate": start_date,
                "endDate": end_date,
                "searchCorpName": "",
                "repIsuSrtCd": "",
            },
        )
        rows, total = parse_warning_list(html)
        return [annotate_category(row, category) for row in rows], total


def collect_rows(
    client: HistoricalWarningClient,
    *,
    start_date: str,
    end_date: str,
    categories: Iterable[str],
) -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
    rows: list[dict[str, str]] = []
    diagnostics: list[dict[str, Any]] = []
    for category in categories:
        if category not in CATEGORY_CONFIG:
            raise ValueError(f"unknown warning category: {category}")
        for chunk_start, chunk_end in three_year_chunks(start_date, end_date):
            first_page, total = client.warning_page(
                category=category,
                start_date=chunk_start,
                end_date=chunk_end,
                page_index=1,
            )
            chunk_rows = list(first_page)
            page_count = max(1, math.ceil((total or len(first_page)) / PAGE_SIZE))
            for page_index in range(2, page_count + 1):
                page_rows, _ = client.warning_page(
                    category=category,
                    start_date=chunk_start,
                    end_date=chunk_end,
                    page_index=page_index,
                )
                chunk_rows.extend(page_rows)
            diagnostics.append(
                {
                    "category": category,
                    "start_date": chunk_start,
                    "end_date": chunk_end,
                    "reported_total": total,
                    "rows_collected": len(chunk_rows),
                    "pages": page_count,
                    "count_matches": total is not None and total == len(chunk_rows),
                }
            )
            rows.extend(chunk_rows)
    deduplicated: dict[tuple[str, str, str, str, str], dict[str, str]] = {}
    for row in rows:
        key = (
            row["issuer_code"],
            row["category"],
            row.get("announcement_date") or row.get("designation_reason", ""),
            row["designation_date"],
            row["release_date"],
        )
        deduplicated[key] = row
    return list(deduplicated.values()), diagnostics


def _load_cached_details(paths: Iterable[Path]) -> dict[str, dict[str, str]]:
    cached: dict[str, dict[str, str]] = {}
    for path in paths:
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        for row in payload.get("rows", []):
            issuer_code = str(row.get("issuer_code") or "")
            ticker = str(row.get("ticker") or "")
            if issuer_code and re.fullmatch(r"[0-9]{6}", ticker):
                cached[issuer_code] = {
                    "ticker": ticker,
                    "isin": str(row.get("isin") or ""),
                    "listed_date": str(row.get("listed_date") or ""),
                    "summary_market": str(row.get("summary_market") or ""),
                }
    return cached


def resolve_tickers(
    rows: list[dict[str, str]],
    client: HistoricalWarningClient,
    *,
    cached: dict[str, dict[str, str]],
    request_delay: float,
    detail_limit: int = 0,
) -> list[dict[str, str]]:
    failures: list[dict[str, str]] = []
    issuer_codes = sorted({row["issuer_code"] for row in rows})
    unresolved = [code for code in issuer_codes if code not in cached]
    if detail_limit > 0:
        unresolved = unresolved[:detail_limit]
    for index, issuer_code in enumerate(unresolved):
        try:
            detail = client.company_summary(issuer_code)
        except RuntimeError as exc:
            failures.append({"issuer_code": issuer_code, "error": str(exc)})
            detail = {}
        ticker = str(detail.get("ticker") or "")
        if re.fullmatch(r"[0-9]{6}", ticker):
            cached[issuer_code] = detail
        else:
            failures.append(
                {"issuer_code": issuer_code, "error": "six-digit ticker unresolved"}
            )
        if index + 1 < len(unresolved):
            time.sleep(max(0.0, request_delay))
    for row in rows:
        row.update(cached.get(row["issuer_code"], {}))
    return failures


def _valid_date(value: str) -> bool:
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def build_audit(
    rows: list[dict[str, str]],
    chunk_diagnostics: list[dict[str, Any]],
    failures: list[dict[str, str]],
    *,
    start_date: str,
    end_date: str,
) -> dict[str, Any]:
    valid = [
        row
        for row in rows
        if re.fullmatch(r"[0-9]{6}", row.get("ticker", ""))
        and _valid_date(row.get("designation_date", ""))
    ]
    unresolved = sorted(
        {
            row["issuer_code"]
            for row in rows
            if not re.fullmatch(r"[0-9]{6}", row.get("ticker", ""))
        }
    )
    unresolved_rows = [
        row
        for row in rows
        if not re.fullmatch(r"[0-9]{6}", row.get("ticker", ""))
    ]
    unresolved_selection_rows = [
        row
        for row in unresolved_rows
        if row.get("designation_date", "") <= "2023-12-31"
    ]
    designation_dates = [row["designation_date"] for row in valid]
    return {
        "generated_at": datetime.now().astimezone().isoformat(),
        "source": {
            "name": "KRX KIND investment attention, warning, and risk history",
            "url": MAIN_URL,
            "market": "KOSDAQ",
            "window": f"{start_date}~{end_date}",
            "access": "official HTML POST result, collected in <=3-year chunks",
        },
        "rows_collected": len(rows),
        "point_in_time_usable_rows": len(valid),
        "unique_issuer_codes": len({row["issuer_code"] for row in rows}),
        "unique_tickers": len({row["ticker"] for row in valid}),
        "category_counts": dict(Counter(row["category"] for row in rows)),
        "usable_category_counts": dict(Counter(row["category"] for row in valid)),
        "designation_date_min": min(designation_dates) if designation_dates else None,
        "designation_date_max": max(designation_dates) if designation_dates else None,
        "open_ended_release_rows": sum(not row.get("release_date") for row in valid),
        "unresolved_issuer_codes": unresolved,
        "detail_failures": failures,
        "chunk_diagnostics": chunk_diagnostics,
        "all_chunk_counts_match": bool(chunk_diagnostics)
        and all(item["count_matches"] for item in chunk_diagnostics),
        "ticker_resolution_complete": not unresolved,
        "selection_2011_2023_unresolved_rows": len(unresolved_selection_rows),
        "selection_2011_2023_filter_complete": bool(chunk_diagnostics)
        and all(item["count_matches"] for item in chunk_diagnostics)
        and not unresolved_selection_rows,
        "point_in_time_filter_complete": bool(chunk_diagnostics)
        and all(item["count_matches"] for item in chunk_diagnostics)
        and not unresolved,
        "release_boundary_rule": "designation_date <= trade_date < release_date; missing release stays active through requested end",
        "lookahead_rule": "warning/risk announcement dates and attention reasons are retained for audit; filtering begins only on the official designation date",
        "known_limits": [
            "KIND company-summary identifiers are resolved retrospectively and may not fully disambiguate ticker reuse.",
            "The release date is treated as effective before the opening auction; intraday designation timing is not available here.",
            "This endpoint does not reconstruct historical VI, trading halts, order queues, or broker-specific warning payloads.",
        ],
        "rows": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Research-only KRX KIND historical warning interval audit"
    )
    parser.add_argument("--start-date", default="2011-01-01")
    parser.add_argument("--end-date", default="2026-07-19")
    parser.add_argument(
        "--categories", default="attention,warning,risk", help="comma-separated"
    )
    parser.add_argument("--out", default=DEFAULT_OUT)
    parser.add_argument("--detail-cache", default=DEFAULT_DETAIL_CACHE)
    parser.add_argument("--detail-limit", type=int, default=0)
    parser.add_argument("--request-delay", type=float, default=0.1)
    args = parser.parse_args()

    categories = [item.strip() for item in args.categories.split(",") if item.strip()]
    out = Path(args.out)
    client = HistoricalWarningClient()
    rows, diagnostics = collect_rows(
        client,
        start_date=args.start_date,
        end_date=args.end_date,
        categories=categories,
    )
    cached = _load_cached_details([out, Path(args.detail_cache)])
    failures = resolve_tickers(
        rows,
        client,
        cached=cached,
        request_delay=args.request_delay,
        detail_limit=args.detail_limit,
    )
    payload = build_audit(
        rows,
        diagnostics,
        failures,
        start_date=args.start_date,
        end_date=args.end_date,
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "out": str(out),
                "rows": payload["rows_collected"],
                "usable_rows": payload["point_in_time_usable_rows"],
                "unique_tickers": payload["unique_tickers"],
                "unresolved": len(payload["unresolved_issuer_codes"]),
                "complete": payload["point_in_time_filter_complete"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
