# Runbook — start / stop / inspect Meridian

## Layout
- `MERIDIAN_HOME` = repo root (defaults there; override with the env var).
- Source of truth: `data/meridian.db` (SQLite WAL). Bulk OHLCV: `data/parquet/`.
- Secrets: `.env` (chmod 600, gitignored). Non-secret config: `config/meridian.yaml`.
- Logs: `logs/meridian_YYYY-MM-DD.log` (structured JSON, 14-day rotation).

## Run the daemon (any OS)

```bash
# one-time
python -m venv .venv && .venv/Scripts/pip install -r requirements-core.txt   # POSIX: .venv/bin/pip
cp .env.example .env            # fill in what you have; everything degrades without keys

# boot (PYTHONPATH=src puts the package on the path without an install; or run `pip install -e .`)
PYTHONPATH=src MERIDIAN_PORT=8788 MERIDIAN_HOME="$PWD" .venv/Scripts/python -m meridian.app
# health: curl http://localhost:8788/api/health
```

Autoreload for development:
`PYTHONPATH=src uvicorn meridian.app:create_app --factory --reload --port 8788`

For the always-on macOS (launchd) deployment, see
[deployment-macos.md](deployment-macos.md).

## Inspect
```bash
curl -s localhost:8788/api/health            | python -m json.tool   # health wall
curl -s localhost:8788/api/system/info                                # version, keys present
curl -s localhost:8788/api/system/scheduler                           # jobs + next run times
curl -s localhost:8788/api/system/connectors                          # connector health
curl -s localhost:8788/api/system/costs                               # LLM spend vs budget
curl -s localhost:8788/api/system/notifications                       # delivery log
python manage.py health                                               # same snapshot, no daemon
```

## Notifications
```bash
python -m meridian.notify "test" -p P1 --title Meridian --path /briefs/1   # respects quiet hours
python -m meridian.notify "test" -p P0 --force                             # bypass quiet + dedupe
```
Channels enable themselves when their keys are in `.env` (ntfy / Pushover / iMessage). With
none configured, sends are logged as `dry_run`; within quiet hours P1/P2 are `queued`.

## Common tasks
```bash
python manage.py migrate            # apply pending migrations (idempotent)
python manage.py seed               # re-seed instruments after editing the watchlist

# --- market data ---
python manage.py backfill NVDA SPY  # 5y daily history -> Parquet (omit tickers for the full watchlist)
python manage.py refresh-quotes     # pull latest quotes now (prices/futures/crypto)
python manage.py ingest crypto      # run one connector now (prices futures crypto alpaca
                                    #   rss gdelt finnhub edgar fred calendar predmkt sentiment shorts stooq)

# --- signals ---
python manage.py signals            # recompute indicators + breadth + regime

# --- live desk & retrospective validation (V2, all keyless) ---
python manage.py refresh            # live pull: quotes + Kalshi + RSS + EDGAR; per-connector
                                    #   summary; partial failures never crash. --dry-run previews.
python manage.py backfill-regime --years 2   # recompute the 2y composite regime -> regime_history
python manage.py backtest-rules     # Brier-score config/rules.yaml over history -> rule_predictions
# make demo  = migrate + boot on the committed snapshot;  make live = refresh + boot

# --- briefs ---
python manage.py brief-now morning  # morning|midday|closing|sunday|crypto|event_flash

# --- conviction ---
python manage.py resolve-predictions  # auto-resolve due predictions -> Brier

# --- ops ---
python manage.py backup             # sqlite .backup + gzip + Parquet mirror -> data/backups/
python manage.py restore-drill      # back up, restore to scratch, verify counts + integrity (exit 0 = pass)
```

## Endpoints map (all under the daemon)
| Area | Routes |
|---|---|
| System | `/api/health` `/api/system/{info,costs,agent-runs,connectors,scheduler,notifications}` |
| Markets | `/api/markets` `/api/markets/:t` `/api/markets/:t/history?range=` |
| News/Filings | `/api/news` `/api/news/clusters` `/api/filings` `/api/filings/{diffs,insiders}` |
| Signals/Macro | `/api/signals` `/api/signals/regime/history` `/api/macro` `/api/macro/prediction-markets` |
| Briefs | `/api/briefs` `/api/briefs/:id` `/api/briefs/latest?kind=` |
| Conviction | `/api/memos` `/api/memos/:id` (POST create / PATCH / transition / redteam / predictions) `/api/journal` `/api/calibration` |
| Live/Feed | `/api/sse` `/feed.xml` `/api/audio/latest` `/og/brief/:id` |

## Config the operator edits most
- `config/meridian.yaml` — watchlist tiers, budgets, brief times, quiet hours, model tiers.
- `config/portfolio.yaml` — positions + cost basis + `memo_id` links (gitignored; copy from `.example`).
- `config/alerts.yaml` — the alert-rule DSL.
- Then `python manage.py seed` (or restart the daemon) to pick up watchlist changes.

## Build the dashboard
```bash
cd web && npm install && npm run build     # -> web/dist, served by the daemon at /
# dev with hot reload + API proxy to :8788:
cd web && npm run dev                       # http://localhost:5273
```

## Kill a stray dev daemon (Windows)
```bash
netstat -ano | grep ':8788 .*LISTENING'    # find PID
taskkill //F //PID <pid>
```
