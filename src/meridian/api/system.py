"""System & health endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Response

from .. import __version__
from ..config import get_settings
from ..db import get_db, vec_available
from ..ops.health import health_snapshot
from ..util import to_json, utcnow_iso

router = APIRouter()


@router.get("/health")
def health() -> Response:
    snap = health_snapshot()
    code = 200 if snap["overall"] != "red" else 503
    return Response(content=to_json(snap), media_type="application/json", status_code=code)


@router.get("/system/info")
def info() -> dict:
    s = get_settings()
    secrets = s.secrets
    # report which keys are present WITHOUT ever echoing their values
    keys = {
        name: secrets.has(name)
        for name in (
            "anthropic_api_key",
            "fred_api_key",
            "alpaca_key_id",
            "finnhub_key",
            "coingecko_key",
            "pushover_token",
            "ntfy_token",
        )
    }
    return {
        "version": __version__,
        "timezone": s.config.timezone,
        "home": str(s.home),
        "base_url": s.base_url(),
        "vec_available": vec_available(),
        "keys_present": keys,
        "ts": utcnow_iso(),
    }


@router.get("/system/freshness")
def freshness() -> dict:
    """Snapshot vs live freshness for the dashboard banner (V2)."""
    from ..ops.refresh import refresh_status

    return refresh_status()


@router.get("/system/costs")
def costs() -> dict:
    from ..ops.costs import cost_summary

    return cost_summary()


@router.get("/system/agent-runs")
def agent_runs(limit: int = 50) -> dict:
    db = get_db()
    rows = db.query(
        "SELECT id,agent,model,started_at,ms,input_tokens,output_tokens,cost_usd,status,"
        "task_ref,error FROM agent_runs ORDER BY started_at DESC LIMIT ?",
        (min(limit, 500),),
    )
    return {"runs": [dict(r) for r in rows]}


@router.get("/system/connectors")
def connectors() -> dict:
    db = get_db()
    rows = db.query("SELECT * FROM connector_health ORDER BY connector")
    return {"connectors": [dict(r) for r in rows]}


@router.get("/system/notifications")
def notifications(limit: int = 50) -> dict:
    db = get_db()
    rows = db.query(
        "SELECT id,priority,title,status,channel,created_at,sent_at,queued_until "
        "FROM notifications ORDER BY created_at DESC LIMIT ?",
        (min(limit, 200),),
    )
    return {"notifications": [dict(r) for r in rows]}


@router.get("/system/scheduler")
def scheduler() -> dict:
    from ..app import get_app_state

    st = get_app_state()
    if not st or not st.scheduler:
        return {"running": False, "jobs": []}
    jobs = []
    for j in st.scheduler.get_jobs():
        jobs.append(
            {
                "id": j.id,
                "name": j.name,
                "next_run_time": j.next_run_time.isoformat() if j.next_run_time else None,
                "trigger": str(j.trigger),
            }
        )
    jobs.sort(key=lambda x: x["next_run_time"] or "z")
    return {"running": st.scheduler.running, "jobs": jobs}
