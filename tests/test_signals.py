"""Phase 3 tests: indicator correctness (vs pandas reference), regime, alert engine."""

from __future__ import annotations

import numpy as np
import pandas as pd
import polars as pl
import pytest

from meridian.signals import indicators as ind


def _series(n=400, seed=7):
    rng = np.random.default_rng(seed)
    steps = rng.normal(0.0005, 0.012, n)
    close = 100 * np.exp(np.cumsum(steps))
    high = close * (1 + np.abs(rng.normal(0, 0.006, n)))
    low = close * (1 - np.abs(rng.normal(0, 0.006, n)))
    open_ = close * (1 + rng.normal(0, 0.004, n))
    vol = rng.integers(1_000_000, 5_000_000, n).astype(float)
    return open_, high, low, close, vol


# -- correctness vs pandas (the "two sources" cross-check, §8.1) -----------------
def test_sma_exact():
    _, _, _, close, _ = _series()
    assert abs(ind.sma(close, 50)[-1] - close[-50:].mean()) < 1e-9


def test_ema_matches_pandas():
    _, _, _, close, _ = _series()
    ref = pd.Series(close).ewm(span=20, adjust=False).mean().iloc[-1]
    assert abs(ind.ema(close, 20)[-1] - ref) / ref < 1e-6


def test_rsi_matches_wilder_reference():
    _, _, _, close, _ = _series()
    s = pd.Series(close)
    delta = s.diff()
    ag = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    al = (-delta.clip(upper=0)).ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    ref = (100 - 100 / (1 + ag / al)).iloc[-1]
    assert abs(ind.rsi(close, 14)[-1] - ref) < 0.01


def test_macd_matches_pandas():
    _, _, _, close, _ = _series()
    s = pd.Series(close)
    ref = (s.ewm(span=12, adjust=False).mean() - s.ewm(span=26, adjust=False).mean()).iloc[-1]
    assert abs(ind.macd(close)[0][-1] - ref) < 1e-6


# -- property tests (§8.1) ------------------------------------------------------
def test_rsi_bounded():
    _, _, _, close, _ = _series(seed=3)
    r = ind.rsi(close, 14)
    r = r[~np.isnan(r)]
    assert r.min() >= 0 and r.max() <= 100


def test_atr_nonnegative():
    _, high, low, close, _ = _series(seed=9)
    a = ind.atr(high, low, close, 14)
    a = a[~np.isnan(a)]
    assert (a >= 0).all()


def test_bollinger_ordering():
    _, _, _, close, _ = _series()
    mid, upper, lower, bw = ind.bollinger(close, 20, 2)
    i = -1
    assert lower[i] < mid[i] < upper[i]
    assert bw[i] > 0


def test_compute_indicators_snapshot():
    o, h, low, c, v = _series()
    df = pl.DataFrame(
        {
            "date": [f"d{i}" for i in range(len(c))],
            "open": o,
            "high": h,
            "low": low,
            "close": c,
            "volume": v,
        }
    )
    snap = ind.compute_indicators(df)
    for k in ("rsi14", "sma50", "atr14", "atr_pct", "bb_bandwidth", "drawdown_pct"):
        assert k in snap
    assert 0 <= snap["rsi14"] <= 100
    # all values are native python types (json/sqlite-safe)
    assert all(isinstance(v, bool | int | float) for v in snap.values())


# -- regime --------------------------------------------------------------------
def test_regime_hysteresis():
    from meridian.signals.regime import _bucket_with_hysteresis

    # coming from Risk-On, a dip to 62 (>65-5) stays Risk-On
    assert _bucket_with_hysteresis(62, "Risk-On") == "Risk-On"
    # a deeper dip to 58 flips to Neutral
    assert _bucket_with_hysteresis(58, "Risk-On") == "Neutral"
    # coming from Risk-Off, 38 (<35+5) stays Risk-Off
    assert _bucket_with_hysteresis(38, "Risk-Off") == "Risk-Off"
    assert _bucket_with_hysteresis(75, "Neutral") == "Risk-On"


# -- alert engine --------------------------------------------------------------
def test_safe_eval():
    from meridian.signals.rules import safe_eval

    assert safe_eval("abs(x) >= 3 and y > 1", {"x": -4, "y": 2}) is True
    assert safe_eval("x > 10", {"x": 5}) is False
    assert safe_eval("__import__('os')", {}) is False  # no builtins → safe


def test_invalidation_alert_fires_and_dedupes(home, db):
    import meridian.notify.router as R
    from meridian.notify.router import Router
    from meridian.signals.rules import evaluate_rules
    from meridian.util import utcnow_iso

    R._router = Router(home, dry_run=True)
    # seed NVDA instrument + quote + a live memo whose invalidation sits above spot
    iid = db.execute(
        "INSERT INTO instruments(ticker,name,kind,tier) VALUES('NVDA','NVDA','equity','holding')"
    )
    db.execute(
        "INSERT INTO quotes_latest(instrument_id,price,prev_close,ts) VALUES(?,100.0,101.0,?)",
        (iid, utcnow_iso()),
    )
    db.execute(
        "INSERT INTO memos(id,ticker,direction,status,invalidation_level,entry_plan,created_at) "
        "VALUES(1,'NVDA','long','live',105.0,'exit',?)",
        (utcnow_iso(),),
    )
    # portfolio.yaml in the test home has no NVDA; write one linking memo 1
    (home.config_dir / "portfolio.yaml").write_text(
        "accounts:\n  - name: b\n    positions:\n      - {ticker: NVDA, qty: 10, memo_id: 1}\n",
        encoding="utf-8",
    )
    first = evaluate_rules(home)
    second = evaluate_rules(home)
    assert first["fired"] >= 1
    assert second["fired"] == 0  # once_per_memo dedupe
    row = db.query_one("SELECT priority, body FROM alerts WHERE rule_id='holding-invalidation'")
    assert row["priority"] == "P0" and "invalidation" in row["body"].lower()


@pytest.mark.asyncio
async def test_signals_api(home, db):
    from httpx import ASGITransport, AsyncClient

    db.set_setting("regime.latest", {"score": 71.2, "bucket": "Risk-On", "components": {"vix": 80}})
    db.set_setting("breadth.latest", {"pct_above_50dma": 59.1})
    from meridian.app import create_app

    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        r = await ac.get("/api/signals")
        assert r.status_code == 200
        assert r.json()["regime"]["bucket"] == "Risk-On"
        assert r.json()["breadth"]["pct_above_50dma"] == 59.1
