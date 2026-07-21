from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from datetime import datetime
from storage.database import get_connection
from api.auth import get_current_user, success, fail

router = APIRouter()

FREE_LIMIT = 5

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

        # 무료 횟수 확인
        free_used = get_free_count(conn, user_id)
        is_free = free_used < FREE_LIMIT
        charged_amount = 0 if is_free else 1000
        now = datetime.now().isoformat()

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
                "charged_amount": 1000,
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
            "requested_at": row["requested_at"],
            "completed_at": row["completed_at"],
        })
    finally:
        conn.close()

@router.get("/registry-requests/{request_id}/download")
def download_registry(request_id: int, user_id: str = Depends(get_current_user)):
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM registry_requests WHERE id=? AND user_id=?",
            (request_id, user_id)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="신청을 찾을 수 없습니다")
        if row["status"] != "COMPLETED":
            return fail("발급이 완료되지 않았습니다")
        # 실제 파일 미구현 - 501
        raise HTTPException(status_code=501, detail="등기부 수집 모듈 미연결 상태입니다")
    finally:
        conn.close()
