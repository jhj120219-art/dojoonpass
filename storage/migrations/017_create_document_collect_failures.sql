-- 017_create_document_collect_failures.sql
--
-- [2026-08-11 Sprint 51] 부트스트랩 누락 복구
--
-- 왜 지금 만드는가
-- ---------------------------------------------------------------------------
-- `document_collect_failures`는 이미 운영 DB에 존재하고 코드도 쓰고 있다:
--   - `collect_documents.py`가 수집 실패를 INSERT
--   - `api/v1/doc_stats.py`가 실패 건수를 SELECT
--   - `storage/migrations/013_*.sql`의 주석이 "auction_item을 참조하는 11개 테이블" 중
--     하나로 이 테이블을 명시적으로 세고 있다
--
-- 그런데 이 테이블을 만드는 코드는 **번호 없는 별도 스크립트**
-- (`storage/migrate_doc_collect.py`)에만 있었고, `docs/CLAUDE.md`가 안내하는 부트스트랩
-- 순서(`migrate_v4_1.py` -> `run_migrations`)에는 들어 있지 않았다.
--
-- 그래서 **빈 DB로 부트스트랩을 재현하면 이 테이블만 생성되지 않는다**
-- (Sprint 51에서 실제로 fresh clone을 만들어 대조하다 발견: 운영 25 테이블 vs fresh 24개,
--  차이가 정확히 이 테이블 하나였다). 그 상태로 배포하면 `doc_stats` 라우터가
-- "no such table"로 실패한다. 현재 프론트가 doc_stats를 쓰지 않아 사용자 영향은 없지만,
-- 스키마가 소스로부터 재현되지 않는다는 것 자체가 `docs/BUGS.md` #28과 같은 부류의 위험이다.
--
-- 안전성
-- ---------------------------------------------------------------------------
-- `CREATE TABLE IF NOT EXISTS` / `CREATE INDEX IF NOT EXISTS`라 **이미 테이블이 있는
-- 운영 DB에서는 완전한 no-op**이다(기존 3행 데이터 무손실). 신규 설치에서만 실제로 생성된다.
-- 정의는 `storage/migrate_doc_collect.py`의 것을 **글자 그대로** 옮겼다 — 스키마 변경이 아니라
-- "이미 있는 정의를 부트스트랩 경로에 편입"하는 작업이다.
-- (`migrate_doc_collect.py`는 기존 호출자/운영 절차가 있을 수 있어 삭제하지 않고 그대로 둔다.)

CREATE TABLE IF NOT EXISTS document_collect_failures (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id INTEGER NOT NULL REFERENCES auction_item(id),
    doc_type TEXT NOT NULL,
    error_message TEXT,
    created_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_dcf_item_id
ON document_collect_failures(item_id);
