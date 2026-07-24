"""Filings endpoints: stream, diffs, insider board."""

from __future__ import annotations

from fastapi import APIRouter

from ..db import get_db
from ..util import from_json, norm_ticker

router = APIRouter()


@router.get("/filings")
def filings(ticker: str | None = None, form: str | None = None, limit: int = 100) -> dict:
    db = get_db()
    where, params = [], []
    if ticker:
        where.append("ticker=?")
        params.append(norm_ticker(ticker))
    if form:
        where.append("form LIKE ?")
        params.append(f"{form}%")
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    params.append(min(limit, 500))
    rows = db.query(
        f"SELECT id,accession,cik,ticker,form,filed_at,url,items_json,summary,materiality "
        f"FROM filings {clause} ORDER BY filed_at DESC, id DESC LIMIT ?",
        params,
    )
    out = []
    for r in rows:
        d = dict(r)
        d["items"] = from_json(r["items_json"], [])
        out.append(d)
    return {"filings": out, "count": len(out)}


@router.get("/filings/diffs")
def diffs(ticker: str | None = None, limit: int = 50) -> dict:
    db = get_db()
    if ticker:
        rows = db.query(
            "SELECT * FROM filing_diffs WHERE ticker=? ORDER BY created_at DESC LIMIT ?",
            (norm_ticker(ticker), limit),
        )
    else:
        rows = db.query("SELECT * FROM filing_diffs ORDER BY created_at DESC LIMIT ?", (limit,))
    return {"diffs": [dict(r) for r in rows]}


@router.get("/filings/insiders")
def insiders(ticker: str | None = None, limit: int = 100) -> dict:
    db = get_db()
    where, params = [], []
    if ticker:
        where.append("ticker=?")
        params.append(norm_ticker(ticker))
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    params.append(min(limit, 500))
    rows = db.query(
        f"SELECT id,ticker,insider_name,role,action,shares,price,value_usd,traded_at,cluster_flag "
        f"FROM insider_trades {clause} ORDER BY traded_at DESC, id DESC LIMIT ?",
        params,
    )
    clusters = db.query(
        "SELECT ticker, COUNT(*) n, SUM(value_usd) total FROM insider_trades "
        "WHERE cluster_flag=1 GROUP BY ticker ORDER BY n DESC"
    )
    return {"insiders": [dict(r) for r in rows], "clusters": [dict(r) for r in clusters]}
