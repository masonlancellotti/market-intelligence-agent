"""Live keyless refresh (V2 WS1).

``manage.py refresh`` pulls TODAY's data using only keyless sources — yfinance quotes,
Kalshi public markets, RSS news, SEC EDGAR (User-Agent only) — recomputes the signal
stack, and records a freshness timestamp for the dashboard banner.

Design guarantees:
* keyless only — connectors requiring secrets (FRED/Finnhub/Alpaca) are skipped, and the
  regime engine's weight renormalisation absorbs their absence;
* per-connector isolation — a connector failing is reported, never fatal (circuit
  breakers already back each one);
* a ``--dry-run`` mode that touches no network and just reports what would run.
"""

from __future__ import annotations

import time

from loguru import logger

from ..config import Settings, get_settings
from ..util import utcnow_iso

# Keyless connectors, in run order. Quote pullers first, then news/filings/markets.
KEYLESS_CONNECTORS = [
    "prices",
    "futures",
    "crypto",
    "predmkt",  # Kalshi public REST — no auth for market data
    "rss",
    "edgar",  # keyless, User-Agent only (placeholder-configurable via .env)
    "gdelt",
    "calendar",
    "sentiment",
]


# Signal-relevant tickers whose recent history we top up so the regime is current.
def _history_tickers(s: Settings) -> list[str]:
    from ..util import norm_ticker

    tick = [
        "SPY",
        "^VIX",
        "^VIX3M",
        *s.config.benchmarks,
        *s.config.sector_etfs,
        "UUP",
        "HYG",
        "LQD",
    ]
    return list(dict.fromkeys(norm_ticker(t) for t in tick))


def refresh_status(settings: Settings | None = None) -> dict:
    """Snapshot vs live freshness for the dashboard banner (safe, read-only)."""
    s = settings or get_settings()
    from ..db import get_db

    db = get_db(s)
    last = db.get_setting("refresh.last")
    # Snapshot date = newest quote timestamp in the committed DB.
    snap = db.query_one("SELECT MAX(ts) AS ts FROM quotes_latest")
    return {
        "last_refresh": (last or {}).get("at"),
        "last_refresh_ok": (last or {}).get("ok"),
        "connectors": (last or {}).get("connectors", []),
        "snapshot_ts": snap["ts"] if snap else None,
        "mode": "live" if last else "snapshot",
    }


def live_refresh(
    dry_run: bool = False, settings: Settings | None = None, refresh_history: bool = True
) -> dict:
    """Run the keyless refresh. Never raises on partial failure."""
    s = settings or get_settings()
    from ..connectors.base import CONNECTORS
    from ..db import get_db

    db = get_db(s)
    db.migrate()

    keyless = []
    for name in KEYLESS_CONNECTORS:
        cls = CONNECTORS.get(name)
        if not cls:
            continue
        try:
            enabled = cls(s).enabled()
        except Exception:  # noqa: BLE001
            enabled = False
        keyless.append({"connector": name, "keyless": True, "enabled": enabled})

    if dry_run:
        return {
            "dry_run": True,
            "would_run": keyless,
            "history_tickers": _history_tickers(s) if refresh_history else [],
            "status": refresh_status(s),
        }

    started = time.time()
    results = []
    for name in KEYLESS_CONNECTORS:
        cls = CONNECTORS.get(name)
        if not cls:
            continue
        t0 = time.time()
        try:
            r = cls(s).run_sync()
        except Exception as e:  # noqa: BLE001 — isolation: a connector never fatal
            r = {"connector": name, "ok": False, "status": "error", "error": str(e)[:200]}
        r["ms"] = int((time.time() - t0) * 1000)
        results.append(r)
        logger.info("refresh {}: {} ({} items)", name, r.get("status"), r.get("items", "-"))

    history = {}
    if refresh_history:
        history = _refresh_recent_history(s)

    signals = {}
    try:
        from ..signals import recompute_all

        sig = recompute_all(s)
        signals = {
            "regime": (sig.get("regime") or {}).get("score"),
            "bucket": (sig.get("regime") or {}).get("bucket"),
        }
    except Exception as e:  # noqa: BLE001
        signals = {"error": str(e)[:200]}

    ok = sum(1 for r in results if r.get("ok"))
    summary = {
        "at": utcnow_iso(),
        "ok": True,
        "elapsed_s": round(time.time() - started, 1),
        "connectors_ok": ok,
        "connectors_total": len(results),
        "connectors": [
            {
                "connector": r["connector"],
                "ok": bool(r.get("ok")),
                "status": r.get("status"),
                "items": r.get("items"),
                "error": r.get("error"),
            }
            for r in results
        ],
        "history": history,
        "signals": signals,
    }
    db.set_setting("refresh.last", summary)
    return summary


def _refresh_recent_history(s: Settings) -> dict:
    from ..connectors.history import update_recent

    ok = fail = 0
    for t in _history_tickers(s):
        try:
            r = update_recent(t, s)
            ok += 1 if r.get("ok") else 0
            fail += 0 if r.get("ok") else 1
        except Exception:  # noqa: BLE001
            fail += 1
    return {"refreshed": ok, "failed": fail}


def format_summary(summary: dict) -> str:
    """Human-readable per-connector success/failure block for the CLI."""
    if summary.get("dry_run"):
        lines = ["refresh --dry-run (no network) — keyless connectors that would run:"]
        for c in summary["would_run"]:
            lines.append(f"  · {c['connector']:<10} enabled={c['enabled']}")
        st = summary["status"]
        lines.append(f"  snapshot_ts={st['snapshot_ts']}  last_refresh={st['last_refresh']}")
        return "\n".join(lines)
    lines = [
        f"refresh complete in {summary['elapsed_s']}s — "
        f"{summary['connectors_ok']}/{summary['connectors_total']} connectors ok"
    ]
    for c in summary["connectors"]:
        mark = "ok " if c["ok"] else "FAIL"
        extra = f" items={c['items']}" if c.get("items") is not None else ""
        err = f"  {c['error']}" if c.get("error") else ""
        lines.append(f"  [{mark}] {c['connector']:<10} {c['status'] or '':<12}{extra}{err}")
    h = summary.get("history") or {}
    if h:
        lines.append(f"  history: {h.get('refreshed', 0)} refreshed, {h.get('failed', 0)} failed")
    sig = summary.get("signals") or {}
    if "bucket" in sig:
        lines.append(f"  regime: {sig.get('score', sig.get('bucket'))} ({sig.get('bucket')})")
    return "\n".join(lines)
