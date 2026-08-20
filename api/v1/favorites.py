import sqlite3
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from datetime import datetime
from storage.database import get_connection
from api.auth import get_current_user, success, error_response
from api.constants import ErrorCode, is_sqlite_int
from api.v1.thumbnails import fetch_thumbnail_seqs, thumbnail_url

router = APIRouter()

class FavoriteRequest(BaseModel):
    item_id: int

def get_item_summary(conn, item_id: int) -> dict:
    # SQLite INTEGER 범위 밖의 id는 어떤 행도 될 수 없다 — 그대로 넘기면 sqlite3이
    # OverflowError를 던져 **로그인한 사용자가 500을 만들 수 있다**
    # (2026-08-17 Sprint 154 실측: POST /favorites {"item_id": 2**63} -> 500).
    # "없음"과 같은 뜻이므로 None을 돌려주고, 호출부의 기존 404 경로를 그대로 탄다.
    if not is_sqlite_int(item_id):
        return None
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
        except sqlite3.IntegrityError:
            # UNIQUE(user_id, item_id) 위반 = 이미 등록된 경우. 예전에는 Exception 전체를
            # 잡아 DB 잠금/디스크 오류까지 "이미 등록됨"으로 잘못 안내했다 — 중복 위반만
            # 이 메시지로 처리하고, 그 외 오류는 감추지 않고 그대로 올린다.
            conn.rollback()
            return error_response(ErrorCode.FAVORITE_ALREADY_EXISTS, "이미 관심물건으로 등록되어 있습니다")
        except Exception:
            conn.rollback()
            raise
        return success({"item_id": req.item_id, "created_at": now})
    finally:
        conn.close()

@router.delete("/favorites/{item_id}")
def remove_favorite(item_id: int, user_id: str = Depends(get_current_user)):
    # 범위 밖 id는 DELETE의 WHERE에도 바인딩할 수 없다(OverflowError -> 500).
    # 그런 즐겨찾기는 존재할 수 없으므로 rowcount=0일 때와 **같은 응답**을 준다.
    if not is_sqlite_int(item_id):
        return error_response(ErrorCode.FAVORITE_NOT_FOUND, "등록된 관심물건이 없습니다")
    conn = get_connection()
    try:
        result = conn.execute(
            "DELETE FROM favorites WHERE user_id=? AND item_id=?",
            (user_id, item_id)
        )
        conn.commit()
        if result.rowcount == 0:
            return error_response(ErrorCode.FAVORITE_NOT_FOUND, "등록된 관심물건이 없습니다")
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
            ORDER BY f.created_at DESC, f.id DESC
        """, (user_id,)).fetchall()
        # 대표 사진 순번을 **쿼리 1회**로 (2026-08-20 Sprint 224).
        # 검색목록에서 사진을 보고 담았는데 관심물건에서는 사진이 사라지던 공백을 메운다.
        # 물건마다 따로 물으면 곧바로 N+1이고, 그때도 화면은 똑같이 잘 보인다 —
        # 느려질 뿐이다. 그래서 search.py 와 **같은 함수**를 쓴다.
        thumbnails = fetch_thumbnail_seqs(conn, [r["id"] for r in rows])
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
                # 사진이 없는 물건은 null — 프런트가 썸네일 자리를 아예 만들지 않는다.
                "thumbnail_url": thumbnail_url(row["id"], thumbnails),
                "favorited_at": row["favorited_at"],
            })
        return success(items)
    finally:
        conn.close()
