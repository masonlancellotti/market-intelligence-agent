"""Connector schedule. Contributed to the daemon's job registry.

Cadence is deliberately conservative on the free/degraded paths (yfinance-delayed):
quotes every 5 min (crypto 24/7), futures proxies every 15 min, daily-history refresh
after the close. When Alpaca keys are present its connector supersedes yfinance quotes.
"""

from __future__ import annotations

from ..config import Settings
from ..ops.jobs import JobSpec, guard


def scheduled_jobs(settings: Settings) -> list[JobSpec]:
    from . import CONNECTORS
    from .history import refresh_history_all

    def _runner(name: str):
        @guard(f"connector:{name}")
        def run():
            CONNECTORS[name]().run_sync()

        return run

    @guard("history_refresh")
    def history_refresh():
        refresh_history_all(settings)

    jobs = [
        JobSpec(
            "conn_prices", "Quotes (equities/ETF)", _runner("prices"), "interval", {"minutes": 5}
        ),
        JobSpec(
            "conn_crypto", "Quotes (crypto 24/7)", _runner("crypto"), "interval", {"minutes": 5}
        ),
        JobSpec("conn_futures", "Futures proxies", _runner("futures"), "interval", {"minutes": 15}),
        JobSpec(
            "history_refresh",
            "Daily bar finalization",
            history_refresh,
            "cron",
            {"hour": 17, "minute": 10},
        ),
        # -- news / filings / macro (Phase 2) --
        JobSpec("conn_rss", "News (RSS)", _runner("rss"), "interval", {"minutes": 10}),
        JobSpec("conn_finnhub", "News (Finnhub)", _runner("finnhub"), "interval", {"minutes": 15}),
        JobSpec(
            "conn_gdelt", "News breadth (GDELT)", _runner("gdelt"), "interval", {"minutes": 60}
        ),
        JobSpec("conn_edgar", "SEC EDGAR", _runner("edgar"), "interval", {"minutes": 5}),
        JobSpec(
            "conn_predmkt", "Prediction markets", _runner("predmkt"), "interval", {"minutes": 60}
        ),
        JobSpec("conn_sentiment", "Sentiment", _runner("sentiment"), "interval", {"minutes": 30}),
        JobSpec("conn_fred", "Macro (FRED)", _runner("fred"), "cron", {"hour": "6,10,14,18"}),
        JobSpec("conn_calendar", "Econ calendar", _runner("calendar"), "cron", {"hour": 6}),
        JobSpec("conn_shorts", "Short data (FINRA)", _runner("shorts"), "cron", {"hour": 18}),
    ]
    # Alpaca supersedes yfinance quotes when keys exist.
    if CONNECTORS.get("alpaca") and CONNECTORS["alpaca"](settings).enabled():
        jobs.append(
            JobSpec(
                "conn_alpaca", "Alpaca IEX quotes", _runner("alpaca"), "interval", {"minutes": 2}
            )
        )
    return jobs
