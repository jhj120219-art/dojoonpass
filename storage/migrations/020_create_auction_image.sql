-- 020_create_auction_image.sql
--
-- [2026-08-17 Sprint 144] 물건 사진(Asset Pipeline) — 저장 계층 신설
--
-- 왜 새 테이블인가 (기존 테이블 재사용을 먼저 검토한 결과)
-- ---------------------------------------------------------------------------
-- 이 저장소는 "중복 테이블을 만들지 않는다"는 규칙이 있어, 사진을 기존 문서 테이블에
-- 얹을 수 있는지 먼저 따졌다. 결론은 **얹을 수 없다**이고 사유는 개수다:
--
--   `doc_raw`         : (item_id, doc_type)당 1개를 전제로 한 컬럼 구성이다
--                       (doc_version으로 세대만 관리하고, 같은 세대에 여러 파일이라는
--                        개념이 없다). 사진은 한 물건에 0~N장(실측 5장)이다.
--   `document_status` : 상태 1행 = 자산 1개라는 대응이 무너진다(사진 5장에 상태 1개).
--
-- 그래서 **개수 축(seq)을 가진 테이블**을 따로 만들되, 다른 것은 전부 기존 규약을
-- 그대로 따른다: 파일은 문서와 같은 물건 디렉터리 아래
-- (`documents/<법원>/<사건>/<물건>/images/`)에 두고, 수집 대기·재시도·우선순위는
-- 기존 `document_queue`를 그대로 쓰며(doc_type='image'), 화면이 읽는 수집 상태는
-- 기존 `document_status`를 그대로 쓴다(doc_type='IMAGE'). 새로 만드는 것은 이 표 하나뿐이다.
--
-- 컬럼 설명
-- ---------------------------------------------------------------------------
--   seq          법원 캐러셀의 **전체 순번**(1부터). alt="전경도_1"의 그 숫자를 그대로 쓴다.
--                종류별 순번이 아니라 전체 순번이라는 것을 실측으로 확인했으므로
--                (전경도_1..3 다음이 관련사진_4,5) 이 값 하나로 화면 정렬이 끝난다.
--   kind         "전경도"/"위치도"/"관련사진"/"내부구조도" 등. 원문 그대로 넣는다 —
--                알 수 없는 종류가 와도 버리지 않는다.
--   storage_path 프로젝트 루트 기준 **상대경로**로 넣는다. 절대경로를 넣으면 배포 경로가
--                바뀌는 순간 DB 전체가 못 쓰게 된다(이 저장소가 실제로 겪은
--                `C:\Users\Administrator\...` 하드코딩 사고와 같은 계열).
--   file_hash    같은 사진을 다시 받았는지 판정용(SHA-256). 재수집 시 바뀐 것만 알아본다.
--   width/height 프런트가 레이아웃 흔들림(CLS) 없이 자리를 잡을 수 있게 한다.
--
-- UNIQUE(item_id, seq)가 **중복 자산 방어선**이다. worker가 같은 물건을 두 번 처리해도
-- 사진이 두 벌 쌓이지 않는다(INSERT OR REPLACE가 같은 행을 덮어쓴다).
--
-- 안전성
-- ---------------------------------------------------------------------------
-- `CREATE TABLE/INDEX IF NOT EXISTS`뿐이고 기존 테이블을 전혀 건드리지 않는다.
-- 기존 데이터에 대해 무손실이며 재실행해도 안전하다(migration_history가 중복 적용을 막는다).

CREATE TABLE IF NOT EXISTS auction_image (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id INTEGER NOT NULL REFERENCES auction_item(id),
    seq INTEGER NOT NULL,
    kind TEXT,
    storage_path TEXT NOT NULL,
    file_hash TEXT,
    file_size INTEGER,
    width INTEGER,
    height INTEGER,
    crawl_date TEXT,
    created_at TEXT,
    UNIQUE(item_id, seq)
);

-- 상세페이지가 "이 물건의 사진을 순서대로" 읽는 것이 유일한 조회 패턴이다.
-- UNIQUE(item_id, seq)가 만드는 자동 인덱스와 열 순서가 같아 사실상 중복이지만,
-- SQLite의 sqlite_autoindex는 이름이 구현 의존이라 쿼리 계획을 이름으로 확인·고정할 수
-- 없다. 명시적 인덱스를 둬서 계획이 바뀌었을 때 회귀 테스트가 알아볼 수 있게 한다.
CREATE INDEX IF NOT EXISTS idx_auction_image_item_seq
ON auction_image(item_id, seq);
