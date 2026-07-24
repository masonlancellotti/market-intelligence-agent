"""C1/C2 latest-quote connector for equities/ETFs/indices via yfinance (delayed).

Alpaca (IEX, real-time) is the plan's primary during RTH but needs keys; when they're
absent this connector supplies ~15-min-delayed quotes so the rest of the system has
prices to work with. Daily history/backfill lives in ``history.py``.
"""

from __future__ import annotations

import asyncio

from loguru import logger

from ..util import clean_float, norm_ticker
from .base import BaseConnector, FetchResult, register


@register
class PricesConnector(BaseConnector):
    name = "prices"
    requires: list[str] = []  # yfinance needs no key (degradable, unofficial)

    def _tickers(self) -> list[str]:
        rows = self.db.query(
            "SELECT ticker FROM instruments WHERE kind IN ('equity','etf','index') ORDER BY ticker"
        )
        return [r["ticker"] for r in rows]

    async def fetch(self) -> FetchResult:
        tickers = self._tickers()
        if not tickers:
            return FetchResult(0, "no equity/etf instruments seeded")
        rows = await asyncio.to_thread(_download_last_quotes, tickers)
        n = 0
        for t, q in rows.items():
            if q.get("price") is None:
                continue
            self.upsert_quote(
                t,
                price=q["price"],
                prev_close=q.get("prev_close"),
                day_open=q.get("open"),
                day_high=q.get("high"),
                day_low=q.get("low"),
                volume=q.get("volume"),
                source="yfinance-delayed",
                is_stale=0,
            )
            self._push_tick(t, q)
            n += 1
        return FetchResult(n, f"{n}/{len(tickers)} quoted")

    def _push_tick(self, ticker: str, q: dict) -> None:
        from ..api.events import publish
        from ..util import pct

        publish(
            "quote",
            {
                "ticker": ticker,
                "price": q["price"],
                "change_pct": pct(q["price"], q.get("prev_close")),
                "source": "yfinance-delayed",
            },
        )


def _download_last_quotes(tickers: list[str]) -> dict[str, dict]:
    """Batch-download last ~5 sessions and extract latest + previous close per ticker."""
    import yfinance as yf

    out: dict[str, dict] = {}
    try:
        data = yf.download(
            tickers=" ".join(tickers),
            period="5d",
            interval="1d",
            auto_adjust=False,
            group_by="ticker",
            threads=True,
            progress=False,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("yfinance batch download failed: {}", e)
        data = None

    for t in tickers:
        try:
            sub = _slice(data, t, single=len(tickers) == 1)
            if sub is None or sub.empty:
                continue
            closes = [clean_float(v) for v in sub["Close"].tolist() if clean_float(v) is not None]
            if not closes:
                continue
            last = sub.iloc[-1]
            out[norm_ticker(t)] = {
                "price": closes[-1],  # last VALID close (latest raw bar may be NaN)
                "prev_close": closes[-2] if len(closes) >= 2 else None,
                "open": clean_float(last.get("Open")),
                "high": clean_float(last.get("High")),
                "low": clean_float(last.get("Low")),
                "volume": clean_float(last.get("Volume")),
            }
        except Exception as e:  # noqa: BLE001
            logger.debug("quote parse failed for {}: {}", t, e)

    # Per-ticker fallback for anything the batch missed (indices like ^VIX/^TNX are
    # flaky in batch downloads but fine individually).
    missing = [t for t in tickers if norm_ticker(t) not in out]
    for t in missing:
        q = _single_quote(t)
        if q:
            out[norm_ticker(t)] = q
    return out


def _single_quote(ticker: str) -> dict | None:
    import yfinance as yf

    try:
        h = yf.Ticker(ticker).history(period="5d", interval="1d", auto_adjust=False)
        if h is None or h.empty:
            return None
        closes = [clean_float(v) for v in h["Close"].tolist() if clean_float(v) is not None]
        if not closes:
            return None
        last = h.iloc[-1]
        return {
            "price": closes[-1],  # last VALID close
            "prev_close": closes[-2] if len(closes) >= 2 else None,
            "open": clean_float(last.get("Open")),
            "high": clean_float(last.get("High")),
            "low": clean_float(last.get("Low")),
            "volume": clean_float(last.get("Volume")),
        }
    except Exception as e:  # noqa: BLE001
        logger.debug("single-quote fallback failed for {}: {}", ticker, e)
        return None


def _slice(data, ticker: str, single: bool):
    if data is None:
        return None
    if single:
        return data
    try:
        return data[ticker]
    except (KeyError, TypeError):
        return None
