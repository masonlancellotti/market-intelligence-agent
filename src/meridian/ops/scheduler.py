"""APScheduler wiring.

Jobs run on a ThreadPoolExecutor so blocking work (sqlite, sync httpx, async
connectors invoked via ``asyncio.run``) never stalls the uvicorn event loop. All
cron triggers use the configured trading timezone (``America/New_York``), DST-correct
via zoneinfo. Scheduling is calendar-aware through :func:`is_trading_day`.
"""

from __future__ import annotations

from apscheduler.executors.pool import ThreadPoolExecutor
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from loguru import logger

from ..config import Settings, get_settings
from ..util import utcnow


def build_scheduler(settings: Settings | None = None) -> AsyncIOScheduler:
    s = settings or get_settings()
    scheduler = AsyncIOScheduler(
        timezone=s.config.timezone,
        executors={"default": ThreadPoolExecutor(max_workers=8)},
        job_defaults={
            "coalesce": True,  # collapse missed runs into one
            "max_instances": 1,  # never overlap a job with itself
            "misfire_grace_time": 300,
        },
    )
    return scheduler


def register_jobs(scheduler: AsyncIOScheduler, settings: Settings | None = None) -> int:
    """Attach every job spec from the registry. Returns count added."""
    from .jobs import all_jobs

    s = settings or get_settings()
    count = 0
    for spec in all_jobs(s):
        scheduler.add_job(
            spec.func,
            trigger=spec.trigger,
            id=spec.id,
            name=spec.name,
            replace_existing=True,
            **spec.kwargs,
        )
        count += 1
    logger.info("registered {} scheduled jobs", count)
    return count


# -- trading calendar awareness -------------------------------------------------
_calendar = None


def _cal():
    global _calendar
    if _calendar is None:
        import pandas_market_calendars as mcal

        _calendar = mcal.get_calendar("XNYS")
    return _calendar


def is_trading_day(settings: Settings | None = None) -> bool:
    """True if today (ET) is an XNYS session (holidays + half-days handled)."""
    s = settings or get_settings()
    today = utcnow().astimezone(s.tz).date()
    try:
        sched = _cal().schedule(start_date=today.isoformat(), end_date=today.isoformat())
        return len(sched) > 0
    except Exception:  # noqa: BLE001
        return today.weekday() < 5  # fallback: Mon–Fri


def market_session(settings: Settings | None = None) -> dict:
    """Return {'open': dt, 'close': dt} in ET for today, or None if closed."""
    s = settings or get_settings()
    today = utcnow().astimezone(s.tz).date()
    try:
        sched = _cal().schedule(start_date=today.isoformat(), end_date=today.isoformat())
        if len(sched) == 0:
            return {"is_open_today": False}
        row = sched.iloc[0]
        return {
            "is_open_today": True,
            "open": row["market_open"].tz_convert(s.config.timezone).isoformat(),
            "close": row["market_close"].tz_convert(s.config.timezone).isoformat(),
        }
    except Exception:  # noqa: BLE001
        return {"is_open_today": today.weekday() < 5}
