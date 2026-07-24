"""Scheduled-job registry.

Each subsystem contributes jobs via a provider function. Providers are imported
lazily and guarded, so a subsystem that isn't wired yet (or fails to import) never
takes down the daemon — it just contributes no jobs. Every job body is wrapped in
:func:`guard` so an exception is logged (and raised to P2) but never kills the loop.
"""

from __future__ import annotations

import functools
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from loguru import logger

from ..config import Settings


@dataclass
class JobSpec:
    id: str
    name: str
    func: Callable[[], Any]
    trigger: str  # 'interval' | 'cron'
    kwargs: dict[str, Any] = field(default_factory=dict)


def guard(name: str) -> Callable:
    """Wrap a job so exceptions are logged + raised to a throttled P2, never fatal."""

    def deco(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(*a, **k):
            try:
                return fn(*a, **k)
            except Exception as e:  # noqa: BLE001
                logger.exception("job {} failed: {}", name, e)
                _report_job_error(name, e)

        return wrapper

    return deco


def _report_job_error(job: str, err: Exception) -> None:
    """Throttled P2 on job failure (1/hr/job) — self-healing visibility."""
    try:
        from ..notify import Notification, get_router

        get_router().send(
            Notification(
                priority="P2",
                title=f"Job error: {job}",
                body=str(err)[:300],
                dedupe_key=f"joberr:{job}",
                cooldown_s=3600,
                click_path="/system",
            )
        )
    except Exception:  # noqa: BLE001
        pass


# -- core jobs (always present) -------------------------------------------------
def _core_jobs(s: Settings) -> list[JobSpec]:
    from ..api.events import publish
    from ..notify import get_router
    from .health import health_snapshot, record_heartbeat

    @guard("heartbeat")
    def heartbeat():
        record_heartbeat(s)
        snap = health_snapshot(s)
        publish("health", {"overall": snap["overall"], "ts": snap["ts"]})

    @guard("flush_notifications")
    def flush_notifications():
        get_router(s).flush_queued()

    return [
        JobSpec("heartbeat", "Scheduler heartbeat", heartbeat, "interval", {"seconds": 60}),
        JobSpec(
            "flush_notifications",
            "Flush queued notifications",
            flush_notifications,
            "interval",
            {"minutes": 5},
        ),
    ]


# Providers contributed by later phases. Each is (module, attr).
_PROVIDERS: list[tuple[str, str]] = [
    ("meridian.connectors.jobs", "scheduled_jobs"),
    ("meridian.signals.jobs", "scheduled_jobs"),
    ("meridian.agents.jobs", "scheduled_jobs"),
    ("meridian.briefs.jobs", "scheduled_jobs"),
    ("meridian.conviction.jobs", "scheduled_jobs"),
    ("meridian.ops.maintenance", "scheduled_jobs"),
]


def all_jobs(s: Settings) -> list[JobSpec]:
    jobs = list(_core_jobs(s))
    for mod_name, attr in _PROVIDERS:
        try:
            mod = __import__(mod_name, fromlist=[attr])
            provider = getattr(mod, attr, None)
            if provider:
                jobs.extend(provider(s))
        except Exception as e:  # noqa: BLE001
            logger.debug("job provider {} not available: {}", mod_name, e)
    # de-dupe by id (last wins)
    seen: dict[str, JobSpec] = {}
    for j in jobs:
        seen[j.id] = j
    return list(seen.values())
