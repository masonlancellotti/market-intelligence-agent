"""Rule-backtest harness — the Calibration Lab engine (V2).

Loads a small set of transparent, ex-ante systematic rules from ``config/rules.yaml``,
evaluates each over the backfilled keyless regime history, resolves every firing from the
realised SPY forward return, and Brier-scores it. Results are stored in ``rule_predictions``
with ``source='rule_backtest'`` — kept strictly separate from live memo predictions.

This is the honest answer to "show me your calibration": real computed scores over real
history for rules whose parameters are visible in config. Everything is RETROSPECTIVE.
"""

from __future__ import annotations

import numpy as np
import yaml
from loguru import logger

from ..config import Settings, get_settings
from ..signals.regime_history import build_frames, history_rows
from ..signals.rules import safe_eval
from ..util import utcnow_iso

HORIZON_KEYS = {5: "fwd_5d", 20: "fwd_20d"}


def load_rules(settings: Settings | None = None) -> list[dict]:
    s = settings or get_settings()
    path = s.config_dir / "rules.yaml"
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data.get("rules", []) if isinstance(data, dict) else (data or [])


def _feature_frame(settings: Settings | None = None) -> list[dict]:
    """Per-day feature rows: regime + breadth (from regime_history) augmented with
    SPY RSI(14) and VIX 1y percentile computed from the same keyless Parquet history."""
    s = settings or get_settings()
    rows = history_rows(s)
    if not rows:
        return []
    from ..signals.indicators import rsi

    dates, closes = build_frames(["SPY", "^VIX"], s)
    idx = {d: k for k, d in enumerate(dates)}
    spy = closes.get("SPY")
    vix = closes.get("^VIX")
    rsi_arr = rsi(spy, 14) if spy is not None else None

    def vix_pct(i: int) -> float | None:
        if vix is None or i < 60 or np.isnan(vix[i]):
            return None
        w = vix[max(0, i - 251) : i + 1]
        w = w[~np.isnan(w)]
        if len(w) < 60:
            return None
        return float((w <= vix[i]).mean() * 100)

    frame = []
    for r in rows:
        i = idx.get(r["date"])
        spy_rsi = (
            float(rsi_arr[i])
            if rsi_arr is not None and i is not None and not np.isnan(rsi_arr[i])
            else None
        )
        frame.append(
            {
                "date": r["date"],
                "regime": r["score"],
                "regime_bucket": r["bucket"],
                "breadth": (r.get("components") or {}).get("breadth"),
                "spy_rsi": spy_rsi,
                "vix_pct": vix_pct(i) if i is not None else None,
                "fwd_5d": r["fwd_5d"],
                "fwd_20d": r["fwd_20d"],
            }
        )
    return frame


def backtest_rules(settings: Settings | None = None) -> dict:
    """Evaluate every rule over history, resolve + Brier-score, persist to rule_predictions."""
    s = settings or get_settings()
    from ..db import get_db

    db = get_db(s)
    db.migrate()
    rules = load_rules(s)
    frame = _feature_frame(s)
    if not frame:
        return {
            "ok": False,
            "error": "no regime history — run backfill-regime first",
            "resolved": 0,
        }

    now = utcnow_iso()
    from ..util import to_json

    db.execute("DELETE FROM rule_predictions WHERE source='rule_backtest'")
    records, per_rule_counts = [], {}
    for rule in rules:
        rid = rule["id"]
        horizon = int(rule.get("horizon", 5))
        fkey = HORIZON_KEYS.get(horizon, "fwd_5d")
        prob = float(rule["probability"])
        fired = 0
        for feat in frame:
            fwd = feat.get(fkey)
            if fwd is None:
                continue  # horizon does not resolve for this day
            if not safe_eval(rule["when"], feat):
                continue
            outcome = 1 if safe_eval(rule["predict"], {"spy_return": fwd}) else 0
            brier = round((prob - outcome) ** 2, 5)
            records.append(
                (
                    rid,
                    "rule_backtest",
                    feat["date"],
                    None,
                    horizon,
                    prob,
                    outcome,
                    brier,
                    to_json({"spy_return": round(fwd, 5), "when": rule["when"]}),
                    now,
                )
            )
            fired += 1
        per_rule_counts[rid] = fired

    db.executemany(
        "INSERT INTO rule_predictions"
        "(rule_id,source,as_of_date,horizon_date,horizon_days,probability,outcome,brier,detail_json,created_at) "
        "VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(rule_id,as_of_date,source) DO UPDATE SET "
        "probability=excluded.probability,outcome=excluded.outcome,brier=excluded.brier,"
        "detail_json=excluded.detail_json",
        records,
    )
    total = len(records)
    logger.info("backtest-rules: {} resolved predictions across {} rules", total, len(rules))
    return {"ok": True, "resolved": total, "by_rule": per_rule_counts, "rules": len(rules)}


# -- summary / reliability ------------------------------------------------------
def _reliability(preds: list[dict], bins=(0.0, 0.35, 0.45, 0.55, 0.65, 1.01)) -> list[dict]:
    out = []
    for lo, hi in zip(bins[:-1], bins[1:], strict=False):
        b = [p for p in preds if lo <= p["probability"] < hi]
        if not b:
            continue
        out.append(
            {
                "bucket": f"{int(lo * 100)}-{int(min(hi, 1.0) * 100)}%",
                "n": len(b),
                "predicted": round(sum(p["probability"] for p in b) / len(b), 3),
                "realized": round(sum(p["outcome"] for p in b) / len(b), 3),
            }
        )
    return out


def _skill(preds: list[dict]) -> dict:
    n = len(preds)
    if n == 0:
        return {"n": 0}
    mean_brier = sum(p["brier"] for p in preds) / n
    base_rate = sum(p["outcome"] for p in preds) / n
    base_brier = base_rate * (1 - base_rate)  # climatology (always-predict-base-rate) Brier
    skill = 1 - mean_brier / base_brier if base_brier > 1e-9 else None
    return {
        "n": n,
        "mean_prob": round(sum(p["probability"] for p in preds) / n, 3),
        "mean_brier": round(mean_brier, 4),
        "base_rate": round(base_rate, 3),
        "base_brier": round(base_brier, 4),
        "skill_score": round(skill, 3) if skill is not None else None,
    }


def rule_backtest_summary(settings: Settings | None = None) -> dict:
    from ..db import get_db
    from ..util import from_json

    db = get_db(settings)
    rows = db.query(
        "SELECT rule_id, probability, outcome, brier, horizon_days FROM rule_predictions "
        "WHERE source='rule_backtest'"
    )
    preds = [dict(r) for r in rows]
    rules_meta = {r["id"]: r for r in load_rules(settings)}

    per_rule = []
    for rid in sorted({p["rule_id"] for p in preds}):
        rp = [p for p in preds if p["rule_id"] == rid]
        meta = rules_meta.get(rid, {})
        per_rule.append(
            {
                "rule_id": rid,
                "when": meta.get("when"),
                "predict": meta.get("predict"),
                "horizon": meta.get("horizon"),
                "rationale": meta.get("rationale"),
                **_skill(rp),
                "reliability": _reliability(rp),
            }
        )
    _ = from_json  # keep import symmetry; detail_json parsed on demand elsewhere
    return {
        "pooled": {**_skill(preds), "reliability": _reliability(preds)},
        "by_rule": per_rule,
        "n_rules": len(per_rule),
        "label": "Systematic rule backtest (RETROSPECTIVE). Brier-scored over keyless "
        "historical data; not live forecasts, not trading advice.",
    }
