"""`enqueue_documents()` / `refresh_queue_priority()` 의 **묶음 쓰기** 회귀 테스트.

운영 DB 는 건드리지 않는다 — `storage.database.snapshot_live_db()` 로 스키마만 뜬 뒤
데이터를 비운 스크래치 사본에서만 돈다.

배경 (2026-08-27, docs/BUGS.md #249)
---------------------------------------------------------------------------
`migrate_execute` 에서 고친 #247 과 **같은 계열**이 큐 쪽 두 함수에도 있었다 —
"바뀌었는지 판정을 DB 에 맡기고 문장은 전부 보낸다".

    enqueue_documents()       행마다 INSERT OR IGNORE 4개 (+ UPDATE 4개)
    refresh_queue_priority()  대기 행마다 UPDATE 1개, no-op 은 `AND priority!=?` 로 거름

수정 전 실측(같은 데이터를 다시 수집한, 아무것도 안 바뀐 정상적인 날):

    입력/대기 25,000행
        enqueue_documents        200,002문장  ->  실제로 추가된 행    0건
        refresh_queue_priority   100,003문장  ->  실제로 바뀐 행      0건

`refresh_queue_priority` 는 **누적 대기 큐**(물건 하나당 최대 4행)를 훑으므로 비용이
그날 일감이 아니라 쌓인 양에 붙는다 — #247 이 10만 행에서 동시 writer 를 죽인 것과
같은 구조다.

이 테스트가 지키는 것
---------------------------------------------------------------------------
속도가 아니라 **결과의 동일성**이다. "안 보낸다"의 유일한 위험은 보내야 할 때
안 보내는 것이므로, 넣어야 하는 경우/갱신해야 하는 경우를 하나씩 따로 만든다.
문장 수 상한도 함께 고정한다 — 그게 없으면 누가 루프로 되돌려도 아무도 모른다.

    python test_queue_write_batching.py
"""
import sys
import os
import sqlite3
import shutil
import tempfile
import logging
import importlib
import contextlib
import io
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import storage.database as dbmod

logging.disable(logging.CRITICAL)

failures = []


def check(name, actual, expected):
    ok = actual == expected
    print("[%s] %s: %r (expected %r)" % ("PASS" if ok else "FAIL", name, actual, expected))
    if not ok:
        failures.append(name)


def check_true(name, cond, detail=""):
    ok = bool(cond)
    print("[%s] %s%s" % ("PASS" if ok else "FAIL", name, ("" if ok else " -> " + str(detail))))
    if not ok:
        failures.append(name)


_TMP = []


# 운영 DB 경로를 **한 번만** 붙잡아 둔다 (2026-08-27, BUGS #257).
#
# ★ `scratch_db()` 는 마지막에 `dbmod.DB_PATH` 를 스크래치로 갈아끼운다. 그래서
#   그때그때의 `dbmod.DB_PATH` 에서 스냅샷을 뜨면, 두 번째 호출부터는 실 DB 가 아니라
#   **직전 스크래치의 사본**을 뜬다. 행은 지우므로 데이터는 안 넘어오지만 **스키마
#   객체(트리거/인덱스/뷰)는 넘어간다** — 검사끼리 조용히 오염된다.
#   `test_upsert_change_detection.py` 에서 실제로 트리거가 새어 나가 집계를 흔들었다.
_LIVE_DB_PATH = dbmod.DB_PATH


def scratch_db():
    """운영 DB 의 스키마 그대로인 빈 DB."""
    d = tempfile.mkdtemp(prefix="qwb_")
    _TMP.append(d)
    path = os.path.join(d, "scratch.db")
    dbmod.DB_PATH = _LIVE_DB_PATH   # 항상 **실 DB** 에서 뜬다
    dbmod.snapshot_live_db(path)
    c = sqlite3.connect(path)
    try:
        c.execute("PRAGMA foreign_keys=OFF")
        for t in [r[0] for r in c.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%' AND name<>'migration_history'")]:
            c.execute('DELETE FROM "%s"' % t)
        c.commit()
    finally:
        c.close()
    dbmod.DB_PATH = path
    return path


def days_ahead(n):
    return (datetime.now() + timedelta(days=n)).strftime("%Y-%m-%d")


def row(i, auction_date=None, **over):
    r = {
        "court_code": "B100001",
        "court_name": "테스트법원",
        "case_no": "2026타경%06d" % i,
        "item_no": "1",
        "auction_date": auction_date if auction_date is not None else days_ahead(30),
    }
    r.update(over)
    return r


def count_statements(fn, *a, **kw):
    """실행 중 실제로 나간 SQL 문장 수와 반환값. (총 문장 수, 반환값)"""
    n, _kind, out = count_by_kind(fn, *a, **kw)
    return n, out


def count_by_kind(fn, *a, **kw):
    """(총 문장 수, {종류: 개수}, 반환값).

    ★ 종류별로 세는 이유 (2026-08-27 변이 테스트로 배웠다):
      총 문장 수만 보면 **건너뛰기가 사라져도 안 잡힌다.** id 를 IN 목록으로 묶어
      보내므로, 안 바뀐 행까지 전부 목록에 넣어도 문장 수는 3~4개밖에 안 늘기
      때문이다. 낭비의 신호는 "문장이 많다"가 아니라 **"보낼 필요 없는 UPDATE 를
      보냈다"** 이므로 그걸 직접 센다.
    """
    kind = {}
    orig = dbmod.get_connection

    def cb(stmt):
        head = (stmt or "").strip().split(" ", 1)[0].upper()
        kind[head] = kind.get(head, 0) + 1

    def patched(*aa, **kk):
        conn = orig(*aa, **kk)
        conn.set_trace_callback(cb)
        return conn

    dbmod.get_connection = patched
    try:
        out = fn(*a, **kw)
    finally:
        dbmod.get_connection = orig
    return sum(kind.values()), kind, out


def q(path, sql, args=()):
    c = sqlite3.connect(path)
    try:
        r = c.execute(sql, args).fetchone()
        return r[0] if r else None
    finally:
        c.close()


def rows_of(path, sql, args=()):
    c = sqlite3.connect(path)
    c.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in c.execute(sql, args)]
    finally:
        c.close()


# ---------------------------------------------------------------------------
# 1. enqueue_documents — 신규는 전부 들어오고, 재실행은 문장이 급감한다
# ---------------------------------------------------------------------------
def test_enqueue_inserts_then_goes_quiet():
    print("\n--- 1. enqueue_documents: 최초 적재 / 재실행 ---")
    path = scratch_db()
    rows = [row(i) for i in range(50)]

    n1, r1 = count_statements(dbmod.enqueue_documents, rows)
    check("최초: added = 50물건 x 4종", r1["added"], 200)
    check("최초: DB 행수도 200", q(path, "SELECT COUNT(*) FROM document_queue"), 200)
    check("최초: refreshed 0", r1["refreshed"], 0)
    check("최초: 4종이 모두 생긴다",
          sorted(x["doc_type"] for x in rows_of(
              path, "SELECT DISTINCT doc_type FROM document_queue")),
          ["appraisal", "image", "spec", "status"])

    # 같은 데이터를 다시 — 아무것도 추가되지 않아야 하고 문장이 거의 없어야 한다
    n2, kind2, r2 = count_by_kind(dbmod.enqueue_documents, rows)
    check("재실행: added 0", r2["added"], 0)
    check("재실행: refreshed 0", r2["refreshed"], 0)
    check("재실행: DB 행수 그대로 200", q(path, "SELECT COUNT(*) FROM document_queue"), 200)
    # 바뀐 것이 없으면 쓰기 문장을 **하나도** 보내지 않아야 한다
    check("재실행: INSERT 문장 0개", kind2.get("INSERT", 0), 0)
    check("재실행: UPDATE 문장 0개", kind2.get("UPDATE", 0), 0)

    # 예전에는 50행 x 4종 = 200 INSERT + 200 UPDATE = 400문장 이상이었다.
    # 이제는 선조회 몇 개 + BEGIN/COMMIT 뿐이어야 한다.
    check_true("재실행 문장 수가 20개 미만 (실제 %d)" % n2, n2 < 20, n2)
    print("     (최초 %d문장 / 재실행 %d문장)" % (n1, n2))


# ---------------------------------------------------------------------------
# 2. enqueue_documents — 기일이 바뀌면 **반드시** 갱신된다
#
#    이 최적화가 깨지면 큐가 옛 기일을 들고 있게 되고, doc_worker 의 2차 방어선이
#    그 stale 값을 보고 살아 있는 사건을 SKIPPED_EXPIRED 로 버린다(Sprint 74 가
#    고쳤던 바로 그 결함). 그래서 따로 고정한다.
# ---------------------------------------------------------------------------
def test_enqueue_refreshes_changed_auction_date():
    print("\n--- 2. enqueue_documents: 기일 변경 반영 ---")
    path = scratch_db()
    old_date, new_date = days_ahead(10), days_ahead(40)
    dbmod.enqueue_documents([row(1, auction_date=old_date)])
    check("최초 기일", q(path, "SELECT DISTINCT auction_date FROM document_queue"), old_date)
    old_prio = q(path, "SELECT DISTINCT priority FROM document_queue")

    n, r = count_statements(dbmod.enqueue_documents, [row(1, auction_date=new_date)])
    check("기일 변경분 refreshed = 4종", r["refreshed"], 4)
    check("added 는 0", r["added"], 0)
    check("DB 기일이 새 값으로", q(path, "SELECT DISTINCT auction_date FROM document_queue"), new_date)
    check("행이 늘지 않는다", q(path, "SELECT COUNT(*) FROM document_queue"), 4)
    new_prio = q(path, "SELECT DISTINCT priority FROM document_queue")
    check_true("우선순위도 함께 재계산된다 (%s -> %s)" % (old_prio, new_prio),
               new_prio == dbmod.calc_priority(new_date), (old_prio, new_prio))

    # 같은 값으로 또 부르면 이번엔 조용해야 한다
    n2, r2 = count_statements(dbmod.enqueue_documents, [row(1, auction_date=new_date)])
    check("같은 기일 재실행 refreshed 0", r2["refreshed"], 0)


# ---------------------------------------------------------------------------
# 3. enqueue_documents — 기존 행의 status 를 되살리지 않는다
#
#    `INSERT OR IGNORE` 의 원래 성질이다. 선조회 방식으로 바꾸면서 이게 바뀌면
#    doc_worker 가 수집을 끝낸 done 행이 매일 pending 으로 되돌아가 영원히 재수집된다.
#
#    ★ 2026-08-27 (BUGS #254) — 예외가 딱 하나 생겼다: `SKIPPED_EXPIRED`.
#      그 상태는 "기일이 지나 대상이 아님"이라는 **주장**인데, 새 기일이 아직 안 지난
#      행에 붙어 있으면 그 주장은 사실이 아니고 아무도 그 행을 다시 보지 않는다.
#      `done` / `failed` 되살리기(=재수집)와 다르다 — 그 행들은 한 번도 받은 적이 없다.
#      운영에서 36행이 그렇게 굳어 있었다(전부 감정평가서, 전부 매각기일이 그날).
#      여기서는 **되살리는 쪽과 안 되살리는 쪽을 같은 검사에서 대비**해 둔다.
# ---------------------------------------------------------------------------
def test_enqueue_preserves_existing_status():
    print("\n--- 3. enqueue_documents: 기존 status 보존 ---")
    path = scratch_db()
    d = days_ahead(20)
    dbmod.enqueue_documents([row(1, auction_date=d)])

    c = sqlite3.connect(path)
    c.execute("UPDATE document_queue SET status='done' WHERE doc_type='spec'")
    c.execute("UPDATE document_queue SET status='SKIPPED_EXPIRED' WHERE doc_type='image'")
    c.execute("UPDATE document_queue SET retry_count=2 WHERE doc_type='status'")
    c.commit()
    c.close()

    dbmod.enqueue_documents([row(1, auction_date=d)])
    got = {x["doc_type"]: (x["status"], x["retry_count"])
           for x in rows_of(path, "SELECT doc_type, status, retry_count FROM document_queue")}
    check("done 은 done 으로 남는다", got["spec"][0], "done")
    check("★ SKIPPED_EXPIRED 는 되살린다(기일이 안 지났으므로, #254)",
          got["image"][0], "pending")
    check("되살릴 때 재시도 예산도 새로 준다", got["image"][1], 0)
    check("되살리지 않은 행의 retry_count 는 그대로", got["status"][1], 2)

    # 기일이 바뀌어 refresh 가 나가도 status/retry_count 는 안 건드린다
    dbmod.enqueue_documents([row(1, auction_date=days_ahead(50))])
    got2 = {x["doc_type"]: (x["status"], x["retry_count"])
            for x in rows_of(path, "SELECT doc_type, status, retry_count FROM document_queue")}
    check("기일 갱신 후에도 done 유지", got2["spec"][0], "done")
    check("기일 갱신 후에도 retry_count 유지", got2["status"][1], 2)
    # 되살리기는 **한 번**이면 끝이다 - 이미 pending 이므로 두 번째부터는 할 일이 없다.
    r3 = dbmod.enqueue_documents([row(1, auction_date=days_ahead(50))])
    check("이미 되살린 뒤에는 되살릴 것이 없다(멱등)", r3.get("revived_expired"), 0)


# ---------------------------------------------------------------------------
# 4. enqueue_documents — 지난 기일은 애초에 안 넣는다 (1차 방어선)
# ---------------------------------------------------------------------------
def test_enqueue_skips_expired():
    print("\n--- 4. enqueue_documents: 지난 기일 사전 제외 ---")
    path = scratch_db()
    r = dbmod.enqueue_documents([
        row(1, auction_date=days_ahead(-1)),
        row(2, auction_date=days_ahead(5)),
    ])
    check("skipped_expired 1건", r["skipped_expired"], 1)
    check("added 는 살아 있는 1물건 x 4종", r["added"], 4)
    check("DB 에도 4행만", q(path, "SELECT COUNT(*) FROM document_queue"), 4)
    check("지난 사건은 큐에 없다",
          q(path, "SELECT COUNT(*) FROM document_queue WHERE case_no=?",
            ("2026타경000001",)), 0)


# ---------------------------------------------------------------------------
# 5. enqueue_documents — 같은 배치에 같은 키가 두 번 있어도 두 벌 안 생긴다
# ---------------------------------------------------------------------------
def test_enqueue_duplicate_within_batch():
    print("\n--- 5. enqueue_documents: 배치 내 중복 키 ---")
    path = scratch_db()
    d = days_ahead(15)
    r = dbmod.enqueue_documents([row(1, auction_date=d), row(1, auction_date=d)])
    check("added 는 4종뿐", r["added"], 4)
    check("DB 행수 4", q(path, "SELECT COUNT(*) FROM document_queue"), 4)
    check("중복 행 없음",
          q(path, "SELECT COUNT(*) FROM (SELECT court_code,case_no,item_no,doc_type"
                  " FROM document_queue GROUP BY 1,2,3,4 HAVING COUNT(*)>1)"), 0)


# ---------------------------------------------------------------------------
# 6. refresh_queue_priority — 바뀌어야 할 것만 바뀌고, 문장은 묶인다
# ---------------------------------------------------------------------------
def test_refresh_priority_batches():
    print("\n--- 6. refresh_queue_priority: 묶음 갱신 ---")
    path = scratch_db()
    # 기일이 서로 다른 물건 30개 -> 우선순위 1/2/3 이 골고루 생긴다
    rows = [row(i, auction_date=days_ahead(1 + (i % 20))) for i in range(30)]
    dbmod.enqueue_documents(rows)
    total = q(path, "SELECT COUNT(*) FROM document_queue")
    check("대기 행 120개", total, 120)

    # 방금 enqueue 가 이미 올바른 우선순위를 넣었으므로 바뀔 것이 없어야 한다
    n1, kind1, changed1 = count_by_kind(dbmod.refresh_queue_priority)
    check("바뀔 것이 없으면 0건", changed1, 0)
    check_true("그때 문장 수가 10개 미만 (실제 %d)" % n1, n1 < 10, n1)
    # ★ 이것이 핵심 단언이다. 바뀔 것이 없으면 UPDATE 를 **한 번도** 보내지 않아야 한다.
    #   총 문장 수만 보면 건너뛰기를 없애도 안 잡힌다 — id 를 IN 으로 묶으므로
    #   안 바뀐 행을 전부 목록에 넣어도 문장은 3~4개만 는다(2026-08-27 변이로 확인).
    check("무변화면 UPDATE 문장이 0개", kind1.get("UPDATE", 0), 0)

    # 우선순위를 일부러 틀어 놓는다 -> 반드시 되돌려져야 한다
    c = sqlite3.connect(path)
    c.execute("UPDATE document_queue SET priority=9")
    c.commit()
    c.close()
    n2, changed2 = count_statements(dbmod.refresh_queue_priority)
    check("틀어 놓은 120행이 전부 고쳐진다", changed2, 120)
    check("priority=9 가 남지 않는다",
          q(path, "SELECT COUNT(*) FROM document_queue WHERE priority=9"), 0)
    # 목표 우선순위는 1/2/3 셋뿐이라 묶음이 몇 개 안 나와야 한다
    check_true("120행을 고치는 데 문장 20개 미만 (실제 %d)" % n2, n2 < 20, n2)
    print("     (무변화 %d문장 / 120행 수정 %d문장)" % (n1, n2))

    # 계산 결과가 실제로 calc_priority 와 같은지 행 단위로 대조한다
    bad = [x for x in rows_of(path, "SELECT auction_date, priority FROM document_queue")
           if x["priority"] != dbmod.calc_priority(x["auction_date"])]
    check("모든 행이 calc_priority 와 일치", len(bad), 0)


# ---------------------------------------------------------------------------
# 7. refresh_queue_priority — 집어갈 수 없는 행은 건드리지 않는다
# ---------------------------------------------------------------------------
def test_refresh_priority_scope():
    print("\n--- 7. refresh_queue_priority: 대상 범위 ---")
    path = scratch_db()
    dbmod.enqueue_documents([row(1, auction_date=days_ahead(30))])
    c = sqlite3.connect(path)
    c.execute("UPDATE document_queue SET priority=9")
    c.execute("UPDATE document_queue SET status='done' WHERE doc_type='spec'")
    c.execute("UPDATE document_queue SET status='SKIPPED_EXPIRED' WHERE doc_type='image'")
    c.execute("UPDATE document_queue SET status='refresh' WHERE doc_type='status'")
    c.commit()
    c.close()

    changed = dbmod.refresh_queue_priority()
    got = {x["doc_type"]: x["priority"]
           for x in rows_of(path, "SELECT doc_type, priority FROM document_queue")}
    check("done 은 건드리지 않는다", got["spec"], 9)
    check("SKIPPED_EXPIRED 도 건드리지 않는다", got["image"], 9)
    check_true("pending 은 고친다", got["appraisal"] != 9, got["appraisal"])
    check_true("refresh 도 고친다 (Sprint 189)", got["status"] != 9, got["status"])
    check("바뀐 건수는 2건", changed, 2)


# ---------------------------------------------------------------------------
# 8. 실패 주입 — enqueue 중간에 죽으면 **부분 저장이 없어야** 한다
# ---------------------------------------------------------------------------
def test_enqueue_rolls_back_on_failure():
    print("\n--- 8. enqueue_documents: 중간 실패 시 부분 저장 없음 ---")
    path = scratch_db()
    dbmod.enqueue_documents([row(1, auction_date=days_ahead(10))])
    before = q(path, "SELECT COUNT(*) FROM document_queue")
    check("사전 상태 4행", before, 4)

    # commit 직전에 터뜨린다 - 새 물건 20개가 이미 executemany 로 들어간 뒤다
    real_conn = dbmod.get_connection

    class Boom(Exception):
        pass

    class Wrapper:
        def __init__(self, inner):
            self._inner = inner

        def commit(self):
            raise Boom("주입된 실패")

        def __getattr__(self, n):
            return getattr(self._inner, n)

    dbmod.get_connection = lambda *a, **k: Wrapper(real_conn(*a, **k))
    raised = None
    try:
        dbmod.enqueue_documents([row(i, auction_date=days_ahead(10))
                                 for i in range(100, 120)])
    except Boom as e:
        raised = e
    finally:
        dbmod.get_connection = real_conn

    check_true("실패가 예외로 올라온다", raised is not None, raised)
    check("커밋되지 않은 20물건이 남지 않는다",
          q(path, "SELECT COUNT(*) FROM document_queue"), before)

    # 그리고 재실행하면 정상적으로 들어온다(이어받기)
    r = dbmod.enqueue_documents([row(i, auction_date=days_ahead(10))
                                 for i in range(100, 120)])
    check("재실행으로 20물건 x 4종이 들어온다", r["added"], 80)
    check("최종 행수 84", q(path, "SELECT COUNT(*) FROM document_queue"), before + 80)


# ---------------------------------------------------------------------------
# 9. 멱등성 — 3회 반복 실행이 완전히 같은 결과
# ---------------------------------------------------------------------------
def test_idempotent_repeat():
    print("\n--- 9. 3회 반복 멱등성 ---")
    path = scratch_db()
    rows = [row(i, auction_date=days_ahead(3 + (i % 25))) for i in range(40)]
    snaps = []
    for _ in range(3):
        dbmod.enqueue_documents(rows)
        dbmod.refresh_queue_priority()
        snaps.append(rows_of(
            path, "SELECT court_code, case_no, item_no, doc_type, priority,"
                  " auction_date, status, retry_count FROM document_queue"
                  " ORDER BY case_no, doc_type"))
    check_true("1회차 == 2회차", snaps[0] == snaps[1], "다름")
    check_true("2회차 == 3회차", snaps[1] == snaps[2], "다름")
    check("중복 행 없음",
          q(path, "SELECT COUNT(*) FROM (SELECT court_code,case_no,item_no,doc_type"
                  " FROM document_queue GROUP BY 1,2,3,4 HAVING COUNT(*)>1)"), 0)
    check("행수 40 x 4", q(path, "SELECT COUNT(*) FROM document_queue"), 160)


# ---------------------------------------------------------------------------
# 10. SQL 바인딩 변수 상한 보호 (#243 계열) — **작은 데이터로** 검증한다
#
#    `enqueue_documents()` 의 선조회와 `refresh_queue_priority()` 의 IN 목록은 둘 다
#    `chunked_for_sql()` 로 나눠 보낸다. 나누지 않으면 느려지는 것이 아니라
#    `OperationalError: too many SQL variables` 로 **그날 작업이 통째로 실패한다.**
#
#    문제는 이 보호가 기본 상한(이 환경 32,766)에서는 수만 행을 넣어야 발동한다는 것이다.
#    그래서 지금까지 검사가 없었고, 변이로 청크 나누기를 지워도 아무도 못 잡았다
#    (2026-08-27 실측: 변이 2종 생존).
#
#    ★ 상한을 **낮추면** 작은 데이터로 같은 경계를 만들 수 있다.
#      `sqlite3.Connection.setlimit()` (Python 3.11+) 로 커넥션의 변수 상한을 10으로
#      내리면, 나누지 않는 구현은 20행에서 바로 죽는다. 대량 DB 없이 계약을 지킨다.
#
#    `sql_variable_limit()` 이 `conn.getlimit()` 을 쓰므로 낮춘 값이 그대로 반영된다 —
#    즉 이 테스트는 "상한을 실제로 물어본다"는 성질까지 함께 고정한다(상수를 박으면 깨진다).
# ---------------------------------------------------------------------------
def test_variable_limit_protection_with_small_data():
    print("\n--- 10. SQL 변수 상한 보호 (상한을 낮춰 소량으로 검증) ---")
    if not hasattr(sqlite3.Connection, "setlimit"):
        print("[SKIP] 이 파이썬에는 setlimit 이 없다 (3.11+ 필요)")
        return

    path = scratch_db()
    LOW = 10
    orig = dbmod.get_connection

    def low_limit_conn(*a, **kw):
        conn = orig(*a, **kw)
        conn.setlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER, LOW)
        return conn

    d = days_ahead(12)
    rows = [row(i, auction_date=d) for i in range(20)]

    dbmod.get_connection = low_limit_conn
    try:
        # 전제: 상한이 정말 낮아졌는지부터 확인한다(안 그러면 이 검사는 공허하다)
        c = low_limit_conn()
        try:
            check("전제: 커넥션 변수 상한이 %d 로 내려갔다" % LOW,
                  dbmod.sql_variable_limit(c), LOW)
        finally:
            c.close()

        err = None
        try:
            r = dbmod.enqueue_documents(rows)
        except sqlite3.OperationalError as e:      # noqa: BLE001
            err = e
        check_true("enqueue_documents 가 낮은 상한에서도 살아남는다", err is None, err)
        if err is None:
            check("20물건 x 4종이 전부 들어온다", r["added"], 80)

        err2 = None
        try:
            changed = dbmod.refresh_queue_priority()
        except sqlite3.OperationalError as e:      # noqa: BLE001
            err2 = e
        check_true("refresh_queue_priority 도 살아남는다", err2 is None, err2)

        # 실제로 고쳐야 하는 상황에서도(IN 목록이 커지는 쪽) 살아남아야 한다
        c = sqlite3.connect(path)
        c.execute("UPDATE document_queue SET priority=9")
        c.commit()
        c.close()
        err3 = None
        try:
            changed = dbmod.refresh_queue_priority()
        except sqlite3.OperationalError as e:      # noqa: BLE001
            err3 = e
            changed = -1
        check_true("80행을 고치는 동안에도 살아남는다", err3 is None, err3)
        check("80행이 전부 고쳐진다", changed, 80)
    finally:
        dbmod.get_connection = orig

    check("정상 상한으로 돌아온 뒤에도 정상", dbmod.refresh_queue_priority(), 0)


if __name__ == "__main__":
    try:
        test_enqueue_inserts_then_goes_quiet()
        test_enqueue_refreshes_changed_auction_date()
        test_enqueue_preserves_existing_status()
        test_enqueue_skips_expired()
        test_enqueue_duplicate_within_batch()
        test_refresh_priority_batches()
        test_refresh_priority_scope()
        test_enqueue_rolls_back_on_failure()
        test_idempotent_repeat()
        test_variable_limit_protection_with_small_data()
    finally:
        for d in _TMP:
            shutil.rmtree(d, ignore_errors=True)
    print("")
    if failures:
        print("FAILED %d: %s" % (len(failures), ", ".join(failures)))
        sys.exit(1)
    print("ALL PASS")
    sys.exit(0)
