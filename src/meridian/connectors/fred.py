"""C12 macro series via FRED. Requires FRED_API_KEY (free); auto-disabled
without it. ~25 series covering rates, curve, inflation, labor, credit, liquidity, USD.
"""

from __future__ import annotations

import asyncio

import httpx

from ..util import clean_float, utcnow_iso
from .base import BaseConnector, FetchResult, register

FRED = "https://api.stlouisfed.org/fred/series/observations"
FRED_META = "https://api.stlouisfed.org/fred/series"

SERIES = [
    "DGS2",
    "DGS10",
    "DGS30",
    "T10Y2Y",
    "T10Y3M",
    "FEDFUNDS",
    "CPIAUCSL",
    "CPILFESL",
    "PCEPILFE",
    "UNRATE",
    "PAYEMS",
    "ICSA",
    "WALCL",
    "RRPONTSYD",
    "BAMLH0A0HYM2",
    "BAMLC0A0CM",
    "NFCI",
    "DTWEXBGS",
    "VIXCLS",
    "UMCSENT",
    "RSAFS",
    "INDPRO",
    "HOUST",
    "GASREGW",
    "M2SL",
]


@register
class FredConnector(BaseConnector):
    name = "fred"
    requires = ["fred_api_key"]

    async def fetch(self) -> FetchResult:
        key = self.settings.secrets.fred_api_key
        points = 0
        async with httpx.AsyncClient(timeout=25, headers={"User-Agent": self.http_ua}) as client:
            for sid in SERIES:
                try:
                    points += await self._one(client, key, sid)
                except Exception:  # noqa: BLE001
                    continue
                await asyncio.sleep(0.05)
        return FetchResult(points, f"{points} obs across {len(SERIES)} series")

    async def _one(self, client: httpx.AsyncClient, key: str, sid: str) -> int:
        # metadata (units/freq) once
        meta = await client.get(
            FRED_META, params={"series_id": sid, "api_key": key, "file_type": "json"}
        )
        if meta.status_code == 200:
            m = meta.json().get("seriess", [{}])[0]
            self.db.execute(
                "INSERT INTO macro_series(series_id,name,units,freq,last_updated) VALUES(?,?,?,?,?) "
                "ON CONFLICT(series_id) DO UPDATE SET name=excluded.name, units=excluded.units, "
                "freq=excluded.freq, last_updated=excluded.last_updated",
                (sid, m.get("title"), m.get("units"), m.get("frequency_short"), utcnow_iso()),
            )
        r = await client.get(
            FRED,
            params={
                "series_id": sid,
                "api_key": key,
                "file_type": "json",
                "sort_order": "desc",
                "limit": "260",
            },
        )
        if r.status_code != 200:
            return 0
        n = 0
        for obs in r.json().get("observations", []):
            v = clean_float(obs.get("value"))
            if v is None:
                continue
            self.db.execute(
                "INSERT INTO macro_points(series_id,date,value) VALUES(?,?,?) "
                "ON CONFLICT(series_id,date) DO UPDATE SET value=excluded.value",
                (sid, obs["date"], v),
            )
            n += 1
        return n
