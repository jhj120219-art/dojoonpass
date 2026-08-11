-- 005_create_registry_usage.sql
CREATE TABLE IF NOT EXISTS registry_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    item_id INTEGER REFERENCES auction_item(id),
    is_free INTEGER NOT NULL DEFAULT 1,
    charged_amount INTEGER NOT NULL DEFAULT 0,
    used_at TEXT NOT NULL
);
-- is_free: 1=무료 5회 이내, 0=초과
CREATE INDEX IF NOT EXISTS idx_registry_usage_user_id ON registry_usage(user_id);
