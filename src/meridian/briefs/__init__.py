"""Briefs: morning/midday/closing/sunday/event-flash assembly.

Every brief renders to the dashboard (canonical), a push (title + 3-bullet TL;DR + deep
link), and a markdown archive. Every claim carries an ``[evidence:id]`` marker validated
by the fact-checker. Without an LLM key the composer degrades to a data-dense
template-with-tables — still fully cited, just no prose.
"""

from .assembly import generate_brief

__all__ = ["generate_brief"]
