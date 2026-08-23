import logging
from fastapi import APIRouter, Depends
from datetime import datetime
from storage.database import get_connection
from api.v1.thumbnails import fetch_thumbnail_seqs, thumbnail_url
from api.auth import get_current_user, success

logger = logging.getLogger(__name__)
router = APIRouter()

# 화면(GET /recent-items)이 보여주는 개수. 저장 쪽 정리(record_view)도 반드시 이 값을
# 그대로 참조한다 — 숫자를 복제해 두면 한쪽만 바뀌었을 때 조용히 어긋난다(이 저장소가
# 반복해서 겪은 실수 패턴, 예: MAX_DOC_RETRY/QUEUE_TO_DOC_STATUS_TYPE 단일 소스 관례).
RECENT_ITEMS_DISPLAY_LIMIT = 20

def record_view(conn, user_id: str, item_id: int):
    """조회 기록 + 오래된 행 정리.

    2026-08-22 신설 — 예전에는 INSERT/UPDATE만 하고 끝나, 화면은 항상 최신 20건만
    보여주는데(LIMIT) 실제 `recent_items` 테이블은 사용자가 서로 다른 물건을 볼 때마다
    한 행씩 **무한정** 쌓였다(같은 물건을 다시 보면 UNIQUE 제약으로 갱신만 되지만,
    새 물건을 보면 항상 새 행이다). 화면에 보이는 개수와 저장하는 개수를 같게 맞춘다 -
    사용자에게 보이는 동작은 그대로다(이미 20건 넘게는 안 보였다), 저장 공간만 준다.
    """
    now = datetime.now().isoformat()
    conn.execute("""
        INSERT INTO recent_items (user_id, item_id, viewed_at)
        VALUES (?, ?, ?)
        ON CONFLICT(user_id, item_id) DO UPDATE SET viewed_at = ?
    """, (user_id, item_id, now, now))
    conn.execute("""
        DELETE FROM recent_items
         WHERE user_id = ?
           AND id NOT IN (
               SELECT id FROM recent_items WHERE user_id = ?
                ORDER BY viewed_at DESC, id DESC LIMIT ?
           )
    """, (user_id, user_id, RECENT_ITEMS_DISPLAY_LIMIT))
    conn.commit()

@router.get("/recent-items")
def get_recent_items(user_id: str = Depends(get_current_user)):
    conn = get_connection()
    try:
        # ★ LEFT JOIN이어야 한다 (2026-08-23 Sprint 267, api/v1/admin.py:320의 registry_requests
        #   LEFT JOIN과 동일한 이유). INNER JOIN이면 `auction_item` 행이 없어진 항목이 사용자의
        #   최근 본 물건 목록에서 **아무 신호도 없이** 사라진다 - 지금은 FK가 걸려 있어 발생하지
        #   않지만, 011~013처럼 FK를 끄고 도는 재작성 마이그레이션 중 대상 행이 빠지면 이 상태가
        #   된다(admin.py가 이미 이 시나리오로 실측한 사례). 화면에 깨진 카드(전부 null)를
        #   보여줄 필요는 없으므로 사용자에게 보이는 목록은 그대로 걸러내되, 걸러진 사실 자체는
        #   로그에 남겨 조용히 방치되지 않게 한다.
        rows = conn.execute("""
            SELECT ai.*, ri.viewed_at
            FROM recent_items ri
            LEFT JOIN auction_item ai ON ri.item_id = ai.id
            WHERE ri.user_id = ?
            ORDER BY ri.viewed_at DESC, ri.id DESC
            LIMIT ?
        """, (user_id, RECENT_ITEMS_DISPLAY_LIMIT)).fetchall()
        orphaned = [r for r in rows if r["id"] is None]
        if orphaned:
            logger.warning(
                "recent_items가 삭제된 auction_item을 가리킨다 (user_id=%s, %d건)",
                user_id, len(orphaned))
        rows = [r for r in rows if r["id"] is not None]
        # 대표 사진 순번 배치 조회 (2026-08-20 Sprint 224) — favorites.py 와 같은 함수.
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
                "viewed_at": row["viewed_at"],
            })
        return success(items)
    finally:
        conn.close()
