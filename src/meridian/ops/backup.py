"""Backups + restore drill.

Uses SQLite's native online backup API (consistent even while the daemon holds the WAL)
so it works cross-platform without the `sqlite3` CLI. Parquet is mirrored by copy. The
restore drill backs up, restores to a scratch path, and verifies row counts match — the
Phase 8 acceptance gate.
"""

from __future__ import annotations

import gzip
import shutil
import sqlite3
import tempfile
from pathlib import Path

from loguru import logger

from ..config import Settings, get_settings
from ..util import today_iso, utcnow_iso

_VERIFY_TABLES = (
    "instruments",
    "news_items",
    "filings",
    "signals",
    "briefs",
    "memos",
    "macro_points",
    "prediction_markets",
)


def _backup_db(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    src_conn = sqlite3.connect(str(src))
    dst_conn = sqlite3.connect(str(dest))
    try:
        with dst_conn:
            src_conn.backup(dst_conn)
    finally:
        src_conn.close()
        dst_conn.close()


def _gzip(path: Path) -> Path:
    gz = path.with_suffix(path.suffix + ".gz")
    with path.open("rb") as f_in, gzip.open(gz, "wb", compresslevel=9) as f_out:
        shutil.copyfileobj(f_in, f_out)
    path.unlink(missing_ok=True)
    return gz


def _counts(db_path: Path) -> dict[str, int]:
    conn = sqlite3.connect(str(db_path))
    try:
        out = {}
        for t in _VERIFY_TABLES:
            try:
                out[t] = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            except sqlite3.Error:
                out[t] = -1
        return out
    finally:
        conn.close()


def run_backup(settings: Settings | None = None) -> dict:
    s = settings or get_settings()
    if not s.db_path.exists():
        return {"ok": False, "error": "no database to back up"}
    dest_dir = s.backups_dir / "daily"
    stamp = today_iso(s.tz)
    raw = dest_dir / f"meridian-{stamp}.db"
    _backup_db(s.db_path, raw)
    gz = _gzip(raw)
    # Parquet mirror
    pq_dest = s.backups_dir / "parquet"
    if s.parquet_dir.exists():
        shutil.copytree(s.parquet_dir, pq_dest, dirs_exist_ok=True)
    # retention: 14 dailies
    dailies = sorted(
        dest_dir.glob("meridian-*.db.gz"), key=lambda p: p.stat().st_mtime, reverse=True
    )
    for old in dailies[14:]:
        old.unlink(missing_ok=True)
    logger.info("backup complete: {} ({} bytes)", gz.name, gz.stat().st_size)
    return {"ok": True, "path": str(gz), "bytes": gz.stat().st_size, "kept": len(dailies[:14])}


def restore_drill(settings: Settings | None = None) -> dict:
    """Back up → restore to a scratch path → verify row counts match. Phase 8 AC."""
    s = settings or get_settings()
    if not s.db_path.exists():
        return {"ok": False, "error": "no database"}
    source_counts = _counts(s.db_path)
    with tempfile.TemporaryDirectory(prefix="meridian_drill_") as tmp:
        tmp_path = Path(tmp)
        backup_raw = tmp_path / "backup.db"
        _backup_db(s.db_path, backup_raw)
        gz = _gzip(backup_raw)
        # restore: gunzip to a scratch db
        restored = tmp_path / "restored.db"
        with gzip.open(gz, "rb") as f_in, restored.open("wb") as f_out:
            shutil.copyfileobj(f_in, f_out)
        restored_counts = _counts(restored)
        # integrity check on the restored copy
        conn = sqlite3.connect(str(restored))
        try:
            integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        finally:
            conn.close()
    matches = source_counts == restored_counts
    result = {
        "ok": matches and integrity == "ok",
        "integrity": integrity,
        "counts_match": matches,
        "source_counts": source_counts,
        "restored_counts": restored_counts,
        "at": utcnow_iso(),
    }
    logger.info("restore drill: ok={} integrity={}", result["ok"], integrity)
    return result
