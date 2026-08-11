-- 014_create_payment_logs.sql
--
-- [CTO 승인 5번] 결제 로그 구조 선구축
--
-- KG이니시스 실연동은 론칭 직전까지 연기하지만, 로그 구조(Table/Entity/Repository/Interface/
-- Mock/테스트/문서)는 미리 만들어 둔다. **실제 API Key 연결은 하지 않는다.**
--
-- 왜 미리 만드는가:
-- 현재 payments 테이블은 "결제의 최종 상태" 한 줄만 갖는다. 실제 PG 연동이 붙으면
-- 주문 생성 -> 결제창 -> 승인 -> 서버 재검증 -> (환불/Webhook) 각 단계가 시간차를 두고
-- 발생하는데, 그 궤적이 아무데도 남지 않으면 결제 분쟁 시 "무슨 일이 있었는지" 재구성할 수 없다.
-- 구조를 먼저 만들어 두면 실연동 시 Provider 구현만 채우면 된다.

-- ---------------------------------------------------------------------------
-- payment_logs: 결제 생명주기의 각 단계를 시간순으로 append-only 기록한다.
--               (UPDATE/DELETE 하지 않는다 — 감사 추적이 목적)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS payment_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    -- 결제가 만들어지기 전 단계(주문 생성 실패 등)도 기록해야 하므로 nullable이다.
    payment_id INTEGER REFERENCES payments(id),
    user_id TEXT,
    -- CREATE_ORDER / CONFIRM / VERIFY / CANCEL / WEBHOOK — PaymentProvider의 생명주기와 1:1
    event_type TEXT NOT NULL,
    -- SUCCESS / FAILED / PENDING — 그 단계의 결과
    status TEXT NOT NULL,
    provider TEXT,              -- mock / kginicis (실연동 전에는 mock)
    order_id TEXT,              -- PG 주문 식별자
    pg_transaction_id TEXT,     -- PG 거래 식별자
    amount INTEGER,
    -- 요청/응답 원문(JSON 문자열). 카드번호 등 민감정보는 저장하지 않는다.
    request_payload TEXT,
    response_payload TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_payment_logs_payment_id ON payment_logs(payment_id);
CREATE INDEX IF NOT EXISTS idx_payment_logs_user_id ON payment_logs(user_id);
CREATE INDEX IF NOT EXISTS idx_payment_logs_created_at ON payment_logs(created_at);
CREATE INDEX IF NOT EXISTS idx_payment_logs_event_type ON payment_logs(event_type, status);

-- ---------------------------------------------------------------------------
-- payment_webhooks: PG가 보내는 Webhook(노티) 원문을 받은 그대로 보관한다.
--                   수신 엔드포인트는 아직 없다 — 구조만 준비한다.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS payment_webhooks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider TEXT NOT NULL,
    event_type TEXT,
    -- PG가 보낸 이벤트 고유 id. 같은 이벤트가 재전송돼도 두 번 처리하지 않도록
    -- UNIQUE로 멱등성을 보장한다(PG는 응답이 늦으면 같은 노티를 여러 번 보낸다).
    event_id TEXT UNIQUE,
    pg_transaction_id TEXT,
    payment_id INTEGER REFERENCES payments(id),
    -- 서명 검증 결과. 검증 전에는 payload를 신뢰하면 안 된다.
    signature_verified INTEGER NOT NULL DEFAULT 0,
    -- RECEIVED / PROCESSED / FAILED / IGNORED
    processing_status TEXT NOT NULL DEFAULT 'RECEIVED',
    raw_payload TEXT NOT NULL,
    error_message TEXT,
    received_at TEXT NOT NULL,
    processed_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_payment_webhooks_payment_id ON payment_webhooks(payment_id);
CREATE INDEX IF NOT EXISTS idx_payment_webhooks_status ON payment_webhooks(processing_status);
CREATE INDEX IF NOT EXISTS idx_payment_webhooks_received_at ON payment_webhooks(received_at);
