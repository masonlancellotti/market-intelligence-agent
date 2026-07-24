"""Notification router — the single choke point.

Responsibilities: dedupe by ``dedupe_key`` (across restarts, via the notifications
table), per-key cooldown/throttle, quiet-hours awareness (P1/P2 queued to the end of
quiet hours; the override priority — P0 — always punches through), channel fan-out,
and delivery logging.

Every push deep-links to the exact dashboard object. Callers construct a
:class:`Notification` and hand it to :meth:`Router.send`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from typing import Literal

from loguru import logger

from ..config import Settings, get_settings
from ..util import parse_iso, utcnow, utcnow_iso
from .channels import channels_for

Priority = Literal["P0", "P1", "P2"]


@dataclass
class Notification:
    priority: Priority
    title: str
    body: str
    dedupe_key: str = ""
    click_path: str = ""  # relative path; router prepends the tailnet base url
    tags: str = ""
    cooldown_s: int = 3600
    force: bool = False  # bypass dedupe + quiet hours (used by tests / manual)
    meta: dict = field(default_factory=dict)


class Router:
    def __init__(self, settings: Settings | None = None, dry_run: bool = False):
        self.settings = settings or get_settings()
        # Dry-run when explicitly asked, OR when no channel is configured anywhere.
        self.dry_run = dry_run

    # -- public API --------------------------------------------------------
    def send(self, n: Notification) -> dict:
        from ..db import get_db

        db = get_db(self.settings)
        now = utcnow()
        click_url = self._click_url(n.click_path)

        # 1) dedupe / cooldown
        if not n.force and n.dedupe_key and self._recently_sent(db, n.dedupe_key, n.cooldown_s):
            return self._log(db, n, "deduped", click_url, sent=False)

        # 2) quiet hours (P0 / override always punches through)
        if not n.force and self._in_quiet_hours(now) and n.priority != self._override():
            queued_until = self._quiet_end_iso(now)
            return self._log(db, n, "queued", click_url, sent=False, queued_until=queued_until)

        # 3) fan out
        return self._deliver(db, n, click_url)

    def flush_queued(self) -> int:
        """Send notifications whose quiet-hours queue window has elapsed. Scheduler job."""
        from ..db import get_db

        db = get_db(self.settings)
        now_iso = utcnow_iso()
        rows = db.query(
            "SELECT * FROM notifications WHERE status='queued' AND queued_until<=? "
            "ORDER BY created_at",
            (now_iso,),
        )
        sent = 0
        for r in rows:
            n = Notification(
                priority=r["priority"],
                title=r["title"],
                body=r["body"],
                dedupe_key=r["dedupe_key"] or "",
                tags=r["tags"] or "",
                force=True,
            )
            click_url = r["click_url"] or ""
            db.execute("DELETE FROM notifications WHERE id=?", (r["id"],))
            self._deliver(db, n, click_url)
            sent += 1
        if sent:
            logger.info("flushed {} queued notifications", sent)
        return sent

    # -- internals ---------------------------------------------------------
    def _deliver(self, db, n: Notification, click_url: str) -> dict:  # noqa: ANN001
        channels = channels_for(n.priority, self.settings.secrets)
        if self.dry_run or not channels:
            return self._log(db, n, "dry_run", click_url, sent=False)
        attempted, ok_any, errors = [], False, []
        for ch in channels:
            ok, detail = ch.send(
                self.settings.secrets,
                title=n.title,
                body=n.body,
                priority=n.priority,
                click_url=click_url,
                tags=n.tags,
            )
            attempted.append(ch.name)
            ok_any = ok_any or ok
            if not ok:
                errors.append(detail)
            # P0 stops at the first successful critical channel is NOT desired —
            # we want redundancy on P0, so fan out to all. For P1/P2 there's one channel.
        status = "sent" if ok_any else "failed"
        return self._log(
            db,
            n,
            status,
            click_url,
            sent=ok_any,
            channel=",".join(attempted),
            error="; ".join(errors) or None,
        )

    def _log(
        self,
        db,  # noqa: ANN001
        n: Notification,
        status: str,
        click_url: str,
        *,
        sent: bool,
        channel: str = "",
        error: str | None = None,
        queued_until: str | None = None,
    ) -> dict:
        now = utcnow_iso()
        db.execute(
            "INSERT INTO notifications"
            "(priority,title,body,dedupe_key,click_url,tags,channel,status,error,"
            " created_at,queued_until,sent_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                n.priority,
                n.title,
                n.body,
                n.dedupe_key,
                click_url,
                n.tags,
                channel,
                status,
                error,
                now,
                queued_until,
                now if sent else None,
            ),
        )
        level = "warning" if status in ("failed",) else "info"
        logger.log(
            level.upper(),
            "notify [{}] {} → {} ({})",
            n.priority,
            n.title,
            status,
            channel or "-",
        )
        return {"status": status, "channel": channel, "error": error, "queued_until": queued_until}

    def _recently_sent(self, db, dedupe_key: str, cooldown_s: int) -> bool:  # noqa: ANN001
        if cooldown_s <= 0:
            return False
        row = db.query_one(
            "SELECT sent_at FROM notifications WHERE dedupe_key=? AND status='sent' "
            "ORDER BY sent_at DESC LIMIT 1",
            (dedupe_key,),
        )
        if not row or not row["sent_at"]:
            return False
        last = parse_iso(row["sent_at"])
        return bool(last and (utcnow() - last).total_seconds() < cooldown_s)

    def _in_quiet_hours(self, now: datetime) -> bool:
        qh = self.settings.config.notifications.quiet_hours
        local = now.astimezone(self.settings.tz).time()
        start = _parse_hhmm(qh.start)
        end = _parse_hhmm(qh.end)
        if start <= end:
            return start <= local < end
        return local >= start or local < end  # window crosses midnight

    def _quiet_end_iso(self, now: datetime) -> str:
        qh = self.settings.config.notifications.quiet_hours
        end = _parse_hhmm(qh.end)
        local = now.astimezone(self.settings.tz)
        target = local.replace(hour=end.hour, minute=end.minute, second=0, microsecond=0)
        if target <= local:
            target += timedelta(days=1)
        return target.astimezone(utcnow().tzinfo).isoformat().replace("+00:00", "Z")

    def _override(self) -> str:
        return self.settings.config.notifications.quiet_hours.override_priority

    def _click_url(self, path: str) -> str:
        if not path:
            return self.settings.base_url()
        base = self.settings.base_url().rstrip("/")
        return base + ("/" + path.lstrip("/"))


def _parse_hhmm(s: str) -> time:
    try:
        h, m = s.split(":")
        return time(int(h), int(m))
    except (ValueError, AttributeError):
        return time(0, 0)


_router: Router | None = None


def get_router(settings: Settings | None = None) -> Router:
    global _router
    if _router is None:
        _router = Router(settings)
    return _router
