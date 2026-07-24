"""Markets endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..config import get_settings
from ..db import get_db
from ..util import norm_ticker, pct

router = APIRouter()

_TIER_ORDER = {"holding": 0, "active": 1, "monitor": 2, "benchmark": 3}
_RANGE_BARS = {"1W": 5, "1M": 22, "3M": 66, "6M": 132, "1Y": 252, "5Y": 1300, "ALL": 100000}


def _quote_row(r) -> dict:
    change = pct(r["price"], r["prev_close"])
    return {
        "ticker": r["ticker"],
        "name": r["name"],
        "kind": r["kind"],
        "tier": r["tier"],
        "sector": r["sector"],
        "price": r["price"],
        "prev_close": r["prev_close"],
        "day_open": r["day_open"],
        "day_high": r["day_high"],
        "day_low": r["day_low"],
        "volume": r["volume"],
        "change_pct": round(change, 2) if change is not None else None,
        "is_stale": bool(r["is_stale"]) if r["is_stale"] is not None else None,
        "ts": r["ts"],
        "source": r["source"],
    }


@router.get("/markets")
def markets() -> dict:
    db = get_db()
    rows = db.query(
        "SELECT i.ticker,i.name,i.kind,i.tier,i.sector,"
        " q.price,q.prev_close,q.day_open,q.day_high,q.day_low,q.volume,q.ts,q.source,q.is_stale "
        "FROM instruments i LEFT JOIN quotes_latest q ON q.instrument_id=i.id "
        "ORDER BY i.ticker"
    )
    items = [_quote_row(r) for r in rows]
    items.sort(key=lambda x: (_TIER_ORDER.get(x["tier"], 9), x["ticker"]))
    groups: dict[str, list] = {}
    for it in items:
        groups.setdefault(it["tier"] or "other", []).append(it)
    return {"instruments": items, "by_tier": groups, "count": len(items)}


@router.get("/markets/{ticker}")
def market_detail(ticker: str) -> dict:
    db = get_db()
    t = norm_ticker(ticker)
    inst = db.query_one("SELECT * FROM instruments WHERE ticker=?", (t,))
    if not inst:
        raise HTTPException(404, f"unknown ticker {t}")
    q = db.query_one("SELECT * FROM quotes_latest WHERE instrument_id=?", (inst["id"],))
    quote = None
    if q:
        merged = dict(inst)
        merged.update(dict(q))
        quote = _quote_row(_Row(merged))
    # latest signals (Phase 3+)
    signals = {
        r["kind"]: r["value"]
        for r in db.query(
            "SELECT kind, value FROM signals WHERE instrument_id=? "
            "AND bar_date=(SELECT MAX(bar_date) FROM signals WHERE instrument_id=?)",
            (inst["id"], inst["id"]),
        )
    }
    # dossier (Phase 4+)
    dossier = db.query_one(
        "SELECT structured_json, markdown, updated_at FROM dossiers WHERE instrument_id=?",
        (inst["id"],),
    )
    return {
        "instrument": dict(inst),
        "quote": quote,
        "signals": signals,
        "dossier": dict(dossier) if dossier else None,
    }


@router.get("/markets/{ticker}/history")
def market_history(ticker: str, range: str = "1Y") -> dict:
    from ..connectors.history import read_daily

    t = norm_ticker(ticker)
    bars = _RANGE_BARS.get(range.upper(), 252)
    df = read_daily(t, lookback=bars, settings=get_settings())
    if df.height == 0:
        return {"ticker": t, "range": range, "bars": []}
    out = [
        {
            "date": row["date"],
            "open": row.get("open"),
            "high": row.get("high"),
            "low": row.get("low"),
            "close": row.get("close"),
            "volume": row.get("volume"),
        }
        for row in df.iter_rows(named=True)
    ]
    return {"ticker": t, "range": range, "bars": out, "count": len(out)}


class _Row(dict):
    """Adapter so _quote_row can accept a merged dict like a sqlite3.Row."""

    def __getitem__(self, k):
        return self.get(k)
