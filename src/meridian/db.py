"""SQLite access + migration runner.

One file is the source of truth. WAL mode gives us concurrent readers with a single
writer, which is exactly the daemon's shape (many pollers read; a few jobs write).
Connections are opened per-use (cheap) with ``check_same_thread=False`` so APScheduler's
threadpool and the asyncio loop can share the database safely.

``sqlite-vec`` is loaded opportunistically. When it is absent (e.g. Windows dev box),
vector search degrades to brute-force cosine in Python over the ``embedding`` BLOB
column — correctness preserved, only speed lost (see docs/DECISIONS.md D-003).
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from loguru import logger

from .config import Settings, get_settings
from .util import utcnow_iso

_VEC_AVAILABLE: bool | None = None
_write_lock = threading.Lock()


def _try_load_vec(conn: sqlite3.Connection) -> bool:
    global _VEC_AVAILABLE
    try:
        import sqlite_vec  # type: ignore

        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        _VEC_AVAILABLE = True
    except Exception:  # noqa: BLE001 — any failure means "degrade to python cosine"
        _VEC_AVAILABLE = False
    return bool(_VEC_AVAILABLE)


def vec_available() -> bool:
    return bool(_VEC_AVAILABLE)


class Database:
    """Thin wrapper around a SQLite file with a numbered-SQL migration runner."""

    def __init__(self, path: Path, migrations_dir: Path):
        self.path = path
        self.migrations_dir = migrations_dir
        self.path.parent.mkdir(parents=True, exist_ok=True)

    # -- connections -------------------------------------------------------
    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(
            self.path,
            check_same_thread=False,
            timeout=30.0,
            isolation_level=None,  # autocommit; we manage transactions explicitly
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=30000")
        conn.execute("PRAGMA synchronous=NORMAL")
        if _VEC_AVAILABLE is None:
            _try_load_vec(conn)
        elif _VEC_AVAILABLE:
            try:
                import sqlite_vec  # type: ignore

                conn.enable_load_extension(True)
                sqlite_vec.load(conn)
                conn.enable_load_extension(False)
            except Exception:  # noqa: BLE001
                pass
        return conn

    @contextmanager
    def cursor(self) -> Iterator[sqlite3.Cursor]:
        conn = self.connect()
        try:
            yield conn.cursor()
        finally:
            conn.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Cursor]:
        """Serialised write transaction (single writer via module lock + BEGIN IMMEDIATE)."""
        conn = self.connect()
        with _write_lock:
            try:
                conn.execute("BEGIN IMMEDIATE")
                cur = conn.cursor()
                yield cur
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
            finally:
                conn.close()

    # -- convenience queries ----------------------------------------------
    def query(self, sql: str, params: Iterable[Any] = ()) -> list[sqlite3.Row]:
        with self.cursor() as cur:
            cur.execute(sql, tuple(params))
            return cur.fetchall()

    def query_one(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Row | None:
        with self.cursor() as cur:
            cur.execute(sql, tuple(params))
            return cur.fetchone()

    def scalar(self, sql: str, params: Iterable[Any] = ()) -> Any:
        row = self.query_one(sql, params)
        return row[0] if row is not None else None

    def execute(self, sql: str, params: Iterable[Any] = ()) -> int:
        with self.transaction() as cur:
            cur.execute(sql, tuple(params))
            return cur.lastrowid or cur.rowcount

    def executemany(self, sql: str, seq: Iterable[Iterable[Any]]) -> int:
        rows = [tuple(r) for r in seq]
        if not rows:
            return 0
        with self.transaction() as cur:
            cur.executemany(sql, rows)
            return cur.rowcount

    # -- key/value settings table -----------------------------------------
    def get_setting(self, key: str, default: Any = None) -> Any:
        from .util import from_json

        row = self.query_one("SELECT value_json FROM settings WHERE key=?", (key,))
        return from_json(row["value_json"], default) if row else default

    def set_setting(self, key: str, value: Any) -> None:
        from .util import to_json

        self.execute(
            "INSERT INTO settings(key, value_json) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json",
            (key, to_json(value)),
        )

    # -- migrations --------------------------------------------------------
    def migrate(self) -> list[str]:
        """Apply pending numbered SQL migrations in order. Idempotent."""
        with self.transaction() as cur:
            cur.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations("
                "  version TEXT PRIMARY KEY, applied_at TEXT)"
            )
        applied = {r["version"] for r in self.query("SELECT version FROM schema_migrations")}
        files = sorted(self.migrations_dir.glob("[0-9]*.sql"))
        newly: list[str] = []
        for f in files:
            version = f.name.split("_", 1)[0]
            if version in applied:
                continue
            sql = f.read_text(encoding="utf-8")
            conn = self.connect()
            with _write_lock:
                try:
                    conn.executescript("BEGIN;\n" + sql + "\nCOMMIT;")
                    conn.execute(
                        "INSERT INTO schema_migrations(version, applied_at) VALUES(?,?)",
                        (version, utcnow_iso()),
                    )
                except Exception:
                    conn.execute("ROLLBACK")
                    conn.close()
                    logger.error("migration {} failed", f.name)
                    raise
                finally:
                    conn.close()
            newly.append(f.name)
            logger.info("applied migration {}", f.name)
        return newly


_db: Database | None = None


def get_db(settings: Settings | None = None) -> Database:
    global _db
    if _db is None:
        s = settings or get_settings()
        _db = Database(s.db_path, s.migrations_dir)
    return _db


def reset_db_singleton() -> None:
    """Test hook — drop the cached Database so a new path takes effect."""
    global _db, _VEC_AVAILABLE
    _db = None
    _VEC_AVAILABLE = None
