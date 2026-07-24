"""Phase 2 tests: dedup/clustering, triage heuristic, EDGAR/predmkt parsing, news/macro API."""

from __future__ import annotations

import pytest

from meridian.connectors.edgar import _extract_form4


def test_canonical_url_strips_trackers(home):
    from meridian.connectors.textproc import canonical_url

    a = canonical_url("https://x.com/a/b?utm_source=nl&id=5&fbclid=zzz")
    assert "utm_source" not in a and "fbclid" not in a and "id=5" in a
    assert canonical_url("https://X.com/a/b/") == canonical_url("https://x.com/a/b")


def test_news_dedup_and_cluster(home, db):
    from meridian.connectors.textproc import ingest_news

    items = [
        {
            "source": "A",
            "url": "https://a.com/story-1",
            "title": "Nvidia beats earnings badly wrong",
            "summary": "x",
        },
        {
            "source": "B",
            "url": "https://b.com/story-1",
            "title": "Nvidia beats earnings badly wrong",
            "summary": "x",
        },
        {"source": "A", "url": "https://a.com/story-1?utm_source=z", "title": "dup", "summary": ""},
    ]
    stats = ingest_news(items, home)
    assert stats["inserted"] == 2  # 3rd is a canonical-URL dup of the 1st
    assert stats["duplicates"] == 1
    # identical titles → same cluster
    clusters = db.query("SELECT cluster_id, COUNT(*) n FROM news_items GROUP BY cluster_id")
    assert any(r["n"] == 2 for r in clusters)


def test_extract_tickers(home):
    from meridian.connectors.textproc import extract_tickers

    hits = extract_tickers(
        "NVDA and MSFT rally; bitcoin BTC steady", ["NVDA", "MSFT", "BTC-USD", "AMZN"]
    )
    assert set(hits) == {"NVDA", "MSFT", "BTC-USD"}


def test_triage_heuristic_materiality(home, db):
    from meridian.agents.triage import _heuristic

    class Row(dict):
        def __getitem__(self, k):
            return self.get(k)

    r = Row(
        id=1,
        source="Reuters",
        title="Acme files for bankruptcy protection",
        summary="",
        tickers_json='["NVDA"]',
    )
    res = _heuristic(r)
    assert res["materiality"] == 5  # high source + bankruptcy + ticker, capped
    assert res["category"] in ("regulatory", "general")
    low = _heuristic(Row(id=2, source="blog", title="A quiet day", summary="", tickers_json="[]"))
    assert low["materiality"] <= 2


def test_edgar_item_materiality(home):
    from meridian.connectors.edgar import EdgarConnector

    c = EdgarConnector(home)
    assert c._materiality("8-K", ["1.03"]) == 5
    assert c._materiality("8-K", ["9.01"]) == 1
    assert c._materiality("8-K", ["2.02", "9.01"]) == 3
    assert c._materiality("10-K", []) == 4


def test_form4_parse(home):
    xml = """
    <ownershipDocument>
      <reportingOwner><reportingOwnerId><rptOwnerName>Jane Insider</rptOwnerName></reportingOwnerId></reportingOwner>
      <isOfficer>1</isOfficer>
      <nonDerivativeTransaction>
        <transactionCoding><transactionCode>P</transactionCode></transactionCoding>
        <transactionAmounts>
          <transactionShares><value>1000</value></transactionShares>
          <transactionPricePerShare><value>50.5</value></transactionPricePerShare>
        </transactionAmounts>
      </nonDerivativeTransaction>
    </ownershipDocument>
    """
    rows = _extract_form4(xml)
    assert len(rows) == 1
    assert rows[0]["name"] == "Jane Insider"
    assert rows[0]["action"] == "P"
    assert rows[0]["shares"] == 1000 and rows[0]["price"] == 50.5


def test_predmkt_categorize(home):
    from meridian.connectors.predmkt import _categorize

    assert _categorize("Will the Fed cut rates in September?") == "fed"
    assert _categorize("CPI above 3% in July?") == "cpi"
    assert _categorize("Who wins the Super Bowl?") is None


@pytest.mark.asyncio
async def test_news_and_macro_api(home, db):
    from httpx import ASGITransport, AsyncClient

    from meridian.util import utcnow_iso

    db.execute(
        "INSERT INTO news_items(source,url,title,summary,published_at,fetched_at,tickers_json,"
        "materiality,category) VALUES('R','http://n/1','NVDA news','',?,?,'[\"NVDA\"]',4,'earnings')",
        (utcnow_iso(), utcnow_iso()),
    )
    db.execute(
        "INSERT INTO prediction_markets(venue,market_id,question,yes_prob,category,fetched_at) "
        "VALUES('kalshi','m1','Fed cut?',0.7,'fed',?)",
        (utcnow_iso(),),
    )
    from meridian.app import create_app

    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        n = await ac.get("/api/news?min_materiality=3")
        assert n.status_code == 200 and n.json()["count"] == 1
        nt = await ac.get("/api/news?ticker=NVDA")
        assert nt.json()["count"] == 1
        m = await ac.get("/api/macro")
        assert m.status_code == 200 and len(m.json()["fed_odds"]) == 1
