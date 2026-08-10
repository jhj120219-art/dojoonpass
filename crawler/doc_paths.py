"""
문서 저장 경로 규칙 (순수 로직, 외부 의존성 없음).

원래 이 정의들은 `crawler/doc_crawler.py`에 있었다. 그런데 그 모듈은 최상단에서
selenium을 import하기 때문에, **경로 계산 함수만 쓰고 싶은 쪽**(회귀 테스트,
문서 서빙 등)까지 selenium 설치를 강요받았다. 실제로 selenium이 없는 환경에서
`test_doc_storage_atomicity.py`가 ModuleNotFoundError로 아예 실행되지 못했다
(2026-08-10 Sprint 47 발견).

여기에는 파일시스템 경로 규칙만 둔다 — selenium/네트워크/DB 의존성을 넣지 않는다.
`doc_crawler.py`는 하위 호환을 위해 이 이름들을 그대로 재노출(re-export)하므로
기존 `from crawler.doc_crawler import get_doc_dir, ...` 호출부는 변경 없이 동작한다.
"""
import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOWNLOAD_DIR = os.path.join(PROJECT_ROOT, "downloads")
DOCUMENT_ROOT = os.path.join(PROJECT_ROOT, "documents")


# court_code 인자명 주의 (2026-08-10 Sprint 48 실측 확인)
# ----------------------------------------------------
# 이름은 "code"지만 **실제로 들어오는 값은 한글 법원명**이다("강릉지원", "서울중앙지방법원").
# config/courts.py의 ALL_COURTS는 `code`와 `name`이 같은 값이고, DB의
# document_queue.court_code / auction_case.court_code / auction_item.court_name도 전부
# 같은 한글 법원명을 담는다. 따라서 이 함수가 만드는 경로(documents/<법원명>/...)와
# api/v1/documents.py가 court_name으로 만드는 경로는 **동일하다** — 서로 다른 인자명을 쓰지만
# 문서 서빙에 불일치는 없다.
#
# 인자명을 court_name으로 바꾸지 않은 이유: DB 컬럼명이 `court_code`라서 여기만 바꾸면
# 호출부(item["court_code"])와 어긋나 혼란이 옮겨갈 뿐이다. 컬럼명 변경은 스키마 변경이라
# 승인이 필요하다.
def get_doc_dir(court_code: str, case_no: str, item_no: str = "1") -> str:
    safe_case_no = case_no.replace("/", "_").strip()
    safe_item_no = (item_no or "1").replace("/", "_").strip()
    path = os.path.join(DOCUMENT_ROOT, court_code, safe_case_no, safe_item_no)
    os.makedirs(path, exist_ok=True)
    return path


# 문서 종류별 "완성 여부 판단 기준 파일" 확장자.
# status는 json+html 세트가 완성되어야 성공이므로 json을 기준 파일로 삼는다
# (html만 있고 json이 없는 "partial" 상태는 기존 결과 재사용 대상에서 제외하기 위함).
_PRIMARY_EXT = {"spec": "pdf", "status": "json", "appraisal": "pdf"}


def doc_exists(court_code: str, case_no: str, item_no: str, doc_type: str) -> bool:
    ext = _PRIMARY_EXT.get(doc_type, "pdf")
    path = os.path.join(get_doc_dir(court_code, case_no, item_no), doc_type + "." + ext)
    return os.path.exists(path) and os.path.getsize(path) > 0
