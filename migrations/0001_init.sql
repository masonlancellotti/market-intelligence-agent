-- MERIDIAN schema v1 (PLAN.md §6). SQLite, WAL mode.
-- Conventions: timestamps are ISO-8601 UTC TEXT; *_json columns hold JSON TEXT;
-- money is REAL USD; bulk OHLCV lives in Parquet, NOT here (§6 retention note).

-- ---------------------------------------------------------------------------
-- Instruments & prices
-- ---------------------------------------------------------------------------
CREATE TABLE instruments (
    id          INTEGER PRIMARY KEY,
    ticker      TEXT NOT NULL UNIQUE,
    name        TEXT,
    kind        TEXT,                 -- equity|etf|crypto|index|future_proxy
    exchange    TEXT,
    cik         TEXT,                 -- zero-padded 10-digit for EDGAR
    sector      TEXT,
    tier        TEXT,                 -- holding|active|monitor|benchmark
    meta_json   TEXT DEFAULT '{}'
);
CREATE INDEX idx_instruments_tier ON instruments(tier);
CREATE INDEX idx_instruments_cik  ON instruments(cik);

-- Rolling hot window + latest quote only. Bulk history is in Parquet.
CREATE TABLE quotes_latest (
    instrument_id INTEGER PRIMARY KEY REFERENCES instruments(id) ON DELETE CASCADE,
    price       REAL,
    prev_close  REAL,
    day_open    REAL,
    day_high    REAL,
    day_low     REAL,
    volume      REAL,
    ts          TEXT,
    source      TEXT,
    is_stale    INTEGER DEFAULT 0
);

-- ---------------------------------------------------------------------------
-- News
-- ---------------------------------------------------------------------------
CREATE TABLE news_items (
    id          INTEGER PRIMARY KEY,
    source      TEXT,
    url         TEXT NOT NULL UNIQUE,
    title       TEXT,
    summary     TEXT,
    published_at TEXT,
    fetched_at  TEXT,
    tickers_json TEXT DEFAULT '[]',
    raw_text    TEXT,
    cluster_id  INTEGER,
    embedding   BLOB,                 -- float32 little-endian; cosine in Python / sqlite-vec
    materiality INTEGER,             -- 0..5, set by triage
    category    TEXT,
    triage_json TEXT,
    triaged_at  TEXT
);
CREATE INDEX idx_news_published ON news_items(published_at DESC);
CREATE INDEX idx_news_cluster   ON news_items(cluster_id);
CREATE INDEX idx_news_materiality ON news_items(materiality DESC);
CREATE INDEX idx_news_triaged   ON news_items(triaged_at);

CREATE TABLE news_clusters (
    id          INTEGER PRIMARY KEY,
    rep_item_id INTEGER REFERENCES news_items(id),
    title       TEXT,
    first_seen  TEXT,
    last_seen   TEXT,
    item_count  INTEGER DEFAULT 1
);

-- ---------------------------------------------------------------------------
-- SEC filings & insiders
-- ---------------------------------------------------------------------------
CREATE TABLE filings (
    id          INTEGER PRIMARY KEY,
    accession   TEXT NOT NULL UNIQUE,
    cik         TEXT,
    ticker      TEXT,
    form        TEXT,                 -- 8-K,10-Q,10-K,4,13F,S-1...
    filed_at    TEXT,
    url         TEXT,
    items_json  TEXT DEFAULT '[]',    -- 8-K item codes e.g. ["2.02","7.01"]
    summary     TEXT,
    materiality INTEGER
);
CREATE INDEX idx_filings_ticker ON filings(ticker);
CREATE INDEX idx_filings_filed  ON filings(filed_at DESC);

CREATE TABLE filing_diffs (
    id            INTEGER PRIMARY KEY,
    ticker        TEXT,
    form          TEXT,
    old_accession TEXT,
    new_accession TEXT,
    section       TEXT,               -- risk_factors | mda | ...
    diff_summary  TEXT,
    significance  INTEGER,            -- 0..5
    created_at    TEXT
);
CREATE INDEX idx_filing_diffs_ticker ON filing_diffs(ticker);

CREATE TABLE insider_trades (
    id           INTEGER PRIMARY KEY,
    filing_id    INTEGER REFERENCES filings(id),
    ticker       TEXT,
    insider_name TEXT,
    role         TEXT,
    action       TEXT,                -- P (purchase) | S (sale) | A (award)
    shares       REAL,
    price        REAL,
    value_usd    REAL,
    traded_at    TEXT,
    cluster_flag INTEGER DEFAULT 0
);
CREATE INDEX idx_insider_ticker ON insider_trades(ticker);

-- ---------------------------------------------------------------------------
-- Macro & prediction markets
-- ---------------------------------------------------------------------------
CREATE TABLE macro_series (
    series_id    TEXT PRIMARY KEY,    -- FRED id
    name         TEXT,
    units        TEXT,
    freq         TEXT,
    last_updated TEXT
);

CREATE TABLE macro_points (
    series_id TEXT NOT NULL,
    date      TEXT NOT NULL,
    value     REAL,
    PRIMARY KEY (series_id, date)
);

CREATE TABLE econ_events (
    id            INTEGER PRIMARY KEY,
    name          TEXT,
    country       TEXT,
    scheduled_at  TEXT,
    importance    TEXT,               -- low|medium|high
    consensus     TEXT,
    previous      TEXT,
    actual        TEXT,
    released_at   TEXT,
    surprise_score REAL,
    UNIQUE(name, scheduled_at)
);
CREATE INDEX idx_econ_scheduled ON econ_events(scheduled_at);

CREATE TABLE prediction_markets (
    id         INTEGER PRIMARY KEY,
    venue      TEXT,                  -- kalshi|polymarket
    market_id  TEXT,
    question   TEXT,
    yes_prob   REAL,
    prev_prob  REAL,
    volume     REAL,
    category   TEXT,
    fetched_at TEXT,
    UNIQUE(venue, market_id)
);
CREATE INDEX idx_predmkt_category ON prediction_markets(category);

-- ---------------------------------------------------------------------------
-- Signals & alerts
-- ---------------------------------------------------------------------------
CREATE TABLE signals (
    id            INTEGER PRIMARY KEY,
    instrument_id INTEGER REFERENCES instruments(id) ON DELETE CASCADE,
    kind          TEXT NOT NULL,      -- rsi14, macd, atr_pct, regime_score...
    value         REAL,
    params_json   TEXT DEFAULT '{}',
    bar_date      TEXT,
    created_at    TEXT,
    UNIQUE(instrument_id, kind, bar_date)
);
CREATE INDEX idx_signals_kind ON signals(kind, bar_date DESC);

CREATE TABLE alerts (
    id           INTEGER PRIMARY KEY,
    rule_id      TEXT,
    instrument_id INTEGER REFERENCES instruments(id),
    priority     TEXT,                -- P0|P1|P2
    title        TEXT,
    body         TEXT,
    evidence_json TEXT DEFAULT '{}',
    fired_at     TEXT,
    delivered_at TEXT,
    channel      TEXT,
    dedupe_key   TEXT
);
CREATE INDEX idx_alerts_fired  ON alerts(fired_at DESC);
CREATE INDEX idx_alerts_dedupe ON alerts(dedupe_key);

-- ---------------------------------------------------------------------------
-- Briefs & dossiers
-- ---------------------------------------------------------------------------
CREATE TABLE briefs (
    id           INTEGER PRIMARY KEY,
    kind         TEXT,                -- morning|midday|closing|sunday|crypto|event_flash|hedge_note
    for_date     TEXT,
    markdown     TEXT,
    json_payload TEXT,
    citations_json TEXT DEFAULT '{}',
    model        TEXT,
    cost_usd     REAL DEFAULT 0,
    audio_path   TEXT,
    created_at   TEXT,
    delivered_at TEXT
);
CREATE INDEX idx_briefs_kind ON briefs(kind, for_date DESC);

CREATE TABLE dossiers (
    instrument_id  INTEGER PRIMARY KEY REFERENCES instruments(id) ON DELETE CASCADE,
    markdown       TEXT,
    structured_json TEXT DEFAULT '{}',
    version        INTEGER DEFAULT 1,
    updated_at     TEXT
);

-- ---------------------------------------------------------------------------
-- Conviction Desk (PLAN.md §11)
-- ---------------------------------------------------------------------------
CREATE TABLE memos (
    id                INTEGER PRIMARY KEY,
    ticker            TEXT,
    direction         TEXT,           -- long|short|hedge
    status            TEXT DEFAULT 'research', -- research|staged|live|closed
    thesis            TEXT,
    edge_type         TEXT,           -- informational|analytical|behavioral|structural
    catalysts_json    TEXT DEFAULT '[]',
    risks_json        TEXT DEFAULT '[]',
    valuation_json    TEXT DEFAULT '{}',
    entry_plan        TEXT,
    invalidation_level REAL,
    invalidation_rule TEXT,
    size_plan         TEXT,
    checklist_json    TEXT DEFAULT '{}',
    checklist_score   INTEGER,
    redteam_verdict   TEXT,
    override_reason   TEXT,
    opened_at         TEXT,
    staged_at         TEXT,
    live_at           TEXT,
    closed_at         TEXT,
    outcome_json      TEXT,
    created_at        TEXT,
    updated_at        TEXT
);
CREATE INDEX idx_memos_status ON memos(status);
CREATE INDEX idx_memos_ticker ON memos(ticker);

CREATE TABLE memo_predictions (
    id           INTEGER PRIMARY KEY,
    memo_id      INTEGER REFERENCES memos(id) ON DELETE CASCADE,
    claim        TEXT,
    probability  REAL,
    horizon_date TEXT,
    kind         TEXT DEFAULT 'manual',  -- price|manual (price ones auto-resolve)
    resolve_rule TEXT,                    -- e.g. "NVDA >= 150"
    resolution   TEXT,                    -- NULL|true|false
    resolved_at  TEXT,
    brier        REAL,
    created_at   TEXT
);
CREATE INDEX idx_predictions_memo ON memo_predictions(memo_id);
CREATE INDEX idx_predictions_horizon ON memo_predictions(horizon_date);

CREATE TABLE journal_entries (
    id       INTEGER PRIMARY KEY,
    ts       TEXT,
    kind     TEXT,                    -- decision|note|review
    memo_id  INTEGER REFERENCES memos(id),
    markdown TEXT
);
CREATE INDEX idx_journal_memo ON journal_entries(memo_id);
CREATE INDEX idx_journal_ts   ON journal_entries(ts DESC);

-- ---------------------------------------------------------------------------
-- Ops: agent runs, connector health, settings
-- ---------------------------------------------------------------------------
CREATE TABLE agent_runs (
    id            INTEGER PRIMARY KEY,
    agent         TEXT,
    model         TEXT,
    started_at    TEXT,
    ms            INTEGER,
    input_tokens  INTEGER,
    output_tokens INTEGER,
    cost_usd      REAL,
    status        TEXT,               -- ok|error|degraded
    task_ref      TEXT,
    error         TEXT
);
CREATE INDEX idx_agent_runs_started ON agent_runs(started_at DESC);

CREATE TABLE connector_health (
    connector         TEXT PRIMARY KEY,
    last_success      TEXT,
    last_error        TEXT,
    last_error_msg    TEXT,
    error_streak      INTEGER DEFAULT 0,
    circuit_open_until TEXT,
    items_24h         INTEGER DEFAULT 0,
    enabled           INTEGER DEFAULT 1,
    status            TEXT DEFAULT 'unknown'  -- ok|amber|red|disabled
);

CREATE TABLE settings (
    key        TEXT PRIMARY KEY,
    value_json TEXT
);
