from fastapi import APIRouter, Depends
from datetime import datetime
from storage.database import get_connection
from api.auth import get_current_user, success

router = APIRouter()

def record_view(conn, user_id: str, item_id: int):
    now = datetime.now().isoformat()
    conn.execute("""
        INSERT INTO recent_items (user_id, item_id, viewed_at)
        VALUES (?, ?, ?)
        ON CONFLICT(user_id, item_id) DO UPDATE SET viewed_at = ?
    """, (user_id, item_id, now, now))
    conn.commit()

@router.get("/recent-items")
def get_recent_items(user_id: str = Depends(get_current_user)):
    conn = get_connection()
    try:
        rows = conn.execute("""
            SELECT ai.*, ri.viewed_at
            FROM recent_items ri
            JOIN auction_item ai ON ri.item_id = ai.id
            WHERE ri.user_id = ?
            ORDER BY ri.viewed_at DESC, ri.id DESC
            LIMIT 20
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
                "viewed_at": row["viewed_at"],
            })
        return success(items)
    finally:
        conn.close()
