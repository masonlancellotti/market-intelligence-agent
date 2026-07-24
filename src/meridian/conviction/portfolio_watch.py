"""Portfolio-change watcher + journal nag.

Every decision (open/add/trim/close) should get a journal entry at decision time. We
detect edits to portfolio.yaml and, if a position changed without a fresh journal entry,
prompt for one (2 lines minimum).
"""

from __future__ import annotations

import hashlib

from loguru import logger

from ..config import Settings, get_settings, load_portfolio
from ..util import iso, utcnow


def _positions_signature(port: dict) -> str:
    parts = []
    for acct in port.get("accounts", []):
        for pos in acct.get("positions", []):
            parts.append(
                f"{acct.get('name')}:{pos.get('ticker')}:{pos.get('qty')}:{pos.get('cost_basis')}"
            )
    parts.sort()
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]


def check_portfolio_change(settings: Settings | None = None) -> dict:
    s = settings or get_settings()
    from ..db import get_db

    db = get_db(s)
    port = load_portfolio(s)
    sig = _positions_signature(port)
    prev = db.get_setting("portfolio.sig")
    if prev is None:
        db.set_setting("portfolio.sig", sig)
        return {"changed": False, "first_seen": True}
    if sig == prev:
        return {"changed": False}

    # changed — was there a decision journal entry in the last hour?
    since = iso(utcnow().replace(microsecond=0))
    recent = db.query_one(
        "SELECT COUNT(*) n FROM journal_entries WHERE kind='decision' AND ts>=datetime('now','-1 hour')"
    )
    db.set_setting("portfolio.sig", sig)
    if not recent or recent["n"] == 0:
        from ..notify import Notification, get_router

        get_router(s).send(
            Notification(
                priority="P1",
                title="Journal your position change",
                body="portfolio.yaml changed with no decision entry — add 2 lines: why, and the invalidation.",
                dedupe_key=f"journal-nag:{sig}",
                cooldown_s=21600,
                click_path="/journal",
            )
        )
        logger.info("portfolio change detected → journal nag")
    _ = since
    return {"changed": True}
