import logging
import os
import sqlite3
from fastapi import APIRouter, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError
from storage.database import get_connection
from api.auth import decode_supabase_jwt
from api.constants import is_sqlite_int
from api.v1.recent_items import record_view
from api.v1.thumbnails import image_url as _image_url

logger = logging.getLogger(__name__)

router = APIRouter()
bearer_scheme = HTTPBearer(auto_error=False)

@router.get("/item/{item_id}")
def get_item(item_id: int, credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme)):
    # SQLite INTEGER 범위를 벗어난 id는 어떤 행도 될 수 없다. 그대로 넘기면
    # sqlite3이 OverflowError를 던져 **인증 없이 500을 만들 수 있다**
    # (2026-08-17 Sprint 144 실측). 음수 id가 이미 404인 것과 같은 취급을 한다.
    if not is_sqlite_int(item_id):
        raise HTTPException(status_code=404, detail="물건을 찾을 수 없습니다")

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

        # 2026-08-17 Sprint 144 — 자산(문서 실체 + 물건 사진)을 **같은 커넥션에서 한 번씩만**
        # 읽는다. 물건당 쿼리 2개가 늘 뿐이며 물건 수·사진 수에 비례해 늘지 않는다(N+1 없음).
        doc_raw = conn.execute(
            """
            SELECT doc_type, page_count, file_size, doc_version
            FROM doc_raw
            WHERE item_id = ?
              AND doc_version = (SELECT MAX(d2.doc_version) FROM doc_raw d2
                                  WHERE d2.item_id = doc_raw.item_id
                                    AND d2.doc_type = doc_raw.doc_type)
            """,
            (item_id,)
        ).fetchall()
        doc_raw_by_type = {r["doc_type"]: r for r in doc_raw}

        # 2026-08-21 Sprint 239, BUGS #177: migration 020 미적용 환경에서
        # `auction_image`가 없어도 상세페이지 전체를 500으로 잃지 않는다 — 사진 없는
        # 물건과 같은 모양(빈 목록)으로 취급한다. 근본 원인은 스키마 드리프트 가드
        # (`test_bootstrap.py`/`test_schema_hygiene.py`)가 별도로 잡는다.
        try:
            images = conn.execute(
                """
                SELECT seq, kind, file_size, width, height
                FROM auction_image WHERE item_id = ? ORDER BY seq
                """,
                (item_id,)
            ).fetchall()
        except sqlite3.OperationalError as e:
            if "no such table: auction_image" not in str(e):
                raise
            logger.warning("auction_image 테이블이 없다(migration 020 미적용) - 사진 없이 응답한다: %s", e)
            images = []

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
                # ES256(JWKS) / HS256(레거시)을 함께 다루는 공용 검증기 — api/auth.py 참고.
                # 예전에는 여기서 HS256만 검증해, Supabase가 ES256으로 전환된 뒤 로그인
                # 사용자도 항상 비로그인으로 처리됐다(docs/BUGS.md #27).
                payload = decode_supabase_jwt(credentials.credentials)
                user_id = payload.get("sub")
            except JWTError:
                logger.debug("item 상세: 토큰 검증 실패 ― 비로그인으로 처리")
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
            # ★ 기존 계약 유지: `doc_type`/`status`는 그대로 있고 **키만 늘었다**.
            #    프런트의 기존 코드(`property.documents.some(d => d.doc_type==='SPEC' ...)`)는
            #    무변경으로 계속 동작한다.
            "documents": [_document_entry(item_id, d, doc_raw_by_type, row) for d in doc_status],
            "images": [_image_entry(item_id, im) for im in images],
            "image_count": len(images),
            # 대표 이미지 = 순번이 가장 앞선 사진. 법원 캐러셀의 첫 장이 곧 대표 전경도다
            # (실측: 전경도_1이 항상 seq=1). 별도의 "대표" 플래그를 만들지 않는 이유는
            # 원천에 그런 개념이 없어서 우리가 임의로 정하면 근거 없는 값이 되기 때문이다.
            "representative_image": (_image_entry(item_id, images[0]) if images else None),
            "images_status": _images_status(doc_status, len(images)),
            "tenants": [dict(t) for t in tenants],
            "rights_summary": dict(rights) if rights else None,
            "is_favorited": is_favorited,
        }
    finally:
        conn.close()


# `documents.py` / `images.py`가 실제로 서빙하는 경로와 **문자열이 같아야** 한다.
# 여기서 규칙을 새로 만들면 "API는 URL을 주는데 그 URL이 404"가 된다 — 이 저장소가
# 파일 경로에서 반복해 겪은 어긋남을 URL에서 되풀이하지 않도록 한 곳에 모아 둔다.
def _document_url(item_id: int, doc_type: str) -> str:
    return "/api/v1/item/%d/documents/%s" % (item_id, doc_type)


def _served_file_size(item_row, doc_type: str):
    """`download_url` 이 **실제로 내려주는 파일**의 크기. 못 구하면 None.

    ## 왜 doc_raw 의 크기를 그대로 쓰면 안 되나 (2026-08-21 Sprint 241)

    `doc_raw` 는 **구조화 산출물**을 실체로 기록한다. STATUS(현황조사서)의 경우
    `doc_raw.storage_path` 가 `status.json` 이다(변경 감지 지문을 그 파일에서 뜬다).
    그런데 `/api/v1/item/{id}/documents/STATUS` 가 내려주는 것은 `status.html` 이다
    (`api/v1/documents.py: DOC_TYPE_FILES`).

    즉 예전에는 **`file_size` 가 `download_url` 과 다른 파일을 설명하고 있었다.**
    2026-08-21 실측(READY 문서 45건 전수):

        SPEC/APPRAISAL   doc_raw 파일 == 서빙 파일  -> 크기 일치 (33건)
        STATUS           doc_raw=status.json vs 서빙=status.html
                         12건 **전부 불일치** (예: 광고 12,827B / 실제 45,747B, 약 3.6배)

    지금은 화면이 이 값을 그리지 않아 사용자에게 보이지는 않는다. 그러나 필드 이름과
    바로 옆의 `download_url` 이 "이 주소로 받으면 이만큼"이라고 말하고 있으므로,
    값이 다른 파일의 것이면 그것은 **API 가 거짓말을 하는 상태**다. 쓰는 쪽이 생기는
    순간(용량 표시, 진행률, 사전 할당) 조용히 틀린다.

    ## 어떻게 고치나

    크기를 **서빙 경로에서 직접 잰다.** 파일명 매핑과 디렉터리 규칙은
    `api/v1/documents.py` 의 것을 그대로 가져다 쓴다 — 같은 어휘를 두 벌로 만들지
    않는다(이 저장소가 BUGS #50/#64 로 반복해 겪은 어긋남의 원인이 그것이었다).

    비용은 READY 문서당 `os.stat` 1회다(물건당 최대 3회). 같은 엔드포인트가 이미
    SQL 쿼리 6개를 돌리므로 상대적으로 무시할 수 있고, 사진 서빙(`images.py`)도
    같은 방식으로 stat 한다.

    실패하면(파일 없음/권한) None 을 돌려준다 — "모른다"는 정직한 값이고,
    `page_count` 가 이미 같은 규약을 쓴다. 여기서 예외를 올려 상세 응답 전체를
    500으로 만들지 않는다.
    """
    try:
        from api.v1.documents import DOC_TYPE_FILES, get_doc_dir
        entry = DOC_TYPE_FILES.get((doc_type or "").upper())
        if not entry:
            return None
        filename = entry[0]
        court_name, case_no = item_row["court_name"], item_row["case_no"]
        if not court_name or not case_no:
            return None
        path = os.path.join(get_doc_dir(court_name, case_no, item_row["item_no"]), filename)
        size = os.path.getsize(path)
        return size if size > 0 else None
    except (OSError, ValueError, TypeError):
        # 파일 없음 / 권한 / 경로 오류만 흡수한다. **bare Exception 을 쓰지 않는다** —
        # 그러면 이 함수 안의 NameError(예: import 누락) 같은 코딩 실수까지 삼켜
        # 모든 file_size 가 조용히 None 이 된다. 이 저장소가 "거짓 성공"이라 부르는 모양이다.
        return None


def _document_entry(item_id: int, row, doc_raw_by_type, item_row=None) -> dict:
    """문서 1건의 화면용 정보.

    `page_count`가 None인 것과 0인 것은 다르다 — None은 "아직 모른다"(수집 전이거나
    PDF가 아니거나 파싱 실패), 0은 있을 수 없는 값이다. 그래서 0으로 뭉개지 않는다.
    프런트는 None이면 페이지 이동 UI를 아예 그리지 않는다.

    ## ★ READY 인데 서빙 파일이 없으면 COLLECTING 으로 낮춘다 (2026-08-25, BUGS #198)

    사진 쪽에는 이 2차 방어선이 **이미 있었다**(`_images_status`: READY 인데 볼 사진이
    0장이면 COLLECTING). 문서 쪽에만 없었다. 그래서 `document_status` 가 READY 이기만
    하면 파일이 실제로 없어도 그대로 "열람 가능"이라고 답했다. 실측(2026-08-25,
    사본 DB + TestClient, 합성 물건 하나로 재현):

        SPEC   status=READY  available=True  file_size=None
               viewer_url=/api/v1/item/16721/documents/SPEC
        그 URL 을 실제로 요청 -> **HTTP 404**

    사진 쪽 주석이 적어 둔 이유가 그대로 적용된다 — *"오류도 빈 화면도 아니라 사용자가
    원인을 알 수 없다."* 프런트도 같은 문제를 한 번 겪었다(`properties/[id]/page.tsx`:
    *"수집중인 문서도 파란 밑줄 링크였고, 누르면 '문서를 찾을 수 없다'"*).

    **판단 근거는 이미 이 함수가 갖고 있었다.** `served_size` 가 그것이다 — 서빙 경로에서
    직접 잰 크기이고, 파일이 없거나 0바이트면 None 이다. 그 값을 `file_size` 로만 쓰고
    판정에는 쓰지 않고 있었다("함수를 불렀다"와 "성공했다"는 다르다 — Sprint 214 가
    doc_worker 에서 고친 것과 같은 모양이다).

    적용 범위를 좁게 잡는다 —

      - `IMAGE` 는 대상이 아니다. 서빙 파일이 하나로 정해지지 않고(0~N장),
        판정은 `_images_status()` 가 이미 한다.
      - `item_row` 가 없으면 잴 수 없으므로 낮추지 않는다("모른다"를 "고장났다"로
        읽지 않는다 — BUGS #188 이 세운 구분).
      - READY 가 아닌 상태는 건드리지 않는다. NO_IMAGE/FAILED/COLLECTING 은
        이미 "볼 것이 없다"와 모순되지 않는다.
    """
    doc_type = row["doc_type"]
    status = row["status"]
    raw = doc_raw_by_type.get(doc_type)

    # 서빙 대상이 아닌 종류(IMAGE)는 이 방어의 대상이 아니다. 목록은 서빙 계층의
    # 것을 그대로 쓴다 — 같은 어휘를 두 벌로 만들지 않는다(`_served_file_size` 와 같은 이유).
    try:
        from api.v1.documents import DOC_TYPE_FILES
        servable = (doc_type or "").upper() in DOC_TYPE_FILES
    except Exception:       # noqa: BLE001 - 판정을 못 하면 낮추지 않는다(안전한 쪽)
        servable = False

    # ★ `file_size` 는 **`download_url` 이 주는 파일**의 크기여야 한다.
    #   READY 가 아니면 URL 자체를 주지 않으므로 크기도 재지 않는다(잴 대상이 없다).
    #   서빙 파일을 못 재면 doc_raw 값으로 떨어지지 않는다 — 그것이 바로 다른 파일을
    #   설명하던 예전 동작이다. 모르면 None 이라고 말한다.
    measured = status == "READY" and item_row is not None and servable
    served_size = _served_file_size(item_row, doc_type) if measured else None

    # 잰 결과 실체가 없으면(파일 없음/0바이트) READY 를 유지하지 않는다.
    effective_status = "COLLECTING" if (measured and served_size is None) else status
    ready = effective_status == "READY"

    return {
        "doc_type": doc_type,
        "status": effective_status,
        # 화면이 "열람 가능"으로 다룰 수 있는가. 상태 문자열 비교를 프런트마다 따로
        # 하지 않도록 서버가 한 번만 판단한다.
        "available": ready,
        "page_count": raw["page_count"] if raw else None,
        "file_size": served_size,
        "doc_version": raw["doc_version"] if raw else None,
        # READY가 아니면 URL을 주지 않는다. 열 수 없는 주소를 건네고 프런트가 404를
        # 받아 보게 하는 것보다, 없다는 사실을 응답에 담는 편이 정직하다.
        "viewer_url": _document_url(item_id, doc_type) if ready else None,
        "download_url": _document_url(item_id, doc_type) if ready else None,
    }


def _image_entry(item_id: int, row) -> dict:
    return {
        "seq": row["seq"],
        "kind": row["kind"],
        "url": _image_url(item_id, row["seq"]),
        # 서버 측 썸네일 생성은 아직 없다(Pillow 도입은 승인 사항 —
        # docs/SPRINT144_ASSET_PIPELINE.md의 SKIP 항목). 원본을 그대로 가리키되
        # **필드는 지금 만들어 둔다** — 나중에 썸네일이 생겨도 프런트 계약이 바뀌지 않는다.
        "thumbnail_url": _image_url(item_id, row["seq"]),
        "width": row["width"],
        "height": row["height"],
        "file_size": row["file_size"],
    }


def _images_status(doc_status_rows, image_count: int) -> str:
    """물건 사진의 수집 상태.

    근거가 둘이라 우선순위를 정해 둔다 —
      1. `auction_image` 행이 있으면 무조건 READY다(볼 수 있는 사진이 실제로 있다).
      2. 사진이 없으면 `document_status`의 IMAGE 행을 따른다.
         - NO_IMAGE : 수집했지만 법원에 사진이 없다(재시도해도 같다, 실패가 아니다)
         - FAILED   : 재시도가 소진된 진짜 실패
         - COLLECTING / 행 없음 : 아직 수집 전
    행이 없을 때 COLLECTING으로 답하는 이유: 사진 수집은 `document_queue`에 적재되지만
    `document_status`의 IMAGE 행은 worker가 처음 결과를 낼 때 비로소 생긴다. 그 사이의
    물건에게 "사진 없음"이라고 답하면 아직 안 해 본 것을 없다고 단정하는 것이 된다.
    """
    if image_count > 0:
        return "READY"
    row = next((d for d in doc_status_rows if d["doc_type"] == "IMAGE"), None)
    if row is None:
        return "COLLECTING"

    # ★ READY 인데 볼 사진이 0장인 것은 **자기모순**이다 (2026-08-18 Sprint 208).
    #
    #   그대로 전달하면 화면은 "사진 있음"이라고 말하고 목록은 빈 상태가 된다 —
    #   오류도 빈 화면도 아니라 사용자가 원인을 알 수 없다.
    #
    #   이 상태가 생기는 실제 경로를 확인했다(같은 스프린트):
    #     - `doc_worker` 가 성공을 먼저 기록하고 사진 기록에서 실패하는 경우
    #       (그 순서는 이번에 바로잡았지만, 여기는 **두 번째 방어선**이다)
    #     - `save_auction_images()` 가 디스크에 없는 항목을 전부 건너뛰어 saved=0 이 되는 경우
    #
    #   NO_IMAGE / FAILED 는 그대로 전달한다 — 그 둘은 "볼 사진이 없다"와 모순되지 않는다.
    #   READY 만 COLLECTING 으로 낮춘다. 근거: 실체가 없으므로 아직 끝나지 않은 것이고,
    #   큐가 재시도 경로를 갖고 있다(행이 없을 때 COLLECTING 이라고 답하는 것과 같은 이유).
    if row["status"] == "READY":
        return "COLLECTING"
    return row["status"]
