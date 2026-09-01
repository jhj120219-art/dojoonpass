"""내용이 비어 있는 현황조사서 캡처(status.html)를 재수집 대상으로 되돌린다.

2026-08-12 Sprint 62 (docs/BUGS.md #61).

왜 필요한가
-----------
`crawler/doc_crawler.py:collect_status()`는 오버레이 텍스트가 **비어 있지만 않으면**
데이터가 채워진 것으로 보고 저장했다. 그런데 오버레이 골격에는 "사건번호", "조사일시",
"검색결과가 없습니다" 같은 **고정 라벨**이 처음부터 들어 있어서, 비동기 데이터가 도착하기
전에도 그 조건이 즉시 참이 됐다. 그래서 사건 데이터가 하나도 없는 페이지가 정상 수집으로
저장됐다.

실측(2026-08-12): status.html 194건 중 **33건**이 이 상태다.
정상 161건은 본문에 사건번호(YYYY타경NNNNN)가 전부 있고, 이 33건은 하나도 없다(완전 분리).

더 나쁜 것은 그 다음이다 — `doc_exists()`는 "파일이 있고 0바이트 초과"만 보므로 이 빈
파일들은 **영구히 재수집 대상에서 빠진다**. 사용자에게는 빈 현황조사서가 계속 보이고,
권리분석 데이터도 영원히 채워지지 않는다.

**왜 1회성인가** — 같은 Sprint에서 `collect_status()`가 (1) 실제 사건 데이터가 채워질
때까지 대기하고 (2) 저장 직전에 한 번 더 검사해 빈 캡처는 **아예 저장하지 않도록**
고쳤다. 앞으로 수집되는 문서에는 이 문제가 생기지 않는다. 이 스크립트는 그 수정 이전에
쌓인 파일만 정리한다.

**파일을 지우지 않고 격리(quarantine)한다** — 판정이 틀렸을 경우 되돌릴 수 있어야 하고,
원본은 크롤러 동작을 나중에 분석할 때 근거가 된다.

    python repair_empty_status_capture.py            # 무엇이 바뀌는지 보고만 한다 (기본)
    python repair_empty_status_capture.py --apply    # 실제로 반영한다
"""
import sys
import os
import argparse
import shutil
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from storage.database import (get_connection,
                              QUEUE_STATUS_PENDING, QUEUE_STATUS_DONE)
# ★ `get_doc_dir()`이 아니라 `_doc_dir_path()`를 쓴다 (2026-08-17 Sprint 153, BUGS #111).
#
# `get_doc_dir()`은 `os.makedirs()`를 부른다. 아래 `find_empty_captures()`는 **읽기 전용
# 스캔**인데 물건 1,876건 전부에 대해 그 함수를 불렀다 — 즉 "이 문서 있어요?"라고 묻기만
# 해도 디렉터리가 생겼다. 실측상 `documents/` 아래 빈 물건 디렉터리가 1,674개이고,
# 여기에 파일이 있는 202개를 더하면 정확히 1,876 = `auction_item` 행수다.
#
# 이 저장소는 같은 사고를 이미 겪고 `_doc_dir_path()`(계산만)와 `get_doc_dir()`(생성까지)로
# 분리해 `doc_exists()`를 고쳤다(2026-08-14). 그런데 이 스크립트에만 적용이 빠져 있었다.
from crawler.doc_paths import _doc_dir_path, status_overlay_has_data

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
QUARANTINE_ROOT = os.path.join(PROJECT_ROOT, "documents_quarantine")


def find_empty_captures(conn):
    """사건 데이터가 없는 status.html을 가진 물건 목록.

    판정은 크롤러가 저장 시점에 쓰는 것과 **같은 함수**(`status_overlay_has_data`)로 한다 —
    여기서 규칙이 갈라지면 "크롤러는 정상이라 저장했는데 이 스크립트는 비었다고 지우는"
    무한 왕복이 생긴다.
    """
    rows = conn.execute(
        "SELECT id, court_name, case_no, item_no FROM auction_item"
    ).fetchall()

    empty, ok = [], 0
    for r in rows:
        d = _doc_dir_path(r["court_name"], r["case_no"], r["item_no"])
        path = os.path.join(d, "status.html")
        if not os.path.exists(path):
            continue
        html = open(path, encoding="utf-8", errors="ignore").read()
        if status_overlay_has_data(html):
            ok += 1
        else:
            empty.append({
                "item_id": r["id"], "court_name": r["court_name"],
                "case_no": r["case_no"], "item_no": r["item_no"],
                "dir": d, "path": path, "size": os.path.getsize(path),
            })
    return empty, ok


def repair(apply: bool) -> int:
    conn = get_connection()
    try:
        empty, ok = find_empty_captures(conn)
        print("status.html 보유 물건: 정상 %d건 / 내용 없음 %d건" % (ok, len(empty)))

        # 안전장치 — 정상 파일이 하나도 없으면 판정 기준 자체가 의심스럽다.
        # (documents/ 경로 문제나 판정 함수 회귀로 전부 "비었다"가 될 수 있다)
        if empty and ok == 0:
            print("[안전장치] 정상 파일이 0건이다. 판정 기준이나 경로가 잘못됐을 수 있어 중단한다.")
            return 1
        if not empty:
            print("정리할 대상이 없다.")
            return 0

        for e in empty[:10]:
            print("   item_id=%-6s %s %s-%s (%d bytes)"
                  % (e["item_id"], e["court_name"], e["case_no"], e["item_no"], e["size"]))
        if len(empty) > 10:
            print("   ... 외 %d건" % (len(empty) - 10))

        if not apply:
            print("\n[dry-run] --apply 를 붙이면 아래를 수행한다:")
            print("  1) status.html/status.json 을 documents_quarantine/ 로 이동")
            print("  2) document_status(STATUS) 를 COLLECTING 으로 되돌림")
            print("  3) document_queue 의 해당 status 행을 pending 으로 되돌림")
            return 0

        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        moved = requeued = reset = 0
        for e in empty:
            rel = os.path.relpath(e["dir"], os.path.join(PROJECT_ROOT, "documents"))
            qdir = os.path.join(QUARANTINE_ROOT, stamp, rel)
            os.makedirs(qdir, exist_ok=True)
            for name in ("status.html", "status.json"):
                src = os.path.join(e["dir"], name)
                if os.path.exists(src):
                    shutil.move(src, os.path.join(qdir, name))
                    moved += 1

            # 화면이 읽는 상태를 "수집중"으로 되돌린다.
            reset += conn.execute(
                "UPDATE document_status SET status='COLLECTING' "
                "WHERE item_id=? AND doc_type='STATUS'", (e["item_id"],)).rowcount
            # 큐도 다시 집도록 되돌린다(재시도 횟수도 초기화 — 실패가 아니라 잘못 저장된 것이므로).
            #
            # 식별키에 반드시 법원을 넣는다. 사건번호는 법원마다 독립적으로 매겨져서
            # 전국적으로 유일하지 않다 — 실측상 case_no 3개가 서로 다른 두 법원에 걸쳐
            # 있고 물건 22건이 연루된다(2026-08-17). 법원을 빼면 A법원 물건을 고치면서
            # 같은 사건번호를 가진 **B법원의 정상 수집분까지 pending으로 되돌려** 멀쩡한
            # 문서를 다시 받게 만든다. `document_queue.court_code`와
            # `auction_item.court_name`은 같은 60종 어휘를 쓴다(차집합 0, 실측 확인).
            # 같은 계열의 사고가 BUGS #18 / #14 / #103으로 반복됐다.
            requeued += conn.execute(
                # 상태값을 리터럴로 박지 않는다 - 오타가 예외가 아니라 **0행 매치**로
                # 조용히 끝나기 때문이다(storage/database.py 의 어휘 주석과 같은 이유).
                "UPDATE document_queue SET status=?, retry_count=0, last_attempt_at=NULL "
                "WHERE court_code=? AND case_no=? AND item_no=? "
                "AND doc_type='status' AND status=?",
                (QUEUE_STATUS_PENDING, e["court_name"], e["case_no"], e["item_no"],
                 QUEUE_STATUS_DONE)).rowcount
        conn.commit()

        print("\n적용 완료")
        print("  격리한 파일: %d개 -> %s" % (moved, os.path.join(QUARANTINE_ROOT, stamp)))
        print("  document_status COLLECTING 으로 되돌림: %d행" % reset)
        print("  document_queue pending 으로 되돌림: %d행" % requeued)
        return 0
    finally:
        conn.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="실제로 반영한다(기본은 dry-run)")
    args = ap.parse_args()
    return repair(args.apply)


if __name__ == "__main__":
    sys.exit(main())
