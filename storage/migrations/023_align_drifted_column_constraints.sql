-- 023_align_drifted_column_constraints.sql
--
-- [2026-08-26] fresh clone 과 라이브 DB 의 **컬럼 제약 드리프트 4건**을 닫는다.
--
-- 배경 — 021/022 와 같은 뿌리, 마지막 조각
-- ---------------------------------------------------------------------------
-- `014_create_payment_logs.sql` / `015_create_registry_credits.sql` /
-- `016_create_audit_and_credit_logs.sql` 이 **운영 DB 에 적용된 뒤에 편집됐다.**
-- 러너는 파일명으로만 "적용됨"을 판단하므로(이미 `migration_history` 에 있다) 나중에
-- 추가된 제약은 기존 DB 에 **영영 반영되지 않는다.** 022 가 그중 인덱스 5개를 채웠고,
-- 여기서 **컬럼 제약**을 맞춘다.
--
--     테이블                  컬럼                fresh(소스)          live(지금)
--     ---------------------  ------------------  -------------------  -----------
--     payment_webhooks       raw_payload         TEXT NOT NULL        TEXT
--     payment_webhooks       processing_status   DEFAULT 'RECEIVED'   기본값 없음
--     registry_credits       amount              DEFAULT 0            기본값 없음
--     registry_credit_logs   delta               DEFAULT 0            기본값 없음
--
-- 왜 위험한가 — "운영에서는 되는데 새 배포에서만 깨진다"
-- ---------------------------------------------------------------------------
-- `raw_payload` 가 대표 사례다. `api/v1/payment_logs.py:record_webhook()` 은
-- `_dump(raw_payload)` 를 그대로 넣는데, `_dump()` 는 `payload is None` 이면 **None 을
-- 그대로 돌려준다.** 지금 라이브는 nullable 이라 조용히 NULL 이 들어가고, fresh clone 은
-- NOT NULL 이라 `IntegrityError` 로 죽는다. **같은 코드가 환경에 따라 다르게 실패한다.**
--
-- 확인한 것: 유일한 제품 호출부(`api/v1/payments.py` 의 webhook 라우트)는 payload 를
-- `json.loads` 후 `isinstance(payload, dict)` 로 검증하고 실패하면 400 을 낸다. 즉
-- **지금 도는 경로에서는 None 이 오지 않는다** — NOT NULL 을 걸어도 정상 트래픽은 막히지
-- 않는다. 오히려 그 계약을 스키마가 강제하게 만드는 쪽이 맞다.
--
-- 방향은 **소스(더 엄격한 쪽)로 맞춘다.** 느슨한 쪽으로 맞추면 방어가 사라진다.
--
-- 안전성 — 세 테이블 모두 **0행**이다
-- ---------------------------------------------------------------------------
-- SQLite 는 컬럼 제약 변경을 지원하지 않아 "새 테이블 -> 복사 -> DROP -> RENAME" 이
-- 유일한 방법이다. 이 저장소가 011/012/013/018 에서 이미 쓰는 패턴 그대로 따른다.
--
--     payment_webhooks       0행
--     registry_credits       0행
--     registry_credit_logs   0행   (2026-08-26 실측)
--
-- **복사할 행이 하나도 없으므로 데이터 손실 가능성이 구조적으로 없다.** 그래도 형식을
-- 지켜 INSERT ... SELECT 를 그대로 둔다 — 혹시 다른 환경에서 행이 있어도 보존된다.
-- `id` 도 함께 옮겨 기존 참조를 깨지 않는다.
--
-- FK 주의: 러너는 `enforce_foreign_keys=False` 커넥션으로 실행한다(run_migrations.py 주석).
-- DROP 과 RENAME 사이에 자식 행이 잠시 고아가 되는 구간을 지나야 하기 때문이다.
--
-- 되돌리기: 이 파일의 CREATE 문에서 `NOT NULL` / `DEFAULT` 만 빼고 같은 순서로 다시 돌리면 된다.

-- ---------------------------------------------------------------------------
-- 1. payment_webhooks : raw_payload NOT NULL + processing_status DEFAULT 'RECEIVED'
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS payment_webhooks_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider TEXT NOT NULL,
    event_type TEXT,
    event_id TEXT UNIQUE,
    pg_transaction_id TEXT,
    payment_id INTEGER REFERENCES payments(id),
    signature_verified INTEGER NOT NULL DEFAULT 0,
    processing_status TEXT NOT NULL DEFAULT 'RECEIVED',
    raw_payload TEXT NOT NULL,
    error_message TEXT,
    received_at TEXT NOT NULL,
    processed_at TEXT
);

-- 기존 행이 있고 raw_payload 가 NULL 이면 NOT NULL 때문에 실패한다. 그런 행은
-- **버리지 않고** 빈 JSON 객체로 승격한다 — "받긴 받았는데 본문이 없다"는 사실을
-- 남기는 편이, 행을 잃거나 마이그레이션이 죽는 것보다 낫다. (이 DB 에서는 0행이라 무의미.)
INSERT INTO payment_webhooks_new (
    id, provider, event_type, event_id, pg_transaction_id, payment_id,
    signature_verified, processing_status, raw_payload, error_message,
    received_at, processed_at
)
SELECT
    id, provider, event_type, event_id, pg_transaction_id, payment_id,
    COALESCE(signature_verified, 0),
    COALESCE(NULLIF(TRIM(COALESCE(processing_status, '')), ''), 'RECEIVED'),
    COALESCE(raw_payload, '{}'),
    error_message, received_at, processed_at
FROM payment_webhooks;

DROP TABLE payment_webhooks;
ALTER TABLE payment_webhooks_new RENAME TO payment_webhooks;

CREATE INDEX IF NOT EXISTS idx_payment_webhooks_payment_id ON payment_webhooks(payment_id);
CREATE INDEX IF NOT EXISTS idx_payment_webhooks_status ON payment_webhooks(processing_status);
CREATE INDEX IF NOT EXISTS idx_payment_webhooks_received_at ON payment_webhooks(received_at);

-- ---------------------------------------------------------------------------
-- 2. registry_credits : amount DEFAULT 0
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS registry_credits_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    reason_type TEXT NOT NULL,
    amount INTEGER NOT NULL DEFAULT 0,
    reason TEXT,
    effective_month TEXT NOT NULL,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL
);

INSERT INTO registry_credits_new (
    id, user_id, reason_type, amount, reason, effective_month, created_by, created_at
)
SELECT id, user_id, reason_type, COALESCE(amount, 0), reason,
       effective_month, created_by, created_at
FROM registry_credits;

DROP TABLE registry_credits;
ALTER TABLE registry_credits_new RENAME TO registry_credits;

CREATE INDEX IF NOT EXISTS idx_registry_credits_user_month ON registry_credits(user_id, effective_month);
CREATE INDEX IF NOT EXISTS idx_registry_credits_created_at ON registry_credits(created_at);

-- ---------------------------------------------------------------------------
-- 3. registry_credit_logs : delta DEFAULT 0
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS registry_credit_logs_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    reason_type TEXT NOT NULL,
    delta INTEGER NOT NULL DEFAULT 0,
    balance_after INTEGER,
    reason TEXT,
    effective_month TEXT NOT NULL,
    actor TEXT NOT NULL,
    related_credit_id INTEGER REFERENCES registry_credits(id),
    related_usage_id INTEGER REFERENCES registry_usage(id),
    created_at TEXT NOT NULL
);

INSERT INTO registry_credit_logs_new (
    id, user_id, reason_type, delta, balance_after, reason, effective_month,
    actor, related_credit_id, related_usage_id, created_at
)
SELECT id, user_id, reason_type, COALESCE(delta, 0), balance_after, reason,
       effective_month, actor, related_credit_id, related_usage_id, created_at
FROM registry_credit_logs;

DROP TABLE registry_credit_logs;
ALTER TABLE registry_credit_logs_new RENAME TO registry_credit_logs;

CREATE INDEX IF NOT EXISTS idx_registry_credit_logs_user ON registry_credit_logs(user_id, effective_month);
CREATE INDEX IF NOT EXISTS idx_registry_credit_logs_user_id ON registry_credit_logs(user_id);
CREATE INDEX IF NOT EXISTS idx_registry_credit_logs_reason ON registry_credit_logs(reason_type);
CREATE INDEX IF NOT EXISTS idx_registry_credit_logs_created_at ON registry_credit_logs(created_at);
