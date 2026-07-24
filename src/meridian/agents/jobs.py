"""Agent schedule. Triage runs on the news cadence (q10min)."""

from __future__ import annotations

from ..config import Settings
from ..ops.jobs import JobSpec, guard


def scheduled_jobs(settings: Settings) -> list[JobSpec]:
    from .triage import triage_pending

    @guard("triage")
    def triage():
        triage_pending(limit=200, settings=settings)

    return [
        JobSpec("triage", "News triage", triage, "interval", {"minutes": 10}),
    ]
