"""Brief data assembly + evidence registry.

Builds the structured data block a brief is composed from. Every fact registers an
evidence row keyed by id (``b:NVDA`` bar, ``n:123`` news, ``f:88`` filing, ``m:DGS10``
macro); the composer cites these ids and the fact-checker validates them. Numbers come
ONLY from here — never from model memory.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..config import Settings, get_settings, load_portfolio
from ..util import from_json, norm_ticker, pct, utcnow_iso


@dataclass
class Evidence:
    """Registry of citable facts for one brief."""

    items: dict[str, dict] = field(default_factory=dict)

    def add(self, eid: str, *, value: Any, label: str, source: str, kind: str) -> str:
        self.items[eid] = {"value": value, "label": label, "source": source, "kind": kind}
        return f"[{eid}]"

    def as_dict(self) -> dict:
        return self.items


def _quote(db, ticker: str) -> dict | None:
    return db.query_one(
        "SELECT q.*, i.ticker FROM quotes_latest q JOIN instruments i ON i.id=q.instrument_id "
        "WHERE i.ticker=?",
        (norm_ticker(ticker),),
    )


def _sig(db, ticker: str) -> dict:
    row = db.query_one("SELECT id FROM instruments WHERE ticker=?", (norm_ticker(ticker),))
    if not row:
        return {}
    return {
        r["kind"]: r["value"]
        for r in db.query(
            "SELECT kind,value FROM signals WHERE instrument_id=? "
            "AND bar_date=(SELECT MAX(bar_date) FROM signals WHERE instrument_id=? AND kind='rsi14')",
            (row["id"], row["id"]),
        )
    }


def _header(db, ev: Evidence) -> dict:
    regime = db.get_setting("regime.latest", {}) or {}
    out: dict[str, Any] = {"regime": regime}
    for key, ticker in [
        ("es", "ES=F"),
        ("nq", "NQ=F"),
        ("ten_y", "^TNX"),
        ("btc", "BTC-USD"),
        ("vix", "^VIX"),
    ]:
        q = _quote(db, ticker)
        if q and q["price"] is not None:
            ev.add(
                f"b:{ticker}", value=q["price"], label=ticker, source=q["source"] or "", kind="bar"
            )
            out[key] = {
                "ticker": ticker,
                "price": q["price"],
                "change_pct": pct(q["price"], q["prev_close"]),
            }
    return out


def _portfolio(db, s: Settings, ev: Evidence) -> list[dict]:
    port = load_portfolio(s)
    out = []
    for acct in port.get("accounts", []):
        for pos in acct.get("positions", []):
            ticker = norm_ticker(pos.get("ticker", ""))
            q = _quote(db, ticker)
            if not q:
                continue
            ev.add(
                f"b:{ticker}", value=q["price"], label=ticker, source=q["source"] or "", kind="bar"
            )
            row = {
                "ticker": ticker,
                "qty": pos.get("qty"),
                "cost_basis": pos.get("cost_basis"),
                "price": q["price"],
                "change_pct": pct(q["price"], q["prev_close"]),
                "pl_pct": pct(q["price"], pos.get("cost_basis")) if pos.get("cost_basis") else None,
            }
            memo_id = pos.get("memo_id")
            if memo_id:
                memo = db.query_one(
                    "SELECT invalidation_level, direction FROM memos WHERE id=?", (memo_id,)
                )
                if memo and memo["invalidation_level"]:
                    row["invalidation_level"] = memo["invalidation_level"]
                    row["dist_to_invalidation_pct"] = pct(q["price"], memo["invalidation_level"])
            # overnight news flag
            nrow = db.query_one(
                "SELECT COUNT(*) n FROM news_items WHERE tickers_json LIKE ? AND materiality>=3 "
                "AND published_at>=datetime('now','-1 day')",
                (f'%"{ticker}"%',),
            )
            row["overnight_news"] = nrow["n"] if nrow else 0
            out.append(row)
    return out


def _movers(db, s: Settings, ev: Evidence, limit: int = 6) -> list[dict]:
    rows = db.query(
        "SELECT i.ticker, q.price, q.prev_close FROM instruments i "
        "JOIN quotes_latest q ON q.instrument_id=i.id "
        "WHERE i.tier IN ('holding','active') AND q.price IS NOT NULL AND q.prev_close IS NOT NULL"
    )
    movers = []
    for r in rows:
        chg = pct(r["price"], r["prev_close"])
        if chg is None:
            continue
        sig = _sig(db, r["ticker"])
        ev.add(f"b:{r['ticker']}", value=r["price"], label=r["ticker"], source="bar", kind="bar")
        movers.append(
            {
                "ticker": r["ticker"],
                "price": r["price"],
                "change_pct": round(chg, 2),
                "rsi14": sig.get("rsi14"),
                "atr_pct": sig.get("atr_pct"),
                "volume_z": sig.get("volume_z"),
                "donchian20_upper": sig.get("donchian20_upper"),
                "donchian20_lower": sig.get("donchian20_lower"),
                "pct_from_52w_high": sig.get("pct_from_52w_high"),
            }
        )
    movers.sort(key=lambda x: -abs(x["change_pct"]))
    return movers[:limit]


def _calendar(db, limit: int = 6) -> list[dict]:
    rows = db.query(
        "SELECT name, country, scheduled_at, importance, consensus, previous FROM econ_events "
        "WHERE scheduled_at>=? ORDER BY scheduled_at LIMIT ?",
        (utcnow_iso(), limit),
    )
    return [dict(r) for r in rows]


def _macro(db, ev: Evidence) -> dict:
    out: dict[str, Any] = {}
    for sid in ("DGS10", "DGS2", "T10Y2Y", "BAMLH0A0HYM2", "CPIAUCSL"):
        row = db.query_one(
            "SELECT value, date FROM macro_points WHERE series_id=? ORDER BY date DESC LIMIT 1",
            (sid,),
        )
        if row:
            ev.add(f"m:{sid}", value=row["value"], label=sid, source="fred", kind="macro")
            out[sid] = {"value": row["value"], "date": row["date"]}
    fed = db.query(
        "SELECT question, yes_prob, prev_prob FROM prediction_markets WHERE category='fed' "
        "AND yes_prob IS NOT NULL ORDER BY volume DESC LIMIT 3"
    )
    out["fed_odds"] = [dict(r) for r in fed]
    out["cnn_fng"] = db.get_setting("sentiment.cnn_fng")
    out["crypto_fng"] = db.get_setting("crypto.fng")
    return out


def _filings(db, ev: Evidence, limit: int = 6) -> list[dict]:
    rows = db.query(
        "SELECT id, ticker, form, filed_at, items_json, materiality FROM filings "
        "WHERE materiality>=3 ORDER BY filed_at DESC, id DESC LIMIT ?",
        (limit,),
    )
    out = []
    for r in rows:
        ev.add(
            f"f:{r['id']}",
            value=r["materiality"],
            label=f"{r['ticker']} {r['form']}",
            source="edgar",
            kind="filing",
        )
        d = dict(r)
        d["items"] = from_json(r["items_json"], [])
        out.append(d)
    return out


def _top_news(db, ev: Evidence, limit: int = 8) -> list[dict]:
    rows = db.query(
        "SELECT id, source, title, tickers_json, materiality, category, published_at "
        "FROM news_items WHERE materiality>=3 ORDER BY materiality DESC, published_at DESC LIMIT ?",
        (limit,),
    )
    out = []
    for r in rows:
        ev.add(
            f"n:{r['id']}",
            value=r["materiality"],
            label=r["title"][:80],
            source=r["source"],
            kind="news",
        )
        d = dict(r)
        d["tickers"] = from_json(r["tickers_json"], [])
        out.append(d)
    return out


def _data_gaps(db) -> list[dict]:
    rows = db.query(
        "SELECT connector, status, last_error, items_24h FROM connector_health "
        "WHERE status IN ('amber','red','disabled') ORDER BY status DESC"
    )
    return [dict(r) for r in rows]


def build_context(kind: str, settings: Settings | None = None) -> dict:
    s = settings or get_settings()
    from ..db import get_db

    db = get_db(s)
    ev = Evidence()
    ctx = {
        "kind": kind,
        "generated_at": utcnow_iso(),
        "header": _header(db, ev),
        "portfolio": _portfolio(db, s, ev),
        "movers": _movers(db, s, ev),
        "calendar": _calendar(db),
        "macro": _macro(db, ev),
        "filings": _filings(db, ev),
        "news_top": _top_news(db, ev),
        "data_gaps": _data_gaps(db),
        "evidence": ev.as_dict(),
    }
    return ctx
