"""C7 news depth via Finnhub. Requires FINNHUB_KEY (free tier, 60 req/min);
auto-disabled without it. Company-news per watchlist ticker → dedup/clustering pipeline.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta

import httpx

from ..util import iso, norm_ticker, utcnow
from .base import BaseConnector, FetchResult, register
from .textproc import ingest_news

FINNHUB = "https://finnhub.io/api/v1"


@register
class FinnhubConnector(BaseConnector):
    name = "finnhub"
    requires = ["finnhub_key"]

    def _tickers(self) -> list[str]:
        cfg = self.settings.config
        return [
            norm_ticker(t)
            for t in dict.fromkeys(cfg.watchlist.holdings + cfg.watchlist.active)
            if not t.endswith("-USD")
        ]

    async def fetch(self) -> FetchResult:
        key = self.settings.secrets.finnhub_key
        frm = iso(utcnow() - timedelta(days=3))[:10]
        to = utcnow().date().isoformat()
        items: list[dict] = []
        async with httpx.AsyncClient(timeout=20) as client:
            for t in self._tickers():
                try:
                    r = await client.get(
                        f"{FINNHUB}/company-news",
                        params={"symbol": t, "from": frm, "to": to, "token": key},
                    )
                    if r.status_code != 200:
                        continue
                    for a in r.json()[:20]:
                        from datetime import UTC, datetime

                        ts = a.get("datetime")
                        pub = (
                            datetime.fromtimestamp(ts, UTC).isoformat().replace("+00:00", "Z")
                            if ts
                            else None
                        )
                        items.append(
                            {
                                "source": a.get("source", "finnhub"),
                                "url": a.get("url", ""),
                                "title": a.get("headline", ""),
                                "summary": (a.get("summary") or "")[:1000],
                                "published_at": pub,
                                "tickers": [t],
                            }
                        )
                except Exception:  # noqa: BLE001
                    continue
                await asyncio.sleep(0.2)  # 60 req/min budget
        stats = ingest_news(items, self.settings)
        return FetchResult(
            stats["inserted"], f"{stats['inserted']} new / {stats['duplicates']} dup"
        )
