-- 008_create_search_indexes.sql
-- 검색엔진 고도화: auction_item 검색 조건에 자주 쓰이는 컬럼에 인덱스 추가 (성능 개선 목적, 스키마/컬럼 변경 없음)
CREATE INDEX IF NOT EXISTS idx_auction_item_case_no ON auction_item(case_no);
CREATE INDEX IF NOT EXISTS idx_auction_item_court_name ON auction_item(court_name);
CREATE INDEX IF NOT EXISTS idx_auction_item_sido_sigungu ON auction_item(sido, sigungu);
CREATE INDEX IF NOT EXISTS idx_auction_item_property_type ON auction_item(property_type);
CREATE INDEX IF NOT EXISTS idx_auction_item_auction_date ON auction_item(auction_date);
CREATE INDEX IF NOT EXISTS idx_auction_item_appraisal_price ON auction_item(appraisal_price);
CREATE INDEX IF NOT EXISTS idx_auction_item_minimum_bid_price ON auction_item(minimum_bid_price);
CREATE INDEX IF NOT EXISTS idx_auction_item_fail_count ON auction_item(fail_count);
CREATE INDEX IF NOT EXISTS idx_rights_summary_item_id ON rights_summary(item_id);
