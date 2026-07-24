# MERIDIAN make targets. Uses uv on the Mac Mini; `python manage.py`
# equivalents exist for machines without make/uv (see docs/RUNBOOK.md).
.DEFAULT_GOAL := help
PORT ?= 8788
PY := uv run

help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

setup: ## create venv + install all deps (core + extras + dev)
	uv sync --extra extras --extra dev

dev: ## run the daemon with autoreload
	MERIDIAN_PORT=$(PORT) $(PY) uvicorn meridian.app:create_app --factory --reload --port $(PORT)

run: ## run the daemon (production style)
	MERIDIAN_PORT=$(PORT) $(PY) meridiand

migrate: ## apply DB migrations
	$(PY) python manage.py migrate

seed: ## seed instruments from watchlist
	$(PY) python manage.py seed

backfill: ## 5y daily history -> Parquet (TICKERS="NVDA MSFT" optional)
	$(PY) python manage.py backfill $(TICKERS)

signals: ## recompute indicators / breadth / regime
	$(PY) python manage.py signals

brief-now: ## generate a brief now (KIND=morning|closing|sunday|...)
	$(PY) python manage.py brief-now $(KIND)

backup: ## sqlite .backup + gzip + Parquet mirror
	$(PY) python manage.py backup

restore-drill: ## verify a backup restores cleanly (Phase 8 AC)
	$(PY) python manage.py restore-drill

test: ## run the test suite
	$(PY) pytest -q

lint: ## ruff check + format check
	$(PY) ruff check src tests
	$(PY) ruff format --check src tests

fix: ## ruff autofix + format
	$(PY) ruff check --fix src tests
	$(PY) ruff format src tests

build-web: ## build the dashboard to web/dist
	cd web && (pnpm install && pnpm build) || (npm install && npm run build)

install-launchd: ## install launchd agents (Mac Mini only)
	bash scripts/install_launchd.sh

deploy: ## git pull -> deps -> migrate -> build web -> restart daemon
	git pull --ff-only
	uv sync --extra extras
	$(PY) python manage.py migrate
	$(MAKE) build-web
	launchctl kickstart -k gui/$$(id -u)/com.meridian.daemon || true

.PHONY: help setup dev run migrate seed backfill signals brief-now test lint fix build-web install-launchd deploy
