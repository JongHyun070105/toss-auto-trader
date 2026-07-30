from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from .news_risk import parse_news_timestamp


PREFETCH_VERSION = "opendart_kosdaq_prefetch_v1"


def safe_disclosure_item(item: object, observed_at: str) -> dict[str, Any]:
    if isinstance(item, dict):
        data = item
    else:
        as_dict = getattr(item, "as_dict", None)
        data = as_dict() if callable(as_dict) else {}
    raw = data.get("raw") if isinstance(data.get("raw"), dict) else {}
    return {
        "provider": "opendart",
        "stock_code": str(raw.get("stock_code") or data.get("stock_code") or ""),
        "corp_name": str(raw.get("corp_name") or data.get("corp_name") or ""),
        "title": str(data.get("title") or ""),
        "url": str(data.get("url") or ""),
        "source": str(data.get("source") or "FSS OpenDART"),
        "published_at": data.get("published_at"),
        "summary": str(data.get("summary") or raw.get("corp_name") or ""),
        "observed_at": observed_at,
    }


def build_prefetch_snapshot(
    items: Iterable[object],
    *,
    trade_date: str,
    observed_at: str,
    begin_date: str,
    end_date: str,
) -> dict[str, Any]:
    disclosures = [safe_disclosure_item(item, observed_at) for item in items]
    return {
        "version": PREFETCH_VERSION,
        "trade_date": trade_date,
        "provider": "opendart",
        "observed_at": observed_at,
        "begin_date": begin_date,
        "end_date": end_date,
        "complete": True,
        "items": disclosures,
        "item_count": len(disclosures),
        "paper_only": True,
        "order_sent": False,
        "live_order_allowed": False,
    }


def append_prefetch_snapshot(path: Path, snapshot: dict[str, Any]) -> bool:
    key = (
        snapshot.get("version"),
        snapshot.get("trade_date"),
        snapshot.get("provider"),
        snapshot.get("observed_at"),
    )
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if (
                row.get("version"),
                row.get("trade_date"),
                row.get("provider"),
                row.get("observed_at"),
            ) == key:
                return False
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(snapshot, ensure_ascii=False, sort_keys=True) + "\n")
    return True


def load_latest_prefetch(
    path: Path,
    *,
    trade_date: str,
    decision_at: object,
    provider: str = "opendart",
) -> dict[str, Any] | None:
    decision = parse_news_timestamp(decision_at)
    if decision is None or not path.exists():
        return None
    eligible: list[tuple[object, dict[str, Any]]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict):
            continue
        if row.get("trade_date") != trade_date or row.get("provider") != provider or not row.get("complete"):
            continue
        observed = parse_news_timestamp(row.get("observed_at"))
        if observed is not None and observed <= decision:
            eligible.append((observed, row))
    return max(eligible, key=lambda pair: pair[0])[1] if eligible else None
