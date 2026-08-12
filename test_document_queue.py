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


def test_reset_stale_queue():
    """`reset_stale_queue()` — Worker 비정상 종료 복구 경로 (2026-08-12 Sprint 61 신설).

    `doc_worker.py`가 기동 시 가장 먼저 부르는 함수인데 그동안 **직접 검사가 0건**이었다
    (`test_pipeline_integrity.py`는 "지금 DB에 정체된 행이 없다"는 결과만 볼 뿐,
    회수 로직 자체가 동작하는지는 확인하지 않는다).

    가장 중요한 것은 회수보다 **회수하지 않아야 할 것을 건드리지 않는 것**이다 —
    지금 돌고 있는 Worker의 in_progress 행을 pending으로 되돌리면 같은 문서를 두 프로세스가
    동시에 수집한다(중복 수집).
    """
    print("\n--- 6. reset_stale_queue: 비정상 종료 회수 (Sprint 61) ---")
    import storage.database as dbmod

    d, conn = make_db()
    real_path = dbmod.DB_PATH
    try:
        rows = [
            # (label, status, last_attempt_at, retry_count)
            ("stale_in_progress", "in_progress", "-30 minutes", 1),
            ("live_in_progress", "in_progress", "-1 minutes", 1),
            ("old_failed", "failed", "-2 days", 3),
            ("recent_failed", "failed", "-1 hours", 3),
            ("skipped_expired", "SKIPPED_EXPIRED", "-2 days", 0),
            ("done_row", "done", "-2 days", 0),
            ("pending_row", "pending", None, 0),
        ]
        for i, (label, status, ago, retry) in enumerate(rows, start=1):
            conn.execute(
                "INSERT INTO document_queue (court_code, case_no, item_no, doc_type,"
                " priority, auction_date, status, retry_count, enqueued_at, last_attempt_at)"
                " VALUES (?,?,?,?,3,'2099-01-01',?,?, '2026-08-11T00:00:00',"
                "         %s)" % ("NULL" if ago is None else "datetime('now', ?)"),
                (("B000210", label, str(i), "spec", status, retry)
                 if ago is None else ("B000210", label, str(i), "spec", status, retry, ago)),
            )
        conn.commit()
        conn.close()

        dbmod.DB_PATH = os.path.join(d, "t.db")
        dbmod.reset_stale_queue()

        check_conn = sqlite3.connect(dbmod.DB_PATH)
        check_conn.row_factory = sqlite3.Row
        after = {r["case_no"]: r for r in
                 check_conn.execute("SELECT case_no, status, retry_count FROM document_queue")}
        check_conn.close()

        # 회수되어야 하는 것
        check("죽은 Worker의 in_progress는 pending으로 회수", after["stale_in_progress"]["status"], "pending")
        check("하루 지난 failed는 pending으로 회수", after["old_failed"]["status"], "pending")
        check("회수된 failed는 retry_count가 0으로 초기화", after["old_failed"]["retry_count"], 0)

        # 절대 건드리면 안 되는 것 (건드리면 중복 수집/재시도 폭주로 이어진다)
        check("살아있는 Worker의 in_progress는 그대로", after["live_in_progress"]["status"], "in_progress")
        check("최근 failed는 재시도 간격 전이라 그대로", after["recent_failed"]["status"], "failed")
        check("SKIPPED_EXPIRED는 회수 대상이 아니다", after["skipped_expired"]["status"], "SKIPPED_EXPIRED")
        check("done은 절대 되돌리지 않는다", after["done_row"]["status"], "done")
        check("pending은 그대로", after["pending_row"]["status"], "pending")
    finally:
        dbmod.DB_PATH = real_path
        shutil.rmtree(d, ignore_errors=True)


def _seed_queue(conn, rows):
    """(case_no, item_no, doc_type, status, priority, auction_date, retry, last_attempt_sql)"""
    for case_no, item_no, doc_type, status, prio, adate, retry, last in rows:
        conn.execute(
            "INSERT INTO document_queue (court_code, case_no, item_no, doc_type, priority,"
            " auction_date, status, retry_count, enqueued_at, last_attempt_at)"
            " VALUES ('B000210',?,?,?,?,?,?,?, '2026-08-11T00:00:00', %s)"
            % ("NULL" if last is None else last),
            (case_no, item_no, doc_type, prio, adate, status, retry))
    conn.commit()


def test_claim_next_queue_item():
    """`claim_next_queue_item()` — Worker가 큐에서 일감을 집는 유일한 경로.

    2026-08-12 Sprint 63 신설. 이 함수는 **검사가 0건**이었다. pending -> in_progress
    원자적 전이와 재시도 간격을 담당하는, 크롤러 동시성의 핵심인데도 그랬다.
    """
    print("\n--- 7. claim_next_queue_item: 선택 규칙 (Sprint 63) ---")
    import storage.database as dbmod

    d, conn = make_db()
    real = dbmod.DB_PATH
    try:
        _seed_queue(conn, [
            # 우선순위가 낮은 숫자가 먼저, 같은 우선순위면 기일이 빠른 것이 먼저
            ("case-prio3", "1", "spec", "pending", 3, "2099-01-01", 0, None),
            ("case-prio1", "1", "spec", "pending", 1, "2099-12-31", 0, None),
            ("case-prio1-early", "1", "spec", "pending", 1, "2099-01-01", 0, None),
            # 방금 시도한 건은 재시도 간격(30분) 전이라 집으면 안 된다
            ("case-recent", "1", "spec", "pending", 0, "2050-01-01", 1,
             "datetime('now','-1 minutes')"),
            # 집으면 안 되는 상태들
            ("case-done", "1", "spec", "done", 0, "2050-01-01", 0, None),
            ("case-failed", "1", "spec", "failed", 0, "2050-01-01", 3, None),
            ("case-skip", "1", "spec", "SKIPPED_EXPIRED", 0, "2050-01-01", 0, None),
            ("case-inprog", "1", "spec", "in_progress", 0, "2050-01-01", 0, None),
        ])
        conn.close()
        dbmod.DB_PATH = os.path.join(d, "t.db")

        got = dbmod.claim_next_queue_item()
        check_true("일감을 집는다", got is not None, "pending이 있는데 None을 반환했습니다")
        # 우선순위 1 중에서 기일이 빠른 쪽
        check("우선순위 ASC + 기일 ASC 순으로 집는다", got["case_no"], "case-prio1-early")

        c = sqlite3.connect(dbmod.DB_PATH)
        c.row_factory = sqlite3.Row
        row = c.execute("SELECT status, last_attempt_at FROM document_queue WHERE case_no=?",
                        ("case-prio1-early",)).fetchone()
        check("집은 항목은 in_progress가 된다", row["status"], "in_progress")
        check_true("last_attempt_at이 기록된다", bool(row["last_attempt_at"]))

        # 두 번째 호출은 남은 우선순위 1을 집는다
        check("다음 호출은 그다음 우선순위를 집는다",
              dbmod.claim_next_queue_item()["case_no"], "case-prio1")
        check("그다음은 우선순위 3", dbmod.claim_next_queue_item()["case_no"], "case-prio3")

        # 남은 것은 전부 집으면 안 되는 상태 + 재시도 간격 전
        check("더 집을 것이 없으면 None", dbmod.claim_next_queue_item(), None)

        # 재시도 간격이 지나면 다시 집힌다
        c.execute("UPDATE document_queue SET last_attempt_at=datetime('now','-%d minutes')"
                  " WHERE case_no='case-recent'" % (dbmod.RETRY_INTERVAL_MINUTES + 5))
        c.commit()
        c.close()
        again = dbmod.claim_next_queue_item()
        check("재시도 간격이 지나면 다시 집힌다", again["case_no"] if again else None, "case-recent")
    finally:
        dbmod.DB_PATH = real
        shutil.rmtree(d, ignore_errors=True)


def test_claim_is_atomic_under_concurrency():
    """동시에 여러 Worker가 집어도 같은 일감을 두 번 주지 않는가.

    같은 문서를 두 프로세스가 동시에 수집하면 중복 수집 + 임시파일 충돌이 난다.
    `claim_next_queue_item()`은 `UPDATE ... WHERE status='pending'` + rowcount로 이를
    막는데, 그 보호가 실제로 동작하는지 **실스레드로** 확인한 적이 없었다.
    """
    print("\n--- 8. claim_next_queue_item: 동시 클레임 (Sprint 63) ---")
    import threading
    import storage.database as dbmod

    d, conn = make_db()
    real = dbmod.DB_PATH
    try:
        n_items = 12
        _seed_queue(conn, [("case-%02d" % i, "1", "spec", "pending", 1, "2099-01-01", 0, None)
                           for i in range(n_items)])
        conn.close()
        dbmod.DB_PATH = os.path.join(d, "t.db")

        claimed, errors = [], []
        lock = threading.Lock()

        def worker():
            try:
                for _ in range(n_items):
                    got = dbmod.claim_next_queue_item()
                    if got is None:
                        break
                    with lock:
                        claimed.append(got["id"])
            except Exception as e:  # noqa: BLE001 - 실패 자체를 검사 대상으로 삼는다
                with lock:
                    errors.append(repr(e))

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=60)

        check("동시 클레임 중 예외 없음", errors, [])
        check("같은 일감을 두 번 주지 않는다(중복 0)", len(claimed) - len(set(claimed)), 0)
        check("모든 일감이 정확히 한 번씩 배분된다", sorted(set(claimed)) == sorted(claimed) and
              len(claimed), n_items)

        c = sqlite3.connect(dbmod.DB_PATH)
        left = c.execute("SELECT COUNT(*) FROM document_queue WHERE status='pending'").fetchone()[0]
        inprog = c.execute("SELECT COUNT(*) FROM document_queue WHERE status='in_progress'").fetchone()[0]
        c.close()
        check("pending이 남지 않는다", left, 0)
        check("전부 in_progress로 전이", inprog, n_items)
    finally:
        dbmod.DB_PATH = real
        shutil.rmtree(d, ignore_errors=True)


def test_mark_queue_skipped_expired():
    """기일이 지난 항목은 실패가 아니라 '대상 아님'으로 기록된다."""
    print("\n--- 9. mark_queue_skipped_expired (Sprint 63) ---")
    import storage.database as dbmod

    d, conn = make_db()
    real = dbmod.DB_PATH
    try:
        _seed_queue(conn, [("case-old", "1", "spec", "in_progress", 1, "2020-01-01", 1, None)])
        qid = conn.execute("SELECT id FROM document_queue WHERE case_no='case-old'").fetchone()[0]
        conn.close()
        dbmod.DB_PATH = os.path.join(d, "t.db")

        dbmod.mark_queue_skipped_expired(qid, "B000210", "case-old", "1", "spec", "2020-01-01")

        c = sqlite3.connect(dbmod.DB_PATH)
        c.row_factory = sqlite3.Row
        row = c.execute("SELECT * FROM document_queue WHERE id=?", (qid,)).fetchone()
        c.close()
        check("상태가 SKIPPED_EXPIRED", row["status"], "SKIPPED_EXPIRED")
        # 실패가 아니므로 재시도 횟수를 소모시키면 안 된다 — 소모시키면 나중에 기일이
        # 갱신돼 다시 대상이 됐을 때 남은 재시도가 부족해진다.
        check("retry_count를 소모하지 않는다", row["retry_count"], 1)
        check_true("last_attempt_at을 남긴다", bool(row["last_attempt_at"]))
    finally:
        dbmod.DB_PATH = real
        shutil.rmtree(d, ignore_errors=True)


def test_calc_priority():
    """매각기일이 가까울수록 우선순위가 높아지는가 (2026-08-12 Sprint 63 신설).

    `refresh_priority.py`(매일 01:50 배치)의 핵심 계산인데 검사가 0건이었다.
    이 값이 틀리면 임박한 물건의 문서가 뒤로 밀려 기일 전에 수집되지 못한다.
    """
    print("\n--- 10. calc_priority: 기일 임박도 (Sprint 63) ---")
    import storage.database as dbmod
    from datetime import datetime as _dt, timedelta as _td

    def after(days):
        return (_dt.now() + _td(days=days)).strftime("%Y-%m-%d")

    check("오늘 기일 -> 최우선(1)", dbmod.calc_priority(after(0)), 1)
    check("내일 기일 -> 최우선(1)", dbmod.calc_priority(after(1)), 1)
    check("3일 뒤 -> 최우선(1)", dbmod.calc_priority(after(3)), 1)
    check("5일 뒤 -> 2순위", dbmod.calc_priority(after(5)), 2)
    check("7일 뒤 -> 2순위", dbmod.calc_priority(after(7)), 2)
    check("10일 뒤 -> 3순위", dbmod.calc_priority(after(10)), 3)
    check("지난 기일도 최우선(1)", dbmod.calc_priority(after(-5)), 1)
    # 값이 없거나 형식이 깨져도 죽지 않고 가장 낮은 우선순위로 떨어져야 한다
    check("빈 값 -> 3", dbmod.calc_priority(""), 3)
    check("None -> 3", dbmod.calc_priority(None), 3)
    check("형식 오류 -> 3", dbmod.calc_priority("2026/08/12"), 3)
    check("쓰레기 값 -> 3", dbmod.calc_priority("nonsense"), 3)


def test_refresh_queue_priority():
    """우선순위 재계산이 pending만 건드리고, **실제로 바뀐 수**를 보고하는가.

    2026-08-12 Sprint 63 — 예전에는 검토한 행 수를 그대로 돌려줘서 배치 로그가 매일 밤
    "재계산 완료: N건"을 남겼다(바뀐 게 0건인 날에도). BUGS #47과 같은 부류의
    "배치 로그가 사실이 아닌 것을 말하는" 문제라 실제 변경 건수를 반환하도록 고쳤다.
    """
    print("\n--- 11. refresh_queue_priority (Sprint 63) ---")
    import storage.database as dbmod
    from datetime import datetime as _dt, timedelta as _td

    def after(days):
        return (_dt.now() + _td(days=days)).strftime("%Y-%m-%d")

    d, conn = make_db()
    real = dbmod.DB_PATH
    try:
        _seed_queue(conn, [
            # 기일이 임박했는데 우선순위가 3으로 낡아 있는 행 -> 1로 올라가야 한다
            ("stale-urgent", "1", "spec", "pending", 3, after(1), 0, None),
            # 이미 올바른 값 -> 바뀌지 않아야 한다
            ("already-ok", "1", "spec", "pending", 3, after(30), 0, None),
            # pending이 아닌 행은 건드리면 안 된다
            ("done-row", "1", "spec", "done", 3, after(1), 0, None),
            ("inprog-row", "1", "spec", "in_progress", 3, after(1), 0, None),
        ])
        conn.close()
        dbmod.DB_PATH = os.path.join(d, "t.db")

        changed = dbmod.refresh_queue_priority()
        check("실제로 바뀐 행 수만 보고한다", changed, 1)

        c = sqlite3.connect(dbmod.DB_PATH)
        c.row_factory = sqlite3.Row
        got = {r["case_no"]: r["priority"]
               for r in c.execute("SELECT case_no, priority FROM document_queue")}
        c.close()
        check("임박한 pending의 우선순위가 올라간다", got["stale-urgent"], 1)
        check("이미 맞는 행은 그대로", got["already-ok"], 3)
        check("done 행은 건드리지 않는다", got["done-row"], 3)
        check("in_progress 행은 건드리지 않는다", got["inprog-row"], 3)

        # 두 번째 실행은 바꿀 것이 없으므로 0이어야 한다(멱등).
        check("변경할 것이 없으면 0을 보고한다", dbmod.refresh_queue_priority(), 0)
    finally:
        dbmod.DB_PATH = real
        shutil.rmtree(d, ignore_errors=True)


def run():
    test_multi_item_case_all_enqueued()
    test_duplicate_still_ignored()
    test_key_dimensions_are_independent()
    test_live_schema_matches()
    test_migration_preserves_rows()
    test_reset_stale_queue()
    test_claim_next_queue_item()
    test_claim_is_atomic_under_concurrency()
    test_mark_queue_skipped_expired()
    test_calc_priority()
    test_refresh_queue_priority()

    print("\n" + "=" * 55)
    if failures:
        print("FAILED (%d): %s" % (len(failures), ", ".join(failures)))
        return 1
    print("ALL TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(run())
