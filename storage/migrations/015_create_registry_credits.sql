-- 015_create_registry_credits.sql
--
-- [CTO 승인 6번] 관리자가 등기부 무료 횟수를 추가/차감/초기화할 수 있는 구조
--
-- 설계 원칙: **잔액 컬럼을 따로 두지 않는다.**
-- 지금 무료 한도는 "플랜별 월 한도(PLAN_CATALOG) - 이번 달 사용량(registry_usage)"으로
-- 계산된다(api/v1/registry.py). 여기에 잔액 컬럼을 새로 만들면 같은 상태가 두 곳에 존재해
-- 반드시 어긋난다(docs/decision-log.md의 Premium 판정에서 이미 같은 이유로 별도 테이블을 거부함).
--
-- 대신 **조정 원장(ledger)** 을 둔다. 관리자의 조정 행위만 append-only로 쌓고,
-- 유효 한도 = 플랜 월 한도 + (이번 달 조정 합계) 로 계산한다.
-- 이 방식의 장점:
--   - 누가/언제/왜 한도를 바꿨는지 전부 남는다(Admin이 단일 공유키라 더더욱 필요하다)
--   - 월이 바뀌면 조정도 자연히 초기화된다(기존 월 리셋 정책과 동일하게 동작)
--   - 잔액 동기화 버그가 원천적으로 불가능하다

CREATE TABLE IF NOT EXISTS registry_credits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    -- GRANT(추가) / DEDUCT(차감) / RESET(초기화)
    -- GRANT는 amount > 0, DEDUCT는 amount < 0으로 저장한다(합계만 내면 되도록).
    -- RESET은 "그 달의 이전 조정을 전부 무효화"하는 표식이며 amount=0으로 기록한다.
    reason_type TEXT NOT NULL,
    amount INTEGER NOT NULL DEFAULT 0,
    reason TEXT,
    -- 조정이 적용되는 월. "YYYY-MM" 형식. 월 리셋 정책과 맞물린다.
    effective_month TEXT NOT NULL,
    -- 조정을 수행한 주체. Admin은 현재 단일 공유키라 사람을 특정할 수 없어
    -- 'ADMIN'/'SUPER_ADMIN' 등급 문자열을 남긴다(권한 등급은 api/v1/admin.py 참고).
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_registry_credits_user_month
    ON registry_credits(user_id, effective_month);
CREATE INDEX IF NOT EXISTS idx_registry_credits_created_at
    ON registry_credits(created_at);
