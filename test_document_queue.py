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
from datetime import datetime, timedelta

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
    sql = open(path, encoding="utf-8-sig").read()
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
        print("[SKIP] auction.db 없음 (fresh clone) ― 스키마 검사 생략")
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
               encoding="utf-8-sig").read()
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
                # ★ 'localtime'이 반드시 있어야 한다. 운영 코드는 last_attempt_at을
                #   파이썬 `datetime.now()`(로컬)로 쓴다. 픽스처만 UTC로 넣으면
                #   한국 기준 9시간 과거의 행을 만들게 되어, "1분 전"이라고 적어 둔 행이
                #   실제로는 "9시간 1분 전"이 된다 — 검사가 의도한 상황을 못 만든다.
                "         %s)" % ("NULL" if ago is None else "datetime('now','localtime', ?)"),
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


def test_reset_stale_queue_recovers_whole_item_batch():
    """`reset_stale_queue()`가 **같은 물건의 여러 doc_type 행**을 전부 회수하는가
    (2026-08-25 신설).

    위 `test_reset_stale_queue()`는 시나리오마다 case_no가 전부 달라 사실상
    "행 1개짜리 물건"만 검사한다. 그런데 `claim_next_item_rows()`(Sprint 236,
    물건 단위 배치)는 **한 물건의 여러 doc_type 행을 한꺼번에** in_progress로
    바꾼다 — 사진/현황조사서/감정평가서 등 3~4행이 같은 물건 아래 동시에 잡힌다.
    그 상태로 프로세스가 죽으면(`main()`의 정상 종료 경로를 전혀 거치지 못하고
    강제 종료되면), 다음 실행이 기동 시 부르는 `reset_stale_queue()` 혼자서
    그 배치 전체를 회수해야 한다.

    `reset_stale_queue()`의 회수 UPDATE는 `WHERE status='in_progress' AND
    last_attempt_at < ...`처럼 **행 단위 집합 연산**이라 물건 단위 개념이 아예
    없다 — 코드를 읽으면 부분 회수가 구조적으로 불가능해 보인다. 그 판단을
    코드 읽기로만 남기지 않고 실제로 심어서 확인한다.
    """
    print("\n--- 6-b. reset_stale_queue: 물건 배치 전체가 회수되는가 (Sprint 신설) ---")
    import storage.database as dbmod

    d, conn = make_db()
    real_path = dbmod.DB_PATH
    try:
        doc_types = ["spec", "status", "appraisal", "image"]
        for doc_type in doc_types:
            conn.execute(
                "INSERT INTO document_queue (court_code, case_no, item_no, doc_type,"
                " priority, auction_date, status, retry_count, enqueued_at, last_attempt_at)"
                " VALUES ('B000210','2025타경999','1',?,3,'2099-01-01','in_progress',0,"
                "         '2026-08-01T00:00:00', datetime('now','localtime','-30 minutes'))",
                (doc_type,))
        conn.commit()
        conn.close()

        dbmod.DB_PATH = os.path.join(d, "t.db")
        dbmod.reset_stale_queue()

        check_conn = sqlite3.connect(dbmod.DB_PATH)
        check_conn.row_factory = sqlite3.Row
        rows = check_conn.execute(
            "SELECT doc_type, status FROM document_queue"
            " WHERE case_no='2025타경999' ORDER BY doc_type").fetchall()
        check_conn.close()

        check_true("검사가 공허하지 않다(배치 4행이 실제로 들어갔다)", len(rows), 4)
        stuck = [r["doc_type"] for r in rows if r["status"] != "pending"]
        check("★ 물건 배치 4행 전부 회수된다(부분 회수 없음)", stuck, [])
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
            # 'localtime' 필수 — 운영 코드가 로컬 시각을 쓰기 때문이다(위 6번 주석 참고)
            ("case-recent", "1", "spec", "pending", 0, "2050-01-01", 1,
             "datetime('now','localtime','-1 minutes')"),
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
        c.execute("UPDATE document_queue SET last_attempt_at="
                  "datetime('now','localtime','-%d minutes')"
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

    # ★★ 2026-08-26 (`docs/BUGS.md` #237) — **위 검사들은 경계에 닿지 않는다.**
    #
    #   경계 변이(`days_left <= 3` -> `< 3`, `<= 7` -> `< 7`)를 넣었더니 **둘 다
    #   살아남았다.** 이유는 이름과 실제 값이 다르기 때문이다.
    #
    #       calc_priority 는 `strptime(auction_date, "%Y-%m-%d")` 로 **자정**을 만들고
    #       `(target - datetime.now()).days` 를 쓴다. now 에는 시각이 붙어 있으므로
    #       timedelta 가 잘려 **days_left = (달력 일수) - 1** 이 된다.
    #
    #   실측(2026-08-26 18:21 기준):
    #
    #       after(3) -> days_left=2   after(7) -> days_left=6    <- 경계가 아니다
    #       after(4) -> days_left=3   after(8) -> days_left=7    <- **여기가 경계다**
    #
    #   즉 "3일 뒤 -> 1" 이라는 이름의 검사는 실제로는 days_left=2 를 보고 있어서,
    #   경계를 한 칸 옮겨도 통과한다. 이름과 검증 내용이 어긋난 자리다.
    #
    #   ★ 제품 동작은 그대로 둔다. `days_left` 의 정의를 바꾸면 큐 정렬이 통째로
    #     달라지는 **정책 변경**이고, 지금 코드가 스스로 일관되지 않다는 근거는 없다.
    #     여기서 할 일은 **경계가 어디인지 정확히 못박는 것**이다.
    check("★ 경계: days_left=3 (달력 4일 뒤) -> 최우선(1)", dbmod.calc_priority(after(4)), 1)
    check("★ 경계 바로 밖: days_left=4 (달력 5일 뒤) -> 2순위", dbmod.calc_priority(after(5)), 2)
    check("★ 경계: days_left=7 (달력 8일 뒤) -> 2순위", dbmod.calc_priority(after(8)), 2)
    check("★ 경계 바로 밖: days_left=8 (달력 9일 뒤) -> 3순위", dbmod.calc_priority(after(9)), 3)

    # 이름이 다시 어긋나지 않도록 **오프셋 자체를 고정한다**.
    # 이 관계가 깨지면(예: 자정 대신 now 기준으로 바뀌면) 위 경계 검사도 함께 옮겨야 한다.
    from datetime import datetime as _dt2
    _target = _dt2.strptime(after(4), "%Y-%m-%d")
    check("★ days_left = 달력일수 - 1 이라는 전제가 유지된다",
          (_target - _dt2.now()).days, 3)
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


# ---------------------------------------------------------------------------
# 12. 유찰 후 재매각 - 새 기일이 큐에 반영되는가 (2026-08-13 Sprint 74 신설)
#
# 한국 경매에서 유찰 후 재매각은 예외가 아니라 일상이다. 그때 같은 (법원, 사건, 물건)에
# **새 매각기일**이 잡힌다. 그런데 `enqueue_documents()`는 `INSERT OR IGNORE`를 쓰고
# UNIQUE는 (court_code, case_no, item_no, doc_type)이라, **이미 행이 있으면 통째로
# 무시**된다. 즉 큐 행은 옛 기일을 그대로 들고 남는다.
#
# 그 다음이 문제다. `doc_worker`의 2차 방어선은 **큐에 저장된 auction_date**를 본다.
#
#     if auction_date and auction_date < today:
#         mark_queue_skipped_expired(...)      # 브라우저 작업 없이 종료
#
# 그래서 기일이 미래로 다시 잡힌 **살아 있는 사건**이, 큐에 남은 옛 날짜 때문에
# "기일 경과"로 판정돼 수집 대상에서 영구히 빠진다.
#
# 실측 (2026-08-13, auction.db) - 실제로 일어나 있었다.
#
#     큐 auction_date != auction_item.auction_date        18행
#     그중 현재 기일이 미래(=재매각으로 살아난 사건)         9행
#     item=1533  큐 2026-07-15 (pending) vs 현재 2026-08-19  <- 6일 뒤 매각인데 죽는다
#     item=502   큐 2026-07-15 (done)    vs 현재 2026-08-19
#     item=505   큐 2026-07-15 (done)    vs 현재 2026-08-19
#
# `refresh_queue_priority()`도 같은 stale 값으로 우선순위를 계산하므로 함께 틀린다.
#
# [수정 범위] 큐 행의 `auction_date`/`priority`를 최신 크롤 값으로 **동기화**한다.
# 상태(status)는 건드리지 않는다 - SKIPPED_EXPIRED/failed/done을 되살릴지는 재수집
# 정책이라 제품 판단이다(docs/roadmap.md 결정 대기). 여기서 고치는 것은 **큐가 자기
# 필드에 사실과 다른 값을 들고 있는 것**뿐이고, 그것만으로 pending 행의 오판은 사라진다.
# ---------------------------------------------------------------------------
def test_relisted_auction_date_is_refreshed():
    print("\n--- 12. 유찰 후 재매각: 새 기일이 큐에 반영된다 (Sprint 74) ---")
    import storage.database as dbmod

    d, conn = make_db()
    real_path = dbmod.DB_PATH
    try:
        # 1차 적재 시점에는 미래였던 기일. 시간이 흘러 지금은 과거다.
        old_date = "2026-07-15"
        # +5일: calc_priority가 3(기본)이 아니라 2를 주는 구간이다.
        # 시드 priority(3)와 달라야 "우선순위도 다시 계산되는가"가 실제로 검증된다
        # (30일로 두면 계산값도 3이라 갱신 누락을 놓친다 - 변이 시험에서 실제로 놓쳤다).
        new_date = (datetime.now() + timedelta(days=5)).strftime("%Y-%m-%d")

        # 2026-08-17 Sprint 144: 'image'(물건 사진)가 넷째 종류로 추가됐다. 이 시드는
        # 아래 주석대로 **모든 종류를 다 넣어야** "신규 적재 0건"이 성립하므로 함께 넣는다.
        _seed_queue(conn, [
            # 네 문서종류를 모두 시드한다 - 그래야 "신규 적재 0건"이 성립해
            # 이 검사가 오직 **기존 행의 갱신**만 보게 된다.
            ("2024타경1533", "1", "spec", "pending", 3, old_date, 0, None),
            ("2024타경1533", "1", "status", "pending", 3, old_date, 0, None),
            ("2024타경1533", "1", "appraisal", "pending", 3, old_date, 0, None),
            ("2024타경1533", "1", "image", "pending", 3, old_date, 0, None),
            # 이미 수집이 끝난 행과 기일경과로 종료된 행도 함께 둔다.
            ("2024타경502", "1", "spec", "done", 3, old_date, 0, None),
            ("2024타경502", "1", "status", "done", 3, old_date, 0, None),
            ("2024타경502", "1", "appraisal", "done", 3, old_date, 0, None),
            ("2024타경502", "1", "image", "done", 3, old_date, 0, None),
            ("2024타경505", "1", "spec", "SKIPPED_EXPIRED", 3, old_date, 0, None),
            ("2024타경505", "1", "status", "SKIPPED_EXPIRED", 3, old_date, 0, None),
            ("2024타경505", "1", "appraisal", "SKIPPED_EXPIRED", 3, old_date, 0, None),
            ("2024타경505", "1", "image", "SKIPPED_EXPIRED", 3, old_date, 0, None),
            # 대조군 — 이쪽은 되살리면 안 된다(#254). 시간이 지나도 성공할 수 없는 항목이
            # 매일 되살아나던 것이 `mark_queue_unsupported()` 가 없앤 문제다.
            ("2024타경777", "1", "spec", "SKIPPED_UNSUPPORTED", 3, old_date, 0, None),
        ])
        conn.close()
        dbmod.DB_PATH = os.path.join(d, "t.db")

        # 재매각으로 새 기일이 잡힌 상태의 크롤 결과를 그대로 넣는다.
        result = dbmod.enqueue_documents([
            {"court_code": "B000210", "case_no": "2024타경1533", "item_no": "1",
             "auction_date": new_date},
            {"court_code": "B000210", "case_no": "2024타경502", "item_no": "1",
             "auction_date": new_date},
            {"court_code": "B000210", "case_no": "2024타경505", "item_no": "1",
             "auction_date": new_date},
            {"court_code": "B000210", "case_no": "2024타경777", "item_no": "1",
             "auction_date": new_date},
        ])

        c = sqlite3.connect(dbmod.DB_PATH)
        c.row_factory = sqlite3.Row

        def row(case_no, doc_type="spec"):
            return c.execute(
                "SELECT * FROM document_queue WHERE case_no=? AND doc_type=?",
                (case_no, doc_type)).fetchone()

        # 중복 적재는 여전히 일어나지 않는다(기존 계약 - BUGS #48).
        check("이미 있는 행을 새로 만들지 않는다",
              c.execute("SELECT COUNT(*) FROM document_queue WHERE case_no='2024타경1533'"
                        ).fetchone()[0], 4)

        # ★ 핵심: 기일이 최신 값으로 갱신된다.
        check("pending 행의 기일이 새 기일로 갱신된다", row("2024타경1533")["auction_date"], new_date)
        check("같은 사건의 다른 문서종류도 갱신된다",
              row("2024타경1533", "status")["auction_date"], new_date)
        check("우선순위도 새 기일 기준으로 다시 계산된다",
              row("2024타경1533")["priority"], dbmod.calc_priority(new_date))
        check_true("우선순위가 시드값(3)에서 실제로 바뀌었다",
                   row("2024타경1533")["priority"] != 3,
                   "계산값이 시드와 같으면 이 검사는 갱신 누락을 잡지 못한다")

        # 상태는 대부분 손대지 않는다 - 재수집 여부는 정책 결정이라 이 수정의 범위가 아니다.
        check("pending은 pending 그대로", row("2024타경1533")["status"], "pending")
        check("done은 되살리지 않는다", row("2024타경502")["status"], "done")
        # ★ 예외는 SKIPPED_EXPIRED 하나다 (2026-08-27, BUGS #254).
        #   그 상태는 "기일이 지나 대상이 아님"이라는 **주장**인데, 새 기일이 미래로
        #   잡힌 지금 그 주장은 사실이 아니다. done/failed 되살리기(=재수집)와 달리
        #   이 행들은 **한 번도 받은 적이 없어** 되살리는 것이 첫 수집이다.
        check("★ SKIPPED_EXPIRED는 되살린다(기일이 다시 잡혔으므로)",
              row("2024타경505")["status"], "pending")
        check("되살릴 때 재시도 예산도 새로 준다",
              row("2024타경505")["retry_count"], 0)
        check("SKIPPED_UNSUPPORTED는 되살리지 않는다(시간이 지나도 성공할 수 없다)",
              row("2024타경777")["status"], "SKIPPED_UNSUPPORTED")
        # 다만 기록된 기일 자체는 사실과 맞아야 한다(운영 조회/통계가 이 값을 본다).
        check("done 행의 기일도 사실과 맞춘다", row("2024타경502")["auction_date"], new_date)
        check("되살린 행의 기일도 새 기일이다",
              row("2024타경505")["auction_date"], new_date)
        check("되살린 행의 우선순위도 새 기일 기준이다",
              row("2024타경505")["priority"], dbmod.calc_priority(new_date))

        # 갱신 건수를 호출부가 알 수 있어야 한다(로그로 추적 가능해야 조용한 실패가 안 된다).
        check_true("반환값에 갱신 건수가 있다", "refreshed" in result, result)
        # 1533(4행) + 502(4행) + 777 의 spec(1행) = 9행이 '기일 갱신'이다.
        # 505 의 4행은 '기일 갱신'이 아니라 **되살리기**로 세어진다(#254) — 두 사건을
        # 한 칸에 합치면 로그가 다시 사실이 아닌 것을 말하게 된다(#47 과 같은 부류).
        check("갱신 건수", result.get("refreshed"), 9)
        check("되살린 건수", result.get("revived_expired"), 4)
        # 777 은 spec 만 시드했으므로 나머지 3종이 새로 들어간다.
        check("신규 적재", result["added"], 3)

        # ★ 결과 확인: 이제 doc_worker의 2차 방어선이 이 행을 죽이지 않는다.
        claimed = dbmod.claim_next_queue_item()
        check_true("일감을 집는다", claimed is not None, "pending이 있는데 None")
        today = datetime.now().strftime("%Y-%m-%d")
        check_true("집은 일감의 기일이 미래다(기일경과로 오판하지 않는다)",
                   claimed["auction_date"] >= today,
                   "claim된 auction_date=%r < today=%r ― doc_worker가 SKIPPED_EXPIRED로 죽인다"
                   % (claimed["auction_date"], today))

        c.close()
    finally:
        dbmod.DB_PATH = real_path
        shutil.rmtree(d, ignore_errors=True)


# ---------------------------------------------------------------------------
# 12-C. 기일이 **이미 최신인데도** SKIPPED_EXPIRED 로 굳은 행 (2026-08-27, BUGS #254)
#
# Sprint 74 의 되살리기는 "기일이 **바뀌었을 때**"만 돌았다. 그런데 운영에서 실제로
# 쌓인 모양은 그게 아니었다 — 날짜는 이미 오늘로 맞춰져 있고 상태만 SKIPPED_EXPIRED 다.
#
#     실측 (2026-08-27 운영 DB)
#       36행: status=SKIPPED_EXPIRED / auction_date=2026-08-27(오늘) / 전부 appraisal
#       같은 물건의 spec/status/image 는 pending — 오늘 함께 수집될 예정
#       document_status 기록 없음 / doc_raw 0행  -> 한 번도 받은 적이 없다
#
# 즉 **오늘 매각이 진행되는 물건의 감정평가서만** 조용히 빠진다. 그리고 날짜가 이미
# 최신이라 "바뀌었을 때만 고친다"로는 **영원히 안 고쳐진다.**
#
# `test_pipeline_integrity.py` 가 상한 1로 잡아 두었고 1 -> 36 으로 늘어 붉어졌다.
# ---------------------------------------------------------------------------
def test_expired_row_with_current_date_is_revived():
    print("\n--- 12-C. 날짜가 이미 최신인 SKIPPED_EXPIRED 도 되살린다 (BUGS #254) ---")
    import storage.database as dbmod

    d, conn = make_db()
    real_path = dbmod.DB_PATH
    try:
        # ★ 핵심: 큐 행의 기일이 **이미 오늘**이다. 바뀔 것이 없다.
        today = datetime.now().strftime("%Y-%m-%d")
        _seed_queue(conn, [
            ("2024타경9001", "1", "spec", "pending", 3, today, 0, None),
            ("2024타경9001", "1", "status", "pending", 3, today, 0, None),
            ("2024타경9001", "1", "image", "pending", 3, today, 0, None),
            # 운영에서 실제로 남아 있던 모양 그대로 — 형제는 pending, 이것만 종결됐다.
            ("2024타경9001", "1", "appraisal", "SKIPPED_EXPIRED", 3, today, 0,
             "'2026-08-26T07:01:23'"),   # 마지막 칸은 **원시 SQL**이다(_seed_queue 참고)
        ])
        conn.close()
        dbmod.DB_PATH = os.path.join(d, "t.db")

        result = dbmod.enqueue_documents([
            {"court_code": "B000210", "case_no": "2024타경9001", "item_no": "1",
             "auction_date": today},
        ])

        c = sqlite3.connect(dbmod.DB_PATH)
        c.row_factory = sqlite3.Row
        appr = c.execute("SELECT * FROM document_queue WHERE case_no='2024타경9001'"
                         " AND doc_type='appraisal'").fetchone()

        check("★ 날짜가 안 바뀌어도 되살린다", appr["status"], "pending")
        check("되살린 건수를 호출부가 알 수 있다", result.get("revived_expired"), 1)
        check("새로 넣은 행은 없다(되살리기지 중복 적재가 아니다)", result["added"], 0)
        check("날짜가 같으므로 '기일 갱신'으로는 세지 않는다", result.get("refreshed"), 0)
        check("행 수는 그대로 4행", c.execute(
            "SELECT COUNT(*) FROM document_queue WHERE case_no='2024타경9001'"
        ).fetchone()[0], 4)

        # ★ 되살린 행을 워커가 실제로 집어 가는가 — 상태만 바꾸고 못 집으면 헛일이다.
        picked = []
        for _ in range(6):
            got = dbmod.claim_next_queue_item()
            if not got:
                break
            picked.append(got["doc_type"])
        check_true("★ 되살린 appraisal 행을 워커가 집어 간다",
                   "appraisal" in picked, "-> 집어 온 것: %s" % picked)

        # 두 번 돌려도 같은 결과여야 한다(멱등) — 이미 pending 이므로 되살릴 것이 없다.
        c.close()
        result2 = dbmod.enqueue_documents([
            {"court_code": "B000210", "case_no": "2024타경9001", "item_no": "1",
             "auction_date": today},
        ])
        check("두 번째 실행에서는 되살릴 것이 없다(멱등)",
              result2.get("revived_expired"), 0)
    finally:
        dbmod.DB_PATH = real_path
        shutil.rmtree(d, ignore_errors=True)


def test_expired_items_are_not_enqueued():
    """1차 방어선 - 매각기일이 지난 사건은 애초에 큐에 넣지 않는다 (2026-08-13 Sprint 84).

    커버리지가 지목했다: `enqueue_documents()`의 `skipped_expired` 분기(364-365행)가
    미커버였다. 이 분기는 `storage/database.py`의 주석이 **1차 방어선**이라 부르는 것이고,
    doc_worker의 2차 방어선(claim 후 기일 재확인)과 짝을 이룬다.

    실측 근거가 주석에 이미 적혀 있다 - 매각기일이 지난 사건은 법원경매정보 사이트의
    사건번호 직접검색으로도 조회되지 않아 **수집 자체가 불가능**하다. 그래서 큐에 넣는
    단계에서 걸러 불필요한 브라우저 작업과 재시도를 아예 만들지 않는다.

    이 분기가 사라지면 만료 사건이 큐에 쌓이고, 2차 방어선이 대신 걸러 주기는 하지만
    그때는 이미 claim/retry 사이클을 소모한 뒤다.
    """
    print("\n--- 12-B. 만료 사건은 큐에 넣지 않는다 (1차 방어선) ---")
    import storage.database as dbmod

    d, conn = make_db()
    real_path = dbmod.DB_PATH
    try:
        conn.close()
        dbmod.DB_PATH = os.path.join(d, "t.db")

        past = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        today = datetime.now().strftime("%Y-%m-%d")
        future = (datetime.now() + timedelta(days=10)).strftime("%Y-%m-%d")

        result = dbmod.enqueue_documents([
            {"court_code": "B000210", "case_no": "expired", "item_no": "1",
             "auction_date": past},
            {"court_code": "B000210", "case_no": "today", "item_no": "1",
             "auction_date": today},
            {"court_code": "B000210", "case_no": "future", "item_no": "1",
             "auction_date": future},
        ])

        c = sqlite3.connect(dbmod.DB_PATH)
        c.row_factory = sqlite3.Row
        try:
            cases = sorted({r["case_no"] for r in c.execute(
                "SELECT case_no FROM document_queue")})
        finally:
            c.close()

        check("만료 사건은 큐에 없다", cases, ["future", "today"])
        # 오늘이 기일인 사건은 **넣어야 한다** — 아직 매각 전이다(D7 경계와 같은 규칙).
        check_true("오늘이 기일인 사건은 큐에 들어간다", "today" in cases, cases)
        # 2026-08-17 Sprint 144: 문서 종류가 3개 -> 4개(spec/status/appraisal/image).
        check("적재는 2건 x 4자산 = 8", result["added"], 8)
        # 몇 건을 걸렀는지 호출부가 알 수 있어야 한다 — 조용히 사라지면 큐가 비어 있는
        # 이유를 나중에 추적할 수 없다(Sprint 54가 없앤 "실패 은폐"와 같은 이유).
        check("걸러낸 건수를 보고한다", result["skipped_expired"], 1)

        # 기일이 아예 없는 사건은 거르지 않는다(모른다고 버리지 않는다).
        result2 = dbmod.enqueue_documents([
            {"court_code": "B000210", "case_no": "no-date", "item_no": "1",
             "auction_date": ""},
        ])
        check("기일이 없으면 거르지 않는다", result2["skipped_expired"], 0)
        check("기일 없는 사건도 적재된다", result2["added"], 4)
    finally:
        dbmod.DB_PATH = real_path
        shutil.rmtree(d, ignore_errors=True)


def test_relist_does_not_touch_unrelated_rows():
    print("\n--- 13. 기일 동기화가 무관한 행을 건드리지 않는다 ---")
    import storage.database as dbmod

    d, conn = make_db()
    real_path = dbmod.DB_PATH
    try:
        new_date = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")
        _seed_queue(conn, [
            ("target", "1", "spec", "pending", 3, "2026-07-15", 0, None),
            ("other-case", "1", "spec", "pending", 3, "2026-07-15", 0, None),
            ("target", "2", "spec", "pending", 3, "2026-07-15", 0, None),   # 다른 물건번호
        ])
        conn.close()
        dbmod.DB_PATH = os.path.join(d, "t.db")

        dbmod.enqueue_documents([
            {"court_code": "B000210", "case_no": "target", "item_no": "1",
             "auction_date": new_date},
        ])

        c = sqlite3.connect(dbmod.DB_PATH)
        c.row_factory = sqlite3.Row
        get = lambda case_no, item_no: c.execute(
            "SELECT auction_date FROM document_queue WHERE case_no=? AND item_no=? AND doc_type='spec'",
            (case_no, item_no)).fetchone()["auction_date"]
        check("대상 행만 갱신된다", get("target", "1"), new_date)
        check("다른 사건은 그대로", get("other-case", "1"), "2026-07-15")
        check("같은 사건이라도 다른 물건번호는 그대로", get("target", "2"), "2026-07-15")
        c.close()
    finally:
        dbmod.DB_PATH = real_path
        shutil.rmtree(d, ignore_errors=True)


# ---------------------------------------------------------------------------
# 14. get_doc_button_id - Worker가 모든 항목에서 부르는 관문 (2026-08-13 Sprint 75 신설)
#
# `doc_worker.py`는 큐에서 집은 항목마다 이 함수를 부르고, None이면 브라우저를 열지 않고
# 바로 실패 처리한다. **모든 문서 수집이 이 한 줄을 통과**하는데 검사가 0건이었다.
#
#     btn_id = get_doc_button_id(doc_type, item_no)
#     if not btn_id:
#         mark_queue_failed(...)   # 브라우저 작업 없이 종료
#
# 핵심 규약은 "현황조사서는 item_no=1 이외의 버튼 id가 DOM으로 확인된 적이 없으므로
# None을 돌려 명시적으로 미지원을 알린다"는 것이다(추측으로 셀렉터를 만들지 않는다).
#
# 실측 (2026-08-13, auction.db)
#     이 함수가 None을 주는 큐 행   109 (전체 3,498의 3%)
#     그중 아직 pending             103   -> 재시도를 소진한 뒤 document_status=FAILED가 된다
#     현재 FAILED 3행 중 1행이 이 경로(item=14, item_no=7, STATUS)
#
# 화면에는 "수집실패"로 뜬다. 시도조차 못 한 것과 실패한 것이 같은 문구인데,
# **표시 문구를 어떻게 나눌지는 제품 판단**이라 여기서 정하지 않는다(docs/roadmap.md).
#
# 한편 "성공할 수 없으니 큐에 넣지 말자"는 방향은 **오히려 나쁘다**. 큐에 없으면
# document_status가 COLLECTING("수집중")에 영원히 머문다 - BUGS #69와 똑같은 상태가 된다.
# 지금처럼 빠르게 실패해 FAILED로 남기는 쪽이 더 정직하다. 그래서 동작을 바꾸지 않고
# 규약만 고정한다.
# ---------------------------------------------------------------------------
def test_get_doc_button_id_contract():
    print("\n--- 14. get_doc_button_id 규약 (Sprint 75) ---")
    from config.settings import get_doc_button_id

    # 지원되는 조합: 물건번호가 id 뒤에 붙는다.
    for doc_type, item_no in (("spec", "1"), ("spec", "2"), ("spec", "7"),
                              ("appraisal", "1"), ("appraisal", "2"), ("appraisal", "7")):
        btn = get_doc_button_id(doc_type, item_no)
        check_true("%s/item_no=%s 는 버튼 id가 있다" % (doc_type, item_no), bool(btn), btn)
        check_true("%s/item_no=%s 의 id가 물건번호로 끝난다" % (doc_type, item_no),
                   str(btn).endswith(item_no), btn)

    # 같은 문서종류라도 물건번호가 다르면 **다른 버튼**이어야 한다
    # (여기가 같아지면 2번 물건을 수집하면서 1번 문서를 저장한다).
    check_true("spec: 물건번호가 다르면 버튼도 다르다",
               get_doc_button_id("spec", "1") != get_doc_button_id("spec", "2"))
    check_true("appraisal: 물건번호가 다르면 버튼도 다르다",
               get_doc_button_id("appraisal", "1") != get_doc_button_id("appraisal", "2"))
    # 문서종류가 다르면 당연히 달라야 한다.
    check_true("spec과 appraisal의 버튼이 다르다",
               get_doc_button_id("spec", "1") != get_doc_button_id("appraisal", "1"))

    # 현황조사서: **물건번호와 무관하게 같은 버튼**이다 (2026-08-17 Sprint 144+ DOM 실측).
    #
    # 예전 규약은 "item_no != '1'이면 None(미지원)"이었고, 그 근거는 "물건번호가 2 이상일
    # 때의 버튼 id를 DOM으로 확인한 적이 없다"였다. 이제 확인했다 — 물건번호 2인 상세페이지
    # 2건(2025타경311, 2023타경2726)에서 `..._btn_curstExmndcTop`이 **번호 없이 그대로**
    # 존재하고 표시된다. 명세서/평가서만 번호가 붙는다(`...Spcfc2`, `...aeeWevl2`).
    # 오버레이 내용도 사건의 모든 물건을 한 문서에 담고 있다(집행관이 사건 단위로 작성).
    #
    # 왜 중요한가 — 옛 규약은 `auction_item` 1,876건 중 물건번호가 1이 아닌 **629건(33.5%)**
    # 의 현황조사서를 영구히 수집 불가로 만들고 있었다.
    check_true("status/item_no=1 은 지원", bool(get_doc_button_id("status", "1")))
    for item_no in ("2", "3", "7", "12"):
        check("status/item_no=%s 도 같은 버튼(사건 단위 문서)" % item_no,
              get_doc_button_id("status", item_no), get_doc_button_id("status", "1"))
    check_true("status 버튼 id에는 물건번호가 붙지 않는다",
               not get_doc_button_id("status", "2").endswith("2"),
               get_doc_button_id("status", "2"))

    # 물건번호 미지정은 "1"로 본다(큐에 item_no가 비어 들어오는 경우 대비).
    for doc_type in ("spec", "status", "appraisal"):
        check("%s: item_no 생략은 1과 같다" % doc_type,
              get_doc_button_id(doc_type, None), get_doc_button_id(doc_type, "1"))
        check("%s: item_no 빈 문자열은 1과 같다" % doc_type,
              get_doc_button_id(doc_type, ""), get_doc_button_id(doc_type, "1"))
        check("%s: item_no 공백은 다듬는다" % doc_type,
              get_doc_button_id(doc_type, " 1 "), get_doc_button_id(doc_type, "1"))

    # 모르는 문서종류는 None. 그럴듯한 id를 지어내지 않는다.
    for doc_type in ("registry", "", "unknown"):
        check("모르는 문서종류(%r)는 None" % doc_type, get_doc_button_id(doc_type, "1"), None)

    # ★ 대소문자: 큐는 소문자로 저장하지만 document_status는 대문자다.
    #   이 함수는 **소문자만** 받는다. 대문자를 넘기면 조용히 None이 되어
    #   "미지원"으로 오인된다 - doc_paths.doc_exists()가 Sprint 73에 겪은 것과 같은 함정이다.
    #   호출부(doc_worker)는 큐 값(소문자)을 그대로 넘기므로 현재 문제는 없다.
    #   여기서는 그 전제를 고정해 둔다 - 호출부가 바뀌면 이 검사가 먼저 실패한다.
    check("대문자 SPEC은 None (소문자 전용 규약)", get_doc_button_id("SPEC", "1"), None)
    src = open(os.path.join(ROOT, "doc_worker.py"), encoding="utf-8-sig").read()
    check_true("doc_worker는 큐의 doc_type을 그대로 넘긴다(소문자 유지)",
               "get_doc_button_id(doc_type, item_no)" in src,
               "호출 형태가 바뀌었다면 대소문자 전제를 다시 확인해야 한다")

    # 큐에 실제로 들어 있는 doc_type 값이 이 함수가 아는 값과 같은지 확인한다.
    #
    # 예외 하나: 'image'는 **버튼이 없어서** 원래부터 None이 정상이다(2026-08-17
    # Sprint 144). 사진은 클릭할 버튼이 아니라 상세페이지 DOM에 이미 있는 캐러셀을
    # 읽으므로, `doc_worker.py`가 `needs_button = doc_type != "image"`로 이 종류만
    # 버튼 id 조회 자체를 건너뛴다. 목록에서 빼는 게 아니라 **왜 아는 값인데도
    # None이 맞는지**를 이 함수 자체가 구분 못 하므로, 여기서만 걸러낸다.
    #
    # 2026-08-18 Sprint 188 실측: 이 검사가 원래 `image`도 "모르는 값"으로 잡아 FAIL했다
    # — `document_queue`에 `image` 행이 실제로 생긴 것을 이 검사가 처음 마주친 것이다
    # (교훈은 test_pipeline_integrity.py의 같은 원인 수정과 동일).
    db = os.path.join(ROOT, "auction.db")
    if os.path.exists(db):
        c = sqlite3.connect("file:%s?mode=ro" % db.replace("?", "%3f"), uri=True)
        try:
            types = {r[0] for r in c.execute("SELECT DISTINCT doc_type FROM document_queue")}
        finally:
            c.close()
        BUTTONLESS_DOC_TYPES = {"image"}
        unknown = sorted(t for t in types - BUTTONLESS_DOC_TYPES if get_doc_button_id(t, "1") is None)
        check("큐의 doc_type 중 이 함수가 모르는 값 없음 (버튼 없는 종류 제외)", unknown, [])
    else:
        print("[SKIP] auction.db 없음 (fresh clone)")

    # config/courts.py:get_court_by_code - 커버리지 56%였던 공개 헬퍼(이 함수만 미커버).
    # 크롤러가 법원 코드로 CourtInfo를 찾는 유일한 경로다. 모르는 코드에 조용히 None을
    # 돌려주면 그 뒤 select_court()가 엉뚱한 법원을 훑게 되므로, 명시적으로 실패해야 한다.
    from config.courts import get_court_by_code, ALL_COURTS
    sample = ALL_COURTS[0]
    got = get_court_by_code(sample.code)
    check("알려진 법원 코드로 찾을 수 있다", got.code, sample.code)
    check("찾은 값의 이름도 같다", got.name, sample.name)
    raised = False
    try:
        get_court_by_code("NOT-A-COURT")
    except ValueError:
        raised = True
    check("모르는 코드는 조용히 None이 아니라 ValueError", raised, True)


# ---------------------------------------------------------------------------
# 15. upsert_batch - 일일 크롤의 유일한 DB 쓰기 경로 (2026-08-13 Sprint 84 신설)
#
# 커버리지가 지목했다: `storage/database.py`의 254-257행(전체 롤백 경로)이 미커버였다.
# `upsert_batch()`는 `mvp_scraper.py:107`이 매일 부르는 **크롤 결과를 DB에 넣는 유일한
# 함수**인데, 실패 처리 두 갈래가 한 번도 실행된 적이 없었다.
#
# 두 갈래의 의미가 완전히 다르다.
#
#   행 단위 실패(안쪽 except)   그 행만 건너뛰고 failed++ -> **나머지 행은 그대로 저장된다**
#                              법원 한 곳의 값 하나가 깨졌다고 그날 수집분 전체를 잃으면 안 된다
#   커밋 실패(바깥 except)      전부 rollback 하고 **예외를 다시 던진다**
#                              여기서 삼키면 mvp_scraper가 성공으로 보고한다 - Sprint 54가
#                              없앤 "실패 은폐"가 되살아나는 자리다
#
# 후자가 특히 중요하다. 조용히 0건 저장하고 성공으로 끝나면, 크롤이 멈춘 사실을
# 아무도 모른 채 며칠이 지난다(2026-08-03~11에 실제로 일어났던 사고).
# ---------------------------------------------------------------------------
def test_upsert_batch_partial_and_total_failure():
    print("\n--- 15. upsert_batch 실패 처리 (Sprint 84) ---")
    import storage.database as dbmod

    d = tempfile.mkdtemp(prefix="qa_upsert_")
    real_path = dbmod.DB_PATH
    try:
        dbmod.DB_PATH = os.path.join(d, "t.db")
        dbmod.init_db()

        def row(case_no, **over):
            base = dict(court_code="B000210", court_name="서울중앙지방법원",
                        case_no=case_no, item_no="1", property_type="아파트",
                        sido="서울", sigungu="강남구", dong="역삼동", lot_number="1",
                        full_address="서울특별시 강남구 역삼동 1",
                        appraisal_price=100000000, minimum_bid_price=70000000,
                        auction_date="2026-09-01", status="진행",
                        validation_status="PASS", validation_reasons="",
                        crawl_date="2026-08-13")
            base.update(over)
            return base

        def count():
            c = sqlite3.connect(dbmod.DB_PATH)
            try:
                return c.execute("SELECT COUNT(*) FROM auction").fetchone()[0]
            finally:
                c.close()

        # (1) 정상 배치
        r = dbmod.upsert_batch([row("2026타경1"), row("2026타경2")])
        check("정상 2건 저장", (r["inserted"], r["updated"], r["failed"]), (2, 0, 0))
        check("DB에 2행", count(), 2)

        # (2) 같은 키로 다시 넣으면 UPDATE다(행이 늘지 않는다).
        r = dbmod.upsert_batch([row("2026타경1", status="유찰")])
        check("같은 키는 UPDATE", (r["inserted"], r["updated"], r["failed"]), (0, 1, 0))
        check("행 수는 그대로", count(), 2)

        # (3) ★ 행 하나가 깨져도 나머지는 저장된다.
        #     appraisal_price에 숫자가 아닌 값이 오면 int()에서 터진다(실제로 일어날 수 있는
        #     형태다 - 법원 페이지가 "미상" 같은 문자열을 줄 때).
        #     ★ 안쪽 except가 사라지면 예외가 그대로 밖으로 나온다. 그 형태로 끝나면
        #        스위트가 크래시해 원인이 안 보이므로, 붙잡아 깔끔한 FAIL로 바꾼다.
        r = None
        leaked = None
        try:
            r = dbmod.upsert_batch([
                row("2026타경10"),
                row("2026타경11", appraisal_price="미상"),   # <- 이 행만 실패
                row("2026타경12"),
            ])
        except Exception as exc:
            leaked = exc
        check_true("행 하나의 실패가 배치 밖으로 새어 나오지 않는다", leaked is None,
                   "행 단위 except가 사라졌는가? 한 법원의 값 하나 때문에 그날 수집분을 "
                   "전부 잃는다: %r" % (leaked,))
        if r is None:
            return
        check("깨진 행만 실패로 센다", (r["inserted"], r["updated"], r["failed"]), (2, 0, 1))
        check("나머지 2행은 저장된다", count(), 4)
        c = sqlite3.connect(dbmod.DB_PATH)
        try:
            saved = {x[0] for x in c.execute("SELECT case_no FROM auction")}
        finally:
            c.close()
        check_true("실패한 행은 저장되지 않았다", "2026타경11" not in saved, sorted(saved))
        check_true("그 앞뒤 행은 저장됐다",
                   {"2026타경10", "2026타경12"} <= saved, sorted(saved))

        # (4) ★ 커밋이 실패하면 전부 롤백하고 예외를 다시 던진다.
        #     여기서 조용히 넘어가면 크롤이 실패해도 성공으로 보고된다.
        before = count()
        real_get_connection = dbmod.get_connection

        class _CommitFails:
            """commit()만 실패하는 커넥션 래퍼. 나머지는 실제 커넥션에 그대로 위임한다."""

            def __init__(self, inner):
                self._inner = inner
                self.rolled_back = False

            def commit(self):
                raise sqlite3.OperationalError("disk I/O error (주입된 실패)")

            def rollback(self):
                self.rolled_back = True
                return self._inner.rollback()

            def __getattr__(self, name):
                return getattr(self._inner, name)

        made = []

        def fake_get_connection(*a, **kw):
            wrapper = _CommitFails(real_get_connection(*a, **kw))
            made.append(wrapper)
            return wrapper

        dbmod.get_connection = fake_get_connection
        raised = None
        try:
            dbmod.upsert_batch([row("2026타경99")])
        except Exception as exc:
            raised = exc
        finally:
            dbmod.get_connection = real_get_connection

        check_true("커밋 실패는 예외로 전파된다(삼키지 않는다)", raised is not None,
                   "성공으로 반환하면 mvp_scraper가 실패를 못 본다")
        check_true("rollback이 호출된다", made and made[0].rolled_back, made)
        check("롤백됐으므로 행이 늘지 않는다", count(), before)
    finally:
        dbmod.DB_PATH = real_path
        shutil.rmtree(d, ignore_errors=True)


# ---------------------------------------------------------------------------
# 16. 성공할 수 없는 항목이 매일 되살아나지 않는가 (2026-08-14 신설)
#
# `doc_worker.py`는 큐에서 집은 항목마다 `get_doc_button_id()`를 부르고, None이면
# 브라우저를 열지 않는다. None이 되는 이유는 **둘 다 영구적**이다 — 현황조사서의
# item_no != '1'(DOM으로 확인된 버튼 id가 없다), 그리고 알 수 없는 doc_type.
#
# 예전에는 이 경로가 `mark_queue_failed()`를 불렀다. 실패는 재시도 대상이고,
# `reset_stale_queue()`는 하루 지난 failed를 pending + retry_count=0으로 되살린다.
# 그래서 **성공 가능성이 0인 항목이 4일 주기로 영원히 재시도됐다.** 실측 재현:
#
#     1일차 pending retry=1  화면 COLLECTING
#     2일차 pending retry=2  화면 COLLECTING
#     3일차 failed  retry=3  화면 FAILED
#     4일차 (reset_stale_queue가 되살린다)
#     5일차 pending retry=1  화면 COLLECTING   <- 처음으로 되돌아간다
#     ... 16일 동안 12회 시도
#
# 나쁜 점이 둘이다. (a) 절대 성공하지 못할 항목이 매일 claim 슬롯을 먹는다.
# (b) **화면 상태가 "수집실패" <-> "수집중"을 4일마다 오간다** — 사용자는 같은 문서가
# 며칠마다 상태를 바꾸는 것을 보지만 실제로 달라진 것은 없다.
#
# 이 검사는 **여러 날을 실제로 돌려** 그 고리가 끊겼는지 본다. 한 번의 호출만 보면
# (예전 코드도 1일차는 똑같이 동작하므로) 이 결함을 잡지 못한다.
# ---------------------------------------------------------------------------
def _db_with_document_status():
    """document_queue + `_set_document_status()`가 필요로 하는 v4.1 3개 테이블."""
    d, conn = make_db()
    conn.executescript("""
        CREATE TABLE auction_case (id INTEGER PRIMARY KEY, case_no TEXT, court_code TEXT,
                                   court_name TEXT);
        CREATE TABLE auction_item (id INTEGER PRIMARY KEY, case_id INTEGER, case_no TEXT,
                                   item_no TEXT, court_name TEXT);
        CREATE TABLE document_status (id INTEGER PRIMARY KEY AUTOINCREMENT, item_id INTEGER,
                                      doc_type TEXT, status TEXT, updated_at TEXT,
                                      UNIQUE(item_id, doc_type));
    """)
    return d, conn


def test_unsupported_item_does_not_retry_forever():
    print("\n--- 16. 버튼 id가 없는 항목은 매일 되살아나지 않는다 ---")
    import storage.database as dbmod
    from config.settings import get_doc_button_id

    d, conn = _db_with_document_status()
    real = dbmod.DB_PATH
    path = os.path.join(d, "t.db")
    try:
        conn.executescript("""
            INSERT INTO auction_case VALUES (1,'2026타경1','B000210','서울중앙지방법원');
            INSERT INTO auction_item VALUES (1,1,'2026타경1','7','서울중앙지방법원');
            INSERT INTO document_status (item_id,doc_type,status,updated_at)
                VALUES (1,'STATUS','COLLECTING','2026-08-01T00:00:00');
        """)
        # 2026-08-17 Sprint 144+: 예전에는 여기 시드가 ("status", item_no=7) — 즉 "현황조사서
        # + 물건번호 2 이상"이었다. 그 조합이 **더 이상 미지원이 아니다**(DOM 실측으로 버튼
        # id를 확정했다 — §14 참고). 그래서 시드를 그대로 두면 이 검사는 "미지원 항목"이
        # 아닌 것을 대상으로 삼아 **공허해진다.**
        #
        # 이 검사가 지키려는 것은 특정 조합이 아니라 **저장 계층의 불변식**이다:
        # `mark_queue_unsupported()`로 종결된 행이 `reset_stale_queue()`에 되살아나
        # 영원히 재시도되지 않는가. 그래서 시드는 `document_status`에 매핑되는 종류
        # (status)로 두되, "버튼 id가 없다"는 상황은 아래 루프가 직접 재현한다.
        _seed_queue(conn, [("2026타경1", "7", "status", "pending", 1, "2099-01-01", 0, None)])
        conn.close()
        dbmod.DB_PATH = path

        # 지금 실제로 버튼 id가 없는 것은 **알 수 없는 doc_type**뿐이다.
        # (현황조사서 + 물건번호 2 이상은 2026-08-17에 지원 대상이 됐다 — §14)
        check("남아 있는 영구 미지원 사유는 '모르는 doc_type'이다",
              get_doc_button_id("registry", "1"), None)
        check_true("현황조사서 + 물건번호 7은 이제 지원된다(옛 전제가 뒤집혔다)",
                   bool(get_doc_button_id("status", "7")))

        def snapshot():
            c = sqlite3.connect(path)
            c.row_factory = sqlite3.Row
            try:
                q = c.execute("SELECT status, retry_count FROM document_queue").fetchone()
                ds = c.execute("SELECT status FROM document_status"
                               " WHERE item_id=1 AND doc_type='STATUS'").fetchone()
                return q["status"], q["retry_count"], ds["status"]
            finally:
                c.close()

        def age_one_day():
            c = sqlite3.connect(path)
            c.execute("UPDATE document_queue SET last_attempt_at="
                      "datetime(last_attempt_at,'-1 day') WHERE last_attempt_at IS NOT NULL")
            c.commit()
            c.close()

        attempts = 0
        seen_ds = set()
        for _ in range(16):          # 16일치 doc_worker 기동
            dbmod.reset_stale_queue()
            while True:
                item = dbmod.claim_next_queue_item()
                if not item:
                    break
                attempts += 1
                # doc_worker.py의 `if needs_button and not btn_id:` 분기와 같은 호출.
                # (버튼 id가 없는 상황 자체를 재현한다 — 어떤 조합이 그 상황을 만드는지는
                #  §14가 따로 고정한다. 여기서 보는 것은 종결 뒤 되살아나지 않는가다.)
                dbmod.mark_queue_unsupported(item["id"], item["court_code"], item["case_no"],
                                             item["item_no"], item["doc_type"])
            seen_ds.add(snapshot()[2])
            age_one_day()

        status, retry, ds = snapshot()
        # ★ 핵심: 16일을 돌려도 시도는 딱 한 번이어야 한다.
        check("16일 동안 시도는 1회뿐이다(재시도 고리가 끊겼다)", attempts, 1)
        check("큐는 종결 상태로 남는다", status, "SKIPPED_UNSUPPORTED")
        check("실패가 아니므로 retry_count를 소모하지 않는다", retry, 0)
        check("화면 상태는 FAILED로 고정된다", ds, "FAILED")
        # 상태가 오가지 않는다 — 첫 시도 뒤로 FAILED 하나만 관측돼야 한다.
        check("화면 상태가 오가지 않는다(관측된 값의 종류)", sorted(seen_ds), ["FAILED"])

        # ★ 위 재현은 doc_worker의 분기를 **흉내낸** 것이다. 실제 호출부가 예전처럼
        #   mark_queue_failed로 돌아가면 위 검사는 그대로 통과하면서 결함만 되살아난다.
        #   그래서 호출부 자체를 소스로 고정한다(§14가 doc_worker 호출 형태를 고정한 것과
        #   같은 방식).
        src = open(os.path.join(ROOT, "doc_worker.py"), encoding="utf-8-sig").read()
        # 2026-08-17 Sprint 144: 분기 조건이 `if not btn_id:` -> `if needs_button and not btn_id:`
        # 로 바뀌었다(물건 사진은 버튼 없이 상세 DOM에서 읽으므로 버튼 검사 대상이 아니다).
        # 이 검사가 지키려는 것은 **조건문의 글자**가 아니라 "버튼 id가 없을 때
        # mark_queue_unsupported로 종결한다"는 동작이므로, 앵커만 새 조건에 맞춘다.
        anchor = "if needs_button and not btn_id:"
        check_true("doc_worker에 '버튼 id 없음' 분기가 있다", anchor in src,
                   "분기 형태가 또 바뀌었다면 이 앵커를 갱신하되 아래 검사는 유지할 것")
        branch = src[src.index(anchor):]
        branch = branch[:branch.index("continue")]
        check_true("doc_worker의 '버튼 id 없음' 분기는 mark_queue_unsupported를 부른다",
                   "mark_queue_unsupported(" in branch,
                   "mark_queue_failed로 되돌아가면 매일 되살아나는 무한 재시도가 다시 생긴다: "
                   + branch.strip())
        check_true("그 분기는 mark_queue_failed를 부르지 않는다",
                   "mark_queue_failed(" not in branch, branch.strip())
    finally:
        dbmod.DB_PATH = real
        shutil.rmtree(d, ignore_errors=True)


# ---------------------------------------------------------------------------
# 18. 종결 함수 넷 중 **셋만** 화면 상태를 쓴다 ― 그 비대칭을 고정한다 (2026-08-14 신설)
#
#     mark_queue_done            -> document_status = READY
#     mark_queue_failed          -> document_status = FAILED    (최종 실패)
#     mark_queue_unsupported     -> document_status = FAILED    (Sprint 101)
#     mark_queue_skipped_expired -> **쓰지 않는다**             <- 다르다
#
# 이 비대칭은 **누락이 아니라 보류**다. Sprint 73이 검토하고 그대로 두기로 했다 ―
# `document_status` enum에 "대상 아님"이 없어 FAILED로 쓰면 실패가 아닌 것을 실패로
# 표기하게 되고, 새 상태를 만드는 것은 상태머신·화면 문구 결정이라 제품 판단이다.
# 근거와 "함께 고쳐야 할 지점" 목록은 `test_document_status_sync.py` §6이 들고 있고,
# 그 검사가 현재 동작(COLLECTING 유지)을 고정한다.
#
# 여기서 고정하는 것은 **다른 것**이다: 나머지 셋이 계속 화면 상태를 쓴다는 것.
# 셋 중 하나가 조용히 빠지면 "수집중"에 영원히 머무는 문서가 새로 생기는데,
# §6은 `skipped_expired` 하나만 보므로 그 손실을 알려 주지 않는다.
#
# ★ 왜 §9로는 부족한가 — §9는 큐의 status/retry_count/last_attempt_at만 본다.
#   **화면 상태를 한 번도 보지 않는다.** 계약의 절반만 보는 검사라
#   나머지 절반이 비어도 초록불이다.
# ---------------------------------------------------------------------------
def test_queue_terminal_functions_screen_status_contract():
    print("\n--- 18. 종결 함수의 화면 상태 계약 ---")
    import inspect
    import storage.database as dbmod

    # 화면 상태를 함께 쓰는 셋 — 하나라도 빠지면 '끝나지 않는 수집중'이 새로 생긴다.
    for name in ("mark_queue_done", "mark_queue_failed", "mark_queue_unsupported"):
        src = inspect.getsource(getattr(dbmod, name))
        check_true("%s 는 document_status를 함께 갱신한다" % name,
                   "_set_document_status" in src or "document_status" in src,
                   "큐만 닫고 화면을 두면 '수집중'이 영원히 남는다")

    # 그리고 넷째는 **일부러** 쓰지 않는다. 누가 이것을 배선하면 여기와
    # `test_document_status_sync.py` §6이 함께 실패해 제품 판단이 필요함을 알린다.
    src = inspect.getsource(dbmod.mark_queue_skipped_expired)
    check_true("mark_queue_skipped_expired 는 화면 상태를 쓰지 않는다(제품 판단 대기)",
               "_set_document_status" not in src,
               "배선하려면 '대상 아님' 상태 정의가 먼저다 ― "
               "test_document_status_sync.py §6의 근거를 보라")

    # 실제 동작으로도 확인한다(소스 검사만 두면 구현이 바뀌어도 통과할 수 있다).
    d, conn = _db_with_document_status()
    real = dbmod.DB_PATH
    path = os.path.join(d, "t.db")
    try:
        conn.executescript("""
            INSERT INTO auction_case VALUES (1,'2020타경9','B000210','서울중앙지방법원');
            INSERT INTO auction_item VALUES (1,1,'2020타경9','1','서울중앙지방법원');
            INSERT INTO document_status (item_id,doc_type,status,updated_at)
                VALUES (1,'SPEC','COLLECTING','2026-08-01T00:00:00');
        """)
        _seed_queue(conn, [("2020타경9", "1", "spec", "pending", 1, "2020-01-01", 0, None)])
        qid = conn.execute("SELECT id FROM document_queue").fetchone()[0]
        conn.close()
        dbmod.DB_PATH = path

        dbmod.mark_queue_skipped_expired(qid, "B000210", "2020타경9", "1", "spec", "2020-01-01")

        c = sqlite3.connect(path)
        c.row_factory = sqlite3.Row
        try:
            q = c.execute("SELECT status, retry_count FROM document_queue"
                          " WHERE id=?", (qid,)).fetchone()
            ds = c.execute("SELECT status FROM document_status"
                           " WHERE item_id=1 AND doc_type='SPEC'").fetchone()["status"]
        finally:
            c.close()
        check("큐는 SKIPPED_EXPIRED로 종결된다", q["status"], "SKIPPED_EXPIRED")
        check("실패가 아니므로 retry_count를 소모하지 않는다", q["retry_count"], 0)
        check("화면 상태는 그대로 수집중이다(§6이 고정한 현재 동작)", ds, "COLLECTING")

        # 종결된 뒤에는 다시 집히지 않는다 ― 그래서 이 '수집중'은 **끝나지 않는다.**
        dbmod.reset_stale_queue()
        check_true("종결 후에는 큐에서 다시 집히지 않는다(그래서 끝나지 않는 수집중이다)",
                   dbmod.claim_next_queue_item() is None)
    finally:
        dbmod.DB_PATH = real
        shutil.rmtree(d, ignore_errors=True)



def test_terminal_functions_respect_the_claim_token():
    """종결 함수 **넷 전부**가 claim 을 확인하는가 (2026-08-25, docs/BUGS.md #202).

    ## 왜 이 검사가 생겼나

    BUGS #181 은 `mark_queue_done` / `mark_queue_failed` 에 claim 토큰 검사를 넣었다.
    그런데 **`mark_queue_skipped_expired` / `mark_queue_unsupported` 는 빠져 있었다.**
    그 비대칭을 합성 물건으로 재현했다:

        A 가 집는다 -> 멈춘다 -> reset_stale_queue 가 회수 -> B 가 집어 실제로 수집
        -> 좀비 A 가 뒤늦게 skipped_expired 를 부른다
           => 큐 = SKIPPED_EXPIRED (B 가 작업 중인데 종결됐다)
           => 그 함수가 last_attempt_at 을 덮으므로 **B 의 토큰까지 무효가 된다**
        -> B 가 수집을 끝내고 done(claim_token=B) 을 부른다
           => 토큰 불일치로 큐는 그대로, 문서만 기록된다
           => 최종: document_status=READY / doc_raw 1행 / **큐=SKIPPED_EXPIRED**

    실제로 받아 놓은 문서가 큐에서는 "대상 아님"으로 남는다 — 이 저장소가 스스로
    확인해 온 불변식("화면이 READY 인데 큐가 done 계열이 아닌 행 0건")을 깨는 상태다.

    ## 무엇을 고정하는가

        남의 claim 이면   큐를 건드리지 않는다 (상태도 last_attempt_at 도 그대로)
        내 claim 이면     예전처럼 종결한다
        토큰 미지정(None) 예전 동작 그대로 (호출부 호환 - `_claim_is_still_ours` 규약)
    """
    print("\n--- 19. 종결 함수가 claim 토큰을 존중하는가 (BUGS #202) ---")
    import inspect
    import storage.database as dbmod

    # (a) 구조: 넷 다 claim_token 을 받고 `_claim_is_still_ours` 로 확인하는가
    TERMINALS = ("mark_queue_done", "mark_queue_failed",
                 "mark_queue_skipped_expired", "mark_queue_unsupported")
    for name in TERMINALS:
        fn = getattr(dbmod, name)
        params = inspect.signature(fn).parameters
        check_true("%s 가 claim_token 인자를 받는다" % name, "claim_token" in params,
                   sorted(params))
        src = inspect.getsource(fn)
        check_true("%s 가 _claim_is_still_ours 로 확인한다" % name,
                   "_claim_is_still_ours" in src,
                   "-> 확인하지 않으면 좀비가 남의 행을 종결시킨다")

    # (b) 행위: 남의 토큰으로는 종결되지 않는다
    d, conn = make_db()
    try:
        saved = dbmod.DB_PATH
        dbmod.DB_PATH = os.path.join(d, "t.db")
        try:
            # `mark_queue_unsupported` 는 화면 상태까지 쓴다. 이 파일의 스키마는 큐 전용이라
            # 그대로 두면 **행위 검사가 예외로 죽어** 판정문 없이 끝난다(가드를 없애는
            # 변이에서 실제로 그랬다). 빈 테이블만 만들어 두면 `_set_document_status`
            # 가 설계대로 "대상 없음" 경고 + False 로 물러난다(Sprint 78 규약).
            conn.executescript(
                "CREATE TABLE IF NOT EXISTS auction_case ("
                " id INTEGER PRIMARY KEY AUTOINCREMENT, court_code TEXT, case_no TEXT);"
                "CREATE TABLE IF NOT EXISTS auction_item ("
                " id INTEGER PRIMARY KEY AUTOINCREMENT, case_id INTEGER,"
                " case_no TEXT, item_no TEXT);"
                "CREATE TABLE IF NOT EXISTS document_status ("
                " id INTEGER PRIMARY KEY AUTOINCREMENT, item_id INTEGER,"
                " doc_type TEXT, status TEXT, updated_at TEXT,"
                " UNIQUE(item_id, doc_type));")
            enqueue(conn, "QA법원", "2026타경1", "1", "spec")
            conn.commit()
            qid = conn.execute("SELECT id FROM document_queue").fetchone()["id"]

            a = dbmod.claim_next_queue_item()
            check_true("A 가 집었다", a is not None and a["id"] == qid)
            token_a = a["claim_token"]

            # 회수 -> B 가 집는다
            conn.execute("UPDATE document_queue SET status='pending',"
                         " last_attempt_at=NULL WHERE id=?", (qid,))
            conn.commit()
            b = dbmod.claim_next_queue_item()
            check_true("B 가 다시 집었다", b is not None and b["id"] == qid)
            token_b = b["claim_token"]
            check_true("두 토큰이 다르다(검사가 공허하지 않다)", token_a != token_b,
                       (token_a, token_b))

            def state():
                r = conn.execute("SELECT status, last_attempt_at FROM document_queue"
                                 " WHERE id=?", (qid,)).fetchone()
                return r["status"], r["last_attempt_at"]

            before = state()

            # 좀비 A 가 자기 토큰으로 종결 시도 -> 아무것도 바뀌면 안 된다
            dbmod.mark_queue_skipped_expired(qid, "QA법원", "2026타경1", "1", "spec",
                                             "2020-01-01", token_a)
            check("★ 좀비의 skipped_expired 는 큐를 바꾸지 않는다", state(), before)

            dbmod.mark_queue_unsupported(qid, "QA법원", "2026타경1", "1", "spec", token_a)
            check("★ 좀비의 unsupported 도 큐를 바꾸지 않는다", state(), before)

            # 대조군 - **자기** claim 이면 종결된다(막기만 하고 기능이 죽으면 안 된다)
            dbmod.mark_queue_skipped_expired(qid, "QA법원", "2026타경1", "1", "spec",
                                             "2020-01-01", token_b)
            check("대조군: 자기 claim 이면 종결된다", state()[0], "SKIPPED_EXPIRED")

            # 대조군 - 토큰 미지정은 예전 동작 그대로(호출부 호환).
            #   `skipped_expired` 로 확인한다 - `unsupported` 는 document_status 까지
            #   써서 이 파일의 큐 전용 스키마에는 없는 테이블이 필요하다
            #   (그쪽 계약은 §18 과 test_unsupported_item_does_not_retry_forever 가 본다).
            conn.execute("UPDATE document_queue SET status='in_progress' WHERE id=?", (qid,))
            conn.commit()
            dbmod.mark_queue_skipped_expired(qid, "QA법원", "2026타경1", "1", "spec",
                                             "2020-01-01")
            check("대조군: 토큰 미지정은 예전처럼 종결한다", state()[0], "SKIPPED_EXPIRED")
        finally:
            dbmod.DB_PATH = saved
    finally:
        conn.close()
        shutil.rmtree(d, ignore_errors=True)

    # (c) 호출부가 실제로 토큰을 넘기는가 (배선이 없으면 위 방어는 죽은 코드다)
    worker_src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   "doc_worker.py"), encoding="utf-8-sig").read()
    for name in ("mark_queue_skipped_expired", "mark_queue_unsupported"):
        idx = worker_src.find(name + "(")
        check_true("doc_worker 가 %s 를 부른다" % name, idx != -1)
        if idx == -1:
            continue
        call = worker_src[idx:idx + 400]
        call = call[:call.index(")\n") + 1] if ")\n" in call else call
        check_true("doc_worker 가 %s 에 claim_token 을 넘긴다" % name,
                   "claim_token" in call, call[:200])

def test_supported_item_still_retries():
    """미지원 종결이 **정상 실패의 재시도까지** 죽이지 않는가 (반대 방향 회귀).

    위 16번을 만족시키려고 "실패하면 무조건 종결"로 바꾸면 일시적 장애(네트워크/팝업
    타이밍)로 실패한 문서가 한 번에 영구 포기된다 — 고치려던 것보다 나쁘다.
    버튼 id가 **있는** 항목은 예전 그대로 3회까지 재시도돼야 한다.
    """
    print("\n--- 17. 버튼 id가 있는 항목의 재시도는 그대로다 ---")
    import storage.database as dbmod
    from config.settings import get_doc_button_id

    d, conn = _db_with_document_status()
    real = dbmod.DB_PATH
    path = os.path.join(d, "t.db")
    try:
        _seed_queue(conn, [("2026타경2", "1", "spec", "pending", 1, "2099-01-01", 0, None)])
        conn.close()
        dbmod.DB_PATH = path
        check_true("전제: 이 조합은 버튼 id가 있다", bool(get_doc_button_id("spec", "1")))

        attempts = 0
        for _ in range(6):
            item = dbmod.claim_next_queue_item()
            if not item:
                break
            attempts += 1
            dbmod.mark_queue_failed(item["id"], item["retry_count"])
            c = sqlite3.connect(path)
            c.execute("UPDATE document_queue SET last_attempt_at="
                      "datetime(last_attempt_at,'-1 hour')")
            c.commit()
            c.close()

        c = sqlite3.connect(path)
        c.row_factory = sqlite3.Row
        row = c.execute("SELECT status, retry_count FROM document_queue").fetchone()
        c.close()
        check("MAX_DOC_RETRY만큼 재시도한다", attempts, dbmod.MAX_DOC_RETRY)
        check("재시도를 소진하면 failed", row["status"], "failed")
        check("retry_count가 소진된다", row["retry_count"], dbmod.MAX_DOC_RETRY)
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
    test_reset_stale_queue_recovers_whole_item_batch()
    test_claim_next_queue_item()
    test_claim_is_atomic_under_concurrency()
    test_mark_queue_skipped_expired()
    test_calc_priority()
    test_refresh_queue_priority()
    test_relisted_auction_date_is_refreshed()
    test_expired_row_with_current_date_is_revived()
    test_expired_items_are_not_enqueued()
    test_relist_does_not_touch_unrelated_rows()
    test_get_doc_button_id_contract()
    test_upsert_batch_partial_and_total_failure()
    test_unsupported_item_does_not_retry_forever()
    test_queue_terminal_functions_screen_status_contract()
    test_terminal_functions_respect_the_claim_token()
    test_supported_item_still_retries()

    print("\n" + "=" * 55)
    if failures:
        print("FAILED (%d): %s" % (len(failures), ", ".join(failures)))
        return 1
    print("ALL TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(run())
