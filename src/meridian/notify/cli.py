"""Standalone notifier CLI.

Works even when the daemon is down — the watchdog uses this to fire a P0 when the
API stops responding. Usage:

    python -m meridian.notify "daemon down" -p P0 --title "Meridian watchdog"
    python -m meridian.notify "morning brief ready" -p P1 --path /briefs/42
"""

from __future__ import annotations

import argparse
import sys

from .router import Notification, Router


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="meridian-notify", description="Send a Meridian push.")
    ap.add_argument("body", help="notification body")
    ap.add_argument("-p", "--priority", default="P1", choices=["P0", "P1", "P2"])
    ap.add_argument("--title", default="Meridian")
    ap.add_argument("--path", default="", help="dashboard deep-link path, e.g. /briefs/42")
    ap.add_argument("--tags", default="")
    ap.add_argument("--dedupe", default="", help="dedupe key")
    ap.add_argument("--force", action="store_true", help="bypass dedupe + quiet hours")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    # The DB must exist for logging; migrate defensively so the CLI never crashes the watchdog.
    try:
        from ..config import get_settings
        from ..db import get_db

        s = get_settings()
        s.ensure_dirs()
        get_db(s).migrate()
    except Exception as e:  # noqa: BLE001
        print(f"warn: db unavailable ({e}); sending without logging", file=sys.stderr)

    router = Router(dry_run=args.dry_run)
    result = router.send(
        Notification(
            priority=args.priority,
            title=args.title,
            body=args.body,
            dedupe_key=args.dedupe,
            click_path=args.path,
            tags=args.tags,
            force=args.force,
        )
    )
    print(result)
    return 0 if result.get("status") in ("sent", "dry_run", "queued", "deduped") else 1


if __name__ == "__main__":
    raise SystemExit(main())
