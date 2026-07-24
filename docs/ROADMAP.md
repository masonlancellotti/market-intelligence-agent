# Roadmap & limitations

An honest account of what is verified today, what is a deployment step rather than a code gap,
and what is deliberately deferred.

## Verified on any host

These are demonstrated by the test suite and by running the real system against the committed
snapshot, with no API keys:

- **55 tests pass; `ruff` clean.** Indicators match a pandas reference to zero difference and
  are property-tested (RSI ∈ [0, 100], ATR ≥ 0).
- **Signal engine** recomputes indicators, breadth, and the regime composite over the full
  universe; the regime bucket is stable across recomputes (hysteresis is unit-tested).
- **Conviction Desk lifecycle**: a thin memo is blocked from going Live below the gate
  threshold; a typed override transitions *and* journals the reason; a fleshed-out memo passes,
  triggers the red team, and its predictions auto-resolve and plot a calibration curve.
- **Briefs in deterministic mode**: morning, closing, Sunday, crypto, and event-flash briefs
  generate from the committed data with 100% citation validity; the code fact-checker catches
  an injected false number and correctly ignores signed percentage changes.
- **Ops**: the backup → restore → verify drill passes (integrity check ok, source and restored
  row counts match); the health wall is green immediately on boot.
- **Dashboard** builds clean (`tsc -b && vite build`) and is served by the daemon as a SPA with
  deep-link fallback.

## Deployment steps (require the always-on host, not code changes)

These are exercised on the target macOS host and are documented in
[deployment-macos.md](deployment-macos.md):

- Real push delivery to a phone via ntfy/Pushover.
- launchd crash/reboot survival and the watchdog P0 path.
- On-device PWA install to the home screen.
- Piper-rendered audio brief and podcast auto-download.
- Designed push-card image attachment (Playwright screenshot).
- A multi-day soak to tune alert thresholds and the noise governor against real volume.

## Optional keys (all free-tier)

The system runs fully without any of these; each simply upgrades a path:

- `ANTHROPIC_API_KEY` — enables the LLM analyst/composer path (otherwise deterministic
  template briefs).
- `FRED_API_KEY` — FRED macro series.
- `ALPACA_KEY_ID` / `ALPACA_SECRET_KEY` — real-time IEX equity quotes.
- `FINNHUB_KEY` — deeper company news.

## Deferred backlog

Explicitly out of scope for now, in rough priority order:

- Earnings-call transcript ingestion with tone-delta analysis.
- Options-flow data (paid feeds).
- A backtest harness that scores alert-rule quality (signal hit-rate reports).
- Brokerage read-only position sync.
- A local LLM fallback (e.g. MLX) for triage.
- A two-way command interface ("brief now", "status <ticker>").
