"""C3 futures / overnight proxies via yfinance.

ES/NQ/YM/RTY/CL/GC + ^VIX/^VIX3M/^TNX + dollar index. These give the Morning Brief its
overnight read and feed the regime model (VIX term structure, dollar trend).
"""

from __future__ import annotations

import asyncio

from ..util import clean_float, norm_ticker
from .base import BaseConnector, FetchResult, register
from .prices import _download_last_quotes

PROXIES = [
    "ES=F",
    "NQ=F",
    "YM=F",
    "RTY=F",
    "CL=F",
    "GC=F",
    "^VIX",
    "^VIX3M",
    "^TNX",
    "DX-Y.NYB",
]


@register
class FuturesConnector(BaseConnector):
    name = "futures"
    requires: list[str] = []

    async def fetch(self) -> FetchResult:
        quotes = await asyncio.to_thread(_download_last_quotes, PROXIES)
        n = 0
        for t in PROXIES:
            q = quotes.get(norm_ticker(t))
            if not q or clean_float(q.get("price")) is None:
                continue
            kind = "index" if t.startswith("^") or t == "DX-Y.NYB" else "future_proxy"
            self.upsert_quote(
                t,
                price=q["price"],
                prev_close=q.get("prev_close"),
                day_open=q.get("open"),
                day_high=q.get("high"),
                day_low=q.get("low"),
                volume=q.get("volume"),
                source="yfinance",
                is_stale=0,
                kind=kind,
            )
            n += 1
        return FetchResult(n, f"{n}/{len(PROXIES)} proxies")
