"""C4/C5 crypto via CoinGecko (public) + alternative.me Fear & Greed.

CoinGecko demo key is optional — public endpoints work keyless. Prices, 24h change and
market caps land in ``quotes_latest``; BTC dominance and crypto F&G go to ``settings``
for the regime model and the crypto brief. ccxt provides OHLCV where a venue is needed.
"""

from __future__ import annotations

import httpx

from ..util import clean_float, norm_ticker
from .base import BaseConnector, FetchResult, register

COINGECKO = "https://api.coingecko.com/api/v3"

# ticker -> coingecko id
COIN_IDS = {
    "BTC-USD": "bitcoin",
    "ETH-USD": "ethereum",
    "SOL-USD": "solana",
    "XRP-USD": "ripple",
    "DOGE-USD": "dogecoin",
    "ADA-USD": "cardano",
    "AVAX-USD": "avalanche-2",
    "LINK-USD": "chainlink",
}


@register
class CryptoConnector(BaseConnector):
    name = "crypto"
    requires: list[str] = []  # public endpoints; COINGECKO_KEY optional

    def _tickers(self) -> list[str]:
        rows = self.db.query("SELECT ticker FROM instruments WHERE kind='crypto'")
        seen = {norm_ticker(r["ticker"]) for r in rows} | {"BTC-USD", "ETH-USD", "SOL-USD"}
        return [t for t in seen if t in COIN_IDS]

    def _headers(self) -> dict:
        h = {"User-Agent": self.http_ua, "Accept": "application/json"}
        key = self.settings.secrets.coingecko_key
        if key:
            h["x-cg-demo-api-key"] = key
        return h

    async def fetch(self) -> FetchResult:
        tickers = self._tickers()
        ids = ",".join(COIN_IDS[t] for t in tickers)
        n = 0
        async with httpx.AsyncClient(timeout=20, headers=self._headers()) as client:
            # prices + 24h change + market cap
            r = await client.get(
                f"{COINGECKO}/simple/price",
                params={
                    "ids": ids,
                    "vs_currencies": "usd",
                    "include_24hr_change": "true",
                    "include_market_cap": "true",
                },
            )
            r.raise_for_status()
            prices = r.json()
            id_to_ticker = {v: k for k, v in COIN_IDS.items()}
            for cid, d in prices.items():
                ticker = id_to_ticker.get(cid)
                price = clean_float(d.get("usd"))
                if not ticker or price is None:
                    continue
                chg = clean_float(d.get("usd_24h_change")) or 0.0
                prev = price / (1 + chg / 100) if chg != -100 else None
                self.upsert_quote(
                    ticker,
                    price=price,
                    prev_close=prev,
                    volume=clean_float(d.get("usd_market_cap")),
                    source="coingecko",
                    is_stale=0,
                    kind="crypto",
                )
                self._push_tick(ticker, price, chg)
                n += 1

            # global dominance
            try:
                g = (await client.get(f"{COINGECKO}/global")).json().get("data", {})
                self.db.set_setting(
                    "crypto.global",
                    {
                        "btc_dominance": clean_float(g.get("market_cap_percentage", {}).get("btc")),
                        "eth_dominance": clean_float(g.get("market_cap_percentage", {}).get("eth")),
                        "total_mcap_usd": clean_float(g.get("total_market_cap", {}).get("usd")),
                    },
                )
            except Exception:  # noqa: BLE001
                pass

        await self._fetch_fng()
        return FetchResult(n, f"{n} coins + F&G")

    async def _fetch_fng(self) -> None:
        """alternative.me crypto Fear & Greed (0–100)."""
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                r = await client.get("https://api.alternative.me/fng/?limit=1")
                d = r.json()["data"][0]
                self.db.set_setting(
                    "crypto.fng",
                    {"value": int(d["value"]), "label": d["value_classification"]},
                )
        except Exception:  # noqa: BLE001
            pass

    def _push_tick(self, ticker: str, price: float, chg: float) -> None:
        from ..api.events import publish

        publish(
            "quote", {"ticker": ticker, "price": price, "change_pct": chg, "source": "coingecko"}
        )
