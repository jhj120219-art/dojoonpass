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


def run():
    test_real_db_integrity_invariants()
    test_cross_court_upsert_safety()
    test_upsert_partial_failure_isolation()
    test_get_stats_contract()

    print("\n" + "=" * 55)
    if failures:
        print("FAILED (%d): %s" % (len(failures), ", ".join(failures)))
        return 1
    print("ALL TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(run())
