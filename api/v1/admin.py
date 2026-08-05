import os
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Header, Query
from pydantic import BaseModel
from storage.database import get_connection
from api.auth import success

router = APIRouter()

VALID_STATUSES = ("PENDING", "PAYMENT_REQUIRED", "PROCESSING", "COMPLETED", "FAILED")

# 관리자가 직접 바꿀 수 있는 전이만 허용한다. PAYMENT_REQUIRED는 결제 성공 시
# api/v1/payments.py가 자동으로 PENDING으로 옮기므로 관리자 전이 대상이 아니다.
# COMPLETED/FAILED는 종결 상태라 그 이후 전이가 없다.
ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "PENDING": {"PROCESSING", "FAILED"},
    "PROCESSING": {"COMPLETED", "FAILED"},
}


def require_admin(x_admin_key: Optional[str] = Header(None, alias="X-Admin-Key")) -> None:
    admin_key = os.getenv("ADMIN_API_KEY", "")
    if not admin_key:
        raise HTTPException(status_code=500, detail="관리자 키 미설정")
    if not x_admin_key or x_admin_key != admin_key:
        raise HTTPException(status_code=403, detail="관리자 권한이 없습니다")


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
    _admin: None = Depends(require_admin),
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
            ORDER BY rr.requested_at DESC
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
    _admin: None = Depends(require_admin),
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
            if req.status == "COMPLETED":
                conn.execute(
                    "UPDATE registry_requests SET status=?, completed_at=?, doc_url=? WHERE id=?",
                    (req.status, now, req.doc_url, request_id),
                )
            elif req.status == "FAILED":
                conn.execute(
                    "UPDATE registry_requests SET status=?, reason=? WHERE id=?",
                    (req.status, req.reason, request_id),
                )
            else:
                conn.execute(
                    "UPDATE registry_requests SET status=? WHERE id=?",
                    (req.status, request_id),
                )
            conn.commit()
        except Exception:
            conn.rollback()
            raise

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
