"""C15 sentiment extras. CNN Fear & Greed (keyless, needs a browser UA).
Stored to ``settings`` for the regime model and briefs. AAII/Stocktwits are best-effort
add-ons and skipped silently if unreachable.
"""

from __future__ import annotations

import httpx

from ..util import clean_float, utcnow_iso
from .base import BaseConnector, FetchResult, register

CNN_FNG = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
_BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


@register
class SentimentConnector(BaseConnector):
    name = "sentiment"
    requires: list[str] = []

    async def fetch(self) -> FetchResult:
        n = 0
        async with httpx.AsyncClient(timeout=20, headers={"User-Agent": _BROWSER_UA}) as client:
            try:
                r = await client.get(CNN_FNG)
                if r.status_code == 200 and r.text.strip().startswith("{"):
                    d = r.json().get("fear_and_greed", {})
                    score = clean_float(d.get("score"))
                    if score is not None:
                        self.db.set_setting(
                            "sentiment.cnn_fng",
                            {
                                "score": round(score, 1),
                                "rating": d.get("rating"),
                                "at": utcnow_iso(),
                            },
                        )
                        n += 1
            except Exception:  # noqa: BLE001
                pass
        return FetchResult(n, "CNN F&G" if n else "CNN F&G unavailable")
