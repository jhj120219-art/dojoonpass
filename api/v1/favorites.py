from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from datetime import datetime
from storage.database import get_connection
from api.auth import get_current_user, success, fail

router = APIRouter()

class FavoriteRequest(BaseModel):
    item_id: int

def get_item_summary(conn, item_id: int) -> dict:
    row = conn.execute(
        "SELECT * FROM auction_item WHERE id = ?", (item_id,)
    ).fetchone()
    if not row:
        return None
    return {
        "id": row["id"],
        "case_no": row["case_no"],
        "item_no": row["item_no"],
        "court_name": row["court_name"],
        "property_type": row["property_type"],
        "sido": row["sido"],
        "sigungu": row["sigungu"],
        "full_address": row["full_address"],
        "appraisal_price": row["appraisal_price"],
        "minimum_bid_price": row["minimum_bid_price"],
        "bid_rate": row["bid_rate"],
        "auction_date": row["auction_date"],
        "status": row["status"],
        "fail_count": row["fail_count"],
    }

@router.post("/favorites")
def add_favorite(req: FavoriteRequest, user_id: str = Depends(get_current_user)):
    conn = get_connection()
    try:
        item = get_item_summary(conn, req.item_id)
        if not item:
            raise HTTPException(status_code=404, detail="물건을 찾을 수 없습니다")
        now = datetime.now().isoformat()
        try:
            conn.execute(
                "INSERT INTO favorites (user_id, item_id, created_at) VALUES (?,?,?)",
                (user_id, req.item_id, now)
            )
            conn.commit()
        except Exception:
            return fail("이미 관심물건으로 등록되어 있습니다")
        return success({"item_id": req.item_id, "created_at": now})
    finally:
        conn.close()

@router.delete("/favorites/{item_id}")
def remove_favorite(item_id: int, user_id: str = Depends(get_current_user)):
    conn = get_connection()
    try:
        result = conn.execute(
            "DELETE FROM favorites WHERE user_id=? AND item_id=?",
            (user_id, item_id)
        )
        conn.commit()
        if result.rowcount == 0:
            return fail("등록된 관심물건이 없습니다")
        return success({"item_id": item_id})
    finally:
        conn.close()

@router.get("/favorites")
def get_favorites(user_id: str = Depends(get_current_user)):
    conn = get_connection()
    try:
        # get_item_summary()를 즐겨찾기 개수만큼 반복 호출하던 N+1 쿼리를 단일 JOIN으로 교체
        # (recent_items.py:get_recent_items()와 동일한 패턴). 응답 필드/순서는 기존과 동일하게 유지.
        rows = conn.execute("""
            SELECT ai.*, f.created_at AS favorited_at
            FROM favorites f
            JOIN auction_item ai ON f.item_id = ai.id
            WHERE f.user_id = ?
            ORDER BY f.created_at DESC
        """, (user_id,)).fetchall()
        items = []
        for row in rows:
            items.append({
                "id": row["id"],
                "case_no": row["case_no"],
                "item_no": row["item_no"],
                "court_name": row["court_name"],
                "property_type": row["property_type"],
                "sido": row["sido"],
                "sigungu": row["sigungu"],
                "full_address": row["full_address"],
                "appraisal_price": row["appraisal_price"],
                "minimum_bid_price": row["minimum_bid_price"],
                "bid_rate": row["bid_rate"],
                "auction_date": row["auction_date"],
                "status": row["status"],
                "fail_count": row["fail_count"],
                "favorited_at": row["favorited_at"],
            })
        return success(items)
    finally:
        conn.close()
