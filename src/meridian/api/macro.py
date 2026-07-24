"""Macro endpoints."""

from __future__ import annotations

from fastapi import APIRouter

from ..db import get_db
from ..util import utcnow_iso

router = APIRouter()

_KEY_SERIES = [
    "DGS2",
    "DGS10",
    "DGS30",
    "T10Y2Y",
    "T10Y3M",
    "FEDFUNDS",
    "CPIAUCSL",
    "CPILFESL",
    "UNRATE",
    "PAYEMS",
    "BAMLH0A0HYM2",
    "NFCI",
    "DTWEXBGS",
    "VIXCLS",
    "M2SL",
    "UMCSENT",
]


def _latest(db, sid: str):
    row = db.query_one(
        "SELECT value, date FROM macro_points WHERE series_id=? ORDER BY date DESC LIMIT 1", (sid,)
    )
    prev = db.query_one(
        "SELECT value FROM macro_points WHERE series_id=? ORDER BY date DESC LIMIT 1 OFFSET 1",
        (sid,),
    )
    if not row:
        return None
    return {
        "series_id": sid,
        "value": row["value"],
        "date": row["date"],
        "prev": prev["value"] if prev else None,
    }


@router.get("/macro")
def macro() -> dict:
    db = get_db()
    series = {sid: _latest(db, sid) for sid in _KEY_SERIES}
    fed = db.query(
        "SELECT venue,question,yes_prob,prev_prob,volume FROM prediction_markets "
        "WHERE category='fed' ORDER BY volume DESC LIMIT 8"
    )
    upcoming = db.query(
        "SELECT name,country,scheduled_at,importance,consensus,previous FROM econ_events "
        "WHERE scheduled_at>=? ORDER BY scheduled_at LIMIT 12",
        (utcnow_iso(),),
    )
    return {
        "series": {k: v for k, v in series.items() if v},
        "fed_odds": [dict(r) for r in fed],
        "cnn_fng": db.get_setting("sentiment.cnn_fng"),
        "crypto_fng": db.get_setting("crypto.fng"),
        "crypto_global": db.get_setting("crypto.global"),
        "upcoming_events": [dict(r) for r in upcoming],
    }


@router.get("/macro/series/{series_id}")
def series(series_id: str, limit: int = 260) -> dict:
    db = get_db()
    meta = db.query_one("SELECT * FROM macro_series WHERE series_id=?", (series_id,))
    pts = db.query(
        "SELECT date, value FROM macro_points WHERE series_id=? ORDER BY date DESC LIMIT ?",
        (series_id, min(limit, 2000)),
    )
    return {
        "series_id": series_id,
        "meta": dict(meta) if meta else None,
        "points": [dict(r) for r in reversed(pts)],
    }


@router.get("/macro/prediction-markets")
def prediction_markets(category: str | None = None, limit: int = 40) -> dict:
    db = get_db()
    if category:
        rows = db.query(
            "SELECT * FROM prediction_markets WHERE category=? ORDER BY volume DESC LIMIT ?",
            (category, limit),
        )
    else:
        rows = db.query("SELECT * FROM prediction_markets ORDER BY volume DESC LIMIT ?", (limit,))
    return {"markets": [dict(r) for r in rows]}
