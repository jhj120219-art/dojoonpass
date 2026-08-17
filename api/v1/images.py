"""물건 사진 서빙 (2026-08-17 Sprint 144).

`api/v1/documents.py`가 문서에 대해 하는 일을 사진에 대해 한다 — 같은 방어선을 그대로
따른다(경로 탐색 차단, 크기 0 거부, 없는 것은 정직하게 404).

## 문서 서빙과 다른 점 하나: 근거가 DB다

`documents.py`는 `auction_item`에서 (법원, 사건, 물건)을 읽어 **경로를 계산**해서 파일을
찾는다. 문서는 종류당 파일 하나로 이름이 고정("spec.pdf")이라 그렇게 할 수 있다.

사진은 개수가 0~N이고 확장자도 장마다 다를 수 있어(실측: 같은 물건 안에서 전경도는 jpg,
위치도는 gif) 경로를 계산으로 알아낼 수 없다. 그래서 `auction_image.storage_path`를
읽는다 — 크롤러가 실제로 쓴 그 경로다.

DB를 근거로 삼는 대신, **DB가 가리키는 경로가 실제로 존재하는지는 반드시 다시 확인한다.**
이 저장소가 반복해서 잡아 온 결함이 정확히 "DB는 있다는데 파일이 없다"이기 때문이다.
"""
import os
import logging

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from storage.database import get_connection
from api.constants import is_sqlite_int
from api.http_cache import not_modified
from crawler.image_assets import IMAGE_MEDIA_TYPES, MIN_IMAGE_BYTES

logger = logging.getLogger(__name__)

router = APIRouter()

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DOCUMENT_ROOT = os.path.join(PROJECT_ROOT, "documents")


def resolve_stored_path(storage_path: str) -> str:
    """DB의 `storage_path`(프로젝트 루트 기준 상대경로)를 절대경로로 바꾼다.

    옛 행이 절대경로를 들고 있어도 동작하도록 둘 다 받는다 — `os.path.join()`은
    두 번째 인자가 절대경로면 그것을 그대로 돌려주므로 분기가 필요 없다.
    """
    return os.path.join(PROJECT_ROOT, storage_path or "")


@router.get("/item/{item_id}/images/{seq}")
def get_item_image(item_id: int, seq: int, request: Request):
    # SQLite INTEGER 범위 밖의 값은 어떤 행도 될 수 없다 — 그대로 넘기면 sqlite3이
    # OverflowError를 던져 **인증 없이 500을 만들 수 있다**(2026-08-17 Sprint 144 실측).
    # `seq`도 같이 본다: 여기서는 두 값 모두 쿼리 바인딩에 그대로 들어간다.
    if not is_sqlite_int(item_id) or not is_sqlite_int(seq):
        raise HTTPException(status_code=404, detail="사진을 찾을 수 없습니다")

    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT storage_path FROM auction_image WHERE item_id=? AND seq=?",
            (item_id, seq),
        ).fetchone()
    finally:
        conn.close()

    if not row or not row["storage_path"]:
        raise HTTPException(status_code=404, detail="사진을 찾을 수 없습니다")

    file_path = resolve_stored_path(row["storage_path"])

    # 경로 탐색 방지 — `documents.py`와 같은 방식.
    # DB 값에서 경로를 만들기 때문에 문서 쪽보다 오히려 더 필요하다(관리 도구나 옛
    # 마이그레이션이 넣은 값이 항상 얌전하다고 가정하지 않는다).
    real_root = os.path.realpath(DOCUMENT_ROOT)
    real_path = os.path.realpath(file_path)
    if os.path.commonpath([real_root, real_path]) != real_root:
        logger.warning("사진 경로가 documents/ 밖을 가리킨다 (item=%s, seq=%s): %s",
                       item_id, seq, row["storage_path"])
        raise HTTPException(status_code=404, detail="사진을 찾을 수 없습니다")

    # "있다"의 기준을 크롤러(`image_assets.image_exists()`)와 같게 맞춘다.
    # 읽는 쪽만 느슨하면 "화면에는 있는데 열면 깨진 이미지"가 된다(BUGS #50 계열).
    if not os.path.isfile(real_path) or os.path.getsize(real_path) < MIN_IMAGE_BYTES:
        raise HTTPException(status_code=404, detail="사진을 찾을 수 없습니다")

    ext = os.path.splitext(real_path)[1].lstrip(".").lower()
    media_type = IMAGE_MEDIA_TYPES.get(ext, "application/octet-stream")

    response = FileResponse(
        real_path,
        media_type=media_type,
        # 사진은 내려받기가 아니라 화면에 그리는 용도다.
        content_disposition_type="inline",
        # ★ stat_result를 넘기지 않으면 Starlette가 **응답을 보낼 때**에야 파일을 stat해
        #   etag/last-modified를 만든다(`FileResponse.__call__`). 그러면 아래 조건부 검사가
        #   검증자를 아직 못 봐서 **항상 200이 나간다**(2026-08-17 실측으로 확인).
        #   여기서 넘겨 주면 생성 시점에 헤더가 채워지고, 파일을 두 번 stat하지도 않는다.
        stat_result=os.stat(real_path),
    )
    # 검색 목록이 이 엔드포인트를 카드마다 부른다(썸네일). 조건부 요청을 해석하지 않으면
    # 같은 사진을 페이지를 넘길 때마다 통째로 다시 받는다 — 실측 1페이지 약 2MB
    # (2026-08-17 Sprint 146). 바이트만 아끼고 신선도 판단은 바꾸지 않는다.
    return not_modified(request, response) or response


# 프런트가 갤러리를 열기 전에 존재만 확인할 수 있게 한다 — 문서 뷰어(`documents.py`)와
# 같은 이유·같은 형태다. 스키마에서 빼는 것도 같다(GET과 operationId가 겹치면
# `/openapi.json` 생성이 깨진다).
@router.head("/item/{item_id}/images/{seq}", include_in_schema=False)
def head_item_image(item_id: int, seq: int, request: Request):
    return get_item_image(item_id, seq, request)
