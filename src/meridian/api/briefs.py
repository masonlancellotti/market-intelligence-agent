"""Briefs endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..db import get_db
from ..util import from_json

router = APIRouter()


@router.get("/briefs")
def briefs(kind: str | None = None, limit: int = 40) -> dict:
    db = get_db()
    if kind:
        rows = db.query(
            "SELECT id,kind,for_date,model,cost_usd,created_at,delivered_at,audio_path "
            "FROM briefs WHERE kind=? ORDER BY created_at DESC LIMIT ?",
            (kind, limit),
        )
    else:
        rows = db.query(
            "SELECT id,kind,for_date,model,cost_usd,created_at,delivered_at,audio_path "
            "FROM briefs ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )
    return {"briefs": [dict(r) for r in rows]}


@router.get("/briefs/latest")
def latest(kind: str = "morning") -> dict:
    db = get_db()
    row = db.query_one(
        "SELECT * FROM briefs WHERE kind=? ORDER BY created_at DESC LIMIT 1", (kind,)
    )
    if not row:
        return {"brief": None}
    return {"brief": _full(row)}


@router.get("/briefs/{brief_id}")
def brief(brief_id: int) -> dict:
    db = get_db()
    row = db.query_one("SELECT * FROM briefs WHERE id=?", (brief_id,))
    if not row:
        raise HTTPException(404, "brief not found")
    return {"brief": _full(row)}


def _full(row) -> dict:
    citations = from_json(row["citations_json"], {})
    return {
        "id": row["id"],
        "kind": row["kind"],
        "for_date": row["for_date"],
        "markdown": row["markdown"],
        "model": row["model"],
        "cost_usd": row["cost_usd"],
        "created_at": row["created_at"],
        "delivered_at": row["delivered_at"],
        "audio_path": row["audio_path"],
        "evidence": citations.get("evidence", {}),  # for hover-cards
        "factcheck": citations.get("factcheck", {}),
    }
