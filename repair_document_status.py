"""과거에 어긋난 `document_status`를 디스크 실물 기준으로 1회 보정한다.

2026-08-11 Sprint 55 (docs/BUGS.md #50).

왜 필요한가 — 문서 상태가 두 곳에 따로 기록되고 있었다.

    auction.has_*_pdf   doc_worker가 갱신 (스케줄러가 매일 돌리는 살아있는 경로)
    document_status     collect_documents.py만 갱신 (어떤 배치도 부르지 않는 스크립트)

화면이 읽는 것은 후자라서, PDF를 이미 받아 둔 물건이 계속 "수집중"으로 보였다
(실측 2026-08-11: has_spec_pdf=1인 197건 중 192건).

**왜 1회성인가** — 같은 Sprint에서 `mark_queue_done()` / `mark_queue_failed()`가
`document_status`를 함께 갱신하도록 고쳤다. 앞으로 수집되는 문서는 자동으로 맞는다.
이 스크립트는 그 수정 이전에 쌓인 이력만 정리한다. 배치에 넣지 않는 이유가 그것이다
(넣으면 필요 없는 작업을 매일 돌리는 데다, 상태를 두 경로가 또 건드리게 된다).

**판단 근거는 DB 플래그가 아니라 디스크 실물이다.** `auction.has_spec_pdf=1`은
과거에 잘못 세워졌을 수 있지만, 파일이 실제로 있으면 사용자는 그것을 열 수 있다.
경로 계산은 `api/v1/documents.py`가 서빙에 쓰는 것과 **같은 규칙**을 쓴다 —
여기서 규칙이 갈라지면 "READY인데 뷰어는 404"가 된다.

    python repair_document_status.py            # 무엇이 바뀌는지 보고만 한다 (기본)
    python repair_document_status.py --apply    # 실제로 반영한다
"""
import sys
import os
import argparse
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from storage.database import get_connection

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
DOCUMENT_ROOT = os.path.join(PROJECT_ROOT, "documents")

# 뷰어가 서빙하는 파일명표는 아래에서 **정본을 그대로 빌려 쓴다** (`DOC_TYPE_FILES`).
#   정본: `crawler/doc_paths.py:CANONICAL_DOC_FILENAME`
# 예전에는 여기에 손으로 적은 사본이 있었고, 그 위에 "같아야 한다"는 주석만
# 달려 있었다 — **그 약속을 강제하는 검사가 없었다.** 자세한 사유는
# 아래 import 문 다음의 정의를 보라.


# 2026-08-17 Sprint 153 (BUGS #111 계열 전수 검색): 조각 정규화를 **크롤러와 같은 함수**로
# 맞췄다. 예전에는 여기에 규칙 사본이 있었고, 그 사본은 `/`만 치환했다:
#
#     safe_case_no = (case_no or "").replace("/", "_").strip()
#
# 크롤러가 쓰는 `sanitize_path_segment()`는 그 사이 **역슬래시도 치환**하고
# `""`/`"."`/`".."`를 `"_"`로 바꾸도록 바뀌었다(Sprint 145~146). 규칙이 갈라진 채로
# 두면 사건번호에 역슬래시가 섞였을 때 크롤러는 `a_b`에 쓰고 이 스크립트는 `a\b`를 찾아
# **같은 문서를 서로 다른 경로로 보게 된다** — 이 저장소가 BUGS #50/#64로 반복해 겪은
# 어긋남이고, `crawler/doc_paths.py`의 주석이 "규칙이 두 벌이 되면"이라고 경고하는 바로
# 그것이다. 이 스크립트는 그 판정으로 `document_status`를 READY로 바꾸므로, 어긋나면
# **화면만 '수집완료'이고 서빙은 404**인 상태를 만든다.
#
# 현재 실데이터에 역슬래시는 0건이라 지금 터지는 버그는 아니다. 규칙이 세 벌인 상태를 없앤다.
# `crawler.doc_paths`는 selenium/DB/fastapi 무의존이라 여기서 import해도 안전하다.
from crawler.doc_paths import (  # noqa: E402
    _doc_dir_path,
    CANONICAL_DOC_FILENAME,
)


# 뷰어가 실제로 서빙하는 파일명. **사본을 두지 않는다** (2026-09-04).
#
# 이 스크립트는 "그 파일이 디스크에 있는가"로 `document_status` 를 READY 로
# 바꾸기 때문에, 여기서 보는 파일과 뷰어가 내려주는 파일이 갈라지면
# **화면만 '수집완료'이고 서빙은 404** 가 된다 — 이 파일 docstring 이 없애려는
# 바로 그 상태다(BUGS #50/#61/#64/#129 와 같은 부류).
#
# 예전에는 여기에 세 항목을 손으로 적어 두고 "같아야 한다"라고만 적어 두었다.
# 그런데 그 약속을 강제하는 검사가 없어서, 정본이 바뀌어도 여기는 조용히 낡을 수
# 있었다. 같은 계열의 다른 사본은 전부 정본과 대조되고 있었고
# (`test_doc_storage_atomicity.py` / `test_document_status_sync.py`),
# `sanitize_path_segment` 는 Sprint 153 에 이미 정본 호출로 바뀌었다 —
# 이 표만 반쪽만 옮겨진 채로 남아 있었다.
#
# 값은 종전과 **바이트까지 같다**(APPRAISAL/SPEC/STATUS → appraisal.pdf/spec.pdf/
# status.html). 동작은 하나도 바뀐 것이 없고, 갈라질 **수 있는 자리**를 없앤다.
DOC_TYPE_FILES = dict(CANONICAL_DOC_FILENAME)


def get_doc_dir(court_name: str, case_no: str, item_no: str) -> str:
    """정본(`crawler/doc_paths.py:_doc_dir_path()`)을 그대로 쓴다.

    **디렉터리를 만들지 않는다** — 이 스크립트는 존재 여부만 판정하는 읽기 전용 도구다
    (BUGS #111: 조회 함수가 `os.makedirs()`를 불러 빈 디렉터리 1,674개가 생긴 사고).

    ## `court_name or ""` 를 버렸다 (2026-09-04)

    예전 구현은 법원 조각에 `or ""` 를 붙여 두었다. 그래서 `court_name=None` 일 때
    **예외 없이 한 단계 위 경로**(`<ROOT>/<사건>/<물건>`)를 돌려줬다 — 정본과
    서빙 쪽은 같은 입력에서 TypeError 를 낸다. 세 구현의 계약이 갈라져 있었고,
    하필 이 파일 것만 **조용히 틀린 경로**를 냈다.

    이 스크립트는 그 경로에 파일이 있으면 `document_status` 를 READY 로 바꾼다.
    그 경로는 DOCUMENT_ROOT **안**이라 아래 담김 검사도 통과한다. 즉 "화면은
    수집완료인데 뷰어는 404" 를 없애려고 만든 도구가, 바로 그 상태를 만들 수 있었다.

    지금 실데이터에 `court_name IS NULL` 은 0행이고 `document_exists()` 가 호출
    **전에** 그것을 걸러내므로 도달하지 않는다. 그래서 지우는 것은 동작 변경이
    아니라 **갈라질 수 있는 자리를 없애는 것**이다.
    """
    # 뿌리는 **이 모듈 것**을 준다(위 documents.py 와 같은 이유).
    return _doc_dir_path(court_name, case_no, item_no, root=DOCUMENT_ROOT)


def document_exists(court_name: str, case_no: str, item_no: str, doc_type: str) -> bool:
    filename = DOC_TYPE_FILES.get(doc_type)
    if not filename or not court_name or not case_no:
        return False

    path = os.path.join(get_doc_dir(court_name, case_no, item_no), filename)

    # api/v1/documents.py:get_document()와 **같은** 경로 탈출 검사.
    # `get_doc_dir()`가 슬래시를 치환하긴 하지만 `court_name`은 치환 대상이 아니고,
    # `case_no='..'`처럼 슬래시 없는 값은 그대로 상위로 올라간다. 값이 DB에서 오므로
    # 당장 악용 경로는 없지만, 여기서 검사를 빼면 DOCUMENT_ROOT 밖 파일의 존재 여부로
    # 상태를 READY로 바꾸게 된다 — 서빙은 404인데 화면만 "수집완료"가 되는 상태다.
    real_root = os.path.realpath(DOCUMENT_ROOT)
    real_path = os.path.realpath(path)
    try:
        if os.path.commonpath([real_root, real_path]) != real_root:
            return False
    except ValueError:
        # 드라이브가 다르면 commonpath가 ValueError를 낸다 — 그것도 밖이다.
        return False

    # 크기까지 본다 — 이 저장소의 "문서가 있다" 정의는 하나다 (2026-08-14).
    #
    #     crawler/doc_paths.py:doc_exists()  =  exists() and getsize() > 0
    #
    # 여기서 `exists()`만 보면 **0바이트 파일을 보고 READY로 바꾼다.** 그런데 서빙
    # 경로(`api/v1/documents.py`)는 0바이트를 404로 막는다. 결과는 바로 위 주석이
    # 예고한 그 상태다 ― **화면은 "수집완료", 실제 다운로드는 404.**
    # 이 스크립트의 목적이 정확히 그 불일치를 없애는 것이므로, 판정 기준도 같아야 한다.
    #
    # `isfile()`을 쓰는 이유: `exists()`는 디렉터리에도 True다.
    return os.path.isfile(real_path) and os.path.getsize(real_path) > 0


def scan(conn):
    """(고쳐야 할 행, 이미 맞는 행, 파일 없는 행) 을 센다. 아무것도 쓰지 않는다."""
    rows = conn.execute("""
        SELECT ds.id, ds.item_id, ds.doc_type, ds.status,
               ai.court_name, ai.case_no, ai.item_no
        FROM document_status ds
        JOIN auction_item ai ON ai.id = ds.item_id
    """).fetchall()

    to_fix, already, missing = [], 0, 0
    for r in rows:
        exists = document_exists(r["court_name"], r["case_no"], r["item_no"], r["doc_type"])
        if not exists:
            missing += 1
            continue
        if r["status"] == "READY":
            already += 1
        else:
            to_fix.append(r)
    return to_fix, already, missing, len(rows)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="실제로 반영한다. 없으면 보고만 하고 아무것도 쓰지 않는다.")
    args = ap.parse_args()

    conn = get_connection()
    try:
        to_fix, already, missing, total = scan(conn)

        print("=" * 60)
        print("document_status 실물 대조")
        print("=" * 60)
        print("  전체 행                    : %d" % total)
        print("  파일 있음 + 이미 READY     : %d" % already)
        print("  파일 있음 + 상태 어긋남    : %d   <- 보정 대상" % len(to_fix))
        print("  파일 없음(건드리지 않음)   : %d" % missing)

        if to_fix:
            print("")
            print("  보정 대상 예시 (상위 10건):")
            for r in to_fix[:10]:
                print("    item_id=%-6s %-10s %-12s -> READY   %s %s-%s"
                      % (r["item_id"], r["doc_type"], r["status"],
                         r["court_name"], r["case_no"], r["item_no"]))

        if not args.apply:
            print("")
            print("  (보고만 함. 반영하려면 --apply)")
            return 0

        if not to_fix:
            print("")
            print("  보정할 것이 없습니다.")
            return 0

        now = datetime.now().isoformat()
        for r in to_fix:
            conn.execute(
                "UPDATE document_status SET status='READY', updated_at=? WHERE id=?",
                (now, r["id"]),
            )
        conn.commit()
        print("")
        print("  %d건 READY로 보정했습니다." % len(to_fix))

        # 반영 후 재검사 — 멱등성 확인. 한 번 더 돌려서 0이 아니면 규칙이 잘못된 것이다.
        again, _, _, _ = scan(conn)
        print("  재검사 잔여: %d건 (0이어야 합니다)" % len(again))
        return 0 if not again else 1
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
