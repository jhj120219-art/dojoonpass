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


def get_doc_dir(court_name: str, case_no: str, item_no: str) -> str:
    safe_case_no = case_no.replace("/", "_").strip()
    safe_item_no = (item_no or "1").replace("/", "_").strip()
    return os.path.join(DOCUMENT_ROOT, court_name, safe_case_no, safe_item_no)


@router.api_route("/item/{item_id}/documents/{doc_type}", methods=["GET", "HEAD"])
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

    filename, media_type = DOC_TYPE_FILES[doc_type]
    doc_dir = get_doc_dir(row["court_name"], row["case_no"], row["item_no"])
    file_path = os.path.join(doc_dir, filename)

    # 경로 탐색 방지: 계산된 경로가 DOCUMENT_ROOT 밖으로 벗어나면 차단
    real_document_root = os.path.realpath(DOCUMENT_ROOT)
    real_file_path = os.path.realpath(file_path)
    if os.path.commonpath([real_document_root, real_file_path]) != real_document_root:
        raise HTTPException(status_code=404, detail="문서를 찾을 수 없습니다")

    if not os.path.exists(real_file_path):
        raise HTTPException(status_code=404, detail="문서를 찾을 수 없습니다")

    return FileResponse(
        real_file_path,
        media_type=media_type,
        filename=filename,
        content_disposition_type="inline",
    )
