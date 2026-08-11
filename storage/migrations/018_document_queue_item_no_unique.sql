-- 018_document_queue_item_no_unique.sql
--
-- [document_queue] UNIQUE(court_code, case_no, doc_type)
--               -> UNIQUE(court_code, case_no, item_no, doc_type)
--
-- 배경 (docs/BUGS.md #48, 2026-08-11 Sprint 55):
-- `enqueue_documents()`의 docstring은 이미 이렇게 적혀 있었다.
--
--     UNIQUE(court_code, case_no, item_no, doc_type) 이므로 이미 대기 중인 항목은
--     INSERT OR IGNORE로 조용히 무시된다 (중복 enqueue 방지)
--
-- 그러나 실제 스키마에는 item_no가 **없었다**. `item_no`는 나중에 ALTER TABLE로 붙은
-- 컬럼이고 UNIQUE 제약은 그대로 남아 있었다. 그 결과 한 사건에 물건이 여러 개일 때
-- **두 번째 물건부터는 INSERT OR IGNORE에 걸려 조용히 버려졌다.**
--
-- 문서는 물건 단위다 — `get_doc_button_id(doc_type, item_no)`가 item_no로 버튼을 고른다.
-- 즉 물건마다 다른 매각물건명세서를 받아야 하는데, 큐에는 사건당 하나만 들어갔다.
--
-- 실측 (2026-08-11, 적용 전):
--     물건이 2개 이상인 사건            190건 (그 안의 물건 680개)
--     자기 item_no로 큐에 없는 물건     716 / 1,870  (38%)
--     (court_code, case_no)당 item_no 종류 수  전부 1  <- 충돌의 직접 증거
--
-- 이것이 권리분석 데이터가 비어 있는 원인 중 하나다. 애초에 큐에 들어간 적이 없으니
-- 수집도 파싱도 될 수 없었다.
--
-- ★ 이 마이그레이션은 **행을 지우지 않는다.** 기존 3,480행을 id까지 그대로 보존한다.
--   제약이 넓어지는 방향(더 많은 조합을 허용)이라 기존 행은 전부 새 제약도 만족한다.
--   빠져 있던 물건들은 다음 enqueue_documents() 실행 때 자연히 채워진다.
--
-- document_queue.id를 참조하는 FK는 없다(2026-08-11 확인). 그래도 id를 보존하는 이유는
-- doc_worker가 claim -> mark_done/failed 사이에 id를 들고 다니기 때문이다.

-- 1. item_no를 포함한 UNIQUE를 가진 새 테이블 (컬럼 구성은 기존과 완전히 동일)
CREATE TABLE IF NOT EXISTS document_queue_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    court_code TEXT NOT NULL,
    case_no TEXT NOT NULL,
    doc_type TEXT NOT NULL,
    priority INTEGER DEFAULT 3,
    auction_date TEXT,
    status TEXT DEFAULT 'pending',
    retry_count INTEGER DEFAULT 0,
    last_attempt_at TEXT,
    enqueued_at TEXT,
    item_no TEXT NOT NULL DEFAULT '1',
    UNIQUE(court_code, case_no, item_no, doc_type)
);

-- 2. id를 그대로 보존하며 이관
INSERT INTO document_queue_new (
    id, court_code, case_no, doc_type, priority, auction_date,
    status, retry_count, last_attempt_at, enqueued_at, item_no
)
SELECT
    id, court_code, case_no, doc_type, priority, auction_date,
    status, retry_count, last_attempt_at, enqueued_at, item_no
FROM document_queue;

-- 3. 교체
DROP TABLE document_queue;
ALTER TABLE document_queue_new RENAME TO document_queue;

-- 4. 인덱스 재생성 (worker의 claim 쿼리가 의존한다)
CREATE INDEX IF NOT EXISTS idx_queue_priority ON document_queue(priority, auction_date);
CREATE INDEX IF NOT EXISTS idx_queue_status ON document_queue(status);
