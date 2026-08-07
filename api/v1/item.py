import logging
from fastapi import APIRouter, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError
from storage.database import get_connection
from api.auth import SUPABASE_JWT_SECRET
from api.v1.recent_items import record_view

logger = logging.getLogger(__name__)

router = APIRouter()
bearer_scheme = HTTPBearer(auto_error=False)

@router.get("/item/{item_id}")
def get_item(item_id: int, credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme)):
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM auction_item WHERE id = ?", (item_id,)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="물건을 찾을 수 없습니다")

        case = conn.execute(
            "SELECT * FROM auction_case WHERE id = ?", (row["case_id"],)
        ).fetchone()

        doc_status = conn.execute(
            "SELECT doc_type, status FROM document_status WHERE item_id = ?",
            (item_id,)
        ).fetchall()

        tenants = conn.execute(
            "SELECT * FROM tenant_rights WHERE item_id = ?", (item_id,)
        ).fetchall()

        rights = conn.execute(
            "SELECT * FROM rights_summary WHERE item_id = ?", (item_id,)
        ).fetchone()

        # 로그인 사용자면 최근조회 자동 기록 + 즐겨찾기 여부 확인
        user_id = None
        if credentials:
            # 토큰이 유효하지 않아도 상세 조회 자체는 비로그인으로 계속 진행한다(선택적 인증).
            # 예전에는 bare except라 KeyboardInterrupt/SystemExit까지 삼켰고 원인도 남지 않았다.
            try:
                payload = jwt.decode(credentials.credentials, SUPABASE_JWT_SECRET,
                    algorithms=["HS256"], options={"verify_aud": False})
                user_id = payload.get("sub")
            except JWTError:
                logger.debug("item 상세: 토큰 검증 실패 — 비로그인으로 처리")
                user_id = None
            if user_id:
                try:
                    record_view(conn, user_id, item_id)
                except Exception:
                    # 최근조회 기록 실패가 상세 조회를 막으면 안 된다 — 기록만 포기한다.
                    logger.warning("최근조회 기록 실패 (item_id=%s)", item_id, exc_info=True)

        is_favorited = False
        if user_id:
            fav = conn.execute(
                "SELECT 1 FROM favorites WHERE user_id=? AND item_id=?",
                (user_id, item_id)
            ).fetchone()
            is_favorited = fav is not None

        return {
            "id": row["id"],
            "case_no": row["case_no"],
            "item_no": row["item_no"],
            "court_name": row["court_name"],
            "property_type": row["property_type"],
            "sido": row["sido"],
            "sigungu": row["sigungu"],
            "dong": row["dong"],
            "lot_number": row["lot_number"],
            "full_address": row["full_address"],
            "appraisal_price": row["appraisal_price"],
            "minimum_bid_price": row["minimum_bid_price"],
            "bid_rate": row["bid_rate"],
            "auction_date": row["auction_date"],
            "status": row["status"],
            "fail_count": row["fail_count"],
            "validation_status": row["validation_status"],
            "crawl_date": row["crawl_date"],
            "case": dict(case) if case else None,
            "documents": [{"doc_type": d["doc_type"], "status": d["status"]} for d in doc_status],
            "tenants": [dict(t) for t in tenants],
            "rights_summary": dict(rights) if rights else None,
            "is_favorited": is_favorited,
        }
    finally:
        conn.close()
