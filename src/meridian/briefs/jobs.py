"""Brief schedule. Morning 07:45, Midday 12:30 (conditional),
Closing 16:20, all ET on trading days. Sunday/crypto-weekend live in Phase 7.
"""

from __future__ import annotations

from loguru import logger

from ..config import Settings
from ..ops.jobs import JobSpec, guard


def scheduled_jobs(settings: Settings) -> list[JobSpec]:
    from ..ops.scheduler import is_trading_day
    from .assembly import generate_brief

    @guard("brief_morning")
    def morning():
        if is_trading_day(settings):
            res = generate_brief("morning", settings)
            # audio + designed card are best-effort (Mac); degrade cleanly elsewhere
            from .audio import generate_audio

            generate_audio(res["id"], settings)

    @guard("brief_midday")
    def midday():
        if is_trading_day(settings) and _midday_warranted(settings):
            generate_brief("midday", settings)

    @guard("brief_closing")
    def closing():
        if is_trading_day(settings):
            generate_brief("closing", settings)

    @guard("event_flash_watch")
    def event_flash():
        from .events import check_macro_releases

        check_macro_releases(settings)

    @guard("brief_sunday")
    def sunday():
        generate_brief("sunday", settings)

    @guard("brief_crypto_weekend")
    def crypto_weekend():
        generate_brief("crypto", settings)

    @guard("calibration_review")
    def calibration():
        # monthly: only on the first Sunday
        from ..util import utcnow

        if utcnow().astimezone(settings.tz).day <= 7:
            from ..conviction.calibration import run_calibration_review

            run_calibration_review(settings)

    return [
        JobSpec("brief_morning", "Morning Brief", morning, "cron", {"hour": 7, "minute": 45}),
        JobSpec("brief_midday", "Midday Pulse", midday, "cron", {"hour": 12, "minute": 30}),
        JobSpec("brief_closing", "Closing Wrap", closing, "cron", {"hour": 16, "minute": 20}),
        JobSpec(
            "event_flash_watch", "Macro release watcher", event_flash, "interval", {"minutes": 3}
        ),
        JobSpec(
            "brief_sunday",
            "Sunday Setup",
            sunday,
            "cron",
            {"day_of_week": "sun", "hour": 17, "minute": 0},
        ),
        JobSpec(
            "brief_crypto_weekend",
            "Crypto Weekend Pulse",
            crypto_weekend,
            "cron",
            {"day_of_week": "sat", "hour": 10, "minute": 0},
        ),
        JobSpec(
            "calibration_review",
            "Monthly Calibration Review",
            calibration,
            "cron",
            {"day_of_week": "sun", "hour": 18, "minute": 0},
        ),
    ]


def _midday_warranted(settings: Settings) -> bool:
    """Midday sends only if a materiality≥3 event occurred today."""
    from ..db import get_db

    db = get_db(settings)
    row = db.query_one(
        "SELECT COUNT(*) n FROM news_items WHERE materiality>=3 "
        "AND published_at>=datetime('now','-6 hours')"
    )
    warranted = bool(row and row["n"] >= 3)
    if not warranted:
        logger.info("midday pulse suppressed — quiet tape (feature)")
    return warranted
