import json
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from storage.database import get_connection
from api.auth import get_current_user, success, error_response
from api.constants import (
    ErrorCode, PaymentType, BillingCycle as BillingCycleEnum,
    SubscriptionStatus, is_paid,
)
from api.v1.registry import OVERAGE_FEE, get_entitled_subscription
from api.v1.payment_providers import get_payment_provider
from api.v1.payment_logs import (
    log_payment_event, get_payment_logs,
    EVENT_CREATE_ORDER, EVENT_CONFIRM, EVENT_VERIFY,
    LOG_SUCCESS, LOG_PENDING,
)

router = APIRouter()

# PG 실연동 전까지는 PAYMENT_PROVIDER=mock(기본값)으로 동작한다 — api/v1/payment_providers.py 참고.
# 값은 기존과 동일하다 — api/constants.py로 정의 위치만 모았다(오타·누락 방지).
VALID_PAYMENT_TYPES = tuple(t.value for t in PaymentType)

# 결제 주기. 구독 요금제가 월/연 2가지라 기간을 상수 하나로 고정하지 않고 주기별로 둔다.
BILLING_MONTHLY = BillingCycleEnum.MONTHLY.value
BILLING_YEARLY = BillingCycleEnum.YEARLY.value
VALID_BILLING_CYCLES = (BILLING_MONTHLY, BILLING_YEARLY)
BILLING_PERIOD_DAYS = {
    BILLING_MONTHLY: 30,
    BILLING_YEARLY: 365,
}

# 구독 요금제 카탈로그 (docs/decision-log.md "구독 정책 최종 확정" 기준).
#
# 가격을 단일 정수로 두지 않고 list_price(정상가) / sale_price(실판매가)로 나눠 둔다 —
# 향후 할인 이벤트를 붙일 때 이 카탈로그의 값만 바꾸면 되고 결제/검증 로직은 손대지 않아도 된다.
#
# 각 가격 항목이 지원하는 필드(전부 선택, 없으면 정상가 청구):
#   list_price       : 정상가(필수)
#   sale_price       : 고정 할인가. 지정되면 이 값이 청구액
#   discount_percent : 정률 할인(%). sale_price가 없을 때만 적용
#   discount_start   : 할인 시작일 "YYYY-MM-DD" (생략 시 제한 없음)
#   discount_end     : 할인 종료일 "YYYY-MM-DD" (그날까지 포함, 생략 시 제한 없음)
#
# 기간을 벗어나면 자동으로 정상가로 돌아가므로, 이벤트 종료 시 코드를 고칠 필요가 없다.
# 계산은 전부 resolve_plan_price()가 담당한다 — 호출부는 가격 규칙을 알지 못한다.
PLAN_CATALOG = {
    "BASIC": {
        "label": "베이직",
        "registry_monthly_limit": 5,
        "prices": {
            BILLING_MONTHLY: {"list_price": 12900, "sale_price": None},
            BILLING_YEARLY: {"list_price": 154800, "sale_price": None},
        },
    },
    "PRO": {
        "label": "프로",
        "registry_monthly_limit": 10,
        "prices": {
            # 연간 할인 이벤트: 정상가 274,800원 → 판매가 198,000원
            BILLING_MONTHLY: {"list_price": 22900, "sale_price": None},
            BILLING_YEARLY: {"list_price": 274800, "sale_price": 198000},
        },
    },
}
VALID_PLANS = tuple(PLAN_CATALOG.keys())


def _is_discount_active(price_entry: dict, at: datetime = None) -> bool:
    """
    할인 적용 기간인지 판단한다.

    `discount_start`/`discount_end`(ISO 날짜 문자열, 둘 다 선택)가 없으면 기간 제한이 없는
    상시 할인으로 본다. 한쪽만 지정하는 것도 허용한다(시작만 = 그 이후 계속,
    종료만 = 그때까지). 종료일은 그날까지 포함한다(`<=` 비교).
    """
    start = price_entry.get("discount_start")
    end = price_entry.get("discount_end")
    if not start and not end:
        return True
    today = (at or datetime.now()).date().isoformat()
    if start and today < start:
        return False
    if end and today > end:
        return False
    return True


def resolve_plan_price(plan: str, billing_cycle: str, at: datetime = None) -> int | None:
    """
    플랜+결제주기로 실제 청구 금액을 결정한다(할인 적용 후 금액).

    가격 정책이 바뀌어도 호출부는 수정하지 않도록, 카탈로그 해석은 전부 이 함수에 모은다.
    알 수 없는 조합이면 None을 반환해 호출부가 거부하도록 한다.

    할인 우선순위: sale_price(고정 할인가) > discount_percent(정률 할인) > list_price(정상가).
    둘 다 지정되면 sale_price가 이긴다(명시적으로 적은 금액이 더 강한 의도이므로).
    `discount_start`/`discount_end` 기간을 벗어나면 할인을 무시하고 정상가로 청구한다.
    """
    plan_entry = PLAN_CATALOG.get(plan)
    if not plan_entry:
        return None
    price_entry = plan_entry["prices"].get(billing_cycle)
    if not price_entry:
        return None

    list_price = price_entry["list_price"]
    if not _is_discount_active(price_entry, at):
        return list_price

    sale_price = price_entry.get("sale_price")
    if sale_price is not None:
        return sale_price

    percent = price_entry.get("discount_percent")
    if percent:
        # 원 단위 절사(내림) — 청구 금액이 정상가를 넘지 않도록 보수적으로 계산한다.
        return int(list_price * (100 - percent) / 100)

    return list_price


def get_registry_monthly_limit(plan: str) -> int:
    """플랜별 등기부 월 무료 한도. 알 수 없는 플랜이면 0(무료 제공 없음)."""
    plan_entry = PLAN_CATALOG.get(plan)
    return plan_entry["registry_monthly_limit"] if plan_entry else 0


def build_plan_catalog_response(at: datetime = None) -> dict:
    """공개 플랜 카탈로그. 프론트가 가격을 하드코딩하지 않도록 서버가 내려준다.

    2026-08-07 CTO 승인 2번: **Backend가 가격/플랜의 단일 Source of Truth**다.
    예전에는 `properties/[id]/page.tsx`가 `PLAN_OPTIONS`로 같은 값을 복사해 갖고 있어,
    한쪽만 고치면 사용자가 본 금액으로 결제를 눌렀을 때 서버가 거부하는 상태가 됐다.

    `price`(실제 청구액)는 항상 `resolve_plan_price()`가 계산한 값이다 — 표시용 값과
    검증용 값이 같은 함수에서 나오므로 구조적으로 어긋날 수 없다.
    """
    plans = []
    for plan, entry in PLAN_CATALOG.items():
        prices = {}
        for cycle in VALID_BILLING_CYCLES:
            price_entry = entry["prices"].get(cycle)
            if not price_entry:
                continue
            charged = resolve_plan_price(plan, cycle, at)
            list_price = price_entry["list_price"]
            prices[cycle] = {
                "list_price": list_price,
                "price": charged,
                "discounted": charged < list_price,
                "discount_amount": max(0, list_price - charged),
                # 할인 기간은 설정된 경우에만 내려간다(없으면 상시 할인 또는 할인 없음).
                "discount_start": price_entry.get("discount_start"),
                "discount_end": price_entry.get("discount_end"),
                "period_days": BILLING_PERIOD_DAYS[cycle],
            }
        plans.append({
            "plan": plan,
            "label": entry["label"],
            "registry_monthly_limit": entry["registry_monthly_limit"],
            "prices": prices,
        })
    return {
        "plans": plans,
        "billing_cycles": list(VALID_BILLING_CYCLES),
        # 무료 한도를 초과했을 때의 건당 금액. 프론트가 별도 상수로 갖고 있던 값이다.
        "overage_fee": OVERAGE_FEE,
    }


@router.get("/plans")
def get_plans():
    """구독 플랜 카탈로그. 인증 불필요(가격은 공개 정보) — 비로그인 화면도 쓸 수 있어야 한다.

    /search·/item과 마찬가지로 인증이 필요 없는 라우트지만, 프론트가 기존 래퍼
    (`fetchJSON`)로 일관되게 다루도록 여기서는 envelope를 사용한다.
    """
    return success(build_plan_catalog_response())


class PaymentCreateRequest(BaseModel):
    payment_type: str
    amount: int
    plan: str | None = None  # payment_type=SUBSCRIPTION일 때 필수
    # 결제주기. 기존 호출(월 구독만 존재하던 시점)과의 호환을 위해 미지정 시 MONTHLY로 간주한다.
    billing_cycle: str | None = None


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


def _provider_name() -> str:
    """현재 선택된 provider 이름(로그 기록용). 값이 없으면 기존과 동일하게 mock."""
    import os
    return os.getenv("PAYMENT_PROVIDER", "mock").strip().lower()


def create_payment_record(conn, user_id: str, payment_type: str, amount: int, plan: str | None, now: str) -> tuple[int, str]:
    # 실제 승인/거절은 provider가 결정한다 — payments.py는 그 결과(status)를 그대로 기록만 한다.
    # Interface v2(2026-08-05): charge() 단일 호출 대신, 실제 PG 흐름(주문 생성→결제창→승인→
    # 서버 재검증)과 동일한 순서로 provider를 호출한다. 지금은 MockProvider만 쓰므로 사용자가
    # 결제창에서 결제를 마치고 돌아오는 단계가 없어 confirm_payment를 곧바로 이어서 호출하지만,
    # 실제 PG 연동 시에는 create_order 이후 클라이언트 리다이렉트→콜백을 거쳐 confirm_payment가
    # 호출되도록 이 지점만 바뀌면 된다(반환값 형태는 그대로라 아래 로직은 안 바뀜).
    metadata = json.dumps({"plan": plan}) if plan else None
    provider = get_payment_provider()
    provider_name = _provider_name()

    # 각 단계를 payment_logs에 남긴다(2026-08-07, CTO 승인 5번). payments 테이블은 최종 상태
    # 한 줄만 갖기 때문에, 분쟁이 생겼을 때 "무슨 순서로 무슨 일이 있었는지"를 재구성하려면
    # 단계별 기록이 따로 있어야 한다. payment_id는 아직 없으므로 아래에서 채운다.
    log_ids = []
    order = provider.create_order(payment_type=payment_type, amount=amount, metadata=metadata)
    log_ids.append(log_payment_event(
        conn, EVENT_CREATE_ORDER, LOG_SUCCESS, user_id=user_id, provider=provider_name,
        order_id=order.order_id, amount=amount,
        request_payload={"payment_type": payment_type, "amount": amount, "plan": plan},
    ))

    confirmed = provider.confirm_payment(order_id=order.order_id, pg_transaction_id="", amount=amount)
    log_ids.append(log_payment_event(
        conn, EVENT_CONFIRM, confirmed.status if confirmed.status in ("SUCCESS", "FAILED") else LOG_PENDING,
        user_id=user_id, provider=provider_name, order_id=order.order_id,
        pg_transaction_id=confirmed.pg_transaction_id, amount=amount,
    ))

    # 클라이언트/콜백이 준 값을 그대로 믿지 않고 서버가 다시 확인한다(verify_payment).
    result = provider.verify_payment(pg_transaction_id=confirmed.pg_transaction_id)
    log_ids.append(log_payment_event(
        conn, EVENT_VERIFY, result.status if result.status in ("SUCCESS", "FAILED") else LOG_PENDING,
        user_id=user_id, provider=provider_name, order_id=order.order_id,
        pg_transaction_id=result.pg_transaction_id, amount=amount,
        response_payload={"status": result.status, "pg_provider": result.pg_provider},
    ))

    payment_id = conn.execute(
        """
        INSERT INTO payments
        (user_id, payment_type, amount, status, pg_provider, pg_transaction_id, metadata, created_at, updated_at)
        VALUES (?,?,?,?,?,?,?,?,?)
        """,
        (user_id, payment_type, amount, result.status, result.pg_provider, result.pg_transaction_id, metadata, now, now),
    ).lastrowid

    # payments row가 생긴 뒤에야 payment_id를 알 수 있다 — 방금 남긴 로그 3건을 이어붙인다.
    # 이렇게 해야 GET /payments/{id}/logs로 한 결제의 전체 궤적을 한 번에 조회할 수 있다.
    conn.execute(
        "UPDATE payment_logs SET payment_id=? WHERE id IN (%s)" % ",".join("?" * len(log_ids)),
        [payment_id] + log_ids,
    )
    return payment_id, result.status


def create_subscription(conn, user_id: str, plan: str, price: int, now: str,
                        billing_cycle: str = BILLING_MONTHLY) -> int:
    started_at = now
    expires_at = (datetime.now() + timedelta(days=BILLING_PERIOD_DAYS[billing_cycle])).isoformat()
    subscription_id = conn.execute(
        """
        INSERT INTO subscriptions
        (user_id, plan, price, status, started_at, expires_at, created_at, updated_at)
        VALUES (?,?,?,?,?,?,?,?)
        """,
        (user_id, plan, price, SubscriptionStatus.ACTIVE.value, started_at, expires_at, now, now),
    ).lastrowid
    return subscription_id


@router.post("/payments")
def create_payment(req: PaymentCreateRequest, user_id: str = Depends(get_current_user)):
    if req.payment_type not in VALID_PAYMENT_TYPES:
        return error_response(ErrorCode.PAY_INVALID_TYPE, "지원하지 않는 결제 유형입니다")
    billing_cycle = req.billing_cycle or BILLING_MONTHLY
    if req.payment_type == "SUBSCRIPTION":
        if req.plan not in VALID_PLANS:
            return error_response(ErrorCode.PAY_INVALID_PLAN, "구독 플랜이 올바르지 않습니다")
        if billing_cycle not in VALID_BILLING_CYCLES:
            return error_response(ErrorCode.PAY_INVALID_BILLING_CYCLE, "결제 주기가 올바르지 않습니다")
        # OVERAGE_FEE 검증과 동일한 방식: 클라이언트가 보낸 amount를 신뢰하지 않고
        # 서버 카탈로그가 계산한 금액(할인 적용 후)과 비교한다.
        expected_amount = resolve_plan_price(req.plan, billing_cycle)
        if expected_amount is None:
            return error_response(ErrorCode.PAY_INVALID_PLAN, "구독 플랜이 올바르지 않습니다")
        if req.amount != expected_amount:
            return error_response(ErrorCode.PAY_AMOUNT_MISMATCH, f"결제 금액이 올바르지 않습니다 ({expected_amount}원)")
    # OVERAGE_USAGE는 registry_requests에 저장된 별도 charged_amount 컬럼이 없어(등기부 신청
    # 응답에만 실리는 값), registry.py와 공유하는 OVERAGE_FEE 상수를 기준으로 정합성을 검증한다.
    if req.payment_type == "OVERAGE_USAGE" and req.amount != OVERAGE_FEE:
        return error_response(ErrorCode.PAY_AMOUNT_MISMATCH, f"결제 금액이 올바르지 않습니다 ({OVERAGE_FEE}원)")

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
                ORDER BY requested_at ASC, id ASC LIMIT 1
                """,
                (user_id,)
            ).fetchone()
            if not target_request:
                return error_response(ErrorCode.PAY_NO_TARGET_REQUEST, "결제가 필요한 등기부 신청이 없습니다")

        # SUBSCRIPTION은 이미 유효한 구독(ACTIVE/GRACE_PERIOD)이 있으면 새로 만들지 않는다
        # (2026-08-09, docs/BUGS.md #19 Registry 중복신청 결함과 동일 패턴). 프론트
        # (properties/[id]/page.tsx)는 애초에 구독이 이미 유효하면 구독 UI 자체를 렌더링하지
        # 않으므로("이미 구독 중이면 재구독 불가"가 기존에 이미 전제된 불변식이다) 여기 도달하는
        # 건 중복 클릭·새로고침 재제출·직접 API 호출뿐이다.
        #
        # "확인 후 생성"은 그 자체로 SELECT -> 판단 -> INSERT 레이스다 — 기본 isolation_level은
        # 첫 쓰기 문에야 트랜잭션을 시작하므로, 커밋되지 않은 두 요청이 동시에 이 SELECT를 지나가면
        # 둘 다 "구독 없음"을 보고 통과할 수 있다(실측 재현: 동시 10회 요청 -> subscriptions/
        # payments 10개씩 생성, 2026-08-09). registry.py의 등기부 중복신청 방지와 동일하게
        # BEGIN IMMEDIATE로 쓰기 락을 먼저 선점해 확인+생성을 하나의 원자적 단위로 묶는다 —
        # 뒤에 오는 결제/구독 생성·최종 commit까지 전부 이 트랜잭션 안에서 이어진다.
        existing_subscription = None
        if req.payment_type == "SUBSCRIPTION":
            conn.isolation_level = None
            conn.execute("BEGIN IMMEDIATE")
            existing_subscription = get_entitled_subscription(conn, user_id)
            if existing_subscription is not None:
                conn.commit()
                return success({
                    "payment": None,
                    "subscription": row_to_subscription(existing_subscription),
                    "registry_request": None,
                    "already_subscribed": True,
                })

        now = datetime.now().isoformat()
        try:
            payment_id, payment_status = create_payment_record(conn, user_id, req.payment_type, req.amount, req.plan, now)

            # 레거시 SUCCESS와 신규 PAID를 모두 성공으로 취급한다(api/constants.py:is_paid).
            if not is_paid(payment_status):
                # provider가 거절/실패를 반환한 경우. MockProvider는 항상 SUCCESS라 지금은
                # 도달하지 않지만, 실제 PG 연동 시 이 분기가 그대로 쓰인다 — 실패 기록은 남기고
                # 구독/등기부 연결 같은 후속 효과는 만들지 않는다.
                conn.commit()
                return error_response(ErrorCode.PAY_FAILED, "결제에 실패했습니다")

            subscription_row = None
            if req.payment_type == "SUBSCRIPTION":
                subscription_id = create_subscription(conn, user_id, req.plan, req.amount, now, billing_cycle)
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
                    return error_response(ErrorCode.PAY_ALREADY_PROCESSED, "이미 결제 처리된 등기부 신청입니다")
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
            # created_at 동률 시 순서가 흔들리지 않도록 id로 tie-break한다(전 도메인 공통 규칙).
            "SELECT * FROM payments WHERE user_id=? ORDER BY created_at DESC, id DESC",
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


@router.get("/payments/{payment_id}/logs")
def get_payment_log_history(payment_id: int, user_id: str = Depends(get_current_user)):
    """이 결제의 단계별 궤적(주문 생성 → 승인 → 검증 …)을 시간순으로 반환한다.

    본인 결제만 조회 가능하다 — 다른 사용자의 payment_id를 넣으면 404로 응답해
    존재 자체를 노출하지 않는다(registry.py의 다운로드와 동일한 소유권 검사 패턴).
    """
    conn = get_connection()
    try:
        owned = conn.execute(
            "SELECT id FROM payments WHERE id=? AND user_id=?", (payment_id, user_id)
        ).fetchone()
        if not owned:
            raise HTTPException(status_code=404, detail="결제 내역을 찾을 수 없습니다")
        return success(get_payment_logs(conn, payment_id))
    finally:
        conn.close()
