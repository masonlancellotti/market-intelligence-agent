"""Phase 1 tests: connector base (circuit breaker, disable), Parquet store, markets API.

Network-free: yfinance is monkeypatched with a synthetic series so tests are fast and
deterministic.
"""

from __future__ import annotations

import polars as pl
import pytest

from meridian.connectors.base import BaseConnector, FetchResult
from meridian.connectors.history import backfill_one, read_daily, write_daily


def _fake_daily(days: int = 40) -> pl.DataFrame:
    import datetime as dt

    base = dt.date(2026, 1, 1)
    rows = []
    px = 100.0
    for i in range(days):
        px *= 1.001 + (0.01 if i % 3 == 0 else -0.004)
        d = base + dt.timedelta(days=i)
        rows.append(
            {
                "date": d.isoformat(),
                "open": px * 0.99,
                "high": px * 1.02,
                "low": px * 0.98,
                "close": px,
                "adj_close": px,
                "volume": 1_000_000 + i,
            }
        )
    return pl.DataFrame(rows)


def test_parquet_roundtrip(home):
    df = _fake_daily()
    write_daily("TEST", df, home)
    got = read_daily("TEST", settings=home)
    assert got.height == df.height
    assert abs(got.row(-1, named=True)["close"] - df.row(-1, named=True)["close"]) < 1e-9
    assert read_daily("TEST", lookback=5, settings=home).height == 5


def test_backfill_updates_quotes(home, db, monkeypatch):
    import meridian.connectors.history as H

    monkeypatch.setattr(H, "fetch_daily_yf", lambda t, years=5: _fake_daily(30))
    res = backfill_one("MSFT", settings=home)
    assert res["ok"] and res["rows"] == 30
    q = db.query_one(
        "SELECT price, prev_close, is_stale FROM quotes_latest q "
        "JOIN instruments i ON i.id=q.instrument_id WHERE i.ticker='MSFT'"
    )
    assert q is not None and q["price"] is not None
    assert q["is_stale"] == 1  # EOD-seeded quote is flagged stale


def test_connector_disabled_without_keys(home):
    class NeedsKey(BaseConnector):
        name = "needs_key"
        requires = ["alpaca_key_id"]

        async def fetch(self):
            raise AssertionError("should not run when disabled")

    res = NeedsKey(home).run_sync()
    assert res["status"] == "disabled"
    assert "alpaca_key_id" in res["missing"]


def test_circuit_breaker_opens(home, db):
    class Flaky(BaseConnector):
        name = "flaky"
        circuit_threshold = 3

        async def fetch(self):
            raise RuntimeError("boom")

    c = Flaky(home)
    for _ in range(3):
        r = c.run_sync()
        assert r["status"] in ("error",)
    row = db.query_one(
        "SELECT status, error_streak, circuit_open_until FROM connector_health WHERE connector='flaky'"
    )
    assert row["status"] == "red"
    assert row["error_streak"] >= 3
    assert row["circuit_open_until"] is not None
    # next run short-circuits
    assert c.run_sync()["status"] == "circuit_open"


def test_connector_success_marks_health(home, db):
    class Good(BaseConnector):
        name = "good"

        async def fetch(self):
            return FetchResult(items=7, detail="ok")

    assert Good(home).run_sync()["items"] == 7
    row = db.query_one(
        "SELECT status, items_24h, error_streak FROM connector_health WHERE connector='good'"
    )
    assert row["status"] == "ok" and row["items_24h"] == 7 and row["error_streak"] == 0


@pytest.mark.asyncio
async def test_markets_api(home, db, monkeypatch):
    from httpx import ASGITransport, AsyncClient

    import meridian.connectors.history as H

    monkeypatch.setattr(H, "fetch_daily_yf", lambda t, years=5: _fake_daily(300))
    backfill_one("SPY", settings=home)

    from meridian.app import create_app

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as ac:
        m = await ac.get("/api/markets")
        assert m.status_code == 200
        assert m.json()["count"] >= 1
        h = await ac.get("/api/markets/SPY/history?range=1M")
        assert h.status_code == 200
        assert h.json()["count"] == 22  # 1M lookback
