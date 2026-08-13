import os
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from storage.database import get_connection

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
def get_doc_dir(court_name: str, case_no: str, item_no: str) -> str:
    safe_case_no = case_no.replace("/", "_").strip()
    safe_item_no = (item_no or "1").replace("/", "_").strip()
    return os.path.join(DOCUMENT_ROOT, court_name, safe_case_no, safe_item_no)


@router.get("/item/{item_id}/documents/{doc_type}")
def get_document(item_id: int, doc_type: str):
    if doc_type not in DOC_TYPE_FILES:
        raise HTTPException(status_code=400, detail="지원하지 않는 문서 종류입니다")

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
    if os.path.commonpath([real_document_root, real_file_path]) != real_document_root:
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

    return FileResponse(
        real_file_path,
        media_type=media_type,
        filename=filename,
        content_disposition_type="inline",
    )


# HEAD는 프론트(`properties/[id]/page.tsx`)가 문서 뷰어를 열기 전에 "파일이 실제로 있는지"만
# 확인하는 용도다. 예전에는 `api_route(methods=["GET","HEAD"])` 하나로 처리했는데, FastAPI가
# 두 메서드에 **같은 operationId**를 만들어 `/openapi.json`을 그릴 때마다
# `UserWarning: Duplicate Operation ID ...`가 나고 OpenAPI 클라이언트 생성도 깨졌다.
# GET/HEAD를 별도 라우트로 나누고 HEAD는 스키마에서 제외해 중복을 없앤다 —
# 동작은 동일하다(Starlette가 HEAD 응답의 본문을 자동으로 버린다).
@router.head("/item/{item_id}/documents/{doc_type}", include_in_schema=False)
def head_document(item_id: int, doc_type: str):
    return get_document(item_id, doc_type)
