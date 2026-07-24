"""News endpoints."""

from __future__ import annotations

from fastapi import APIRouter

from ..db import get_db
from ..util import from_json, norm_ticker

router = APIRouter()


@router.get("/news")
def news(
    ticker: str | None = None,
    min_materiality: int = 0,
    category: str | None = None,
    limit: int = 60,
) -> dict:
    db = get_db()
    where, params = ["(materiality IS NULL OR materiality>=?)"], [min_materiality]
    if ticker:
        where.append("tickers_json LIKE ?")
        params.append(f'%"{norm_ticker(ticker)}"%')
    if category:
        where.append("category=?")
        params.append(category)
    clause = "WHERE " + " AND ".join(where)
    params.append(min(limit, 300))
    rows = db.query(
        f"SELECT id,source,url,title,summary,published_at,tickers_json,materiality,category,"
        f"cluster_id FROM news_items {clause} ORDER BY published_at DESC LIMIT ?",
        params,
    )
    out = []
    for r in rows:
        d = dict(r)
        d["tickers"] = from_json(r["tickers_json"], [])
        d.pop("tickers_json", None)
        out.append(d)
    return {"news": out, "count": len(out)}


@router.get("/news/clusters")
def clusters(limit: int = 40) -> dict:
    db = get_db()
    rows = db.query(
        "SELECT c.id, c.title, c.item_count, c.first_seen, c.last_seen, "
        "(SELECT AVG(materiality) FROM news_items WHERE cluster_id=c.id) avg_materiality "
        "FROM news_clusters c WHERE c.item_count>1 ORDER BY c.last_seen DESC LIMIT ?",
        (limit,),
    )
    return {"clusters": [dict(r) for r in rows]}
