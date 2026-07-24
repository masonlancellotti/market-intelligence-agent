"""C13 economic calendar. ForexFactory weekly XML (keyless) for macro
releases; Finnhub earnings calendar (keyed, degrades) for watchlist earnings dates.
Surprise scoring happens when the actual prints.
"""

from __future__ import annotations

import re

import httpx

from ..util import clean_float, utcnow_iso
from .base import BaseConnector, FetchResult, register

FF_XML = "https://nfs.faireconomy.media/ff_calendar_thisweek.xml"

_IMPORTANCE = {"High": "high", "Medium": "medium", "Low": "low", "Holiday": "low"}


@register
class EconCalendarConnector(BaseConnector):
    name = "calendar"
    requires: list[str] = []

    async def fetch(self) -> FetchResult:
        n = 0
        async with httpx.AsyncClient(timeout=25, headers={"User-Agent": self.http_ua}) as client:
            n += await self._forexfactory(client)
            n += await self._earnings(client)
        return FetchResult(n, f"{n} calendar events")

    async def _forexfactory(self, client: httpx.AsyncClient) -> int:
        try:
            r = await client.get(FF_XML)
            if r.status_code != 200:
                return 0
            xml = r.text
        except Exception:  # noqa: BLE001
            return 0
        n = 0
        for block in re.findall(r"<event>(.*?)</event>", xml, re.S):
            title = _tag(block, "title")
            country = _tag(block, "country")
            impact = _IMPORTANCE.get(_tag(block, "impact") or "", "low")
            # keep US events + all High-impact events globally
            not_us = not title or country not in ("USD", "United States", "US")
            if not_us and impact != "high":
                continue
            date = _tag(block, "date")
            time_ = _tag(block, "time")
            scheduled = _parse_ff_datetime(date, time_)
            importance = _IMPORTANCE.get(_tag(block, "impact") or "", "low")
            self.db.execute(
                "INSERT INTO econ_events(name,country,scheduled_at,importance,consensus,previous,actual)"
                " VALUES(?,?,?,?,?,?,?) "
                "ON CONFLICT(name,scheduled_at) DO UPDATE SET consensus=excluded.consensus, "
                "previous=excluded.previous, importance=excluded.importance",
                (
                    title,
                    country or "US",
                    scheduled,
                    importance,
                    _tag(block, "forecast"),
                    _tag(block, "previous"),
                    _tag(block, "actual"),
                ),
            )
            n += 1
        return n

    async def _earnings(self, client: httpx.AsyncClient) -> int:
        key = self.settings.secrets.finnhub_key
        if not key:
            return 0
        from datetime import timedelta

        from ..util import iso, utcnow

        frm = utcnow().date().isoformat()
        to = iso(utcnow() + timedelta(days=14))[:10]
        try:
            r = await client.get(
                "https://finnhub.io/api/v1/calendar/earnings",
                params={"from": frm, "to": to, "token": key},
            )
            if r.status_code != 200:
                return 0
            watch = {
                t.upper()
                for t in self.settings.config.watchlist.holdings
                + self.settings.config.watchlist.active
            }
            n = 0
            for e in r.json().get("earningsCalendar", []):
                sym = (e.get("symbol") or "").upper()
                if sym not in watch:
                    continue
                self.db.execute(
                    "INSERT INTO econ_events(name,country,scheduled_at,importance,consensus,previous,actual)"
                    " VALUES(?,?,?,?,?,?,?) ON CONFLICT(name,scheduled_at) DO NOTHING",
                    (
                        f"{sym} earnings",
                        "US",
                        f"{e.get('date')}T12:00:00Z",
                        "high",
                        str(clean_float(e.get("epsEstimate")) or ""),
                        "",
                        "",
                    ),
                )
                n += 1
            return n
        except Exception:  # noqa: BLE001
            return 0


def _tag(block: str, tag: str) -> str | None:
    m = re.search(rf"<{tag}>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</{tag}>", block, re.S)
    return m.group(1).strip() if m else None


def _parse_ff_datetime(date: str | None, time_: str | None) -> str:
    # FF date like "07-05-2026", time like "8:30am" or "All Day" / "Tentative"
    if not date:
        return utcnow_iso()
    try:
        from datetime import datetime

        base = datetime.strptime(date, "%m-%d-%Y")
        if time_ and re.match(r"\d", time_):
            t = datetime.strptime(time_.strip().lower(), "%I:%M%p")
            base = base.replace(hour=t.hour, minute=t.minute)
        # FF times are ET; store as naive-ET-labelled UTC-ish (surprise scoring uses date)
        return base.isoformat() + "Z"
    except Exception:  # noqa: BLE001
        return f"{date}Z"
