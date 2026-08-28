-- 026_create_favorite_notes.sql
-- 관심물건의 사용자 메모 / 태그 / 출처 (2026-08-28)
--
-- 왜 `favorites` 에 열을 붙이지 않고 옆 테이블인가:
--   `favorites` 는 "담았다"는 사실만 담는 테이블이고 API 6곳이 `SELECT *` 로 읽는다.
--   열을 붙이면 그 6곳의 응답 모양이 한꺼번에 바뀐다. 옆 테이블 + LEFT JOIN 이면
--   읽는 쪽이 필요한 곳만 늘려 쓸 수 있고, 이 마이그레이션이 실패해도 관심물건
--   기능 자체는 그대로 동작한다.
--
-- ★ 이 파일은 **순수 가산**이다 -- CREATE TABLE/INDEX IF NOT EXISTS 뿐이고
--   기존 테이블을 고치거나 지우는 문장이 없다. 011~013 처럼 재작성이 필요한
--   마이그레이션과 성격이 다르다(운영 적용 자체는 여전히 승인 영역이다).
--
-- `item_id` 는 `favorites` 가 아니라 `auction_item` 을 가리킨다. 찜을 해제해도
-- 메모가 사라지지 않아야 하기 때문이다 -- 다시 담았을 때 예전 메모가 돌아온다.
CREATE TABLE IF NOT EXISTS favorite_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    item_id INTEGER NOT NULL REFERENCES auction_item(id),
    memo TEXT,
    tags TEXT,
    source TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(user_id, item_id)
);
-- 조회는 항상 "내 것 전부"다(마이페이지/관심물건 목록). user_id 단독 인덱스면 충분하고,
-- (user_id, item_id) 는 위 UNIQUE 가 이미 인덱스를 만들어 준다 -- 021 이 지운
-- "접두가 겹치는 중복 인덱스"를 여기서 다시 만들지 않는다.
CREATE INDEX IF NOT EXISTS idx_favorite_notes_user_id ON favorite_notes(user_id);
