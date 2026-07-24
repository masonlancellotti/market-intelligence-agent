"""Agent layer: triage → analysts → red team → composer → fact-checker.

Structured I/O via tool-use JSON schemas; cost-tiered models; hard daily budget governor
with graceful degrade. The composer alone emits markdown.
"""

from .runner import BudgetExceeded, LLMUnavailable, llm_available, run_structured, run_text

__all__ = [
    "run_structured",
    "run_text",
    "llm_available",
    "LLMUnavailable",
    "BudgetExceeded",
]
