"""C8 news breadth via GDELT DOC 2.0. Keyless macro-theme coverage:
central banks, tariffs, geopolitics. Feeds the same dedup/clustering pipeline.
"""

from __future__ import annotations

import asyncio

import httpx

from .base import BaseConnector, FetchResult, register
from .textproc import ingest_news

GDELT = "https://api.gdeltproject.org/api/v2/doc/doc"

QUERIES = [
    "central bank monetary policy",
    "sovereign debt crisis",
    "geopolitics conflict markets",
    "semiconductor export controls",
    "energy supply shock",
]


@register
class GDELTConnector(BaseConnector):
    name = "gdelt"
    requires: list[str] = []

    async def fetch(self) -> FetchResult:
        items: list[dict] = []
        async with httpx.AsyncClient(timeout=25, headers={"User-Agent": self.http_ua}) as client:
            for i, q in enumerate(QUERIES):
                if i:
                    await asyncio.sleep(5.5)  # GDELT: max 1 request / 5s
                try:
                    r = await client.get(
                        GDELT,
                        params={
                            "query": q,
                            "mode": "artlist",
                            "maxrecords": "20",
                            "format": "json",
                            "sort": "datedesc",
                            "timespan": "24h",
                        },
                    )
                    if r.status_code != 200 or not r.text.strip().startswith("{"):
                        continue
                    for a in r.json().get("articles", []):
                        items.append(
                            {
                                "source": a.get("domain", "gdelt"),
                                "url": a.get("url", ""),
                                "title": a.get("title", ""),
                                "summary": "",
                                "published_at": _gdelt_date(a.get("seendate", "")),
                                "category": "macro",
                            }
                        )
                except Exception:  # noqa: BLE001
                    continue
        stats = ingest_news(items, self.settings)
        return FetchResult(
            stats["inserted"], f"{stats['inserted']} new / {stats['duplicates']} dup"
        )


def _gdelt_date(s: str) -> str | None:
    # GDELT format: 20260705T134500Z
    if not s or len(s) < 15:
        return None
    try:
        return f"{s[0:4]}-{s[4:6]}-{s[6:8]}T{s[9:11]}:{s[11:13]}:{s[13:15]}Z"
    except Exception:  # noqa: BLE001
        return None
