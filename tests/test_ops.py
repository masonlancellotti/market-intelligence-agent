"""Phase 8 tests: backup + restore drill, cost governance, health overall status."""

from __future__ import annotations

from meridian.ops.backup import restore_drill, run_backup
from meridian.ops.costs import budget_state, estimate_cost
from meridian.util import utcnow_iso


def _seed(db):
    db.execute(
        "INSERT INTO instruments(ticker,name,kind,tier) VALUES('NVDA','NVDA','equity','holding')"
    )
    db.execute(
        "INSERT INTO news_items(source,url,title,published_at,fetched_at) VALUES('R','http://n/1','t',?,?)",
        (utcnow_iso(), utcnow_iso()),
    )


def test_backup_creates_file(home, db):
    _seed(db)
    res = run_backup(home)
    assert res["ok"] is True
    assert res["path"].endswith(".db.gz") and res["bytes"] > 0


def test_restore_drill_passes(home, db):
    _seed(db)
    res = restore_drill(home)
    assert res["ok"] is True
    assert res["integrity"] == "ok"
    assert res["counts_match"] is True
    assert res["source_counts"] == res["restored_counts"]


def test_cost_estimate():
    # Haiku pricing: $1/MTok in, $5/MTok out
    assert estimate_cost("claude-haiku-4-5-20251001", 1_000_000, 0) == 1.0
    assert estimate_cost("claude-opus-4-8", 0, 1_000_000) == 75.0


def test_budget_state_transitions(home, db):
    from meridian.ops.costs import daily_cap

    cap = daily_cap(home)
    # spend 85% → warn
    db.execute(
        "INSERT INTO agent_runs(agent,model,started_at,cost_usd) VALUES('t','m',?,?)",
        (utcnow_iso(), cap * 0.85),
    )
    assert budget_state(home) == "warn"
    db.execute(
        "INSERT INTO agent_runs(agent,model,started_at,cost_usd) VALUES('t','m',?,?)",
        (utcnow_iso(), cap * 0.30),
    )
    assert budget_state(home) == "exhausted"


def test_health_overall(home, db):
    from meridian.ops.health import health_snapshot, record_heartbeat

    record_heartbeat(home)
    # a red connector drags overall to red
    db.execute("INSERT INTO connector_health(connector,status,enabled) VALUES('x','red',1)")
    assert health_snapshot(home)["overall"] == "red"
