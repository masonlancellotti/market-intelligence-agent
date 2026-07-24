"""Red Team pass — Opus at Staged→Live and every Sunday on Live memos.

Strongest possible bear (or bull, if short) case; attacks evidence quality, crowding,
valuation, timing. Verdict pinned to the memo so the dashboard shows the bear case next to
the thesis, permanently. Degrades to a structured heuristic when no LLM key.
"""

from __future__ import annotations

from ..agents.runner import (
    BudgetExceeded,
    LLMUnavailable,
    llm_available,
    log_degraded,
    run_structured,
)
from ..agents.schemas import REDTEAM_SCHEMA
from ..config import Settings, get_settings
from ..util import from_json, to_json


def run_redteam(memo_id: int, settings: Settings | None = None) -> dict:
    s = settings or get_settings()
    from ..db import get_db

    db = get_db(s)
    memo = db.query_one("SELECT * FROM memos WHERE id=?", (memo_id,))
    if not memo:
        return {"ok": False, "error": "memo not found"}

    if llm_available(s):
        try:
            verdict = _llm_redteam(dict(memo), s)
        except (LLMUnavailable, BudgetExceeded):
            verdict = _heuristic_redteam(dict(memo))
            log_degraded("redteam", task_ref=f"memo:{memo_id}")
    else:
        verdict = _heuristic_redteam(dict(memo))
        log_degraded("redteam", task_ref=f"memo:{memo_id}")

    db.execute("UPDATE memos SET redteam_verdict=? WHERE id=?", (to_json(verdict), memo_id))
    return {"ok": True, "verdict": verdict}


def _llm_redteam(memo: dict, s: Settings) -> dict:
    side = "bull" if memo.get("direction") == "short" else "bear"
    system = (
        f"You are the Red Team for a market-research desk. Build the strongest possible {side} "
        "case against this thesis. Attack evidence quality, crowding, valuation, and timing. "
        "For each objection give a severity 1-5 and what it addresses. End with an overall "
        "severity, what_would_change_my_mind, and a verdict (thesis_holds/wounded/broken)."
    )
    user = "MEMO:\n" + to_json(
        {
            k: memo.get(k)
            for k in (
                "ticker",
                "direction",
                "thesis",
                "edge_type",
                "catalysts_json",
                "risks_json",
                "valuation_json",
                "invalidation_level",
                "invalidation_rule",
            )
        }
    )
    obj, _ = run_structured(
        "redteam",
        system,
        user,
        REDTEAM_SCHEMA,
        model=s.config.models.deep,
        max_tokens=1500,
        settings=s,
    )
    obj["mode"] = "llm"
    return obj


def _heuristic_redteam(memo: dict) -> dict:
    risks = (
        from_json(memo.get("risks_json"), [])
        if isinstance(memo.get("risks_json"), str)
        else (memo.get("risks_json") or [])
    )
    objections = [
        {"objection": f"Stated risk not fully priced: {r}", "severity": 3, "addresses": "thesis"}
        for r in risks[:3]
    ]
    objections += [
        {
            "objection": "Is this consensus? If widely held, the edge may already be in the price.",
            "severity": 3,
            "addresses": "crowding",
        },
        {
            "objection": "Valuation vs history/peers — is the entry demanding perfect execution?",
            "severity": 3,
            "addresses": "valuation",
        },
        {
            "objection": "Timing: what forces the catalyst to matter on your horizon vs drifting?",
            "severity": 2,
            "addresses": "timing",
        },
    ]
    severity = max((o["severity"] for o in objections), default=3)
    return {
        "objections": objections,
        "overall_severity": severity,
        "what_would_change_my_mind": [
            "A dated catalyst with a clear mechanism",
            "Evidence the position is under-owned / contrarian",
        ],
        "verdict": "wounded" if severity >= 4 else "thesis_holds",
        "mode": "heuristic",
    }
