"""Monthly Calibration Review — Opus writes the uncomfortable memo:
where Mason is overconfident, which edge types actually work, holding-period patterns.
Degrades to a structured data summary when no LLM key. This is the feature that compounds.
"""

from __future__ import annotations

from ..agents.runner import BudgetExceeded, LLMUnavailable, llm_available, log_degraded, run_text
from ..config import Settings, get_settings
from ..util import to_json, today_iso, utcnow_iso
from .predictions import brier_summary


def _edge_breakdown(db) -> list[dict]:
    rows = db.query(
        "SELECT m.edge_type, COUNT(p.id) n, AVG(p.brier) mean_brier, "
        "SUM(CASE WHEN p.resolution='true' THEN 1 ELSE 0 END)*1.0/COUNT(p.id) hit_rate "
        "FROM memo_predictions p JOIN memos m ON m.id=p.memo_id "
        "WHERE p.resolution IS NOT NULL GROUP BY m.edge_type"
    )
    return [dict(r) for r in rows]


def run_calibration_review(settings: Settings | None = None) -> dict:
    s = settings or get_settings()
    from ..db import get_db

    db = get_db(s)
    summary = brier_summary(s)
    edges = _edge_breakdown(db)
    data = {"brier": summary, "by_edge_type": edges}

    if summary["n"] == 0:
        markdown = "# Calibration Review\n\n_No resolved predictions yet — nothing to grade._"
    elif llm_available(s):
        try:
            markdown, _ = run_text(
                "calibration",
                "You are the Calibration Reviewer for a market-research desk. Write the uncomfortable "
                "monthly memo: where is Mason overconfident, which edge types actually work, holding-"
                "period patterns. Be specific and use only the provided numbers.",
                "DATA:\n" + to_json(data),
                model=s.config.models.deep,
                max_tokens=1200,
                settings=s,
            )
        except (LLMUnavailable, BudgetExceeded):
            markdown = _degraded_review(summary, edges)
            log_degraded("calibration")
    else:
        markdown = _degraded_review(summary, edges)
        log_degraded("calibration")

    brief_id = db.execute(
        "INSERT INTO briefs(kind,for_date,markdown,model,cost_usd,created_at) VALUES(?,?,?,?,?,?)",
        ("calibration", today_iso(s.tz), markdown, "review", 0.0, utcnow_iso()),
    )
    return {"brief_id": brief_id, "summary": summary}


def _degraded_review(summary: dict, edges: list[dict]) -> str:
    md = [
        "# Calibration Review",
        "",
        f"- Resolved predictions: **{summary['n']}**",
        f"- Mean Brier: **{summary['mean_brier']}** (0 = perfect, 0.25 = coin flip)",
        f"- Hit rate: **{summary['hit_rate']}**",
        "",
        "## Calibration by confidence",
    ]
    for c in summary["calibration"]:
        gap = c["realized"] - c["predicted"]
        tag = (
            "well-calibrated"
            if abs(gap) < 0.1
            else ("overconfident" if gap < 0 else "underconfident")
        )
        md.append(
            f"- {c['bucket']}: said {int(c['predicted'] * 100)}%, happened {int(c['realized'] * 100)}% (n={c['n']}) — {tag}"
        )
    if edges:
        md.append("\n## By edge type")
        for e in edges:
            md.append(
                f"- {e['edge_type'] or 'unclassified'}: n={e['n']}, mean Brier {round(e['mean_brier'] or 0, 3)}, hit rate {round(e['hit_rate'] or 0, 2)}"
            )
    md.append(
        "\n_Generated in review mode (no LLM key). The numbers don't lie; act on the overconfident buckets._"
    )
    return "\n".join(md)
