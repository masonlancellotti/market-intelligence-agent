"""Brief assembly orchestrator.

Pipeline: build context → (analysts → composer) or degrade to template → fact-check →
store + archive → deliver push + SSE. Chooses the LLM path only when a key is present and
the daily budget allows; otherwise the degrade path (still fully cited).
"""

from __future__ import annotations

from loguru import logger

from ..agents.runner import BudgetExceeded, LLMUnavailable, llm_available
from ..config import Settings, get_settings
from ..util import to_json, today_iso, utcnow_iso
from . import context as ctxmod
from . import factcheck, templates

_MAX_RETRIES = 2


def generate_brief(
    kind: str = "morning", settings: Settings | None = None, event: dict | None = None
) -> dict:
    s = settings or get_settings()
    from ..db import get_db

    db = get_db(s)
    ctx = ctxmod.build_context(kind, s)
    evidence = ctx["evidence"]

    markdown, model, cost, mode = _render(kind, ctx, s, event)

    # fact-check (code layer always runs)
    result = factcheck.validate(markdown, evidence)
    retries = 0
    while not result["ok"] and mode == "llm" and retries < _MAX_RETRIES:
        logger.info("brief factcheck failed ({}), regenerating", result)
        markdown, model, cost2, mode = _render(kind, ctx, s, event)
        cost += cost2
        result = factcheck.validate(markdown, evidence)
        retries += 1
    if not result["ok"]:
        markdown = factcheck.mark_unverified(markdown, result)

    brief_id = db.execute(
        "INSERT INTO briefs(kind,for_date,markdown,json_payload,citations_json,model,cost_usd,created_at) "
        "VALUES(?,?,?,?,?,?,?,?)",
        (
            kind,
            today_iso(s.tz),
            markdown,
            to_json(ctx),
            to_json({"evidence": evidence, "factcheck": result}),
            model,
            cost,
            utcnow_iso(),
        ),
    )
    logger.info(
        "brief {} #{} ({} mode) ${:.4f} factcheck_ok={}", kind, brief_id, mode, cost, result["ok"]
    )
    _deliver(s, db, kind, brief_id, ctx, markdown)
    return {"id": brief_id, "kind": kind, "mode": mode, "cost_usd": cost, "factcheck": result}


def _render(kind: str, ctx: dict, s: Settings, event: dict | None):
    """Return (markdown, model, cost, mode)."""
    if llm_available(s):
        try:
            return _render_llm(kind, ctx, s, event)
        except (LLMUnavailable, BudgetExceeded) as e:
            logger.info("brief degrading to template: {}", e)
    return _render_degraded(kind, ctx, event), "template", 0.0, "template"


def _render_llm(kind: str, ctx: dict, s: Settings, event: dict | None):
    from . import analysts, composer

    cost = 0.0
    notes = {}
    if kind in ("morning", "closing", "sunday"):
        for name, fn in (
            ("macro", analysts.macro_note),
            ("technical", analysts.technical_note),
            ("crypto", analysts.crypto_note),
        ):
            try:
                note, c = fn(ctx, s)
                notes[name] = note
                cost += c
            except Exception as e:  # noqa: BLE001
                logger.warning("analyst {} failed: {}", name, e)
    markdown, c = composer.compose(kind, ctx, notes, s)
    cost += c
    return markdown, s.config.models.composer, cost, "llm"


def _render_degraded(kind: str, ctx: dict, event: dict | None) -> str:
    if kind == "closing":
        return templates.render_closing(ctx)
    if kind == "event_flash":
        return templates.render_event_flash(ctx, event or {})
    if kind == "sunday":
        from .hedge import hedge_ideas

        return templates.render_sunday(ctx, hedge_ideas(), _live_memo_summaries())
    if kind in ("crypto", "crypto_weekend"):
        return templates.render_crypto(ctx, ctx.get("macro", {}))
    return templates.render_morning(ctx)


def _live_memo_summaries() -> list[dict]:
    from ..db import get_db
    from ..util import from_json

    out = []
    for r in get_db().query(
        "SELECT id,ticker,direction,checklist_score,redteam_verdict FROM memos WHERE status='live'"
    ):
        out.append(
            {
                "ticker": r["ticker"],
                "direction": r["direction"],
                "gate_score": r["checklist_score"],
                "redteam": from_json(r["redteam_verdict"], {}),
            }
        )
    return out


def _tldr_for_push(markdown: str) -> str:
    """Extract the TL;DR bullets for the push body."""
    lines = markdown.splitlines()
    out = []
    capture = False
    for ln in lines:
        if ln.strip().lower().startswith("## tl;dr"):
            capture = True
            continue
        if capture:
            if ln.startswith("## "):
                break
            if ln.strip().startswith(("-", "*")):
                out.append(ln.strip().lstrip("-* ").strip())
    return "\n".join(f"• {re_strip(b)}" for b in out[:3]) or "Brief ready."


def re_strip(s: str) -> str:
    import re

    return re.sub(r"\[[a-z]:[^\]]+\]|\*\*", "", s).strip()


def _deliver(s: Settings, db, kind: str, brief_id: int, ctx: dict, markdown: str) -> None:
    from ..api.events import publish
    from ..notify import Notification, get_router

    publish("brief_ready", {"id": brief_id, "kind": kind})
    titles = {
        "morning": "☀️ Morning Brief",
        "closing": "🔔 Closing Wrap",
        "event_flash": "⚡ Event Flash",
        "sunday": "📊 Sunday Setup",
        "midday": "🕛 Midday Pulse",
        "crypto": "₿ Crypto Weekend",
    }
    priority = "P1"
    get_router(s).send(
        Notification(
            priority=priority,
            title=titles.get(kind, "Meridian Brief"),
            body=_tldr_for_push(markdown),
            dedupe_key=f"brief:{kind}:{today_iso(s.tz)}",
            cooldown_s=3600,
            click_path=f"/briefs/{brief_id}",
        )
    )
    db.execute("UPDATE briefs SET delivered_at=? WHERE id=?", (utcnow_iso(), brief_id))
