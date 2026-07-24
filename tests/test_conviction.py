"""Phase 6 tests: gate scoring, transitions, red team, predictions/Brier, portfolio watch, API."""

from __future__ import annotations

import pytest

from meridian.conviction import memos as M
from meridian.conviction.predictions import brier_summary, resolve_prediction


def _full_memo_fields():
    return {
        "ticker": "NVDA",
        "direction": "long",
        "thesis": "AI compute demand outstrips supply through 2027.",
        "edge_type": "analytical",
        "risks": ["export controls", "substitution", "valuation"],
        "valuation": {"pe_fwd": 32},
        "catalysts": ["Q2 earnings"],
        "invalidation_level": 170.0,
        "invalidation_rule": "close < 170 x2d",
        "entry_plan": "trim half",
        "size_plan": "risk 1%",
    }


def test_gate_scoring_thin_vs_full(home, db):
    thin = M.get_memo(M.create_memo({"ticker": "X", "thesis": "up"}, home), home)
    assert thin["gate"]["score"] < 70 and thin["gate"]["passes"] is False

    mid = M.create_memo(_full_memo_fields(), home)
    db.execute("UPDATE memos SET created_at=datetime('now','-2 days') WHERE id=?", (mid,))
    full = M.get_memo(mid, home)
    assert full["gate"]["score"] >= 70 and full["gate"]["passes"] is True
    # invalidation is the heaviest item
    assert full["gate"]["breakdown"]["invalidation"]["points"] == 15


def test_gate_blocks_live_without_override(home, db):
    mid = M.create_memo({"ticker": "X", "thesis": "up"}, home)
    M.transition_memo(mid, "staged", settings=home)
    res = M.transition_memo(mid, "live", settings=home)
    assert res.get("blocked") is True and res["ok"] is False
    # override lets it through AND journals the reason
    res2 = M.transition_memo(mid, "live", override_reason="accept risk", settings=home)
    assert res2["ok"] is True and res2["status"] == "live"
    j = db.query(
        "SELECT markdown FROM journal_entries WHERE memo_id=? AND markdown LIKE '%override%'",
        (mid,),
    )
    assert len(j) >= 1


def test_gate_passes_live_when_scored(home, db):
    mid = M.create_memo(_full_memo_fields(), home)
    db.execute("UPDATE memos SET created_at=datetime('now','-2 days') WHERE id=?", (mid,))
    M.transition_memo(mid, "staged", settings=home)
    res = M.transition_memo(mid, "live", settings=home)
    assert res["ok"] is True and res["status"] == "live"
    memo = M.get_memo(mid, home)
    assert memo["redteam_verdict"] is not None  # red team ran on going live


def test_redteam_heuristic(home, db):
    from meridian.conviction.redteam import run_redteam

    mid = M.create_memo({"ticker": "X", "thesis": "up", "risks": ["a", "b"]}, home)
    out = run_redteam(mid, home)
    assert out["ok"] and out["verdict"]["mode"] == "heuristic"
    assert len(out["verdict"]["objections"]) >= 3
    assert out["verdict"]["verdict"] in ("thesis_holds", "wounded", "broken")


def test_predictions_brier_and_calibration(home, db):
    mid = M.create_memo({"ticker": "X", "thesis": "up"}, home)
    p1 = M.add_prediction(
        mid, {"claim": "up", "probability": 0.7, "horizon_date": "2026-09-01"}, home
    )
    p2 = M.add_prediction(
        mid, {"claim": "down", "probability": 0.2, "horizon_date": "2026-09-01"}, home
    )
    resolve_prediction(p1, True, home)  # brier (0.7-1)^2 = 0.09
    resolve_prediction(p2, False, home)  # brier (0.2-0)^2 = 0.04
    bs = brier_summary(home)
    assert bs["n"] == 2
    assert abs(bs["mean_brier"] - 0.065) < 1e-6
    assert bs["hit_rate"] == 1.0  # both correct-direction


def test_price_prediction_auto_resolves(home, db):
    from meridian.conviction.predictions import resolve_due
    from meridian.util import utcnow_iso

    iid = db.execute(
        "INSERT INTO instruments(ticker,name,kind,tier) VALUES('NVDA','NVDA','equity','holding')"
    )
    db.execute(
        "INSERT INTO quotes_latest(instrument_id,price,ts) VALUES(?,200.0,?)", (iid, utcnow_iso())
    )
    mid = M.create_memo({"ticker": "NVDA", "thesis": "up"}, home)
    M.add_prediction(
        mid,
        {
            "claim": "NVDA above 150",
            "probability": 0.8,
            "horizon_date": "2020-01-01",
            "kind": "price",
            "resolve_rule": "NVDA >= 150",
        },
        home,
    )
    out = resolve_due(home)
    assert out["auto_resolved"] == 1
    row = db.query_one("SELECT resolution FROM memo_predictions WHERE resolve_rule='NVDA >= 150'")
    assert row["resolution"] == "true"  # price 200 >= 150


def test_portfolio_change_detection(home, db):
    from meridian.conviction.portfolio_watch import check_portfolio_change

    (home.config_dir / "portfolio.yaml").write_text(
        "accounts:\n  - name: b\n    positions:\n      - {ticker: NVDA, qty: 10}\n",
        encoding="utf-8",
    )
    assert check_portfolio_change(home)["first_seen"] is True
    assert check_portfolio_change(home)["changed"] is False
    (home.config_dir / "portfolio.yaml").write_text(
        "accounts:\n  - name: b\n    positions:\n      - {ticker: NVDA, qty: 20}\n",
        encoding="utf-8",
    )
    assert check_portfolio_change(home)["changed"] is True


@pytest.mark.asyncio
async def test_memos_api(home, db):
    from httpx import ASGITransport, AsyncClient

    from meridian.app import create_app

    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
        created = await ac.post(
            "/api/memos", json={"ticker": "NVDA", "thesis": "up", "direction": "long"}
        )
        assert created.status_code == 200
        mid = created.json()["id"]
        k = await ac.get("/api/memos")
        assert "research" in k.json()["kanban"]
        block = await ac.post(f"/api/memos/{mid}/transition", json={"to": "staged"})
        assert block.json()["ok"] is True
        live = await ac.post(f"/api/memos/{mid}/transition", json={"to": "live"})
        assert live.json().get("blocked") is True  # gate blocks
