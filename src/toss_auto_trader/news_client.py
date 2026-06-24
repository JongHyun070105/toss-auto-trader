from __future__ import annotations

import json
import os
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

from .rate_limit import RateLimiter, RateLimitPolicy


@dataclass(frozen=True)
class NewsItem:
    provider: str
    title: str
    url: str
    source: str | None = None
    published_at: str | None = None
    summary: str | None = None
    sentiment: float | None = None
    raw: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "title": self.title,
            "url": self.url,
            "source": self.source,
            "published_at": self.published_at,
            "summary": self.summary,
            "sentiment": self.sentiment,
            "raw": self.raw or {},
        }


class NewsClientError(RuntimeError):
    pass


class NewsHub:
    def __init__(self) -> None:
        self.limiters = {
            "naver": RateLimiter(RateLimitPolicy(min_interval_seconds=0.0, max_calls_per_minute=60, cooldown_seconds=120)),
            "marketaux": RateLimiter(RateLimitPolicy(min_interval_seconds=5, max_calls_per_minute=10, cooldown_seconds=300)),
            "finnhub": RateLimiter(RateLimitPolicy(min_interval_seconds=2, max_calls_per_minute=20, cooldown_seconds=300)),
            "alphavantage": RateLimiter(RateLimitPolicy(min_interval_seconds=60, max_calls_per_minute=1, cooldown_seconds=3600)),
        }

    def _request_json(self, provider: str, url: str, headers: dict[str, str] | None = None) -> dict[str, Any]:
        limiter = self.limiters[provider]
        if not limiter.can_call():
            raise NewsClientError(f"{provider} rate-limited locally; wait {limiter.seconds_until_next_call():.1f}s")
        final_headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X) toss-auto-trader-lab/0.1", "Accept": "application/json"}
        if headers:
            final_headers.update(headers)
        req = urllib.request.Request(url, headers=final_headers)
        try:
            limiter.record_call()
            with urllib.request.urlopen(req, timeout=20) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            if "HTTP Error 429" in str(exc):
                limiter.record_429()
            raise

    def naver_news(self, query: str, display: int = 10, sort: str = "date") -> list[NewsItem]:
        client_id = os.getenv("NAVER_CLIENT_ID")
        client_secret = os.getenv("NAVER_CLIENT_SECRET")
        if not client_id or not client_secret:
            raise NewsClientError("NAVER_CLIENT_ID/NAVER_CLIENT_SECRET missing")
        params = urllib.parse.urlencode({"query": query, "display": min(display, 100), "start": 1, "sort": sort})
        data = self._request_json(
            "naver",
            f"https://openapi.naver.com/v1/search/news.json?{params}",
            {"X-Naver-Client-Id": client_id, "X-Naver-Client-Secret": client_secret},
        )
        items = []
        for item in data.get("items", []):
            items.append(
                NewsItem(
                    provider="naver",
                    title=_strip_html(item.get("title", "")),
                    url=item.get("originallink") or item.get("link") or "",
                    source="naver",
                    published_at=item.get("pubDate"),
                    summary=_strip_html(item.get("description", "")),
                    raw=item,
                )
            )
        return items

    def marketaux_news(self, query: str, limit: int = 3, language: str = "en") -> list[NewsItem]:
        token = os.getenv("MARKETAUX_API_TOKEN")
        if not token:
            raise NewsClientError("MARKETAUX_API_TOKEN missing")
        params = urllib.parse.urlencode({"api_token": token, "search": query, "language": language, "limit": min(limit, 3)})
        data = self._request_json("marketaux", f"https://api.marketaux.com/v1/news/all?{params}")
        items = []
        for item in data.get("data", []):
            sentiment = None
            entities = item.get("entities") or []
            if entities:
                vals = [e.get("sentiment_score") for e in entities if e.get("sentiment_score") is not None]
                if vals:
                    sentiment = sum(float(v) for v in vals) / len(vals)
            items.append(
                NewsItem(
                    provider="marketaux",
                    title=item.get("title", ""),
                    url=item.get("url", ""),
                    source=(item.get("source") or ""),
                    published_at=item.get("published_at"),
                    summary=item.get("description"),
                    sentiment=sentiment,
                    raw=item,
                )
            )
        return items

    def finnhub_market_news(self, category: str = "general", min_id: int = 0) -> list[NewsItem]:
        token = os.getenv("FINNHUB_API_KEY")
        if not token:
            raise NewsClientError("FINNHUB_API_KEY missing")
        params = urllib.parse.urlencode({"category": category, "minId": min_id})
        data = self._request_json("finnhub", f"https://finnhub.io/api/v1/news?{params}", {"X-Finnhub-Token": token})
        items = []
        for item in data if isinstance(data, list) else []:
            published = item.get("datetime")
            items.append(
                NewsItem(
                    provider="finnhub",
                    title=item.get("headline", ""),
                    url=item.get("url", ""),
                    source=item.get("source"),
                    published_at=str(published) if published is not None else None,
                    summary=item.get("summary"),
                    raw=item,
                )
            )
        return items

    def alphavantage_news(self, tickers: str = "AAPL,MSFT,NVDA", limit: int = 5) -> list[NewsItem]:
        key = os.getenv("ALPHAVANTAGE_API_KEY")
        if not key:
            raise NewsClientError("ALPHAVANTAGE_API_KEY missing")
        params = urllib.parse.urlencode({"function": "NEWS_SENTIMENT", "tickers": tickers, "limit": min(limit, 5), "apikey": key})
        data = self._request_json("alphavantage", f"https://www.alphavantage.co/query?{params}")
        items = []
        for item in data.get("feed", [])[: min(limit, 5)]:
            sentiment = item.get("overall_sentiment_score")
            items.append(
                NewsItem(
                    provider="alphavantage",
                    title=item.get("title", ""),
                    url=item.get("url", ""),
                    source=item.get("source"),
                    published_at=item.get("time_published"),
                    summary=item.get("summary"),
                    sentiment=float(sentiment) if sentiment is not None else None,
                    raw=item,
                )
            )
        return items


def _strip_html(text: str) -> str:
    return text.replace("<b>", "").replace("</b>", "").replace("&quot;", '"').replace("&amp;", "&")
