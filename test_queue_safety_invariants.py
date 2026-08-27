"""큐/체크포인트 **안전장치 불변식** 회귀 테스트.

운영 DB 는 건드리지 않는다 — 임시 디렉터리에 실제 부트스트랩 3단계로 만든 스크래치 DB
에서만 돈다. 브라우저도 대량 데이터도 필요 없다.

왜 이 파일이 생겼나 (2026-08-27, 변이 감사)
---------------------------------------------------------------------------
`storage/database.py` / `storage/checkpoint.py` / `crawler/resume.py` 의 **오래된
안전장치**에 결함을 하나씩 심고 기존 스위트 8개를 돌려 봤다. 결과:

    잡음 3 / 놓침 7

즉 이 저장소가 여러 스프린트에 걸쳐 쌓아 온 방어 중 **일곱 개가 아무 검사에도
묶여 있지 않았다.** 전부 "지금은 맞게 동작하지만, 누가 지워도 스위트가 초록"인 상태다.

    놓친 것                                      지우면 무슨 일이 나는가
    ------------------------------------------  ----------------------------------------
    claim 의 CAS 조건(`AND status=?`)            워커 둘이 같은 행을 집는다 -> 같은 문서 2회 수집
    claim 경쟁 패배 판정(`if not cur.rowcount`)   진 것을 이긴 것으로 알고 남의 일을 한다
    MAX_DOC_RETRY = 3                            성공할 수 없는 항목을 영원히 재시도한다
    RETRY_INTERVAL_MINUTES = 30                  같은 행을 몇 분 만에 3회 태워 예산을 소진한다
    CLAIM_RACE_MAX_ATTEMPTS = 5                  경쟁에 지면 큐가 비었다고 오판(BUGS #130)
    `_NOW_LOCAL` 로컬시각 기준                    UTC 로 되돌아가 30분이 **9시간 30분**이 된다
    체크포인트 `os.replace()`                     Windows 에서 재저장이 실패 -> 진행 상황 유실

마지막 둘은 이 저장소가 **이미 사고로 겪고 고친 것**이다(`_NOW_LOCAL` 주석,
`test_checkpoint_atomicity` 도입 사유). 고친 사실이 검사로 묶이지 않으면 같은 사고가
같은 자리에서 다시 난다.

    python test_queue_safety_invariants.py
"""
import sys
import os
import io
import shutil
import sqlite3
import tempfile
import logging
import contextlib
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

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


def fresh_db():
    """실제 부트스트랩 3단계로 스키마를 만든다 — 손으로 베끼지 않는다."""
    tmp = tempfile.mkdtemp(prefix="qsi_")
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


def seed_queue(path, rows):
    """(court_code, case_no, item_no, doc_type, status, retry_count, last_attempt_at)"""
    c = sqlite3.connect(path)
    try:
        c.executemany(
            "INSERT INTO document_queue (court_code, case_no, item_no, doc_type,"
            " priority, auction_date, status, retry_count, last_attempt_at, enqueued_at)"
            " VALUES (?,?,?,?,1,?,?,?,?,?)",
            [(r[0], r[1], r[2], r[3], future(), r[4], r[5], r[6],
              datetime.now().isoformat()) for r in rows])
        c.commit()
    finally:
        c.close()


def future(days=30):
    return (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d")


def q(path, sql, args=()):
    c = sqlite3.connect(path)
    try:
        r = c.execute(sql, args).fetchone()
        return r[0] if r else None
    finally:
        c.close()


class InterleavingConn(object):
    """`UPDATE document_queue` **직전**에 콜백을 실행하는 커넥션 래퍼.

    claim 의 CAS 는 "SELECT 로 고른 뒤 UPDATE 하기까지 사이에 남이 채 갔는가" 를
    막는 장치다. 그 사이를 실제로 벌리지 않으면 검사가 성립하지 않는다.
    (`test_worker_batching.py` 가 쓰는 것과 같은 기법)
    """

    def __init__(self, conn, on_update):
        self._conn = conn
        self._on_update = on_update
        self.fired = 0

    def execute(self, sql, *a, **kw):
        if sql.lstrip().upper().startswith("UPDATE DOCUMENT_QUEUE") and self.fired == 0:
            self.fired += 1
            self._on_update()
        return self._conn.execute(sql, *a, **kw)

    def __getattr__(self, name):
        return getattr(self._conn, name)


# ---------------------------------------------------------------------------
# 1. claim 의 CAS — SELECT 와 UPDATE 사이에 남이 채 가면 **집지 않는다**
# ---------------------------------------------------------------------------
def test_claim_cas_rejects_row_taken_meanwhile():
    print("\n--- 1. claim CAS: 사이에 채인 행은 집지 않는다 ---")
    db, path = fresh_db()
    seed_queue(path, [("B1", "2026타경1", "1", "spec", "pending", 0, None)])

    stolen = {"done": False}

    def competitor():
        """claim 이 UPDATE 를 보내기 **직전**에 다른 실행이 같은 행을 가져간다."""
        if stolen["done"]:
            return
        stolen["done"] = True
        c = sqlite3.connect(path)
        try:
            c.execute("UPDATE document_queue SET status='in_progress'"
                      " WHERE status='pending'")
            c.commit()
        finally:
            c.close()

    real_get = db.get_connection
    wrapper = {"w": None}

    def fake_get(*a, **kw):
        conn = real_get(*a, **kw)
        if wrapper["w"] is None:
            wrapper["w"] = InterleavingConn(conn, competitor)
            return wrapper["w"]
        return conn

    db.get_connection = fake_get
    try:
        got = db.claim_next_queue_item()
    finally:
        db.get_connection = real_get

    check_true("경쟁자가 실제로 끼어들었다(검사가 공허하지 않다)",
               wrapper["w"] is not None and wrapper["w"].fired == 1,
               wrapper["w"].fired if wrapper["w"] else "래퍼 미설치")
    # 남이 가져간 행을 우리가 또 집으면 **같은 문서를 두 번 수집**한다.
    check("채인 행을 집지 않는다", got, None)
    # 그리고 행 상태는 경쟁자가 만든 그대로여야 한다(우리가 덮어쓰지 않았다)
    check("경쟁자의 상태가 보존된다",
          q(path, "SELECT status FROM document_queue"), "in_progress")


# ---------------------------------------------------------------------------
# 2. 재시도 예산 — MAX_DOC_RETRY 를 넘으면 더 이상 집히지 않는다
# ---------------------------------------------------------------------------
def test_retry_budget_is_finite():
    """예산은 `mark_queue_failed()` 가 집행한다 — 소진되면 'failed' 로 굳는다.

    ★ 처음 이 검사를 `status='failed'` 인 행을 claim 해 보는 방식으로 썼다가 틀렸다.
      `QUEUE_CLAIMABLE_STATUSES` 는 ('pending', 'refresh') 뿐이라 failed 는 애초에
      집히지 않는다 — 그러면 "예산이 남은 행도 안 집힌다"가 되어 검사가 성립하지 않는다.
      예산의 실제 집행 지점은 `mark_queue_failed():2241` 의 `new_retry >= MAX_DOC_RETRY` 다.
    """
    print("\n--- 2. 재시도 예산 상한 ---")
    db, path = fresh_db()
    # ★ 여기서 **반드시 빠져나간다.** 아래 루프가 `MAX_DOC_RETRY` 만큼 도는데,
    #   상한이 터무니없이 크면(=이 장치가 무력화된 상태) 검사가 실패하는 대신
    #   **몇 시간을 매달린다.** 2026-08-27 변이 테스트에서 실제로 그랬다 —
    #   `MAX_DOC_RETRY = 99999` 변이가 이 파일을 900초 타임아웃으로 끌고 갔고,
    #   그러면 "잡았다"가 아니라 "하네스가 죽었다"가 된다.
    #   느리게 실패하는 검사는 아무도 안 돌린다. 빠르게, 이유를 말하고 실패한다.
    if not (0 < db.MAX_DOC_RETRY < 100):
        check_true("재시도 상한이 합리적 범위(0 < MAX_DOC_RETRY < 100)",
                   False, db.MAX_DOC_RETRY)
        return
    check_true("검사가 공허하지 않다(상한이 유한하다)",
               0 < db.MAX_DOC_RETRY < 100, db.MAX_DOC_RETRY)

    seed_queue(path, [("B1", "2026타경1", "1", "spec", "pending", 0, None)])

    # 예산이 남아 있는 동안은 실패해도 **다시 대기로 돌아온다**
    for attempt in range(db.MAX_DOC_RETRY - 1):
        got = db.claim_next_queue_item()
        check_true("%d번째 시도에서 집힌다" % (attempt + 1), got is not None, got)
        if not got:
            return
        db.mark_queue_failed(got["id"], got["retry_count"],
                             claim_token=got.get("claim_token"))
        # 간격 때문에 바로는 못 집으므로 시계를 뒤로 돌려 놓는다(간격 자체는 3번이 검사)
        c = sqlite3.connect(path)
        c.execute("UPDATE document_queue SET last_attempt_at=?",
                  ((datetime.now() - timedelta(hours=48)).isoformat(),))
        c.commit()
        c.close()
        check_true("예산이 남아 있으면 대기로 돌아온다",
                   q(path, "SELECT status FROM document_queue") in ("pending", "refresh"),
                   q(path, "SELECT status FROM document_queue"))

    # 마지막 한 번 더 실패하면 예산이 소진되어 'failed' 로 굳는다
    got = db.claim_next_queue_item()
    check_true("마지막 예산으로 집힌다", got is not None, got)
    if got:
        db.mark_queue_failed(got["id"], got["retry_count"],
                             claim_token=got.get("claim_token"))
    check("예산 소진 후 'failed' 로 굳는다",
          q(path, "SELECT status FROM document_queue"), "failed")
    check("retry_count 가 상한에 도달했다",
          q(path, "SELECT retry_count FROM document_queue"), db.MAX_DOC_RETRY)

    # 시계를 아무리 뒤로 돌려도 다시 집히지 않는다 — 영원한 재시도를 막는 것이 이 장치다
    c = sqlite3.connect(path)
    c.execute("UPDATE document_queue SET last_attempt_at=?",
              ((datetime.now() - timedelta(days=30)).isoformat(),))
    c.commit()
    c.close()
    check("소진된 행은 시간이 지나도 집히지 않는다", db.claim_next_queue_item(), None)


# ---------------------------------------------------------------------------
# 3. 재시도 간격 — 방금 실패한 행은 바로 다시 집히지 않는다
#
#    ★ 이 검사는 `_NOW_LOCAL` 의 **시각 기준**까지 함께 지킨다.
#      저장값은 `datetime.now()`(로컬)인데 비교를 `datetime('now')`(UTC)로 하면
#      한국에서 30분이 **9시간 30분**이 된다 — doc_worker 는 02:00~04:00 두 시간만
#      도므로 그 밤에 재시도가 영영 오지 않는다. 아래 "1시간 전" 행이 그 경계를 가른다.
# ---------------------------------------------------------------------------
def test_retry_interval_uses_local_clock():
    print("\n--- 3. 재시도 간격 + 시각 기준(로컬) ---")
    db, path = fresh_db()
    check_true("검사가 공허하지 않다(간격이 0보다 크다)",
               db.RETRY_INTERVAL_MINUTES > 0, db.RETRY_INTERVAL_MINUTES)

    # ★ 상태는 **pending** 이어야 한다. 간격 조건은 claim 의 WHERE 에 있고,
    #   claim 은 claimable(pending/refresh) 만 본다 — failed 로 두면 간격과 무관하게
    #   안 집혀서 검사가 공허해진다(2026-08-27 실제로 그렇게 썼다가 잡았다).
    just_now = datetime.now().isoformat()
    seed_queue(path, [("B1", "2026타경1", "1", "spec", "pending", 1, just_now)])
    check("방금 시도한 행은 아직 집히지 않는다", db.claim_next_queue_item(), None)

    # 간격의 두 배가 지난 행은 집혀야 한다.
    # UTC 로 비교하면(=결함) 한국에서는 9시간 30분이 지나야 하므로 이 행이 안 집힌다.
    passed = (datetime.now()
              - timedelta(minutes=db.RETRY_INTERVAL_MINUTES * 2)).isoformat()
    c = sqlite3.connect(path)
    c.execute("UPDATE document_queue SET last_attempt_at=?", (passed,))
    c.commit()
    c.close()
    got = db.claim_next_queue_item()
    check_true("간격이 지난 행은 집힌다 (UTC 로 비교하면 여기서 실패한다)",
               got is not None, got)


# ---------------------------------------------------------------------------
# 4. claim 경쟁 상한 — 경쟁에 져도 "큐가 비었다"로 끝내지 않는다 (BUGS #130)
# ---------------------------------------------------------------------------
def test_claim_race_retries_other_rows():
    print("\n--- 4. 경쟁 패배 != 큐 비었음 (BUGS #130) ---")
    db, path = fresh_db()
    check_true("검사가 공허하지 않다(재시도 상한이 1 이상)",
               db.CLAIM_RACE_MAX_ATTEMPTS >= 1, db.CLAIM_RACE_MAX_ATTEMPTS)

    # 두 행. 경쟁자는 **첫 UPDATE 직전에 한 번만** 끼어들어 우선순위가 높은 쪽을 채 간다.
    seed_queue(path, [
        ("B1", "2026타경1", "1", "spec", "pending", 0, None),
        ("B1", "2026타경2", "1", "spec", "pending", 0, None),
    ])

    fired = {"n": 0}

    def competitor():
        fired["n"] += 1
        c = sqlite3.connect(path)
        try:
            # 지금 claim 이 고른 그 행 하나만 채 간다(id 가 가장 작은 pending)
            c.execute("UPDATE document_queue SET status='in_progress'"
                      " WHERE id=(SELECT MIN(id) FROM document_queue WHERE status='pending')")
            c.commit()
        finally:
            c.close()

    real_get = db.get_connection
    installed = {"w": None}

    def fake_get(*a, **kw):
        conn = real_get(*a, **kw)
        if installed["w"] is None:
            installed["w"] = InterleavingConn(conn, competitor)
            return installed["w"]
        return conn

    db.get_connection = fake_get
    try:
        got = db.claim_next_queue_item()
    finally:
        db.get_connection = real_get

    check_true("경쟁자가 실제로 끼어들었다", fired["n"] == 1, fired["n"])
    # 한 행을 뺏겼어도 **남은 행**을 집어야 한다. None 이면 호출부가 "큐 비었음"으로 읽고
    # 그날 수집을 끝낸다(Sprint 191 이 고친 결함).
    check_true("빼앗겨도 다른 행을 집는다(None 이 아니다)", got is not None, got)
    if got:
        check("집은 것은 경쟁자가 가져가지 않은 쪽", got["case_no"], "2026타경2")


# ---------------------------------------------------------------------------
# 5. 체크포인트 — 이미 있는 파일 위에 다시 저장할 수 있다 (원자적 교체)
#
#    Windows 의 `os.rename()` 은 목적지가 있으면 FileExistsError 다.
#    `os.replace()` 여야 **두 번째 저장부터** 동작한다 — 크롤은 사건마다 저장하므로
#    이것이 깨지면 첫 사건 이후 진행 상황이 하나도 안 남는다.
# ---------------------------------------------------------------------------
def test_checkpoint_overwrite_is_atomic():
    print("\n--- 5. 체크포인트 재저장(원자적 교체) ---")
    from storage.checkpoint import CheckpointManager
    tmp = tempfile.mkdtemp(prefix="qsi_cp_")
    _TMP.append(tmp)
    cp = CheckpointManager(path=os.path.join(tmp, "checkpoint.json"))

    cp.save("B1", "2026타경1", 1, 10)
    first = cp.get("B1")
    check_true("첫 저장이 남는다", first is not None, first)

    err = None
    try:
        for i in range(2, 6):
            cp.save("B1", "2026타경%d" % i, i, 10)
    except Exception as e:      # noqa: BLE001
        err = e
    check_true("덮어쓰기가 예외 없이 된다 (os.rename 이면 여기서 죽는다)", err is None, err)
    check("마지막 값이 반영된다", cp.get("B1")["last_case_no"], "2026타경5")

    cp.clear("B1")
    check("clear 후 사라진다", cp.get("B1"), None)


# ---------------------------------------------------------------------------
# 6. 이어받기 위치 — 마지막 완료 **다음**부터, 못 찾으면 처음부터
# ---------------------------------------------------------------------------
def test_resume_position():
    print("\n--- 6. 이어받기 위치 계산 ---")
    from crawler.resume import resume_start_idx, case_no_matches_list_entry

    items = [{"case_no": "2024타경1"}, {"case_no": "2024타경2"},
             {"case_no": "2024타경3 / 2024타경4"}]
    check("체크포인트 없으면 0", resume_start_idx(items, None), 0)
    check("마지막 완료의 **다음**부터", resume_start_idx(items, "2024타경2"), 2)
    check("병합 사건의 구성요소도 매칭된다", resume_start_idx(items, "2024타경4"), 3)
    # 오늘 목록에 없으면(취하/기일변경) 처음부터 — 재수집은 멱등하므로 안전하다
    check("목록에 없으면 0(처음부터)", resume_start_idx(items, "2024타경999"), 0)

    # ★ 부분 문자열 포함으로 되돌아가면 안 된다 (BUGS: 짧은 사건번호가 긴 것의 접두)
    check_true("접두 오탐이 없다: '2024타경1' vs '2024타경100920'",
               not case_no_matches_list_entry("2024타경1", "2024타경100920"),
               "부분 문자열 매칭으로 되돌아갔다")
    check_true("정확히 같으면 매칭된다",
               case_no_matches_list_entry("2024타경1", "2024타경1"), False)


if __name__ == "__main__":
    try:
        test_claim_cas_rejects_row_taken_meanwhile()
        test_retry_budget_is_finite()
        test_retry_interval_uses_local_clock()
        test_claim_race_retries_other_rows()
        test_checkpoint_overwrite_is_atomic()
        test_resume_position()
    finally:
        for d in _TMP:
            shutil.rmtree(d, ignore_errors=True)
    print("")
    if failures:
        print("FAILED %d: %s" % (len(failures), ", ".join(failures)))
        sys.exit(1)
    print("ALL PASS")
    sys.exit(0)
