-- 016_create_audit_and_credit_logs.sql
--
-- [CTO 승인 4·5·6번] registry_credit_logs / audit_logs / Soft Delete
--
-- 세 가지를 한 마이그레이션에 묶은 이유: 전부 "누가 언제 무엇을 왜 바꿨는가"를 남기는
-- 감사(audit) 계열이고, 서로 참조하지 않는 신규 테이블/컬럼이라 순서 의존이 없다.

-- ---------------------------------------------------------------------------
-- 1) registry_credit_logs (승인 4번)
--
-- registry_credits(조정 원장)와 **별도**다. 둘의 역할이 다르다:
--   registry_credits      = 유효 한도 계산에 실제로 반영되는 관리자 조정만
--   registry_credit_logs  = 무료 횟수가 움직인 **모든 사건**의 추적 기록
--
-- 사용(USAGE)까지 한도 계산에 넣으면 registry_usage가 이미 세고 있는 사용량과 이중 차감이
-- 된다. 그래서 사용은 로그에만 남기고 계산에는 넣지 않는다(api/constants.py:ADJUSTMENT_REASONS).
-- balance_after를 함께 저장해 "그 시점에 얼마였는지"를 재계산 없이 볼 수 있게 한다.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS registry_credit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    -- GRANT(관리자 지급) / DEDUCT(회수) / RESET(초기화) / USAGE(사용) /
    -- EVENT(이벤트 지급) / REFUND(환불 복구) / OTHER(기타)
    reason_type TEXT NOT NULL,
    -- 변동량. 지급은 양수, 사용/회수는 음수. RESET은 0.
    delta INTEGER NOT NULL DEFAULT 0,
    -- 변동 직후의 유효 한도/사용량 스냅샷. 사후 재계산 없이 그 시점 상태를 알 수 있다.
    balance_after INTEGER,
    reason TEXT,
    effective_month TEXT NOT NULL,          -- "YYYY-MM"
    -- 이 로그를 만든 주체. 관리자면 'ADMIN'/'SUPER_ADMIN', 사용자 행위면 'USER',
    -- 시스템 자동이면 'SYSTEM'.
    actor TEXT NOT NULL,
    -- 연관 레코드(있으면). 관리자 조정이면 registry_credits.id, 사용이면 registry_usage.id
    related_credit_id INTEGER REFERENCES registry_credits(id),
    related_usage_id INTEGER REFERENCES registry_usage(id),
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_registry_credit_logs_user
    ON registry_credit_logs(user_id, effective_month);
CREATE INDEX IF NOT EXISTS idx_registry_credit_logs_created_at
    ON registry_credit_logs(created_at);
CREATE INDEX IF NOT EXISTS idx_registry_credit_logs_reason
    ON registry_credit_logs(reason_type);

-- ---------------------------------------------------------------------------
-- 2) audit_logs (승인 5번)
--
-- Admin 작업 이력. before/after를 JSON 문자열로 저장해 "무엇이 어떻게 바뀌었는지"를
-- 그대로 남긴다. Admin이 아직 공유키 기반이라 admin_id에는 등급 문자열이 들어간다
-- (개별 운영자 식별은 인증 방식 교체가 선행돼야 함 — docs/BETA_RELEASE_CHECKLIST.md P1-4).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    admin_id TEXT NOT NULL,
    action TEXT NOT NULL,
    target_type TEXT NOT NULL,
    target_id TEXT,
    before TEXT,
    after TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_audit_logs_target ON audit_logs(target_type, target_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_created_at ON audit_logs(created_at);
CREATE INDEX IF NOT EXISTS idx_audit_logs_admin ON audit_logs(admin_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_action ON audit_logs(action);

-- ---------------------------------------------------------------------------
-- 3) Soft Delete (승인 6번) — "기존 기능과 충돌하지 않는 범위에서만"
--
-- 적용 대상 선정 기준: **실제로 DELETE가 일어나는 테이블**만 고른다.
--   favorites      : DELETE /favorites/{item_id}        -> 적용
--   search_presets : DELETE /search-presets/{preset_id} -> 적용
--
-- 제외 대상과 이유:
--   payments / subscriptions / registry_requests / registry_usage
--     → 삭제 경로가 애초에 없다. 컬럼만 늘리면 모든 조회에 `deleted_at IS NULL`을 붙여야 해
--       실익 없이 회귀 위험만 커진다.
--   auction / auction_item 등 크롤러 테이블
--     → 크롤러가 UPSERT만 하고 삭제하지 않는다.
--
-- ★ 이번 마이그레이션은 **컬럼만 추가**한다. 기존 DELETE 동작은 그대로 두고,
--   soft delete로 전환할지는 별도 판단(그렇게 하면 UNIQUE(user_id,item_id) 때문에
--   재등록이 막히는 문제를 먼저 풀어야 한다 — docs/backend.md 참고).
-- ---------------------------------------------------------------------------
ALTER TABLE favorites ADD COLUMN deleted_at TEXT;
ALTER TABLE favorites ADD COLUMN deleted_by TEXT;

ALTER TABLE search_presets ADD COLUMN deleted_at TEXT;
ALTER TABLE search_presets ADD COLUMN deleted_by TEXT;

CREATE INDEX IF NOT EXISTS idx_favorites_deleted_at ON favorites(deleted_at);
CREATE INDEX IF NOT EXISTS idx_search_presets_deleted_at ON search_presets(deleted_at);
