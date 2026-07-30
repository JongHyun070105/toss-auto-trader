from __future__ import annotations

import html
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Iterable
from zoneinfo import ZoneInfo


KST = ZoneInfo("Asia/Seoul")

HARD_RISK_RULES = {
    "listing_or_trading": (
        "상장폐지",
        "거래정지",
        "정리매매",
        "관리종목",
        "투자위험",
        "감사의견 거절",
        "의견거절",
    ),
    "capital_or_dilution": (
        "유상증자",
        "감자결정",
        "무상감자",
        "차등감자",
        "전환사채",
        "신주인수권부사채",
    ),
    "financial_distress": (
        "부도",
        "회생절차",
        "파산신청",
        "자본잠식",
        "계속기업 불확실",
    ),
    "misconduct": (
        "횡령",
        "배임",
        "압수수색",
        "검찰 수사",
    ),
}

REVIEW_RISK_RULES = {
    "regulatory_or_legal": ("과징금", "제재", "소송", "불성실공시"),
    "earnings_deterioration": ("적자전환", "영업손실", "순손실", "실적 부진"),
    "market_warning": ("투자경고", "단기과열", "VI 발동", "변동성완화장치"),
}

POSITIVE_CONTEXT_RULES = {
    "commercial": ("공급계약", "수주", "계약 체결"),
    "approval": ("품목허가", "승인", "FDA", "CE 인증"),
    "earnings": ("흑자전환", "호실적", "최대 실적"),
}

RISK_NEGATION_PHRASES = {
    "관리종목": ("관리종목 피한", "관리종목 해제", "관리종목 지정 해제"),
    "거래정지": ("거래정지 해제", "거래 재개"),
    "상장폐지": ("상장폐지 우려 해소", "상폐 위기 탈출"),
    "유상증자": ("유상증자 철회", "유증 철회"),
    "감자결정": ("감자결정 철회",),
    "전환사채": ("전환사채 상환", "CB 상환"),
    "자본잠식": ("자본잠식 해소",),
}

OFFICIAL_DISCLOSURE_PROVIDERS = {"opendart", "kind"}


def parse_news_timestamp(value: object) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    if re.fullmatch(r"\d+(?:\.\d+)?", raw):
        stamp = float(raw)
        if stamp > 10_000_000_000:
            stamp /= 1000.0
        try:
            return datetime.fromtimestamp(stamp, tz=timezone.utc).astimezone(KST)
        except (OSError, OverflowError, ValueError):
            return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = parsedate_to_datetime(raw)
        except (TypeError, ValueError, OverflowError):
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=KST)
    return parsed.astimezone(KST)


def clean_text(value: object) -> str:
    text = re.sub(r"<[^>]+>", " ", html.unescape(str(value or "")))
    return re.sub(r"\s+", " ", text).strip()


def normalize_entity(value: object) -> str:
    text = clean_text(value).lower()
    text = re.sub(r"(?:주식회사|\(주\)|㈜)", "", text)
    return re.sub(r"[^0-9a-z가-힣]", "", text)


def is_entity_relevant(title: object, summary: object, entity_names: Iterable[str]) -> bool:
    haystack = normalize_entity(f"{clean_text(title)} {clean_text(summary)}")
    needles = {normalize_entity(name) for name in entity_names}
    return any(len(needle) >= 2 and needle in haystack for needle in needles)


def _keyword_hits(text: str, rules: dict[str, tuple[str, ...]]) -> list[dict[str, str]]:
    lowered = text.lower()
    hits: list[dict[str, str]] = []
    for category, keywords in rules.items():
        for keyword in keywords:
            negations = RISK_NEGATION_PHRASES.get(keyword, ())
            if keyword.lower() in lowered and not any(phrase.lower() in lowered for phrase in negations):
                hits.append({"category": category, "keyword": keyword})
    return hits


def _item_dict(item: object) -> dict[str, Any]:
    if isinstance(item, dict):
        return item
    as_dict = getattr(item, "as_dict", None)
    return as_dict() if callable(as_dict) else {}


def assess_news_snapshot(
    items: Iterable[object],
    *,
    decision_at: object,
    observed_at: object,
    entity_names: Iterable[str],
    max_age_hours: float = 72.0,
) -> dict[str, Any]:
    """Assess point-in-time news metadata without making a live order decision."""
    decision = parse_news_timestamp(decision_at)
    observed = parse_news_timestamp(observed_at)
    if decision is None or observed is None:
        raise ValueError("decision_at and observed_at must be parseable timestamps")

    assessed: list[dict[str, Any]] = []
    for raw_item in items:
        item = _item_dict(raw_item)
        item_observed = parse_news_timestamp(item.get("observed_at")) or observed
        title = clean_text(item.get("title"))
        summary = clean_text(item.get("summary"))
        published = parse_news_timestamp(item.get("published_at"))
        relevant = is_entity_relevant(title, summary, entity_names)
        age_hours = (decision - published).total_seconds() / 3600.0 if published else None
        published_before_decision = bool(published and published <= decision)
        published_before_observation = bool(published and published <= item_observed)
        within_window = bool(age_hours is not None and 0 <= age_hours <= max_age_hours)
        eligible = relevant and published_before_decision and published_before_observation and within_window
        combined = f"{title} {summary}"
        detected_hard_hits = _keyword_hits(combined, HARD_RISK_RULES) if eligible else []
        review_hits = _keyword_hits(combined, REVIEW_RISK_RULES) if eligible else []
        provider = str(item.get("provider") or "").lower()
        if provider in OFFICIAL_DISCLOSURE_PROVIDERS:
            hard_hits = detected_hard_hits
        else:
            hard_hits = []
            review_hits.extend(
                {"category": f"general_news_{hit['category']}", "keyword": hit["keyword"]}
                for hit in detected_hard_hits
            )
        positive_hits = _keyword_hits(combined, POSITIVE_CONTEXT_RULES) if eligible else []
        assessed.append(
            {
                "provider": item.get("provider"),
                "title": title,
                "url": item.get("url"),
                "source": item.get("source"),
                "published_at": published.isoformat() if published else None,
                "observed_at": item_observed.isoformat(),
                "point_in_time_valid": item_observed <= decision,
                "entity_relevant": relevant,
                "published_before_decision": published_before_decision,
                "published_before_observation": published_before_observation,
                "within_age_window": within_window,
                "eligible": eligible,
                "hard_risk_hits": hard_hits,
                "review_risk_hits": review_hits,
                "positive_context_hits": positive_hits,
            }
        )

    eligible_items = [item for item in assessed if item["eligible"]]
    hard_items = [item for item in eligible_items if item["hard_risk_hits"]]
    review_items = [item for item in eligible_items if item["review_risk_hits"]]
    positive_items = [item for item in eligible_items if item["positive_context_hits"]]
    promotion_items = [item for item in eligible_items if item["point_in_time_valid"]]
    if hard_items:
        shadow_decision = "risk_veto"
    elif review_items:
        shadow_decision = "manual_review"
    elif eligible_items:
        shadow_decision = "no_veto_evidence"
    else:
        shadow_decision = "no_eligible_news"
    point_in_time_valid = observed <= decision
    return {
        "decision_at": decision.isoformat(),
        "observed_at": observed.isoformat(),
        "point_in_time_valid": point_in_time_valid,
        "max_age_hours": max_age_hours,
        "items_returned": len(assessed),
        "relevant_items": sum(item["entity_relevant"] for item in assessed),
        "eligible_items": len(eligible_items),
        "hard_risk_items": len(hard_items),
        "review_risk_items": len(review_items),
        "positive_context_items": len(positive_items),
        "shadow_decision": shadow_decision,
        "promotion_eligible_observation": point_in_time_valid,
        "promotion_eligible_items": len(promotion_items),
        "paper_only": True,
        "order_sent": False,
        "live_order_allowed": False,
        "items": assessed,
    }
