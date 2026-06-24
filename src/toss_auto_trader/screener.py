from __future__ import annotations

import csv
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from .indicators import build_technical_features
from .news_client import NewsHub
from .toss_client import TossInvestClient


def score_news_titles(titles: list[str]) -> Decimal:
    text = " ".join(titles).lower()
    positive = ["자사주", "수주", "성장", "실적", "흑자", "증가", "계약", "투자", "확대", "기대"]
    negative = ["경고", "위험", "급락", "적자", "감소", "소송", "상폐", "정지", "우려", "조정"]
    return Decimal(sum(2 for w in positive if w in text) - sum(3 for w in negative if w in text))


@dataclass
class LowPriceCandidate:
    symbol: str
    name: str
    market: str
    security_type: str
    price: Decimal
    currency: str
    naver_volume: int = 0
    avg_volume: Decimal = Decimal("0")
    score: Decimal = Decimal("0")
    bucket: str = ""
    news_titles: list[str] | None = None
    warnings: list[dict[str, Any]] | None = None
    reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "name": self.name,
            "market": self.market,
            "security_type": self.security_type,
            "price": str(self.price),
            "currency": self.currency,
            "naver_volume": self.naver_volume,
            "avg_volume": str(self.avg_volume),
            "score": str(self.score),
            "bucket": self.bucket,
            "news_titles": self.news_titles or [],
            "warnings": self.warnings or [],
            "reason": self.reason,
        }


def load_seed_csv(path: str, limit: int = 120) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    p = Path(path)
    if not p.exists():
        return rows
    with p.open(newline="") as f:
        for row in csv.DictReader(f):
            if row.get("symbol"):
                rows.append(row)
            if len(rows) >= limit:
                break
    return rows


def screen_low_price_candidates(
    client: TossInvestClient,
    *,
    seed_rows: list[dict[str, Any]],
    max_price: Decimal = Decimal("10000"),
    six_bucket: Decimal = Decimal("6000"),
    four_bucket: Decimal = Decimal("4000"),
    max_candidates: int = 30,
    fetch_candles: bool = True,
    fetch_news: bool = True,
    news_limit: int = 3,
    exclude_inverse_leverage: bool = True,
) -> dict[str, Any]:
    symbols = [r["symbol"] for r in seed_rows]
    if not symbols:
        return {"candidates": [], "pairs_6_4": []}
    symbols = symbols[:200]
    prices = client.get_prices(symbols).get("result", [])
    stocks = client.get_stocks(symbols).get("result", [])
    by_price = {p["symbol"]: p for p in prices}
    by_stock = {s["symbol"]: s for s in stocks}
    by_seed = {r["symbol"]: r for r in seed_rows}
    candidates: list[LowPriceCandidate] = []
    hub = NewsHub()
    for sym in symbols:
        p = by_price.get(sym)
        st = by_stock.get(sym, {})
        if not p:
            continue
        price = Decimal(str(p.get("lastPrice", "0")))
        if price <= 0 or price > max_price:
            continue
        name = st.get("name") or by_seed.get(sym, {}).get("name", sym)
        security_type = st.get("securityType", "UNKNOWN")
        if st.get("status") and st.get("status") != "ACTIVE":
            continue
        lname = f"{name} {st.get('englishName','')}".lower()
        if exclude_inverse_leverage and any(x in lname for x in ["인버스", "inverse", "레버리지", "2x", "선물인버스"]):
            continue
        bucket = "six" if price <= six_bucket else "ten"
        if price <= four_bucket:
            bucket = "four"
        avg_volume = Decimal("0")
        tech_bonus = Decimal("0")
        if fetch_candles:
            try:
                candles = client.get_candles(sym, "1d", 60).get("result", {}).get("candles", [])
                vols = [Decimal(str(c.get("volume", "0"))) for c in candles[:20]]
                avg_volume = sum(vols, Decimal("0")) / Decimal(max(1, len(vols)))
                features = build_technical_features(candles)
                if features.get("ma_alignment") == "bullish":
                    tech_bonus += Decimal("15")
                rsi = Decimal(str(features.get("rsi14") or "50"))
                if Decimal("35") <= rsi <= Decimal("70"):
                    tech_bonus += Decimal("10")
                elif rsi > Decimal("80"):
                    tech_bonus -= Decimal("15")
            except Exception:
                pass
        news_titles: list[str] = []
        if fetch_news:
            try:
                news = hub.naver_news(f"{name} 주가", display=news_limit)
                news_titles = [n.title for n in news[:news_limit]]
            except Exception:
                news_titles = []
        warnings: list[dict[str, Any]] = []
        try:
            warnings = client.get_stock_warnings(sym).get("result", [])
        except Exception:
            warnings = []
        if warnings:
            tech_bonus -= Decimal("30")
        # Score: small-account fit + liquidity proxy + technical/news/warning info.
        fit = Decimal("25") if bucket == "four" else (Decimal("20") if bucket == "six" else Decimal("10"))
        liquidity = min(Decimal("30"), avg_volume / Decimal("100000")) if avg_volume else Decimal("0")
        news_bonus = Decimal(min(10, len(news_titles) * 3)) + score_news_titles(news_titles)
        if security_type == "ETF":
            news_bonus -= Decimal("5")  # ponytail: ETF needs NAV/spread/LP checks before auto-approval.
        score = fit + liquidity + tech_bonus + news_bonus
        reason = f"bucket={bucket}; fit={fit}; liquidity={liquidity:.2f}; tech_bonus={tech_bonus}; news_score={news_bonus}; warnings={len(warnings)}"
        candidates.append(
            LowPriceCandidate(
                symbol=sym,
                name=name,
                market=st.get("market") or by_seed.get(sym, {}).get("market", ""),
                security_type=security_type,
                price=price,
                currency=p.get("currency", st.get("currency", "KRW")),
                naver_volume=int(float(by_seed.get(sym, {}).get("naver_volume") or 0)),
                avg_volume=avg_volume,
                score=score,
                bucket=bucket,
                news_titles=news_titles,
                warnings=warnings,
                reason=reason,
            )
        )
    candidates.sort(key=lambda c: (c.score, c.avg_volume), reverse=True)
    candidates = candidates[:max_candidates]
    fours = [c for c in candidates if c.price <= four_bucket and not c.warnings]
    sixes = [c for c in candidates if c.price <= six_bucket and not c.warnings]
    pairs = []
    for a in sixes:
        for b in fours:
            if a.symbol == b.symbol:
                continue
            total = a.price + b.price
            if total <= max_price:
                pairs.append({
                    "total_price": str(total),
                    "remaining_cash": str(max_price - total),
                    "score": str(a.score + b.score),
                    "six_slot": a.as_dict(),
                    "four_slot": b.as_dict(),
                })
    pairs.sort(key=lambda x: Decimal(x["score"]), reverse=True)
    return {"candidates": [c.as_dict() for c in candidates], "pairs_6_4": pairs[:10]}
