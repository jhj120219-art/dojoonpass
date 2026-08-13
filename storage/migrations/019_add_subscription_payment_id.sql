-- 019_add_subscription_payment_id.sql
--
-- 왜 필요한가 (2026-08-13 Sprint 96, BUGS #94)
--
-- 결제와 구독을 잇는 열쇠가 없었다. 구독 결제를 환불해도 어느 구독이 그 결제로
-- 만들어졌는지 코드가 알 수 없어, "환불했는데 구독이 그대로 살아 있다"를 고칠
-- 대상조차 특정할 수 없었다.
--
--     registry_requests   payment_id 있음   결제 <-> 등기부 신청이 이어진다
--     subscriptions       payment_id 없음   여기만 끊겨 있었다
--
-- 환불 시 구독을 어떻게 할지(즉시 해지/주기 만료/일할)는 **정책 결정 대기**이고
-- 이 마이그레이션은 그것을 정하지 않는다. 어떤 선택지를 고르든 먼저 있어야 하는
-- 식별자만 만든다. docs/roadmap.md "결정 대기 - 구독 결제를 환불하면" 참고.
--
-- NULL 허용: 이 칼럼이 생기기 전에 만들어진 구독은 결제를 특정할 수 없다.
-- 0이나 -1 같은 가짜 값으로 채우면 "모르는 것"과 "없는 것"이 구분되지 않는다.
ALTER TABLE subscriptions ADD COLUMN payment_id INTEGER REFERENCES payments(id);

CREATE INDEX IF NOT EXISTS idx_subscriptions_payment_id ON subscriptions(payment_id);
