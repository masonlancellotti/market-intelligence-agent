"""Shared test fixtures. Each test runs against an isolated MERIDIAN_HOME (temp dir)
with a fresh migrated SQLite DB, so tests never touch real data or secrets.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]

TEST_YAML = """
timezone: America/New_York
watchlist:
  holdings: [NVDA]
  active: [MSFT, SPY, QQQ, TLT, GLD]
  monitor: [BTC-USD, ETH-USD]
benchmarks: [SPY, QQQ, TLT, GLD, BTC-USD]
sector_etfs: [XLK, XLF, XLE]
budgets: {llm_daily_usd: 3.0, llm_monthly_usd: 60.0}
notifications:
  quiet_hours: {start: "23:00", end: "07:00", override_priority: P0}
"""


@pytest.fixture()
def home(tmp_path, monkeypatch):
    (tmp_path / "config").mkdir()
    (tmp_path / "migrations").mkdir()
    for f in (REPO / "migrations").glob("*.sql"):
        shutil.copy(f, tmp_path / "migrations" / f.name)
    (tmp_path / "config" / "meridian.yaml").write_text(TEST_YAML, encoding="utf-8")
    # real alert rules so the engine has something to evaluate
    shutil.copy(REPO / "config" / "alerts.yaml", tmp_path / "config" / "alerts.yaml")
    # real systematic rulebook for the Calibration Lab backtest tests
    shutil.copy(REPO / "config" / "rules.yaml", tmp_path / "config" / "rules.yaml")
    monkeypatch.setenv("MERIDIAN_HOME", str(tmp_path))

    from meridian.config import reload_settings
    from meridian.db import get_db, reset_db_singleton

    reset_db_singleton()
    s = reload_settings()
    s.ensure_dirs()
    get_db(s).migrate()
    yield s

    reset_db_singleton()
    reload_settings()


@pytest.fixture()
def db(home):
    from meridian.db import get_db

    return get_db(home)
