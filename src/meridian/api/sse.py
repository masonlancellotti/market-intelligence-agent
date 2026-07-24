"""GET /api/sse — one Server-Sent-Events channel for the whole dashboard."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Request
from sse_starlette.sse import EventSourceResponse

from ..util import to_json, utcnow_iso
from .events import get_bus

router = APIRouter()


@router.get("/sse")
async def sse(request: Request) -> EventSourceResponse:
    bus = get_bus()
    queue = bus.subscribe()

    async def gen():
        # greet immediately so the client flips to "connected"
        yield {"event": "hello", "id": utcnow_iso(), "data": to_json({"ok": True})}
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    ev = await asyncio.wait_for(queue.get(), timeout=20.0)
                    yield ev.sse()
                except TimeoutError:
                    # heartbeat keeps proxies from killing the idle connection
                    yield {"event": "ping", "id": utcnow_iso(), "data": "{}"}
        finally:
            bus.unsubscribe(queue)

    return EventSourceResponse(gen())
