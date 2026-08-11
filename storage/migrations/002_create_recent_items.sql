-- 002_create_recent_items.sql
-- 최근조회 테이블
CREATE TABLE IF NOT EXISTS recent_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    item_id INTEGER NOT NULL REFERENCES auction_item(id),
    viewed_at TEXT NOT NULL,
    UNIQUE(user_id, item_id)
);
CREATE INDEX IF NOT EXISTS idx_recent_items_user_id ON recent_items(user_id);
CREATE INDEX IF NOT EXISTS idx_recent_items_viewed_at ON recent_items(user_id, viewed_at);
