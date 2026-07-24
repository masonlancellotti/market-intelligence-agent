# Decision records

Architecture decision records (ADRs). Each entry captures an engineering choice, the
context that forced it, and the substitute adopted. IDs are stable and referenced from code
comments. Dates are when the decision was made.

---

### D-001 · 2026-07-05 · Cross-platform development, macOS deployment target

The production target is an always-on Apple Silicon Mac Mini, but the codebase is developed
and tested cross-platform. Everything is written path-agnostic behind `MERIDIAN_HOME`, and all
platform-agnostic code (backend, connectors, signals, agents, dashboard) runs and is verified
on any OS. macOS-only pieces (launchd process management, Piper TTS, `tailscale cert`,
Playwright card rendering, iMessage) are isolated as deployment artifacts and documented in
[deployment-macos.md](deployment-macos.md). No architectural choice depends on the host OS.

### D-002 · 2026-07-05 · `pip` + `venv` for local development; `uv` for deployment

`pyproject.toml` is the dependency source of truth and is fully `uv`-compatible. Where `uv`
is unavailable, a `.venv` created with `python -m venv` plus `requirements-core.txt` mirrors
the core dependencies. Zero code impact.

### D-003 · 2026-07-05 · `sqlite-vec` optional; Python cosine fallback for vector search

News embeddings are stored as a `float32` BLOB in `news_items.embedding`. When the
`sqlite-vec` extension loads, an accelerated in-DB vector path is available; when it does not,
retrieval degrades to brute-force cosine in Python. At the news volumes involved (a few
thousand rows) the fallback is fine, and no schema change is needed to switch paths.

### D-004 · 2026-07-05 · Default daemon port 8788

The daemon serves on port 8788 by default (override with `MERIDIAN_PORT`) to avoid colliding
with other local services that commonly claim 8787. Deep links and deployment configuration
use the same value.

### D-005 · 2026-07-05 · Local embeddings model is optional at runtime

The embedding provider is pluggable: it uses `sentence-transformers/all-MiniLM-L6-v2` when
installed, and otherwise a deterministic hashing embedding that still supports
dedup/clustering by cosine (lower quality, zero heavy dependencies). Clustering also always
has a URL-canonicalization + title-MinHash path regardless of the embedding backend.

### D-006 · 2026-07-05 · Python 3.13 supported; 3.12 is the floor

`pyproject.toml` pins `>=3.12`. The code uses no 3.13-only syntax, so either interpreter runs
the system. Noted for completeness.

### D-007 · 2026-07-05 · yfinance is the working primary for daily history

Stooq's CSV endpoint began returning a browser-challenge page rather than CSV from some
networks, so it cannot be scraped headlessly there. yfinance is therefore the primary
backfill/refresh source; the Stooq connector remains implemented and registered but degrades
silently (reports zero items, never alarms) and is off the default schedule. It can be
promoted back where the endpoint is reachable. Backfill is verified end-to-end at 25 tickers /
33,066 daily rows / 0 integrity violations.

### D-008 · 2026-07-05 · Briefs run in deterministic mode without an LLM key

With no `ANTHROPIC_API_KEY`, the deterministic template path is the active brief renderer:
briefs are assembled directly from the structured context, still fully cited with evidence
markers, and the code fact-checker (marker existence + numeric match at display precision)
runs on every brief. The LLM analyst/composer path is fully wired and correct for when a key
is present. Economic-surprise scoring is approximated as
`(actual − consensus) / max(|consensus| · 0.1, 0.1)` where a historical standard deviation is
unavailable — adequate to fire event flashes, refinable with more history.

### D-009 · 2026-07-05 · Audio and designed cards degrade off-macOS

`audio.py` always writes the spoken-word *script* and synthesises audio only when `piper` and
`ffmpeg` are on the PATH; the podcast feed links whatever exists. The `/og/brief/:id` card
route renders platform-agnostic HTML and is screenshotted by Playwright when available,
degrading to no image attachment otherwise. No feature is lost, only the media rendering.

### D-010 · 2026-07-05 · Frontend build works with npm or pnpm

`package.json` is pnpm-compatible; the Makefile tries pnpm and falls back to npm. `tsc -b &&
vite build` passes clean either way.
