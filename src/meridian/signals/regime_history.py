"""Historical regime validation (V2 quant centerpiece).

Recomputes the composite risk regime once per trading day over ~2 years of *keyless*
yfinance history, so the gauge can be inspected retrospectively rather than only "now".

Only the price-based, keyless components are used — the FRED/sentiment components that
need keys are dropped and the remaining weights are renormalised, exactly as the live
engine does (see ``regime.py``). The keyless subset and its proxies:

* ``vix``       — ^VIX 1y percentile + ^VIX/^VIX3M term structure (same formula as live)
* ``breadth``   — % of a benchmark+sector universe above its own 50-DMA that day
* ``credit_rs`` — XLF/SPY and IWM/SPY 21d relative strength (same as live)
* ``dollar``    — UUP 20d trend (keyless proxy for the FRED broad-dollar index)
* ``hy_oas``    — HYG/LQD 20d relative strength (keyless proxy for HY OAS: widening
                  spreads = HY underperforming IG = risk-off)

Everything here is RETROSPECTIVE, in-sample description — never a trading claim. The
forward-return panel quantifies what SPY *did* after each regime bucket historically; it
does not forecast.
"""

from __future__ import annotations

import numpy as np
from loguru import logger

from ..config import Settings, get_settings
from ..connectors.history import backfill_one, read_daily
from ..util import norm_ticker, utcnow_iso

# Keyless universe. Core (SPY, ^VIX) drives the master date axis; the rest are optional
# and simply drop out (weight renormalisation) on days they lack data.
CORE = ["SPY", "^VIX"]
SUPPORT = ["^VIX3M", "QQQ", "IWM", "UUP", "HYG", "LQD", "XLF"]
SECTORS = ["XLK", "XLF", "XLE", "XLV", "XLY", "XLP", "XLI", "XLU", "XLB", "XLRE", "XLC"]
REGIME_TICKERS = list(dict.fromkeys([*CORE, *SUPPORT, *SECTORS]))

# breadth universe (drop indices/futures; use liquid ETFs we backfill anyway)
BREADTH_UNIVERSE = list(dict.fromkeys(["SPY", "QQQ", "IWM", *SECTORS]))

# Keyless subset of the live WEIGHTS (same keys/values where they map).
WEIGHTS = {"vix": 20, "breadth": 15, "credit_rs": 10, "dollar": 10, "hy_oas": 20}


def _clip(x: float) -> float:
    return float(max(0.0, min(100.0, x)))


# -- frame assembly -------------------------------------------------------------
def build_frames(
    tickers: list[str], settings: Settings | None = None
) -> tuple[list[str], dict[str, np.ndarray]]:
    """Align every ticker's close series onto SPY's trading-day axis.

    Missing bars become NaN so per-day subscores can drop them cleanly.
    """
    s = settings or get_settings()
    spy = read_daily("SPY", settings=s)
    if spy.height == 0:
        return [], {}
    dates = spy.get_column("date").to_list()
    idx = {d: k for k, d in enumerate(dates)}
    out: dict[str, np.ndarray] = {}
    for t in tickers:
        t = norm_ticker(t)
        df = read_daily(t, settings=s)
        if df.height == 0:
            continue
        arr = np.full(len(dates), np.nan)
        for d, c in zip(
            df.get_column("date").to_list(), df.get_column("close").to_numpy(), strict=False
        ):
            k = idx.get(d)
            if k is not None:
                arr[k] = c
        out[t] = arr
    return dates, out


def _rolling_sma(arr: np.ndarray, n: int) -> np.ndarray:
    out = np.full(len(arr), np.nan)
    for i in range(len(arr)):
        w = arr[max(0, i - n + 1) : i + 1]
        w = w[~np.isnan(w)]
        if len(w) >= n:
            out[i] = w[-n:].mean()
    return out


# -- per-day subscores ----------------------------------------------------------
def _vix_sub(vix: np.ndarray, vix3m: np.ndarray | None, i: int) -> float | None:
    if i < 60 or np.isnan(vix[i]):
        return None
    window = vix[max(0, i - 251) : i + 1]
    window = window[~np.isnan(window)]
    if len(window) < 60:
        return None
    latest = float(vix[i])
    pct = float((window <= latest).mean() * 100)
    base = 100 - pct
    if vix3m is not None and not np.isnan(vix3m[i]) and vix3m[i] > 0:
        ratio = latest / float(vix3m[i])
        term = _clip(100 - (ratio - 0.85) / 0.30 * 100)
        return _clip(0.6 * base + 0.4 * term)
    return _clip(base)


def _breadth_sub(closes: dict, sma50: dict, universe: list[str], i: int) -> float | None:
    total = above = 0
    for t in universe:
        c, s50 = closes.get(t), sma50.get(t)
        if c is None or s50 is None or i >= len(c):
            continue
        if np.isnan(c[i]) or np.isnan(s50[i]):
            continue
        total += 1
        if c[i] > s50[i]:
            above += 1
    if total < 3:
        return None
    return _clip(above / total * 100)


def _rs(a: np.ndarray, b: np.ndarray, i: int, lb: int = 21) -> float | None:
    if i < lb:
        return None
    for x in (a[i], b[i], a[i - lb], b[i - lb]):
        if np.isnan(x) or x == 0:
            return None
    return (float(a[i] / b[i]) / float(a[i - lb] / b[i - lb]) - 1.0) * 100.0


def _credit_rs_sub(closes: dict, i: int) -> float | None:
    scores = []
    for num, den in (("XLF", "SPY"), ("IWM", "SPY")):
        if num in closes and den in closes:
            v = _rs(closes[num], closes[den], i)
            if v is not None:
                scores.append(v)
    if not scores:
        return None
    return _clip(50 + float(np.mean(scores)) * 10)


def _trend(arr: np.ndarray, i: int, n: int = 20) -> float | None:
    if i < n or np.isnan(arr[i]) or np.isnan(arr[i - n]) or arr[i - n] == 0:
        return None
    return (float(arr[i] / arr[i - n]) - 1.0) * 100.0


def _dollar_sub(closes: dict, i: int) -> float | None:
    if "UUP" not in closes:
        return None
    t = _trend(closes["UUP"], i, 20)
    if t is None:
        return None
    return _clip(50 - t * 8)  # rising dollar → risk-off


def _hy_oas_sub(closes: dict, i: int) -> float | None:
    if "HYG" not in closes or "LQD" not in closes:
        return None
    ratio = _rs(closes["HYG"], closes["LQD"], i, lb=20)
    if ratio is None:
        return None
    return _clip(50 + ratio * 8)  # HY outperforming IG → tightening spreads → risk-on


def _bucket_with_hysteresis(score: float, prev: str) -> str:
    hi, lo, h = 65.0, 35.0, 5.0

    def plain(x):
        return "Risk-On" if x >= hi else ("Risk-Off" if x <= lo else "Neutral")

    if prev == "Risk-On":
        return "Risk-On" if score >= hi - h else plain(score)
    if prev == "Risk-Off":
        return "Risk-Off" if score <= lo + h else plain(score)
    return plain(score)


# -- series computation (pure) --------------------------------------------------
def compute_regime_series(dates: list[str], closes: dict[str, np.ndarray]) -> list[dict]:
    """Compute the daily composite regime over the aligned frames. Pure + deterministic."""
    n = len(dates)
    if n == 0 or "SPY" not in closes:
        return []
    spy = closes["SPY"]
    vix = closes.get("^VIX")
    vix3m = closes.get("^VIX3M")
    sma50 = {t: _rolling_sma(c, 50) for t, c in closes.items()}

    rows: list[dict] = []
    prev_bucket = "Neutral"
    for i in range(n):
        subs = {
            "vix": _vix_sub(vix, vix3m, i) if vix is not None else None,
            "breadth": _breadth_sub(closes, sma50, BREADTH_UNIVERSE, i),
            "credit_rs": _credit_rs_sub(closes, i),
            "dollar": _dollar_sub(closes, i),
            "hy_oas": _hy_oas_sub(closes, i),
        }
        present = {k: v for k, v in subs.items() if v is not None}
        if len(present) < 2:  # need a minimally-supported composite
            continue
        total_w = sum(WEIGHTS[k] for k in present)
        score = sum(present[k] * WEIGHTS[k] for k in present) / total_w
        bucket = _bucket_with_hysteresis(score, prev_bucket)
        prev_bucket = bucket
        fwd5 = float(spy[i + 5] / spy[i] - 1.0) if i + 5 < n and not np.isnan(spy[i]) else None
        fwd20 = float(spy[i + 20] / spy[i] - 1.0) if i + 20 < n and not np.isnan(spy[i]) else None
        rows.append(
            {
                "date": dates[i],
                "score": round(score, 2),
                "bucket": bucket,
                "coverage": round(total_w, 0),
                "components": {k: round(v, 1) for k, v in present.items()},
                "spy_close": round(float(spy[i]), 2) if not np.isnan(spy[i]) else None,
                "fwd_5d": round(fwd5, 5) if fwd5 is not None else None,
                "fwd_20d": round(fwd20, 5) if fwd20 is not None else None,
            }
        )
    return rows


# -- orchestration --------------------------------------------------------------
def ensure_history(years: int, settings: Settings | None = None, download: bool = True) -> dict:
    """Backfill any regime ticker whose Parquet is missing or too short."""
    s = settings or get_settings()
    fetched, skipped, failed = [], [], []
    need = years * 252 + 300  # warmup for 252d VIX percentile + 50-DMA
    for t in REGIME_TICKERS:
        df = read_daily(t, settings=s)
        if df.height >= need:
            skipped.append(t)
            continue
        if not download:
            failed.append(t)
            continue
        r = backfill_one(t, years=years + 1, settings=s)
        (fetched if r.get("ok") else failed).append(t)
    return {"fetched": fetched, "skipped": skipped, "failed": failed}


def backfill_regime(
    years: int = 2, settings: Settings | None = None, download: bool = True
) -> dict:
    """Download keyless history, recompute the daily regime, persist to ``regime_history``."""
    s = settings or get_settings()
    from ..db import get_db

    db = get_db(s)
    db.migrate()
    hist = ensure_history(years, s, download=download)
    dates, closes = build_frames(REGIME_TICKERS, s)
    if not dates:
        return {"ok": False, "error": "no SPY history available", "history": hist, "rows": 0}
    series = compute_regime_series(dates, closes)

    # keep the trailing `years` window (plus a little) — warmup rows are just scaffolding
    from datetime import date, timedelta

    cutoff = (date.fromisoformat(dates[-1]) - timedelta(days=int(years * 372))).isoformat()
    kept = [r for r in series if r["date"] >= cutoff]

    from ..util import to_json

    now = utcnow_iso()
    db.execute("DELETE FROM regime_history")
    db.executemany(
        "INSERT INTO regime_history"
        "(date,score,bucket,coverage,components_json,spy_close,fwd_5d,fwd_20d,created_at) "
        "VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(date) DO UPDATE SET "
        "score=excluded.score,bucket=excluded.bucket,coverage=excluded.coverage,"
        "components_json=excluded.components_json,spy_close=excluded.spy_close,"
        "fwd_5d=excluded.fwd_5d,fwd_20d=excluded.fwd_20d",
        [
            (
                r["date"],
                r["score"],
                r["bucket"],
                r["coverage"],
                to_json(r["components"]),
                r["spy_close"],
                r["fwd_5d"],
                r["fwd_20d"],
                now,
            )
            for r in kept
        ],
    )
    buckets = {
        b: sum(1 for r in kept if r["bucket"] == b) for b in ("Risk-On", "Neutral", "Risk-Off")
    }
    logger.info(
        "backfill-regime: {} rows ({} .. {})",
        len(kept),
        kept[0]["date"] if kept else None,
        kept[-1]["date"] if kept else None,
    )
    return {
        "ok": True,
        "rows": len(kept),
        "from": kept[0]["date"] if kept else None,
        "to": kept[-1]["date"] if kept else None,
        "buckets": buckets,
        "history": hist,
    }


# -- readers (API) --------------------------------------------------------------
def history_rows(settings: Settings | None = None, limit: int | None = None) -> list[dict]:
    from ..db import get_db
    from ..util import from_json

    db = get_db(settings)
    sql = "SELECT date,score,bucket,coverage,components_json,spy_close,fwd_5d,fwd_20d FROM regime_history ORDER BY date"
    rows = db.query(sql)
    out = [
        {
            "date": r["date"],
            "score": r["score"],
            "bucket": r["bucket"],
            "coverage": r["coverage"],
            "components": from_json(r["components_json"], {}),
            "spy_close": r["spy_close"],
            "fwd_5d": r["fwd_5d"],
            "fwd_20d": r["fwd_20d"],
        }
        for r in rows
    ]
    return out[-limit:] if limit else out


def _dist(vals: list[float]) -> dict:
    a = np.array([v for v in vals if v is not None], dtype=float)
    if len(a) == 0:
        return {"n": 0}
    return {
        "n": int(len(a)),
        "mean": round(float(np.mean(a)) * 100, 2),
        "median": round(float(np.median(a)) * 100, 2),
        "p25": round(float(np.percentile(a, 25)) * 100, 2),
        "p75": round(float(np.percentile(a, 75)) * 100, 2),
        "pct_positive": round(float((a > 0).mean()) * 100, 1),
    }


def forward_return_stats(settings: Settings | None = None) -> dict:
    """Forward SPY return distribution conditional on regime bucket (in-sample)."""
    from ..db import get_db

    db = get_db(settings)
    rows = db.query("SELECT bucket, fwd_5d, fwd_20d FROM regime_history")
    order = ["Risk-On", "Neutral", "Risk-Off"]
    by_bucket = {}
    for b in order:
        brs = [r for r in rows if r["bucket"] == b]
        by_bucket[b] = {
            "h5": _dist([r["fwd_5d"] for r in brs]),
            "h20": _dist([r["fwd_20d"] for r in brs]),
        }
    overall = {
        "h5": _dist([r["fwd_5d"] for r in rows]),
        "h20": _dist([r["fwd_20d"] for r in rows]),
    }
    return {
        "by_bucket": by_bucket,
        "overall": overall,
        "n_days": len(rows),
        "caveat": "In-sample description of realised SPY forward returns by regime bucket "
        "over the backfilled window. NOT a forecast or trading signal.",
    }
