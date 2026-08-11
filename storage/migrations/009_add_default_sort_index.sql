-- 009_add_default_sort_index.sql
-- Sprint 3 STEP3: 검색 성능 개선 (ORDER BY)
-- api/v1/search.py의 기본 정렬(ORDER BY auction_date DESC, fail_count DESC)에 정확히
-- 일치하는 복합 인덱스 추가. 기존 idx_fail_count_date(fail_count, auction_date)는
-- 컬럼 순서가 반대라 이 정렬에 쓰이지 않으므로 그대로 두고(삭제하지 않음), 새 인덱스만 추가한다.
CREATE INDEX IF NOT EXISTS idx_auction_item_default_sort ON auction_item(auction_date DESC, fail_count DESC);
