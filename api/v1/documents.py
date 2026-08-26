import os
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from storage.database import get_connection
from api.constants import is_sqlite_int
from api.http_cache import not_modified

router = APIRouter()

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DOCUMENT_ROOT = os.path.join(PROJECT_ROOT, "documents")

# doc_type -> (파일명, media_type). STATUS는 PDF가 아니라 HTML이라 별도 처리.
DOC_TYPE_FILES = {
    "APPRAISAL": ("appraisal.pdf", "application/pdf"),
    "SPEC": ("spec.pdf", "application/pdf"),
    "STATUS": ("status.html", "text/html"),
}


# crawler/doc_paths.py:get_doc_dir()는 같은 경로를 만들면서 인자명을 court_code로 쓴다.
# 이름만 다를 뿐 **값은 동일한 한글 법원명**이라 두 경로는 일치한다(2026-08-10 Sprint 48
# DB 실측 확인 — ALL_COURTS의 code == name, 관련 컬럼 전부 한글 법원명).
# 크롤러가 쓴 문서를 API가 못 찾는 문제는 없다.
#
# ★ 2026-08-17 Sprint 146: 조각 정규화를 **크롤러와 같은 함수**로 맞췄다.
#   Sprint 145에 `sanitize_path_segment()`가 신설되면서 쓰는 쪽(`_doc_dir_path`)은
#   역슬래시까지 치환하게 됐는데, **읽는 쪽인 여기만 옛 규칙(`/`만 치환)으로 남아 있었다.**
#   사건번호에 역슬래시가 섞이면 크롤러는 `a_b`에 쓰고 API는 `a\b`를 찾아 **같은 문서를
#   두 경로로 보게 된다**(이 저장소가 BUGS #50/#64로 반복해 겪은 바로 그 어긋남).
#   현재 실데이터에 역슬래시는 0건이라 지금 터지는 버그는 아니지만, 규칙이 두 벌인 상태
#   자체를 없앤다. `crawler.doc_paths`는 selenium/DB/fastapi 무의존이라 여기서 import해도
#   안전하다(`api/v1/images.py`가 `crawler.image_assets`를 쓰는 것과 같은 방식).
from crawler.doc_paths import sanitize_path_segment  # noqa: E402


def get_doc_dir(court_name: str, case_no: str, item_no: str) -> str:
    return os.path.join(DOCUMENT_ROOT, court_name,
                        sanitize_path_segment(case_no),
                        sanitize_path_segment(item_no or "1"))


@router.get("/item/{item_id}/documents/{doc_type}")
def get_document(item_id: int, doc_type: str, request: Request):
    # 대소문자를 가리지 않는다. 이 저장소는 **같은 개념을 두 벌 어휘로** 저장한다 —
    # `document_status.doc_type`은 대문자(SPEC/STATUS/APPRAISAL), `document_queue.doc_type`은
    # 소문자(spec/status/appraisal)다. 화면은 `document_status`에서 값을 받아 오므로 지금
    # 깨지지 않지만, 큐 쪽 값으로 URL을 만드는 코드(복구 스크립트·운영 도구·향후 기능)는
    # 400을 받는다. 게다가 그 400 메시지가 오타로 넣은 값과 **구별되지 않아** 원인을 찾기
    # 어렵다(2026-08-17 Sprint 148 Performance 감사 중 실측 발견).
    #
    # 받아들이는 입력만 넓히는 변경이라 기존 대문자 호출의 동작은 그대로다.
    # 값은 `DOC_TYPE_FILES`의 키로만 쓰이므로(파일명은 상수에서 온다) 경로 조작 위험은 없다.
    doc_type = (doc_type or "").upper()
    if doc_type not in DOC_TYPE_FILES:
        raise HTTPException(status_code=400, detail="지원하지 않는 문서 종류입니다")

    # SQLite INTEGER 범위 밖의 id는 어떤 행도 될 수 없다 — 그대로 넘기면 sqlite3이
    # OverflowError를 던져 **인증 없이 500을 만들 수 있다**(2026-08-17 Sprint 144 실측).
    if not is_sqlite_int(item_id):
        raise HTTPException(status_code=404, detail="물건을 찾을 수 없습니다")

    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT court_name, case_no, item_no FROM auction_item WHERE id = ?",
            (item_id,)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="물건을 찾을 수 없습니다")
    finally:
        conn.close()

    # court_name/case_no는 nullable 컬럼이라 NULL이면 아래 os.path.join이 TypeError로
    # 터져 500이 된다 — 문서 경로를 만들 수 없는 상태이므로 404로 정직하게 응답한다.
    if not row["court_name"] or not row["case_no"]:
        raise HTTPException(status_code=404, detail="문서를 찾을 수 없습니다")

    filename, media_type = DOC_TYPE_FILES[doc_type]
    doc_dir = get_doc_dir(row["court_name"], row["case_no"], row["item_no"])
    file_path = os.path.join(doc_dir, filename)

    # 경로 탐색 방지: 계산된 경로가 DOCUMENT_ROOT 밖으로 벗어나면 차단
    real_document_root = os.path.realpath(DOCUMENT_ROOT)
    real_file_path = os.path.realpath(file_path)
    # ★ 2026-08-26 (`docs/BUGS.md` #229): 드라이브가 다르면 `commonpath` 가 ValueError 를
    #   낸다(Windows). `court_name` 이 "D:" 같은 값이면 `os.path.join` 이 베이스를 갈아치워
    #   실제로 그 상황이 된다(`get_doc_dir("D:", ...)` -> "D:2024타경1\\1" 실측).
    #   막아야 할 입력에서 가드가 죽으면 404 가 아니라 500 이 나간다.
    try:
        outside = os.path.commonpath([real_document_root, real_file_path]) != real_document_root
    except ValueError:
        outside = True
    if outside:
        raise HTTPException(status_code=404, detail="문서를 찾을 수 없습니다")

    # ★ "있다"의 기준을 **크롤러와 같게** 맞춘다 (2026-08-13 Sprint 98).
    #
    #   예전에는 `os.path.exists()`만 봤다. 그래서 **0바이트 파일이 200으로 나갔다.**
    #   프런트는 뷰어를 열기 전에 HEAD로 존재만 확인하고(`properties/[id]/page.tsx:215`
    #   — `res.ok`만 본다) 200이면 iframe을 띄우므로, 사용자는 **아무 설명 없는 빈 화면**을
    #   본다. "문서가 없다"는 안내조차 못 받는다.
    #
    #   쓰는 쪽은 이미 크기를 본다 — `crawler/doc_paths.doc_exists()`는
    #   `exists() and getsize() > 0`이라야 "수집됨"으로 친다. 읽는 쪽만 기준이 느슨해서
    #   **크롤러는 "아직 없음"이라 재수집 대상으로 보는 파일을 API는 "있음"이라고 답하는**
    #   비대칭이 있었다. 두 정의를 하나로 맞춘다.
    #
    #   `test_document_status_sync.py`는 이미 이 상태를 "뷰어가 200을 주지만 사용자에게는
    #   빈 문서"라고 적어 두고 **데이터에만** 그 조건을 강제하고 있었다(현재 실 DB 0건).
    #   엔드포인트 자체에도 같은 기준을 둬서, 0바이트 파일이 생기더라도 거짓 성공이 되지 않게 한다.
    #   Sprint 95가 admin의 쓰기 검사를 download의 읽기 검사와 맞춘 것과 같은 정렬이다.
    if not os.path.isfile(real_file_path) or os.path.getsize(real_file_path) == 0:
        raise HTTPException(status_code=404, detail="문서를 찾을 수 없습니다")

    response = FileResponse(
        real_file_path,
        media_type=media_type,
        filename=filename,
        content_disposition_type="inline",
        # stat_result를 넘겨야 생성 시점에 etag/last-modified가 채워진다 —
        # 넘기지 않으면 Starlette가 전송 시점에 stat하므로 아래 조건부 검사가
        # 검증자를 보지 못해 항상 200이 된다(images.py의 같은 주석 참고).
        stat_result=os.stat(real_file_path),
    )
    # 브라우저가 되보낸 검증자가 현재 파일의 것과 같으면 본문을 다시 보내지 않는다
    # (2026-08-17 Sprint 146). `FileResponse`는 etag/last-modified를 붙여 주지만
    # 조건부 요청을 해석하지는 않아, 실측상 2.5MB 감정평가서가 매번 전부 재전송됐다.
    # 신선도 판단은 바꾸지 않는다 — 클라이언트는 여전히 매번 서버에 물어본다.
    return not_modified(request, response) or response


# HEAD는 프론트(`properties/[id]/page.tsx`)가 문서 뷰어를 열기 전에 "파일이 실제로 있는지"만
# 확인하는 용도다. 예전에는 `api_route(methods=["GET","HEAD"])` 하나로 처리했는데, FastAPI가
# 두 메서드에 **같은 operationId**를 만들어 `/openapi.json`을 그릴 때마다
# `UserWarning: Duplicate Operation ID ...`가 나고 OpenAPI 클라이언트 생성도 깨졌다.
# GET/HEAD를 별도 라우트로 나누고 HEAD는 스키마에서 제외해 중복을 없앤다 —
# 동작은 동일하다(Starlette가 HEAD 응답의 본문을 자동으로 버린다).
@router.head("/item/{item_id}/documents/{doc_type}", include_in_schema=False)
def head_document(item_id: int, doc_type: str, request: Request):
    return get_document(item_id, doc_type, request)
