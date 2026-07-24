"""Phase 0 acceptance-ish tests: config, db, seeding, notifier, health."""

from __future__ import annotations

from meridian.notify.router import Notification, Router
from meridian.ops.bootstrap import seed_instruments
from meridian.ops.health import health_snapshot, record_heartbeat


def test_config_loads(home):
    assert home.config.timezone == "America/New_York"
    assert "NVDA" in home.config.watchlist.holdings
    assert set(home.config.watchlist.all()) >= {"NVDA", "MSFT", "SPY", "BTC-USD"}
    # secrets absent by default -> connectors will disable, not crash
    assert home.secrets.has("anthropic_api_key") is False


def test_migrations_idempotent(db):
    assert db.migrate() == []  # already applied in fixture
    tables = {r["name"] for r in db.query("SELECT name FROM sqlite_master WHERE type='table'")}
    for t in ("instruments", "news_items", "memos", "agent_runs", "notifications"):
        assert t in tables


def test_settings_kv_roundtrip(db):
    db.set_setting("x.y", {"a": 1})
    assert db.get_setting("x.y") == {"a": 1}
    assert db.get_setting("missing", 42) == 42


def test_seed_instruments(home, db):
    n = seed_instruments(home)
    assert n >= 8
    nvda = db.query_one("SELECT tier, kind FROM instruments WHERE ticker='NVDA'")
    assert nvda["tier"] == "holding" and nvda["kind"] == "equity"
    btc = db.query_one("SELECT kind FROM instruments WHERE ticker='BTC-USD'")
    assert btc["kind"] == "crypto"


def test_health_snapshot(home, db):
    record_heartbeat(home)
    snap = health_snapshot(home)
    assert snap["overall"] in ("green", "amber", "red")
    assert snap["scheduler"]["ok"] is True  # heartbeat just recorded
    assert snap["db_writable"] is True


def test_notify_dry_run_when_no_channels(home, db):
    r = Router(home, dry_run=True)
    res = r.send(Notification(priority="P1", title="t", body="b", force=True))
    assert res["status"] == "dry_run"
    row = db.query_one("SELECT status FROM notifications ORDER BY id DESC LIMIT 1")
    assert row["status"] == "dry_run"


def test_notify_dedupe(home, db):
    r = Router(home, dry_run=True)
    # force=False so dedupe applies; but dry_run never marks 'sent', so dedupe won't trip.
    # Simulate a prior 'sent' row, then confirm the next send is deduped.
    from meridian.util import utcnow_iso

    db.execute(
        "INSERT INTO notifications(priority,title,body,dedupe_key,status,created_at,sent_at) "
        "VALUES('P1','t','b','k1','sent',?,?)",
        (utcnow_iso(), utcnow_iso()),
    )
    res = r.send(Notification(priority="P1", title="t", body="b", dedupe_key="k1", cooldown_s=3600))
    assert res["status"] == "deduped"


def test_notify_quiet_hours_queue(home, db, monkeypatch):
    # Force "now" to sit inside quiet hours (02:00 ET) so P1 queues.
    from datetime import UTC, datetime

    import meridian.notify.router as R

    fake = datetime(2026, 7, 5, 6, 0, tzinfo=UTC)  # 02:00 ET
    monkeypatch.setattr(R, "utcnow", lambda: fake)
    r = Router(home, dry_run=True)
    res = r.send(Notification(priority="P1", title="t", body="b"))
    assert res["status"] == "queued"
    # a P0 within quiet hours punches through (override priority)
    res0 = r.send(Notification(priority="P0", title="t", body="b"))
    assert res0["status"] == "dry_run"  # not queued
