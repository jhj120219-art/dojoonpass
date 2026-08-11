"""document_queue 적재/상태전이 회귀 테스트 (2026-08-11 Sprint 55 신설).

selenium 없이 실행된다 — `storage.database`만 import한다.
실제 `auction.db`를 건드리지 않도록 **임시 DB 파일**을 만들어 검증한다.

핵심 회귀 (BUGS #48):
    `document_queue`의 UNIQUE에 `item_no`가 빠져 있어서, 한 사건에 물건이 여러 개일 때
    두 번째 물건부터 `INSERT OR IGNORE`에 조용히 삼켜졌다.
    실측(2026-08-11 적용 전): 물건 1,870개 중 716개(38%)가 자기 item_no로 큐에 없었다.

    python test_document_queue.py
"""
import sys
import os
import sqlite3
import tempfile
import shutil

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

ROOT = os.path.dirname(os.path.abspath(__file__))
MIGRATIONS = os.path.join(ROOT, "storage", "migrations")

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


def queue_schema():
    """현재 저장소의 document_queue 정의를 마이그레이션 파일에서 그대로 가져온다.

    테스트 안에 스키마를 손으로 베껴 두면 진짜 스키마가 바뀌어도 테스트는 계속 통과한다
    — 그게 바로 이 버그가 오래 살아남은 방식이다(코드 주석은 item_no가 있다고 했고
    실제 테이블에는 없었다). 그래서 018 마이그레이션 파일을 읽어 쓴다.
    """
    path = os.path.join(MIGRATIONS, "018_document_queue_item_no_unique.sql")
    sql = open(path, encoding="utf-8").read()
    start = sql.index("CREATE TABLE IF NOT EXISTS document_queue_new")
    end = sql.index(";", start) + 1
    return sql[start:end].replace("document_queue_new", "document_queue")


def make_db():
    d = tempfile.mkdtemp(prefix="qa_queue_")
    path = os.path.join(d, "t.db")
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(queue_schema())
    return d, conn


def enqueue(conn, court, case_no, item_no, doc_type):
    """`enqueue_documents()`가 쓰는 것과 **같은** INSERT OR IGNORE 구문."""
    cur = conn.execute("""
        INSERT OR IGNORE INTO document_queue
            (court_code, case_no, item_no, doc_type, priority, auction_date, status, retry_count, enqueued_at)
        VALUES (?, ?, ?, ?, 3, '2099-01-01', 'pending', 0, '2026-08-11T00:00:00')
    """, (court, case_no, item_no, doc_type))
    return cur.rowcount


# ---------------------------------------------------------------------------
def test_multi_item_case_all_enqueued():
    print("\n--- 1. 한 사건의 물건이 여러 개일 때 (BUGS #48 회귀) ---")
    d, conn = make_db()
    try:
        added = 0
        for item_no in ("1", "2", "3"):
            added += enqueue(conn, "B000210", "2024타경3700", item_no, "spec")
        check("물건 3개가 모두 적재된다", added, 3)

        rows = conn.execute(
            "SELECT item_no FROM document_queue WHERE case_no='2024타경3700' ORDER BY item_no"
        ).fetchall()
        check("큐에 남은 item_no", [r["item_no"] for r in rows], ["1", "2", "3"])
    finally:
        conn.close()
        shutil.rmtree(d, ignore_errors=True)


def test_duplicate_still_ignored():
    print("\n--- 2. 진짜 중복은 여전히 무시된다 ---")
    d, conn = make_db()
    try:
        check("최초 적재", enqueue(conn, "B000210", "2024타경1", "1", "spec"), 1)
        check("같은 (법원,사건,물건,문서)는 무시", enqueue(conn, "B000210", "2024타경1", "1", "spec"), 0)
        check("총 1행", conn.execute("SELECT COUNT(*) FROM document_queue").fetchone()[0], 1)
    finally:
        conn.close()
        shutil.rmtree(d, ignore_errors=True)


def test_key_dimensions_are_independent():
    print("\n--- 3. 키의 네 축이 각각 독립적으로 구분된다 ---")
    d, conn = make_db()
    try:
        base = ("B000210", "2024타경1", "1", "spec")
        enqueue(conn, *base)
        check("문서종류가 다르면 별개", enqueue(conn, "B000210", "2024타경1", "1", "status"), 1)
        check("물건번호가 다르면 별개", enqueue(conn, "B000210", "2024타경1", "2", "spec"), 1)
        check("사건번호가 다르면 별개", enqueue(conn, "B000210", "2024타경2", "1", "spec"), 1)
        check("법원이 다르면 별개", enqueue(conn, "B000211", "2024타경1", "1", "spec"), 1)
        check("총 5행", conn.execute("SELECT COUNT(*) FROM document_queue").fetchone()[0], 5)
    finally:
        conn.close()
        shutil.rmtree(d, ignore_errors=True)


def test_live_schema_matches():
    print("\n--- 4. 실제 auction.db의 제약이 실제로 고쳐졌는가 ---")
    db = os.path.join(ROOT, "auction.db")
    if not os.path.exists(db):
        print("[SKIP] auction.db 없음 (fresh clone) — 스키마 검사 생략")
        return
    conn = sqlite3.connect("file:%s?mode=ro" % db.replace("?", "%3f"), uri=True)
    try:
        sql = conn.execute(
            "SELECT sql FROM sqlite_master WHERE name='document_queue'").fetchone()[0]
        unique = [ln.strip() for ln in sql.splitlines() if "UNIQUE" in ln.upper()]
        check_true("UNIQUE에 item_no가 포함된다",
                   any("item_no" in u for u in unique),
                   "실제 제약: %s" % unique)

        # 코드 주석이 말하는 키와 실제 키가 같은가 — 이 둘이 갈라진 것이 버그의 본질이었다.
        src = open(os.path.join(ROOT, "storage", "database.py"), encoding="utf-8-sig").read()
        i = src.index("def enqueue_documents")
        doc = src[i:i + 1200]
        check_true("enqueue_documents 주석의 키가 실제 스키마와 일치한다",
                   ("UNIQUE(court_code, case_no, item_no, doc_type)" in doc)
                   == any("item_no" in u for u in unique),
                   "주석과 스키마가 다시 갈라졌습니다")
    finally:
        conn.close()


def test_migration_preserves_rows():
    print("\n--- 5. 018 마이그레이션이 행을 지우지 않는가 (SQL 정적 검사) ---")
    sql = open(os.path.join(MIGRATIONS, "018_document_queue_item_no_unique.sql"),
               encoding="utf-8").read()
    up = sql.upper()
    check_true("DELETE 문이 없다", "DELETE FROM" not in up, "행 삭제가 포함돼 있습니다")
    check_true("기존 행을 새 테이블로 이관한다",
               "INSERT INTO DOCUMENT_QUEUE_NEW" in up and "FROM DOCUMENT_QUEUE" in up)
    check_true("id를 명시적으로 보존한다",
               "id, court_code" in sql and "SELECT\n    id," in sql,
               "id를 옮기지 않으면 worker가 들고 있던 id가 어긋납니다")
    check_true("인덱스를 재생성한다",
               up.count("CREATE INDEX") >= 2, "DROP TABLE 후 인덱스가 사라집니다")


def run():
    test_multi_item_case_all_enqueued()
    test_duplicate_still_ignored()
    test_key_dimensions_are_independent()
    test_live_schema_matches()
    test_migration_preserves_rows()

    print("\n" + "=" * 55)
    if failures:
        print("FAILED (%d): %s" % (len(failures), ", ".join(failures)))
        return 1
    print("ALL TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(run())
