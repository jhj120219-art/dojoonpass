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
import datetime
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ★ DB 경로는 **현재 작업 디렉터리가 아니라 이 파일 기준**이다 (2026-08-21 Sprint 246).
#   상대경로면 다른 폴더에서 실행했을 때 그 폴더에 0바이트 auction.db 가 생기고
#   "no such table" 로 죽는다(실측). 운영 도구가 엉뚱한 DB 를 보는 것보다 낫지만,
#   찌꺼기 파일이 남고 오류 문구가 원인을 가린다.
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "auction.db")
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

    head("1. document_queue 고아 - 대응 auction_item 이 없는 행")
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

    head("2. 그 고아가 '진짜' 고아인가 - 물건이 정말 없는지 다시 확인")
    # 지우기 전에 반드시 확인해야 하는 것: 법원만 다르게 저장돼 있을 가능성.
    for r in rows[:12]:
        same_case = conn.execute(
            "SELECT court_name, item_no FROM auction_item WHERE case_no=?",
            (r["case_no"],)).fetchall()
        note = ("다른 법원에 같은 사건번호 있음: %s"
                % [(x["court_name"], x["item_no"]) for x in same_case]) if same_case else "어디에도 없음"
        print("    %-14s %-16s 물건%-3s -> %s"
              % (r["court_code"], r["case_no"][:16], r["item_no"], note))

    head("3. documents/ 고아 디렉터리 - 대응 물건이 없는 문서 폴더")
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


    # ------------------------------------------------------------------
    # 3-b. 고아 큐 행이 실제로 **얼마를** 낭비하는가 (2026-08-21 Sprint 241 신설)
    #
    # 이 스크립트는 지금까지 고아 큐 행을 "해를 끼치지 않고 낭비만 한다"고만 적었다.
    # **얼마를** 낭비하는지가 없으면 정리 우선순위를 정할 수 없다. 그래서 잰다.
    #
    # 비용 모델은 추정이 아니라 **진짜 `doc_worker.main()` 을 돌려 관측한 것**이다
    # (2026-08-21, 브라우저만 가짜. 고아 사건에 대해 `go_to_case_detail()` 이 False 를
    #  돌려주는 실제 상황을 재현):
    #
    #     30분 간격 cycle1  이동 12회  retry 1  -> pending
    #     30분 간격 cycle2  이동 12회  retry 2  -> pending
    #     30분 간격 cycle3  이동 12회  retry 3  -> failed (종결)
    #     cycle4~6          이동  0회           (종결됐으므로 그날은 더 안 돈다)
    #     ★ 다음 날         이동 12회           reset_stale_queue() 가 failed 를 되살린다
    #
    # 즉 **기일이 남은 고아 1행 = 하루 MAX_DOC_RETRY(3)회 이동**이고,
    # 그것이 **기일이 지날 때까지 매일 반복**된다.
    #
    # 반대로 **기일이 이미 지난 고아는 공짜다.** 만료 가드가 브라우저를 열기 전에
    # SKIPPED_EXPIRED 로 종결하고, 그 상태는 reset_stale_queue() 가 되살리지 않는다
    # (같은 실측에서 이동 0회 확인).
    # ------------------------------------------------------------------
    head("3-b. 고아 큐 행의 워커 시간 비용 (실측 모델)")

    NAV_SECONDS = 10.9          # Sprint 235 실측 중앙값 (go_to_case_detail)
    MAX_RETRY = 3               # storage.database.MAX_DOC_RETRY
    today = datetime.date.today().isoformat()

    claimable = {"pending", "failed", "refresh", "refresh_pending"}
    costly, free, terminal = [], [], []
    for r in rows:
        if r["status"] not in claimable:
            terminal.append(r)
        elif r["auction_date"] and r["auction_date"] < today:
            free.append(r)
        else:
            costly.append(r)

    daily_navs = len(costly) * MAX_RETRY
    daily_seconds = daily_navs * NAV_SECONDS
    try:
        import config.settings as _cfg
        sh, sm = map(int, _cfg.DOC_WORKER_START_TIME.split(":"))
        eh, em = map(int, _cfg.DOC_WORKER_END_TIME.split(":"))
        window_min = (eh * 60 + em) - (sh * 60 + sm)
    except Exception:
        window_min = 120

    print("  고아 큐 행 %d행을 비용으로 나누면:" % len(rows))
    print("    종결 상태(더 안 돈다)            %3d행   비용 0" % len(terminal))
    print("    기일 경과(만료 가드가 막는다)     %3d행   비용 0 (브라우저 안 연다)" % len(free))
    print("    ★ 기일이 남았다(매일 재시도)      %3d행   비용 있음" % len(costly))
    print()
    print("  기일이 남은 고아의 하루 비용:")
    print("    이동 %d행 x %d회 = %d회 x %.1f초 = %.1f초 (%.1f분)"
          % (len(costly), MAX_RETRY, daily_navs, NAV_SECONDS, daily_seconds, daily_seconds / 60))
    print("    실행 창 %d분 대비 %.1f%%" % (window_min, 100.0 * daily_seconds / (window_min * 60)))
    print("    ※ 기일이 지날 때까지 **매일** 반복된다(reset_stale_queue 가 되살린다).")
    if not costly:
        print()
        print("  -> 지금은 기일이 남은 고아가 **0행**이라 실제 낭비는 없다.")
        print("     정리의 시급성은 낮다. 다만 크롤이 재개되면 새 고아는 위 비용을 곧바로 쓴다.")
    else:
        print()
        print("  -> 지금 이 %d행이 매일 %.1f분을 먹고 있다. 정리하면 그만큼이 회수된다."
              % (len(costly), daily_seconds / 60))

    print("""
  안전한 처리 방안 (이 스크립트는 실행하지 않는다)

    1순위  기일이 남은 고아만 손댄다. 기일 경과분은 이미 공짜라 지울 실익이 없다.
    2순위  지우기 전에 2절("진짜 고아인가")을 반드시 통과시킨다 - migrate_execute 가
           auction_item 을 재작성하는 중이면 **정상 물건도 잠깐 고아로 보인다.**
           그 순간에 지우면 살아 있는 물건의 큐를 지우는 것이 된다.
    3순위  지우는 대신 `mark_queue_unsupported()` 로 **종결**시키는 선택지도 있다.
           그 상태는 reset_stale_queue() 가 되살리지 않으므로 매일 반복이 끊긴다.
           행이 남으므로 되돌릴 수 있다(삭제보다 안전하다). 다만 이것도 큐를 바꾸는
           운영 변경이라 승인 영역이다.""")

    head("4. 삭제 기준 제안 (실행하지 않는다 - 사람이 판단할 근거)")
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
