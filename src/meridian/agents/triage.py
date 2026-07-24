"""Triage agent — Haiku, high-volume, cheap.

For each new news item: relevance, ticker tagging, materiality 0–5, category, one-line
gist. Batched 20-up per LLM call. Degrades to a transparent heuristic when no key
or budget — the system keeps triaging, just less smartly, and logs a ``degraded`` run.
"""

from __future__ import annotations

from loguru import logger

from ..config import Settings, get_settings
from ..util import from_json, norm_ticker, to_json, utcnow_iso
from .runner import BudgetExceeded, LLMUnavailable, llm_available, log_degraded, run_structured
from .schemas import TRIAGE_SCHEMA

BATCH = 20

_HIGH_SOURCES = {
    "reuters",
    "bloomberg",
    "wsj",
    "financial times",
    "ft",
    "cnbc",
    "sec",
    "fed",
    "federal reserve",
    "the wall street journal",
    "barron's",
    "associated press",
}
_MATERIAL_KW = {
    "earnings": 2,
    "guidance": 2,
    "downgrade": 2,
    "upgrade": 2,
    "acquisition": 3,
    "merger": 3,
    "lawsuit": 2,
    "sec ": 2,
    "recall": 2,
    "bankruptcy": 4,
    "layoff": 2,
    "beats": 2,
    "misses": 2,
    "fda": 2,
    "resign": 3,
    "ceo": 2,
    "cuts": 1,
    "raises": 1,
    "probe": 2,
    "fraud": 3,
    "default": 3,
}
_CATEGORY_KW = [
    ("earnings", ["earnings", "guidance", "revenue", "eps", "quarter"]),
    ("macro", ["fed", "inflation", "cpi", "rates", "jobs", "gdp", "treasury", "powell"]),
    ("ma", ["acquisition", "merger", "buyout", "takeover", "acquire"]),
    ("regulatory", ["sec", "lawsuit", "antitrust", "fine", "probe", "investigation", "fraud"]),
    ("management", ["ceo", "cfo", "resign", "appoint", "departure"]),
    ("product", ["launch", "unveil", "recall", "fda", "approval"]),
]


def triage_pending(limit: int = 200, settings: Settings | None = None) -> dict:
    from ..db import get_db

    s = settings or get_settings()
    db = get_db(s)
    rows = db.query(
        "SELECT id,source,title,summary,tickers_json FROM news_items "
        "WHERE triaged_at IS NULL ORDER BY published_at DESC LIMIT ?",
        (limit,),
    )
    if not rows:
        return {"triaged": 0, "mode": "none"}

    use_llm = llm_available(s)
    total_cost = 0.0
    triaged = 0
    mode = "llm" if use_llm else "heuristic"

    if use_llm:
        try:
            for i in range(0, len(rows), BATCH):
                batch = rows[i : i + BATCH]
                results, cost = _llm_batch(batch, s)
                total_cost += cost
                triaged += _apply(db, batch, results)
        except (LLMUnavailable, BudgetExceeded) as e:
            logger.info("triage degrading to heuristic: {}", e)
            mode = "heuristic"
            use_llm = False

    if not use_llm:
        for r in rows:
            res = _heuristic(r)
            triaged += _apply(db, [r], {r["id"]: res})
        log_degraded("triage", task_ref=f"{triaged} items")

    return {"triaged": triaged, "mode": mode, "cost_usd": round(total_cost, 5)}


def _apply(db, rows, results: dict) -> int:
    n = 0
    for r in rows:
        res = results.get(r["id"])
        if not res:
            continue
        db.execute(
            "UPDATE news_items SET materiality=?, category=?, triage_json=?, triaged_at=?, "
            "tickers_json=? WHERE id=?",
            (
                int(res.get("materiality", 1)),
                res.get("category", "general"),
                to_json(res),
                utcnow_iso(),
                to_json(res.get("tickers") or from_json(r["tickers_json"], [])),
                r["id"],
            ),
        )
        n += 1
    return n


def _llm_batch(batch, s: Settings):
    universe = ", ".join(s.config.watchlist.all())
    system = (
        "You are the triage analyst for a market-research desk. For each news item, decide "
        "relevance to the watchlist, tag tickers, score materiality 0-5 (0 irrelevant, 5 "
        "market-moving), classify category, and write a one-line neutral gist. Numbers only "
        f"from the item text. Watchlist: {universe}."
    )
    lines = [
        f"[{r['id']}] ({r['source']}) {r['title']} :: {(r['summary'] or '')[:200]}" for r in batch
    ]
    user = "Triage these items:\n" + "\n".join(lines)
    obj, cost = run_structured(
        "triage",
        system,
        user,
        TRIAGE_SCHEMA,
        model=s.config.models.triage,
        max_tokens=2000,
        task_ref=f"batch:{len(batch)}",
        settings=s,
    )
    results = {}
    for item in obj.get("results", []):
        results[item.get("id")] = item
    return results, cost


def _heuristic(row) -> dict:
    title = (row["title"] or "").lower()
    summary = (row["summary"] or "").lower()
    text = f"{title} {summary}"
    source = (row["source"] or "").lower()

    materiality = 1
    if any(hs in source for hs in _HIGH_SOURCES):
        materiality += 2
    for kw, w in _MATERIAL_KW.items():
        if kw in text:
            materiality = max(materiality, 1 + w)
    tickers = from_json(row["tickers_json"], [])
    if tickers:
        materiality += 1
    materiality = max(0, min(5, materiality))

    category = "general"
    for cat, kws in _CATEGORY_KW:
        if any(k in text for k in kws):
            category = cat
            break

    return {
        "id": row["id"],
        "relevant": materiality >= 2 or bool(tickers),
        "tickers": [norm_ticker(t) for t in tickers],
        "materiality": materiality,
        "category": category,
        "gist": (row["title"] or "")[:160],
    }
