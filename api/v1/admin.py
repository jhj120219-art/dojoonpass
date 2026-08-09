import hmac
import logging
import os
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Header, Query
from pydantic import BaseModel
from storage.database import get_connection
from api.auth import success
# Admin은 실패를 전부 HTTPException(FastAPI 표준 detail)으로 반환한다 —
# 기존 클라이언트가 status_code로 분기하고 있어 envelope로 바꾸면 Breaking Change다.
# 따라서 여기서는 ErrorCode를 쓰지 않고, 상태/감사 관련 Enum만 가져온다.
from api.constants import AuditAction, AuditTargetType, RegistryRequestStatus
from api.v1.audit import record_audit, get_audit_logs

logger = logging.getLogger(__name__)

router = APIRouter()

# 값은 기존과 동일하다 — api/constants.py로 정의 위치만 모았다(오타·누락 방지).
VALID_STATUSES = tuple(s.value for s in RegistryRequestStatus)

# 관리자가 직접 바꿀 수 있는 전이만 허용한다. PAYMENT_REQUIRED는 결제 성공 시
# api/v1/payments.py가 자동으로 PENDING으로 옮기므로 관리자 전이 대상이 아니다.
# COMPLETED/FAILED는 종결 상태라 그 이후 전이가 없다.
ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "PENDING": {"PROCESSING", "FAILED"},
    "PROCESSING": {"COMPLETED", "FAILED"},
}


# 관리자 권한 2단계 (2026-08-07 CTO 승인). Operator 등급은 두지 않는다.
#   ADMIN       — 등기부 신청 운영(목록 조회, 상태 전이). 일상 운영자
#   SUPER_ADMIN — ADMIN의 모든 권한 + 과금에 직접 영향을 주는 조작(등기부 무료횟수 조정 등)
#
# 등급은 "어떤 키로 인증했는가"로 정해진다. 기존 ADMIN_API_KEY는 그대로 ADMIN 등급으로
# 동작하므로(하위호환) 이번 변경으로 기존 운영이 깨지지 않는다.
# 여기서 Supabase JWT를 쓰지 않는 이유는 docs/decision-log.md "Admin 인증" 참고.
ROLE_ADMIN = "ADMIN"
ROLE_SUPER_ADMIN = "SUPER_ADMIN"

# 등급별 포함 관계. SUPER_ADMIN은 ADMIN이 할 수 있는 것을 전부 할 수 있다.
ROLE_RANK = {ROLE_ADMIN: 1, ROLE_SUPER_ADMIN: 2}


def resolve_admin_role(x_admin_key: Optional[str]) -> Optional[str]:
    """제시된 키가 어느 등급에 해당하는지 판정한다. 어디에도 맞지 않으면 None.

    SUPER_ADMIN_API_KEY를 먼저 본다 — 두 값이 같게 설정된 경우 더 높은 등급을 준다.
    비교는 전부 상수 시간(hmac.compare_digest)으로 한다. 단순 `!=`는 앞에서부터 다르면
    즉시 반환되어 비교 시간이 일치하는 접두 길이에 비례하는 타이밍 사이드채널이 된다.
    """
    if not x_admin_key:
        return None
    super_key = os.getenv("SUPER_ADMIN_API_KEY", "")
    if super_key and hmac.compare_digest(x_admin_key, super_key):
        return ROLE_SUPER_ADMIN
    admin_key = os.getenv("ADMIN_API_KEY", "")
    if admin_key and hmac.compare_digest(x_admin_key, admin_key):
        return ROLE_ADMIN
    return None


def _require_role(x_admin_key: Optional[str], minimum: str) -> str:
    if not os.getenv("ADMIN_API_KEY", "") and not os.getenv("SUPER_ADMIN_API_KEY", ""):
        # 두 키 모두 없으면 Admin API 자체를 쓸 수 없다(기존 동작 유지: 500).
        raise HTTPException(status_code=500, detail="관리자 키 미설정")
    role = resolve_admin_role(x_admin_key)
    if role is None:
        # 키 값 자체는 절대 남기지 않는다(로그 유출 시 그대로 관리자 권한이 되므로).
        # 시도가 있었다는 사실만 기록해 무차별 대입을 사후에라도 인지할 수 있게 한다.
        logger.warning("Admin 인증 실패 (키 %s)", "불일치" if x_admin_key else "미제공")
        raise HTTPException(status_code=403, detail="관리자 권한이 없습니다")
    if ROLE_RANK[role] < ROLE_RANK[minimum]:
        logger.warning("Admin 권한 부족: %s 등급이 %s 전용 작업을 시도함", role, minimum)
        raise HTTPException(status_code=403, detail=f"{minimum} 권한이 필요합니다")
    return role


def require_admin(x_admin_key: Optional[str] = Header(None, alias="X-Admin-Key")) -> str:
    """ADMIN 이상. 등기부 신청 운영 전반."""
    return _require_role(x_admin_key, ROLE_ADMIN)


def require_super_admin(x_admin_key: Optional[str] = Header(None, alias="X-Admin-Key")) -> str:
    """SUPER_ADMIN 전용. 과금에 직접 영향을 주는 조작."""
    return _require_role(x_admin_key, ROLE_SUPER_ADMIN)


class StatusUpdateRequest(BaseModel):
    status: str
    reason: Optional[str] = None  # status=FAILED일 때 필수
    doc_url: Optional[str] = None  # status=COMPLETED일 때 필수. api/v1/registry.py의 download가 이 값을 그대로 사용한다


def row_to_admin_registry_request(row) -> dict:
    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "item_id": row["item_id"],
        "case_no": row["case_no"],
        "full_address": row["full_address"],
        "usage_id": row["usage_id"],
        "payment_id": row["payment_id"],
        "status": row["status"],
        "doc_url": row["doc_url"],
        "reason": row["reason"],
        "requested_at": row["requested_at"],
        "completed_at": row["completed_at"],
    }


@router.get("/admin/registry-requests")
def list_registry_requests(
    status: Optional[str] = Query(None),
    user_id: Optional[str] = Query(None),
    item_id: Optional[int] = Query(None),
    case_no: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
    admin_role: str = Depends(require_admin),
):
    if status is not None and status not in VALID_STATUSES:
        raise HTTPException(status_code=400, detail=f"허용되지 않는 status 값입니다: {status}")

    conn = get_connection()
    try:
        conditions = ["1=1"]
        params: list = []
        if status:
            conditions.append("rr.status = ?")
            params.append(status)
        if user_id:
            conditions.append("rr.user_id = ?")
            params.append(user_id)
        if item_id is not None:
            conditions.append("rr.item_id = ?")
            params.append(item_id)
        if case_no:
            conditions.append("ai.case_no LIKE ?")
            params.append(f"%{case_no}%")

        where = " AND ".join(conditions)
        total = conn.execute(
            f"""
            SELECT COUNT(*) FROM registry_requests rr
            JOIN auction_item ai ON rr.item_id = ai.id
            WHERE {where}
            """,
            params,
        ).fetchone()[0]

        offset = (page - 1) * size
        rows = conn.execute(
            f"""
            SELECT rr.*, ai.case_no, ai.full_address
            FROM registry_requests rr
            JOIN auction_item ai ON rr.item_id = ai.id
            WHERE {where}
            -- requested_at만으로 정렬하면 동률 행의 순서가 쿼리마다 달라질 수 있어,
            -- offset 페이지네이션에서 같은 행이 두 페이지에 나오거나 아예 빠질 수 있다.
            -- id를 tie-break로 걸어 정렬을 전순서(total order)로 만든다.
            ORDER BY rr.requested_at DESC, rr.id DESC
            LIMIT ? OFFSET ?
            """,
            params + [size, offset],
        ).fetchall()

        return success({
            "total": total,
            "page": page,
            "size": size,
            "items": [row_to_admin_registry_request(r) for r in rows],
        })
    finally:
        conn.close()


@router.patch("/admin/registry-requests/{request_id}")
def update_registry_request_status(
    request_id: int,
    req: StatusUpdateRequest,
    admin_role: str = Depends(require_admin),
):
    if req.status not in ("PROCESSING", "COMPLETED", "FAILED"):
        raise HTTPException(status_code=400, detail=f"허용되지 않는 상태 값입니다: {req.status}")
    if req.status == "FAILED" and not req.reason:
        raise HTTPException(status_code=400, detail="FAILED 처리에는 reason이 필요합니다")
    if req.status == "COMPLETED" and not req.doc_url:
        raise HTTPException(status_code=400, detail="COMPLETED 처리에는 doc_url이 필요합니다")

    conn = get_connection()
    try:
        current = conn.execute(
            "SELECT * FROM registry_requests WHERE id=?", (request_id,)
        ).fetchone()
        if not current:
            raise HTTPException(status_code=404, detail="신청을 찾을 수 없습니다")

        allowed_next = ALLOWED_TRANSITIONS.get(current["status"], set())
        if req.status not in allowed_next:
            raise HTTPException(
                status_code=400,
                detail=f"{current['status']} -> {req.status} 전이는 허용되지 않습니다",
            )

        now = datetime.now().isoformat()
        try:
            # WHERE에 status=current를 다시 걸어(2026-08-09 Sprint 39 TOCTOU 감사) SELECT와
            # UPDATE 사이에 다른 요청이 먼저 상태를 바꿨다면 rowcount=0으로 감지한다 — 이 조건이
            # 없으면 같은 request_id에 동시에 도착한 두 관리자 요청(예: 같은 PROCESSING 건을
            # 하나는 COMPLETED로, 하나는 FAILED로)이 둘 다 "현재 상태는 PROCESSING"을 보고
            # 통과해 나중에 커밋되는 쪽이 앞선 결과(doc_url/reason 포함)를 조용히 덮어쓸 수
            # 있었다. payments.py의 OVERAGE_USAGE 연결과 동일한 조건부 UPDATE 패턴이다.
            if req.status == "COMPLETED":
                cursor = conn.execute(
                    "UPDATE registry_requests SET status=?, completed_at=?, doc_url=? WHERE id=? AND status=?",
                    (req.status, now, req.doc_url, request_id, current["status"]),
                )
            elif req.status == "FAILED":
                cursor = conn.execute(
                    "UPDATE registry_requests SET status=?, reason=? WHERE id=? AND status=?",
                    (req.status, req.reason, request_id, current["status"]),
                )
            else:
                cursor = conn.execute(
                    "UPDATE registry_requests SET status=? WHERE id=? AND status=?",
                    (req.status, request_id, current["status"]),
                )
            if cursor.rowcount == 0:
                conn.rollback()
                raise HTTPException(
                    status_code=409,
                    detail=f"다른 요청이 먼저 상태를 바꿨습니다 (기대한 현재 상태: {current['status']})",
                )
            conn.commit()
        except HTTPException:
            raise
        except Exception:
            conn.rollback()
            raise

        # 상태 전이 감사 로그. registry_requests에 "누가/언제 바꿨는지"를 담을 컬럼이 없고
        # (스키마 변경은 승인 필요), Admin은 단일 공유키라 개별 운영자를 특정할 수도 없다 —
        # 최소한 어떤 신청이 어떤 상태로 넘어갔는지는 로그로 남겨 사후 추적이 가능하게 한다.
        logger.info(
            "Admin 상태 전이: registry_request id=%s %s -> %s (reason=%s, doc_url=%s, by=%s)",
            request_id, current["status"], req.status,
            req.reason or "-", req.doc_url or "-", admin_role,
        )
        # 감사 로그(CTO 승인 5번). 로그 파일은 회전·유실되므로 DB에도 남긴다 —
        # "이 신청이 왜 FAILED가 됐는지"를 나중에 실제로 되짚을 수 있어야 한다.
        # 바뀐 필드만 담는다(전체 행을 넣으면 무엇이 바뀌었는지 오히려 안 보인다).
        record_audit(
            conn, admin_id=admin_role,
            action=AuditAction.REGISTRY_STATUS_CHANGE,
            target_type=AuditTargetType.REGISTRY_REQUEST,
            target_id=request_id,
            before={"status": current["status"], "reason": current["reason"],
                    "doc_url": current["doc_url"]},
            after={"status": req.status, "reason": req.reason, "doc_url": req.doc_url},
        )
        conn.commit()

        updated = conn.execute(
            """
            SELECT rr.*, ai.case_no, ai.full_address
            FROM registry_requests rr
            JOIN auction_item ai ON rr.item_id = ai.id
            WHERE rr.id=?
            """,
            (request_id,),
        ).fetchone()
        return success(row_to_admin_registry_request(updated))
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 등기부 무료 횟수 조정 (CTO 승인 6번) — SUPER_ADMIN 전용
#
# 과금에 직접 영향을 주는 조작이라 일상 운영 등급(ADMIN)에게는 열지 않는다.
# 잔액을 직접 쓰지 않고 조정 원장에 append만 한다 — 설계 근거는
# api/v1/registry_credits.py 및 storage/migrations/015_create_registry_credits.sql 참고.
# ---------------------------------------------------------------------------
class RegistryCreditRequest(BaseModel):
    user_id: str
    reason_type: str            # GRANT / DEDUCT / RESET
    amount: int = 0             # 항상 양수 크기로 보낸다. 부호는 서버가 reason_type으로 정한다
    reason: Optional[str] = None


@router.get("/admin/registry-credits/{user_id}")
def get_registry_credit_status(
    user_id: str,
    admin_role: str = Depends(require_admin),
):
    """이 사용자의 이번 달 한도 구성과 조정 이력을 보여준다(조회는 ADMIN도 가능)."""
    from api.v1.registry import get_plan_free_limit, get_free_count, get_user_free_limit
    from api.v1.registry_credits import (
        get_credit_adjustment, get_current_month, row_to_credit,
    )

    conn = get_connection()
    try:
        month = get_current_month()
        plan_limit = get_plan_free_limit(conn, user_id)
        adjustment = get_credit_adjustment(conn, user_id, month)
        effective = get_user_free_limit(conn, user_id)
        used = get_free_count(conn, user_id)
        history = conn.execute(
            "SELECT * FROM registry_credits WHERE user_id=?"
            " ORDER BY created_at DESC, id DESC LIMIT 100",
            (user_id,),
        ).fetchall()
        return success({
            "user_id": user_id,
            "month": month,
            "plan_limit": plan_limit,
            "adjustment": adjustment,
            "effective_limit": effective,
            "used": used,
            # 남은 횟수는 음수가 되지 않도록 막는다(한도보다 많이 쓴 상태는 0으로 보인다).
            "remaining": max(0, effective - used),
            "history": [row_to_credit(r) for r in history],
        })
    finally:
        conn.close()


@router.post("/admin/registry-credits")
def adjust_registry_credit(
    req: RegistryCreditRequest,
    admin_role: str = Depends(require_super_admin),
):
    """무료 횟수를 추가(GRANT) / 차감(DEDUCT) / 초기화(RESET)한다."""
    from api.v1.registry import get_free_count, get_user_free_limit
    from api.v1.registry_credits import (
        add_credit, get_credit_adjustment, get_current_month, VALID_REASON_TYPES,
    )

    if not req.user_id.strip():
        raise HTTPException(status_code=400, detail="user_id가 필요합니다")
    if req.reason_type not in VALID_REASON_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"허용되지 않는 조정 유형입니다: {req.reason_type} "
                   f"(허용값: {', '.join(VALID_REASON_TYPES)})",
        )

    conn = get_connection()
    try:
        # 조정 전 값을 먼저 읽어 감사 로그의 before로 쓴다.
        before_adjustment = get_credit_adjustment(conn, req.user_id.strip())
        try:
            credit_id = add_credit(
                conn, req.user_id.strip(), req.reason_type, req.amount,
                req.reason, created_by=admin_role,
            )
            conn.commit()
        except ValueError as e:
            conn.rollback()
            raise HTTPException(status_code=400, detail=str(e))
        except Exception:
            conn.rollback()
            raise

        # 과금에 직접 영향을 주는 조작이라 반드시 감사 로그를 남긴다.
        logger.info(
            "Admin 등기부 한도 조정: user=%s %s amount=%s reason=%s (by=%s, credit_id=%s)",
            req.user_id, req.reason_type, req.amount, req.reason or "-", admin_role, credit_id,
        )
        record_audit(
            conn, admin_id=admin_role,
            action=AuditAction.REGISTRY_CREDIT_ADJUST,
            target_type=AuditTargetType.REGISTRY_CREDIT,
            target_id=credit_id,
            before={"user_id": req.user_id.strip(), "adjustment": before_adjustment},
            after={"user_id": req.user_id.strip(), "reason_type": req.reason_type,
                   "amount": req.amount, "reason": req.reason,
                   "adjustment": get_credit_adjustment(conn, req.user_id.strip())},
        )
        conn.commit()

        effective = get_user_free_limit(conn, req.user_id.strip())
        used = get_free_count(conn, req.user_id.strip())
        return success({
            "credit_id": credit_id,
            "user_id": req.user_id.strip(),
            "month": get_current_month(),
            "adjustment": get_credit_adjustment(conn, req.user_id.strip()),
            "effective_limit": effective,
            "used": used,
            "remaining": max(0, effective - used),
        })
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Admin REST 구조 (CTO 승인 7번)
#
# 목표 구조: /admin/users - /admin/payments - /admin/registry - /admin/subscriptions
#
# **기존 경로는 그대로 유지한다.** `/admin/registry-requests`와 `/admin/registry-credits`는
# 이미 운영 문서·테스트가 참조하고 있어 없애면 Breaking Change다(decision-log "기존 API 유지").
# 새 구조는 **추가**로 제공하고, 비어 있던 영역(users/payments/subscriptions)은 신규
# 엔드포인트로 채운다 — 경로 폐기나 응답 구조 변경처럼 Spec 결정이 필요한 것은 하지 않는다.
#
# 신규 엔드포인트는 구독 상태 변경 하나를 빼면 전부 **읽기 전용**이다.
# ---------------------------------------------------------------------------

def _offset(page: int, size: int) -> int:
    return (page - 1) * size


@router.get("/admin/registry/requests")
def admin_registry_requests(
    status: Optional[str] = Query(None),
    user_id: Optional[str] = Query(None),
    item_id: Optional[int] = Query(None),
    case_no: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
    admin_role: str = Depends(require_admin),
):
    """`/admin/registry-requests`의 새 구조 경로. 동작·응답이 완전히 동일하다."""
    return list_registry_requests(
        status=status, user_id=user_id, item_id=item_id, case_no=case_no,
        page=page, size=size, admin_role=admin_role,
    )


@router.get("/admin/users")
def admin_list_users(
    q: Optional[str] = Query(None, description="user_id 부분 일치"),
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
    admin_role: str = Depends(require_admin),
):
    """사용자 목록.

    이 저장소에는 users 테이블이 없다 — 인증은 Supabase `auth.users`가 담당하고 여기에는
    회원 정보가 없다(decision-log "Authentication"). 따라서 **서비스 활동이 있는 user_id를
    집계**해 보여준다. 이메일 등 개인정보는 Supabase 쪽에 있으므로 여기서 노출하지 않는다.
    """
    conn = get_connection()
    try:
        like = "%" + q + "%" if q else None
        where = "WHERE user_id LIKE ?" if like else ""
        params = [like] if like else []

        base = """
            SELECT user_id FROM payments
            UNION SELECT user_id FROM subscriptions
            UNION SELECT user_id FROM registry_requests
            UNION SELECT user_id FROM favorites
        """
        total = conn.execute(
            "SELECT COUNT(*) FROM (" + base + ") " + where, params
        ).fetchone()[0]
        # ★ 페이지를 먼저 자르고 그 결과에만 집계를 건다.
        # 집계 서브쿼리를 바깥에 두면 SQLite가 **전체 사용자**에 대해 4개 서브쿼리를 실행한
        # 뒤에야 ORDER BY/LIMIT를 적용한다 — 사용자가 N명이면 페이지 크기와 무관하게 4N번
        # 인덱스 탐색이 일어난다. 안쪽에서 LIMIT를 적용하면 4×size로 줄고, 정렬 기준과
        # 반환 행은 완전히 동일하다(user_id 단일 정렬이라 tie-break도 불필요).
        rows = conn.execute(
            "SELECT user_id,"
            " (SELECT COUNT(*) FROM payments p WHERE p.user_id = u.user_id) AS payment_count,"
            " (SELECT COUNT(*) FROM subscriptions s WHERE s.user_id = u.user_id) AS subscription_count,"
            " (SELECT COUNT(*) FROM registry_requests r WHERE r.user_id = u.user_id) AS registry_request_count,"
            " (SELECT COUNT(*) FROM favorites f WHERE f.user_id = u.user_id) AS favorite_count"
            " FROM (SELECT user_id FROM (" + base + ") " + where +
            "       ORDER BY user_id LIMIT ? OFFSET ?) u"
            " ORDER BY user_id",
            params + [size, _offset(page, size)],
        ).fetchall()
        return success([dict(r) for r in rows],
                       meta={"total": total, "page": page, "size": size})
    finally:
        conn.close()


@router.get("/admin/payments")
def admin_list_payments(
    user_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    payment_type: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
    admin_role: str = Depends(require_admin),
):
    """결제 목록(읽기 전용). 사용자용 `GET /payments`와 달리 전체 사용자를 대상으로 한다."""
    conn = get_connection()
    try:
        conditions, params = ["1=1"], []
        if user_id:
            conditions.append("user_id = ?")
            params.append(user_id)
        if status:
            conditions.append("status = ?")
            params.append(status)
        if payment_type:
            conditions.append("payment_type = ?")
            params.append(payment_type)
        where = " AND ".join(conditions)

        total = conn.execute(
            "SELECT COUNT(*) FROM payments WHERE " + where, params).fetchone()[0]
        rows = conn.execute(
            "SELECT * FROM payments WHERE " + where +
            " ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?",
            params + [size, _offset(page, size)],
        ).fetchall()
        return success([dict(r) for r in rows],
                       meta={"total": total, "page": page, "size": size})
    finally:
        conn.close()


@router.get("/admin/payments/{payment_id}/logs")
def admin_payment_logs(payment_id: int, admin_role: str = Depends(require_admin)):
    """결제 단계별 궤적(payment_logs). 결제 분쟁 대응용."""
    from api.v1.payment_logs import get_payment_logs

    conn = get_connection()
    try:
        exists = conn.execute("SELECT id FROM payments WHERE id=?", (payment_id,)).fetchone()
        if not exists:
            raise HTTPException(status_code=404, detail="결제 내역을 찾을 수 없습니다")
        return success(get_payment_logs(conn, payment_id))
    finally:
        conn.close()


@router.get("/admin/subscriptions")
def admin_list_subscriptions(
    user_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
    admin_role: str = Depends(require_admin),
):
    """구독 목록(읽기 전용).

    조회 전에 만료 동기화를 돌려 "만료됐는데 ACTIVE로 남은" 행이 잘못 보이지 않게 한다
    (api/v1/subscriptions.py의 lazy sync — 배치에 의존하지 않는 이유는 그쪽 docstring 참고).
    """
    from api.v1.subscriptions import sync_expired_status, row_to_subscription

    conn = get_connection()
    try:
        # 읽기 경로다 — 호출부에 트랜잭션이 없으므로 여기서 확정해야 변경이 남는다.
        sync_expired_status(conn, user_id, commit=True)

        conditions, params = ["1=1"], []
        if user_id:
            conditions.append("user_id = ?")
            params.append(user_id)
        if status:
            conditions.append("status = ?")
            params.append(status)
        where = " AND ".join(conditions)

        total = conn.execute(
            "SELECT COUNT(*) FROM subscriptions WHERE " + where, params).fetchone()[0]
        rows = conn.execute(
            "SELECT * FROM subscriptions WHERE " + where +
            " ORDER BY started_at DESC, id DESC LIMIT ? OFFSET ?",
            params + [size, _offset(page, size)],
        ).fetchall()
        return success([row_to_subscription(r) for r in rows],
                       meta={"total": total, "page": page, "size": size})
    finally:
        conn.close()


class SubscriptionStatusRequest(BaseModel):
    status: str
    reason: Optional[str] = None


@router.patch("/admin/subscriptions/{subscription_id}")
def admin_change_subscription_status(
    subscription_id: int,
    req: SubscriptionStatusRequest,
    admin_role: str = Depends(require_super_admin),
):
    """구독 상태 변경. 과금에 직접 영향을 주므로 SUPER_ADMIN 전용이다.

    전이 규칙(api/v1/state_machines.py)을 통과하지 못하면 400 — 임의 상태로 건너뛸 수 없다.
    """
    from api.v1.state_machines import InvalidTransition
    from api.v1.subscriptions import change_status

    conn = get_connection()
    try:
        try:
            result = change_status(conn, subscription_id, req.status, actor=admin_role)
        except LookupError:
            raise HTTPException(status_code=404, detail="구독을 찾을 수 없습니다")
        except InvalidTransition as e:
            conn.rollback()
            raise HTTPException(status_code=400, detail=str(e))

        record_audit(
            conn, admin_id=admin_role,
            action=AuditAction.SUBSCRIPTION_STATUS_CHANGE,
            target_type=AuditTargetType.SUBSCRIPTION,
            target_id=subscription_id,
            before={"status": result["before"]["status"],
                    "expires_at": result["before"]["expires_at"]},
            after={"status": result["after"]["status"],
                   "expires_at": result["after"]["expires_at"],
                   "reason": req.reason},
        )
        conn.commit()
        return success(result["after"])
    finally:
        conn.close()


@router.get("/admin/audit-logs")
def admin_audit_logs(
    target_type: Optional[str] = Query(None),
    target_id: Optional[str] = Query(None),
    admin_id: Optional[str] = Query(None),
    action: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
    admin_role: str = Depends(require_admin),
):
    """Admin 작업 이력 조회 (CTO 승인 5번)."""
    conn = get_connection()
    try:
        total, items = get_audit_logs(
            conn, target_type=target_type, target_id=target_id,
            admin_id=admin_id, action=action,
            limit=size, offset=_offset(page, size),
        )
        return success(items, meta={"total": total, "page": page, "size": size})
    finally:
        conn.close()


@router.get("/admin/registry/credit-logs/{user_id}")
def admin_registry_credit_logs(user_id: str, admin_role: str = Depends(require_admin)):
    """무료 횟수 변동 추적 로그 (CTO 승인 4번).

    `/admin/registry-credits/{user_id}`가 "현재 한도 + 조정 원장"을 보여준다면,
    이쪽은 "무료 횟수가 움직인 모든 사건"(지급·사용·회수·이벤트·환불)을 보여준다.
    """
    from api.v1.registry_credits import get_credit_logs

    conn = get_connection()
    try:
        return success(get_credit_logs(conn, user_id))
    finally:
        conn.close()
