"""Analyst agents — Sonnet. Read the structured context, emit structured
notes. Used by the LLM composer path; the degrade path renders tables directly.
"""

from __future__ import annotations

from ..agents.runner import run_structured
from ..agents.schemas import ANALYST_NOTE_SCHEMA
from ..config import Settings
from ..util import to_json

_RULES = (
    "Rules: (1) numbers ONLY from the DATA block — if missing, write '[data gap: X]', never "
    "estimate. (2) cite evidence ids for every fact: [n:id] news, [f:id] filing, [m:id] macro, "
    "[b:TICKER] bar. (3) forward-looking statements carry an explicit probability + horizon. "
    "(4) distinguish fact / consensus / your inference. (5) be terse."
)


def _note(domain: str, system_extra: str, ctx: dict, s: Settings) -> tuple[dict, float]:
    system = f"You are the {domain} analyst for a market-research desk. {system_extra} {_RULES}"
    user = "DATA:\n" + to_json(ctx)
    return run_structured(
        f"analyst:{domain}",
        system,
        user,
        ANALYST_NOTE_SCHEMA,
        model=s.config.models.analyst,
        max_tokens=1200,
        settings=s,
    )


def macro_note(ctx: dict, s: Settings):
    return _note(
        "macro",
        "Read rates, curve, HY spreads, inflation, Fed odds, regime → macro state + what "
        "changed since yesterday.",
        {"header": ctx["header"], "macro": ctx["macro"], "calendar": ctx["calendar"]},
        s,
    )


def technical_note(ctx: dict, s: Settings):
    return _note(
        "technical",
        "Signals only (no news). Per watchlist name: trend, key levels (Donchian/BB/52w/round "
        "numbers), setups forming.",
        {"movers": ctx["movers"], "header": ctx["header"]},
        s,
    )


def crypto_note(ctx: dict, s: Settings):
    return _note(
        "crypto",
        "BTC/ETH/SOL structure, funding/OI context, Fear & Greed, key levels.",
        {"header": ctx["header"], "crypto_fng": ctx["macro"].get("crypto_fng")},
        s,
    )
