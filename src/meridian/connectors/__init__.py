"""Ingestion connectors.

Every connector subclasses :class:`BaseConnector`: uniform tenacity backoff, a
per-connector circuit breaker, freshness stamping, and health logging. A connector
failing must never take down the daemon or silently zero out data.

Public helpers used by ``manage.py`` and the scheduler:
- :func:`run_connector` — run one connector by name, now.
- :func:`refresh_quotes_now` — pull latest quotes for the watchlist, now.
"""

from __future__ import annotations

# Import connector modules so their @register decorators populate CONNECTORS.
from . import (  # noqa: E402,F401
    alpaca,
    calendar_ff,
    crypto,
    edgar,
    finnhub,
    fred,
    futures,
    gdelt,
    predmkt,
    prices,
    rss,
    sentiment,
    shorts,
    stooq,
)
from .base import CONNECTORS, BaseConnector, FetchResult, register

__all__ = [
    "BaseConnector",
    "FetchResult",
    "CONNECTORS",
    "register",
    "run_connector",
    "refresh_quotes_now",
]


def run_connector(name: str) -> dict:
    cls = CONNECTORS.get(name)
    if not cls:
        return {"ok": False, "error": f"unknown connector '{name}'", "known": sorted(CONNECTORS)}
    return cls().run_sync()


def refresh_quotes_now() -> dict:
    """Pull latest quotes for the whole watchlist (equities+ETF+futures+crypto)."""
    out = {}
    for name in ("prices", "futures", "crypto"):
        if name in CONNECTORS:
            out[name] = CONNECTORS[name]().run_sync()
    return out
