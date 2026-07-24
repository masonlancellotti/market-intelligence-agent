"""Predictions, auto-resolution, Brier scores, calibration.

Every memo logs ≥2 falsifiable predictions. Price-checkable ones auto-resolve from bar
data; others get a resolution prompt at horizon. Brier scores accumulate into a
calibration curve (predicted vs realised frequency) — the feature that compounds.
"""

from __future__ import annotations

import re

from loguru import logger

from ..config import Settings, get_settings
from ..util import norm_ticker, today_iso, utcnow_iso

_RULE = re.compile(r"([\^\w\-\.=]+)\s*(>=|<=|>|<|==)\s*([\d.]+)")


def _price(db, ticker: str) -> float | None:
    row = db.query_one(
        "SELECT q.price FROM quotes_latest q JOIN instruments i ON i.id=q.instrument_id WHERE i.ticker=?",
        (norm_ticker(ticker),),
    )
    return row["price"] if row else None


def _eval_rule(db, rule: str) -> bool | None:
    m = _RULE.search(rule or "")
    if not m:
        return None
    ticker, op, val = m.group(1), m.group(2), float(m.group(3))
    price = _price(db, ticker)
    if price is None:
        return None
    return {
        ">=": price >= val,
        "<=": price <= val,
        ">": price > val,
        "<": price < val,
        "==": abs(price - val) < 1e-6,
    }[op]


def resolve_prediction(pred_id: int, outcome: bool, settings: Settings | None = None) -> None:
    from ..db import get_db

    db = get_db(settings)
    row = db.query_one("SELECT probability FROM memo_predictions WHERE id=?", (pred_id,))
    if not row:
        return
    p = row["probability"]
    brier = round((p - (1.0 if outcome else 0.0)) ** 2, 4)
    db.execute(
        "UPDATE memo_predictions SET resolution=?, resolved_at=?, brier=? WHERE id=?",
        ("true" if outcome else "false", utcnow_iso(), brier, pred_id),
    )


def resolve_due(settings: Settings | None = None) -> dict:
    s = settings or get_settings()
    from ..db import get_db

    db = get_db(s)
    today = today_iso(s.tz)
    rows = db.query(
        "SELECT id, memo_id, claim, kind, resolve_rule FROM memo_predictions "
        "WHERE resolution IS NULL AND horizon_date IS NOT NULL AND horizon_date<=?",
        (today,),
    )
    auto = prompted = 0
    for r in rows:
        if r["kind"] == "price" and r["resolve_rule"]:
            outcome = _eval_rule(db, r["resolve_rule"])
            if outcome is not None:
                resolve_prediction(r["id"], outcome, s)
                auto += 1
                continue
        _prompt_resolution(s, r)
        prompted += 1
    if auto or prompted:
        logger.info("predictions: {} auto-resolved, {} prompted", auto, prompted)
    return {"auto_resolved": auto, "prompted": prompted}


def _prompt_resolution(s: Settings, pred) -> None:
    from ..notify import Notification, get_router

    get_router(s).send(
        Notification(
            priority="P1",
            title="Resolve prediction",
            body=f"Did this resolve true? “{pred['claim'][:120]}”",
            dedupe_key=f"resolve:{pred['id']}",
            cooldown_s=86400,
            click_path="/conviction",
        )
    )


def brier_summary(settings: Settings | None = None) -> dict:
    from ..db import get_db

    db = get_db(settings)
    resolved = db.query(
        "SELECT probability, resolution, brier FROM memo_predictions WHERE resolution IS NOT NULL"
    )
    n = len(resolved)
    if n == 0:
        return {"n": 0, "mean_brier": None, "calibration": [], "hit_rate": None}
    mean_brier = round(sum(r["brier"] for r in resolved) / n, 4)
    hits = sum(1 for r in resolved if (r["resolution"] == "true") == (r["probability"] >= 0.5))
    # calibration buckets
    buckets = [(0, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 1.01)]
    calib = []
    for lo, hi in buckets:
        b = [r for r in resolved if lo <= r["probability"] < hi]
        if b:
            predicted = sum(r["probability"] for r in b) / len(b)
            realized = sum(1 for r in b if r["resolution"] == "true") / len(b)
            calib.append(
                {
                    "bucket": f"{int(lo * 100)}-{int(hi * 100)}%",
                    "n": len(b),
                    "predicted": round(predicted, 3),
                    "realized": round(realized, 3),
                }
            )
    return {"n": n, "mean_brier": mean_brier, "hit_rate": round(hits / n, 3), "calibration": calib}
