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

# api/v1/documents.py:DOC_TYPE_FILES 와 같아야 한다.
DOC_TYPE_FILES = {
    "APPRAISAL": "appraisal.pdf",
    "SPEC": "spec.pdf",
    "STATUS": "status.html",
}


def get_doc_dir(court_name: str, case_no: str, item_no: str) -> str:
    """api/v1/documents.py:get_doc_dir() 와 동일한 규칙."""
    safe_case_no = (case_no or "").replace("/", "_").strip()
    safe_item_no = (item_no or "1").replace("/", "_").strip()
    return os.path.join(DOCUMENT_ROOT, court_name or "", safe_case_no, safe_item_no)


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

    return os.path.exists(real_path)


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
