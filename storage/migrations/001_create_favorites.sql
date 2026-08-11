-- 001_create_favorites.sql
-- 관심물건 테이블
CREATE TABLE IF NOT EXISTS favorites (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    item_id INTEGER NOT NULL REFERENCES auction_item(id),
    created_at TEXT NOT NULL,
    UNIQUE(user_id, item_id)
);
CREATE INDEX IF NOT EXISTS idx_favorites_user_id ON favorites(user_id);
CREATE INDEX IF NOT EXISTS idx_favorites_item_id ON favorites(item_id);
