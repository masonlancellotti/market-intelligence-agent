"""One-time-ish bootstrap: seed the ``instruments`` table from watchlist config.

Idempotent (upsert on ticker). Assigns the highest-precedence tier a ticker qualifies
for (holding > active > monitor > benchmark) and a best-effort ``kind``.
"""

from __future__ import annotations

from ..config import Settings, get_settings
from ..util import norm_ticker, to_json, utcnow_iso

_FUTURE_PROXIES = {"ES=F", "NQ=F", "YM=F", "RTY=F", "CL=F", "GC=F", "DX-Y.NYB"}
_INDEXES = {"^VIX", "^VIX3M", "^TNX", "^GSPC", "^NDX", "^DJI", "^RUT"}


def _kind(ticker: str, etf_set: set[str]) -> str:
    t = ticker.upper()
    if t.endswith("-USD"):
        return "crypto"
    if t in _FUTURE_PROXIES or t.endswith("=F"):
        return "future_proxy"
    if t.startswith("^") or t in _INDEXES:
        return "index"
    if t in etf_set:
        return "etf"
    return "equity"


def seed_instruments(settings: Settings | None = None) -> int:
    from ..db import get_db

    s = settings or get_settings()
    db = get_db(s)
    cfg = s.config

    # tier precedence, lowest first so later assignments win
    tiered: dict[str, str] = {}
    for t in cfg.benchmarks:
        tiered[norm_ticker(t)] = "benchmark"
    for t in cfg.sector_etfs:
        tiered.setdefault(norm_ticker(t), "monitor")
    for t in cfg.watchlist.monitor:
        tiered[norm_ticker(t)] = "monitor"
    for t in cfg.watchlist.active:
        tiered[norm_ticker(t)] = "active"
    for t in cfg.watchlist.holdings:
        tiered[norm_ticker(t)] = "holding"

    etf_set = {norm_ticker(t) for t in cfg.sector_etfs} | {
        "SPY",
        "QQQ",
        "IWM",
        "TLT",
        "GLD",
        "UUP",
        "SMH",
        "EEM",
        "RSP",
        "DIA",
    }

    n = 0
    for ticker, tier in tiered.items():
        kind = _kind(ticker, etf_set)
        db.execute(
            "INSERT INTO instruments(ticker,name,kind,tier,meta_json) VALUES(?,?,?,?,?) "
            "ON CONFLICT(ticker) DO UPDATE SET tier=excluded.tier, kind=excluded.kind",
            (ticker, ticker, kind, tier, to_json({"seeded_at": utcnow_iso()})),
        )
        n += 1
    return n


def instrument_id(ticker: str, settings: Settings | None = None) -> int | None:
    from ..db import get_db

    row = get_db(settings).query_one(
        "SELECT id FROM instruments WHERE ticker=?", (norm_ticker(ticker),)
    )
    return row["id"] if row else None
