-- Notification delivery log (PLAN.md §12). The router logs every send here for
-- dedupe (across restarts), quiet-hours queueing, and the /system delivery history.
CREATE TABLE notifications (
    id           INTEGER PRIMARY KEY,
    priority     TEXT,                -- P0|P1|P2
    title        TEXT,
    body         TEXT,
    dedupe_key   TEXT,
    click_url    TEXT,
    tags         TEXT,
    channel      TEXT,                -- comma-joined channels attempted
    status       TEXT,                -- sent|queued|deduped|failed|dry_run
    error        TEXT,
    created_at   TEXT,
    queued_until TEXT,
    sent_at      TEXT
);
CREATE INDEX idx_notifications_dedupe  ON notifications(dedupe_key, sent_at);
CREATE INDEX idx_notifications_created ON notifications(created_at DESC);
CREATE INDEX idx_notifications_status  ON notifications(status);
