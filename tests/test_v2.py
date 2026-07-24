"""V2 tests: live refresh (dry-run), historical regime backfill, rule backtests, APIs.

Hermetic — synthetic Parquet history seeded into an isolated MERIDIAN_HOME; no network.
"""

from __future__ import annotations

import numpy as np
import polars as pl
import pytest

REGIME_SEED_TICKERS = [
    "SPY",
    "QQQ",
    "IWM",
    "^VIX",
    "^VIX3M",
    "UUP",
    "HYG",
    "LQD",
    "XLF",
    "XLK",
    "XLE",
    "XLV",
    "XLY",
    "XLP",
    "XLI",
    "XLU",
    "XLB",
    "XLRE",
    "XLC",
]


def _bdays(n: int, end: str = "2026-06-30") -> list[str]:
    end_d = np.datetime64(end)
    days = np.busday_offset(end_d, -np.arange(n)[::-1], roll="backward")
    return [str(d) for d in days]


def _synth(
    ticker: str, n: int, seed: int, base: float, vol: float, level: bool = False
) -> pl.DataFrame:
    rng = np.random.default_rng(seed)
    dates = _bdays(n)
    if level:  # VIX-like mean-reverting level series
        x = np.zeros(n)
        x[0] = base
        for i in range(1, n):
            x[i] = max(9.0, x[i - 1] + (base - x[i - 1]) * 0.05 + rng.normal(0, vol))
        close = x
    else:
        steps = rng.normal(0.0004, vol, n)
        close = base * np.exp(np.cumsum(steps))
    high = close * (1 + np.abs(rng.normal(0, 0.004, n)))
    low = close * (1 - np.abs(rng.normal(0, 0.004, n)))
    open_ = close * (1 + rng.normal(0, 0.003, n))
    return pl.DataFrame(
        {
            "date": dates,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "adj_close": close,
            "volume": rng.integers(1_000_000, 5_000_000, n).astype(float),
        }
    )


def _seed_history(settings, n: int = 360) -> None:
    from meridian.connectors.history import write_daily

    for k, t in enumerate(REGIME_SEED_TICKERS):
        level = t in ("^VIX", "^VIX3M")
        base = 18.0 if level else (400.0 + k * 5)
        vol = 0.9 if level else 0.011
        write_daily(t, _synth(t, n, seed=100 + k, base=base, vol=vol, level=level), settings)


# -- WS1: live refresh dry-run (no network) ------------------------------------
def test_refresh_dry_run_is_hermetic(home):
    from meridian.ops.refresh import format_summary, live_refresh

    out = live_refresh(dry_run=True)
    assert out["dry_run"] is True
    names = {c["connector"] for c in out["would_run"]}
    assert {"prices", "predmkt", "rss", "edgar"} <= names  # keyless core present
    assert "alpaca" not in names and "fred" not in names  # keyed excluded
    assert "no network" in format_summary(out)


def test_refresh_status_reports_snapshot(home, db):
    from meridian.ops.refresh import refresh_status

    st = refresh_status()
    assert st["mode"] == "snapshot"  # nothing refreshed yet
    assert st["last_refresh"] is None


# -- WS2: historical regime --------------------------------------------------
def test_compute_regime_series_deterministic():
    from meridian.signals.regime_history import compute_regime_series

    dates = _bdays(300)
    rng = np.random.default_rng(1)
    spy = 400 * np.exp(np.cumsum(rng.normal(0.0004, 0.01, 300)))
    vix = 15 + 5 * np.abs(rng.normal(0, 1, 300))
    frames = {
        "SPY": spy,
        "^VIX": vix,
        "XLF": spy * 1.01,
        "IWM": spy * 0.99,
        "UUP": np.full(300, 28.0),
    }
    a = compute_regime_series(dates, frames)
    b = compute_regime_series(dates, frames)
    assert a == b  # pure + deterministic
    assert len(a) > 200
    for r in a:
        assert 0 <= r["score"] <= 100
        assert r["bucket"] in ("Risk-On", "Neutral", "Risk-Off")


def test_backfill_regime_persists_rows(home):
    _seed_history(home)
    from meridian.signals.regime_history import backfill_regime, history_rows

    res = backfill_regime(years=2, download=False)
    assert res["ok"] and res["rows"] > 100
    rows = history_rows()
    assert len(rows) == res["rows"]
    assert rows[0]["date"] < rows[-1]["date"]
    assert all(0 <= r["score"] <= 100 for r in rows)


def test_forward_return_stats(home):
    _seed_history(home)
    from meridian.signals.regime_history import backfill_regime, forward_return_stats

    backfill_regime(years=2, download=False)
    stats = forward_return_stats()
    assert stats["n_days"] > 100
    assert "caveat" in stats and "NOT a forecast" in stats["caveat"]
    assert set(stats["by_bucket"]) == {"Risk-On", "Neutral", "Risk-Off"}


# -- WS3: rule backtests -----------------------------------------------------
def test_backtest_rules_generates_resolved_predictions(home):
    _seed_history(home)
    from meridian.conviction.rulebook import backtest_rules, rule_backtest_summary
    from meridian.signals.regime_history import backfill_regime

    backfill_regime(years=2, download=False)
    res = backtest_rules()
    assert res["ok"] and res["resolved"] >= 50  # synthetic window; real 2y clears 200
    summary = rule_backtest_summary()
    assert summary["pooled"]["n"] == res["resolved"]
    assert 0.0 <= summary["pooled"]["mean_brier"] <= 1.0
    assert summary["by_rule"], "expected per-rule breakdown"
    for rule in summary["by_rule"]:
        assert rule["reliability"], "each fired rule has a reliability point"


# -- APIs --------------------------------------------------------------------
@pytest.mark.asyncio
async def test_v2_api_endpoints(home):
    _seed_history(home)
    from meridian.conviction.rulebook import backtest_rules
    from meridian.signals.regime_history import backfill_regime

    backfill_regime(years=2, download=False)
    backtest_rules()

    from httpx import ASGITransport, AsyncClient

    from meridian.app import create_app

    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.get("/api/regime/history")
        assert r.status_code == 200 and r.json()["retrospective"] is True
        assert len(r.json()["history"]) > 100

        r = await ac.get("/api/regime/forward-returns")
        assert r.status_code == 200 and "caveat" in r.json()

        r = await ac.get("/api/calibration/rules")
        assert r.status_code == 200
        body = r.json()
        assert body["pooled"]["n"] > 0 and "RETROSPECTIVE" in body["label"]

        r = await ac.get("/api/system/freshness")
        assert r.status_code == 200 and r.json()["mode"] in ("snapshot", "live")
