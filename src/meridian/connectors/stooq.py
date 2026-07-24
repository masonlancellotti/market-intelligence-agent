"""C2 Stooq daily CSV (no key). names Stooq the primary history source; as of
build it is behind a JavaScript bot-challenge (docs/DECISIONS.md D-007), so yfinance is the
working primary and this connector degrades cleanly: if it sees the challenge page it
reports 0 items rather than crashing. Left intact because Stooq may be reachable from the
Mini's network or later.
"""

from __future__ import annotations

import httpx
import polars as pl

from ..config import Settings
from ..util import norm_ticker
from .base import BaseConnector, FetchResult, register
from .history import write_daily


def _stooq_symbol(ticker: str) -> str:
    t = norm_ticker(ticker)
    if t.endswith("-USD"):
        return t.replace("-USD", "usd").lower()  # btcusd
    if t.startswith("^"):
        return t.lower()
    return f"{t.lower()}.us"  # US equities/ETFs


def fetch_stooq_daily(ticker: str, settings: Settings | None = None) -> pl.DataFrame | None:
    sym = _stooq_symbol(ticker)
    url = f"https://stooq.com/q/d/l/?s={sym}&i=d"
    r = httpx.get(url, timeout=25, headers={"User-Agent": "Mozilla/5.0"})
    body = r.text
    if body.lstrip().startswith("<") or "requires JavaScript" in body or "Date,Open" not in body:
        return None  # bot challenge / unavailable
    lines = [ln for ln in body.strip().splitlines() if "," in ln]
    if len(lines) < 2:
        return None
    rows = []
    for ln in lines[1:]:
        parts = ln.split(",")
        if len(parts) < 5:
            continue
        try:
            rows.append(
                {
                    "date": parts[0],
                    "open": float(parts[1]),
                    "high": float(parts[2]),
                    "low": float(parts[3]),
                    "close": float(parts[4]),
                    "adj_close": float(parts[4]),
                    "volume": float(parts[5]) if len(parts) > 5 and parts[5] else None,
                }
            )
        except ValueError:
            continue
    return pl.DataFrame(rows) if rows else None


@register
class StooqConnector(BaseConnector):
    name = "stooq"
    requires: list[str] = []
    circuit_threshold = 99  # never alarm — it's a best-effort secondary

    async def fetch(self) -> FetchResult:
        import asyncio

        tickers = [
            r["ticker"]
            for r in self.db.query(
                "SELECT ticker FROM instruments WHERE kind IN ('equity','etf') ORDER BY ticker"
            )
        ]
        written = 0
        gated = 0
        for t in tickers:
            df = await asyncio.to_thread(fetch_stooq_daily, t, self.settings)
            if df is None:
                gated += 1
                continue
            write_daily(t, df, self.settings)
            written += 1
        if written == 0 and gated:
            return FetchResult(0, f"stooq bot-gated for {gated} tickers (yfinance is primary)")
        return FetchResult(written, f"{written} histories via stooq")
