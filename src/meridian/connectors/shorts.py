"""C16 short data. FINRA Reg SHO daily short-volume files (keyless).
Short-volume ratio per watchlist ticker stored as a signal (kind='short_vol_ratio').
"""

from __future__ import annotations

from datetime import timedelta

import httpx

from ..util import norm_ticker, utcnow, utcnow_iso
from .base import BaseConnector, FetchResult, register

FINRA = "https://cdn.finra.org/equity/regsho/daily/CNMSshvol{ymd}.txt"


@register
class ShortsConnector(BaseConnector):
    name = "shorts"
    requires: list[str] = []

    def _watch(self) -> set[str]:
        cfg = self.settings.config
        return {
            norm_ticker(t) for t in cfg.watchlist.all() + cfg.benchmarks if not t.endswith("-USD")
        }

    async def fetch(self) -> FetchResult:
        watch = self._watch()
        async with httpx.AsyncClient(timeout=25, headers={"User-Agent": self.http_ua}) as client:
            for back in range(0, 5):  # find the most recent published file
                day = (utcnow() - timedelta(days=back)).strftime("%Y%m%d")
                try:
                    r = await client.get(FINRA.format(ymd=day))
                except Exception:  # noqa: BLE001
                    continue
                if r.status_code != 200 or "Symbol" not in r.text[:100]:
                    continue
                return FetchResult(self._parse(r.text, watch, day), f"regsho {day}")
        return FetchResult(0, "no recent FINRA file")

    def _parse(self, text: str, watch: set[str], ymd: str) -> int:
        bar_date = f"{ymd[0:4]}-{ymd[4:6]}-{ymd[6:8]}"
        n = 0
        for line in text.splitlines()[1:]:
            parts = line.split("|")
            if len(parts) < 5:
                continue
            sym = norm_ticker(parts[1])
            if sym not in watch:
                continue
            try:
                short_v = float(parts[2])
                total_v = float(parts[4])
            except ValueError:
                continue
            if total_v <= 0:
                continue
            ratio = round(short_v / total_v, 4)
            iid = self.instrument_id(sym)
            self.db.execute(
                "INSERT INTO signals(instrument_id,kind,value,params_json,bar_date,created_at) "
                "VALUES(?,?,?,?,?,?) ON CONFLICT(instrument_id,kind,bar_date) DO UPDATE SET "
                "value=excluded.value",
                (iid, "short_vol_ratio", ratio, "{}", bar_date, utcnow_iso()),
            )
            n += 1
        return n
