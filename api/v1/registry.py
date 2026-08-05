import os
import mimetypes
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from datetime import datetime
from storage.database import get_connection
from api.auth import get_current_user, success, fail

router = APIRouter()

FREE_LIMIT = 5
OVERAGE_FEE = 1000  # 무료 초과 시 건당 금액. api/v1/payments.py의 OVERAGE_USAGE 결제 검증이 이 값을 그대로 참조한다.

# 등기부 실제 문서 저장 위치. api/v1/documents.py의 DOCUMENT_ROOT(크롤러가 수집하는
# STATUS/SPEC/APPRAISAL)와는 별개다 — 등기부등본은 이 크롤러가 수집하는 대상이 아니라
# 별도 경로(대법원 인터넷등기소 등)로 발급받아 운영자가 Admin(api/v1/admin.py)을 통해
# doc_url을 등록하는 방식으로 연결한다(자동 수집 엔진 아님, 문서 전달 경로만 구현).
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REGISTRY_DOCUMENT_ROOT = os.path.join(PROJECT_ROOT, "registry_documents")

class RegistryRequest(BaseModel):
    item_id: int

def get_free_count(conn, user_id: str) -> int:
    return conn.execute(
        "SELECT COUNT(*) FROM registry_usage WHERE user_id=? AND is_free=1",
        (user_id,)
    ).fetchone()[0]

def has_active_subscription(conn, user_id: str) -> bool:
    now = datetime.now().isoformat()
    row = conn.execute("""
        SELECT id FROM subscriptions
        WHERE user_id=? AND status='ACTIVE'
        AND (expires_at IS NULL OR expires_at > ?)
    """, (user_id, now)).fetchone()
    return row is not None

@router.post("/registry-requests")
def create_registry_request(req: RegistryRequest, user_id: str = Depends(get_current_user)):
    conn = get_connection()
    # 무료횟수 COUNT는 api/v1/payments.py의 OVERAGE_USAGE처럼 "row 하나를 조건부로 잠그는"
    # 방식으로는 막을 수 없는 집계 값이라, 이 커넥션의 트랜잭션을 직접 제어해(BEGIN IMMEDIATE로
    # 즉시 쓰기 락 선점) COUNT 확인과 INSERT를 하나의 원자적 단위로 묶는다 — 동시 요청 중
    # 하나가 커밋을 마칠 때까지 다른 요청은 자신의 COUNT를 다시 셀 수 없으므로 레이스가 없어진다.
    conn.isolation_level = None
    try:
        # 물건 존재 확인
        item = conn.execute(
            "SELECT id FROM auction_item WHERE id=?", (req.item_id,)
        ).fetchone()
        if not item:
            raise HTTPException(status_code=404, detail="물건을 찾을 수 없습니다")

        # 구독 확인
        if not has_active_subscription(conn, user_id):
            return fail("구독이 필요합니다")

        now = datetime.now().isoformat()

        conn.execute("BEGIN IMMEDIATE")
        try:
            # 무료 횟수 확인 (이 지점부터는 쓰기 락을 쥐고 있어 다른 요청과 절대 겹치지 않는다)
            free_used = get_free_count(conn, user_id)
            is_free = free_used < FREE_LIMIT
            charged_amount = 0 if is_free else OVERAGE_FEE

            # PAYMENT_REQUIRED 처리
            if not is_free:
                req_id = conn.execute("""
                    INSERT INTO registry_requests
                    (user_id, item_id, status, requested_at)
                    VALUES (?,?,?,?)
                """, (user_id, req.item_id, "PAYMENT_REQUIRED", now)).lastrowid
                conn.commit()
                return success({
                    "id": req_id,
                    "item_id": req.item_id,
                    "status": "PAYMENT_REQUIRED",
                    "is_free": False,
                    "free_remaining": 0,
                    "charged_amount": OVERAGE_FEE,
                    "requested_at": now,
                })

            # 무료 사용 기록
            usage_id = conn.execute("""
                INSERT INTO registry_usage
                (user_id, item_id, is_free, charged_amount, used_at)
                VALUES (?,?,?,?,?)
            """, (user_id, req.item_id, 1, 0, now)).lastrowid

            # 신청 생성
            req_id = conn.execute("""
                INSERT INTO registry_requests
                (user_id, item_id, usage_id, status, requested_at)
                VALUES (?,?,?,?,?)
            """, (user_id, req.item_id, usage_id, "PENDING", now)).lastrowid

            conn.commit()
            return success({
                "id": req_id,
                "item_id": req.item_id,
                "status": "PENDING",
                "is_free": True,
                "free_remaining": FREE_LIMIT - free_used - 1,
                "charged_amount": 0,
                "requested_at": now,
            })
        except Exception:
            conn.rollback()
            raise
    finally:
        conn.close()

@router.get("/registry-requests")
def get_registry_requests(user_id: str = Depends(get_current_user)):
    conn = get_connection()
    try:
        rows = conn.execute("""
            SELECT rr.*, ai.full_address, ai.case_no
            FROM registry_requests rr
            JOIN auction_item ai ON rr.item_id = ai.id
            WHERE rr.user_id = ?
            ORDER BY rr.requested_at DESC
        """, (user_id,)).fetchall()
        return success([{
            "id": r["id"],
            "item_id": r["item_id"],
            "case_no": r["case_no"],
            "full_address": r["full_address"],
            "status": r["status"],
            "reason": r["reason"],
            "requested_at": r["requested_at"],
            "completed_at": r["completed_at"],
        } for r in rows])
    finally:
        conn.close()

@router.get("/registry-requests/{request_id}")
def get_registry_request(request_id: int, user_id: str = Depends(get_current_user)):
    conn = get_connection()
    try:
        row = conn.execute("""
            SELECT rr.*, ai.full_address, ai.case_no
            FROM registry_requests rr
            JOIN auction_item ai ON rr.item_id = ai.id
            WHERE rr.id=? AND rr.user_id=?
        """, (request_id, user_id)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="신청을 찾을 수 없습니다")
        return success({
            "id": row["id"],
            "item_id": row["item_id"],
            "case_no": row["case_no"],
            "full_address": row["full_address"],
            "status": row["status"],
            "reason": row["reason"],
            "requested_at": row["requested_at"],
            "completed_at": row["completed_at"],
        })
    finally:
        conn.close()

@router.get("/registry-requests/{request_id}/download")
def download_registry(request_id: int, user_id: str = Depends(get_current_user)):
    conn = get_connection()
    try:
        # 본인 신청만 조회 가능(WHERE user_id=?로 소유권 확인) — 다른 유저의 request_id를
        # 넣어도 404로 응답해 존재 자체를 노출하지 않는다.
        row = conn.execute(
            "SELECT * FROM registry_requests WHERE id=? AND user_id=?",
            (request_id, user_id)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="신청을 찾을 수 없습니다")
        if row["status"] != "COMPLETED":
            # PENDING/PAYMENT_REQUIRED/PROCESSING/FAILED 등 실제 상태를 그대로 알려준다(거짓 UI 금지).
            return fail(f"발급이 완료되지 않았습니다 (현재 상태: {row['status']})")
        if not row["doc_url"]:
            # COMPLETED인데 doc_url이 없는 경우는 admin.py가 COMPLETED 전이 시 doc_url을 필수로
            # 받으므로 정상 경로로는 발생하지 않지만, 방어적으로 처리한다.
            return fail("발급된 문서를 찾을 수 없습니다")

        # 경로 탐색 방지: api/v1/documents.py:get_document()와 동일한 방식(commonpath 검사).
        file_path = os.path.join(REGISTRY_DOCUMENT_ROOT, row["doc_url"])
        real_root = os.path.realpath(REGISTRY_DOCUMENT_ROOT)
        real_file_path = os.path.realpath(file_path)
        if os.path.commonpath([real_root, real_file_path]) != real_root:
            raise HTTPException(status_code=404, detail="문서를 찾을 수 없습니다")
        if not os.path.exists(real_file_path):
            raise HTTPException(status_code=404, detail="문서 파일을 찾을 수 없습니다")

        media_type, _ = mimetypes.guess_type(real_file_path)
        return FileResponse(
            real_file_path,
            media_type=media_type or "application/octet-stream",
            filename=os.path.basename(real_file_path),
            content_disposition_type="attachment",
        )
    finally:
        conn.close()
