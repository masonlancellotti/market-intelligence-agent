"""Phase 4 tests: fact-checker (catches false numbers), degrade brief, event surprise, API."""

from __future__ import annotations

import pytest

from meridian.briefs import factcheck
from meridian.briefs.events import compute_surprise
from meridian.util import utcnow_iso


def _seed_market(db):
    for ticker, price, prev, kind, tier in [
        ("^VIX", 16.15, 16.6, "index", "benchmark"),
        ("SPY", 744.78, 745.76, "etf", "active"),
        ("NVDA", 194.83, 197.58, "equity", "holding"),
    ]:
        iid = db.execute(
            "INSERT INTO instruments(ticker,name,kind,tier) VALUES(?,?,?,?)",
            (ticker, ticker, kind, tier),
        )
        db.execute(
            "INSERT INTO quotes_latest(instrument_id,price,prev_close,source,ts) VALUES(?,?,?,'t',?)",
            (iid, price, prev, utcnow_iso()),
        )


def test_factcheck_all_present_and_matching(home, db):
    evidence = {
        "b:NVDA": {"value": 194.83, "kind": "bar"},
        "b:^VIX": {"value": 16.149, "kind": "bar"},
        "n:5": {"value": 4, "kind": "news"},
    }
    md = "NVDA $194.83 [b:NVDA] · VIX 16.1 [b:^VIX] · story [n:5]"
    res = factcheck.validate(md, evidence)
    assert res["ok"] is True
    assert res["checked_numbers"] >= 2  # display-precision match (16.1 vs 16.149)


def test_factcheck_catches_false_number(home, db):
    evidence = {"b:NVDA": {"value": 194.83, "kind": "bar"}}
    md = "NVDA $999.99 [b:NVDA]"
    res = factcheck.validate(md, evidence)
    assert res["ok"] is False
    assert res["numeric_mismatches"][0]["id"] == "b:NVDA"
    assert res["numeric_mismatches"][0]["claimed"] == 999.99


def test_factcheck_catches_missing_marker(home, db):
    res = factcheck.validate("something [n:999] happened", {})
    assert res["ok"] is False
    assert "n:999" in res["missing_markers"]


def test_factcheck_ignores_percent_changes(home, db):
    # a signed percent change next to a price marker must NOT be validated as the price
    evidence = {"b:ES=F": {"value": 7557.0, "kind": "bar"}}
    md = "ES +0.38% [b:ES=F]"
    res = factcheck.validate(md, evidence)
    assert res["ok"] is True and res["checked_numbers"] == 0


def test_compute_surprise():
    assert compute_surprise("3.5", "3.0") == pytest.approx(1.67, abs=0.1)  # (3.5-3)/0.3
    assert compute_surprise("250K", "180K") is not None
    assert compute_surprise("n/a", "3.0") is None


def test_degrade_brief_generates(home, db):
    _seed_market(db)
    db.set_setting("regime.latest", {"score": 71.2, "bucket": "Risk-On"})
    db.execute(
        "INSERT INTO news_items(source,url,title,published_at,fetched_at,tickers_json,materiality) "
        "VALUES('R','http://n/1','Big NVDA news',?,?,'[\"NVDA\"]',5)",
        (utcnow_iso(), utcnow_iso()),
    )
    from meridian.briefs import generate_brief

    res = generate_brief("morning", home)
    assert res["mode"] == "template"  # no LLM key
    assert res["cost_usd"] == 0.0
    assert res["factcheck"]["ok"] is True  # degrade renderer is always self-consistent
    md = db.scalar("SELECT markdown FROM briefs WHERE id=?", (res["id"],))
    assert "Morning Brief" in md and "[b:NVDA]" in md


def test_event_flash_fires_on_surprise(home, db):
    _seed_market(db)
    db.set_setting("regime.latest", {"score": 50, "bucket": "Neutral"})
    db.execute(
        "INSERT INTO econ_events(name,country,scheduled_at,importance,consensus,actual) "
        "VALUES('CPI','US',?, 'high','3.0','4.2')",
        (utcnow_iso(),),
    )
    from meridian.briefs.events import check_macro_releases

    out = check_macro_releases(home)
    assert out["fired"] == 1
    b = db.query_one("SELECT kind, markdown FROM briefs WHERE kind='event_flash'")
    assert b is not None and "Event Flash" in b["markdown"]
    # idempotent — doesn't re-flash the same event
    assert check_macro_releases(home)["fired"] == 0


@pytest.mark.asyncio
async def test_briefs_api(home, db):
    from httpx import ASGITransport, AsyncClient

    db.execute(
        "INSERT INTO briefs(kind,for_date,markdown,citations_json,model,cost_usd,created_at) "
        "VALUES('morning','2026-07-05','# Brief\\nhi [b:NVDA]',?,'template',0.0,?)",
        ('{"evidence":{"b:NVDA":{"value":194.83}}}', utcnow_iso()),
    )
    from meridian.app import create_app

    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        lst = await ac.get("/api/briefs")
        assert lst.status_code == 200 and len(lst.json()["briefs"]) == 1
        latest = await ac.get("/api/briefs/latest?kind=morning")
        assert latest.json()["brief"]["evidence"]["b:NVDA"]["value"] == 194.83
