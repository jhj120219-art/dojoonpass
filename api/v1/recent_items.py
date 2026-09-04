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
    # ★ "처음 본 시각"을 함께 남긴다 (2026-09-04, migration 031).
    #
    #   `viewed_at` 은 재조회마다 덮어써진다 — 그것이 "최근 본 물건" 정렬의 의미이므로
    #   그대로 둔다. 그런데 Time-to-Decision 의 **시작점**은 그 값이 될 수 없다:
    #   같은 물건을 다시 볼수록 시작점이 앞으로 끌려와, 오래 고민한 물건일수록
    #   T2D 가 짧게 나온다(정반대로 틀린다).
    #
    #   그래서 덮어쓰지 않는 열을 따로 둔다. `COALESCE(first_viewed_at, ?)` 가
    #   그 "덮어쓰지 않음"이다 — 이미 값이 있으면 지킨다.
    #
    #   031 의 운영 적용은 승인 영역이라 **열이 없는 환경이 실제로 존재한다.**
    #   무조건 쓰면 `no such column` 으로 물건 상세 조회가 통째로 500 이 된다 —
    #   부가 측정값 하나 때문에 핵심 화면이 죽는다. `favorites.py` 가
    #   `favorite_notes` 에 쓰는 것과 같은 판단이다.
    has_first = conn.execute(
        "SELECT 1 FROM pragma_table_info('recent_items') WHERE name='first_viewed_at'"
    ).fetchone() is not None
    if has_first:
        conn.execute("""
            INSERT INTO recent_items (user_id, item_id, viewed_at, first_viewed_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id, item_id) DO UPDATE SET
                viewed_at = ?,
                first_viewed_at = COALESCE(recent_items.first_viewed_at, ?)
        """, (user_id, item_id, now, now, now, now))
    else:
        conn.execute("""
            INSERT INTO recent_items (user_id, item_id, viewed_at)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id, item_id) DO UPDATE SET viewed_at = ?
        """, (user_id, item_id, now, now))
    # ★ 임장을 다녀온 물건의 행은 **지우지 않는다** (2026-09-04).
    #
    #   ## 왜 지금까지 문제가 아니었나
    #
    #   이 DELETE 는 저장 공간을 묶는 장치다. 위 주석이 적어 둔 그대로 —
    #   "사용자에게 보이는 동작은 그대로다(이미 20건 넘게는 안 보였다), 저장 공간만 준다."
    #   **표시 쿼리(`get_recent_items`)에 자체 `LIMIT` 이 이미 있기 때문에** 그 말이
    #   성립한다. 즉 행을 더 남겨도 화면은 20건 그대로다.
    #
    #   ## 왜 이제는 문제인가
    #
    #   2026-09-04 에 `first_viewed_at`(migration 031)이 이 표에 붙었다. 그 값은
    #   Time-to-Decision 의 **시작점**이다. 그런데 행이 지워지면 열이 있어도 소용없다 —
    #   물건을 많이 보는 사용자일수록 처음 본 기록이 먼저 사라지고, 그 결과 T2D 는
    #   **가벼운 사용자 쪽으로 치우쳐** 측정된다(`audit_time_to_decision.py` [5]).
    #
    #   ## 왜 이것이 정책 변경이 아닌가
    #
    #   상한(20)을 바꾸지 않는다. 화면에 보이는 개수도 그대로다. 남기는 것은
    #   **임장을 다녀온 물건**뿐이고, 그 수는 사용자가 실제로 현장에 간 횟수라
    #   본질적으로 작다(500건을 임장하지 않는다). 즉 저장 비용의 성격이 바뀌지 않는다.
    #
    #   그리고 이 물건들이야말로 사용자가 **가장 오래 붙들고 판단한 것**이다 —
    #   T2D 가 재려는 바로 그 대상이 지워지고 있었던 셈이다.
    #
    #   ## 030 이 없는 환경
    #
    #   `field_visits` 가 없으면 예전 그대로 동작한다. 부가 측정 하나 때문에
    #   최근 본 물건 기록이 통째로 실패하면 안 된다(이 파일의 다른 방어와 같은 판단).
    keep_visited = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='field_visits'"
    ).fetchone() is not None
    if keep_visited:
        conn.execute("""
            DELETE FROM recent_items
             WHERE user_id = ?
               AND id NOT IN (
                   SELECT id FROM recent_items WHERE user_id = ?
                    ORDER BY viewed_at DESC, id DESC LIMIT ?
               )
               AND item_id NOT IN (
                   SELECT item_id FROM field_visits WHERE user_id = ?
               )
        """, (user_id, user_id, RECENT_ITEMS_DISPLAY_LIMIT, user_id))
    else:
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
