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
def _doc_dir_path(court_code: str, case_no: str, item_no: str = "1") -> str:
    """경로만 계산한다. **디스크를 건드리지 않는다.**

    2026-08-14 분리. 경로 규칙은 여기 한 곳에만 두고, `get_doc_dir()`은 여기에
    디렉터리 생성을 얹는다 — 규칙이 두 벌이 되면 "쓰는 곳과 읽는 곳이 다른 경로를
    보는" 이 저장소의 단골 결함이 된다.
    """
    safe_case_no = case_no.replace("/", "_").strip()
    safe_item_no = (item_no or "1").replace("/", "_").strip()
    return os.path.join(DOCUMENT_ROOT, court_code, safe_case_no, safe_item_no)


def get_doc_dir(court_code: str, case_no: str, item_no: str = "1") -> str:
    """문서 디렉터리 경로. **없으면 만든다.**

    쓰기 직전에 부르는 용도다(`doc_crawler`의 spec/status/appraisal 저장 4곳,
    `collect_documents`의 최종 경로). 조회만 할 때는 `_doc_dir_path()`를 쓴다 —
    아래 `doc_exists()`가 그렇게 한다.
    """
    path = _doc_dir_path(court_code, case_no, item_no)
    os.makedirs(path, exist_ok=True)
    return path


# 문서 종류별 "완성 여부 판단 기준 파일" 확장자.
# status는 json+html 세트가 완성되어야 성공이므로 json을 기준 파일로 삼는다
# (html만 있고 json이 없는 "partial" 상태는 기존 결과 재사용 대상에서 제외하기 위함).
_PRIMARY_EXT = {"spec": "pdf", "status": "json", "appraisal": "pdf"}


def doc_exists(court_code: str, case_no: str, item_no: str, doc_type: str) -> bool:
    """이 문서가 "수집 완료"로 인정할 수 있는 상태인지.

    `doc_type`은 대소문자를 가리지 않는다. 이 저장소는 문서 종류를 **대문자**로 다루는 쪽이
    훨씬 많은데(`document_status.doc_type`, `api/v1/documents.py:DOC_TYPE_FILES`,
    아래 `CANONICAL_DOC_FILENAME`) 이 함수만 소문자 키를 쓰고 있었다.

    ★ 예전 구현은 `_PRIMARY_EXT.get(doc_type, "pdf")`였다. 대문자를 넘기면 사전에 없으니
    **조용히 "pdf"로 떨어져 틀린 답**을 냈다. 그리고 그 틀림이 종류마다 달랐다:

        doc_exists(..., "SPEC")       -> "SPEC.pdf"  Windows는 대소문자를 구분하지 않아
                                        spec.pdf에 우연히 맞는다 (정답)
        doc_exists(..., "APPRAISAL")  -> 위와 같은 이유로 우연히 정답
        doc_exists(..., "STATUS")     -> "STATUS.pdf" — status의 기준 파일은 **json**인데
                                        기본값 pdf로 떨어져 **항상 False** (오답)

    2/3이 우연히 맞는 것이 가장 나쁘다 — 잘못된 호출이 대부분의 경우 정상으로 보이다가
    STATUS에서만 조용히 틀린다. 그 오답의 방향도 나쁘다: "완료됐는데 미완료로 보임"이라
    이미 수집된 문서를 영구히 재수집 대상으로 남긴다(이 파일이 BUGS #22/#50/#65에서
    반복해 경고해 온 바로 그 함정의 반대 방향).

    또한 예전 구현은 파일명을 **호출자가 준 대소문자 그대로** 만들었다. 대소문자를 구분하는
    파일시스템에서는 SPEC/APPRAISAL조차 False가 된다. 이제 항상 소문자 파일명을 쓴다.

    모르는 `doc_type`은 조용히 pdf로 넘기지 않고 예외를 던진다 — 바로 아래
    `canonical_doc_path()`가 이미 취하고 있는 태도와 같다(알 수 없는 종류에 그럴듯한
    답을 지어내지 않는다).
    """
    key = (doc_type or "").lower()
    if key not in _PRIMARY_EXT:
        raise ValueError(
            "알 수 없는 doc_type: %r (가능한 값: %s)"
            % (doc_type, ", ".join(sorted(_PRIMARY_EXT)))
        )
    # ★ `get_doc_dir()` 이 아니라 `_doc_dir_path()` 를 쓴다 (2026-08-14).
    #
    #   이 함수는 **조회**다. 그런데 예전에는 `get_doc_dir()` 을 불렀고, 그 함수는
    #   `os.makedirs()` 를 한다. 즉 **"이 문서 있어요?" 라고 묻기만 해도 디스크에
    #   빈 디렉터리가 생겼다.** 실측 재현: 없는 물건 하나를 조회하면 3단계 디렉터리
    #   (법원/사건/물건번호)가 생기고, 물어볼 때마다 쌓인다.
    #
    #   그 쓰레기가 실제로 남아 있다 — `documents/` 아래 **대응 물건이 없는 빈 디렉터리
    #   5개**가 그렇게 만들어진 것들이다(`A/B/1` 처럼 테스트가 물어본 흔적도 있다).
    #   조회는 조회만 해야 한다. 만드는 것은 쓰기 직전에 `get_doc_dir()` 이 한다.
    path = os.path.join(_doc_dir_path(court_code, case_no, item_no),
                        key + "." + _PRIMARY_EXT[key])
    return os.path.exists(path) and os.path.getsize(path) > 0


# 현황조사서 오버레이가 "실제 데이터가 채워진 상태"인지 판정한다 (2026-08-12 Sprint 62).
# --------------------------------------------------------------------------------
# 왜 필요한가 — `doc_crawler.collect_status()`는 오버레이의 텍스트가 **비어 있지만 않으면**
# 데이터가 채워진 것으로 보고 저장했다. 그런데 오버레이 골격에는 "사건번호", "조사일시",
# "검색결과가 없습니다" 같은 **고정 라벨**이 처음부터 들어 있어서, 비동기 데이터가 도착하기
# 전에도 그 조건이 즉시 참이 된다. 그 결과 내용이 하나도 없는 페이지가 정상 수집으로
# 저장됐다(2026-08-12 실측: status.html 194건 중 33건).
#
# 더 나쁜 것은 그 다음이다 — `doc_exists()`는 "파일이 있고 0바이트 초과"만 보므로 이 빈
# 파일들은 **영구히 재수집 대상에서 제외**된다(BUGS #22/#50과 같은 부류의 함정).
#
# 판정 기준으로 사건번호(YYYY타경NNNNN)를 쓴다. 이 표기는 현황조사서 본문에 반드시
# 채워지는 값이고, 실측에서 정상 161건은 161건 모두 매칭 / 빈 캡처 33건은 0건 매칭으로
# **완전히 분리**됐다(원본 HTML 문자열 기준).
import re as _re

_CASE_NO_PATTERN = _re.compile(r"\d{4}\s*타경\s*\d+")


def status_overlay_has_data(text: str) -> bool:
    """현황조사서 오버레이 텍스트/HTML에 실제 사건 데이터가 들어 있으면 True.

    라벨만 있는 빈 골격은 False가 되어야 한다 — 이 함수가 False면 저장하지 않고
    실패로 처리해 **큐에 남겨 재시도**하는 것이 올바른 동작이다.
    """
    if not text:
        return False
    return bool(_CASE_NO_PATTERN.search(text))


# 뷰어가 실제로 서빙하는 파일 경로 (2026-08-12 Sprint 66).
# --------------------------------------------------------------------------------
# `api/v1/documents.py:DOC_TYPE_FILES`가 찾는 파일명과 **같은 규칙**이어야 한다 —
# 여기가 갈라지면 "document_status는 READY인데 뷰어는 404"가 된다(BUGS #50과 같은 부류).
# `api.v1.documents`를 import하지 않는 이유는 그쪽이 fastapi를 끌어오기 때문이다
# (이 모듈은 selenium/fastapi 무의존이어야 테스트에서 그대로 쓸 수 있다).
# 두 정의가 어긋나지 않는지는 회귀 테스트가 소스를 대조해 확인한다.
CANONICAL_DOC_FILENAME = {
    "SPEC": "spec.pdf",
    "STATUS": "status.html",
    "APPRAISAL": "appraisal.pdf",
}

# 이 경로로 "다운로드된 PDF"를 옮겨 완성할 수 있는 문서 종류.
# STATUS는 PDF 다운로드가 아니라 오버레이 HTML을 긁어오는 방식이라 여기 속하지 않는다
# (`crawler/doc_crawler.py:collect_status()`가 담당한다).
PDF_DOWNLOADABLE_DOC_TYPES = ("SPEC", "APPRAISAL")


def canonical_doc_path(court_name: str, case_no: str, item_no: str, doc_type: str) -> str:
    """뷰어가 서빙하는 최종 저장 경로. `doc_type`은 대문자(document_status 표기)다."""
    filename = CANONICAL_DOC_FILENAME[doc_type.upper()]
    return os.path.join(get_doc_dir(court_name, case_no, item_no), filename)
