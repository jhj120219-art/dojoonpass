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
import argparse
import sqlite3
import sys

DB_PATH = "auction.db"


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

        locked = [r for r in rows if r["last_attempt_at"]]
        print("조건에 맞는 큐 행 %d개 (그중 잠긴 것 %d개)" % (len(rows), len(locked)))
        for r in rows:
            print("   %s %s-%s %-10s %-12s last_attempt=%s"
                  % (r["court_code"], r["case_no"], r["item_no"], r["doc_type"],
                     r["status"], r["last_attempt_at"] or "-"))

        if not args.apply:
            print("\n[dry-run] --apply 를 붙이면 위 %d개의 last_attempt_at을 NULL로 만든다."
                  % len(locked))
            return 0

        cur = conn.execute(
            "UPDATE document_queue SET last_attempt_at = NULL WHERE " + where, params)
        conn.commit()
        print("\n재시도 잠금 해제된 항목 수:", cur.rowcount)
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
