"""고아 데이터(대응 물건이 없는 큐 행 / 문서 파일)를 **찾아서 보여준다.**

2026-08-14 신설. 이 스크립트는 **삭제하지 않는다.** `--apply` 옵션도 없다.
파괴적 정리는 운영 판단이므로, 여기서는 **무엇이 고아인지 / 왜 고아인지 / 지우면
무엇을 잃는지**를 정확히 만들어 두는 데까지만 한다.

왜 필요한가
-----------------------------------------------------------------------------
2026-08-14 실측에서 다음이 발견됐다.

    document_queue 고아      18행   대응 auction_item 이 없다
    documents/ 고아 디렉터리   6개   그중 1개에는 실제 파일 4개가 들어 있다

고아가 생긴 경로는 하나가 아니다. 확인된 것:

  * 물건이 사라졌는데 큐/파일은 남았다 (예: 고양지원 2024타경2803 — auction / auction_item
    양쪽에 행이 없는데 문서 4개가 디스크에 있다)
  * Migration 018 이전에 `item_no` 없이 적재된 큐 행 (당시 UNIQUE 에 item_no 가 없어
    두 번째 물건부터 조용히 삼켜졌다 — docs/BUGS.md #48)

**"고아"의 정의를 코드로 고정하는 것이 이 스크립트의 핵심이다.** 정의가 흔들리면
지우면 안 되는 것을 지운다. 특히 아래 두 가지를 지킨다.

  1. 법원 간 사건번호는 독립 채번이다 → 반드시 **(법원, 사건번호, 물건번호) 3자**로
     맞춘다. 사건번호만으로 조인하면 다른 법원의 같은 사건번호가 서로를 가려
     **고아가 아닌 것을 고아로 본다**(실측: 2개 이상 법원에 같은 case_no 3건).
  2. 파일이 실제로 들어 있는 디렉터리는 **따로 분류**한다. 빈 디렉터리와 같은 위험이 아니다.

    python cleanup_orphans_dryrun.py
"""
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

DB_PATH = "auction.db"
DOCUMENT_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "documents")


def head(t):
    print("\n" + "=" * 74 + "\n" + t + "\n" + "=" * 74)


def main() -> int:
    if "--apply" in sys.argv:
        print("이 스크립트는 삭제를 수행하지 않는다. --apply 는 지원하지 않는다.")
        print("삭제는 운영 판단이므로, 이 출력을 근거로 사람이 결정해야 한다.")
        return 2

    conn = sqlite3.connect("file:%s?mode=ro" % DB_PATH, uri=True)
    conn.row_factory = sqlite3.Row

    head("1. document_queue 고아 — 대응 auction_item 이 없는 행")
    # ★ 3자 조인. case_no 단독 조인은 법원 간 동명 사건을 가린다.
    rows = conn.execute("""
        SELECT dq.* FROM document_queue dq
        LEFT JOIN auction_item a
          ON a.court_name = dq.court_code
         AND a.case_no    = dq.case_no
         AND COALESCE(a.item_no,'1') = COALESCE(dq.item_no,'1')
        WHERE a.id IS NULL
        ORDER BY dq.court_code, dq.case_no, dq.item_no
    """).fetchall()
    print("  고아 큐 행: %d" % len(rows))
    by_status = {}
    for r in rows:
        by_status[r["status"]] = by_status.get(r["status"], 0) + 1
    print("  상태별:", by_status)
    for r in rows[:12]:
        print("    %-14s %-16s 물건%-3s %-10s %s 기일=%s"
              % (r["court_code"], r["case_no"][:16], r["item_no"], r["doc_type"],
                 r["status"], r["auction_date"]))
    if len(rows) > 12:
        print("    ... 외 %d행" % (len(rows) - 12))

    head("2. 그 고아가 '진짜' 고아인가 — 물건이 정말 없는지 다시 확인")
    # 지우기 전에 반드시 확인해야 하는 것: 법원만 다르게 저장돼 있을 가능성.
    for r in rows[:12]:
        same_case = conn.execute(
            "SELECT court_name, item_no FROM auction_item WHERE case_no=?",
            (r["case_no"],)).fetchall()
        note = ("다른 법원에 같은 사건번호 있음: %s"
                % [(x["court_name"], x["item_no"]) for x in same_case]) if same_case else "어디에도 없음"
        print("    %-14s %-16s 물건%-3s -> %s"
              % (r["court_code"], r["case_no"][:16], r["item_no"], note))

    head("3. documents/ 고아 디렉터리 — 대응 물건이 없는 문서 폴더")
    empty_dirs, with_files = [], []
    if os.path.isdir(DOCUMENT_ROOT):
        for court in sorted(os.listdir(DOCUMENT_ROOT)):
            cdir = os.path.join(DOCUMENT_ROOT, court)
            if not os.path.isdir(cdir):
                continue
            for case in sorted(os.listdir(cdir)):
                casedir = os.path.join(cdir, case)
                if not os.path.isdir(casedir):
                    continue
                for item_no in sorted(os.listdir(casedir)):
                    idir = os.path.join(casedir, item_no)
                    if not os.path.isdir(idir):
                        continue
                    hit = conn.execute(
                        "SELECT id FROM auction_item WHERE court_name=?"
                        " AND REPLACE(case_no,'/','_')=? AND COALESCE(item_no,'1')=?",
                        (court, case, item_no)).fetchone()
                    if hit:
                        continue
                    files = [f for f in os.listdir(idir)
                             if os.path.isfile(os.path.join(idir, f))]
                    (with_files if files else empty_dirs).append((court, case, item_no, files))

    print("  빈 고아 디렉터리        : %d" % len(empty_dirs))
    for d in empty_dirs:
        print("    %s / %s / %s" % d[:3])
    print("  ★ 파일이 든 고아 디렉터리: %d" % len(with_files))
    for court, case, item_no, files in with_files:
        total = sum(os.path.getsize(os.path.join(DOCUMENT_ROOT, court, case, item_no, f))
                    for f in files)
        print("    %s / %s / %s -> %s (%.1f KB)"
              % (court, case, item_no, files, total / 1024))

    head("4. 삭제 기준 제안 (실행하지 않는다 — 사람이 판단할 근거)")
    print("""  안전한 순서로만 적는다. 각 단계는 **되돌릴 수 없다.**

  [A] 빈 고아 디렉터리 (%d개)
      잃을 것이 없다. 파일이 0개이므로 삭제해도 정보 손실이 없다.
      다만 크롤러가 곧 다시 만들 수 있으므로 실익도 크지 않다.

  [B] 고아 큐 행 (%d행)
      doc_worker 가 집어도 `_set_document_status()` 가 대상 물건을 못 찾아
      경고만 남기고 끝난다(조용히 실패하지는 않는다). 즉 **해를 끼치지 않고
      낭비만 한다.** 지우면 그 낭비가 사라진다.
      ※ 지우기 전에 2절에서 "어디에도 없음"인지 반드시 확인할 것.

  [C] 파일이 든 고아 디렉터리 (%d개)
      **가장 신중해야 한다.** 물건 행이 왜 사라졌는지가 먼저다.
      물건이 잘못 지워진 것이라면 이 파일이 유일한 사본일 수 있다.
      지우기 전에: 같은 사건이 다른 법원/다른 item_no 로 저장돼 있지 않은지,
      그리고 백업에 남아 있는지 확인해야 한다.
    """ % (len(empty_dirs), len(rows), len(with_files)))

    head("5. 결론")
    print("  이 스크립트는 아무것도 지우지 않았다.")
    print("  삭제는 운영 데이터 파괴이므로 사람의 판단이 필요하다.")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
