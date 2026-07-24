"""Composer agent — Sonnet. The only agent that emits markdown.

Assembles a brief from the structured context + analyst notes, following the fixed
template, with an ``[evidence:id]`` marker on every number. The fact-checker then
validates the output.
"""

from __future__ import annotations

from ..agents.runner import run_text
from ..config import Settings
from ..util import to_json

MORNING_TEMPLATE = """# Morning Brief — {weekday}
## TL;DR (≤3 bullets)
## Overnight & Global
## Today's Calendar
## Portfolio Check
## Watchlist Movers & Setups
## Macro Pulse
## Filings & Insiders
## One Thing to Think About
## Data Gaps & System Notes"""

_SYSTEM = (
    "You are the composer for a market-research desk. Assemble the brief from the DATA and "
    "NOTES per the exact section template. NON-NEGOTIABLE: every number must come from DATA "
    "and carry its evidence marker ([b:TICKER] bar, [n:id] news, [m:id] macro, [f:id] filing). "
    "Never invent a number. Keep each section tight. End with the required disclaimer footer."
)


def compose(kind: str, ctx: dict, notes: dict, s: Settings) -> tuple[str, float]:
    template = MORNING_TEMPLATE if kind == "morning" else f"# {kind.title()} Brief"
    user = (
        f"TEMPLATE:\n{template}\n\nDATA:\n{to_json(ctx)}\n\nANALYST NOTES:\n{to_json(notes)}\n\n"
        "Write the brief now."
    )
    return run_text(
        "composer", _SYSTEM, user, model=s.config.models.composer, max_tokens=2500, settings=s
    )
