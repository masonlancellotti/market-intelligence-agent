"""In-process SSE pub/sub bus.

One channel carries ``quote``, ``alert``, ``brief_ready`` and ``health`` events to
every connected dashboard. Publishers (scheduler jobs, the alert engine, the notifier)
call :func:`publish`; subscribers get an async iterator of server-sent events.

Thread-safety: publishers run in APScheduler's threadpool, subscribers in the asyncio
loop. We hop onto the loop with ``call_soon_threadsafe`` so queues are only touched
from the loop thread.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from loguru import logger

from ..util import to_json, utcnow_iso


@dataclass
class Event:
    event: str
    data: dict[str, Any]
    id: str = field(default_factory=utcnow_iso)

    def sse(self) -> dict[str, str]:
        return {"event": self.event, "id": self.id, "data": to_json(self.data)}


class SSEBus:
    def __init__(self, history: int = 50):
        self._subscribers: set[asyncio.Queue[Event]] = set()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._recent: deque[Event] = deque(maxlen=history)

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def subscribe(self) -> asyncio.Queue[Event]:
        q: asyncio.Queue[Event] = asyncio.Queue(maxsize=1000)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[Event]) -> None:
        self._subscribers.discard(q)

    def publish(self, event: str, data: dict[str, Any]) -> None:
        """Safe to call from any thread."""
        ev = Event(event=event, data=data)
        self._recent.append(ev)
        loop = self._loop
        if loop is None or not self._subscribers:
            return
        with contextlib.suppress(RuntimeError):  # loop closed during shutdown
            loop.call_soon_threadsafe(self._fanout, ev)

    def _fanout(self, ev: Event) -> None:
        dead = []
        for q in self._subscribers:
            try:
                q.put_nowait(ev)
            except asyncio.QueueFull:
                dead.append(q)
        for q in dead:
            logger.warning("SSE subscriber queue full; dropping")
            self._subscribers.discard(q)

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)


_bus = SSEBus()


def get_bus() -> SSEBus:
    return _bus


def publish(event: str, data: dict[str, Any]) -> None:
    _bus.publish(event, data)
