-- 003_create_search_presets.sql
-- 검색조건 저장 테이블
CREATE TABLE IF NOT EXISTS search_presets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    name TEXT NOT NULL,
    conditions TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_search_presets_user_id ON search_presets(user_id);
