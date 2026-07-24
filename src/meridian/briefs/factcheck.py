"""Fact-checker.

Code layer (always runs, no LLM): every ``[type:id]`` marker must exist in the evidence
registry, and any number written immediately before a bar/macro marker must match the
stored value within tolerance. An LLM layer (Haiku) optionally scans for *uncited*
quantitative claims. Failures reject & regenerate a section (max 2 retries) or publish
with an "unverified" note.
"""

from __future__ import annotations

import re

_MARKER = re.compile(r"\[([a-z]):([^\]]+)\]")
# An UNSIGNED number directly citing a marker — either just before it or just after it.
# Signed numbers (+0.38%, -1.39%) are derived changes, NOT the cited value, so excluded
# via the (?<![+\-]) lookbehind / the leading-sign exclusion.
# lookbehind excludes +,-,digit AND '.' so we never grab a fragment of a signed/decimal
# number (e.g. "38" out of "+0.38%"); trailing (?![\d.]) ensures a complete token.
_NUM_BEFORE = re.compile(r"(?<![+\-\d.])(\$?\d[\d,]*\.?\d*)(?![\d.])\s*%?\s*\[(b|m):([^\]]+)\]")
# after-marker only in table-cell context ("[b:NVDA] | $194.83") so we never cross a
# bullet separator into the next item (e.g. "[b:BTC-USD] · 10Y").
_NUM_AFTER = re.compile(r"\[(b|m):([^\]]+)\]\s*\|\s*(?<![+\-])(\$?\d[\d,]*\.?\d*)(?![\d.])")
_NUM_TOLERANCE = 0.001  # 0.1% fallback


def _to_float(s: str) -> float | None:
    try:
        return float(s.replace("$", "").replace(",", "").replace("+", ""))
    except ValueError:
        return None


def _decimals(s: str) -> int:
    s = s.replace("$", "").replace(",", "")
    return len(s.split(".")[1]) if "." in s else 0


def _matches(claimed_str: str, stored: float) -> bool:
    claimed = _to_float(claimed_str)
    if claimed is None:
        return True  # unparseable → don't flag
    # display-precision match (handles 16.1 vs 16.149 → both "16.1" at 1dp)
    d = _decimals(claimed_str)
    if round(stored, d) == round(claimed, d):
        return True
    if stored == 0:
        return abs(claimed) < 1e-9
    return abs(claimed - stored) / abs(stored) <= _NUM_TOLERANCE


def validate(markdown: str, evidence: dict) -> dict:
    """Return {ok, missing_markers, numeric_mismatches, checked}."""
    missing = [
        f"{m.group(1)}:{m.group(2)}"
        for m in _MARKER.finditer(markdown)
        if f"{m.group(1)}:{m.group(2)}" not in evidence
    ]

    mismatches = []
    checked = 0
    seen: set[tuple] = set()
    for regex, num_grp, id_grps in ((_NUM_BEFORE, 1, (2, 3)), (_NUM_AFTER, 3, (1, 2))):
        for m in regex.finditer(markdown):
            eid = f"{m.group(id_grps[0])}:{m.group(id_grps[1])}"
            num_str = m.group(num_grp)
            ev = evidence.get(eid)
            if ev is None or ev.get("kind") not in ("bar", "macro"):
                continue
            stored = ev.get("value")
            if not isinstance(stored, int | float):
                continue
            key = (eid, num_str, m.start())
            if key in seen:
                continue
            seen.add(key)
            checked += 1
            if not _matches(num_str, stored):
                mismatches.append(
                    {"id": eid, "claimed": _to_float(num_str), "stored": round(stored, 4)}
                )

    return {
        "ok": not missing and not mismatches,
        "missing_markers": sorted(set(missing)),
        "numeric_mismatches": mismatches,
        "checked_numbers": checked,
    }


def mark_unverified(markdown: str, result: dict) -> str:
    """Annotate a brief that failed validation rather than dropping it."""
    if result["ok"]:
        return markdown
    notes = []
    if result["missing_markers"]:
        notes.append(f"missing evidence: {', '.join(result['missing_markers'][:6])}")
    if result["numeric_mismatches"]:
        ex = result["numeric_mismatches"][0]
        notes.append(
            f"{len(result['numeric_mismatches'])} numeric mismatch(es), e.g. {ex['id']} "
            f"claimed {ex['claimed']} vs stored {ex['stored']}"
        )
    banner = "\n\n> **Unverified:** " + "; ".join(notes) + "\n"
    return markdown + banner
