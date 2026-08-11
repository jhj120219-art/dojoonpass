-- 012_auction_court_code_unique.sql
--
-- [데이터 소실 해결] auction(크롤러 원본)의 UNIQUE(case_no, item_no)
--                 -> UNIQUE(court_code, case_no, item_no)
--
-- 배경 (docs/BUGS.md #18):
-- 011에서 auction_case를 (court_code, case_no) 복합키로 바꿨지만, 그 위 단계인 크롤러 원본
-- 테이블 auction은 여전히 법원 구분이 없는 UNIQUE(case_no, item_no)였다.
-- storage/database.py:upsert_batch()가 이 키로 기존 행을 찾아 court_code/court_name/주소/가격을
-- 전부 UPDATE하므로, 서로 다른 법원이 같은 사건번호+물건번호를 쓰면 병합이 아니라
-- **앞서 저장된 법원의 물건이 통째로 교체되어 사라졌다**(사본 DB로 재현 확인).
--
-- 실측: 법원 간 사건번호 공유 3건. 세 건 모두 한쪽 법원이 item_no=1을 차지하고 다른 쪽 목록에서
-- 정확히 item_no=1만 결번이라, 이미 소실이 발생했을 가능성이 높다(제약 특성상 사후 확인 불가).
--
-- SQLite는 UNIQUE 제약을 ALTER로 바꿀 수 없으므로 011과 동일한 표준 재작성 패턴을 쓴다.
-- auction 테이블을 참조하는 FK는 없으므로(auction_item은 auction_case를 참조한다) 안전하다.
--
-- 주의: 이 테이블은 docs/backend.md에서 "크롤러 원본, 변경 금지"로 표기돼 있었다.
-- 그 취지는 하위호환 보호이고 컬럼 구성은 그대로 유지하므로(제약만 강화), CTO 승인 하에 진행한다.

-- 1. 법원을 포함한 복합 UNIQUE를 가진 새 테이블 생성 (컬럼 구성은 기존과 완전히 동일)
CREATE TABLE IF NOT EXISTS auction_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    court_code TEXT,
    court_name TEXT,
    case_no TEXT NOT NULL,
    item_no TEXT,
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
    validation_status TEXT,
    validation_reasons TEXT,
    crawl_date TEXT,
    created_at TEXT,
    updated_at TEXT,
    has_spec_pdf INTEGER DEFAULT 0,
    has_status_doc INTEGER DEFAULT 0,
    has_appraisal_pdf INTEGER DEFAULT 0,
    UNIQUE(court_code, case_no, item_no)
);

-- 2. 기존 데이터를 id까지 그대로 이관한다.
--    id를 보존해야 하는 이유: auction.id를 참조하는 선언 FK는 없지만, document_queue 등
--    운영 데이터와 로그가 이 id를 사용해 왔으므로 값이 바뀌면 추적이 끊긴다.
INSERT INTO auction_new (
    id, court_code, court_name, case_no, item_no, property_type,
    sido, sigungu, dong, lot_number, full_address,
    appraisal_price, minimum_bid_price, auction_date, status,
    validation_status, validation_reasons, crawl_date,
    created_at, updated_at, has_spec_pdf, has_status_doc, has_appraisal_pdf
)
SELECT
    id, court_code, court_name, case_no, item_no, property_type,
    sido, sigungu, dong, lot_number, full_address,
    appraisal_price, minimum_bid_price, auction_date, status,
    validation_status, validation_reasons, crawl_date,
    created_at, updated_at, has_spec_pdf, has_status_doc, has_appraisal_pdf
FROM auction;

-- 3. 교체
DROP TABLE auction;
ALTER TABLE auction_new RENAME TO auction;

-- 4. 인덱스 재생성 (테이블 재작성 시 기존 인덱스는 함께 사라진다)
CREATE INDEX IF NOT EXISTS idx_case_no ON auction(case_no);
CREATE INDEX IF NOT EXISTS idx_auction_date ON auction(auction_date);
CREATE INDEX IF NOT EXISTS idx_sido ON auction(sido);
CREATE INDEX IF NOT EXISTS idx_court_name ON auction(court_name);
CREATE INDEX IF NOT EXISTS idx_validation ON auction(validation_status);
-- 신규: upsert_batch()가 매 크롤링마다 (court_code, case_no, item_no)로 조회하므로
-- 복합 UNIQUE의 자동 인덱스가 그대로 쓰인다(별도 인덱스 불요).
