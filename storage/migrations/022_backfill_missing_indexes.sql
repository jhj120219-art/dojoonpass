-- 022_backfill_missing_indexes.sql
--
-- [2026-08-26] 소스는 선언하는데 **라이브 DB 에만 없는** 인덱스 5개를 채운다.
--
-- 배경 — "이미 적용된 마이그레이션을 나중에 편집했다"
-- ---------------------------------------------------------------------------
-- `test_bootstrap.py` 의 `KNOWN_FRESH_ONLY_INDEXES` 가 이 5개를 알려진 격차로 들고 있었다.
-- 원인은 그 파일 주석이 이미 정확히 적어 둔 그대로다 — `014_create_payment_logs.sql` /
-- `015_create_registry_credits.sql` 이 **운영 DB 에 적용된 뒤에 내용이 편집됐다.**
-- 러너는 파일명으로만 "적용됨"을 판단해 스킵하므로(`migration_history` 에 이미 있다)
-- 나중에 추가된 CREATE INDEX 는 **기존 DB 에 영영 반영되지 않는다.**
--
--     idx_payment_logs_created_at         payment_logs(created_at)
--     idx_payment_logs_event_type         payment_logs(event_type, status)
--     idx_payment_webhooks_received_at    payment_webhooks(received_at)
--     idx_payment_webhooks_status         payment_webhooks(processing_status)
--     idx_registry_credits_created_at     registry_credits(created_at)
--
-- 왜 지금 채우나 — 이것은 "새 배포에서만 다른 성능"을 만든다
-- ---------------------------------------------------------------------------
-- 다섯 개 전부 **관리자 조회 경로**가 쓰는 정렬/필터 열이다
-- (`api/v1/admin.py` 의 결제 목록·웹훅 목록, `api/v1/payment_logs.py`).
-- 지금은 네 테이블이 전부 0행이라 차이가 드러나지 않지만, 결제가 실연동되는 순간
-- **fresh clone 은 인덱스가 있고 기존 운영 DB 는 없는** 상태가 된다. 그러면 같은 코드가
-- 환경에 따라 다른 실행계획을 타고, 느린 쪽이 하필 **운영**이다. 재현도 어렵다.
--
-- 안전성
-- ---------------------------------------------------------------------------
-- `CREATE INDEX IF NOT EXISTS` 뿐이다. **테이블도 행도 건드리지 않는다.**
-- 대상 네 테이블은 이 DB 에서 전부 0행이라 생성 비용도 사실상 0이다.
-- 재실행해도 안전하고, 되돌리려면 각각 DROP INDEX 하면 된다.
--
-- 함께 손대지 **않는** 것 (일부러 남긴다)
-- ---------------------------------------------------------------------------
-- 1. 컬럼 제약 드리프트 4건 — `payment_webhooks.raw_payload`(fresh NOT NULL / live nullable),
--    `payment_webhooks.processing_status`(fresh DEFAULT 'RECEIVED' / live 없음),
--    `registry_credit_logs.delta` / `registry_credits.amount`(fresh DEFAULT 0 / live 없음).
--    이쪽은 인덱스와 달리 **테이블 재작성**이 필요하다(SQLite 는 제약 변경을 지원하지 않는다).
--    네 테이블 다 0행이라 재작성 자체는 안전하지만, DROP/RENAME 을 도는 동안 실패하면
--    복구가 필요한 형태라 **별도 마이그레이션으로 따로 다룬다**(다음 스프린트 후보).
--    `test_bootstrap.py` 의 `KNOWN_FRESH_ONLY_COLUMNS` / `KNOWN_LIVE_ONLY_COLUMNS` 가
--    그동안 이 격차를 계속 지킨다.
--
-- 2. `auction_case.court_code` (fresh nullable / live NOT NULL) — **live 쪽이 옳다.**
--    이 열은 `UNIQUE(court_code, case_no)` 의 앞자리인데 SQLite 는 NULL 을 서로 다른 값으로
--    보므로, nullable 이면 court_code 가 NULL 인 중복 사건이 제약을 그대로 통과한다.
--    즉 **더 엄격한 live 를 fresh 에 맞추면 오히려 방어가 사라진다.** 실측으로도 1,796행
--    전부 court_code 가 채워져 있다(NULL/빈값 0건). 방향을 반대로 잡아야 하는 항목이라
--    (소스를 live 에 맞춰야 한다) 여기서 성급히 건드리지 않는다.
--
-- 3. `registry_credit_logs.idx_registry_credit_logs_user_id` (live 에만 있음) — 지우지 않는다.
--    `idx_registry_credit_logs_user(user_id, effective_month)` 의 접두라 "중복"으로 보이지만,
--    migration 021 이 측정으로 확인했듯 **좁은 인덱스는 커버링 스캔에서 더 빠르다**
--    (같은 실험에서 접두 인덱스를 지웠더니 sido 검색이 +540%). 근거 없이 지우지 않는다.

CREATE INDEX IF NOT EXISTS idx_payment_logs_created_at
    ON payment_logs(created_at);
CREATE INDEX IF NOT EXISTS idx_payment_logs_event_type
    ON payment_logs(event_type, status);

CREATE INDEX IF NOT EXISTS idx_payment_webhooks_received_at
    ON payment_webhooks(received_at);
CREATE INDEX IF NOT EXISTS idx_payment_webhooks_status
    ON payment_webhooks(processing_status);

CREATE INDEX IF NOT EXISTS idx_registry_credits_created_at
    ON registry_credits(created_at);
