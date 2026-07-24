"""C9/C10/C11 SEC EDGAR. Keyless but requires a real contact UA.

* CIK map: ``company_tickers.json`` → fill ``instruments.cik`` (cached daily).
* Filings: per holding/active CIK, poll ``data.sec.gov/submissions/CIK{cik}.json`` for new
  filings; 8-K item codes drive a materiality prior *before* the LLM sees anything.
* Form 4: parse the ownership XML → ``insider_trades``; ≥3 distinct insiders buying within
  14d → cluster flag (feeds the ``insider-cluster`` alert).

Rate-limited to be a good EDGAR citizen (≤10 req/s; we poll far slower).
"""

from __future__ import annotations

import asyncio
import re

import httpx

from ..util import norm_ticker, to_json, utcnow_iso
from .base import BaseConnector, FetchResult, register

SUBMISSIONS = "https://data.sec.gov/submissions/CIK{cik}.json"
TICKERS_MAP = "https://www.sec.gov/files/company_tickers.json"

# 8-K item-code materiality prior (0–5) before any LLM triage.
ITEM_MATERIALITY = {
    "1.03": 5,  # bankruptcy / receivership
    "5.02": 4,  # departure/appointment of directors or officers
    "1.01": 3,  # entry into a material definitive agreement
    "2.02": 3,  # results of operations (earnings)
    "2.01": 3,  # completion of acquisition/disposition
    "1.02": 3,  # termination of a material agreement
    "8.01": 2,  # other events
    "7.01": 2,  # Reg FD disclosure
    "5.07": 2,  # shareholder vote
    "9.01": 1,  # financial statements & exhibits
}
_HIGH_ITEMS = {"1.03", "5.02", "1.01"}  # P0 for holdings


@register
class EdgarConnector(BaseConnector):
    name = "edgar"
    requires = ["sec_user_agent"]  # UA is mandatory; without it we can't be a good citizen

    def _headers(self) -> dict:
        return {"User-Agent": self.settings.secrets.sec_user_agent, "Accept": "application/json"}

    def _target_tickers(self) -> list[str]:
        cfg = self.settings.config
        return [
            norm_ticker(t)
            for t in dict.fromkeys(cfg.watchlist.holdings + cfg.watchlist.active)
            if not t.endswith("-USD")
        ]

    async def fetch(self) -> FetchResult:
        async with httpx.AsyncClient(timeout=25, headers=self._headers()) as client:
            await self._ensure_cik_map(client)
            new_filings = 0
            insiders = 0
            for ticker in self._target_tickers():
                cik = self._cik_for(ticker)
                if not cik:
                    continue
                try:
                    nf, ni = await self._poll_cik(client, ticker, cik)
                    new_filings += nf
                    insiders += ni
                except Exception:  # noqa: BLE001
                    continue
                await asyncio.sleep(0.15)  # stay well under 10 req/s
        return FetchResult(new_filings, f"{new_filings} filings, {insiders} insider rows")

    # -- CIK map ----------------------------------------------------------
    async def _ensure_cik_map(self, client: httpx.AsyncClient) -> None:
        last = self.db.get_setting("edgar.cikmap_at")
        if last and (utcnow_iso()[:10] == last[:10]):
            return
        try:
            r = await client.get(TICKERS_MAP)
            data = r.json()
            by_ticker = {}
            for row in data.values():
                by_ticker[norm_ticker(row["ticker"])] = str(row["cik_str"]).zfill(10)
            for ticker in self._target_tickers():
                cik = by_ticker.get(ticker)
                if cik:
                    self.db.execute("UPDATE instruments SET cik=? WHERE ticker=?", (cik, ticker))
            self.db.set_setting("edgar.cikmap_at", utcnow_iso())
        except Exception:  # noqa: BLE001
            pass

    def _cik_for(self, ticker: str) -> str | None:
        row = self.db.query_one("SELECT cik FROM instruments WHERE ticker=?", (ticker,))
        return row["cik"] if row and row["cik"] else None

    # -- per-company polling ---------------------------------------------
    async def _poll_cik(self, client: httpx.AsyncClient, ticker: str, cik: str) -> tuple[int, int]:
        r = await client.get(SUBMISSIONS.format(cik=cik))
        if r.status_code != 200:
            return 0, 0
        data = r.json()
        recent = data.get("filings", {}).get("recent", {})
        forms = recent.get("form", [])
        accns = recent.get("accessionNumber", [])
        dates = recent.get("filingDate", [])
        items = recent.get("items", [])
        primary = recent.get("primaryDocument", [])
        new_filings = insiders = 0
        for i in range(min(len(forms), 40)):  # only the newest 40 per company per poll
            accession = accns[i]
            if self.db.query_one("SELECT id FROM filings WHERE accession=?", (accession,)):
                continue
            form = forms[i]
            item_codes = [
                c.strip() for c in (items[i] if i < len(items) else "").split(",") if c.strip()
            ]
            materiality = self._materiality(form, item_codes)
            url = _filing_url(cik, accession, primary[i] if i < len(primary) else "")
            filing_id = self.db.execute(
                "INSERT INTO filings(accession,cik,ticker,form,filed_at,url,items_json,materiality) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (accession, cik, ticker, form, dates[i], url, to_json(item_codes), materiality),
            )
            new_filings += 1
            self._maybe_alert_filing(ticker, form, item_codes, materiality, filing_id)
            if form in ("4", "4/A"):
                insiders += await self._parse_form4(
                    client, ticker, cik, accession, dates[i], filing_id
                )
        return new_filings, insiders

    def _materiality(self, form: str, items: list[str]) -> int:
        if form.startswith("8-K"):
            return max([ITEM_MATERIALITY.get(c, 2) for c in items] or [2])
        return {
            "10-K": 4,
            "10-Q": 3,
            "S-1": 3,
            "13F": 2,
            "4": 2,
            "3": 1,
            "SC 13D": 4,
            "SC 13G": 2,
        }.get(form, 2)

    def _maybe_alert_filing(
        self, ticker: str, form: str, items: list[str], materiality: int, fid: int
    ) -> None:
        is_holding = norm_ticker(ticker) in {
            norm_ticker(t) for t in self.settings.config.watchlist.holdings
        }
        if not (form.startswith("8-K") and is_holding):
            return
        high = any(c in _HIGH_ITEMS for c in items)
        from ..notify import Notification, get_router

        get_router(self.settings).send(
            Notification(
                priority="P0" if high else "P1",
                title=f"8-K filed: {ticker}",
                body=f"Items {', '.join(items) or '—'} (materiality {materiality})",
                dedupe_key=f"filing:{fid}",
                click_path="/filings",
                cooldown_s=0,
            )
        )

    # -- Form 4 insider parse --------------------------------------------
    async def _parse_form4(
        self,
        client: httpx.AsyncClient,
        ticker: str,
        cik: str,
        accession: str,
        filed: str,
        filing_id: int,
    ) -> int:
        try:
            xml = await _fetch_form4_xml(client, cik, accession)
            if not xml:
                return 0
            rows = _extract_form4(xml)
            n = 0
            for row in rows:
                self.db.execute(
                    "INSERT INTO insider_trades"
                    "(filing_id,ticker,insider_name,role,action,shares,price,value_usd,traded_at) "
                    "VALUES(?,?,?,?,?,?,?,?,?)",
                    (
                        filing_id,
                        ticker,
                        row["name"],
                        row["role"],
                        row["action"],
                        row["shares"],
                        row["price"],
                        (row["shares"] or 0) * (row["price"] or 0),
                        filed,
                    ),
                )
                n += 1
            self._detect_cluster(ticker)
            return n
        except Exception:  # noqa: BLE001
            return 0

    def _detect_cluster(self, ticker: str) -> None:
        """≥3 distinct insiders buying (P) within 14 days → cluster + P1."""
        from datetime import timedelta

        from ..util import iso, utcnow

        cutoff = iso(utcnow() - timedelta(days=14))
        row = self.db.query_one(
            "SELECT COUNT(DISTINCT insider_name) n FROM insider_trades "
            "WHERE ticker=? AND action='P' AND traded_at>=?",
            (ticker, cutoff[:10]),
        )
        if row and row["n"] >= 3:
            self.db.execute(
                "UPDATE insider_trades SET cluster_flag=1 WHERE ticker=? AND action='P' AND traded_at>=?",
                (ticker, cutoff[:10]),
            )
            from ..notify import Notification, get_router

            get_router(self.settings).send(
                Notification(
                    priority="P1",
                    title=f"Insider cluster buy: {ticker}",
                    body=f"{row['n']} distinct insiders bought in the last 14 days",
                    dedupe_key=f"insider-cluster:{ticker}",
                    cooldown_s=86400,
                    click_path="/filings",
                )
            )


def _filing_url(cik: str, accession: str, primary: str) -> str:
    acc_nodash = accession.replace("-", "")
    base = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc_nodash}"
    return f"{base}/{primary}" if primary else f"{base}/"


async def _fetch_form4_xml(client: httpx.AsyncClient, cik: str, accession: str) -> str | None:
    acc_nodash = accession.replace("-", "")
    idx = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc_nodash}/{accession}-index.htm"
    r = await client.get(idx)
    m = re.findall(r'href="([^"]+\.xml)"', r.text)
    for href in m:
        if "form" in href.lower() or "ownership" in href.lower() or href.endswith(".xml"):
            url = "https://www.sec.gov" + href if href.startswith("/") else href
            doc = await client.get(url)
            if "<ownershipDocument" in doc.text:
                return doc.text
    return None


def _extract_form4(xml: str) -> list[dict]:
    name = _tag(xml, "rptOwnerName") or "insider"
    role = "officer" if "<isOfficer>1" in xml else ("director" if "<isDirector>1" in xml else "10%")
    rows = []
    for block in re.findall(
        r"<nonDerivativeTransaction>(.*?)</nonDerivativeTransaction>", xml, re.S
    ):
        code = _tag(block, "transactionCode") or ""
        shares = _num(_tag(block, "transactionShares") or _val(block, "transactionShares"))
        price = _num(
            _tag(block, "transactionPricePerShare") or _val(block, "transactionPricePerShare")
        )
        action = {"P": "P", "S": "S", "A": "A"}.get(code, code[:1] or "A")
        rows.append(
            {"name": name, "role": role, "action": action, "shares": shares, "price": price}
        )
    return rows


def _tag(xml: str, tag: str) -> str | None:
    m = re.search(rf"<{tag}>(.*?)</{tag}>", xml, re.S)
    return m.group(1).strip() if m else None


def _val(block: str, tag: str) -> str | None:
    m = re.search(rf"<{tag}>.*?<value>(.*?)</value>", block, re.S)
    return m.group(1).strip() if m else None


def _num(s: str | None) -> float | None:
    if not s:
        return None
    try:
        return float(re.sub(r"[^0-9.\-]", "", s))
    except ValueError:
        return None
