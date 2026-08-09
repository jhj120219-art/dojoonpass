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


def run():
    test_real_db_integrity_invariants()
    test_cross_court_upsert_safety()

    print("\n" + "=" * 55)
    if failures:
        print("FAILED (%d): %s" % (len(failures), ", ".join(failures)))
        return 1
    print("ALL TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(run())
