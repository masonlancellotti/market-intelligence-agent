"""Small shared helpers: UTC time, JSON, tickers, safe numeric formatting."""

from __future__ import annotations

import json
import math
from datetime import UTC, date, datetime
from typing import Any


def utcnow() -> datetime:
    return datetime.now(UTC)


def utcnow_iso() -> str:
    """ISO-8601 UTC, seconds precision, 'Z' suffix — the storage convention."""
    return utcnow().replace(microsecond=0).isoformat().replace("+00:00", "Z")


def iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    # normalise to tz-aware UTC (SQLite datetime() yields naive strings)
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt


def today_iso(tz=UTC) -> str:
    return utcnow().astimezone(tz).date().isoformat()


def to_json(obj: Any) -> str:
    return json.dumps(obj, separators=(",", ":"), default=_json_default, ensure_ascii=False)


def from_json(s: str | None, default: Any = None) -> Any:
    if not s:
        return default
    try:
        return json.loads(s)
    except (json.JSONDecodeError, TypeError):
        return default


def _json_default(o: Any) -> Any:
    if isinstance(o, datetime | date):
        return o.isoformat()
    if isinstance(o, float) and (math.isnan(o) or math.isinf(o)):
        return None
    raise TypeError(f"not JSON serialisable: {type(o)}")


def clean_float(x: Any) -> float | None:
    """NaN/inf -> None so numbers never leak into JSON or the DB as garbage."""
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return f


def norm_ticker(t: str) -> str:
    return (t or "").strip().upper()


def pct(a: float | None, b: float | None) -> float | None:
    """Percent change from b (prior) to a (current)."""
    a, b = clean_float(a), clean_float(b)
    if a is None or b is None or b == 0:
        return None
    return (a - b) / b * 100.0
