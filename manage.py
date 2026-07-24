#!/usr/bin/env python
"""MERIDIAN management CLI — cross-platform entry point.

    python manage.py migrate          # apply DB migrations
    python manage.py seed             # seed instruments from watchlist
    python manage.py health           # print health snapshot
    python manage.py backfill [TICKERS...]   # 5y daily history -> Parquet (Phase 1)
    python manage.py refresh-quotes   # pull latest quotes now (Phase 1)
    python manage.py ingest NAME      # run one connector now (Phase 1/2)
    python manage.py signals          # recompute indicators/breadth/regime (Phase 3)
    python manage.py brief-now KIND   # generate a brief now (Phase 4)
    python manage.py notify "msg" -p P1
    python manage.py resolve-predictions   # auto-resolve due predictions (Phase 6)

On the Mac Mini the Makefile wraps these behind `make` + `uv run`.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))


def _print(obj):
    import json

    print(json.dumps(obj, indent=2, default=str))


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if not argv:
        print(__doc__)
        return 0
    cmd, rest = argv[0], argv[1:]

    from meridian.config import get_settings
    from meridian.db import get_db

    s = get_settings()
    s.ensure_dirs()

    if cmd == "migrate":
        _print({"applied": get_db(s).migrate()})
        return 0

    if cmd == "seed":
        get_db(s).migrate()
        from meridian.ops.bootstrap import seed_instruments

        _print({"seeded": seed_instruments(s)})
        return 0

    if cmd == "health":
        get_db(s).migrate()
        from meridian.ops.health import health_snapshot

        _print(health_snapshot(s))
        return 0

    if cmd == "notify":
        from meridian.notify.cli import main as notify_main

        return notify_main(rest)

    if cmd == "backfill":
        get_db(s).migrate()
        from meridian.connectors.history import backfill_all

        _print(backfill_all(rest or None))
        return 0

    if cmd == "refresh-quotes":
        get_db(s).migrate()
        from meridian.connectors import refresh_quotes_now

        _print(refresh_quotes_now())
        return 0

    if cmd == "ingest":
        get_db(s).migrate()
        from meridian.connectors import run_connector

        if not rest:
            print("usage: manage.py ingest <connector-name>")
            return 2
        _print(run_connector(rest[0]))
        return 0

    if cmd == "signals":
        get_db(s).migrate()
        from meridian.signals import recompute_all

        _print(recompute_all())
        return 0

    if cmd == "brief-now":
        get_db(s).migrate()
        from meridian.briefs import generate_brief

        kind = rest[0] if rest else "morning"
        res = generate_brief(kind)
        _print({"brief_id": res.get("id"), "kind": kind, "cost_usd": res.get("cost_usd")})
        return 0

    if cmd == "resolve-predictions":
        get_db(s).migrate()
        from meridian.conviction.predictions import resolve_due

        _print(resolve_due())
        return 0

    if cmd == "backup":
        from meridian.ops.backup import run_backup

        _print(run_backup(s))
        return 0

    if cmd == "restore-drill":
        from meridian.ops.backup import restore_drill

        res = restore_drill(s)
        _print(res)
        return 0 if res.get("ok") else 1

    print(f"unknown command: {cmd}\n{__doc__}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
