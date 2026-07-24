"""Event Flash watcher. Within ~10 min of a P0-worthy macro surprise
(high-importance release, |surprise|≥1.5) or a holding 8-K, generate a single-event
deep-ish dive. Surprise is scored from actual vs consensus when both are numeric.
"""

from __future__ import annotations

import re

from loguru import logger

from ..config import Settings, get_settings
from ..util import utcnow_iso


def _num(s) -> float | None:
    if s is None:
        return None
    m = re.search(r"-?\d[\d,]*\.?\d*", str(s).replace(",", ""))
    if not m:
        return None
    val = float(m.group())
    suffix = str(s).strip()[-1:].upper()
    return val * {"K": 1e3, "M": 1e6, "B": 1e9}.get(suffix, 1)


def compute_surprise(actual, consensus) -> float | None:
    a, c = _num(actual), _num(consensus)
    if a is None or c is None:
        return None
    scale = max(abs(c) * 0.1, 0.1)  # crude sigma proxy (docs/DECISIONS.md D-008)
    return round((a - c) / scale, 2)


def score_surprises(settings: Settings | None = None) -> int:
    from ..db import get_db

    db = get_db(settings)
    n = 0
    for r in db.query(
        "SELECT id, actual, consensus FROM econ_events "
        "WHERE actual IS NOT NULL AND actual!='' AND surprise_score IS NULL"
    ):
        sc = compute_surprise(r["actual"], r["consensus"])
        if sc is not None:
            db.execute(
                "UPDATE econ_events SET surprise_score=?, released_at=? WHERE id=?",
                (sc, utcnow_iso(), r["id"]),
            )
            n += 1
    return n


def check_macro_releases(settings: Settings | None = None) -> dict:
    """Fire an Event Flash for freshly-released high-importance surprises."""
    s = settings or get_settings()
    from ..db import get_db
    from .assembly import generate_brief

    db = get_db(s)
    score_surprises(s)
    flashed = set(db.get_setting("events.flashed", []) or [])
    fired = []
    for r in db.query(
        "SELECT id, name, importance, actual, consensus, surprise_score FROM econ_events "
        "WHERE importance='high' AND surprise_score IS NOT NULL "
        "AND ABS(surprise_score)>=1.5 ORDER BY released_at DESC LIMIT 5"
    ):
        if r["id"] in flashed:
            continue
        event = {
            "title": r["name"],
            "summary": f"{r['name']}: actual {r['actual']} vs consensus {r['consensus']} "
            f"(surprise {r['surprise_score']:+.1f}σ).",
            "read": f"A {abs(r['surprise_score']):.1f}σ {'upside' if r['surprise_score'] > 0 else 'downside'} "
            f"surprise — watch the rates/dollar/equity reaction for confirmation vs overreaction.",
        }
        res = generate_brief("event_flash", s, event=event)
        fired.append({"event_id": r["id"], "brief_id": res["id"]})
        flashed.add(r["id"])
        logger.info("event flash fired for {}", r["name"])
    if fired:
        db.set_setting("events.flashed", list(flashed))
    return {"fired": len(fired), "details": fired}
