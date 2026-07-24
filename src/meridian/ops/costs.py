"""LLM cost governance.

Every agent call is logged to ``agent_runs``. Hard daily cap from config: at 80% a
P2 warning fires; at 100% agents degrade (triage-only, template briefs) rather than
overrun. Sunday is allowed a multiple of the daily cap.
"""

from __future__ import annotations

from datetime import timedelta

from ..config import Settings, get_settings
from ..util import utcnow

# Anthropic per-MTok pricing (USD), used to estimate cost when the API doesn't return it.
# Input / output. Kept here so pricing changes are one edit.
PRICING = {
    "claude-haiku-4-5-20251001": (1.00, 5.00),
    "claude-haiku-4-5": (1.00, 5.00),
    "claude-sonnet-5": (3.00, 15.00),
    "claude-opus-4-8": (15.00, 75.00),
}
_DEFAULT_PRICE = (3.00, 15.00)


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    pin, pout = PRICING.get(model, _DEFAULT_PRICE)
    return round(input_tokens / 1e6 * pin + output_tokens / 1e6 * pout, 6)


def _spent_since(iso_start: str) -> float:
    from ..db import get_db

    row = get_db().query_one(
        "SELECT COALESCE(SUM(cost_usd),0) AS s FROM agent_runs WHERE started_at>=?",
        (iso_start,),
    )
    return float(row["s"]) if row else 0.0


def spent_today(settings: Settings | None = None) -> float:
    s = settings or get_settings()
    start = utcnow().astimezone(s.tz).replace(hour=0, minute=0, second=0, microsecond=0)
    return _spent_since(start.astimezone(utcnow().tzinfo).isoformat().replace("+00:00", "Z"))


def spent_this_month(settings: Settings | None = None) -> float:
    s = settings or get_settings()
    start = utcnow().astimezone(s.tz).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return _spent_since(start.astimezone(utcnow().tzinfo).isoformat().replace("+00:00", "Z"))


def daily_cap(settings: Settings | None = None) -> float:
    s = settings or get_settings()
    cap = s.config.budgets.llm_daily_usd
    if utcnow().astimezone(s.tz).weekday() == 6:  # Sunday
        cap *= s.config.budgets.sunday_multiplier
    return cap


def budget_state(settings: Settings | None = None) -> str:
    """One of: ok | warn (>=80%) | exhausted (>=100%)."""
    s = settings or get_settings()
    cap = daily_cap(s)
    if cap <= 0:
        return "ok"
    frac = spent_today(s) / cap
    if frac >= 1.0:
        return "exhausted"
    if frac >= 0.80:
        return "warn"
    return "ok"


def can_spend(model: str, est_usd: float, settings: Settings | None = None) -> bool:
    s = settings or get_settings()
    return spent_today(s) + est_usd <= daily_cap(s) + 1e-9


def cost_summary(settings: Settings | None = None) -> dict:
    from ..db import get_db

    s = settings or get_settings()
    today = spent_today(s)
    month = spent_this_month(s)
    cap_d = daily_cap(s)
    cap_m = s.config.budgets.llm_monthly_usd
    day7 = utcnow() - timedelta(days=7)
    by_agent = get_db().query(
        "SELECT agent, COUNT(*) n, COALESCE(SUM(cost_usd),0) cost, "
        "COALESCE(SUM(input_tokens),0) tin, COALESCE(SUM(output_tokens),0) tout "
        "FROM agent_runs WHERE started_at>=? GROUP BY agent ORDER BY cost DESC",
        (day7.isoformat().replace("+00:00", "Z"),),
    )
    return {
        "today_usd": round(today, 4),
        "daily_cap_usd": round(cap_d, 2),
        "today_pct": round(today / cap_d * 100, 1) if cap_d else 0,
        "month_usd": round(month, 4),
        "monthly_cap_usd": cap_m,
        "month_pct": round(month / cap_m * 100, 1) if cap_m else 0,
        "state": budget_state(s),
        "by_agent_7d": [dict(r) for r in by_agent],
    }
