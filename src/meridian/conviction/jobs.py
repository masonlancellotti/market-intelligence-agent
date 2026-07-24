"""Conviction Desk schedule. Prediction resolution daily, portfolio-change
watch every 15 min, Sunday Red Team on Live memos, monthly calibration review.
"""

from __future__ import annotations

from ..config import Settings
from ..ops.jobs import JobSpec, guard


def scheduled_jobs(settings: Settings) -> list[JobSpec]:
    from .portfolio_watch import check_portfolio_change
    from .predictions import resolve_due

    @guard("resolve_predictions")
    def resolve():
        resolve_due(settings)

    @guard("portfolio_watch")
    def portwatch():
        check_portfolio_change(settings)

    @guard("sunday_redteam")
    def sunday_redteam():
        from ..db import get_db
        from .redteam import run_redteam

        db = get_db(settings)
        for r in db.query("SELECT id FROM memos WHERE status='live'"):
            run_redteam(r["id"], settings)

    return [
        JobSpec(
            "resolve_predictions",
            "Resolve due predictions",
            resolve,
            "cron",
            {"hour": 16, "minute": 45},
        ),
        JobSpec(
            "portfolio_watch", "Portfolio change watch", portwatch, "interval", {"minutes": 15}
        ),
        JobSpec(
            "sunday_redteam",
            "Sunday Red Team",
            sunday_redteam,
            "cron",
            {"day_of_week": "sun", "hour": 16, "minute": 30},
        ),
    ]
