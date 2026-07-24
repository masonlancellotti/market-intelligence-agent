"""Housekeeping & retention.

Nightly: recompute connector 24h item counts, prune old notification rows, apply the
news raw_text 180-day retention, and checkpoint the WAL. The OS-level backup itself is
launchd's job (scripts/backup.sh); this keeps the live DB tidy.
"""

from __future__ import annotations

from datetime import timedelta

from loguru import logger

from ..config import Settings
from ..util import iso, utcnow


def run_housekeeping(settings: Settings | None = None) -> dict:
    from ..db import get_db

    db = get_db(settings)
    now = utcnow()
    stats: dict[str, int] = {}

    # news raw_text retention: 180 days -> summary-only
    cutoff_news = iso(now - timedelta(days=180))
    stats["news_raw_trimmed"] = db.execute(
        "UPDATE news_items SET raw_text=NULL WHERE published_at<? AND raw_text IS NOT NULL",
        (cutoff_news,),
    )

    # prune old delivered notifications (>45d) — keep the log lean
    cutoff_notif = iso(now - timedelta(days=45))
    stats["notifications_pruned"] = db.execute(
        "DELETE FROM notifications WHERE created_at<?", (cutoff_notif,)
    )

    # (connector items_24h counts are maintained by each connector on write)

    # WAL checkpoint to keep the -wal file from growing unbounded
    try:
        with db.cursor() as cur:
            cur.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    except Exception:  # noqa: BLE001
        pass

    logger.info("housekeeping: {}", stats)
    return stats


def scheduled_jobs(settings: Settings) -> list:
    from .jobs import JobSpec, guard

    @guard("housekeeping")
    def _hk():
        run_housekeeping(settings)

    @guard("backup")
    def _backup():
        from .backup import run_backup

        run_backup(settings)

    return [
        JobSpec("housekeeping", "Nightly housekeeping", _hk, "cron", {"hour": 3, "minute": 5}),
        # in-process backup (belt-and-suspenders alongside the launchd backup on the Mini)
        JobSpec("backup", "Nightly DB backup", _backup, "cron", {"hour": 2, "minute": 30}),
    ]
