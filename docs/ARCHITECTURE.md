# Architecture

Meridian is a single long-lived daemon that ingests market data, computes signals,
runs an LLM-assisted analysis pipeline, and serves everything through a React PWA. This
document describes how the pieces fit together and why the boundaries are drawn where
they are.

## System overview

```
                       ┌─────────────────────────────────────────────────┐
                       │                  meridiand                       │
                       │        FastAPI + APScheduler, asyncio            │
 ┌───────────────┐     │  ┌────────────┐   ┌───────────┐  ┌───────────┐  │
 │ External data │────▶│  │ Connectors │──▶│  SQLite   │◀─│  Signal   │  │
 │ news · EDGAR  │     │  │ (pull/poll)│   │ (WAL) +   │  │  engine   │  │
 │ FRED · prices │     │  └────────────┘   │ Parquet   │  └─────┬─────┘  │
 │ crypto · cal  │     │                   └─────┬─────┘        │        │
 └───────────────┘     │                         │              │        │
                       │                  ┌──────▼──────────────▼─────┐  │
                       │                  │        Agent layer        │  │
                       │                  │ triage → analysts → red   │  │
                       │                  │ team → composer → checker │  │
                       │                  └──────┬───────────────┬────┘  │
                       │      ┌──────────────────┤               │       │
                       │ ┌────▼─────┐      ┌─────▼─────┐   ┌─────▼────┐  │
                       │ │ Briefs · │      │ Alerts &  │   │ REST +   │  │
                       │ │ dossiers │      │ notifier  │   │ SSE API  │  │
                       │ │ · memos  │      └─────┬─────┘   └─────┬────┘  │
                       │ └──────────┘            │               │       │
                       └────────────────────────┼───────────────┼───────┘
                                                 │               │
                                      ┌──────────▼────┐   ┌──────▼─────────┐
                                      │ ntfy/Pushover │   │ Dashboard PWA  │
                                      │ push channels │   │ (all devices)  │
                                      └───────────────┘   └────────────────┘
```

A single process (`meridiand`) owns scheduling, ingestion, signals, agents, and the API.
Heavy one-shot jobs (history backfills, the weekly deep-dive) run as spawned subprocesses
so the daemon never blocks. One SQLite database in WAL mode is the source of truth for
everything except bulk OHLCV history, which lives in Parquet and is queried through DuckDB.

## Design principles

1. **Trustworthy over clever.** Every number a brief shows is traceable to a stored
   evidence row. Stale data is labelled stale; failed connectors are visible, never
   silent. LLM output is fact-checked against stored values before it is published.
2. **Disciplined by construction.** The system's job is not to generate trade ideas but
   to make a decision process repeatable: thesis → evidence → red-team → invalidation
   level → sized entry → journaled outcome → calibration feedback.
3. **Quiet.** High signal-to-noise. Adaptive thresholds, deduplication, digest batching,
   and a noise governor keep alert volume honest.
4. **Local-first and cheap.** Data lives in SQLite/Parquet on one machine. Free-tier data
   sources by default. LLM spend is governed by a hard daily budget, and the whole system
   degrades to a fully deterministic, zero-key mode when no API keys are present.
5. **Human-in-the-loop, always.** Meridian never trades and never holds write access to a
   brokerage. It prepares; the operator decides.

## Component boundaries

| Layer | Package | Responsibility |
|---|---|---|
| Daemon | `meridian.app` | FastAPI factory, lifespan, APScheduler wiring, static serving |
| Config | `meridian.config` | `.env` secrets + `meridian.yaml` merged into one frozen `Settings` |
| Storage | `meridian.db` | SQLite (WAL) connection-per-use, numbered-SQL migration runner |
| Connectors | `meridian.connectors` | One module per source; uniform retry + circuit breaker |
| Signals | `meridian.signals` | Indicators, breadth, regime composite, alert-rule DSL |
| Agents | `meridian.agents` | LLM runner (structured tool-use, budget governor), triage |
| Briefs | `meridian.briefs` | Analysts, composer, fact-checker, templates, audio, hedge module |
| Conviction | `meridian.conviction` | Memos, gate checklist, red team, predictions, calibration |
| Notify | `meridian.notify` | Router (dedupe/quiet-hours/fan-out) + channels + standalone CLI |
| API | `meridian.api` | REST routers under `/api/*` plus one SSE channel |
| Ops | `meridian.ops` | Health, cost governance, backup/restore, scheduler registry |

## Storage model

SQLite (WAL mode) is the single source of truth. Connections are opened per use with
`check_same_thread=False` so the APScheduler thread pool and the asyncio loop can share the
database. Schema is applied by a small numbered-SQL migration runner (`migrations/00xx_*.sql`)
— no ORM, no migration framework.

Key table groups:

- **Instruments & quotes** — `instruments`, `quotes_latest`. Bulk OHLCV history is *not*
  stored in SQLite; it lives in `data/parquet/{daily,intraday}/{ticker}.parquet` and is read
  through DuckDB/polars. SQLite keeps only the rolling hot window and the latest quote.
- **News & filings** — `news_items` (with an embedding BLOB for clustering/retrieval),
  `news_clusters`, `filings`, `filing_diffs`, `insider_trades`.
- **Macro** — `macro_series`, `macro_points`, `econ_events`, `prediction_markets`.
- **Signals & alerts** — `signals`, `alerts`.
- **Briefs & memory** — `briefs`, `dossiers` (per-ticker living memory patched incrementally).
- **Conviction** — `memos`, `memo_predictions`, `journal_entries`.
- **Telemetry** — `agent_runs` (tokens + cost per LLM call), `connector_health`, `settings`.

Vector search over `news_items.embedding` uses `sqlite-vec` when the extension loads and
degrades to brute-force cosine in Python otherwise — correctness preserved, only speed lost.

## Ingestion connectors

Every connector subclasses `BaseConnector`: an async `fetch()`, uniform exponential backoff,
a per-connector circuit breaker (opens after repeated failures and records
`connector_health.circuit_open_until`), and freshness stamping. A connector failing never
takes down the daemon or silently zeroes out data — stale rows keep their last value with
`is_stale=1`.

Sources span equities/ETF quotes and daily history, futures and index proxies, crypto
(spot + funding/sentiment context), news (RSS, a news API, and GDELT for macro-theme
breadth), SEC EDGAR (current-feed polling, submission documents, Form 4 insider parsing
with cluster detection), FRED macro series, an economic calendar, prediction markets
(Kalshi + Polymarket), sentiment indices, and FINRA short data. All default sources are
free-tier; each connector marks itself `disabled` in the health wall when its key is absent.

## Signal engine

- **Indicators** (nightly on daily bars, intraday subset during market hours): moving
  averages, RSI (Wilder), MACD, ATR/ATR%, Bollinger bands + bandwidth percentile, Donchian
  channels, 52-week distance, realized volatility, volume z-score, gap %, drawdown from ATH,
  relative strength vs a benchmark, and golden/death-cross and range-compression events.
  Indicators are verified against a pandas reference to zero difference and property-tested
  (RSI ∈ [0, 100], ATR ≥ 0).
- **Breadth & internals**: percent above 50/200-day moving averages, advancers/decliners,
  new highs minus lows, sector relative-strength ranking, a rolling correlation matrix, and a
  correlation-shift detector.
- **Regime composite (0–100)**: a weight-renormalising z-score blend of volatility term
  structure, high-yield credit spreads, the yield curve, the dollar, breadth, credit-sensitive
  relative strength, blended fear/greed, and financial conditions. Buckets (Risk-On / Neutral /
  Risk-Off) carry hysteresis to prevent flapping; transitions raise an alert and reweight brief
  emphasis.
- **Alert rules**: a declarative DSL in `config/alerts.yaml`. Each rule has a scope, a
  safe-evaluated boolean expression over named signal variables, a priority, a message
  template, and throttle/cooldown controls. A noise governor collapses low-priority alerts
  into a digest and raises thresholds when volume spikes.

## Agent layer

The agent layer is an **LLM-assisted verification and synthesis pipeline**, not an
autonomous trader. A single runner (`agents/runner.py`) is the one entry point for every
model call: it forces structured tool-use output against a JSON schema, applies prompt
caching to system blocks, enforces the hard daily budget *before* spending, and logs tokens
and cost to `agent_runs` afterward.

Roles are cost-tiered by task difficulty (a cheap model for high-volume triage, a mid model
for analysts and the composer, a top model for red-team and calibration reviews). Bake-in
prompt rules keep the pipeline honest: numbers come only from the structured data block
(never from model memory), every factual claim carries an evidence id, forward-looking
statements carry an explicit probability and horizon, and the composer is the only role that
emits markdown.

**Graceful degradation is a first-class feature.** With no `ANTHROPIC_API_KEY`, the entire
pipeline degrades to deterministic heuristics and a template renderer: triage falls back to
rule-based materiality scoring, and briefs are assembled directly from the structured context
as data-dense, fully-cited markdown. The code fact-checker — which validates that every
evidence marker resolves and every numeric claim matches its stored value at display
precision — runs on both the LLM and the degraded output. This is what makes the committed
demo run end-to-end at $0 with zero keys.

## Conviction Desk

The Conviction Desk is the discipline core and the reason the project exists.

- **Memo lifecycle**: `Research → Staged → Live → Closed`, shown as a kanban. A conviction
  memo is the atomic unit — no position without a memo.
- **The gate**: a 10-item checklist scored objectively from memo fields, weighted so that the
  invalidation level and written exit plan carry the most points. A memo cannot move to Live
  below the gate minimum without a typed override reason, which is itself journaled.
- **Red team**: a top-tier model builds the strongest opposing case at Staged→Live and on a
  weekly cadence for Live memos. The verdict is pinned to the memo so the dashboard shows the
  bear case next to the thesis permanently.
- **Predictions & calibration**: every memo logs at least two falsifiable predictions with a
  probability and a horizon. Price-checkable predictions auto-resolve from bar data; Brier
  scores accumulate into a calibration curve (predicted vs realized frequency, bucketed) and
  hit-rate breakdowns. A periodic calibration review summarises where judgment is
  over/under-confident and which edge types actually work. This is the feature that compounds.
- **Journal**: every decision gets a timestamped entry; a portfolio change detected without a
  journal entry triggers a nag.

## Outputs

Briefs render to three surfaces: the dashboard (canonical), a push notification (title +
short TL;DR + deep link), and a markdown archive. The daily set is a morning brief (the
flagship), a conditional midday pulse, a closing wrap, and a real-time event flash on a
material surprise. The weekly set adds a deeper Sunday setup (which re-underwrites every Live
memo and refreshes hedge ideas) and a crypto weekend pulse. The morning brief can additionally
be synthesised to audio and served as a private podcast feed.

## Notifications

`notify/router.py` is the single choke point: deduplication by key, per-rule throttles,
quiet-hours queueing, channel fan-out, and delivery logging. Priorities map to channels —
P0 bypasses quiet hours on a critical channel, P1 respects quiet hours, P2 rolls into the
next digest. A standalone `python -m meridian.notify` CLI works even when the daemon is down,
which is what the deployment watchdog uses.

## Dashboard

A React 19 + TypeScript + Vite PWA, served as a static bundle by FastAPI. The design system
is built on CSS design tokens (typography scale, system color palette in light and dark,
materials, spring motion) before any page, so the interface is consistent by construction.
Data flows over REST (`/api/*`) with one SSE channel for live quotes, alerts, and
brief-ready events. Pages cover the Today dashboard, markets and market detail, signals,
macro, filings, briefs, the Conviction kanban, the journal/calibration view, and a system
health wall.

## Runtime shape and cost

Steady-state LLM spend is governed by hard daily and monthly caps; at the cap the agents
degrade rather than overrun. Data sources are free-tier, and the deterministic degrade path
means the system is fully operable at $0. See [DECISIONS.md](DECISIONS.md) for the recorded
engineering trade-offs and [ROADMAP.md](ROADMAP.md) for what is verified versus deferred.
