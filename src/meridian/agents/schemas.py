"""JSON schemas for structured agent I/O.

All non-composer agents emit JSON validated at the tool-use layer, so the model retries
on mismatch. Numbers must come only from the provided data block.
"""

from __future__ import annotations

TRIAGE_SCHEMA = {
    "type": "object",
    "properties": {
        "results": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer", "description": "the item id from the input"},
                    "relevant": {"type": "boolean"},
                    "tickers": {"type": "array", "items": {"type": "string"}},
                    "materiality": {"type": "integer", "minimum": 0, "maximum": 5},
                    "category": {
                        "type": "string",
                        "enum": [
                            "earnings",
                            "macro",
                            "ma",
                            "regulatory",
                            "product",
                            "management",
                            "market",
                            "general",
                        ],
                    },
                    "gist": {"type": "string", "description": "one-line neutral summary"},
                },
                "required": ["id", "relevant", "materiality", "category", "gist"],
            },
        }
    },
    "required": ["results"],
}

# Analyst note (macro/technical/crypto/equity) — used in Phase 4.
ANALYST_NOTE_SCHEMA = {
    "type": "object",
    "properties": {
        "headline": {"type": "string"},
        "points": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "evidence": {"type": "array", "items": {"type": "string"}},
                    "kind": {"type": "string", "enum": ["fact", "interpretation", "inference"]},
                },
                "required": ["text", "kind"],
            },
        },
        "levels": {"type": "array", "items": {"type": "object"}},
        "probability_statements": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "claim": {"type": "string"},
                    "probability": {"type": "number"},
                    "horizon": {"type": "string"},
                },
            },
        },
    },
    "required": ["headline", "points"],
}

REDTEAM_SCHEMA = {
    "type": "object",
    "properties": {
        "objections": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "objection": {"type": "string"},
                    "severity": {"type": "integer", "minimum": 1, "maximum": 5},
                    "addresses": {
                        "type": "string",
                        "enum": ["evidence", "crowding", "valuation", "timing", "thesis"],
                    },
                },
                "required": ["objection", "severity"],
            },
        },
        "overall_severity": {"type": "integer", "minimum": 1, "maximum": 5},
        "what_would_change_my_mind": {"type": "array", "items": {"type": "string"}},
        "verdict": {"type": "string", "enum": ["thesis_holds", "wounded", "broken"]},
    },
    "required": ["objections", "overall_severity", "verdict"],
}

FACTCHECK_SCHEMA = {
    "type": "object",
    "properties": {
        "uncited_numeric_claims": {"type": "array", "items": {"type": "string"}},
        "ok": {"type": "boolean"},
    },
    "required": ["ok"],
}
