#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import replace
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from toss_auto_trader.config import Settings
from toss_auto_trader.news_client import NewsClientError, NewsHub, NewsItem
from toss_auto_trader.news_prefetch import load_latest_prefetch, safe_disclosure_item
from toss_auto_trader.news_risk import assess_news_snapshot, parse_news_timestamp
from toss_auto_trader.toss_client import TossInvestClient


KST = ZoneInfo("Asia/Seoul")
STRATEGY_NAME = "robust_gap5_news_risk_shadow_v1"
DEFAULT_AUDIT = Path("logs/simple_gap_entry_price_audit.jsonl")
DEFAULT_OUTPUT = Path("logs/simple_gap_news_shadow.jsonl")


def _positive_float(value: object) -> float | None:
    try:
        parsed = float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def load_candidate_snapshot(path: Path, trade_date: str) -> dict[str, Any]:
    candidates: dict[str, dict[str, Any]] = {}
    ranks: dict[str, int] = {}
    timestamps: list[datetime] = []
    selected_at: datetime | None = None
    parse_errors = 0
    if not path.exists():
        return {
            "candidates": [],
            "decision_at": None,
            "audit_file_exists": False,
            "parse_errors": 0,
        }
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        if not raw_line.strip():
            continue
        try:
            row = json.loads(raw_line)
        except json.JSONDecodeError:
            parse_errors += 1
            continue
        if not isinstance(row, dict) or row.get("trade_date") != trade_date:
            continue
        symbol = str(row.get("symbol") or "").strip()
        captured = parse_news_timestamp(row.get("captured_at"))
        if captured is not None:
            timestamps.append(captured)
        if symbol and row.get("decision") == "candidate" and _positive_float(row.get("first_minute_open")):
            candidates[symbol] = row
        rank = row.get("candidate_rank")
        if symbol and isinstance(rank, int):
            ranks[symbol] = rank
        if row.get("decision") == "selected_for_order" and captured is not None:
            selected_at = captured

    ordered = sorted(
        candidates.values(),
        key=lambda row: (
            ranks.get(str(row.get("symbol") or ""), 999999),
            _positive_float(row.get("first_minute_open")) or float("inf"),
            str(row.get("symbol") or ""),
        ),
    )
    for fallback_rank, row in enumerate(ordered, start=1):
        row["candidate_rank"] = ranks.get(str(row.get("symbol") or ""), fallback_rank)
    decision_at = selected_at or (max(timestamps) if timestamps else None)
    return {
        "candidates": ordered,
        "decision_at": decision_at.isoformat() if decision_at else None,
        "audit_file_exists": True,
        "parse_errors": parse_errors,
    }


def _stock_names(client: TossInvestClient, symbols: list[str]) -> dict[str, str]:
    if not symbols:
        return {}
    rows = client.get_stocks(symbols).get("result", [])
    return {
        str(row.get("symbol")): str(row.get("name") or row.get("symbol"))
        for row in rows
        if row.get("symbol")
    }


def _safe_item_metadata(item: object) -> dict[str, Any]:
    if isinstance(item, dict):
        return {
            key: item.get(key)
            for key in (
                "provider",
                "title",
                "url",
                "source",
                "published_at",
                "summary",
                "observed_at",
                "stock_code",
            )
        }
    if not isinstance(item, NewsItem):
        return {}
    return {
        "provider": item.provider,
        "title": item.title,
        "url": item.url,
        "source": item.source,
        "published_at": item.published_at,
        "summary": item.summary,
    }


def _append_snapshot(path: Path, snapshot: dict[str, Any]) -> bool:
    key = (snapshot.get("trade_date"), snapshot.get("decision_at"), tuple(snapshot.get("providers", [])))
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            row_key = (row.get("trade_date"), row.get("decision_at"), tuple(row.get("providers", [])))
            if row_key == key:
                return False
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(snapshot, ensure_ascii=False, sort_keys=True) + "\n")
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Paper-only news/disclosure risk snapshot; never sends orders")
    parser.add_argument("--date", default=date.today().isoformat())
    parser.add_argument("--audit", type=Path, default=DEFAULT_AUDIT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--prefetch", type=Path, default=Path("logs/simple_gap_news_prefetch.jsonl"))
    parser.add_argument("--providers", default="naver,opendart")
    parser.add_argument("--max-candidates", type=int, default=10)
    parser.add_argument("--news-limit", type=int, default=10)
    parser.add_argument("--naver-query-interval", type=float, default=0.8)
    parser.add_argument("--max-age-hours", type=float, default=72.0)
    parser.add_argument("--decision-at")
    parser.add_argument("--print-only", action="store_true")
    args = parser.parse_args(argv)

    loaded = load_candidate_snapshot(args.audit, args.date)
    candidates = loaded["candidates"][: max(0, args.max_candidates)]
    decision_at = args.decision_at or loaded.get("decision_at")
    if decision_at is None:
        decision_at = f"{args.date}T09:01:00+09:00"
    decision_timestamp = parse_news_timestamp(decision_at)
    if decision_timestamp is None:
        parser.error("--decision-at must be an ISO/RFC timestamp")
    decision_at = decision_timestamp.isoformat()
    providers = [item.strip() for item in args.providers.split(",") if item.strip()]
    settings = replace(Settings.from_env(), dry_run=True, live_trading=False)
    toss_client = TossInvestClient(settings)
    hub = NewsHub()
    symbols = [str(row["symbol"]) for row in candidates]
    names = _stock_names(toss_client, symbols)
    provider_status: dict[str, Any] = {}

    for provider in providers:
        if provider not in {"naver", "opendart"}:
            provider_status[provider] = {"items": 0, "errors": ["unsupported provider"]}

    naver_items: dict[str, list[NewsItem]] = {symbol: [] for symbol in symbols}
    if "naver" in providers:
        naver_errors = []
        for index, symbol in enumerate(symbols):
            name = names.get(symbol, symbol)
            try:
                naver_items[symbol] = hub.naver_news(name, display=args.news_limit, sort="date")
            except Exception as exc:
                naver_errors.append({"symbol": symbol, "error": str(exc)[:300]})
            if index + 1 < len(symbols) and args.naver_query_interval > 0:
                time.sleep(args.naver_query_interval)
        provider_status["naver"] = {
            "queries": len(symbols),
            "items": sum(len(rows) for rows in naver_items.values()),
            "errors": naver_errors,
        }

    dart_items: list[dict[str, Any]] = []
    if "opendart" in providers:
        prefetched = load_latest_prefetch(
            args.prefetch,
            trade_date=args.date,
            decision_at=decision_at,
            provider="opendart",
        )
        if prefetched is not None:
            dart_items = [item for item in prefetched.get("items", []) if isinstance(item, dict)]
            provider_status["opendart"] = {
                "items": len(dart_items),
                "errors": [],
                "source": "preopen_prefetch",
                "observed_at": prefetched.get("observed_at"),
                "point_in_time_valid": True,
            }
        else:
            begin = (date.fromisoformat(args.date) - timedelta(days=3)).isoformat()
            try:
                fetched = hub.opendart_disclosures(begin_date=begin, end_date=args.date, corp_class="K")
                dart_observed_at = datetime.now(KST).isoformat()
                dart_items = [safe_disclosure_item(item, dart_observed_at) for item in fetched]
                provider_status["opendart"] = {
                    "items": len(dart_items),
                    "errors": [],
                    "source": "live_query_without_prefetch",
                    "observed_at": dart_observed_at,
                    "point_in_time_valid": parse_news_timestamp(dart_observed_at) <= decision_timestamp,
                }
            except NewsClientError as exc:
                provider_status["opendart"] = {"items": 0, "errors": [str(exc)]}
            except Exception as exc:
                provider_status["opendart"] = {"items": 0, "errors": [str(exc)[:300]]}

    # Use the completion time so a pre-open request finishing after the order
    # decision can never be mislabeled as a point-in-time observation.
    observed_at = datetime.now(KST).isoformat()
    assessments = []
    for candidate in candidates:
        symbol = str(candidate["symbol"])
        name = names.get(symbol, symbol)
        matched_dart = [
            item for item in dart_items if str(item.get("stock_code") or "") == symbol
        ]
        items = naver_items.get(symbol, []) + matched_dart
        assessment = assess_news_snapshot(
            [_safe_item_metadata(item) for item in items],
            decision_at=decision_at,
            observed_at=observed_at,
            entity_names=[name],
            max_age_hours=args.max_age_hours,
        )
        assessments.append(
            {
                "symbol": symbol,
                "name": name,
                "candidate_rank": candidate.get("candidate_rank"),
                "first_minute_open": _positive_float(candidate.get("first_minute_open")),
                "assessment": assessment,
            }
        )

    counts = {
        decision: sum(row["assessment"]["shadow_decision"] == decision for row in assessments)
        for decision in ("risk_veto", "manual_review", "no_veto_evidence", "no_eligible_news")
    }
    coverage_complete = all(
        provider in provider_status and not provider_status[provider].get("errors")
        for provider in providers
    )
    snapshot = {
        "strategy_name": STRATEGY_NAME,
        "trade_date": args.date,
        "decision_at": decision_at,
        "observed_at": observed_at,
        "providers": providers,
        "provider_status": provider_status,
        "coverage_complete": coverage_complete,
        "candidate_count": len(candidates),
        "counts": counts,
        "candidates": assessments,
        "paper_only": True,
        "order_sent": False,
        "live_order_allowed": False,
        "strategy_alpha_claim": False,
        "policy": {
            "official_disclosure_hard_negative_can_only_create_a_shadow_veto": True,
            "positive_news_never_approves_a_live_order": True,
            "absence_of_news_is_not_a_safety_signal": True,
            "provider_failure_is_not_a_safety_signal": True,
            "observed_after_decision_is_not_promotion_eligible": True,
        },
        "audit": {key: value for key, value in loaded.items() if key != "candidates"},
    }
    written = False if args.print_only else _append_snapshot(args.output, snapshot)
    output = {**snapshot, "output": str(args.output), "written": written, "print_only": args.print_only}
    print(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
