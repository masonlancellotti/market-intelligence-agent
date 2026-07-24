"""Signals endpoints."""

from __future__ import annotations

from fastapi import APIRouter

from ..db import get_db
from ..util import norm_ticker

router = APIRouter()


@router.get("/signals")
def signals() -> dict:
    db = get_db()
    regime = db.get_setting("regime.latest")
    breadth = db.get_setting("breadth.latest")
    governor = db.get_setting("alerts.noise_governor")
    alerts = db.query(
        "SELECT a.rule_id,a.priority,a.title,a.body,a.fired_at,i.ticker "
        "FROM alerts a LEFT JOIN instruments i ON i.id=a.instrument_id "
        "ORDER BY a.fired_at DESC LIMIT 40"
    )
    return {
        "regime": regime,
        "breadth": breadth,
        "noise_governor": governor,
        "alerts": [dict(r) for r in alerts],
    }


@router.get("/signals/regime/history")
def regime_history(days: int = 90) -> dict:
    from ..signals.regime import regime_history as hist

    return {"history": hist(days=days)}


@router.get("/regime/history")
def regime_backfill_history(limit: int = 600) -> dict:
    """Backfilled ~2y daily composite regime (RETROSPECTIVE). Empty until backfill-regime runs."""
    from ..signals.regime_history import history_rows

    return {"history": history_rows(limit=limit), "retrospective": True}


@router.get("/regime/forward-returns")
def regime_forward_returns() -> dict:
    """In-sample SPY forward-return distribution conditional on regime bucket."""
    from ..signals.regime_history import forward_return_stats

    return forward_return_stats()


@router.get("/signals/alerts")
def alerts(limit: int = 100) -> dict:
    db = get_db()
    rows = db.query(
        "SELECT a.id,a.rule_id,a.priority,a.title,a.body,a.fired_at,a.delivered_at,i.ticker "
        "FROM alerts a LEFT JOIN instruments i ON i.id=a.instrument_id "
        "ORDER BY a.fired_at DESC LIMIT ?",
        (min(limit, 500),),
    )
    return {"alerts": [dict(r) for r in rows]}


@router.get("/signals/{ticker}")
def instrument_signals(ticker: str) -> dict:
    db = get_db()
    t = norm_ticker(ticker)
    inst = db.query_one("SELECT id FROM instruments WHERE ticker=?", (t,))
    if not inst:
        return {"ticker": t, "signals": {}}
    rows = db.query(
        "SELECT kind, value, bar_date FROM signals WHERE instrument_id=? "
        "AND bar_date=(SELECT MAX(bar_date) FROM signals WHERE instrument_id=?)",
        (inst["id"], inst["id"]),
    )
    return {
        "ticker": t,
        "signals": {r["kind"]: r["value"] for r in rows},
        "bar_date": rows[0]["bar_date"] if rows else None,
    }
