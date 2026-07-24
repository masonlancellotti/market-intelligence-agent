"""BaseConnector — the uniform ingestion contract.

Guarantees for every connector:
* tenacity exponential backoff (max 5 attempts) around ``fetch``;
* a per-connector circuit breaker: 5 consecutive failures opens the circuit for a
  cooldown window and raises a P2; cycles are skipped while open;
* freshness stamping + health logging to ``connector_health``;
* graceful disable when required secrets are absent (status ``disabled``, never a crash).

Subclasses implement async ``fetch() -> FetchResult``. The scheduler calls
``run_sync()`` (which wraps ``run()`` in ``asyncio.run`` inside its worker thread), so
connectors may freely mix async httpx and sync libraries via ``asyncio.to_thread``.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import timedelta

from loguru import logger
from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_exponential

from ..config import Settings, get_settings
from ..util import iso, utcnow, utcnow_iso

CONNECTORS: dict[str, type[BaseConnector]] = {}


def register(cls: type[BaseConnector]) -> type[BaseConnector]:
    CONNECTORS[cls.name] = cls
    return cls


@dataclass
class FetchResult:
    items: int = 0
    detail: str = ""


class ConnectorError(Exception):
    pass


class BaseConnector:
    name: str = "base"
    requires: list[str] = []  # secret names that must be present to enable
    circuit_threshold: int = 5
    circuit_cooldown_s: int = 900  # 15 min
    http_ua: str = "Meridian/1.0 (+https://github.com/meridian; research)"

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        from ..db import get_db

        self.db = get_db(self.settings)

    # -- to implement -----------------------------------------------------
    async def fetch(self) -> FetchResult:  # pragma: no cover - abstract
        raise NotImplementedError

    # -- lifecycle --------------------------------------------------------
    def enabled(self) -> bool:
        return all(self.settings.secrets.has(r) for r in self.requires)

    async def run(self) -> dict:
        if not self.enabled():
            self._upsert_health(status="disabled", enabled=0)
            missing = [r for r in self.requires if not self.settings.secrets.has(r)]
            return {"connector": self.name, "ok": False, "status": "disabled", "missing": missing}

        if self._circuit_open():
            return {"connector": self.name, "ok": False, "status": "circuit_open"}

        try:
            result = await self._with_retry()
            self._mark_success(result.items)
            return {
                "connector": self.name,
                "ok": True,
                "status": "ok",
                "items": result.items,
                "detail": result.detail,
            }
        except Exception as e:  # noqa: BLE001
            self._mark_failure(e)
            return {"connector": self.name, "ok": False, "status": "error", "error": str(e)[:300]}

    def run_sync(self) -> dict:
        return asyncio.run(self.run())

    async def _with_retry(self) -> FetchResult:
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(5),
            wait=wait_exponential(multiplier=1, min=1, max=30),
            retry=retry_if_exception_type(Exception),
            reraise=True,
        ):
            with attempt:
                return await self.fetch()
        return FetchResult()  # unreachable

    # -- circuit breaker + health ----------------------------------------
    def _health_row(self):
        return self.db.query_one("SELECT * FROM connector_health WHERE connector=?", (self.name,))

    def _circuit_open(self) -> bool:
        row = self._health_row()
        if not row or not row["circuit_open_until"]:
            return False
        from ..util import parse_iso

        until = parse_iso(row["circuit_open_until"])
        return bool(until and until > utcnow())

    def _upsert_health(self, **fields) -> None:
        cols = list(fields.keys())
        existing = self._health_row()
        if existing:
            sets = ", ".join(f"{c}=?" for c in cols)
            self.db.execute(
                f"UPDATE connector_health SET {sets} WHERE connector=?",
                (*fields.values(), self.name),
            )
        else:
            allcols = ["connector", *cols]
            ph = ",".join("?" for _ in allcols)
            self.db.execute(
                f"INSERT INTO connector_health({','.join(allcols)}) VALUES({ph})",
                (self.name, *fields.values()),
            )

    def _mark_success(self, items: int) -> None:
        self._upsert_health(
            last_success=utcnow_iso(),
            error_streak=0,
            circuit_open_until=None,
            items_24h=items,
            status="ok",
            enabled=1,
        )
        logger.info("connector {} ok ({} items)", self.name, items)

    def _mark_failure(self, err: Exception) -> None:
        row = self._health_row()
        streak = (row["error_streak"] if row else 0) + 1
        status = "amber"
        circuit_until = None
        if streak >= self.circuit_threshold:
            status = "red"
            circuit_until = iso(utcnow() + timedelta(seconds=self.circuit_cooldown_s))
            self._raise_p2(err, streak)
        self._upsert_health(
            last_error=utcnow_iso(),
            last_error_msg=str(err)[:400],
            error_streak=streak,
            circuit_open_until=circuit_until,
            status=status,
            enabled=1,
        )
        logger.warning("connector {} failed (streak {}): {}", self.name, streak, err)

    def _raise_p2(self, err: Exception, streak: int) -> None:
        try:
            from ..notify import Notification, get_router

            get_router(self.settings).send(
                Notification(
                    priority="P2",
                    title=f"Connector down: {self.name}",
                    body=f"{streak} consecutive failures; circuit open {self.circuit_cooldown_s // 60}m. {err}"[
                        :300
                    ],
                    dedupe_key=f"connector:{self.name}",
                    cooldown_s=3600,
                    click_path="/system",
                )
            )
        except Exception:  # noqa: BLE001
            pass

    # -- shared write helpers --------------------------------------------
    def instrument_id(self, ticker: str, kind: str | None = None) -> int:
        from ..ops.bootstrap import instrument_id
        from ..util import norm_ticker

        t = norm_ticker(ticker)
        iid = instrument_id(t, self.settings)
        if iid is None:
            iid = self.db.execute(
                "INSERT INTO instruments(ticker,name,kind,tier,meta_json) VALUES(?,?,?,?,'{}') "
                "ON CONFLICT(ticker) DO UPDATE SET ticker=excluded.ticker",
                (t, t, kind or "equity", "monitor"),
            )
            row = self.db.query_one("SELECT id FROM instruments WHERE ticker=?", (t,))
            iid = row["id"] if row else iid
        return iid

    def upsert_quote(
        self,
        ticker: str,
        *,
        price: float | None,
        prev_close: float | None = None,
        day_open: float | None = None,
        day_high: float | None = None,
        day_low: float | None = None,
        volume: float | None = None,
        source: str = "",
        is_stale: int = 0,
        kind: str | None = None,
    ) -> None:
        iid = self.instrument_id(ticker, kind=kind)
        self.db.execute(
            "INSERT INTO quotes_latest"
            "(instrument_id,price,prev_close,day_open,day_high,day_low,volume,ts,source,is_stale) "
            "VALUES(?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(instrument_id) DO UPDATE SET "
            "price=excluded.price, prev_close=excluded.prev_close, day_open=excluded.day_open, "
            "day_high=excluded.day_high, day_low=excluded.day_low, volume=excluded.volume, "
            "ts=excluded.ts, source=excluded.source, is_stale=excluded.is_stale",
            (
                iid,
                price,
                prev_close,
                day_open,
                day_high,
                day_low,
                volume,
                utcnow_iso(),
                source,
                is_stale,
            ),
        )
