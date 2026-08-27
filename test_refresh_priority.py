# -*- coding: utf-8 -*-
"""`refresh_priority.py` 회귀 — 2026-08-24 Sprint 252 신설.

## 왜 이 파일이 생겼나

전체 스위트를 coverage 로 돌려 **제품 모듈별 합산 커버리지**를 냈더니, 커버리지 0% 인
제품 모듈이 5개였다. 그중 넷은 성격이 분명하다 —

    filter/report_generator.py / filter/scoring_engine.py   아무도 안 부르는 죽은 코드
                                                            (CLAUDE.md 가 "테스트를 붙이지 말라"고
                                                             명시. 배선되는 순간이 테스트할 때다)
    unlock_retry.py / backfill_doc_raw.py                    운영자 수동 도구(기본 dry-run).
                                                            정적 가드가 따로 있다
                                                            (test_schema_hygiene 의 --apply 검사)

**나머지 하나가 다르다.** `refresh_priority.py` 는 **스케줄 파이프라인의 진입점**이다 —
`run_priority_refresh.bat` 이 매일 01:50 에 이것을 돌린다(등록은 승인 영역이지만, 등록
직후부터 매일 도는 코드다). 그런데 어떤 테스트도 이 파일을 **한 줄도 실행한 적이 없었다.**

즉 깨져 있어도 알 수 있는 방법이 "새벽에 배치가 실패하는 것"뿐이었다. 이 저장소가
반복해서 경계해 온 "없는 것은 눈에 띄지 않는다"의 전형이다.

## 무엇을 고정하는가

`main()` 을 **실제로 실행한다**(import 만 하지 않는다). 운영 DB 는 건드리지 않는다 —
`storage.database.DB_PATH` 를 스크래치 사본으로 돌리고, 끝나면 지운다.

    1. main() 이 예외 없이 끝난다            .bat 의 errorlevel 계약(실패 시 non-zero)
    2. 우선순위가 실제로 재계산된다          기일이 임박한 대기 행의 priority 가 올라간다
    3. 반환값은 **바뀐 행 수**다              Sprint 63 정정: 검토한 행 수가 아니다
    4. 종결 상태는 건드리지 않는다            done / SKIPPED_EXPIRED 는 되살아나면 안 된다
    5. 바꿀 것이 없으면 0건                   같은 입력으로 두 번 돌리면 두 번째는 0

    python test_refresh_priority.py
"""
import datetime
import os
import shutil
import sqlite3
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

failures = []


def check(name, actual, expected):
    ok = actual == expected
    print("[%s] %s: %r (expected %r)" % ("PASS" if ok else "FAIL", name, actual, expected))
    if not ok:
        failures.append(name)


def check_true(name, cond, detail=""):
    print("[%s] %s%s" % ("PASS" if cond else "FAIL", name, ("" if cond else " -- " + str(detail))))
    if not cond:
        failures.append(name)


def _days_out(n):
    return (datetime.date.today() + datetime.timedelta(days=n)).isoformat()


def run():
    import storage.database as db

    root = os.path.dirname(os.path.abspath(__file__))
    src = db.DB_PATH
    if not os.path.exists(src):
        check_true("원본 DB 가 있다", False, src)
        return 1

    tmp = tempfile.mkdtemp(prefix="refreshprio_")
    scratch = os.path.join(tmp, "auction.db")
    # ★ `shutil.copy2()` 를 쓰지 않는다 — 다른 프로세스가 쓰는 중이면 찢어진 사본이
    #   나온다(`snapshot_live_db()` docstring 의 실측). 2026-08-27 BUGS #251 에서
    #   `test_db_snapshot.py` 의 감사가 **별칭을 따라가도록** 강화되며 드러났다.
    db.snapshot_live_db(scratch)
    saved = db.DB_PATH
    db.DB_PATH = scratch

    # refresh_priority 는 import 시점에 storage.database 의 이름을 가져간다.
    # DB_PATH 를 바꾼 **뒤에** import 해야 스크래치를 본다 — 그리고 그 함수들은
    # 호출 시점에 db.DB_PATH 를 읽으므로(get_connection 안에서) 순서만 맞으면 된다.
    try:
        import refresh_priority

        # ── 준비: 우선순위가 확실히 틀린 대기 행을 심는다 ──────────────────
        # calc_priority: <=3일 -> 1, <=7일 -> 2, 그 밖 -> 3
        con = sqlite3.connect(scratch)
        try:
            con.execute("DELETE FROM document_queue WHERE court_code = 'QA법원'")
            seed = [
                # (doc_type, auction_date, 심어 둘 priority, 기대 priority, status)
                ("spec",      _days_out(1),  3, 1, "pending"),   # 임박 -> 1 로 올라가야
                ("status",    _days_out(5),  3, 2, "pending"),   # 7일 이내 -> 2
                ("appraisal", _days_out(30), 1, 3, "pending"),   # 멀다 -> 3 으로 내려가야
                ("image",     _days_out(2),  1, 1, "pending"),   # 이미 정답 -> 안 바뀜
                ("spec",      _days_out(1),  3, 1, "refresh"),   # refresh 도 대기 행이다
                ("status",    _days_out(1),  3, 3, "done"),      # 종결 -> 건드리지 않는다
                ("appraisal", _days_out(1),  3, 3, "SKIPPED_EXPIRED"),
            ]
            for i, (dt, ad, prio, _exp, st) in enumerate(seed):
                con.execute(
                    "INSERT INTO document_queue"
                    " (court_code, case_no, item_no, doc_type, priority, auction_date,"
                    "  status, retry_count, enqueued_at)"
                    " VALUES ('QA법원', ?, '1', ?, ?, ?, ?, 0, ?)",
                    ("2099타경%d" % i, dt, prio, ad, st, datetime.datetime.now().isoformat()))
            con.commit()
            planted = con.execute(
                "SELECT COUNT(*) FROM document_queue WHERE court_code='QA법원'").fetchone()[0]
        finally:
            con.close()
        check("심어 둔 QA 행 수", planted, len(seed))

        # ── 1회차 실행 ────────────────────────────────────────────────────
        crashed = None
        try:
            refresh_priority.main()
        except Exception as exc:      # noqa: BLE001
            crashed = "%s: %s" % (type(exc).__name__, exc)
        check_true("★ main() 이 예외 없이 끝난다(.bat 의 errorlevel 계약)",
                   crashed is None, crashed)

        con = sqlite3.connect(scratch)
        con.row_factory = sqlite3.Row
        try:
            got = {}
            for r in con.execute(
                    "SELECT case_no, doc_type, status, priority FROM document_queue"
                    " WHERE court_code='QA법원' ORDER BY case_no"):
                got[r["case_no"]] = (r["doc_type"], r["status"], r["priority"])
        finally:
            con.close()

        for i, (dt, ad, _prio, exp, st) in enumerate(seed):
            case_no = "2099타경%d" % i
            actual = got.get(case_no)
            check_true("%s(%s/%s) priority == %d" % (case_no, dt, st, exp),
                       actual is not None and actual[2] == exp,
                       "-> %r" % (actual,))

        # ── 2회차: 이제 바꿀 것이 없어야 한다 (반환값이 '바뀐 행 수'라는 계약) ──
        changed2 = db.refresh_queue_priority()
        check("★ 두 번째 실행의 변경 건수(검토 수가 아니라 변경 수다)", changed2, 0)

        # ── 종결 상태가 대기로 되살아나지 않았는가 ────────────────────────
        con = sqlite3.connect(scratch)
        try:
            statuses = dict(con.execute(
                "SELECT status, COUNT(*) FROM document_queue"
                " WHERE court_code='QA법원' GROUP BY status").fetchall())
        finally:
            con.close()
        check("종결 상태 행이 그대로다(done 1 / SKIPPED_EXPIRED 1)",
              (statuses.get("done"), statuses.get("SKIPPED_EXPIRED")), (1, 1))

        # ── 검사가 공허하지 않다: 1회차에 실제로 뭔가 바뀌었는가 ──────────
        #    (심어 둔 7행 중 4행이 틀린 우선순위였다: idx 0,1,2,4)
        con = sqlite3.connect(scratch)
        try:
            corrected = con.execute(
                "SELECT COUNT(*) FROM document_queue WHERE court_code='QA법원'"
                " AND status IN ('pending','refresh') AND priority = ?", (1,)).fetchone()[0]
        finally:
            con.close()
        check_true("검사가 공허하지 않다(임박 대기 행이 priority 1 이 됐다)",
                   corrected >= 3, "-> priority=1 인 대기 행 %d개" % corrected)

    finally:
        db.DB_PATH = saved
        shutil.rmtree(tmp, ignore_errors=True)

    # 운영 DB 가 정말 그대로인지 마지막으로 확인한다 — 이 파일이 스크래치를 쓴다는
    # 주장 자체를 검증한다(경로를 잘못 되돌리면 다음 실행이 운영 DB 를 건드린다).
    con = sqlite3.connect("file:%s?mode=ro" % saved.replace("\\", "/"), uri=True)
    try:
        leaked = con.execute(
            "SELECT COUNT(*) FROM document_queue WHERE court_code='QA법원'").fetchone()[0]
    finally:
        con.close()
    check("★ 운영 DB 에 QA 행이 새지 않았다", leaked, 0)
    check("DB_PATH 가 원래대로 복원됐다", db.DB_PATH, saved)

    print("\n" + "=" * 55)
    if failures:
        print("FAILED (%d): %s" % (len(failures), ", ".join(failures)))
        return 1
    print("ALL TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(run())
