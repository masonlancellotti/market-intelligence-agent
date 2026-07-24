"""Conviction endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Body, HTTPException

from ..conviction import memos as M
from ..conviction.predictions import brier_summary
from ..db import get_db

router = APIRouter()


@router.get("/memos")
def memos_kanban(status: str | None = None) -> dict:
    return {"kanban": M.list_memos(status)}


@router.get("/memos/{memo_id}")
def memo_detail(memo_id: int) -> dict:
    memo = M.get_memo(memo_id)
    if not memo:
        raise HTTPException(404, "memo not found")
    return {"memo": memo}


@router.post("/memos")
def create(data: dict = Body(...)) -> dict:
    memo_id = M.create_memo(data)
    return {"id": memo_id, "memo": M.get_memo(memo_id)}


@router.patch("/memos/{memo_id}")
def update(memo_id: int, patch: dict = Body(...)) -> dict:
    memo = M.update_memo(memo_id, patch)
    if not memo:
        raise HTTPException(404, "memo not found")
    return {"memo": memo}


@router.post("/memos/{memo_id}/transition")
def transition(memo_id: int, body: dict = Body(...)) -> dict:
    return M.transition_memo(memo_id, body.get("to"), body.get("override_reason"))


@router.post("/memos/{memo_id}/redteam")
def redteam(memo_id: int) -> dict:
    from ..conviction.redteam import run_redteam

    return run_redteam(memo_id)


@router.post("/memos/{memo_id}/predictions")
def add_prediction(memo_id: int, pred: dict = Body(...)) -> dict:
    pid = M.add_prediction(memo_id, pred)
    return {"id": pid}


@router.get("/journal")
def journal(limit: int = 60) -> dict:
    db = get_db()
    rows = db.query(
        "SELECT j.id,j.ts,j.kind,j.memo_id,j.markdown,m.ticker "
        "FROM journal_entries j LEFT JOIN memos m ON m.id=j.memo_id "
        "ORDER BY j.ts DESC LIMIT ?",
        (min(limit, 300),),
    )
    return {"entries": [dict(r) for r in rows], "calibration": brier_summary()}


@router.post("/journal")
def add_journal(body: dict = Body(...)) -> dict:
    jid = M.add_journal(body.get("memo_id"), body.get("markdown", ""), body.get("kind", "note"))
    return {"id": jid}


@router.get("/calibration")
def calibration() -> dict:
    return brier_summary()
