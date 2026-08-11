-- 007_create_registry_requests.sql
CREATE TABLE IF NOT EXISTS registry_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    item_id INTEGER NOT NULL REFERENCES auction_item(id),
    usage_id INTEGER REFERENCES registry_usage(id),
    payment_id INTEGER REFERENCES payments(id),
    status TEXT NOT NULL DEFAULT 'PENDING',
    doc_url TEXT,
    requested_at TEXT NOT NULL,
    completed_at TEXT
);
-- status: PENDING / PAYMENT_REQUIRED / PROCESSING / COMPLETED / FAILED
CREATE INDEX IF NOT EXISTS idx_registry_requests_user_id ON registry_requests(user_id);
CREATE INDEX IF NOT EXISTS idx_registry_requests_status ON registry_requests(status);
