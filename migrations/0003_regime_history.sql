-- Regime backfill + rule-backtest tables (V2: historical validation & calibration lab).
-- Both are RETROSPECTIVE research surfaces, kept strictly separate from live forecasts.

-- Daily composite-regime values recomputed over ~2y of keyless yfinance history.
CREATE TABLE IF NOT EXISTS regime_history (
    date            TEXT PRIMARY KEY,   -- YYYY-MM-DD (trading day)
    score           REAL NOT NULL,      -- 0..100 composite (keyless subset, renormalised)
    bucket          TEXT NOT NULL,      -- Risk-On|Neutral|Risk-Off (hysteresis carried)
    coverage        REAL,               -- summed weight of present components
    components_json TEXT DEFAULT '{}',  -- {component: subscore}
    spy_close       REAL,               -- SPY close on that day (chart convenience)
    fwd_5d          REAL,               -- SPY forward 5-trading-day return (fraction)
    fwd_20d         REAL,               -- SPY forward 20-trading-day return (fraction)
    created_at      TEXT
);
CREATE INDEX IF NOT EXISTS idx_regime_history_bucket ON regime_history(bucket);

-- Resolved predictions from systematic rules, Brier-scored over history.
-- source is always 'rule_backtest' here; live memo predictions stay in memo_predictions.
CREATE TABLE IF NOT EXISTS rule_predictions (
    id           INTEGER PRIMARY KEY,
    rule_id      TEXT NOT NULL,
    source       TEXT NOT NULL DEFAULT 'rule_backtest',
    as_of_date   TEXT NOT NULL,        -- day the antecedent fired
    horizon_date TEXT,                 -- resolution day
    horizon_days INTEGER,
    probability  REAL NOT NULL,        -- ex-ante rule probability
    outcome      INTEGER,              -- 1 true / 0 false (resolved from realised return)
    brier        REAL,
    detail_json  TEXT DEFAULT '{}',
    created_at   TEXT,
    UNIQUE(rule_id, as_of_date, source)
);
CREATE INDEX IF NOT EXISTS idx_rule_predictions_rule ON rule_predictions(rule_id);
