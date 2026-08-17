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
import time
from typing import Optional

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
def sanitize_path_segment(value: str) -> str:
    """경로 한 조각(사건번호·물건번호)을 디렉터리 이름으로 안전하게 만든다.

    ## 왜 함수로 뽑았나 (2026-08-17 Sprint 145)

    같은 치환이 **세 곳에** 각자 적혀 있었다 — 이 파일의 `_doc_dir_path()`와
    `find_sibling_case_document()`, 그리고 `crawler/image_assets.py:image_path()`.
    바로 위 `_doc_dir_path()`의 주석이 *"규칙이 두 벌이 되면 쓰는 곳과 읽는 곳이 다른
    경로를 보는 이 저장소의 단골 결함이 된다"* 고 적어 둔 그 상태다. 한 곳으로 모은다.

    ## `/`만으로는 부족하다 (실측)

    사건번호는 복수 사건이 합쳐질 때 `"2024타경1451 / 2024타경32745"`처럼 들어온다
    (실 DB 1,876건 중 **425건(22.7%)**이 `/`를 포함한다). 그래서 `/`를 `_`로 바꿔 왔다.

    그런데 **Windows에서는 역슬래시도 경로 구분자**다. 실측:

        case_no = r"..\\..\\evil"  ->  documents/ 를 벗어나 <repo>/evil/1 을 가리킨다

    서빙 쪽은 `realpath`+`commonpath`로 이미 막혀 있어 파일이 새지는 않는다
    (`api/v1/documents.py`, `api/v1/images.py`). 그러나 **쓰기 쪽**은 `get_doc_dir()`가
    `os.makedirs()`를 부르므로 저장소 바깥에 디렉터리를 만들 수 있다. 이 저장소는
    이미 `doc_paths` 때문에 빈 디렉터리 1,674개가 생긴 사고를 겪었다.

    현재 실데이터에 역슬래시·`..`는 **0건**이다(확인함). 즉 지금 터지고 있는 버그가
    아니라, 원천(법원 사이트 HTML)이 예상 밖 값을 주면 터지는 자리를 미리 막는 것이다.
    """
    safe = (value or "").replace("/", "_").replace("\\", "_").strip()
    # 경로를 거슬러 올라가는 조각은 이름으로 쓰지 않는다. 빈 값도 마찬가지 —
    # os.path.join에 ""를 주면 조각이 통째로 사라져 상위 디렉터리를 가리킨다.
    if safe in ("", ".", ".."):
        return "_"
    return safe


def _doc_dir_path(court_code: str, case_no: str, item_no: str = "1") -> str:
    """경로만 계산한다. **디스크를 건드리지 않는다.**

    2026-08-14 분리. 경로 규칙은 여기 한 곳에만 두고, `get_doc_dir()`은 여기에
    디렉터리 생성을 얹는다 — 규칙이 두 벌이 되면 "쓰는 곳과 읽는 곳이 다른 경로를
    보는" 이 저장소의 단골 결함이 된다.
    """
    return os.path.join(DOCUMENT_ROOT, court_code,
                        sanitize_path_segment(case_no),
                        sanitize_path_segment(item_no or "1"))


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


# 사건 단위 문서 — 물건번호와 무관하게 사건 전체에 하나만 존재하는 문서.
# ---------------------------------------------------------------------------
# 2026-08-17 Sprint 145 실측으로 확정했다. 같은 사건(2025타경311)의 물건 1과 물건 2에
# 대해 **각각 따로** 실제 수집을 돌려 바이트를 대조한 결과:
#
#     status.html   40,596 B  해시 동일          -> 완전히 같은 파일
#     status.json   12,014 B  해시 다름          -> 그런데 내용은 같다
#                             `fields` 115개 키가 완전 일치하고, 차이는 우리가 찍는
#                             `extracted_at` 타임스탬프 하나뿐이었다
#
# 법원 DOM에서도 같은 결론이 나온다 — 현황조사서 버튼(`..._btn_curstExmndcTop`)만
# 물건번호가 안 붙고, 오버레이 본문이 사건의 모든 물건을 한 문서에 담는다
# (집행관이 사건 단위로 작성하는 문서다).
#
# 왜 이 상수가 필요한가 — 사건에 물건이 N개면 **같은 문서를 N번 받게 된다.**
# 실측 비용(2026-08-17): 사건 1,384개 / 물건 1,876개이므로 초과 수집 492회(35.5%),
# worker 1건당 약 22초이니 **약 3.0시간**이다(가동 창 02:00~04:00 = 2시간을 넘는다).
# (★ 2026-08-17 Sprint 147 정정: 이 '약 3시간'은 navigation까지 건너뛴다고 **가정한** 값이다. Sprint 145 구현은 `collect_status()` 안에서만 재사용해 물건당 0.6초(overlay)만 아꼈고 navigation 15.2초는 그대로 들었다 — 실제 절감 492회 기준 **5분**. Sprint 147이 doc_worker의 호출 순서를 바꿔(재사용 가능하면 이동 자체를 생략) 실 worker 2건 기준 41.1초 -> 23.8초, 492회 기준 **약 130분** 절감으로 실현했다.)
# 용량은 13.4 MB로 무시할 수준이라, 비용은 저장이 아니라 **시간**이다.
CASE_LEVEL_DOC_TYPES = ("status",)


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


# 사건 단위 문서를 형제 물건에서 재사용하기 (2026-08-17 Sprint 145)
# ---------------------------------------------------------------------------
# 위 `CASE_LEVEL_DOC_TYPES` 주석의 실측이 근거다 — 같은 사건의 다른 물건이 이미 받아 둔
# 현황조사서는 **바이트까지 같은 문서**이므로, 브라우저를 다시 몰지 않고 복사하면 된다.
#
# ★ 이것은 **저장 구조 변경이 아니다.** 파일은 종전과 똑같은 경로
#   (`documents/<법원>/<사건>/<물건>/status.html`)에 똑같은 내용으로 놓인다.
#   달라지는 것은 "그 바이트를 어디서 얻는가"뿐이다(법원 재조회 -> 형제 물건 복사).
#   그래서 API·뷰어·`doc_exists()`·백필 어느 것도 영향을 받지 않는다.

def find_sibling_case_document(court_code: str, case_no: str, item_no: str,
                               doc_type: str, max_age_seconds: Optional[float] = None):
    """같은 사건의 **다른 물건**이 이미 받아 둔 사건 단위 문서를 찾는다. 없으면 None.

    돌려주는 값: 그 형제 물건의 디렉터리 경로.

    `max_age_seconds`가 주어지면 기준 파일이 그보다 오래된 형제는 **쓰지 않는다.**
    호출부(`collect_status`)가 "같은 실행에서 방금 받은 것만 재사용"하도록 좁히는 데 쓴다 —
    몇 달 전에 받은 문서를 새 물건에 복사하면, 새로 받았다면 얻었을 최신본 대신 옛것을
    주게 된다. 재수집 정책이 아직 미결정이라(`docs/roadmap.md`) 그 판단을 여기서
    내리지 않고, **보수적으로 좁힐 수 있는 손잡이만** 둔다.

    디스크를 건드리지 않는다(읽기만 한다) — `doc_exists()`와 같은 규약이다.
    """
    key = (doc_type or "").lower()
    if key not in CASE_LEVEL_DOC_TYPES:
        return None
    ext = _PRIMARY_EXT.get(key)
    if not ext:
        return None

    safe_case_no = sanitize_path_segment(case_no)
    safe_item_no = sanitize_path_segment(item_no or "1")
    case_dir = os.path.join(DOCUMENT_ROOT, court_code, safe_case_no)
    if not os.path.isdir(case_dir):
        return None

    now = time.time()
    for sibling in sorted(os.listdir(case_dir)):
        if sibling == safe_item_no:
            continue
        sib_dir = os.path.join(case_dir, sibling)
        if not os.path.isdir(sib_dir):
            continue
        primary = os.path.join(sib_dir, key + "." + ext)
        try:
            if os.path.getsize(primary) <= 0:
                continue
            if max_age_seconds is not None and (now - os.path.getmtime(primary)) > max_age_seconds:
                continue
        except OSError:
            continue
        return sib_dir
    return None
