"""Conviction memo lifecycle.

Research → Staged → Live → Closed. The Gate is enforced on Staged→Live: below 70/100 the
transition is refused unless a typed ``override_reason`` is supplied, which is journaled.
Staged→Live also triggers the Red Team pass (pinned to the memo).
"""

from __future__ import annotations

from loguru import logger

from ..config import Settings, get_settings
from ..util import from_json, norm_ticker, to_json, utcnow_iso
from .checklist import score_memo

STATUSES = ("research", "staged", "live", "closed")
_JSON_FIELDS = ("catalysts_json", "risks_json", "valuation_json", "checklist_json", "outcome_json")


def create_memo(data: dict, settings: Settings | None = None) -> int:
    s = settings or get_settings()
    from ..db import get_db

    db = get_db(s)
    now = utcnow_iso()
    memo_id = db.execute(
        "INSERT INTO memos(ticker,direction,status,thesis,edge_type,catalysts_json,risks_json,"
        "valuation_json,entry_plan,invalidation_level,invalidation_rule,size_plan,checklist_json,"
        "created_at,updated_at,opened_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            norm_ticker(data.get("ticker", "")),
            data.get("direction", "long"),
            "research",
            data.get("thesis", ""),
            data.get("edge_type"),
            to_json(data.get("catalysts", [])),
            to_json(data.get("risks", [])),
            to_json(data.get("valuation", {})),
            data.get("entry_plan", ""),
            data.get("invalidation_level"),
            data.get("invalidation_rule", ""),
            data.get("size_plan", ""),
            to_json(data.get("checklist", {})),
            now,
            now,
            now,
        ),
    )
    for pred in data.get("predictions", []):
        add_prediction(memo_id, pred, s)
    logger.info("memo #{} created ({} {})", memo_id, data.get("ticker"), data.get("direction"))
    return memo_id


def update_memo(memo_id: int, patch: dict, settings: Settings | None = None) -> dict:
    from ..db import get_db

    db = get_db(settings)
    cols, vals = [], []
    field_map = {
        "thesis": "thesis",
        "edge_type": "edge_type",
        "entry_plan": "entry_plan",
        "invalidation_level": "invalidation_level",
        "invalidation_rule": "invalidation_rule",
        "size_plan": "size_plan",
        "direction": "direction",
        "redteam_verdict": "redteam_verdict",
    }
    for k, col in field_map.items():
        if k in patch:
            cols.append(f"{col}=?")
            vals.append(patch[k])
    for k, col in [
        ("catalysts", "catalysts_json"),
        ("risks", "risks_json"),
        ("valuation", "valuation_json"),
        ("checklist", "checklist_json"),
        ("outcome", "outcome_json"),
    ]:
        if k in patch:
            cols.append(f"{col}=?")
            vals.append(to_json(patch[k]))
    if cols:
        cols.append("updated_at=?")
        vals.append(utcnow_iso())
        db.execute(f"UPDATE memos SET {', '.join(cols)} WHERE id=?", (*vals, memo_id))
    return get_memo(memo_id, settings)


def get_memo(memo_id: int, settings: Settings | None = None) -> dict | None:
    from ..db import get_db

    db = get_db(settings)
    row = db.query_one("SELECT * FROM memos WHERE id=?", (memo_id,))
    if not row:
        return None
    memo = _hydrate(dict(row))
    memo["gate"] = score_memo(dict(row))
    memo["predictions"] = [
        dict(p)
        for p in db.query(
            "SELECT * FROM memo_predictions WHERE memo_id=? ORDER BY horizon_date", (memo_id,)
        )
    ]
    memo["journal"] = [
        dict(j)
        for j in db.query(
            "SELECT * FROM journal_entries WHERE memo_id=? ORDER BY ts DESC", (memo_id,)
        )
    ]
    return memo


def list_memos(status: str | None = None, settings: Settings | None = None) -> dict:
    from ..db import get_db

    db = get_db(settings)
    if status:
        rows = db.query("SELECT * FROM memos WHERE status=? ORDER BY updated_at DESC", (status,))
    else:
        rows = db.query("SELECT * FROM memos ORDER BY updated_at DESC")
    kanban: dict[str, list] = {s: [] for s in STATUSES}
    for r in rows:
        memo = _hydrate(dict(r))
        memo["gate_score"] = score_memo(dict(r))["score"]
        kanban.setdefault(r["status"], []).append(memo)
    return kanban


def transition_memo(
    memo_id: int,
    to_status: str,
    override_reason: str | None = None,
    settings: Settings | None = None,
) -> dict:
    s = settings or get_settings()
    from ..db import get_db

    db = get_db(s)
    row = db.query_one("SELECT * FROM memos WHERE id=?", (memo_id,))
    if not row:
        return {"ok": False, "error": "memo not found"}
    if to_status not in STATUSES:
        return {"ok": False, "error": f"invalid status {to_status}"}

    # The Gate: Staged → Live
    if row["status"] == "staged" and to_status == "live":
        gate = score_memo(dict(row))
        if not gate["passes"] and not override_reason:
            return {
                "ok": False,
                "blocked": True,
                "gate": gate,
                "error": f"Gate score {gate['score']}/100 < {gate['gate_min']} — override reason required",
            }
        if override_reason:
            add_journal(
                memo_id,
                f"**Gate override** (score {gate['score']}/100): {override_reason}",
                kind="decision",
                settings=s,
            )
            db.execute("UPDATE memos SET override_reason=? WHERE id=?", (override_reason, memo_id))
        # Red Team pass on going Live
        from .redteam import run_redteam

        try:
            run_redteam(memo_id, s)
        except Exception as e:  # noqa: BLE001
            logger.warning("red team failed on memo #{}: {}", memo_id, e)

    ts_col = {"staged": "staged_at", "live": "live_at", "closed": "closed_at"}.get(to_status)
    now = utcnow_iso()
    sets = ["status=?", "updated_at=?"]
    vals: list = [to_status, now]
    if ts_col:
        sets.append(f"{ts_col}=?")
        vals.append(now)
    db.execute(f"UPDATE memos SET {', '.join(sets)} WHERE id=?", (*vals, memo_id))
    add_journal(memo_id, f"Status → **{to_status}**", kind="decision", settings=s)
    logger.info("memo #{} → {}", memo_id, to_status)
    return {"ok": True, "status": to_status, "memo": get_memo(memo_id, s)}


def add_prediction(memo_id: int, pred: dict, settings: Settings | None = None) -> int:
    from ..db import get_db

    db = get_db(settings)
    return db.execute(
        "INSERT INTO memo_predictions(memo_id,claim,probability,horizon_date,kind,resolve_rule,created_at) "
        "VALUES(?,?,?,?,?,?,?)",
        (
            memo_id,
            pred.get("claim", ""),
            float(pred.get("probability", 0.5)),
            pred.get("horizon_date"),
            pred.get("kind", "manual"),
            pred.get("resolve_rule"),
            utcnow_iso(),
        ),
    )


def add_journal(
    memo_id: int | None, markdown: str, kind: str = "note", settings: Settings | None = None
) -> int:
    from ..db import get_db

    return get_db(settings).execute(
        "INSERT INTO journal_entries(ts,kind,memo_id,markdown) VALUES(?,?,?,?)",
        (utcnow_iso(), kind, memo_id, markdown),
    )


def _hydrate(memo: dict) -> dict:
    for f in _JSON_FIELDS:
        if f in memo and isinstance(memo[f], str):
            memo[f.replace("_json", "")] = from_json(
                memo[f],
                []
                if f != "checklist_json" and f != "valuation_json" and f != "outcome_json"
                else {},
            )
    return memo
