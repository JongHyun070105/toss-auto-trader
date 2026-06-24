from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from .indicators import d


@dataclass(frozen=True)
class AgentOpinion:
    agent: str
    score: int
    action: str
    reason: str
    data: dict[str, Any]


def technical_analyst(features: dict[str, Any], cfg: dict[str, Any]) -> AgentOpinion:
    score = 50
    reasons: list[str] = []
    rsi = d(features.get("rsi14"), "50")
    alignment = features.get("ma_alignment")
    if alignment == "bullish":
        score += 15; reasons.append("MA bullish alignment")
    elif alignment == "bearish":
        score -= 20; reasons.append("MA bearish alignment")
    if Decimal("35") <= rsi <= Decimal("70"):
        score += 10; reasons.append(f"RSI acceptable {rsi}")
    elif rsi > Decimal("80"):
        score -= 15; reasons.append(f"RSI overheated {rsi}")
    elif rsi < Decimal("25"):
        score -= 5; reasons.append(f"RSI weak/falling {rsi}")
    overheat_block = cfg.get("selection", {}).get("rsi_overheat_block")
    if overheat_block is not None and rsi > Decimal(str(overheat_block)):
        score -= 25
        reasons.append(f"RSI overheat block {rsi}>{overheat_block}")
    buy_threshold = int(cfg.get("selection", {}).get("technical_buy_score", 70))
    action = "BUY" if score >= buy_threshold else "HOLD"
    return AgentOpinion("technical", max(0, min(100, score)), action, "; ".join(reasons) or "neutral", features)


def risk_manager(features: dict[str, Any], cfg: dict[str, Any]) -> AgentOpinion:
    defaults = cfg.get("risk", {})
    default_stop = Decimal(str(defaults.get("stop_loss_pct", 0.03)))
    default_take = Decimal(str(defaults.get("take_profit_pct", 0.06)))
    last = d(features.get("last_close"), "0")
    atr14 = d(features.get("atr14"), "0")
    if last > 0 and atr14 > 0:
        atr_pct = atr14 / last
        stop = max(default_stop, min(Decimal("0.06"), atr_pct * Decimal("1.5")))
        take = max(default_take, stop * Decimal("2"))
    else:
        stop, take = default_stop, default_take
    return AgentOpinion(
        "risk",
        70,
        "ALLOW",
        f"dynamic stop={stop:.4f}, take={take:.4f}",
        {"stop_loss_pct": str(stop), "take_profit_pct": str(take), "trailing_stop_pct": str(stop / Decimal("2"))},
    )


def fee_analyst(cfg: dict[str, Any]) -> AgentOpinion:
    fees = cfg.get("fees", {}).get("KR", {})
    buy = Decimal(str(fees.get("buy_commission_pct", 0.0001)))
    sell = Decimal(str(fees.get("sell_commission_pct", 0.0001)))
    tax = Decimal(str(fees.get("sell_tax_pct", 0.002)))
    roundtrip = buy + sell + tax
    return AgentOpinion("fee", 75, "ALLOW", f"roundtrip cost {roundtrip:.4%}", {"roundtrip_cost_pct": str(roundtrip)})


def performance_feedback(recent_stats: dict[str, Any], cfg: dict[str, Any]) -> AgentOpinion:
    win_rate = Decimal(str(recent_stats.get("win_rate", 0)))
    losing_streak = int(recent_stats.get("losing_streak", 0))
    score = 60
    reasons = []
    if losing_streak >= 3:
        score -= 20; reasons.append("losing streak -> conservative")
    if win_rate >= Decimal("0.55"):
        score += 10; reasons.append("recent win rate ok")
    if win_rate and win_rate < Decimal("0.4"):
        score -= 10; reasons.append("recent win rate weak")
    return AgentOpinion("performance", max(0, min(100, score)), "ALLOW" if score >= 50 else "HOLD", "; ".join(reasons) or "neutral", recent_stats)


def news_analyst(news_items: list[dict[str, Any]], cfg: dict[str, Any]) -> AgentOpinion:
    text = " ".join(str(n.get("title", "")) for n in news_items).lower()
    positive = ["자사주", "수주", "성장", "실적", "흑자", "증가", "계약", "투자", "확대", "기대"]
    negative = ["경고", "위험", "급락", "적자", "감소", "소송", "상폐", "정지", "우려", "조정"]
    delta = sum(3 for w in positive if w in text) - sum(5 for w in negative if w in text)
    score = max(0, min(100, 50 + delta))
    action = "HOLD" if score < int(cfg.get("selection", {}).get("news_min_score", 45)) else "ALLOW"
    return AgentOpinion("news", score, action, f"news_score={score}, items={len(news_items)}", {"items": news_items[:5], "score": score})


def coordinator(opinions: list[AgentOpinion], cfg: dict[str, Any]) -> dict[str, Any]:
    thresholds = cfg.get("selection", {})
    min_score = int(thresholds.get("sideways_min_score", 70))
    min_conf = Decimal(str(thresholds.get("min_confidence", 0.70)))
    score = sum(o.score for o in opinions) / max(1, len(opinions))
    confidence = Decimal(str(score / 100))
    blockers = [o for o in opinions if o.action in {"HOLD", "BLOCK"} and o.agent in {"technical", "performance", "news"}]
    if blockers or score < min_score or confidence < min_conf:
        side = "HOLD"
        reason = "관망: " + "; ".join(f"{o.agent}:{o.reason}" for o in opinions)
    else:
        side = "BUY"
        reason = "매수 후보: " + "; ".join(f"{o.agent}:{o.reason}" for o in opinions)
    risk = next((o.data for o in opinions if o.agent == "risk"), {})
    fee = next((o.data for o in opinions if o.agent == "fee"), {})
    return {
        "side": side,
        "score": round(score, 2),
        "confidence": str(confidence),
        "reason": reason,
        "risk": risk,
        "fee": fee,
        "opinions": [o.__dict__ for o in opinions],
    }
