-- 024_auction_case_court_code_not_null.sql
--
-- [2026-08-26] `auction_case.court_code` 를 NOT NULL 로 굳힌다 — 드리프트의 **마지막 조각**.
--
-- 021/022/023 과 같은 뿌리, 다만 **방향이 반대다**
-- ---------------------------------------------------------------------------
-- 앞의 셋은 "라이브를 소스에 맞췄다". 여기는 **소스를 라이브에 맞춘다.** 이유는 단순하다 —
-- 이 항목만은 **라이브 쪽이 옳기 때문**이다.
--
--     011_auction_case_court_code_unique.sql  ->  court_code TEXT          (nullable)
--     라이브 DB (실측 2026-08-26)              ->  court_code TEXT NOT NULL
--
-- 왜 NOT NULL 이 옳은가
-- ---------------------------------------------------------------------------
-- 이 열은 `UNIQUE(court_code, case_no)` 의 **앞자리**다. 그런데 SQLite 는 UNIQUE 안에서
-- **NULL 을 서로 다른 값으로 취급한다.** 즉 nullable 이면
--
--     (NULL, '2024타경1097')
--     (NULL, '2024타경1097')      <- 제약을 그대로 통과한다
--
-- 가 둘 다 들어간다. 이 UNIQUE 의 존재 이유가 011 헤더에 적혀 있듯 *"법원마다 사건번호를
-- 독립 채번하므로 사건번호만으로는 물건이 소실된다"* 는 것이었는데, court_code 가 비면
-- **그 방어가 통째로 사라진다.** 그러니 소스를 라이브에 맞추는 것이 맞다.
--
-- 반대로 맞췄다면(라이브를 nullable 로) 지금 있는 방어를 스스로 없애는 셈이 된다.
--
-- 컬럼 **순서**도 함께 맞춘다
-- ---------------------------------------------------------------------------
-- 011 은 `case_no, court_code` 순, 라이브는 `court_code, case_no` 순이다(012 이후의 재작성
-- 결과로 보인다). `PRAGMA table_info` 를 이름으로 비교하면 안 보이지만 `SELECT *` 의 열
-- 순서가 달라지므로 **위치로 읽는 코드가 있으면 환경마다 다른 값을 읽는다.**
-- 라이브 순서를 정본으로 고정한다.
--
-- 안전성 — 1,796행, NULL 0건
-- ---------------------------------------------------------------------------
--     SELECT COUNT(*) FROM auction_case                                   1796
--     SELECT COUNT(*) FROM auction_case WHERE court_code IS NULL OR ''       0   (실측)
--
-- 즉 NOT NULL 로 굳혀도 **버려지는 행이 없다.** 그래도 방어적으로 COALESCE 를 둔다 —
-- 다른 환경에 NULL 이 있으면 행을 잃는 대신 빈 문자열로 승격시켜 마이그레이션이
-- 죽지 않게 한다(값을 지어내지 않는다. 빈 문자열은 "모른다"가 그대로 보이는 표시다).
--
-- ★ `id` 를 그대로 옮긴다. `auction_item.case_id` 가 이 표의 `id` 를 참조하므로
--   (`REFERENCES auction_case(id)`) 번호가 바뀌면 2,444개 물건의 사건 연결이 끊긴다.
--   러너는 `enforce_foreign_keys=False` 로 실행하므로 DROP~RENAME 사이 구간을 통과한다.
--
-- 되돌리기: 아래 CREATE 에서 `NOT NULL` 만 빼고 같은 순서로 다시 돌리면 된다.

CREATE TABLE IF NOT EXISTS auction_case_nn (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    court_code TEXT NOT NULL,
    case_no TEXT NOT NULL,
    court_name TEXT,
    case_type TEXT,
    filed_date TEXT,
    demand_deadline TEXT,
    created_at TEXT,
    updated_at TEXT,
    UNIQUE(court_code, case_no)
);

INSERT INTO auction_case_nn (
    id, court_code, case_no, court_name, case_type,
    filed_date, demand_deadline, created_at, updated_at
)
SELECT
    id,
    COALESCE(court_code, ''),
    case_no,
    court_name, case_type, filed_date, demand_deadline, created_at, updated_at
FROM auction_case;

DROP TABLE auction_case;
ALTER TABLE auction_case_nn RENAME TO auction_case;

CREATE INDEX IF NOT EXISTS idx_auction_case_case_no ON auction_case(case_no);
CREATE INDEX IF NOT EXISTS idx_auction_case_court_code ON auction_case(court_code);
