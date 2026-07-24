"""Morning-brief audio.

Composer produces a ~2.5-min conversational script (numbers rounded) → local Piper TTS
(fast on Apple Silicon, free, private) → data/audio/YYYY-MM-DD.m4a. On a box without
Piper/ffmpeg (e.g. Windows dev) it degrades to saving the script text and leaving audio
for the Mini (docs/DECISIONS.md D-009). The podcast feed links whatever exists.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

from loguru import logger

from ..config import Settings, get_settings


def _spoken_script(markdown: str) -> str:
    """Turn a brief into a conversational, roundable spoken script."""
    lines = markdown.splitlines()
    parts: list[str] = ["Good morning. Here's your Meridian brief."]
    section = ""
    for ln in lines:
        s = ln.strip()
        if s.startswith("## "):
            section = s[3:].split("(")[0].strip()
            if section.lower() in (
                "tl;dr",
                "portfolio check",
                "macro pulse",
                "watchlist movers & setups",
            ):
                parts.append(f"{section}.")
            continue
        if s.startswith(("- ", "* ")) and section:
            text = _despeak(s[2:])
            if text:
                parts.append(text)
    parts.append("That's your brief. Not investment advice.")
    return " ".join(parts[:40])


def _despeak(s: str) -> str:
    s = re.sub(r"\[[a-z]:[^\]]+\]", "", s)  # drop evidence markers
    s = re.sub(r"[*_`|]", "", s)
    s = re.sub(r"\$([\d,]+)\.\d+", r"$\1", s)  # round cents off
    s = re.sub(r"(\d+\.\d)\d+%", r"\1%", s)  # round pct to 1dp
    return re.sub(r"\s+", " ", s).strip()


def generate_audio(brief_id: int, settings: Settings | None = None) -> dict:
    s = settings or get_settings()
    from ..db import get_db

    db = get_db(s)
    row = db.query_one("SELECT markdown, for_date FROM briefs WHERE id=?", (brief_id,))
    if not row:
        return {"ok": False, "error": "brief not found"}
    script = _spoken_script(row["markdown"])
    s.audio_dir.mkdir(parents=True, exist_ok=True)
    stamp = row["for_date"] or "latest"
    script_path = s.audio_dir / f"{stamp}.txt"
    script_path.write_text(script, encoding="utf-8")

    audio_path = _synthesize(script, s.audio_dir / f"{stamp}", s)
    if audio_path:
        db.execute("UPDATE briefs SET audio_path=? WHERE id=?", (str(audio_path), brief_id))
        db.set_setting("audio.latest", str(audio_path))
        return {"ok": True, "audio": str(audio_path), "script_chars": len(script)}
    logger.info("audio degraded to script only (Piper/ffmpeg unavailable)")
    db.set_setting("audio.latest_script", str(script_path))
    return {"ok": True, "audio": None, "script": str(script_path), "degraded": True}


def _synthesize(script: str, out_stem: Path, s: Settings) -> Path | None:
    piper = shutil.which("piper")
    ffmpeg = shutil.which("ffmpeg")
    if not piper:
        return None
    wav = out_stem.with_suffix(".wav")
    try:
        subprocess.run(
            [piper, "--model", "en_US-lessac-medium", "--output_file", str(wav)],
            input=script.encode(),
            check=True,
            capture_output=True,
            timeout=120,
        )
        if ffmpeg:
            m4a = out_stem.with_suffix(".m4a")
            subprocess.run(
                [ffmpeg, "-y", "-i", str(wav), "-c:a", "aac", "-b:a", "64k", str(m4a)],
                check=True,
                capture_output=True,
                timeout=120,
            )
            wav.unlink(missing_ok=True)
            return m4a
        return wav
    except Exception as e:  # noqa: BLE001
        logger.warning("piper synthesis failed: {}", e)
        return None
