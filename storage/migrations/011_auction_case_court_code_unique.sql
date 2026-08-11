-- 011_auction_case_court_code_unique.sql
--
-- [Release Blocking 해결] auction_case의 UNIQUE(case_no) -> UNIQUE(court_code, case_no)
--
-- 배경: 법원마다 사건번호를 독립 채번하므로 전국 단일 UNIQUE(case_no)는 구조적으로 충돌한다.
-- 서로 다른 법원의 동일 사건번호가 하나의 auction_case row로 병합되어, auction_item.case_id가
-- 잘못된 법원의 사건을 가리키는 문제가 발생했다(실측 3건 확인).
--
-- SQLite는 기존 테이블의 UNIQUE 제약을 ALTER로 변경할 수 없으므로, 새 테이블 생성 ->
-- 데이터 이관 -> 교체 방식(표준 SQLite 테이블 재작성 패턴)을 사용한다.
--
-- court_code 값의 정본: 크롤러 원본 테이블 auction.court_code를 그대로 쓴다.
-- (현재 이 컬럼에는 config/courts.py:ALL_COURTS의 code = 법원명 문자열이 들어있고 NULL은 0건임을
--  실측 확인했다. 향후 실제 법원코드 체계로 바꾸더라도 이 마이그레이션 구조는 그대로 유효하다.)

-- 1. 복합 UNIQUE를 가진 새 테이블 생성 (court_code 컬럼 신규 추가)
CREATE TABLE IF NOT EXISTS auction_case_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_no TEXT NOT NULL,
    court_code TEXT,
    court_name TEXT,
    case_type TEXT,
    filed_date TEXT,
    demand_deadline TEXT,
    created_at TEXT,
    updated_at TEXT,
    UNIQUE(court_code, case_no)
);

-- 2. 크롤러 원본(auction)의 (court_code, case_no) 조합을 정본으로 이관한다.
--    기존 auction_case에 있던 메타(case_type/filed_date/demand_deadline)는 case_no로 매칭해
--    보존한다. 충돌했던 사건은 이 단계에서 법원별로 자연스럽게 분리된다.
INSERT OR IGNORE INTO auction_case_new
    (case_no, court_code, court_name, case_type, filed_date, demand_deadline, created_at, updated_at)
SELECT DISTINCT
    a.case_no,
    a.court_code,
    a.court_name,
    ac.case_type,
    ac.filed_date,
    ac.demand_deadline,
    COALESCE(ac.created_at, a.created_at),
    COALESCE(ac.updated_at, a.updated_at)
FROM auction a
LEFT JOIN auction_case ac ON ac.case_no = a.case_no;

-- 3. auction_item.case_id를 새 테이블 기준으로 다시 연결한다.
--    auction_item에는 court_code 컬럼이 없으므로 court_name으로 매칭한다
--    (현재 데이터에서 court_code == court_name 이므로 동일한 결과를 보장한다).
UPDATE auction_item
SET case_id = (
    SELECT acn.id FROM auction_case_new acn
    WHERE acn.case_no = auction_item.case_no
      AND acn.court_code = auction_item.court_name
)
WHERE EXISTS (
    SELECT 1 FROM auction_case_new acn
    WHERE acn.case_no = auction_item.case_no
      AND acn.court_code = auction_item.court_name
);

-- 4. 구 테이블을 교체한다(데이터는 3번까지 전부 새 테이블로 이관 완료된 상태).
DROP TABLE auction_case;
ALTER TABLE auction_case_new RENAME TO auction_case;

-- 5. 인덱스 재생성 (테이블 재작성 시 기존 인덱스는 함께 사라진다)
CREATE INDEX IF NOT EXISTS idx_auction_case_case_no ON auction_case(case_no);
CREATE INDEX IF NOT EXISTS idx_auction_case_court_code ON auction_case(court_code);
