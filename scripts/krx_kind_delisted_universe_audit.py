#!/usr/bin/env python3
"""Audit survivor bias with the official KIND KOSDAQ delisting registry.

This research-only collector never imports the live trader and never calls an
order endpoint. It stores public delisting metadata, not raw account data.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime
from html.parser import HTMLParser
from http.cookiejar import CookieJar
from pathlib import Path
from typing import Any


LIST_URL = "https://kind.krx.co.kr/investwarn/delcompany.do"
SUMMARY_URL = "https://kind.krx.co.kr/common/companysummary.do"
DEFAULT_DB = "data/edge_research_universe_15y.sqlite3"
DEFAULT_OUT = (
    "data/kr_foreign_microstructure_research/"
    "krx_kind_delisted_universe_audit.json"
)


def _clean(parts: list[str]) -> str:
    return " ".join(" ".join(parts).split())


class DelistedListParser(HTMLParser):
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
            if self._issuer_code and len(self._cells) >= 4:
                self.rows.append(
                    {
                        "issuer_code": self._issuer_code,
                        "company_name": self._company_name or self._cells[1],
                        "market": self._market or "unknown",
                        "delisting_date": self._cells[2],
                        "reason": self._cells[3],
                        "note": self._cells[4] if len(self._cells) >= 5 else "",
                    }
                )
            self._in_row = False
        elif tag == "div" and self._in_info:
            match = re.search(r"전체\s*([0-9,]+)\s*건", _clean(self._info_parts))
            if match:
                self.total_count = int(match.group(1).replace(",", ""))
            self._in_info = False


class CompanySummaryParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.cells: list[tuple[str, str]] = []
        self._cell_tag: str | None = None
        self._parts: list[str] = []

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        if tag in {"th", "td"}:
            self._cell_tag = tag
            self._parts = []

    def handle_data(self, data: str) -> None:
        if self._cell_tag is not None:
            self._parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if self._cell_tag == tag:
            self.cells.append((tag, _clean(self._parts)))
            self._cell_tag = None

    def fields(self) -> dict[str, str]:
        result: dict[str, str] = {}
        for index, (tag, label) in enumerate(self.cells[:-1]):
            if tag != "th":
                continue
            next_tag, value = self.cells[index + 1]
            if next_tag == "td":
                result[label] = value
        return result


def parse_delisted_list(html: str) -> tuple[list[dict[str, str]], int | None]:
    parser = DelistedListParser()
    parser.feed(html)
    return parser.rows, parser.total_count


def parse_company_summary(html: str) -> dict[str, str]:
    parser = CompanySummaryParser()
    parser.feed(html)
    fields = parser.fields()
    return {
        "ticker": fields.get("종목코드", ""),
        "isin": fields.get("표준코드", ""),
        "listed_date": fields.get("상장일", ""),
        "summary_market": fields.get("시장구분", ""),
    }


def classify_delisting(company_name: str, reason: str) -> str:
    if "스팩" in company_name:
        return "spac"
    if any(word in reason for word in ("피흡수합병", "합병", "완전자회사", "주식교환")):
        return "corporate_action"
    if "자진" in reason:
        return "voluntary"
    distress_terms = (
        "감사의견",
        "계속성",
        "경영의 투명성",
        "파산",
        "부도",
        "자본잠식",
        "사업보고서",
        "해산",
        "상장폐지기준",
    )
    if any(word in reason for word in distress_terms):
        return "distress_or_enforcement"
    return "other"


class KindClient:
    def __init__(self, *, timeout: float = 30.0) -> None:
        self.timeout = timeout
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(CookieJar())
        )

    def post(self, url: str, data: dict[str, str], *, retries: int = 3) -> str:
        body = urllib.parse.urlencode(data).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=body,
            headers={
                "User-Agent": "toss-auto-trader-lab research audit/1.0",
                "Referer": "https://kind.krx.co.kr/investwarn/delcompany.do?method=searchDelCompanyMain",
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            },
        )
        last_error: Exception | None = None
        for attempt in range(retries):
            try:
                with self.opener.open(request, timeout=self.timeout) as response:
                    return response.read().decode("utf-8", errors="replace")
            except (urllib.error.URLError, TimeoutError) as exc:
                last_error = exc
                if attempt + 1 < retries:
                    time.sleep(0.5 * (attempt + 1))
        raise RuntimeError(f"KIND request failed after {retries} attempts") from last_error

    def delisted_list(
        self, *, from_date: str, to_date: str, market_type: str = "2"
    ) -> tuple[list[dict[str, str]], int | None]:
        html = self.post(
            LIST_URL,
            {
                "method": "searchDelCompanySub",
                "forward": "delcompany_sub",
                "currentPageSize": "3000",
                "pageIndex": "1",
                "orderMode": "2",
                "orderStat": "D",
                "tabType": "1",
                "marketType": market_type,
                "fromDate": from_date,
                "toDate": to_date,
            },
        )
        return parse_delisted_list(html)

    def company_summary(self, issuer_code: str) -> dict[str, str]:
        html = self.post(
            SUMMARY_URL,
            {
                "method": "searchCompanySummaryOvrvwDetail",
                "menuIndex": "0",
                "strIsurCd": issuer_code,
                "lstCd": "",
                "methodType": "0",
            },
        )
        return parse_company_summary(html)


def database_symbols(db_path: str) -> dict[str, dict[str, str]]:
    connection = sqlite3.connect(f"file:{Path(db_path).resolve()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(
            """
            SELECT symbol,MIN(substr(timestamp,1,10)) AS first_date,
              MAX(substr(timestamp,1,10)) AS last_date
            FROM candle_cache WHERE interval='1d' GROUP BY symbol
            """
        ).fetchall()
    finally:
        connection.close()
    return {
        str(row["symbol"]): {
            "first_date": str(row["first_date"]),
            "last_date": str(row["last_date"]),
        }
        for row in rows
    }


def build_audit(
    rows: list[dict[str, str]],
    db_symbols: dict[str, dict[str, str]],
    *,
    registry_total: int | None,
    from_date: str,
    to_date: str,
) -> dict[str, Any]:
    for row in rows:
        row["category"] = classify_delisting(row["company_name"], row["reason"])
        ticker = row.get("ticker", "")
        cached = db_symbols.get(ticker)
        row["present_in_current_cache"] = bool(cached)
        row["cache_first_date"] = cached["first_date"] if cached else ""
        row["cache_last_date"] = cached["last_date"] if cached else ""
        row["ticker_reuse_suspected"] = bool(
            cached and cached["first_date"] > row["delisting_date"]
        )
    valid = [row for row in rows if re.fullmatch(r"[0-9]{6}", row.get("ticker", ""))]
    unique_tickers = {row["ticker"] for row in valid}
    overlap = [row for row in valid if row["present_in_current_cache"]]
    reused = [row for row in overlap if row["ticker_reuse_suspected"]]
    return {
        "generated_at": datetime.now().astimezone().isoformat(),
        "source": {
            "name": "KRX KIND delisted company registry and company summary",
            "list_url": "https://kind.krx.co.kr/investwarn/delcompany.do?method=searchDelCompanyMain",
            "market": "KOSDAQ",
            "window": f"{from_date}~{to_date}",
        },
        "registry_total": registry_total,
        "rows_collected": len(rows),
        "valid_six_digit_tickers": len(valid),
        "unique_tickers": len(unique_tickers),
        "category_counts": dict(Counter(row["category"] for row in rows).most_common()),
        "present_in_current_cache": len(overlap),
        "absent_from_current_cache": len(valid) - len(overlap),
        "ticker_reuse_suspected": len(reused),
        "distress_absent_from_current_cache": sum(
            row["category"] == "distress_or_enforcement"
            and not row["present_in_current_cache"]
            for row in valid
        ),
        "survivorship_bias_resolved": False,
        "interpretation": "The official registry quantifies missing delisted names, but metadata alone cannot reconstruct their historical OHLC or 09:01 fills.",
        "rows": rows,
    }


def _load_cached_details(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return {
        str(row.get("issuer_code")): row
        for row in payload.get("rows", [])
        if row.get("issuer_code") and row.get("ticker")
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Research-only KRX KIND delisted-universe audit"
    )
    parser.add_argument("--from-date", default="2011-01-01")
    parser.add_argument("--to-date", default="2026-07-19")
    parser.add_argument("--db-path", default=DEFAULT_DB)
    parser.add_argument("--out", default=DEFAULT_OUT)
    parser.add_argument("--detail-limit", type=int, default=0)
    parser.add_argument("--request-delay", type=float, default=0.15)
    args = parser.parse_args()

    out = Path(args.out)
    cached = _load_cached_details(out)
    client = KindClient()
    rows, total = client.delisted_list(
        from_date=args.from_date, to_date=args.to_date, market_type="2"
    )
    if args.detail_limit > 0:
        rows = rows[: args.detail_limit]
    failures: list[dict[str, str]] = []
    for index, row in enumerate(rows):
        detail = cached.get(row["issuer_code"])
        if detail is None:
            try:
                detail = client.company_summary(row["issuer_code"])
            except RuntimeError as exc:
                failures.append(
                    {"issuer_code": row["issuer_code"], "error": str(exc)}
                )
                detail = {}
            if index + 1 < len(rows):
                time.sleep(max(0.0, args.request_delay))
        row.update(detail)
    payload = build_audit(
        rows,
        database_symbols(args.db_path),
        registry_total=total,
        from_date=args.from_date,
        to_date=args.to_date,
    )
    payload["detail_failures"] = failures
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "out": str(out),
                "registry_total": total,
                "rows": len(rows),
                "valid_tickers": payload["valid_six_digit_tickers"],
                "absent_from_cache": payload["absent_from_current_cache"],
                "detail_failures": len(failures),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
