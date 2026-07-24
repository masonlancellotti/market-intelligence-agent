"""meridiand — the single long-lived daemon.

FastAPI factory + APScheduler wiring + SSE + static serving in one process. launchd
owns the process lifecycle (KeepAlive); this owns everything inside it.
"""

from __future__ import annotations

import asyncio
import sys
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger

from . import __version__
from .config import Settings, get_settings
from .util import utcnow_iso


@dataclass
class AppState:
    settings: Settings
    scheduler: object | None = None
    started_at: str = field(default_factory=utcnow_iso)


_state: AppState | None = None


def get_app_state() -> AppState | None:
    return _state


def _configure_logging(settings: Settings) -> None:
    logger.remove()
    logger.add(sys.stderr, level="INFO", enqueue=True, backtrace=False, diagnose=False)
    log_dir = settings.home / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    logger.add(
        log_dir / "meridian_{time:YYYY-MM-DD}.log",
        rotation="00:00",
        retention="14 days",
        level="INFO",
        serialize=True,  # structured JSON logs
        enqueue=True,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _state
    s = get_settings()
    _configure_logging(s)
    s.ensure_dirs()
    logger.info("MERIDIAN {} starting — home={}", __version__, s.home)

    # DB up first
    from .db import get_db

    db = get_db(s)
    applied = db.migrate()
    if applied:
        logger.info("applied migrations: {}", applied)

    # seed instruments from watchlist
    from .ops.bootstrap import seed_instruments

    logger.info("seeded {} instruments", seed_instruments(s))

    # SSE bus bound to the running loop
    from .api.events import get_bus

    get_bus().bind_loop(asyncio.get_running_loop())

    # scheduler
    from .ops.scheduler import build_scheduler, register_jobs

    scheduler = build_scheduler(s)
    register_jobs(scheduler, s)
    scheduler.start()
    _state = AppState(settings=s, scheduler=scheduler)
    # record an immediate heartbeat so /api/health is green from t=0 (the interval
    # job's first run is at +60s otherwise)
    from .ops.health import record_heartbeat

    record_heartbeat(s)
    logger.info("scheduler started with {} jobs", len(scheduler.get_jobs()))

    try:
        yield
    finally:
        logger.info("MERIDIAN shutting down")
        if scheduler.running:
            scheduler.shutdown(wait=False)


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(
        title="MERIDIAN",
        version=__version__,
        lifespan=lifespan,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )
    # tailnet-only, but permit local dev tooling
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    _mount_routers(app)
    _mount_static(app, s)
    return app


def _mount_routers(app: FastAPI) -> None:
    from .api import sse, system

    app.include_router(system.router, prefix="/api", tags=["system"])
    app.include_router(sse.router, prefix="/api", tags=["sse"])

    # Optional routers from later phases — mounted if importable.
    for mod_name, prefix, tag in [
        ("meridian.api.markets", "/api", "markets"),
        ("meridian.api.news", "/api", "news"),
        ("meridian.api.signals", "/api", "signals"),
        ("meridian.api.macro", "/api", "macro"),
        ("meridian.api.filings", "/api", "filings"),
        ("meridian.api.briefs", "/api", "briefs"),
        ("meridian.api.memos", "/api", "conviction"),
        ("meridian.api.feed", "", "feed"),
    ]:
        try:
            mod = __import__(mod_name, fromlist=["router"])
            app.include_router(mod.router, prefix=prefix, tags=[tag])
        except Exception as e:  # noqa: BLE001
            logger.debug("router {} not mounted: {}", mod_name, e)


def _mount_static(app: FastAPI, settings: Settings) -> None:
    dist = settings.web_dist

    @app.get("/api")
    def api_root() -> dict:
        return {"service": "meridian", "version": __version__, "ts": utcnow_iso()}

    if dist.exists() and (dist / "index.html").exists():
        assets = dist / "assets"
        if assets.exists():
            app.mount("/assets", StaticFiles(directory=assets), name="assets")

        @app.get("/{full_path:path}")
        def spa(full_path: str):
            # never hijack the API namespace
            if full_path.startswith("api/"):
                return JSONResponse({"error": "not found"}, status_code=404)
            candidate = dist / full_path
            if full_path and candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(dist / "index.html")
    else:

        @app.get("/")
        def placeholder() -> dict:
            return {
                "service": "meridian",
                "version": __version__,
                "note": "dashboard not built yet — run `make build-web` (web/dist missing)",
                "api": "/api",
                "health": "/api/health",
            }


def main() -> None:
    """Entry point (`meridiand`). Runs uvicorn with the daemon app.

    We pass the factory as an import string so uvicorn constructs the app inside the
    real ``meridian.app`` module (not the ``__main__`` copy created by ``python -m``).
    That keeps module-level state such as ``_state`` visible to the API routers.
    """
    import os

    import uvicorn

    host = "0.0.0.0"  # firewalled to the tailnet interface in deployment
    # 8788 default so we never collide with the prediction-terminal server on 8787
    # (docs/DECISIONS.md D-004). Override with MERIDIAN_PORT.
    port = int(os.environ.get("MERIDIAN_PORT", "8788"))
    logger.info("serving on http://{}:{}", host, port)
    uvicorn.run(
        "meridian.app:create_app",
        factory=True,
        host=host,
        port=port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
