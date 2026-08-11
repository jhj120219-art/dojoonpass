-- 006_create_payments.sql
CREATE TABLE IF NOT EXISTS payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    payment_type TEXT NOT NULL,
    amount INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING',
    pg_provider TEXT,
    pg_transaction_id TEXT,
    metadata TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
-- payment_type: SUBSCRIPTION / OVERAGE_USAGE
-- status: PENDING / SUCCESS / FAILED / REFUNDED
-- pg_provider: TOSS / IAMPORT / null (미연동)
CREATE INDEX IF NOT EXISTS idx_payments_user_id ON payments(user_id);
CREATE INDEX IF NOT EXISTS idx_payments_status ON payments(status);
