"""Conviction Desk — the discipline core.

No position without a memo. The memo, not the mood, is what gets reviewed later. A memo
runs Research → Staged → Live → Closed; the Gate blocks
Staged→Live below 70/100 without a typed, journaled override. Every memo logs ≥2
falsifiable predictions that auto-resolve into Brier scores → the calibration engine.
"""

from .memos import create_memo, get_memo, list_memos, transition_memo, update_memo

__all__ = ["create_memo", "get_memo", "list_memos", "transition_memo", "update_memo"]
