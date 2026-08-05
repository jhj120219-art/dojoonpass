import json
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from storage.database import get_connection
from api.auth import get_current_user, success, fail
from api.v1.registry import OVERAGE_FEE
from api.v1.payment_providers import get_payment_provider

router = APIRouter()

# PG 실연동 전까지는 PAYMENT_PROVIDER=mock(기본값)으로 동작한다 — api/v1/payment_providers.py 참고.
# 구독 기간 정책이 아직 확정되지 않아 30일 고정으로 둔다 (사용자 확인 필요).
SUBSCRIPTION_PERIOD_DAYS = 30
VALID_PAYMENT_TYPES = ("SUBSCRIPTION", "OVERAGE_USAGE")
VALID_PLANS = ("BETA_EARLYBIRD", "STANDARD")
# 구독 정책 문서(docs/backend.md "구독 정책") 기준 금액. OVERAGE_FEE와 동일한 방식으로
# 서버에서 검증한다 — 클라이언트가 보낸 amount를 더 이상 그대로 신뢰하지 않는다.
PLAN_PRICES = {
    "BETA_EARLYBIRD": 9900,
    "STANDARD": 22900,
}


class PaymentCreateRequest(BaseModel):
    payment_type: str
    amount: int
    plan: str | None = None  # payment_type=SUBSCRIPTION일 때 필수


def row_to_payment(row) -> dict:
    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "payment_type": row["payment_type"],
        "amount": row["amount"],
        "status": row["status"],
        "pg_provider": row["pg_provider"],
        "pg_transaction_id": row["pg_transaction_id"],
        "metadata": row["metadata"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def row_to_subscription(row) -> dict:
    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "plan": row["plan"],
        "price": row["price"],
        "status": row["status"],
        "started_at": row["started_at"],
        "expires_at": row["expires_at"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def row_to_registry_request(row) -> dict:
    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "item_id": row["item_id"],
        "usage_id": row["usage_id"],
        "payment_id": row["payment_id"],
        "status": row["status"],
        "doc_url": row["doc_url"],
        "requested_at": row["requested_at"],
        "completed_at": row["completed_at"],
    }


def create_payment_record(conn, user_id: str, payment_type: str, amount: int, plan: str | None, now: str) -> tuple[int, str]:
    # 실제 승인/거절은 provider가 결정한다 — payments.py는 그 결과(status)를 그대로 기록만 한다.
    # Interface v2(2026-08-05): charge() 단일 호출 대신, 실제 PG 흐름(주문 생성→결제창→승인→
    # 서버 재검증)과 동일한 순서로 provider를 호출한다. 지금은 MockProvider만 쓰므로 사용자가
    # 결제창에서 결제를 마치고 돌아오는 단계가 없어 confirm_payment를 곧바로 이어서 호출하지만,
    # 실제 PG 연동 시에는 create_order 이후 클라이언트 리다이렉트→콜백을 거쳐 confirm_payment가
    # 호출되도록 이 지점만 바뀌면 된다(반환값 형태는 그대로라 아래 로직은 안 바뀜).
    metadata = json.dumps({"plan": plan}) if plan else None
    provider = get_payment_provider()

    order = provider.create_order(payment_type=payment_type, amount=amount, metadata=metadata)
    confirmed = provider.confirm_payment(order_id=order.order_id, pg_transaction_id="", amount=amount)
    # 클라이언트/콜백이 준 값을 그대로 믿지 않고 서버가 다시 확인한다(verify_payment).
    result = provider.verify_payment(pg_transaction_id=confirmed.pg_transaction_id)

    payment_id = conn.execute(
        """
        INSERT INTO payments
        (user_id, payment_type, amount, status, pg_provider, pg_transaction_id, metadata, created_at, updated_at)
        VALUES (?,?,?,?,?,?,?,?,?)
        """,
        (user_id, payment_type, amount, result.status, result.pg_provider, result.pg_transaction_id, metadata, now, now),
    ).lastrowid
    return payment_id, result.status


def create_subscription(conn, user_id: str, plan: str, price: int, now: str) -> int:
    started_at = now
    expires_at = (datetime.now() + timedelta(days=SUBSCRIPTION_PERIOD_DAYS)).isoformat()
    subscription_id = conn.execute(
        """
        INSERT INTO subscriptions
        (user_id, plan, price, status, started_at, expires_at, created_at, updated_at)
        VALUES (?,?,?,?,?,?,?,?)
        """,
        (user_id, plan, price, "ACTIVE", started_at, expires_at, now, now),
    ).lastrowid
    return subscription_id


@router.post("/payments")
def create_payment(req: PaymentCreateRequest, user_id: str = Depends(get_current_user)):
    if req.payment_type not in VALID_PAYMENT_TYPES:
        return fail("지원하지 않는 결제 유형입니다")
    if req.payment_type == "SUBSCRIPTION":
        if req.plan not in VALID_PLANS:
            return fail("구독 플랜이 올바르지 않습니다")
        # OVERAGE_FEE 검증과 동일한 방식: 클라이언트가 보낸 amount를 신뢰하지 않고
        # 플랜별 고정 가격(PLAN_PRICES)과 비교한다.
        if req.amount != PLAN_PRICES[req.plan]:
            return fail(f"결제 금액이 올바르지 않습니다 ({PLAN_PRICES[req.plan]}원)")
    # OVERAGE_USAGE는 registry_requests에 저장된 별도 charged_amount 컬럼이 없어(등기부 신청
    # 응답에만 실리는 값), registry.py와 공유하는 OVERAGE_FEE 상수를 기준으로 정합성을 검증한다.
    if req.payment_type == "OVERAGE_USAGE" and req.amount != OVERAGE_FEE:
        return fail(f"결제 금액이 올바르지 않습니다 ({OVERAGE_FEE}원)")

    conn = get_connection()
    try:
        # OVERAGE_USAGE는 이 결제로 해결할 등기부 신청을 먼저 확정한다(가장 오래된 미결제 건).
        # 여기서 대상이 없으면 결제 자체를 만들지 않는다 — 짝이 없는 payment row가 남지 않도록.
        target_request = None
        if req.payment_type == "OVERAGE_USAGE":
            target_request = conn.execute(
                """
                SELECT * FROM registry_requests
                WHERE user_id=? AND status='PAYMENT_REQUIRED' AND payment_id IS NULL
                ORDER BY requested_at ASC LIMIT 1
                """,
                (user_id,)
            ).fetchone()
            if not target_request:
                return fail("결제가 필요한 등기부 신청이 없습니다")

        now = datetime.now().isoformat()
        try:
            payment_id, payment_status = create_payment_record(conn, user_id, req.payment_type, req.amount, req.plan, now)

            if payment_status != "SUCCESS":
                # provider가 거절/실패를 반환한 경우. MockProvider는 항상 SUCCESS라 지금은
                # 도달하지 않지만, 실제 PG 연동 시 이 분기가 그대로 쓰인다 — 실패 기록은 남기고
                # 구독/등기부 연결 같은 후속 효과는 만들지 않는다.
                conn.commit()
                return fail("결제에 실패했습니다")

            subscription_row = None
            if req.payment_type == "SUBSCRIPTION":
                subscription_id = create_subscription(conn, user_id, req.plan, req.amount, now)
                subscription_row = conn.execute(
                    "SELECT * FROM subscriptions WHERE id=?", (subscription_id,)
                ).fetchone()

            linked_registry_request = None
            if target_request is not None:
                # WHERE에 payment_id IS NULL/status 조건을 다시 걸어, 조회 이후 다른 요청이 먼저
                # 선점했다면(동시 결제 레이스) rowcount=0으로 감지해 이 결제를 롤백한다.
                cursor = conn.execute(
                    """
                    UPDATE registry_requests SET payment_id=?, status='PENDING'
                    WHERE id=? AND payment_id IS NULL AND status='PAYMENT_REQUIRED'
                    """,
                    (payment_id, target_request["id"]),
                )
                if cursor.rowcount == 0:
                    conn.rollback()
                    return fail("이미 결제 처리된 등기부 신청입니다")
                linked_registry_request = conn.execute(
                    "SELECT * FROM registry_requests WHERE id=?", (target_request["id"],)
                ).fetchone()

            conn.commit()
        except Exception:
            conn.rollback()
            raise

        payment_row = conn.execute("SELECT * FROM payments WHERE id=?", (payment_id,)).fetchone()
        return success({
            "payment": row_to_payment(payment_row),
            "subscription": row_to_subscription(subscription_row) if subscription_row else None,
            "registry_request": row_to_registry_request(linked_registry_request) if linked_registry_request else None,
        })
    finally:
        conn.close()


@router.get("/payments")
def get_payments(user_id: str = Depends(get_current_user)):
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM payments WHERE user_id=? ORDER BY created_at DESC",
            (user_id,)
        ).fetchall()
        return success([row_to_payment(r) for r in rows])
    finally:
        conn.close()


@router.get("/payments/{payment_id}")
def get_payment(payment_id: int, user_id: str = Depends(get_current_user)):
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM payments WHERE id=? AND user_id=?",
            (payment_id, user_id)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="결제 내역을 찾을 수 없습니다")
        return success(row_to_payment(row))
    finally:
        conn.close()
