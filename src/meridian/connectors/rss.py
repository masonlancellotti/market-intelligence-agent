"""C6 news via RSS.

Google News RSS is the reliable, keyless backbone (same source the prediction-terminal
proxy uses): one query feed per macro theme + one per active/holding ticker. A few direct
publisher feeds (Fed, MarketWatch, Yahoo) are added best-effort and skipped on failure.
All items flow through the dedup+clustering pipeline in ``textproc``.
"""

from __future__ import annotations

import asyncio
from urllib.parse import quote

import feedparser

from ..util import norm_ticker
from .base import BaseConnector, FetchResult, register
from .textproc import ingest_news

MACRO_THEMES = [
    "federal reserve interest rates",
    "CPI inflation report",
    "treasury yields bonds",
    "US jobs report payrolls",
    "tariffs trade policy",
    "stock market today",
    "oil prices",
    "recession economy",
]

DIRECT_FEEDS = {
    "Fed": "https://www.federalreserve.gov/feeds/press_all.xml",
    "MarketWatch": "http://feeds.marketwatch.com/marketwatch/topstories/",
    "YahooFinance": "https://finance.yahoo.com/news/rssindex",
}


def _gnews_url(query: str) -> str:
    return f"https://news.google.com/rss/search?q={quote(query)}&hl=en-US&gl=US&ceid=US:en"


def _parse_feed(url: str, default_source: str = "") -> list[dict]:
    d = feedparser.parse(url)
    items = []
    for e in d.entries[:30]:
        title = getattr(e, "title", "") or ""
        link = getattr(e, "link", "") or ""
        if not title or not link:
            continue
        # Google News encodes " - Source" into the title
        source = default_source
        clean_title = title
        if " - " in title and not default_source:
            clean_title, _, source = title.rpartition(" - ")
        summary = getattr(e, "summary", "") or ""
        published = None
        if getattr(e, "published_parsed", None):
            import calendar
            from datetime import UTC, datetime

            published = (
                datetime.fromtimestamp(calendar.timegm(e.published_parsed), UTC)
                .isoformat()
                .replace("+00:00", "Z")
            )
        items.append(
            {
                "source": source or "rss",
                "url": link,
                "title": clean_title.strip(),
                "summary": _strip_html(summary)[:1000],
                "published_at": published,
            }
        )
    return items


def _strip_html(s: str) -> str:
    import re

    return re.sub(r"<[^>]+>", "", s or "").strip()


@register
class RSSConnector(BaseConnector):
    name = "rss"
    requires: list[str] = []

    def _ticker_queries(self) -> list[tuple[str, str]]:
        cfg = self.settings.config
        tickers = cfg.watchlist.holdings + cfg.watchlist.active
        out = []
        for t in dict.fromkeys(norm_ticker(x) for x in tickers):
            if t.endswith("-USD"):
                out.append((t, _gnews_url(f"{t.split('-')[0]} crypto")))
            else:
                out.append((t, _gnews_url(f"{t} stock")))
        return out

    async def fetch(self) -> FetchResult:
        feeds: list[tuple[str, str, list[str] | None]] = []
        for theme in MACRO_THEMES:
            feeds.append((_gnews_url(theme), "", None))
        for ticker, url in self._ticker_queries():
            feeds.append((url, "", [ticker]))
        for src, url in DIRECT_FEEDS.items():
            feeds.append((url, src, None))

        all_items: list[dict] = []
        results = await asyncio.gather(
            *[asyncio.to_thread(_parse_feed, url, src) for url, src, _ in feeds],
            return_exceptions=True,
        )
        for (_url, _src, tag), res in zip(feeds, results, strict=False):
            if isinstance(res, Exception):
                continue
            for it in res:
                if tag:
                    it["tickers"] = tag
                all_items.append(it)

        stats = await asyncio.to_thread(ingest_news, all_items, self.settings)
        return FetchResult(
            stats["inserted"],
            f"{stats['inserted']} new / {stats['duplicates']} dup / {stats['new_clusters']} clusters",
        )
