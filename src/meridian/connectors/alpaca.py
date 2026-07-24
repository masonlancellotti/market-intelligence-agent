"""C1 Alpaca Market Data (IEX feed) — real-time equity/ETF quotes.

Requires ALPACA_KEY_ID/SECRET; without them the connector auto-disables (base class) and
yfinance-delayed quotes fill in. This implements the REST latest-bars snapshot (the WS
live stream is a Phase-1 follow-up; snapshots on a short cadence are sufficient for the
alert engine's needs and stay well inside the free tier).
"""

from __future__ import annotations

import httpx

from ..util import clean_float
from .base import BaseConnector, FetchResult, register

DATA_BASE = "https://data.alpaca.markets/v2"


@register
class AlpacaConnector(BaseConnector):
    name = "alpaca"
    requires = ["alpaca_key_id", "alpaca_secret_key"]

    def _headers(self) -> dict:
        return {
            "APCA-API-KEY-ID": self.settings.secrets.alpaca_key_id,
            "APCA-API-SECRET-KEY": self.settings.secrets.alpaca_secret_key,
            "Accept": "application/json",
        }

    def _tickers(self) -> list[str]:
        rows = self.db.query("SELECT ticker FROM instruments WHERE kind IN ('equity','etf')")
        return [r["ticker"] for r in rows]

    async def fetch(self) -> FetchResult:
        tickers = self._tickers()
        if not tickers:
            return FetchResult(0, "no equity/etf instruments")
        n = 0
        async with httpx.AsyncClient(timeout=20, headers=self._headers()) as client:
            # latest daily bars + latest trade in one round trip each
            bars = await client.get(
                f"{DATA_BASE}/stocks/bars/latest",
                params={"symbols": ",".join(tickers), "feed": "iex"},
            )
            bars.raise_for_status()
            snap = bars.json().get("bars", {})

            # previous close from the prior daily bar
            prev = await client.get(
                f"{DATA_BASE}/stocks/bars",
                params={
                    "symbols": ",".join(tickers),
                    "timeframe": "1Day",
                    "limit": "2",
                    "feed": "iex",
                },
            )
            prev_map = _prev_closes(prev.json().get("bars", {})) if prev.status_code < 300 else {}

            for sym, bar in snap.items():
                price = clean_float(bar.get("c"))
                if price is None:
                    continue
                self.upsert_quote(
                    sym,
                    price=price,
                    prev_close=prev_map.get(sym),
                    day_open=clean_float(bar.get("o")),
                    day_high=clean_float(bar.get("h")),
                    day_low=clean_float(bar.get("l")),
                    volume=clean_float(bar.get("v")),
                    source="alpaca-iex",
                    is_stale=0,
                )
                n += 1
        return FetchResult(n, f"{n} quotes via alpaca")


def _prev_closes(bars_by_sym: dict) -> dict[str, float]:
    out = {}
    for sym, arr in bars_by_sym.items():
        if isinstance(arr, list) and len(arr) >= 2:
            out[sym] = clean_float(arr[-2].get("c"))
    return out
