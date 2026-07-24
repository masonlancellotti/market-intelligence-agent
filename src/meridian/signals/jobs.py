"""Signal-engine schedule.

17:15 ET: full indicators → breadth → regime (after 17:10 bar finalization).
Every 30 min: recompute regime (VIX/breadth/F&G move intraday).
Every minute: evaluate the alert rules.
"""

from __future__ import annotations

from ..config import Settings
from ..ops.jobs import JobSpec, guard


def scheduled_jobs(settings: Settings) -> list[JobSpec]:
    from .engine import recompute_all
    from .regime import compute_regime
    from .rules import evaluate_rules

    @guard("signals_recompute")
    def recompute():
        recompute_all(settings)

    @guard("regime_intraday")
    def regime():
        compute_regime(settings)

    @guard("alert_loop")
    def alerts():
        evaluate_rules(settings)

    return [
        JobSpec(
            "signals_recompute",
            "Indicators/breadth/regime",
            recompute,
            "cron",
            {"hour": 17, "minute": 15},
        ),
        JobSpec("regime_intraday", "Regime refresh", regime, "interval", {"minutes": 30}),
        JobSpec("alert_loop", "Alert rule engine", alerts, "interval", {"minutes": 1}),
    ]
