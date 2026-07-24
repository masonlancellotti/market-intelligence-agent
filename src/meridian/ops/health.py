"""Health snapshot — drives the watchdog and the /system wall.

Reports: scheduler heartbeat freshness, per-connector freshness/circuit state, DB
writability, disk %, and last-brief timestamps. ``overall`` is green/amber/red.
"""

from __future__ import annotations

import shutil
from typing import Any

from ..config import Settings, get_settings
from ..util import parse_iso, utcnow, utcnow_iso

HEARTBEAT_KEY = "scheduler.heartbeat"
HEARTBEAT_STALE_S = 180  # scheduler pings every 60s; >3 missed = unhealthy


def record_heartbeat(settings: Settings | None = None) -> None:
    from ..db import get_db

    s = settings or get_settings()
    get_db(s).set_setting(HEARTBEAT_KEY, utcnow_iso())


def _db_writable(db) -> bool:  # noqa: ANN001
    try:
        db.set_setting("health.probe", utcnow_iso())
        return True
    except Exception:  # noqa: BLE001
        return False


def health_snapshot(settings: Settings | None = None) -> dict[str, Any]:
    from ..db import get_db

    s = settings or get_settings()
    db = get_db(s)
    now = utcnow()

    # scheduler heartbeat
    hb = db.get_setting(HEARTBEAT_KEY)
    hb_dt = parse_iso(hb) if hb else None
    hb_age = (now - hb_dt).total_seconds() if hb_dt else None
    scheduler_ok = hb_age is not None and hb_age < HEARTBEAT_STALE_S

    # connectors
    connectors = []
    conn_red = conn_amber = 0
    for r in db.query("SELECT * FROM connector_health ORDER BY connector"):
        status = r["status"] or "unknown"
        connectors.append(
            {
                "connector": r["connector"],
                "status": status,
                "last_success": r["last_success"],
                "last_error": r["last_error"],
                "error_streak": r["error_streak"],
                "circuit_open_until": r["circuit_open_until"],
                "items_24h": r["items_24h"],
                "enabled": bool(r["enabled"]),
            }
        )
        if status == "red":
            conn_red += 1
        elif status == "amber":
            conn_amber += 1

    # disk
    disk_pct = None
    try:
        usage = shutil.disk_usage(s.data_dir)
        disk_pct = round(usage.used / usage.total * 100, 1)
    except Exception:  # noqa: BLE001
        pass

    # last briefs
    last_briefs = {}
    for r in db.query("SELECT kind, MAX(created_at) AS last FROM briefs GROUP BY kind"):
        last_briefs[r["kind"]] = r["last"]

    db_ok = _db_writable(db)

    # overall
    overall = "green"
    if not scheduler_ok or not db_ok or conn_red > 0 or (disk_pct and disk_pct > 95):
        overall = "red"
    elif conn_amber > 0 or (disk_pct and disk_pct > 88):
        overall = "amber"

    return {
        "overall": overall,
        "ts": utcnow_iso(),
        "scheduler": {"ok": scheduler_ok, "last_heartbeat": hb, "age_s": hb_age},
        "db_writable": db_ok,
        "disk_pct": disk_pct,
        "connectors": connectors,
        "connector_summary": {"red": conn_red, "amber": conn_amber, "total": len(connectors)},
        "last_briefs": last_briefs,
    }
