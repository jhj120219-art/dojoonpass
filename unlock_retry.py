# -*- coding: utf-8 -*-
"""document_queue의 재시도 잠금(last_attempt_at)을 푼다.

`doc_worker`는 최근에 시도한 항목을 일정 시간 다시 집지 않는다. 그 대기를 수동으로
건너뛰고 싶을 때 쓰는 도구다.

2026-08-17 Sprint 148 정정 — 예전에는 이랬다:

    WHERE case_no = '2024타경1775' AND doc_type = 'appraisal'

두 가지가 문제였다.

1. **법원이 빠져 있었다.** 사건번호는 법원마다 독립적으로 매겨져서 전국적으로 유일하지
   않다(실측: case_no 3개가 두 법원에 걸쳐 있고 물건 22건이 연루된다). 같은 사건번호를
   가진 다른 법원의 큐 행까지 함께 풀려 엉뚱한 문서를 다시 받게 된다. 큐의 식별키는
   (court_code, case_no, item_no) 셋 전부다. BUGS #18 / #14 / #103과 같은 계열이다.
2. **대상이 소스에 박혀 있고 곧바로 커밋됐다.** 실행하면 무엇이 바뀔지 미리 볼 수 없었다.

그래서 인자로 받고, 이 저장소의 다른 도구들과 같이 **기본을 dry-run**으로 바꿨다
(`backfill_doc_raw.py` / `migrate_dryrun.py` / `empty_doc_dirs_dryrun.py`와 같은 규칙).

사용법:

    python unlock_retry.py 서울중앙지방법원 2024타경1775                 # 미리보기
    python unlock_retry.py 서울중앙지방법원 2024타경1775 --apply         # 실제 반영
    python unlock_retry.py 서울중앙지방법원 2024타경1775 --doc-type appraisal --item-no 1
"""
import os
import argparse
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 상태 어휘는 저장소에 하나뿐이다 - 여기서 문자열을 새로 적으면 언젠가 갈라진다
# (`repair_empty_status_capture.py` 가 같은 이유로 같은 곳에서 가져온다).
from storage.database import QUEUE_CLAIMABLE_STATUSES

# ★ DB 경로는 **현재 작업 디렉터리가 아니라 이 파일 기준**이다 (2026-08-21 Sprint 246).
#   상대경로면 다른 폴더에서 실행했을 때 그 폴더에 0바이트 auction.db 가 생기고
#   "no such table" 로 죽는다(실측). 운영 도구가 엉뚱한 DB 를 보는 것보다 낫지만,
#   찌꺼기 파일이 남고 오류 문구가 원인을 가린다.
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "auction.db")


def build_where(court, case_no, doc_type, item_no):
    """법원은 **항상** 조건에 들어간다(선택 인자가 아니다)."""
    where = ["court_code = ?", "case_no = ?"]
    params = [court, case_no]
    if item_no is not None:
        where.append("item_no = ?")
        params.append(item_no)
    if doc_type:
        where.append("doc_type = ?")
        params.append(doc_type)
    return " AND ".join(where), params


# ★ 잠금을 풀어도 되는 상태 (2026-09-04).
#
# `last_attempt_at` 한 컬럼이 **성격이 다른 두 가지**를 겸한다.
#
#   대기 상태(pending / refresh)   재시도 잠금이다.
#                                  `claim_next_queue_item()` 이
#                                  `last_attempt_at <= now-30분` 일 때만 집는다.
#                                  NULL 로 만들면 "지금 바로 집어도 된다"가 된다 —
#                                  이 도구가 하려던 일이 바로 그것이다.
#
#   그 밖의 상태                    **회수와 소유권의 유일한 근거**다.
#                                  - `reset_stale_queue()` 는 `in_progress` 회수와
#                                    `failed` -> `pending` 복구를 둘 다
#                                    `last_attempt_at IS NOT NULL` 로 걸러 낸다.
#                                  - `_claim_is_still_ours()` 는 claim 시점의
#                                    `last_attempt_at` 을 토큰으로 삼아 종결 권한을
#                                    확인한다(BUGS #181).
#
# 그래서 예전 동작(조건에 맞는 **모든** 행을 NULL)은 잠금을 푸는 것이 아니라
# **회수 장치를 부수는 것**이었다. 임시 DB 로 재현했다(2026-09-04):
#
#     in_progress + last_attempt_at=NULL  -> reset_stale_queue() 가 영원히 회수 못 한다
#                                            (in_progress 는 claim 대상도 아니다)
#                                         = 아무도 다시 집을 수 없는 **영구 정지 행**
#     failed      + last_attempt_at=NULL  -> 하루 뒤 pending 복구가 영원히 일어나지 않는다
#
# 둘 다 "재시도를 앞당기려고" 부른 도구가 **재시도를 영영 없애는** 정반대 결과다.
# 그래서 대기 상태만 푼다. 나머지는 건드리지 않고 왜 건너뛰었는지 화면에 남긴다 —
# 조용히 빼면 운영자는 "풀었다"고 믿는다(이 저장소가 반복해 잡아 온 침묵이다).
UNLOCKABLE_STATUSES = tuple(QUEUE_CLAIMABLE_STATUSES)


def main():
    ap = argparse.ArgumentParser(description="document_queue 재시도 잠금 해제")
    ap.add_argument("court", help="법원명 (예: 서울중앙지방법원) - 생략할 수 없다")
    ap.add_argument("case_no", help="사건번호 (예: 2024타경1775)")
    ap.add_argument("--item-no", default=None, help="물건번호 (생략하면 사건 전체)")
    ap.add_argument("--doc-type", default=None,
                    help="spec / status / appraisal (생략하면 전부)")
    ap.add_argument("--apply", action="store_true",
                    help="실제로 반영한다 (기본은 dry-run)")
    args = ap.parse_args()

    where, params = build_where(args.court, args.case_no, args.doc_type, args.item_no)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT court_code, case_no, item_no, doc_type, status, last_attempt_at "
            "FROM document_queue WHERE " + where, params).fetchall()

        if not rows:
            print("대상이 없다: %s %s" % (args.court, args.case_no))
            return 1

        unlockable = [r for r in rows
                      if r["last_attempt_at"] and r["status"] in UNLOCKABLE_STATUSES]
        protected = [r for r in rows
                     if r["last_attempt_at"] and r["status"] not in UNLOCKABLE_STATUSES]
        print("조건에 맞는 큐 행 %d개 (풀 수 있는 것 %d개 / 건드리지 않는 것 %d개)"
              % (len(rows), len(unlockable), len(protected)))
        for r in rows:
            mark = ""
            if r["last_attempt_at"] and r["status"] not in UNLOCKABLE_STATUSES:
                mark = "   <- 대기 상태가 아니라 건너뛴다(회수 근거를 지우면 안 된다)"
            print("   %s %s-%s %-10s %-12s last_attempt=%s%s"
                  % (r["court_code"], r["case_no"], r["item_no"], r["doc_type"],
                     r["status"], r["last_attempt_at"] or "-", mark))

        if protected:
            print("\n[주의] 위 %d행은 %s 상태가 아니다. last_attempt_at 을 지우면"
                  % (len(protected), " / ".join(UNLOCKABLE_STATUSES)))
            print("       reset_stale_queue() 가 그 행을 영원히 회수하지 못한다"
                  "(in_progress 는 정지, failed 는 복구 불가).")

        if not args.apply:
            print("\n[dry-run] --apply 를 붙이면 위 %d개의 last_attempt_at을 NULL로 만든다."
                  % len(unlockable))
            return 0

        if not unlockable:
            print("\n풀 수 있는 행이 없다. 아무것도 바꾸지 않았다.")
            return 0

        # ★ 상태 조건을 **SQL 에** 건다. 위에서 목록을 골라 두었지만 그 조회와
        #   여기 사이에 워커가 행을 집어갔을 수 있다 — 그러면 방금 in_progress 가
        #   된 행의 claim 토큰을 지우게 된다. 판정을 조회 시점 가정에 기대게 두지
        #   않는다(`storage/database.py:enqueue_documents()` 의 CAS 가드와 같은 규칙).
        status_ph = ", ".join("?" * len(UNLOCKABLE_STATUSES))
        cur = conn.execute(
            "UPDATE document_queue SET last_attempt_at = NULL WHERE " + where
            + " AND status IN (" + status_ph + ")",
            params + list(UNLOCKABLE_STATUSES))
        conn.commit()
        print("\n재시도 잠금 해제된 항목 수:", cur.rowcount)
        if protected:
            print("건드리지 않은 항목 수:", len(protected))
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
