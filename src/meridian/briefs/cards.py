"""Designed push cards. Headless Chromium (Playwright) screenshots the
/og/brief/:id route so the morning push itself looks designed. Degrades to no-attachment
when Playwright isn't installed (e.g. Windows dev) — docs/DECISIONS.md D-009.
"""

from __future__ import annotations

from pathlib import Path

from loguru import logger

from ..config import Settings, get_settings


def render_card(brief_id: int, settings: Settings | None = None) -> Path | None:
    s = settings or get_settings()
    try:
        from playwright.sync_api import sync_playwright  # type: ignore
    except Exception:  # noqa: BLE001
        logger.info("playwright not installed — skipping designed card")
        return None
    out = s.audio_dir.parent / "cards"
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"brief-{brief_id}.png"
    url = f"http://localhost:8788/og/brief/{brief_id}"
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 1200, "height": 630})
            page.goto(url, wait_until="networkidle")
            page.screenshot(path=str(path))
            browser.close()
        return path
    except Exception as e:  # noqa: BLE001
        logger.warning("card render failed: {}", e)
        return None
