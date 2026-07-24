"""C14 prediction markets — Kalshi + Polymarket.

Ported from the prediction-terminal project. Keyless
public data. We keep only macro-relevant markets (Fed decisions, CPI/inflation, rates,
recession, jobs, elections/geopolitics) and store them as macro event probabilities;
the ``fed-odds-swing`` alert watches 24h moves in Fed-decision odds.
"""

from __future__ import annotations

import httpx

from ..util import clean_float, utcnow_iso
from .base import BaseConnector, FetchResult, register

KALSHI_EVENTS = "{base}/events"
POLY_EVENTS = "https://gamma-api.polymarket.com/events"

_MACRO_KEYWORDS = {
    "fed": ["fed ", "fomc", "rate cut", "rate hike", "interest rate", "powell", "federal reserve"],
    "cpi": ["cpi", "inflation", "pce"],
    "recession": ["recession", "gdp", "soft landing"],
    "jobs": ["jobs report", "unemployment", "payrolls", "nonfarm"],
    "election": ["election", "president", "senate", "house control", "nominee"],
    "geopolitics": ["war", "ceasefire", "tariff", "sanction", "invasion"],
}


def _categorize(question: str) -> str | None:
    q = (question or "").lower()
    for cat, kws in _MACRO_KEYWORDS.items():
        if any(k in q for k in kws):
            return cat
    return None


@register
class PredictionMarketsConnector(BaseConnector):
    name = "predmkt"
    requires: list[str] = []

    async def fetch(self) -> FetchResult:
        n = 0
        async with httpx.AsyncClient(timeout=25, headers={"User-Agent": self.http_ua}) as client:
            n += await self._kalshi(client)
            n += await self._poly(client)
        return FetchResult(n, f"{n} macro markets")

    async def _kalshi(self, client: httpx.AsyncClient) -> int:
        base = self.settings.secrets.kalshi_api_base
        n = 0
        cursor = None
        for _ in range(3):  # up to 3 pages
            params = {"status": "open", "with_nested_markets": "true", "limit": "200"}
            if cursor:
                params["cursor"] = cursor
            try:
                r = await client.get(KALSHI_EVENTS.format(base=base), params=params)
                if r.status_code != 200:
                    break
                data = r.json()
            except Exception:  # noqa: BLE001
                break
            for ev in data.get("events", []):
                for m in ev.get("markets", []):
                    q = m.get("title") or ev.get("title") or ""
                    cat = _categorize(q)
                    if not cat:
                        continue
                    last = clean_float(m.get("last_price"))
                    yes = (last / 100) if last is not None else _mid(m)
                    if yes is None:
                        continue
                    prev = clean_float(m.get("previous_price"))
                    prev_prob = (prev / 100) if prev is not None else None
                    self._upsert(
                        "kalshi",
                        m.get("ticker") or m.get("id"),
                        q,
                        yes,
                        prev_prob,
                        clean_float(m.get("volume")),
                        cat,
                    )
                    n += 1
            cursor = data.get("cursor")
            if not cursor:
                break
        return n

    async def _poly(self, client: httpx.AsyncClient) -> int:
        n = 0
        try:
            r = await client.get(
                POLY_EVENTS,
                params={
                    "closed": "false",
                    "active": "true",
                    "order": "volume24hr",
                    "ascending": "false",
                    "limit": "100",
                },
            )
            if r.status_code != 200:
                return 0
            events = r.json()
        except Exception:  # noqa: BLE001
            return 0
        for ev in events if isinstance(events, list) else []:
            for m in ev.get("markets", []):
                q = m.get("question") or ev.get("title") or ""
                cat = _categorize(q)
                if not cat:
                    continue
                yes = _poly_yes(m)
                if yes is None:
                    continue
                chg = clean_float(m.get("oneDayPriceChange"))
                prev_prob = (yes - chg) if chg is not None else None
                self._upsert(
                    "polymarket",
                    m.get("id") or m.get("conditionId"),
                    q,
                    yes,
                    prev_prob,
                    clean_float(m.get("volume") or ev.get("volume")),
                    cat,
                )
                n += 1
        return n

    def _upsert(self, venue, market_id, question, yes_prob, prev_prob, volume, category) -> None:
        if not market_id:
            return
        self.db.execute(
            "INSERT INTO prediction_markets"
            "(venue,market_id,question,yes_prob,prev_prob,volume,category,fetched_at) "
            "VALUES(?,?,?,?,?,?,?,?) "
            "ON CONFLICT(venue,market_id) DO UPDATE SET "
            "yes_prob=excluded.yes_prob, prev_prob=excluded.prev_prob, volume=excluded.volume, "
            "question=excluded.question, category=excluded.category, fetched_at=excluded.fetched_at",
            (
                venue,
                str(market_id),
                question[:300],
                yes_prob,
                prev_prob,
                volume,
                category,
                utcnow_iso(),
            ),
        )


def _mid(m: dict) -> float | None:
    bid = clean_float(m.get("yes_bid"))
    ask = clean_float(m.get("yes_ask"))
    if bid is not None and ask is not None:
        return (bid + ask) / 200  # cents → prob
    return None


def _poly_yes(m: dict) -> float | None:
    import json

    raw = m.get("outcomePrices")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return None
    if isinstance(raw, list) and raw:
        return clean_float(raw[0])
    return None
