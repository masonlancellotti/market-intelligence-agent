"""Private podcast feed + audio serving.

`/feed.xml` is an RSS podcast feed of morning briefs (audio enclosures when present) so
Mason subscribes in Apple Podcasts over Tailscale and it auto-downloads each morning.
`/api/audio/latest` serves the latest rendered audio (or the spoken script as a fallback).
`/og/brief/{id}` renders a designed card used for screenshot push attachments.
"""

from __future__ import annotations

from pathlib import Path
from xml.sax.saxutils import escape

from fastapi import APIRouter
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, Response

from ..config import get_settings
from ..db import get_db
from ..util import parse_iso

router = APIRouter()


@router.get("/feed.xml")
def feed() -> Response:
    s = get_settings()
    base = s.base_url().rstrip("/")
    db = get_db()
    briefs = db.query(
        "SELECT id, kind, for_date, markdown, audio_path, created_at FROM briefs "
        "WHERE kind IN ('morning','sunday') ORDER BY created_at DESC LIMIT 60"
    )
    items = []
    for b in briefs:
        title = f"Meridian {b['kind'].title()} — {b['for_date']}"
        link = f"{base}/briefs/{b['id']}"
        desc = _first_lines(b["markdown"], 6)
        pub = _rfc822(b["created_at"])
        enclosure = ""
        if b["audio_path"] and Path(b["audio_path"]).exists():
            size = Path(b["audio_path"]).stat().st_size
            enclosure = (
                f'<enclosure url="{base}/api/audio/{b["id"]}" length="{size}" type="audio/mp4"/>'
            )
        items.append(
            f"<item><title>{escape(title)}</title><link>{escape(link)}</link>"
            f'<guid isPermaLink="false">meridian-{b["id"]}</guid>'
            f"<pubDate>{pub}</pubDate><description>{escape(desc)}</description>{enclosure}</item>"
        )
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd">'
        "<channel><title>Meridian Morning Brief</title>"
        f"<link>{base}</link><language>en-us</language>"
        "<description>Private market-intelligence briefs for Mason. Not investment advice.</description>"
        "<itunes:author>Meridian</itunes:author>"
        f"{''.join(items)}</channel></rss>"
    )
    return Response(content=xml, media_type="application/rss+xml")


@router.get("/api/audio/latest")
def audio_latest():
    db = get_db()
    path = db.get_setting("audio.latest")
    if path and Path(path).exists():
        return FileResponse(path, media_type="audio/mp4")
    script = db.get_setting("audio.latest_script")
    if script and Path(script).exists():
        return PlainTextResponse(Path(script).read_text(encoding="utf-8"))
    return PlainTextResponse("No audio yet.", status_code=404)


@router.get("/api/audio/{brief_id}")
def audio_for(brief_id: int):
    db = get_db()
    row = db.query_one("SELECT audio_path FROM briefs WHERE id=?", (brief_id,))
    if row and row["audio_path"] and Path(row["audio_path"]).exists():
        return FileResponse(row["audio_path"], media_type="audio/mp4")
    return PlainTextResponse("No audio for this brief.", status_code=404)


@router.get("/og/brief/{brief_id}", response_class=HTMLResponse)
def og_card(brief_id: int) -> HTMLResponse:
    """Designed OG card (1200x630) — Playwright screenshots this for push attachments."""
    db = get_db()
    row = db.query_one("SELECT kind, for_date, markdown FROM briefs WHERE id=?", (brief_id,))
    if not row:
        return HTMLResponse("<h1>not found</h1>", status_code=404)
    regime = db.get_setting("regime.latest", {}) or {}
    tldr = _tldr_lines(row["markdown"])
    html = f"""<!doctype html><html><head><meta charset="utf-8"><style>
      * {{ margin:0; box-sizing:border-box; }}
      body {{ width:1200px; height:630px; background:#000; color:#fff;
        font-family:-apple-system,'SF Pro Text',sans-serif; padding:64px; display:flex; flex-direction:column; }}
      .k {{ color:#8e8e93; font-size:26px; letter-spacing:.04em; text-transform:uppercase; }}
      h1 {{ font-size:64px; font-weight:800; letter-spacing:-.02em; margin:8px 0 28px; }}
      .regime {{ display:inline-block; padding:8px 20px; border-radius:100px; font-size:30px; font-weight:700;
        background:{"#30d15833" if (regime.get("score") or 0) >= 65 else "#ff9f0a33" if (regime.get("score") or 0) > 35 else "#ff453a33"};
        color:{"#30d158" if (regime.get("score") or 0) >= 65 else "#ff9f0a" if (regime.get("score") or 0) > 35 else "#ff453a"}; }}
      ul {{ margin-top:36px; font-size:34px; line-height:1.5; list-style:none; }}
      li {{ margin:14px 0; padding-left:36px; position:relative; }}
      li:before {{ content:'—'; position:absolute; left:0; color:#0a84ff; }}
      .ft {{ margin-top:auto; color:#48484a; font-size:22px; font-family:'SF Mono',monospace; }}
    </style></head><body>
      <div class="k">Meridian · {escape(row["kind"].title())} · {escape(row["for_date"] or "")}</div>
      <h1>Morning Brief</h1>
      <div class="regime">Regime {regime.get("bucket", "—")} {regime.get("score", "")}/100</div>
      <ul>{"".join(f"<li>{escape(t)}</li>" for t in tldr[:3])}</ul>
      <div class="ft">mini.tailnet.ts.net · not investment advice</div>
    </body></html>"""
    return HTMLResponse(html)


def _first_lines(md: str, n: int) -> str:
    return "\n".join(ln for ln in md.splitlines() if ln.strip() and not ln.startswith("#"))[:600]


def _tldr_lines(md: str) -> list[str]:
    import re

    out, cap = [], False
    for ln in md.splitlines():
        if ln.lower().startswith("## tl;dr"):
            cap = True
            continue
        if cap and ln.startswith("## "):
            break
        if cap and ln.strip().startswith(("-", "*")):
            out.append(re.sub(r"\[[a-z]:[^\]]+\]|\*\*|_", "", ln.strip().lstrip("-* ")).strip())
    return out


def _rfc822(iso: str | None) -> str:
    dt = parse_iso(iso)
    return dt.strftime("%a, %d %b %Y %H:%M:%S +0000") if dt else ""
