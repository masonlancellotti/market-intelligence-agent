"""News dedup + clustering pipeline.

* URL canonicalization (strip trackers) — the DB's UNIQUE(url) rejects exact dups.
* Cross-source clustering: embed title+summary, assign to the nearest recent cluster if
  cosine ≥ threshold, else open a new cluster. "Same story across 3 feeds → 1 cluster."
* Heuristic ticker tagging against the watchlist as a pre-triage signal.
"""

from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from ..config import get_settings
from ..util import norm_ticker, to_json, utcnow_iso
from .embeddings import cosine, embed_one, from_blob, to_blob

_TRACKER_PREFIXES = ("utm_", "utm", "pk_", "mc_")
_TRACKER_KEYS = {"fbclid", "gclid", "igshid", "ref", "cmpid", "ns_source", "guccounter", "spm"}
_CLUSTER_THRESHOLD = 0.82
_CLUSTER_WINDOW_DAYS = 3


def canonical_url(url: str) -> str:
    try:
        parts = urlsplit(url.strip())
    except (ValueError, AttributeError):
        return url
    query = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=False)
        if k.lower() not in _TRACKER_KEYS and not k.lower().startswith(_TRACKER_PREFIXES)
    ]
    host = parts.netloc.lower()
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme or "https", host, path, urlencode(query), ""))


def normalize_title(title: str) -> str:
    t = re.sub(r"\s+", " ", (title or "").lower()).strip()
    return re.sub(r"[^a-z0-9 ]", "", t)


def extract_tickers(text: str, universe: list[str]) -> list[str]:
    """Heuristic: match $TICKER / (TICKER) / bare uppercase tokens against the universe."""
    if not text:
        return []
    up = text.upper()
    hits = []
    for t in universe:
        base = norm_ticker(t).split("-")[0]  # BTC-USD -> BTC
        if len(base) < 2:
            continue
        if re.search(rf"(?<![A-Z]){re.escape(base)}(?![A-Z])", up):
            hits.append(norm_ticker(t))
    return sorted(set(hits))


def _recent_cluster_reps(db, window_days: int):
    from datetime import timedelta

    from ..util import iso, utcnow

    cutoff = iso(utcnow() - timedelta(days=window_days))
    rows = db.query(
        "SELECT c.id AS cluster_id, n.embedding AS emb "
        "FROM news_clusters c JOIN news_items n ON n.id=c.rep_item_id "
        "WHERE c.last_seen>=? ORDER BY c.last_seen DESC LIMIT 400",
        (cutoff,),
    )
    return [(r["cluster_id"], from_blob(r["emb"])) for r in rows if r["emb"] is not None]


def _assign_cluster(db, title: str, emb, item_id_placeholder=None) -> tuple[int, bool]:
    """Return (cluster_id, is_new). Compares to recent cluster representatives."""
    best_id, best_cos = None, 0.0
    for cid, rep in _recent_cluster_reps(db, _CLUSTER_WINDOW_DAYS):
        c = cosine(emb, rep)
        if c > best_cos:
            best_id, best_cos = cid, c
    now = utcnow_iso()
    if best_id is not None and best_cos >= _CLUSTER_THRESHOLD:
        db.execute(
            "UPDATE news_clusters SET last_seen=?, item_count=item_count+1 WHERE id=?",
            (now, best_id),
        )
        return best_id, False
    cid = db.execute(
        "INSERT INTO news_clusters(rep_item_id,title,first_seen,last_seen,item_count) "
        "VALUES(NULL,?,?,?,1)",
        (title[:200], now, now),
    )
    return cid, True


def upsert_news_item(item: dict, settings=None) -> dict:
    """Insert one news item with dedup + clustering. item keys: source,url,title,summary,
    published_at,tickers(optional list),raw_text(optional),category(optional)."""
    from ..db import get_db

    s = settings or get_settings()
    db = get_db(s)
    curl = canonical_url(item.get("url", ""))
    if not curl or not item.get("title"):
        return {"status": "skipped"}

    existing = db.query_one("SELECT id FROM news_items WHERE url=?", (curl,))
    if existing:
        return {"status": "duplicate", "id": existing["id"]}

    title = item["title"]
    summary = item.get("summary") or ""
    emb = embed_one(f"{title}. {summary}")

    universe = s.config.watchlist.all()
    tickers = item.get("tickers") or extract_tickers(f"{title} {summary}", universe)

    cluster_id, is_new = _assign_cluster(db, title, emb)
    now = utcnow_iso()
    item_id = db.execute(
        "INSERT INTO news_items"
        "(source,url,title,summary,published_at,fetched_at,tickers_json,raw_text,cluster_id,"
        " embedding,category) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (
            item.get("source", ""),
            curl,
            title,
            summary,
            item.get("published_at") or now,
            now,
            to_json(tickers),
            item.get("raw_text"),
            cluster_id,
            to_blob(emb),
            item.get("category"),
        ),
    )
    if is_new:
        db.execute("UPDATE news_clusters SET rep_item_id=? WHERE id=?", (item_id, cluster_id))
    return {"status": "inserted", "id": item_id, "cluster_id": cluster_id, "new_cluster": is_new}


def ingest_news(items: list[dict], settings=None) -> dict:
    inserted = dups = 0
    new_clusters = 0
    for it in items:
        r = upsert_news_item(it, settings)
        if r["status"] == "inserted":
            inserted += 1
            new_clusters += 1 if r.get("new_cluster") else 0
        elif r["status"] == "duplicate":
            dups += 1
    return {"inserted": inserted, "duplicates": dups, "new_clusters": new_clusters}
