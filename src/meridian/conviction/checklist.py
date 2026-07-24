"""The Gate — 10-item conviction checklist.

A memo cannot go Staged→Live below 70/100 without a typed override reason (itself
journaled). Each item is scored from the memo's structured fields so the gate is
objective and repeatable; item 6 (invalidation + exit) is the heaviest at 15.
"""

from __future__ import annotations

from ..util import from_json, parse_iso, utcnow

# (key, label, max_points). Weights sum to 100.
ITEMS = [
    ("thesis", "Thesis in one falsifiable sentence", 10),
    ("edge", "Edge classification (info/analytical/behavioral/structural) + why", 10),
    ("disconfirming", "Disconfirming evidence actively sought & listed", 10),
    ("valuation", "Valuation sanity vs history & peers", 10),
    ("catalysts", "Catalyst(s) + expected timeline", 10),
    ("invalidation", "Invalidation level + rule + written exit plan", 15),
    ("sizing", "Position size vs portfolio vol budget", 10),
    ("correlation", "Correlation to existing book (flag if >0.7)", 10),
    ("redteam", "Red Team objections addressed point-by-point", 10),
    ("cooling_off", "Cooling-off ≥24h between creation and Live", 5),
]
GATE_MIN = 70


def score_memo(memo: dict) -> dict:
    """Return {score, breakdown:{key:{points,max,ok,note}}, passes}."""
    breakdown: dict[str, dict] = {}
    checklist = (
        from_json(memo.get("checklist_json"), {})
        if isinstance(memo.get("checklist_json"), str)
        else (memo.get("checklist_json") or {})
    )

    for key, label, mx in ITEMS:
        pts, note = _score_item(key, mx, memo, checklist)
        breakdown[key] = {
            "label": label,
            "points": pts,
            "max": mx,
            "ok": pts >= mx * 0.75,
            "note": note,
        }

    total = sum(b["points"] for b in breakdown.values())
    return {
        "score": total,
        "breakdown": breakdown,
        "passes": total >= GATE_MIN,
        "gate_min": GATE_MIN,
    }


def _nonempty(v) -> bool:
    if v is None:
        return False
    if isinstance(v, str):
        return len(v.strip()) > 0
    if isinstance(v, list | dict):
        return len(v) > 0
    return True


def _list(memo, field):
    v = memo.get(field)
    return from_json(v, []) if isinstance(v, str) else (v or [])


def _score_item(key: str, mx: int, memo: dict, checklist: dict) -> tuple[int, str]:
    # explicit checklist override (manual answer) wins if present
    manual = checklist.get(key)
    if isinstance(manual, dict) and manual.get("points") is not None:
        return min(int(manual["points"]), mx), manual.get("note", "manual")

    if key == "thesis":
        t = (memo.get("thesis") or "").strip()
        if not t:
            return 0, "no thesis"
        # falsifiable + concise heuristic: one/two sentences, has a claim
        sentences = t.count(".") + t.count("?")
        return (
            mx if 0 < len(t) <= 240 and sentences <= 2 else int(mx * 0.6),
            "ok" if len(t) <= 240 else "tighten to one sentence",
        )
    if key == "edge":
        et = (memo.get("edge_type") or "").lower()
        return (
            mx if et in ("informational", "analytical", "behavioral", "structural") else 0,
            et or "unclassified",
        )
    if key == "disconfirming":
        risks = _list(memo, "risks_json")
        return (mx if len(risks) >= 2 else int(mx * len(risks) / 2), f"{len(risks)} risks listed")
    if key == "valuation":
        val = memo.get("valuation_json")
        val = from_json(val, {}) if isinstance(val, str) else (val or {})
        return (mx if _nonempty(val) else 0, "valuation noted" if val else "no valuation")
    if key == "catalysts":
        cats = _list(memo, "catalysts_json")
        return (mx if len(cats) >= 1 else 0, f"{len(cats)} catalysts")
    if key == "invalidation":
        has_level = memo.get("invalidation_level") is not None
        has_rule = _nonempty(memo.get("invalidation_rule"))
        has_exit = _nonempty(memo.get("entry_plan"))
        pts = (6 if has_level else 0) + (5 if has_rule else 0) + (4 if has_exit else 0)
        return pts, f"level={has_level} rule={has_rule} exit={has_exit}"
    if key == "sizing":
        return (
            mx if _nonempty(memo.get("size_plan")) else 0,
            "sized" if memo.get("size_plan") else "no size plan",
        )
    if key == "correlation":
        # satisfied if there's a correlation note in checklist or valuation
        note = checklist.get("correlation_note") or (memo.get("valuation_json") and "corr")
        return (mx if note else int(mx * 0.5), "noted" if note else "assumed low (verify)")
    if key == "redteam":
        return (
            mx if _nonempty(memo.get("redteam_verdict")) else 0,
            "red team run" if memo.get("redteam_verdict") else "no red team",
        )
    if key == "cooling_off":
        created = parse_iso(memo.get("created_at"))
        if not created:
            return 0, "no timestamp"
        hours = (utcnow() - created).total_seconds() / 3600
        return (mx if hours >= 24 else 0, f"{hours:.0f}h since creation")
    return 0, ""
