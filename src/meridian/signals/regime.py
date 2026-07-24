"""Regime model — risk-on/off composite 0–100.

A weighted blend of sub-scores (each 0=max risk-off … 100=max risk-on). Components that
lack data (e.g. FRED series without a key) are dropped and the remaining weights are
renormalised, so the gauge always produces a value from whatever is available. Buckets:
Risk-On ≥65, Neutral 35–65, Risk-Off ≤35, with ±5 hysteresis to prevent flapping.
Transitions are P1 alerts and reweight brief emphasis.
"""

from __future__ import annotations

import numpy as np

from ..config import Settings, get_settings
from ..connectors.history import read_daily
from ..util import utcnow_iso

# component -> weight (sums to 100)
WEIGHTS = {
    "vix": 20,
    "hy_oas": 20,
    "curve": 10,
    "dollar": 10,
    "breadth": 15,
    "credit_rs": 10,
    "fear_greed": 10,
    "nfci": 5,
}


def _macro_series(db, sid: str, n: int = 30) -> np.ndarray | None:
    rows = db.query(
        "SELECT value FROM macro_points WHERE series_id=? ORDER BY date DESC LIMIT ?", (sid, n)
    )
    if not rows:
        return None
    return np.array([r["value"] for r in rows][::-1], dtype=float)


def _clip(x: float) -> float:
    return float(max(0.0, min(100.0, x)))


def _trend_pct(arr: np.ndarray, n: int = 20) -> float | None:
    if arr is None or len(arr) < 2:
        return None
    m = min(n, len(arr) - 1)
    if arr[-1 - m] == 0:
        return None
    return (arr[-1] / arr[-1 - m] - 1.0) * 100.0


def _vix_subscore(db, s: Settings) -> float | None:
    vix_df = read_daily("^VIX", settings=s)
    latest = None
    if vix_df.height >= 60:
        vals = vix_df.get_column("close").to_numpy()
        latest = vals[-1]
        pct = (vals[-252:] <= latest).mean() * 100 if len(vals) >= 60 else 50
        base = 100 - pct  # low VIX percentile → risk-on
    else:
        q = db.query_one(
            "SELECT price FROM quotes_latest q JOIN instruments i ON i.id=q.instrument_id "
            "WHERE i.ticker='^VIX'"
        )
        if not q or q["price"] is None:
            return None
        latest = q["price"]
        base = _clip(100 - (latest - 10) / 30 * 100)  # ~10 → risk-on, ~40 → risk-off
    # term structure: VIX < VIX3M (contango) risk-on; inversion risk-off
    v3 = db.query_one(
        "SELECT price FROM quotes_latest q JOIN instruments i ON i.id=q.instrument_id "
        "WHERE i.ticker='^VIX3M'"
    )
    if v3 and v3["price"] and latest:
        ratio = latest / v3["price"]
        term = _clip(100 - (ratio - 0.85) / 0.30 * 100)  # ratio<1 contango risk-on
        return _clip(0.6 * base + 0.4 * term)
    return _clip(base)


def _hy_oas_subscore(db) -> float | None:
    arr = _macro_series(db, "BAMLH0A0HYM2", 30)
    t = _trend_pct(arr, 20)
    if t is None:
        return None
    # widening spreads (positive trend) → risk-off
    return _clip(50 - t * 5)


def _curve_subscore(db) -> float | None:
    t10y2y = _macro_series(db, "T10Y2Y", 30)
    if t10y2y is None:
        return None
    level = t10y2y[-1]
    slope = t10y2y[-1] - t10y2y[-min(20, len(t10y2y))]
    # steeper/positive curve → risk-on; deep inversion → risk-off
    return _clip(50 + level * 25 + slope * 20)


def _dollar_subscore(db) -> float | None:
    arr = _macro_series(db, "DTWEXBGS", 30)
    t = _trend_pct(arr, 20)
    if t is None:
        return None
    return _clip(50 - t * 8)  # rising dollar → risk-off


def _breadth_subscore(db) -> float | None:
    b = db.get_setting("breadth.latest")
    if not b or b.get("pct_above_50dma") is None:
        return None
    return _clip(b["pct_above_50dma"])


def _credit_rs_subscore(s: Settings) -> float | None:
    scores = []
    for pair in (("XLF", "SPY"), ("IWM", "SPY")):
        a = read_daily(pair[0], settings=s)
        b = read_daily(pair[1], settings=s)
        if a.height < 25 or b.height < 25:
            continue
        ac = a.get_column("close").to_numpy()
        bc = b.get_column("close").to_numpy()
        m = min(len(ac), len(bc))
        ratio = ac[-m:] / bc[-m:]
        if m >= 21:
            scores.append((ratio[-1] / ratio[-21] - 1.0) * 100.0)
    if not scores:
        return None
    return _clip(50 + np.mean(scores) * 10)


def _fear_greed_subscore(db) -> float | None:
    cnn = db.get_setting("sentiment.cnn_fng")
    crypto = db.get_setting("crypto.fng")
    vals = []
    if cnn and cnn.get("score") is not None:
        vals.append(cnn["score"])
    if crypto and crypto.get("value") is not None:
        vals.append(crypto["value"])
    if not vals:
        return None
    return _clip(float(np.mean(vals)))  # higher greed → risk-on


def _nfci_subscore(db) -> float | None:
    arr = _macro_series(db, "NFCI", 5)
    if arr is None:
        return None
    # NFCI: negative = loose (risk-on), positive = tight (risk-off)
    return _clip(50 - arr[-1] * 40)


def compute_regime(settings: Settings | None = None) -> dict:
    s = settings or get_settings()
    from ..db import get_db

    db = get_db(s)
    subs = {
        "vix": _vix_subscore(db, s),
        "hy_oas": _hy_oas_subscore(db),
        "curve": _curve_subscore(db),
        "dollar": _dollar_subscore(db),
        "breadth": _breadth_subscore(db),
        "credit_rs": _credit_rs_subscore(s),
        "fear_greed": _fear_greed_subscore(db),
        "nfci": _nfci_subscore(db),
    }
    present = {k: v for k, v in subs.items() if v is not None}
    if not present:
        return {"score": None, "bucket": "unknown", "components": {}}
    total_w = sum(WEIGHTS[k] for k in present)
    score = sum(present[k] * WEIGHTS[k] for k in present) / total_w

    prev = db.get_setting("regime.latest", {}) or {}
    prev_bucket = prev.get("bucket", "Neutral")
    bucket = _bucket_with_hysteresis(score, prev_bucket)

    result = {
        "score": round(score, 1),
        "bucket": bucket,
        "prev_bucket": prev_bucket,
        "changed": bucket != prev_bucket and prev_bucket in ("Risk-On", "Neutral", "Risk-Off"),
        "components": {k: round(v, 1) for k, v in present.items()},
        "coverage": round(total_w, 0),
        "at": utcnow_iso(),
    }
    db.set_setting("regime.latest", result)
    _store_history(db, s, score, bucket)
    if result["changed"]:
        _alert_transition(s, result)
    return result


def _bucket_with_hysteresis(score: float, prev: str) -> str:
    hi, lo = 65.0, 35.0
    h = 5.0
    if prev == "Risk-On":
        return "Risk-On" if score >= hi - h else _plain_bucket(score, hi, lo)
    if prev == "Risk-Off":
        return "Risk-Off" if score <= lo + h else _plain_bucket(score, hi, lo)
    return _plain_bucket(score, hi, lo)


def _plain_bucket(score: float, hi: float, lo: float) -> str:
    if score >= hi:
        return "Risk-On"
    if score <= lo:
        return "Risk-Off"
    return "Neutral"


def _store_history(db, s: Settings, score: float, bucket: str) -> None:
    iid = _spy_id(db)
    if iid is None:
        return
    from ..util import today_iso

    db.execute(
        "INSERT INTO signals(instrument_id,kind,value,params_json,bar_date,created_at) "
        "VALUES(?,?,?,?,?,?) ON CONFLICT(instrument_id,kind,bar_date) DO UPDATE SET value=excluded.value",
        (
            iid,
            "regime_score",
            round(score, 2),
            f'{{"bucket":"{bucket}"}}',
            today_iso(s.tz),
            utcnow_iso(),
        ),
    )


def _spy_id(db):
    r = db.query_one("SELECT id FROM instruments WHERE ticker='SPY'")
    return r["id"] if r else None


def _alert_transition(s: Settings, result: dict) -> None:
    from ..notify import Notification, get_router

    get_router(s).send(
        Notification(
            priority="P1",
            title=f"Regime → {result['bucket']}",
            body=f"Risk composite {result['score']}/100 (was {result['prev_bucket']})",
            dedupe_key=f"regime:{result['bucket']}",
            cooldown_s=21600,
            click_path="/signals",
        )
    )


def regime_history(settings: Settings | None = None, days: int = 90) -> list[dict]:
    s = settings or get_settings()
    from ..db import get_db

    db = get_db(s)
    iid = _spy_id(db)
    if iid is None:
        return []
    rows = db.query(
        "SELECT bar_date, value, params_json FROM signals WHERE instrument_id=? AND kind='regime_score' "
        "ORDER BY bar_date DESC LIMIT ?",
        (iid, days),
    )
    from ..util import from_json

    return [
        {
            "date": r["bar_date"],
            "score": r["value"],
            "bucket": from_json(r["params_json"], {}).get("bucket"),
        }
        for r in reversed(rows)
    ]
