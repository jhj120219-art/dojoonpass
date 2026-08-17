"""
auction 식별키 회귀 테스트 (docs/BUGS.md #14, #18 / 2026-08-08 Migration 010~016 복구).

python.exe만 있으면 실행되는 순수 로직 테스트다 — jose를 타지 않는 storage.database만
import한다. 두 부분으로 나뉜다:

    1) 실제 auction.db(읽기 전용 쿼리만)에 대한 무결성 불변식 검사 — orphan / duplicate /
       court mismatch / NULL court_code가 전부 0이어야 한다.
    2) upsert_batch()의 법원 교차 덮어쓰기 방지 회귀 — 임시 스크래치 DB 사본에서만 쓰기
       테스트를 수행한다(실제 auction.db는 절대 쓰지 않는다).

    python test_auction_identity.py
"""
import sys
import os
import shutil
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import storage.database as dbmod

failures = []


def check(name, actual, expected):
    ok = actual == expected
    print("[%s] %s: %r (expected %r)" % ("PASS" if ok else "FAIL", name, actual, expected))
    if not ok:
        failures.append(name)


def test_real_db_integrity_invariants():
    """실제 auction.db에 대한 읽기 전용 무결성 검사. 데이터를 전혀 바꾸지 않는다."""
    print("\n--- 1. real auction.db integrity invariants (read-only) ---")
    conn = dbmod.get_connection()
    try:
        check(
            "auction dup (court_code,case_no,item_no)",
            len(conn.execute(
                "SELECT court_code,case_no,item_no,COUNT(*) c FROM auction"
                " GROUP BY court_code,case_no,item_no HAVING c>1"
            ).fetchall()),
            0,
        )
        check(
            "auction_case dup (court_code,case_no)",
            len(conn.execute(
                "SELECT court_code,case_no,COUNT(*) c FROM auction_case"
                " GROUP BY court_code,case_no HAVING c>1"
            ).fetchall()),
            0,
        )
        check(
            "auction_item dup (case_id,item_no)",
            len(conn.execute(
                "SELECT case_id,item_no,COUNT(*) c FROM auction_item"
                " GROUP BY case_id,item_no HAVING c>1"
            ).fetchall()),
            0,
        )
        check(
            "auction_case.court_code NULL count",
            conn.execute("SELECT COUNT(*) FROM auction_case WHERE court_code IS NULL").fetchone()[0],
            0,
        )
        check(
            "auction_item.case_id NULL count",
            conn.execute("SELECT COUNT(*) FROM auction_item WHERE case_id IS NULL").fetchone()[0],
            0,
        )
        check(
            "auction_item.case_id orphan (no matching auction_case)",
            conn.execute(
                "SELECT COUNT(*) FROM auction_item ai LEFT JOIN auction_case ac"
                " ON ai.case_id = ac.id WHERE ai.case_id IS NOT NULL AND ac.id IS NULL"
            ).fetchone()[0],
            0,
        )
        check(
            "court mismatch (auction_item.court_name != linked auction_case.court_code)",
            conn.execute(
                "SELECT COUNT(*) FROM auction_item ai JOIN auction_case ac"
                " ON ai.case_id = ac.id WHERE ai.court_name != ac.court_code"
            ).fetchone()[0],
            0,
        )
        for t in ("favorites", "recent_items", "registry_usage", "registry_requests",
                  "document_status", "doc_raw", "parsed_document", "tenant_rights",
                  "rights_summary", "rights_analysis_history"):
            check(
                "%s.item_id orphan" % t,
                conn.execute(
                    "SELECT COUNT(*) FROM %s t LEFT JOIN auction_item ai ON t.item_id = ai.id"
                    " WHERE t.item_id IS NOT NULL AND ai.id IS NULL" % t
                ).fetchone()[0],
                0,
            )
        ddl_auction = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='auction'"
        ).fetchone()[0]
        check("auction has court-aware UNIQUE", "UNIQUE(court_code, case_no, item_no)" in ddl_auction, True)
        ddl_case = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='auction_case'"
        ).fetchone()[0]
        check("auction_case has court-aware UNIQUE", "UNIQUE(court_code, case_no)" in ddl_case, True)
        ddl_item = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='auction_item'"
        ).fetchone()[0]
        check("auction_item has case_id-based UNIQUE", "UNIQUE(case_id, item_no)" in ddl_item, True)
    finally:
        conn.close()


def test_cross_court_upsert_safety():
    """docs/BUGS.md #18 재발 방지: 서로 다른 법원이 같은 case_no+item_no를 upsert해도
    한쪽이 사라지지 않고 별도 행으로 공존해야 한다. 실제 auction.db가 아니라 임시 사본에서만
    쓰기 테스트를 수행한다."""
    print("\n--- 2. cross-court upsert_batch() safety (scratch copy only) ---")
    real_path = dbmod.DB_PATH
    tmp_dir = tempfile.mkdtemp(prefix="kokchal_qa_")
    tmp_db = os.path.join(tmp_dir, "scratch.db")
    shutil.copy2(real_path, tmp_db)
    dbmod.DB_PATH = tmp_db
    try:
        case_no = "QA-AUCTION-IDENTITY-TEST"
        r1 = dbmod.upsert_batch([{
            "court_code": "QA법원A", "court_name": "QA법원A",
            "case_no": case_no, "item_no": "1", "full_address": "A",
        }])
        check("court A first insert", r1, {"inserted": 1, "updated": 0, "failed": 0})

        r2 = dbmod.upsert_batch([{
            "court_code": "QA법원B", "court_name": "QA법원B",
            "case_no": case_no, "item_no": "1", "full_address": "B",
        }])
        check("court B upsert with SAME case_no+item_no -> separate INSERT, not overwrite",
              r2, {"inserted": 1, "updated": 0, "failed": 0})

        conn = dbmod.get_connection()
        rows = conn.execute(
            "SELECT court_code, full_address FROM auction WHERE case_no=? ORDER BY court_code",
            (case_no,),
        ).fetchall()
        check("both courts' rows coexist after cross-court upsert", len(rows), 2)
        by_court = {r["court_code"]: r["full_address"] for r in rows}
        check("court A row preserved (not overwritten by court B)",
              by_court.get("QA법원A"), "A")
        check("court B row present", by_court.get("QA법원B"), "B")

        r3 = dbmod.upsert_batch([{
            "court_code": "QA법원A", "court_name": "QA법원A",
            "case_no": case_no, "item_no": "1", "full_address": "A-updated",
        }])
        check("court A re-upsert with same key -> UPDATE in place, not a new row",
              r3, {"inserted": 0, "updated": 1, "failed": 0})
        rows2 = conn.execute(
            "SELECT COUNT(*) FROM auction WHERE case_no=?", (case_no,)
        ).fetchone()[0]
        check("row count still 2 after same-court re-upsert (no duplicate created)", rows2, 2)
        conn.close()
    finally:
        dbmod.DB_PATH = real_path
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_cross_court_migrate_safety():
    """§2의 나머지 절반 — **동기화 경로**도 법원을 구분하는가 (2026-08-14 신설).

    §2는 크롤러의 쓰기 경로(`upsert_batch`)가 법원을 구분하는지 본다. 그런데 데이터가
    화면에 닿으려면 `migrate_execute.py`를 한 번 더 지나야 하고, **그쪽은 검사가 없었다.**

    실제로 거기 구멍이 있었다. 2026-08-07에 "auction_item 조회/갱신에 법원 구분이 없다"를
    고쳐 `(case_id, item_no)` 로 바꿨는데(migrate_execute.py 주석), 60줄 아래
    `document_status` 조회는 `WHERE case_no=? AND item_no=?` 그대로 남아 있었다.
    같은 수정의 나머지 절반이 빠진 것이다.

    증상(2026-08-14 사본 재현): 법원이 다른 같은 (사건, 물건) 두 개를 만들면

        수집 완료한 쪽 : document_status 행이 **아예 생기지 않는다**
                         -> 받아 둔 문서를 사용자가 못 본다
        자체 검증      : document_status 건수 불일치

    실 DB에는 법원이 다른 같은 사건번호가 **3개** 있다(2024타경34089 / 2024타경3700 /
    2024타경4973). 지금은 물건번호가 마침 달라 무사할 뿐이다.

    실제 auction.db는 쓰지 않는다 — 임시 사본에서만 돌린다.
    """
    print("\n--- 5. cross-court migrate_execute safety (scratch copy only) ---")
    import sqlite3
    import migrate_execute

    real_path = dbmod.DB_PATH
    tmp_dir = tempfile.mkdtemp(prefix="kokchal_mig_")
    tmp_db = os.path.join(tmp_dir, "scratch.db")
    shutil.copy2(real_path, tmp_db)
    dbmod.DB_PATH = tmp_db
    try:
        CASE, ITEM = "QA-MIGRATE-COURT", "1"
        # 같은 (사건, 물건)을 두 법원에 만든다. 한쪽만 문서를 수집한 상태로 둔다.
        dbmod.upsert_batch([
            {"court_code": "QA법원A", "court_name": "QA법원A", "case_no": CASE,
             "item_no": ITEM, "full_address": "A"},
            {"court_code": "QA법원B", "court_name": "QA법원B", "case_no": CASE,
             "item_no": ITEM, "full_address": "B"},
        ])
        # `has_*_pdf` 는 크롤 수집 결과라 `upsert_batch()` 의 입력이 아니다
        # (doc_worker 가 따로 쓴다). 그래서 여기서 직접 세운다 —
        # 처음에 upsert 입력에 넣었다가 전제 검사에 걸렸다.
        conn = dbmod.get_connection()
        try:
            conn.execute("UPDATE auction SET has_spec_pdf=1"
                         " WHERE case_no=? AND court_code='QA법원A'", (CASE,))
            conn.commit()
            seeded = conn.execute(
                "SELECT court_code, has_spec_pdf FROM auction WHERE case_no=?"
                " ORDER BY court_code", (CASE,)).fetchall()
        finally:
            conn.close()
        # 전제가 깨지면 아래 판정은 의미가 없다.
        check("전제: 두 법원 행이 만들어졌다", len(seeded), 2)
        check("전제: 한쪽만 수집 완료", [r["has_spec_pdf"] for r in seeded], [1, 0])

        ok = migrate_execute.execute()
        _check_true("migrate_execute 가 검증을 통과한다", ok,
                    "자체 건수 검증이 실패하면 문서 상태가 유실된 것이다")

        c = sqlite3.connect(tmp_db)
        c.row_factory = sqlite3.Row
        try:
            got = {r["court_code"]: r["st"] for r in c.execute("""
                SELECT ac.court_code,
                       (SELECT status FROM document_status
                         WHERE item_id = ai.id AND doc_type='SPEC') AS st
                FROM auction_item ai JOIN auction_case ac ON ac.id = ai.case_id
                WHERE ai.case_no=? AND ai.item_no=?""", (CASE, ITEM))}
        finally:
            c.close()

        # 핵심: 두 법원이 **각자의** 문서 상태를 갖는다.
        check("수집한 법원은 READY", got.get("QA법원A"), "READY")
        check("수집하지 않은 법원은 COLLECTING", got.get("QA법원B"), "COLLECTING")
        _check_true("두 법원 모두 document_status 행을 갖는다(유실 없음)",
                    None not in (got.get("QA법원A"), got.get("QA법원B")), got)
    finally:
        dbmod.DB_PATH = real_path
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_migrate_exit_code_contract():
    """검증이 실패하면 **종료코드로도** 실패여야 한다 (2026-08-14 신설).

    예전에는 `[FAIL] document_status 불일치: ...` 를 찍고도 `sys.exit(0)` 이었다.
    그래서 `run_daily.bat` 의 `if errorlevel 1` 에 걸리지 않고, **자기 검증이 실패했다고
    적혀 있는 그 로그 파일에** `[SUCCESS]` 마커가 함께 찍혔다.

    이 저장소가 Sprint 13/54/99에서 `.bat` 계층에 대해 없앤 "실패 은폐"와 같은 모양이고,
    이번에는 파이썬 쪽에 남아 있었다.
    """
    print("\n--- 6. migrate_execute 종료코드 계약 ---")
    import sqlite3
    import migrate_execute

    real_path = dbmod.DB_PATH
    tmp_dir = tempfile.mkdtemp(prefix="kokchal_exit_")
    tmp_db = os.path.join(tmp_dir, "scratch.db")
    shutil.copy2(real_path, tmp_db)
    dbmod.DB_PATH = tmp_db
    try:
        _check_true("정상 상태에서는 True(성공)를 돌려준다", migrate_execute.execute() is True)

        # 건수 검증을 깨뜨린다 — migrate 는 stray 행을 지우지 않으므로 그대로 남는다.
        c = sqlite3.connect(tmp_db)
        try:
            c.execute("INSERT INTO document_status (item_id, doc_type, status, updated_at)"
                      " VALUES (999999, 'SPEC', 'READY', '2026-01-01')")
            c.commit()
        finally:
            c.close()

        _check_true("검증이 깨지면 False(실패)를 돌려준다",
                    migrate_execute.execute() is False,
                    "True를 돌려주면 run_daily.bat이 [SUCCESS]를 남긴다")
    finally:
        dbmod.DB_PATH = real_path
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # 호출부도 함께 고정한다 — 반환값을 만들어 놓고 __main__ 이 무시하면 의미가 없다.
    src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "migrate_execute.py"), encoding="utf-8-sig").read()
    main_block = src[src.index('if __name__ == "__main__":'):]
    _check_true("__main__ 이 execute() 의 반환값을 종료코드로 쓴다",
                "execute()" in main_block and "sys.exit(0)" not in main_block,
                main_block.strip()[:160])


def test_dryrun_predicts_what_execute_does():
    """미리보기가 **실행 결과와 같은 숫자**를 말하는가 (2026-08-14 신설).

    `migrate_dryrun.py` 는 `migrate_execute.py` 를 돌리기 전에 무엇이 만들어질지 보여준다.
    그런데 `auction_case` 중복 제거 키가 **`case_no` 단독**이었다 —
    execute 는 `(court_code, case_no)` 를 쓴다.

        2026-08-14 실측
          dryrun  (case_no 만)      1,381건
          execute (court+case_no)   1,384건   <- 실제 auction_case 행 수

    미리보기가 실행 결과와 다른 숫자를 말하면, 실행 뒤 그 차이를 보고
    "execute 가 뭔가 잘못했다"고 오판한다. 두 키가 같은지 **출력으로** 확인한다
    (소스를 대조하면 형태만 같고 동작이 달라도 통과할 수 있다).

    읽기 전용이다 — dryrun 은 아무것도 쓰지 않는다.
    """
    print("\n--- 7. dryrun 예고 == execute 결과 ---")
    import io
    import re
    import contextlib
    import migrate_dryrun

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        migrate_dryrun.dryrun()
    out = buf.getvalue()

    m = re.search(r"auction_case\s*예정\s*:\s*([\d,]+)", out)
    _check_true("dryrun 출력에서 auction_case 예정 건수를 읽었다", bool(m), out[:200])
    if not m:
        return
    predicted = int(m.group(1).replace(",", ""))

    conn = dbmod.get_connection()
    try:
        # execute 와 같은 키로 센다 — 이것이 실제로 만들어질 auction_case 수다.
        truth = conn.execute(
            "SELECT COUNT(*) FROM (SELECT DISTINCT court_code, case_no FROM auction)"
        ).fetchone()[0]
        actual = conn.execute("SELECT COUNT(*) FROM auction_case").fetchone()[0]
    finally:
        conn.close()

    print("    예고 %d / (court,case) 고유 %d / 실제 auction_case %d"
          % (predicted, truth, actual))
    check("dryrun 예고가 (court_code, case_no) 기준과 같다", predicted, truth)
    # 실제 테이블과도 같아야 한다 — 셋이 어긋나면 어느 쪽이 틀렸는지부터 봐야 한다.
    check("실제 auction_case 행 수와도 같다", actual, truth)


def _check_true(name, cond, detail=""):
    print("[%s] %s%s" % ("PASS" if cond else "FAIL", name, ("" if cond else " -- " + str(detail))))
    if not cond:
        failures.append(name)


def test_upsert_partial_failure_isolation():
    """행 하나가 깨져도 배치 전체가 죽지 않는가 (2026-08-13 Sprint 78 신설).

    커버리지로 찾은 미검증 경로다 — `upsert_batch()`의 행 단위 예외 처리
    (`storage/database.py` 245-247)와 전체 실패 롤백(254-257)이 한 번도 실행되지 않았다.
    §2는 정상 경로(insert/update/법원 격리)만 본다.

    왜 중요한가 — 이 함수는 **매일 06:00 크롤러의 유일한 DB 쓰기 경로**다(mvp_scraper.py).
    법원 60곳에서 모은 수백 행을 한 번에 넣는데, 그중 한 행이 기형이면(가격 필드에 숫자가
    아닌 값이 오는 것은 크롤링에서 드문 일이 아니다) **나머지 전부가 함께 사라지면 안 된다.**
    이 저장소의 FR-101("1개 실패는 전체 실패로 이어지지 않는다")이 이 경로에도 적용된다.

    실제 auction.db는 절대 쓰지 않는다 — §2와 같은 스크래치 사본 방식.
    """
    print("\n--- 3. upsert_batch() partial failure isolation (scratch copy only) ---")
    real_path = dbmod.DB_PATH
    tmp_dir = tempfile.mkdtemp(prefix="kokchal_qa_upsert_")
    tmp_db = os.path.join(tmp_dir, "scratch.db")
    shutil.copy2(real_path, tmp_db)
    dbmod.DB_PATH = tmp_db
    try:
        case = "QA-UPSERT-ISOLATION"

        def row(item_no, price="1000", court="QA법원C"):
            return {"court_code": court, "court_name": court, "case_no": case,
                    "item_no": item_no, "full_address": "addr-" + item_no,
                    "appraisal_price": price, "minimum_bid_price": "500"}

        # 가운데 행의 가격이 숫자가 아니다 -> int() 변환에서 ValueError.
        # 앞뒤 행은 정상이므로 저장돼야 한다.
        #
        # ★ 예외를 잡아 FAIL로 바꾼다. 격리가 사라지면 이 호출이 그대로 던지는데, 그러면
        # 스위트가 **크래시로 중단**돼 남은 검사가 실행되지 않는다(변이 시험에서 확인).
        # 실패는 깔끔한 FAIL이어야 원인과 범위를 함께 볼 수 있다
        # (`test_api_regression.py::_safe_out`이 같은 이유로 존재한다).
        try:
            result = dbmod.upsert_batch([row("1"), row("2", price="가격미정"), row("3")])
        except Exception as exc:  # noqa: BLE001
            _check_true("깨진 행이 배치 전체를 죽이지 않는다(행 단위 격리)", False,
                        "예외가 그대로 올라왔다: %r" % (exc,))
            result = {"inserted": 0, "updated": 0, "failed": 0}
        else:
            _check_true("깨진 행이 배치 전체를 죽이지 않는다(행 단위 격리)", True)

        check("깨진 행은 failed로 계수된다", result["failed"], 1)
        check("정상 행은 그대로 저장된다", result["inserted"], 2)
        _check_true("합계가 입력 행 수와 같다(조용히 사라지는 행이 없다)",
                    result["inserted"] + result["updated"] + result["failed"] == 3, result)

        conn = dbmod.get_connection()
        try:
            saved = {r["item_no"] for r in conn.execute(
                "SELECT item_no FROM auction WHERE case_no=?", (case,)).fetchall()}
            check("깨진 행 앞의 정상 행이 커밋됐다", "1" in saved, True)
            check("깨진 행 뒤의 정상 행도 커밋됐다", "3" in saved, True)
            check("깨진 행은 저장되지 않았다", "2" in saved, False)
        finally:
            conn.close()

        # 재실행: 정상 행은 UPDATE로, 깨진 행은 여전히 failed로 간다(누적 오염 없음).
        again = dbmod.upsert_batch([row("1", price="2000"), row("2", price="가격미정")])
        check("재실행 시 정상 행은 update", again["updated"], 1)
        check("재실행 시 깨진 행은 여전히 failed", again["failed"], 1)
        conn = dbmod.get_connection()
        try:
            price = conn.execute(
                "SELECT appraisal_price FROM auction WHERE case_no=? AND item_no='1'",
                (case,)).fetchone()["appraisal_price"]
            check("update가 실제로 값을 바꿨다", price, 2000)
            check("깨진 행이 뒤늦게 생기지도 않았다", conn.execute(
                "SELECT COUNT(*) FROM auction WHERE case_no=? AND item_no='2'",
                (case,)).fetchone()[0], 0)
        finally:
            conn.close()

        # 빈 배치: 크롤이 0건을 돌려준 날에도 예외 없이 0을 보고해야 한다
        # (mvp_scraper는 rows가 비면 enqueue를 건너뛰지만 upsert 자체는 호출될 수 있다).
        check("빈 배치는 0/0/0", dbmod.upsert_batch([]),
              {"inserted": 0, "updated": 0, "failed": 0})

        # 필수 키가 아예 없는 행 — 크롤러 파싱이 실패했을 때의 모습이다.
        # 지금 구현은 빈 문자열 기본값으로 저장한다(예외가 아니다). 그 동작을 고정한다:
        # 조용히 죽지 않는다는 것이 계약이고, 빈 키 행을 어떻게 다룰지는 크롤러 정책이다.
        empty = dbmod.upsert_batch([{}])
        _check_true("키 없는 행도 배치를 죽이지 않는다",
                    empty["inserted"] + empty["updated"] + empty["failed"] == 1, empty)
        conn = dbmod.get_connection()
        try:
            conn.execute("DELETE FROM auction WHERE case_no=? OR case_no=''", (case,))
            conn.commit()
        finally:
            conn.close()
    finally:
        dbmod.DB_PATH = real_path
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_get_stats_contract():
    """`get_stats()` — 크롤러가 매 실행 끝에 로그로 남기는 요약(미검증 경로였다).

    이 값이 틀리면 운영자가 "오늘 몇 건 들어왔나"를 잘못 읽는다. 실제 DB를 읽기만 한다.
    """
    print("\n--- 4. get_stats() contract (read-only) ---")
    stats = dbmod.get_stats()
    _check_true("dict를 돌려준다", isinstance(stats, dict), type(stats))
    total = dbmod.get_connection()
    try:
        actual = total.execute("SELECT COUNT(*) FROM auction").fetchone()[0]
    finally:
        total.close()
    # 키 이름은 구현이 정한다 — 총건수를 담은 키가 실제 건수와 맞는지만 본다.
    matching = [k for k, v in stats.items() if v == actual]
    _check_true("총 건수와 일치하는 항목이 있다(집계가 실제 DB를 반영한다)",
                bool(matching) or actual == 0, "stats=%r actual=%d" % (stats, actual))
    _check_true("음수 값이 없다", all(
        (v >= 0) for v in stats.values() if isinstance(v, (int, float))), stats)


# ---------------------------------------------------------------------------
# document_queue 를 쓰는 SQL은 반드시 법원으로 좁혀야 한다 (2026-08-17 Sprint 148 신설)
#
# 사건번호는 법원마다 독립적으로 매겨진다. 전국적으로 유일하지 않으므로 큐의 식별키는
# (court_code, case_no, item_no) 셋 전부다. 하나라도 빠지면 다른 법원의 행을 건드린다.
#
# 이 계열의 사고가 반복됐다 — BUGS #18, #14, #103, 그리고 Sprint 148에서 발견한
# `repair_empty_status_capture.py`의 재큐잉 UPDATE(법원 누락으로 다른 법원의 정상
# 수집분까지 pending으로 되돌림)까지 네 번째다. 개별 수정만으로는 다섯 번째가 또 나온다.
#
# 실측 근거(2026-08-17): case_no 3개가 서로 다른 두 법원에 걸쳐 있고 물건 22건이 연루된다.
# 0.2%라 눈에 잘 안 띄지만 0이 아니므로 "실무상 유일하다"는 가정은 성립하지 않는다.
#
# 검사 대상은 **git이 추적하는 프로덕션 .py**로 한정한다. `check_*.py`/`step*.py` 같은
# 일회성 조사 스크립트는 gitignore 대상이라 애초에 빠지고, 테스트 자신은 합성 case_no를
# 쓰므로 제외한다.
# ---------------------------------------------------------------------------
def _sql_literal_at(src, pos):
    """`pos`가 들어 있는 파이썬 문자열 리터럴의 내용을 돌려준다.

    인접한 리터럴이 이어 붙어 있으면(이 저장소에서 긴 SQL을 쓰는 방식) 함께 잇는다.
    리터럴 밖으로는 절대 넘어가지 않으므로, 뒤따르는 파라미터 튜플이나 다음 문장이
    검사 대상에 섞이지 않는다.
    """
    import re as _re

    i = pos
    while i > 0 and src[i - 1] not in "\"'":
        i -= 1
    if i == 0:
        return src[pos:pos + 200]
    q = src[i - 1]
    if i >= 3 and src[i - 3:i] == q * 3:          # 삼중 따옴표
        j = src.find(q * 3, pos)
        return src[pos:j if j > 0 else pos + 500]

    parts = []
    k = pos
    for _ in range(20):                            # 인접 연결은 현실적으로 몇 개뿐이다
        j = k
        while j < len(src) and src[j] != q:
            if src[j] == "\\":
                j += 1
            j += 1
        parts.append(src[k:j])
        nxt = _re.match(r"\s*([\"'])", src[j + 1:j + 120])
        if not nxt:
            break
        q = nxt.group(1)
        k = j + 1 + nxt.end()
    return " ".join(parts)


def test_document_queue_writes_are_court_scoped():
    print("\n--- document_queue 쓰기 SQL이 법원으로 좁혀지는가 ---")
    import re
    import subprocess

    root = os.path.dirname(os.path.abspath(__file__))

    # ★ 2026-08-17 Sprint 178: **미추적 파일도 검사한다.**
    #
    # 예전에는 `git ls-files`만 썼다. 그런데 이 저장소는 지금 실동작 모듈 여러 개가
    # 아직 add되지 않은 상태이고(`api/v1/images.py` / `api/http_cache.py` /
    # `crawler/image_crawler.py` 등, 프로덕션이 실제로 import한다), 그것들이 검사에서
    # 통째로 빠져 있었다. 즉 **"검사했다"고 말하면서 실동작 코드를 건너뛰고 있었다.**
    #
    # `--exclude-standard`를 함께 주므로 .gitignore 대상(산출물, step*.py 등)은 여전히
    # 빠진다. `test_schema_hygiene.py` §6-B가 쓰는 방식과 같다.
    def _git(*args):
        try:
            r = subprocess.run(["git"] + list(args), cwd=root,
                               capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.SubprocessError):
            return None
        if r.returncode != 0:
            return None
        return [l.strip().replace("\\", "/") for l in r.stdout.splitlines() if l.strip()]

    tracked = _git("ls-files", "*.py")
    untracked = _git("ls-files", "--others", "--exclude-standard", "*.py")
    if tracked is None or untracked is None:
        print("[SKIP] git을 실행할 수 없거나 저장소가 아니다")
        return

    files = sorted(set(tracked) | set(untracked))
    files = [f for f in files if not os.path.basename(f).startswith("test_")]

    # `UPDATE document_queue` / `DELETE FROM document_queue` 로 시작하는 문장을 잡는다.
    # 인접 문자열 리터럴로 쪼개져 있어도 원본 소스를 그대로 읽으므로 이어서 보인다.
    START = re.compile(r'(?is)\b(UPDATE\s+document_queue|DELETE\s+FROM\s+document_queue)\b')

    violations = []
    scanned = 0
    for rel in files:
        path = os.path.join(root, rel.replace("/", os.sep))
        try:
            # utf-8-sig로 읽는다 — 이 저장소의 소스 68개에 UTF-8 BOM이 있고, `utf-8`로
            # 읽으면 BOM이 U+FEFF로 남는다. 지금은 정규식 기반이라 깨지지 않지만,
            # 나중에 이 검사를 AST로 바꾸면 `ast.parse()`가 SyntaxError를 내고 **검사한
            # 척하면서 절반을 빼먹는다**(2026-08-17 Sprint 167에 내 감사 스크립트가 실제로
            # 프로덕션 77개 중 40개를 그렇게 건너뛰고 있었다). 저장소 규약은 utf-8-sig다
            # (`test_console_encoding.py` / `test_crawl_exit_code.py` 등 전부 그렇다).
            with open(path, encoding="utf-8-sig", errors="replace") as fh:
                src = fh.read()
        except OSError:
            continue
        for m in START.finditer(src):
            scanned += 1
            # SQL 문장 **자체**만 본다. 고정 길이 창으로 자르면 뒤따르는 파라미터나
            # logger 호출까지 딸려 들어와 오탐이 난다(실제로 `storage/database.py`의
            # `WHERE id = ?` 문장이 7줄 뒤 logger의 case_no 때문에 위반으로 잡혔다).
            window = _sql_literal_at(src, m.start())
            if "case_no" not in window:
                continue          # id 등 다른 키로 좁힌 문장은 대상이 아니다
            if re.search(r"court_code|court_name", window):
                continue          # 법원이 들어 있으면 정상
            line = src[:m.start()].count("\n") + 1
            violations.append("%s:%d  %s" % (rel, line, " ".join(window.split())[:90]))

    if violations:
        print("   ★ 법원 없이 case_no로 document_queue를 쓰는 곳:")
        for v in violations:
            print("      %s" % v)
        print("   사건번호는 법원마다 독립이다. court_code를 WHERE에 추가하라")
    check("document_queue 쓰기 SQL에 법원이 빠진 곳", sorted(violations), [])
    print("   프로덕션 .py %d개(추적+미추적)에서 document_queue 쓰기 문장 %d개 검사"
          % (len(files), scanned))



def test_migrate_reports_actual_changes():
    """법원 값이 바뀌면 `migrate_execute` 가 **무엇이 바뀌었는지** 집계하는가 (Sprint 185).

    ## 왜 필요한가

    `migrate_execute` 의 UPDATE 는 값이 같아도 매번 실행된다. 그래서 `updated_at` 은
    전 행이 같은 값이 되고(2026-08-17 실측: auction_item 1,876행 100%가 2026-08-12),
    물건 단위 변경 이력 테이블도 없다. 결과적으로 **"오늘 어떤 물건의 기일/최저가/상태가
    바뀌었나"를 아무도 답할 수 없었다.**

    법원 자료는 절차 진행에 따라 계속 바뀐다 — 유찰되면 기일이 다시 잡히고 최저가가
    내려간다. 그 사실을 관측하지 못하면 재수집도 알림도 숫자로 정할 수 없다.

    Sprint 185가 **UPDATE 동작은 그대로 두고 집계만** 추가했다. 이 검사는 그 관측이
    (a) 실제 변경을 잡고 (b) 변경이 없을 때 0을 보고하는지 고정한다. 둘 다 필요하다 —
    항상 0이면 관측이 죽은 것이고, 항상 N이면 "매번 다 바뀐다"는 잘못된 신호다.

    실제 auction.db 는 쓰지 않는다 — 임시 사본에서만 돌린다.
    """
    print("\n--- 8. migrate_execute 가 실제 변경을 관측하는가 (Sprint 185) ---")
    import sqlite3
    import importlib
    import migrate_execute

    real_path = dbmod.DB_PATH
    tmp_dir = tempfile.mkdtemp(prefix="kokchal_chg_")
    tmp_db = os.path.join(tmp_dir, "scratch.db")
    shutil.copy2(real_path, tmp_db)
    dbmod.DB_PATH = tmp_db
    try:
        importlib.reload(migrate_execute)

        conn = sqlite3.connect(tmp_db)
        conn.row_factory = sqlite3.Row
        target = conn.execute(
            "SELECT court_code, case_no, item_no, auction_date, minimum_bid_price, status"
            " FROM auction LIMIT 1").fetchone()
        _check_true("대조 대상 물건을 찾았다", target is not None, None)
        if target is None:
            return

        # (1) 아무것도 바꾸지 않고 한 번 돌린다 -> 변경 0건이어야 한다.
        migrate_execute.execute()
        base = dict(migrate_execute.LAST_FIELD_CHANGES)
        check("변경이 없으면 관측도 0건", base, {})

        # (2) 크롤러 원본(auction)의 값을 바꾼다 = 법원에서 기일/최저가가 움직인 상황.
        new_date, new_price = "2099-12-31", 12345
        conn.execute(
            "UPDATE auction SET auction_date=?, minimum_bid_price=?"
            " WHERE court_code=? AND case_no=? AND item_no=?",
            (new_date, new_price, target["court_code"], target["case_no"], target["item_no"]))
        conn.commit()

        migrate_execute.execute()
        seen = dict(migrate_execute.LAST_FIELD_CHANGES)
        check("기일 변경을 잡는다", seen.get("auction_date"), 1)
        check("최저가 변경을 잡는다", seen.get("minimum_bid_price"), 1)
        _check_true("바뀌지 않은 필드는 세지 않는다", "appraisal_price" not in seen, seen)

        # (3) 변경이 auction_item 까지 전파됐는가 — 관측만 하고 반영이 안 되면 무의미하다.
        after = conn.execute("""
            SELECT ai.auction_date, ai.minimum_bid_price FROM auction_item ai
            JOIN auction_case ac ON ac.id = ai.case_id
            WHERE ac.court_code=? AND ai.case_no=? AND ai.item_no=?""",
            (target["court_code"], target["case_no"], target["item_no"])).fetchone()
        check("전파: 기일", after["auction_date"], new_date)
        check("전파: 최저가", int(after["minimum_bid_price"]), new_price)
        conn.close()
    finally:
        dbmod.DB_PATH = real_path
        shutil.rmtree(tmp_dir, ignore_errors=True)


def run():
    test_real_db_integrity_invariants()
    test_document_queue_writes_are_court_scoped()
    test_cross_court_upsert_safety()
    test_upsert_partial_failure_isolation()
    test_get_stats_contract()
    test_cross_court_migrate_safety()
    test_migrate_exit_code_contract()
    test_dryrun_predicts_what_execute_does()
    test_migrate_reports_actual_changes()

    print("\n" + "=" * 55)
    if failures:
        print("FAILED (%d): %s" % (len(failures), ", ".join(failures)))
        return 1
    print("ALL TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(run())
