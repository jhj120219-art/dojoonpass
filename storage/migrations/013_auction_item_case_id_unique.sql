-- 013_auction_item_case_id_unique.sql
--
-- [식별키 case_id 기반 리팩터링] auction_item의 UNIQUE(case_no, item_no)
--                             -> UNIQUE(case_id, item_no)
--
-- 배경 (docs/BUGS.md #18, CTO 승인 "가능하면 case_id 기반으로 리팩토링 / auction_case와 일관성 유지"):
-- auction_item도 auction과 같은 결함을 갖고 있었다 — UNIQUE(case_no, item_no)에 법원이 없어
-- 서로 다른 법원의 같은 사건번호+물건번호가 한 행으로 취급된다.
--
-- 여기서는 court_code를 또 복제해 넣는 대신 **case_id 기반**으로 간다.
-- case_id는 011에서 (court_code, case_no) 복합키가 된 auction_case를 가리키므로
-- 이미 법원이 특정된 값이다. 즉 (case_id, item_no)는 법원+사건번호+물건번호와 동치이면서
-- 정규화 관점에서도 옳다(같은 정보를 두 곳에 중복 저장하지 않는다).
--
-- ★ id 보존이 필수다: auction_item.id는 favorites / recent_items / registry_requests /
--   registry_usage / document_status / doc_raw / parsed_document / tenant_rights /
--   rights_summary / rights_analysis_history / document_collect_failures 11개 테이블이 참조한다.
--   따라서 INSERT 시 id를 명시적으로 그대로 옮긴다.

-- 1. case_id 기반 복합 UNIQUE를 가진 새 테이블 (컬럼 구성은 기존과 완전히 동일)
CREATE TABLE IF NOT EXISTS auction_item_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id INTEGER REFERENCES auction_case(id),
    case_no TEXT NOT NULL,
    item_no TEXT,
    court_name TEXT,
    property_type TEXT,
    sido TEXT,
    sigungu TEXT,
    dong TEXT,
    lot_number TEXT,
    full_address TEXT,
    appraisal_price INTEGER DEFAULT 0,
    minimum_bid_price INTEGER DEFAULT 0,
    auction_date TEXT,
    status TEXT,
    fail_count INTEGER DEFAULT 0,
    bid_rate REAL DEFAULT 0,
    validation_status TEXT,
    crawl_date TEXT,
    created_at TEXT,
    updated_at TEXT,
    UNIQUE(case_id, item_no)
);

-- 2. id를 그대로 보존하며 이관 (자식 테이블 11개의 참조가 끊기지 않도록)
INSERT INTO auction_item_new (
    id, case_id, case_no, item_no, court_name, property_type,
    sido, sigungu, dong, lot_number, full_address,
    appraisal_price, minimum_bid_price, auction_date, status,
    fail_count, bid_rate, validation_status, crawl_date, created_at, updated_at
)
SELECT
    id, case_id, case_no, item_no, court_name, property_type,
    sido, sigungu, dong, lot_number, full_address,
    appraisal_price, minimum_bid_price, auction_date, status,
    fail_count, bid_rate, validation_status, crawl_date, created_at, updated_at
FROM auction_item;

-- 3. 교체
DROP TABLE auction_item;
ALTER TABLE auction_item_new RENAME TO auction_item;

-- 4. 인덱스 재생성 (검색 API가 의존하는 인덱스 전부)
CREATE INDEX IF NOT EXISTS idx_ai_case_no ON auction_item(case_no);
CREATE INDEX IF NOT EXISTS idx_ai_sido ON auction_item(sido);
CREATE INDEX IF NOT EXISTS idx_ai_auction_date ON auction_item(auction_date);
CREATE INDEX IF NOT EXISTS idx_search_main ON auction_item(sido, sigungu, property_type, auction_date);
CREATE INDEX IF NOT EXISTS idx_minimum_bid_price ON auction_item(minimum_bid_price);
CREATE INDEX IF NOT EXISTS idx_fail_count_date ON auction_item(fail_count, auction_date);
CREATE INDEX IF NOT EXISTS idx_status_date ON auction_item(status, auction_date);
CREATE INDEX IF NOT EXISTS idx_auction_item_case_no ON auction_item(case_no);
CREATE INDEX IF NOT EXISTS idx_auction_item_court_name ON auction_item(court_name);
CREATE INDEX IF NOT EXISTS idx_auction_item_sido_sigungu ON auction_item(sido, sigungu);
CREATE INDEX IF NOT EXISTS idx_auction_item_property_type ON auction_item(property_type);
CREATE INDEX IF NOT EXISTS idx_auction_item_auction_date ON auction_item(auction_date);
CREATE INDEX IF NOT EXISTS idx_auction_item_appraisal_price ON auction_item(appraisal_price);
CREATE INDEX IF NOT EXISTS idx_auction_item_minimum_bid_price ON auction_item(minimum_bid_price);
CREATE INDEX IF NOT EXISTS idx_auction_item_fail_count ON auction_item(fail_count);
CREATE INDEX IF NOT EXISTS idx_auction_item_default_sort ON auction_item(auction_date DESC, fail_count DESC);
