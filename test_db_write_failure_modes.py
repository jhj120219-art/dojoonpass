# -*- coding: utf-8 -*-
"""DB 쓰기 경로의 **장애 거동** 회귀 — 2026-08-31 신설.

## 왜 이 파일이 생겼나 — `docs/BUGS.md` #268 이 없는 검사를 가리키고 있었다

BUGS #268 은 2026-08-28 에 **해결**로 적혀 있고, 근거로 검사 두 벌을 이름까지 들어
설명한다(`test_db_write_failure_modes.py` 6절 30단언 / `test_queue_multiprocess_claim.py`
3절 14단언). 2026-08-31 실측: **저장소에 그 두 파일이 없다.** git 이력에도 없다.
즉 "고정했다"고 적힌 거동 중 실제로 고정된 것은 행 단위 격리 하나뿐이었다
(`test_auction_identity.py` §3 — 그것은 실재한다).

이 파일이 그 공백을 메운다. 다만 **BUGS 의 서술을 그대로 베끼지 않는다** — 각 거동을
스크래치 DB 에서 먼저 재고, 잰 값으로 단언을 세웠다(아래 각 절에 실측값을 적어 둔다).

## 왜 이 거동들이 중요한가

`upsert_batch()` 의 계수(`inserted/updated/unchanged/failed`)는 `CrawlOutcome.persisted`
를 거쳐 크롤의 **종료 코드**가 된다. 틀린 숫자는 곧 `run_daily.bat` 의 잘못된 판정이고,
"실패했는데 성공으로 끝났다"가 된다. 그래서 여기서 보는 것은 성능이 아니라
**실패가 거짓 성공이 되지 않는가**다.

## 무엇을 보지 않는가 (중복 방지)

행 단위 격리(깨진 행 하나가 배치를 죽이지 않는다 / 실패 행은 DB 에 남지 않는다)는
`test_auction_identity.py` §3 이 이미 촘촘히 고정한다. 여기서 다시 만들지 않는다.

    python test_db_write_failure_modes.py

운영 DB 는 건드리지 않는다 — 임시 디렉터리에 부트스트랩 3단계로 만든 스크래치 DB 에서만 돈다.
출력은 ASCII 위주로 쓴다(콘솔 cp949).
"""
import contextlib
import io
import os
import shutil
import sqlite3
import subprocess
import sys
import time
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

ROOT = os.path.dirname(os.path.abspath(__file__))
failures = []
_TMP = []


def check(name, actual, expected):
    ok = actual == expected
    print("[%s] %s: %r (expected %r)" % ("PASS" if ok else "FAIL", name, actual, expected))
    if not ok:
        failures.append(name)


def check_true(name, cond, detail=""):
    print("[%s] %s%s" % ("PASS" if cond else "FAIL", name, ("" if cond else " -- " + str(detail))))
    if not cond:
        failures.append(name)


def fresh_db():
    """실제 부트스트랩 3단계로 스키마를 만든다 — 손으로 베끼지 않는다.

    `test_queue_safety_invariants.py` 의 같은 이름 헬퍼와 같은 방식이다.
    """
    tmp = tempfile.mkdtemp(prefix="dbwf_")
    _TMP.append(tmp)
    path = os.path.join(tmp, "auction.db")
    import storage.database as db
    import storage.migrate_v4_1 as mig
    import storage.migrations.run_migrations as runmig
    db.DB_PATH = path
    with contextlib.redirect_stdout(io.StringIO()):
        db.init_db()
        mig.migrate()
        runmig.run()
    return db, path


def rows(n, start=0, price=1000):
    """크롤러가 `upsert_batch()` 에 넘기는 모양 그대로."""
    return [{
        "court_code": "B1", "court_name": "테스트지원",
        "case_no": "2026타경%d" % (start + i), "item_no": "1",
        "property_type": "아파트", "address": "서울 어딘가 %d" % i,
        "sido": "서울", "sigungu": "강남구", "dong": "역삼동",
        "appraisal_price": price, "minimum_bid_price": price // 2,
        "auction_date": "2026-12-01", "status": "유찰 1회",
        "crawl_date": "2026-08-31",
    } for i in range(n)]


def count(path, table="auction"):
    c = sqlite3.connect(path)
    try:
        return c.execute("SELECT COUNT(*) FROM %s" % table).fetchone()[0]
    finally:
        c.close()


_REAL_CONNECT = sqlite3.connect


@contextlib.contextmanager
def connection_factory(factory):
    """`storage.database.get_connection()` 이 만드는 커넥션을 갈아 끼운다.

    제품 코드를 고치지 않고 장애를 주입하는 유일한 자리다 — `get_connection()` 은
    `sqlite3.connect()` 를 부르므로 그것만 감싼다.
    """
    def fake(*a, **k):
        k["factory"] = factory
        return _REAL_CONNECT(*a, **k)
    sqlite3.connect = fake
    try:
        yield
    finally:
        sqlite3.connect = _REAL_CONNECT


# ---------------------------------------------------------------------------
# 1. 트랜잭션 모양 — 배치 하나 = 트랜잭션 하나
# ---------------------------------------------------------------------------
def test_transaction_shape():
    """실측(2026-08-31, n=50): commit 1 / rollback 0 / 행당 문장 1 / 배치당 SELECT 2.

    #256 이 계수를 "행마다 묻기"에서 "배치 앞뒤로 두 번 세기"로 바꿔 얻은 이득이다.
    행마다 SELECT 를 되돌리면 여기서 잡힌다.
    """
    print("\n--- 1. 트랜잭션 모양 (배치 하나 = 트랜잭션 하나) ---")
    db, path = fresh_db()

    class Counting(sqlite3.Connection):
        stats = None

        def execute(self, sql, *a, **k):
            head = sql.strip().split()[0].upper()
            Counting.stats[head] = Counting.stats.get(head, 0) + 1
            return super().execute(sql, *a, **k)

        def commit(self):
            Counting.stats["commit"] += 1
            return super().commit()

        def rollback(self):
            Counting.stats["rollback"] += 1
            return super().rollback()

    n = 50
    for label, batch in (("신규", rows(n)), ("변화없음", rows(n))):
        Counting.stats = {"commit": 0, "rollback": 0}
        with connection_factory(Counting):
            res = db.upsert_batch(batch)
        st = Counting.stats
        check_true("%s: 배치당 commit 1회" % label, st["commit"] == 1, st["commit"])
        check_true("%s: rollback 없음" % label, st["rollback"] == 0, st["rollback"])
        check_true("%s: 행당 쓰기 문장 1개" % label,
                   st.get("INSERT", 0) == n, st.get("INSERT"))
        check_true("%s: 배치당 SELECT 2회 (행마다 묻지 않는다)" % label,
                   st.get("SELECT", 0) == 2, st.get("SELECT"))
        check_true("%s: 계수 합이 입력 행 수와 같다" % label,
                   sum(res[k] for k in ("inserted", "updated", "unchanged", "failed")) == n, res)

    # 계수 자체도 확인 — 두 번째 배치는 값이 같으므로 전부 unchanged 여야 한다.
    check("두 번째 배치는 전부 unchanged", db.upsert_batch(rows(n))["unchanged"], n)


# ---------------------------------------------------------------------------
# 2. 커밋 실패 — 그 배치는 한 행도 남지 않는다
# ---------------------------------------------------------------------------
def test_commit_failure_leaves_nothing():
    """실측: `OperationalError` 가 그대로 올라오고 행 수가 변하지 않는다.

    조용히 성공하면 크롤은 "저장했다"로 끝나는데 DB 에는 아무것도 없다 —
    다음 날 검색이 비는데 로그에는 성공만 남는다.
    """
    print("\n--- 2. 커밋이 실패하면 그 배치는 한 행도 남지 않는다 ---")
    db, path = fresh_db()
    db.upsert_batch(rows(10))
    before = count(path)
    check_true("전제: 정상 배치가 저장돼 있다", before == 10, before)

    class BoomCommit(sqlite3.Connection):
        def commit(self):
            raise sqlite3.OperationalError("QA 주입: 커밋 실패")

    raised = None
    with connection_factory(BoomCommit):
        try:
            db.upsert_batch(rows(20, start=9000))
        except Exception as exc:                      # noqa: BLE001
            raised = type(exc).__name__

    check_true("예외가 삼켜지지 않고 올라온다", raised is not None, raised)
    check("커밋 실패한 배치의 행이 하나도 남지 않는다", count(path), before)


# ---------------------------------------------------------------------------
# 3. DB 잠김 — 조용히 성공하지 않는다
# ---------------------------------------------------------------------------
def test_locked_db_does_not_silently_succeed():
    """실측: 다른 커넥션이 EXCLUSIVE 를 쥐고 있으면 `OperationalError: database is locked`.

    여기서 예외가 아니라 0건 성공으로 끝나면, 크롤은 "오늘 새 물건이 없었다"로
    보고하고 아무도 이상을 눈치채지 못한다.
    """
    print("\n--- 3. DB 가 잠겨 있으면 조용히 성공하지 않는다 ---")
    db, path = fresh_db()
    before = count(path)

    locker = _REAL_CONNECT(path, timeout=0.1)
    locker.execute("BEGIN EXCLUSIVE")
    raised = None
    try:
        db.upsert_batch(rows(5, start=8000))
    except Exception as exc:                          # noqa: BLE001
        raised = "%s: %s" % (type(exc).__name__, exc)
    finally:
        locker.rollback()
        locker.close()

    check_true("잠김이 예외로 드러난다", raised is not None and "locked" in raised.lower(), raised)
    check("잠긴 동안 아무 행도 쓰이지 않았다", count(path), before)
    # 잠금이 풀린 뒤에는 정상 동작해야 한다 — 일시적 장애가 영구 손상이 되면 안 된다.
    check("잠금 해제 후 같은 배치가 정상 저장된다",
          db.upsert_batch(rows(5, start=8000))["inserted"], 5)


# ---------------------------------------------------------------------------
# 4. 프로세스 사망 — 커밋 전에 죽으면 한 행도 남지 않는다
# ---------------------------------------------------------------------------
_CHILD = r'''
import io, os, sys, contextlib, sqlite3
sys.path.insert(0, %(root)r)
import storage.database as db
db.DB_PATH = %(path)r

_real = sqlite3.connect
class DieBeforeCommit(sqlite3.Connection):
    def commit(self):
        # 커밋 직전에 프로세스가 통째로 사라진다(예외가 아니라 죽음).
        os._exit(9)

def fake(*a, **k):
    k["factory"] = DieBeforeCommit
    return _real(*a, **k)
sqlite3.connect = fake

rows = [{
    "court_code": "B1", "court_name": "t", "case_no": "2026타경%%d" %% (70000 + i),
    "item_no": "1", "property_type": "아파트", "address": "a", "sido": "서울",
    "sigungu": "강남구", "dong": "역삼동", "appraisal_price": 1000,
    "minimum_bid_price": 500, "auction_date": "2026-12-01",
    "status": "유찰 1회", "crawl_date": "2026-08-31",
} for i in range(500)]
with contextlib.redirect_stdout(io.StringIO()):
    db.upsert_batch(rows)
print("NOT_REACHED")
'''


def test_process_death_before_commit_leaves_nothing():
    """커밋 직전에 `os._exit(9)` 로 죽는 자식 프로세스를 실제로 띄운다.

    예외 주입과 다른 점: `finally`/`rollback` 이 **아예 돌지 않는다.** 그래도 남으면
    안 되는 이유는 SQLite 가 저널로 원자성을 보장하기 때문이고, 그 보장이 이 코드의
    트랜잭션 사용 방식에서도 유지되는지를 본다(자동 커밋 모드로 새면 500행이 남는다).
    """
    print("\n--- 4. 커밋 전에 프로세스가 죽으면 한 행도 남지 않는다 ---")
    db, path = fresh_db()
    db.upsert_batch(rows(3))
    before = count(path)

    script = _CHILD % {"root": ROOT, "path": path}
    proc = subprocess.run([sys.executable, "-X", "utf8", "-c", script],
                          capture_output=True, text=True, timeout=180)
    check("자식이 커밋 직전에 죽었다(종료코드 9)", proc.returncode, 9)
    check_true("자식이 끝까지 가지 않았다", "NOT_REACHED" not in (proc.stdout or ""),
               (proc.stdout or "")[:80])
    check("죽은 배치의 500행이 하나도 남지 않았다", count(path), before)

    # 그리고 DB 가 여전히 멀쩡해야 한다 — 손상됐으면 다음 크롤이 통째로 막힌다.
    check("죽은 뒤에도 DB 가 정상이다(무결성)",
          sqlite3.connect(path).execute("PRAGMA integrity_check").fetchone()[0], "ok")
    check("죽은 뒤에도 새 배치를 저장할 수 있다",
          db.upsert_batch(rows(4, start=6000))["inserted"], 4)


# ---------------------------------------------------------------------------
# 5. 실패 뒤 재실행 — 앞선 실패가 다음 배치를 오염시키지 않는다 + 멱등
# ---------------------------------------------------------------------------
def test_rerun_after_failure_is_clean_and_idempotent():
    print("\n--- 5. 실패 뒤 재실행이 깨끗하고 멱등하다 ---")
    db, path = fresh_db()

    class BoomCommit(sqlite3.Connection):
        def commit(self):
            raise sqlite3.OperationalError("QA 주입: 커밋 실패")

    with connection_factory(BoomCommit):
        try:
            db.upsert_batch(rows(10, start=5000))
        except Exception:                             # noqa: BLE001
            pass

    first = db.upsert_batch(rows(10, start=5000))
    check("실패했던 배치를 다시 넣으면 전부 신규다(앞선 실패가 남기지 않았다)",
          first["inserted"], 10)
    second = db.upsert_batch(rows(10, start=5000))
    check("같은 배치를 또 넣으면 전부 unchanged 다(멱등)", second["unchanged"], 10)
    check("중복 행이 생기지 않았다", count(path), 10)


# ---------------------------------------------------------------------------
# 6. 큐 claim 배타성 — **스레드가 아니라 진짜 프로세스** 두 개
# ---------------------------------------------------------------------------
_CLAIMER = r'''
import io, os, sys, json, time, contextlib
sys.path.insert(0, %(root)r)
import storage.database as db
db.DB_PATH = %(path)r

# * 출발 신호를 기다린다. 이것이 없으면 먼저 뜬 프로세스가 큐를 통째로 비우고
#   두 번째는 빈 큐를 보게 된다 - 동시성을 재려던 검사가 순차 실행을 재게 된다
#   (2026-08-31 첫 실행에서 실제로 40:0 이 나왔다).
go = %(go)r
while not os.path.exists(go):
    time.sleep(0.01)

got = []
with contextlib.redirect_stdout(io.StringIO()):
    while True:
        item = db.claim_next_queue_item()
        if not item:
            break
        got.append(item["id"])
        time.sleep(0.005)     # 서로 끼어들 틈을 준다
sys.stderr.write(json.dumps(got))
'''


def test_queue_claim_is_exclusive_across_processes():
    """워커를 두 프로세스로 띄워 같은 행을 두 번 집지 않는지 본다.

    스레드 검사(`test_queue_safety_invariants.py`)와 다른 점: 프로세스가 나뉘면
    GIL 도 같은 커넥션도 공유되지 않고 **SQLite 파일 잠금만** 남는다. claim 의 CAS
    (`UPDATE ... WHERE id=? AND status=?`)가 그 조건에서도 성립해야 한다.
    같은 문서를 두 번 수집하면 브라우저 예산이 두 배로 든다.
    """
    print("\n--- 6. 큐 claim 이 프로세스 사이에서도 배타적이다 ---")
    db, path = fresh_db()

    n = 40
    conn = sqlite3.connect(path)
    try:
        conn.executemany(
            "INSERT INTO document_queue (court_code, case_no, item_no, doc_type,"
            " priority, auction_date, status, retry_count, enqueued_at)"
            " VALUES (?,?,?,?,1,'2026-12-01','pending',0,'2026-08-31T00:00:00')",
            [("B1", "2026타경%d" % (4000 + i), "1", "spec") for i in range(n)])
        conn.commit()
    finally:
        conn.close()
    check("전제: 큐에 %d행을 넣었다" % n,
          count(path, "document_queue"), n)

    go = os.path.join(os.path.dirname(path), "GO")
    script = _CLAIMER % {"root": ROOT, "path": path, "go": go}
    procs = [subprocess.Popen([sys.executable, "-X", "utf8", "-c", script],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
             for _ in range(2)]
    # 둘 다 import 를 끝내고 신호를 기다리게 둔 뒤 동시에 출발시킨다.
    time.sleep(2.0)
    with open(go, "w") as fh:
        fh.write("go")
    claimed = []
    for p in procs:
        _out, err = p.communicate(timeout=300)
        try:
            claimed.append(json.loads(err.strip().splitlines()[-1]))
        except Exception:                             # noqa: BLE001
            claimed.append([])

    a, b = claimed
    both = sorted(a + b)
    check_true("두 프로세스가 실제로 나눠 집었다(검사가 공허하지 않다)",
               len(a) > 0 and len(b) > 0, (len(a), len(b)))
    check("★ 같은 행을 두 번 집은 경우가 없다", len(both), len(set(both)))
    check("큐를 남김없이 소진했다", len(both), n)
    left = sqlite3.connect(path).execute(
        "SELECT COUNT(*) FROM document_queue WHERE status='pending'").fetchone()[0]
    check("pending 이 남아 있지 않다", left, 0)


import json  # noqa: E402  (자식 스크립트 문자열 뒤에서만 쓴다)


def run():
    try:
        test_transaction_shape()
        test_commit_failure_leaves_nothing()
        test_locked_db_does_not_silently_succeed()
        test_process_death_before_commit_leaves_nothing()
        test_rerun_after_failure_is_clean_and_idempotent()
        test_queue_claim_is_exclusive_across_processes()
    finally:
        for d in _TMP:
            shutil.rmtree(d, ignore_errors=True)

    print("\n" + "=" * 55)
    if failures:
        print("FAILED (%d): %s" % (len(failures), ", ".join(failures)))
        return 1
    print("ALL TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(run())
