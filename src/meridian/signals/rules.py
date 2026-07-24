"""Alert rule engine.

Evaluates the declarative rules in ``config/alerts.yaml`` on a q1min loop against a named
signal-variable snapshot, using a restricted ``eval`` (trusted config, no builtins). Fires
through the notification router (dedupe/cooldown/quiet-hours) and records every alert to the
``alerts`` table for the dashboard feed.

Division of labour: price/signal rules fire *here*; genuinely event-driven alerts (new 8-K,
insider cluster, regime transition, macro surprise) fire at their source — their event flags
default False here so they don't double-fire, and the router dedupes regardless.
"""

from __future__ import annotations

from datetime import timedelta

from loguru import logger

from ..config import Settings, get_settings, load_alert_rules, load_portfolio
from ..util import iso, norm_ticker, today_iso, utcnow, utcnow_iso

_ALLOWED = {"abs": abs, "min": min, "max": max, "round": round, "len": len}
_NOISE_LIMIT = 8  # >8 alerts/hour → collapse P2s into a digest


def safe_eval(expr: str, variables: dict) -> bool:
    try:
        return bool(eval(expr, {"__builtins__": {}}, {**_ALLOWED, **variables}))  # noqa: S307
    except Exception:  # noqa: BLE001
        return False


class SafeDict(dict):
    def __missing__(self, key):
        return "n/a"


def _fmt(template: str, variables: dict) -> str:
    try:
        return template.format_map(SafeDict(variables))
    except (ValueError, KeyError):
        return template


# --------------------------------------------------------------------------------------
# Variable snapshots
# --------------------------------------------------------------------------------------
def _macro_vars(db, s: Settings) -> dict:
    v: dict = {
        "new_8k": False,
        "item_material": False,
        "item_codes": "",
        "insider_cluster_buy": False,
        "insider_count": 0,
        "econ_high_importance": False,
        "surprise_score": 0.0,
        "econ_name": "",
        "econ_actual": "",
        "econ_consensus": "",
        "regime_bucket_changed": False,
    }
    # VIX
    vix = db.query_one(
        "SELECT price, prev_close FROM quotes_latest q JOIN instruments i ON i.id=q.instrument_id "
        "WHERE i.ticker='^VIX'"
    )
    if vix and vix["price"]:
        v["vix"] = vix["price"]
        pc = vix["prev_close"] or vix["price"]
        v["vix_change_pct"] = (vix["price"] / pc - 1.0) * 100.0 if pc else 0.0
        v["vix_crossed_25"] = bool(pc < 25 <= vix["price"])
    else:
        v.update({"vix": 0.0, "vix_change_pct": 0.0, "vix_crossed_25": False})
    # regime
    regime = db.get_setting("regime.latest", {}) or {}
    v["regime_bucket"] = regime.get("bucket", "unknown")
    v["regime_score"] = regime.get("score", 50)
    v["regime_prev_bucket"] = regime.get("prev_bucket", "unknown")
    # fed odds swing (top fed market by volume)
    fed = db.query_one(
        "SELECT yes_prob, prev_prob FROM prediction_markets WHERE category='fed' "
        "AND yes_prob IS NOT NULL ORDER BY volume DESC LIMIT 1"
    )
    if fed and fed["yes_prob"] is not None and fed["prev_prob"] is not None:
        v["fed_odds_yes"] = round(fed["yes_prob"] * 100, 1)
        v["fed_odds_move_pts"] = abs(fed["yes_prob"] - fed["prev_prob"]) * 100
    else:
        v["fed_odds_yes"] = 0.0
        v["fed_odds_move_pts"] = 0.0
    return v


def _sig_map(db, iid: int) -> dict:
    rows = db.query(
        "SELECT kind, value FROM signals WHERE instrument_id=? AND "
        "bar_date=(SELECT MAX(bar_date) FROM signals WHERE instrument_id=? AND kind='rsi14')",
        (iid, iid),
    )
    return {r["kind"]: r["value"] for r in rows}


def _instrument_vars(db, inst) -> dict:
    q = db.query_one("SELECT * FROM quotes_latest WHERE instrument_id=?", (inst["id"],))
    sig = _sig_map(db, inst["id"])
    price = q["price"] if q else None
    prev = q["prev_close"] if q else None
    day_change = (price / prev - 1.0) * 100.0 if price and prev else 0.0
    gap = sig.get("gap_pct")
    if gap is None and q and q["day_open"] and prev:
        gap = (q["day_open"] / prev - 1.0) * 100.0
    high52 = sig.get("high_52w")
    cross = int(sig.get("cross_50_200") or 0)
    return {
        "ticker": inst["ticker"],
        "price": round(price, 2) if price else 0.0,
        "prev_close": prev or 0.0,
        "day_change_pct": round(day_change, 2),
        "premarket_gap_pct": round(gap, 2) if gap is not None else 0.0,
        "atr_pct": sig.get("atr_pct") or 0.0,
        "volume_z": sig.get("volume_z") or 0.0,
        "rsi14": sig.get("rsi14") or 50.0,
        "close": price or 0.0,
        "high_52w": high52 or 0.0,
        "close_above_52w_high": bool(high52 and price and price >= high52 - 1e-9),
        "cross_50_200": cross,
        "cross_50_200_label": {1: "golden cross", -1: "death cross", 0: ""}[cross],
    }


def _scope_contexts(db, s: Settings, scope: str, macro: dict):
    """Yield (label, vars) contexts for a rule's scope."""
    if scope == "macro":
        yield ("macro", macro)
        return
    if scope in ("holdings", "active", "monitor"):
        tier = "holding" if scope == "holdings" else scope
        for inst in db.query("SELECT * FROM instruments WHERE tier=?", (tier,)):
            yield (inst["ticker"], {**macro, **_instrument_vars(db, inst)})
        return
    if scope == "portfolio":
        yield from _portfolio_contexts(db, s, macro, crypto_only=False)
        return
    if scope == "crypto-holdings":
        yield from _portfolio_contexts(db, s, macro, crypto_only=True)
        return


def _portfolio_contexts(db, s: Settings, macro: dict, crypto_only: bool):
    port = load_portfolio(s)
    for acct in port.get("accounts", []):
        for pos in acct.get("positions", []):
            ticker = norm_ticker(pos.get("ticker", ""))
            if crypto_only and not ticker.endswith("-USD"):
                continue
            inst = db.query_one("SELECT * FROM instruments WHERE ticker=?", (ticker,))
            if not inst:
                continue
            base = {**macro, **_instrument_vars(db, inst)}
            base.update(_invalidation_vars(db, ticker, pos, base.get("price")))
            yield (ticker, base)


def _invalidation_vars(db, ticker: str, pos: dict, price) -> dict:
    memo_id = pos.get("memo_id")
    out = {
        "memo_id": memo_id or 0,
        "invalidation_level": 0.0,
        "exit_plan": "",
        "invalidation_crossed": False,
    }
    if not memo_id or price is None:
        return out
    memo = db.query_one(
        "SELECT invalidation_level, direction, entry_plan FROM memos WHERE id=?", (memo_id,)
    )
    if not memo or memo["invalidation_level"] is None:
        return out
    level = memo["invalidation_level"]
    direction = memo["direction"] or "long"
    crossed = (price <= level) if direction != "short" else (price >= level)
    out.update(
        {
            "invalidation_level": level,
            "exit_plan": (memo["entry_plan"] or "see memo")[:120],
            "invalidation_crossed": bool(crossed),
        }
    )
    return out


# --------------------------------------------------------------------------------------
# Engine
# --------------------------------------------------------------------------------------
def evaluate_rules(settings: Settings | None = None) -> dict:
    s = settings or get_settings()
    from ..db import get_db

    db = get_db(s)
    rules = load_alert_rules(s)
    macro = _macro_vars(db, s)
    governor = _noise_governor_active(db, s)

    fired = 0
    suppressed = 0
    for rule in rules:
        try:
            for label, variables in _scope_contexts(db, s, rule.get("scope", "macro"), macro):
                if not safe_eval(rule.get("when", "False"), variables):
                    continue
                priority = _resolve_priority(rule, variables)
                # noise governor: collapse P2 pushes into the dashboard-only digest
                push = not (governor and priority == "P2")
                if _fire(db, s, rule, label, variables, priority, push=push):
                    fired += 1
                    if not push:
                        suppressed += 1
        except Exception as e:  # noqa: BLE001
            logger.warning("rule {} failed: {}", rule.get("id"), e)
    return {"fired": fired, "p2_suppressed": suppressed, "governor": governor}


def _resolve_priority(rule: dict, variables: dict) -> str:
    p = rule.get("priority", "P2")
    if isinstance(p, str) and p.startswith("P") and len(p) == 2:
        return p
    # conditional expression like "P0 if item_material else P1"
    try:
        val = eval(p, {"__builtins__": {}}, {**_ALLOWED, **variables})  # noqa: S307
        return val if val in ("P0", "P1", "P2") else "P2"
    except Exception:  # noqa: BLE001
        return "P2"


def _dedupe_key(rule: dict, label: str, variables: dict, s: Settings) -> str:
    throttle = rule.get("throttle", "none")
    rid = rule.get("id")
    if throttle == "once_per_day":
        return f"{rid}:{label}:{today_iso(s.tz)}"
    if throttle == "once_per_memo":
        return f"{rid}:memo{variables.get('memo_id')}"
    if throttle == "once_per_bar":
        return f"{rid}:{label}:{today_iso(s.tz)}"
    return f"{rid}:{label}"


def _already_fired(db, dedupe: str, rule: dict) -> bool:
    """Throttle/cooldown dedupe against the alerts table (independent of the router)."""
    throttle = rule.get("throttle", "none")
    if throttle in ("once_per_day", "once_per_bar"):
        # dedupe_key already carries the date → any prior row means "already fired today"
        return (
            db.query_one("SELECT 1 FROM alerts WHERE dedupe_key=? LIMIT 1", (dedupe,)) is not None
        )
    if throttle == "once_per_memo":
        since = iso(utcnow() - timedelta(hours=24))  # re-arm once per day
    else:
        since = iso(utcnow() - timedelta(seconds=int(rule.get("cooldown", 3600) or 3600)))
    return (
        db.query_one(
            "SELECT 1 FROM alerts WHERE dedupe_key=? AND fired_at>=? LIMIT 1", (dedupe, since)
        )
        is not None
    )


def _fire(
    db, s: Settings, rule: dict, label: str, variables: dict, priority: str, push: bool
) -> bool:
    dedupe = _dedupe_key(rule, label, variables, s)
    if _already_fired(db, dedupe, rule):
        return False
    title = f"{label} — {rule.get('id')}" if label != "macro" else rule.get("id")
    body = _fmt(rule.get("msg", rule.get("id", "")), variables)
    iid = None
    if label != "macro":
        row = db.query_one("SELECT id FROM instruments WHERE ticker=?", (label,))
        iid = row["id"] if row else None

    # record the alert row (dashboard feed) regardless of push
    db.execute(
        "INSERT INTO alerts(rule_id,instrument_id,priority,title,body,evidence_json,fired_at,dedupe_key) "
        "VALUES(?,?,?,?,?,?,?,?)",
        (rule.get("id"), iid, priority, title, body, "{}", utcnow_iso(), dedupe),
    )
    from ..api.events import publish

    publish("alert", {"rule": rule.get("id"), "priority": priority, "title": title, "body": body})

    if push:
        from ..notify import Notification, get_router

        cooldown = int(rule.get("cooldown", 3600))
        get_router(s).send(
            Notification(
                priority=priority,
                title=title,
                body=body,
                dedupe_key=dedupe,
                cooldown_s=cooldown,
                click_path=_deep_link(label),
            )
        )
    return True


def _deep_link(label: str) -> str:
    return f"/markets/{label}" if label != "macro" else "/signals"


def _noise_governor_active(db, s: Settings) -> bool:
    since = iso(utcnow() - timedelta(hours=1))
    row = db.query_one("SELECT COUNT(*) n FROM alerts WHERE fired_at>=?", (since,))
    active = bool(row and row["n"] > _NOISE_LIMIT)
    if active:
        db.set_setting(
            "alerts.noise_governor", {"active": True, "at": utcnow_iso(), "count": row["n"]}
        )
        logger.info("noise governor active ({} alerts in last hour) — collapsing P2s", row["n"])
    return active
