"""MERIDIAN — a private, always-on market-intelligence research desk.

The package is organised into layers that mirror:

    connectors/  ingest external data (news, EDGAR, FRED, prices, crypto, ...)
    signals/     indicators, breadth, regime model, declarative alert rules
    agents/      the LLM analysis pipeline (triage -> analysts -> composer -> factcheck)
    briefs/      brief assembly, templates, TTS audio
    conviction/  the discipline core: memos, checklist gate, predictions, calibration
    notify/      P0/P1/P2 routing across ntfy / Pushover / iMessage
    api/         FastAPI routers + SSE
    ops/         health, cost governance, backups, watchdog

A single long-lived daemon (`meridiand`, see app.py) owns scheduling, ingestion,
signals, agents and the API. SQLite (WAL) is the source of truth; bulk OHLCV lives
in Parquet queried via DuckDB.
"""

__version__ = "1.0.0"
