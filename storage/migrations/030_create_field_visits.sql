-- 030_create_field_visits.sql
-- 임장(현장 확인) 기록 (2026-09-04)
--
-- 왜 필요한가 — 제품의 workflow 에서 통째로 비어 있던 한 칸
-- ---------------------------------------------------------------------------
-- 콕찰이 줄이려는 것은 "경매 의사결정에 드는 시간"이고, 그 시간은
--
--     DISCOVER  물건 발견 (검색/필터)
--     REVIEW    핵심정보 검토 (권리/임차인/문서)
--     FIELD     임장                       <- 여기가 코드에 **한 줄도 없었다**
--     DECIDE    입찰 판단                  <- 기록할 자리가 없었다
--
-- 로 나뉜다. 2026-09-04 전수 확인: `임장`/`field`/`inspection` 을 다루는 route ·
-- API · 테이블이 저장소에 **0개**였다. 사용자는 현장에서 본 것을 콕찰 밖(수첩,
-- 메모앱, 카톡)에 적고, 판단할 때 그것을 다시 찾아 와야 했다. 그 왕복이 곧
-- 이 제품이 줄이겠다고 말한 시간이다.
--
-- 무엇을 담고 무엇을 담지 않는가
-- ---------------------------------------------------------------------------
-- 담는 것: 사용자가 **직접 확인하고 직접 적은 것**.
--   - 체크리스트 확인 여부
--   - 현장 메모
--   - 위험요소
--   - 사용자 본인의 입찰 판단(BID / HOLD / DROP)
--
-- 담지 않는 것: **점수 · 추천 · 수익률 · 자동 투자판단.**
--   `docs/decision-log.md` 가 프로젝트 범위 밖으로 못박은 것들이다
--   (`docs/CLAUDE.md`: "투자점수 / AI 추천 / 수익률 계산 / 자동 투자판단 기능은
--   개발하지 않는다"). 이 표는 판단을 **대신하지 않고 기록만** 한다.
--
-- 왜 `favorites` 에 열을 붙이지 않고 별도 표인가
-- ---------------------------------------------------------------------------
-- 026(favorite_notes)이 같은 판단을 이미 적어 두었다 — `favorites` 는 "담았다"는
-- 사실만 담는 표이고 API 여러 곳이 `SELECT *` 로 읽는다. 열을 붙이면 그 응답들이
-- 한꺼번에 바뀐다. 그리고 임장은 찜과 수명이 다르다: 찜을 해제해도 다녀온 사실과
-- 그때의 판단은 남아야 한다. 그래서 `auction_item` 을 직접 가리킨다(026 과 같은 이유).
--
-- 체크 항목을 왜 행으로 두는가 (열이 아니라)
-- ---------------------------------------------------------------------------
-- 체크리스트는 제품이 다듬어 가며 늘고 준다. 열로 두면 항목이 바뀔 때마다
-- 마이그레이션이 필요하고, 그 적용은 승인 영역이라 제품 속도가 스키마에 묶인다.
-- 행으로 두면 항목 변경이 **코드 상수 변경**으로 끝난다(`api/v1/field_visits.py`).
--
-- ★ 이 파일은 **순수 가산**이다 — `CREATE TABLE/INDEX IF NOT EXISTS` 뿐이고
--   기존 표를 고치거나 지우는 문장이 없다. 026 과 같은 성격이며,
--   **운영 적용 자체는 여전히 승인 영역이다**(`docs/CLAUDE.md`).
--   적용 전에도 API 는 죽지 않는다 — `api/v1/field_visits.py` 가 표 존재를 먼저
--   확인하고 503(FIELD_NOT_AVAILABLE)으로 **정직하게** 답한다(favorites 가
--   favorite_notes 에 쓰는 것과 같은 방식).

CREATE TABLE IF NOT EXISTS field_visits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    item_id INTEGER NOT NULL REFERENCES auction_item(id),
    -- IN_PROGRESS: 임장 시작함 / DONE: 현장 확인을 끝냄
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    -- 현장 메모(자유 서술)
    memo TEXT,
    -- 위험요소(현장에서 본 것. 권리분석의 risk_reason 과 별개다 — 그쪽은 문서 기반이다)
    risk_note TEXT,
    -- 사용자 본인의 입찰 판단. BID / HOLD / DROP. 판단하기 전에는 NULL.
    decision TEXT,
    decided_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    -- 한 사용자는 한 물건에 임장 기록 하나를 갖는다. 다시 다녀오면 그 기록을 잇는다
    -- (여러 번 방문을 따로 남기는 것은 제품 결정이라 여기서 정하지 않는다).
    UNIQUE(user_id, item_id)
);

-- 조회는 항상 "내 것"이다(내 임장 목록 / 이 물건의 내 임장).
-- (user_id, item_id) 는 위 UNIQUE 가 이미 인덱스를 만들어 주므로 따로 만들지 않는다 —
-- 021 이 지운 "접두가 겹치는 중복 인덱스"를 다시 만들지 않기 위해서다.
CREATE INDEX IF NOT EXISTS idx_field_visits_user_id ON field_visits(user_id);

CREATE TABLE IF NOT EXISTS field_visit_checks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    visit_id INTEGER NOT NULL REFERENCES field_visits(id),
    -- 체크 항목 키. 어휘의 정본은 `api/v1/field_visits.py:CHECK_ITEMS` 하나다.
    check_key TEXT NOT NULL,
    checked INTEGER NOT NULL DEFAULT 0,
    note TEXT,
    updated_at TEXT NOT NULL,
    UNIQUE(visit_id, check_key)
);
