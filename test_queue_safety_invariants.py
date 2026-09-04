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


def test_queue_status_vocabulary_is_declared_in_one_place():
    """`document_queue.status` 의 어휘가 **상수 한 곳**에서만 나오는가 (2026-08-31 신설).

    ## 왜 필요한가

    이 컬럼의 값은 전부 `WHERE status='...'` 로 **비교**된다. 오타는 예외가 아니라
    **0행 매치**다 - `mark_queue_done()` 이 아무 행도 바꾸지 못하면 그 행은
    `in_progress` 로 남아 stale 회수까지 붙잡혀 있고, 화면에는 수집이 끝난 것으로
    보인다. 로그에도 남지 않는 조용한 실패다.

    2026-08-31 실측: 여덟 값 중 여섯은 상수인데 **`done`/`failed` 만 상수가 없었고**,
    상수가 있는 값조차 SQL 문자열에 리터럴로 박힌 자리가 있었다(`'SKIPPED_EXPIRED'`).
    같은 파일의 주석이 "문자열로 구별하면 언젠가 어긋난다"고 경고한 바로 그 모양이다.
    """
    print("\n--- 큐 상태 어휘가 한 곳에서만 나오는가 ---")
    import re
    from storage.database import (
        QUEUE_STATUSES, QUEUE_STATUS_DONE, QUEUE_STATUS_FAILED,
        QUEUE_CLAIM_STATUS, QUEUE_RESUME_STATUS, QUEUE_CLAIMABLE_STATUSES,
        QUEUE_IN_PROGRESS_STATUSES,
    )

    # (a) 선언이 실제로 있고 비어 있지 않다 - 검사가 공허하지 않다.
    check("어휘 집합이 선언돼 있다", len(QUEUE_STATUSES) >= 8, True)
    check("done 이 상수로 있다", QUEUE_STATUS_DONE, "done")
    check("failed 가 상수로 있다", QUEUE_STATUS_FAILED, "failed")

    # (b) 파생 목록이 전부 그 집합 안에 있다. 하나라도 밖이면 전이표가 어휘를 벗어난 것이다.
    derived = set(QUEUE_CLAIM_STATUS) | set(QUEUE_CLAIM_STATUS.values())
    derived |= set(QUEUE_RESUME_STATUS) | set(QUEUE_RESUME_STATUS.values())
    derived |= set(QUEUE_CLAIMABLE_STATUSES) | set(QUEUE_IN_PROGRESS_STATUSES)
    check("파생 목록이 어휘를 벗어나지 않는다",
          sorted(derived - set(QUEUE_STATUSES)), [])

    # (c) 제품 SQL 이 상태값을 **문자열로 박지 않는다.**
    #     값을 SQL 텍스트에 넣으면 오타가 조용히 0행 매치가 되고, 이 저장소의
    #     SQL 조립 감사 규칙(값은 예외 없이 바인딩)과도 어긋난다.
    root = os.path.dirname(os.path.abspath(__file__))
    # ★ `=` 뿐 아니라 `IN (...)` 도 잡는다 (2026-09-04).
    #
    #   예전 정규식은 `status = '...'` 하나만 봤다. 그래서 `status IN ('SKIPPED_EXPIRED',
    #   'SKIPPED_UNSUPPORTED')` 형태가 **전수 검사를 그대로 통과**했고, 실제로
    #   `reset_failures.py` 가 그 모양으로 남아 있었다(2026-09-04 실측 1곳).
    #
    #   그 자리가 특히 나쁘다 — 그 스크립트는 이 목록으로 "되살리면 안 되는 행"을
    #   고른다. 오타가 나면 0행 매치라 **보호 대상이 없다**가 되어, 성공할 수 없는
    #   문서까지 COLLECTING 으로 되돌린다. 이 검사가 막으려던 바로 그 모양이
    #   검사의 사각지대에 있었다.
    _alt = "|".join(re.escape(v) for v in sorted(QUEUE_STATUSES))
    #   ★ 대소문자는 **구별한다.** 큐 어휘는 소문자('failed')이고 화면 어휘는
    #     대문자('FAILED')다 - `re.I` 를 걸면 `document_status` 의 정상적인
    #     'FAILED' 를 큐 리터럴로 오인한다(실제로 `repair_unsupported_status_docs.py`
    #     가 그렇게 오탐으로 잡혔다). 키워드 `IN` 의 대소문자만 열어 둔다.
    literal = re.compile(r"status\s*=\s*'(%s)'|status\s+(?i:IN)\s*\(\s*'(%s)'"
                         % (_alt, _alt))

    def code_strings(path):
        """그 파일의 **실제 코드에 쓰이는 문자열**만. docstring 은 뺀다.

        줄 단위로 훑으면 docstring 안의 설명문("status='SKIPPED_EXPIRED' 는 ...")까지
        결함으로 잡는다. SQL 은 삼중따옴표 문자열이라 삼중따옴표를 통째로 지울 수도
        없다. 그래서 구문 트리로 **docstring 자리만** 정확히 제외한다.
        """
        import ast as _ast
        tree = _ast.parse(io.open(path, encoding="utf-8-sig").read())
        docs = set()
        for node in _ast.walk(tree):
            if isinstance(node, (_ast.Module, _ast.FunctionDef,
                                 _ast.AsyncFunctionDef, _ast.ClassDef)):
                body = getattr(node, "body", None)
                if body and isinstance(body[0], _ast.Expr) and                         isinstance(body[0].value, _ast.Constant) and                         isinstance(body[0].value.value, str):
                    docs.add(id(body[0].value))
        for node in _ast.walk(tree):
            if isinstance(node, _ast.Constant) and isinstance(node.value, str)                     and id(node) not in docs:
                yield getattr(node, "lineno", 0), node.value

    offenders = []
    # ★ 대상 파일을 **손으로 적지 않는다** (2026-09-01 확장).
    #
    #   예전에는 네 파일만 훑었다 - storage/database.py / doc_worker.py /
    #   api/v1/doc_stats.py / refresh_priority.py. 그런데 큐 상태를 **쓰는**
    #   코드가 그 밖에도 있었다(실측 2026-09-01):
    #
    #       repair_empty_status_capture.py  UPDATE document_queue SET status='pending'
    #                                       ... AND status='done'   <- 실제 writer
    #       audit_schedule_health.py        WHERE status='pending'  <- 감사 질의
    #       audit_asset_integrity.py        dq.status = 'done' 등    <- 감사 질의
    #
    #   셋 다 리터럴이라 오타가 나면 예외가 아니라 0행 매치다. writer 쪽은 되돌림이
    #   조용히 안 되고, 감사 쪽은 **감사기가 거짓으로 초록**을 낸다(BUGS #271 과 같은 모양).
    #
    #   범위가 좁다는 사실 자체가 "여기만 리터럴이어도 된다"는 두 번째 규약이다
    #   (Sprint 118 이 시간대 검사에서 같은 결론을 냈다). 그래서 git 에게 묻는다.
    import subprocess as _sp
    try:
        _out = _sp.run(["git", "ls-files", "*.py"], cwd=root,
                       capture_output=True, text=True, timeout=30)
        _tracked = [x for x in _out.stdout.split()
                    if x.endswith(".py") and "-DESKTOP-" not in x
                    and not os.path.basename(x).startswith("test_")] if _out.returncode == 0 else []
    except (OSError, _sp.SubprocessError):
        _tracked = []
    if len(_tracked) < 20:
        # git 이 없는 배포본 - 예전 목록으로 되돌린다(범위는 좁지만 0보다 낫다).
        _tracked = ["storage/database.py", "doc_worker.py",
                    "api/v1/doc_stats.py", "refresh_priority.py"]
    check_true("검사 대상 파일을 실제로 모았다 - %d개" % len(_tracked), len(_tracked) >= 4)
    for rel in _tracked:
        path = os.path.join(root, rel.replace("/", os.sep))
        if not os.path.exists(path):
            continue
        for lineno, text in code_strings(path):
            if literal.search(text):
                offenders.append("%s:%d" % (rel, lineno))
    check("SQL 에 상태값 리터럴이 박혀 있지 않다", sorted(set(offenders)), [])

    # 탐지기 자체 증명 - 합성 입력에서는 반드시 잡혀야 한다.
    check_true("리터럴 탐지기가 동작한다",
               bool(literal.search("UPDATE q SET status='done' WHERE id=?")))
    check_true("★ IN (...) 형태도 잡는다",
               bool(literal.search(
                   "SELECT 1 WHERE q.status IN ('SKIPPED_EXPIRED', 'SKIPPED_UNSUPPORTED')")))
    check_true("바인딩 형태는 잡지 않는다(오탐 없음)",
               not literal.search("UPDATE q SET status=? WHERE id=?"))
    check_true("IN 의 바인딩 형태도 잡지 않는다(오탐 없음)",
               not literal.search("SELECT 1 WHERE q.status IN (?, ?)"))

    # (d) 실제 DB 에 어휘 밖의 값이 없다. 스크립트가 몰래 늘렸는지까지 본다.
    db_path = os.path.join(root, "auction.db")
    if os.path.exists(db_path):
        conn = sqlite3.connect("file:%s?mode=ro" % db_path.replace("\\", "/"), uri=True)
        try:
            rows = conn.execute(
                "SELECT status, COUNT(*) FROM document_queue GROUP BY 1").fetchall()
        finally:
            conn.close()
        unknown = sorted(st for st, _ in rows if st not in QUEUE_STATUSES)
        check("실제 DB 의 상태가 전부 선언된 어휘다", unknown, [])
        print("   DB 실측: %s" % ", ".join("%s=%d" % (st, n) for st, n in rows))
    else:
        # 검사를 조용히 건너뛰지 않는다 - 무엇을 못 봤는지 화면에 남긴다.
        print("   (auction.db 없음 - DB 대조는 이번 실행에서 하지 못했다)")

    # (e) ★ 상수 **값 자체**의 오타를 잡는다.
    #
    #     (b)/(c) 는 전부 같은 상수에서 파생되므로, 상수 값에 오타가 나면 양쪽이
    #     함께 틀려 **조용히 통과한다**(2026-08-31 변이 검증에서 실제로 생존했다).
    #     그래서 여기서는 제품 코드가 **DB 에 실제로 쓴 값**을 읽어, 이 파일에
    #     손으로 적은 기대 문자열과 맞춘다. 두 출처가 독립이라 오타가 드러난다.
    db2, path2 = fresh_db()
    seed_queue(path2, [("B9", "2026타경9", "1", "spec", "pending", 0, None)])
    claimed = db2.claim_next_queue_item()
    check_true("전제: 큐에서 한 건을 집었다", claimed is not None, claimed)
    check("claim 이 DB 에 쓴 상태 = 'in_progress'",
          q(path2, "SELECT status FROM document_queue"), "in_progress")
    db2.mark_queue_done(claimed["id"], "B9", "2026타경9", "1", "spec",
                        None, "hash-9",
                        claim_token=claimed.get("claim_token"))
    check("mark_queue_done 이 DB 에 쓴 상태 = 'done'",
          q(path2, "SELECT status FROM document_queue"), "done")


def test_document_status_vocabulary_is_declared_in_one_place():
    """`document_status.status` 어휘가 상수와 어긋나지 않는가 (2026-08-31 신설).

    큐(`document_queue.status`)와 **같은 파이프라인의 이웃 컬럼**이라 같은 자리에서 본다.
    큐가 "워커가 어디까지 했는가"라면 이쪽은 "화면이 무엇을 보여 줄 수 있는가"다.

    ## 왜 필요한가

    2026-08-31 실측: `api/constants.py:DocumentStatus` 가 여섯 값만 선언하고 있었는데
    제품은 **일곱 번째 값(`NO_IMAGE`)을 실제로 쓰고 있었다.**

        doc_worker.py            done_status = "NO_IMAGE" if result.get("no_asset") else "READY"
        api/v1/item.py           `_images_status()` 가 그대로 내보낸다
        storage/database.py      DOC_STATUS_HAS_ARTIFACT = ("READY", "NO_IMAGE")
        audit_asset_integrity.py 정합성 판정이 정상으로 센다
        properties/[id]/page.tsx '사진 없음' 라벨

    DB·수집기·API·화면·감사기가 전부 아는 값을 **상태값 정의만 몰랐다.**
    이런 어긋남은 실행해도 드러나지 않는다 — 상태값이 문자열이라 열거형을 거치지 않고도
    잘 돌기 때문이다. 드러나는 순간은 누군가 열거형만 보고 분기를 짤 때다.
    """
    print("\n--- 문서 상태 어휘가 상수와 맞는가 ---")
    import re
    from api.constants import DocumentStatus, DOCUMENT_STATUSES_IN_USE

    declared = {e.value for e in DocumentStatus}
    in_use = {str(v) for v in DOCUMENT_STATUSES_IN_USE}

    # (a) 검사가 공허하지 않다.
    check("열거형이 비어 있지 않다", len(declared) >= 6, True)
    check("사용 집합이 선언의 부분집합이다", sorted(in_use - declared), [])

    # (b) 제품 코드가 실제로 쓰는 값이 전부 선언돼 있다.
    #     `_set_document_status(...)` 호출과 `document_status` 관련 상수를 훑는다.
    root = os.path.dirname(os.path.abspath(__file__))
    written = set()
    scanned = 0
    for rel in ("storage/database.py", "doc_worker.py", "api/v1/item.py",
                "repair_document_status.py", "repair_unsupported_status_docs.py"):
        path = os.path.join(root, rel)
        if not os.path.exists(path):
            continue
        scanned += 1
        src = io.open(path, encoding="utf-8-sig").read()
        for m in re.finditer(r"_set_document_status\([^)]*?['\"]([A-Z_]+)['\"]", src, re.S):
            written.add(m.group(1))
        for m in re.finditer(r"done_status\s*=\s*['\"]([A-Z_]+)['\"]"
                             r"|done_status\s*=\s*['\"]([A-Z_]+)['\"]\s+if", src):
            written.add(m.group(1) or m.group(2))
        for m in re.finditer(r"DOC_STATUS_HAS_ARTIFACT\s*=\s*\(([^)]*)\)", src):
            written |= set(re.findall(r"['\"]([A-Z_]+)['\"]", m.group(1)))
    check_true("훑을 파일을 실제로 찾았다", scanned >= 3, scanned)
    check_true("코드가 쓰는 값을 실제로 찾았다", len(written) >= 3, sorted(written))
    check("코드가 쓰는 값이 전부 선언돼 있다", sorted(written - declared), [])
    print("   코드가 쓰는 값: %s" % ", ".join(sorted(written)))

    # (b-2) ★ `DOCUMENT_STATUSES_IN_USE` 가 **코드에서 유도된 값과 같은가** (2026-09-01).
    #
    #   위 (b) 는 `written ⊆ declared` 만 본다. 그래서 다음 구멍이 남아 있었다 —
    #   누가 `OCR` 을 실제로 방출하기 시작해도
    #     (b) 통과: OCR 은 선언돼 있다
    #     (c) 통과: DB 값도 선언 안에 있다
    #     (e) 통과: 라벨은 `in_use` 만 보는데 OCR 이 거기 없으니 아예 검사 대상이 아니다
    #   즉 **화면에 영문 코드가 그대로 나가는데 어떤 검사도 붉어지지 않는다.**
    #
    #   `DOCUMENT_STATUSES_IN_USE` 는 손으로 유지하는 집합인데, 그 집합이 낡아도
    #   알 방법이 없었다. 위에서 이미 **코드로부터 방출 값을 유도**해 두었으므로
    #   (`written`), 그 둘을 맞대면 집합이 유도값과 어긋나는 순간 붉어진다.
    #
    #   양방향으로 본다 —
    #     written - in_use : 방출하는데 집합에 없다 (라벨/감사가 못 본다)
    #     in_use - written : 집합은 쓴다는데 방출하는 코드가 없다 (집합이 낡았다)
    #
    #   ★ 새 검사를 만들지 않고 여기 붙인 이유: 이 함수가 이미 `written` 을 유도하고
    #     `in_use` 를 읽는다. 같은 불변식을 다른 파일에서 또 세면 한쪽만 고쳐지는 날이 온다.
    check("★ IN_USE 에 없는데 코드가 방출하는 값", sorted(written - in_use), [])
    check("★ 코드가 방출하지 않는데 IN_USE 에 있는 값", sorted(in_use - written), [])

    # (c) 실제 DB 에 선언 밖의 값이 없다.
    db_path = os.path.join(root, "auction.db")
    if os.path.exists(db_path):
        conn = sqlite3.connect("file:%s?mode=ro" % db_path.replace("\\", "/"), uri=True)
        try:
            rows = conn.execute(
                "SELECT status, COUNT(*) FROM document_status GROUP BY 1").fetchall()
        finally:
            conn.close()
        check("DB 의 문서 상태가 전부 선언된 어휘다",
              sorted(st for st, _ in rows if st not in declared), [])
        print("   DB 실측: %s" % ", ".join("%s=%d" % (st, n) for st, n in rows))
    else:
        print("   (auction.db 없음 - DB 대조는 이번 실행에서 하지 못했다)")

    # (d) ★ NO_IMAGE 가 "실패가 아니다"라는 규칙이 코드에 살아 있는가.
    #     이 값이 FAILED 로 뭉뚱그려지면 사용자는 기다리면 사진이 생길 것으로 오해한다.
    from storage.database import DOC_STATUS_HAS_ARTIFACT
    check("NO_IMAGE 는 '보여 줄 자산이 있다' 쪽에 있다",
          "NO_IMAGE" in DOC_STATUS_HAS_ARTIFACT, True)
    check("READY 도 같은 쪽에 있다", "READY" in DOC_STATUS_HAS_ARTIFACT, True)
    check("FAILED 는 그 쪽이 아니다", "FAILED" in DOC_STATUS_HAS_ARTIFACT, False)

    # (e) 화면 라벨이 선언된 값을 덮는가 - 라벨 없는 값은 사용자에게 원문이 노출된다.
    #     (원문 노출 자체는 이 저장소의 의도된 폴백이므로 결함이 아니다.
    #      여기서는 **실제로 쓰이는 값**만 라벨이 있어야 한다고 본다.)
    detail = os.path.join(root, "src", "app", "properties", "[id]", "page.tsx")
    if os.path.exists(detail):
        src = io.open(detail, encoding="utf-8-sig").read()
        m = re.search(r"DOC_STATUS_LABEL[^=]*=\s*\{(.*?)\n\}", src, re.S)
        check("화면 라벨표를 찾았다", m is not None, True)
        if m:
            labelled = set(re.findall(r"^\s*([A-Z_]+)\s*:", m.group(1), re.M))
            missing = sorted(v for v in in_use if v not in labelled)
            check("실제로 쓰이는 상태는 전부 화면 라벨이 있다", missing, [])



def test_unsupported_repair_never_touches_confirmed_answers():
    """`repair_unsupported_status_docs.py` 가 **덮으면 안 되는 행**을 대상에 넣지 않는가.

    ## 실제로 넣고 있었다 (2026-09-04 실측, 운영 DB 스냅샷)

        FAILED 로 바꿀 대상 12행  <- **전부 doc_type='IMAGE'**
          그중 status='NO_IMAGE'  3행

    두 가지가 겹쳐 있었다.

    (1) **사진이 흘러들었다.** 이 스크립트의 전제는 "상세페이지 수집 버튼 id 를
        몰라서 못 받는 문서"다. 그런데 `get_doc_button_id()` 가 None 을 주는 이유는
        둘이다 — (a) 버튼 id 를 모른다, (b) 버튼이라는 개념이 없다. 사진이 (b)인데
        루프가 둘을 구별하지 않았다. Sprint 144 가 `IMAGE` 를 `document_status` 와
        `QUEUE_TO_DOC_STATUS_TYPE` 에 넣는 순간 조용히 대상이 됐다 — 그 파일 상단이
        *"대상이 0건이 됐다, 설계가 의도대로 동작한 사례"* 라고 적어 둔 **뒤에** 벌어졌다.

    (2) **덮지 않을 상태를 손으로 적었다.** `== "READY"` 였는데 정본은
        `storage/database.py:DOC_STATUS_HAS_ARTIFACT`(READY + NO_IMAGE)다.
        `NO_IMAGE` 는 실패가 아니라 *"법원이 사진을 제공하지 않는다"* 는
        **확인된 답**이고 재시도해도 같다. FAILED 로 뒤집으면 화면은 '수집실패'가
        되고 큐는 영원히 다시 시도한다.

    합성 DB 로 두 성질을 함께 고정한다(운영 데이터의 우연에 기대지 않는다).
    """
    print("\n--- 미지원 문서 보정이 확인된 답을 덮지 않는가 ---")
    import importlib.util as iu
    from storage.database import DOC_STATUS_HAS_ARTIFACT

    db, path = fresh_db()
    root = os.path.dirname(os.path.abspath(__file__))

    # ★ `document_status` 는 (item_id, doc_type) 이 UNIQUE 다. 한 물건에 같은 종류를
    #   여러 상태로 심으면 INSERT OR REPLACE 가 접어 버린다(처음 짰을 때 5행이 2행이
    #   됐고, 바로 아래 '공허하지 않다' 검사가 그것을 잡았다). 조합마다 물건을 새로 만든다.
    seeded = [("IMAGE", "NO_IMAGE"), ("IMAGE", "COLLECTING"),
              ("IMAGE", "READY"), ("SPEC", "READY"), ("SPEC", "COLLECTING")]
    item_ids = []
    c = sqlite3.connect(path)
    try:
        now = datetime.now().isoformat()
        c.execute("INSERT INTO auction_case (court_code, case_no, created_at, updated_at)"
                  " VALUES ('QA법원','2099타경1',?,?)", (now, now))
        case_id = c.execute(
            "SELECT id FROM auction_case WHERE case_no='2099타경1'").fetchone()[0]
        for idx, (dt, st) in enumerate(seeded, start=1):
            c.execute("INSERT INTO auction_item (case_id, case_no, item_no, court_name,"
                      " created_at, updated_at) VALUES (?,?,?,?,?,?)",
                      (case_id, '2099타경1', str(idx), 'QA법원', now, now))
            iid = c.execute("SELECT id FROM auction_item WHERE case_id=? AND item_no=?",
                            (case_id, str(idx))).fetchone()[0]
            item_ids.append(iid)
            c.execute("INSERT INTO document_status"
                      " (item_id, doc_type, status, updated_at) VALUES (?,?,?,?)",
                      (iid, dt, st, now))
        c.commit()
    finally:
        c.close()

    spec = iu.spec_from_file_location(
        "rusd_qa", os.path.join(root, "repair_unsupported_status_docs.py"))
    m = iu.module_from_spec(spec)
    spec.loader.exec_module(m)

    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        targets, skipped, total = m.plan(conn)
    finally:
        conn.close()

    # 검사가 공허하지 않다 — 심은 행이 실제로 보인다.
    conn = sqlite3.connect(path)
    try:
        marks = ",".join("?" * len(item_ids))
        rows_seen = conn.execute(
            "SELECT COUNT(*) FROM document_status WHERE item_id IN (%s)" % marks,
            item_ids).fetchone()[0]
    finally:
        conn.close()
    check("검사가 공허하지 않다 - 심은 상태 행이 있다", rows_seen, len(seeded))
    check_true("검사가 공허하지 않다 - NO_IMAGE 를 실제로 심었다",
               "NO_IMAGE" in DOC_STATUS_HAS_ARTIFACT, sorted(DOC_STATUS_HAS_ARTIFACT))

    # (1) 산출물이 있는 상태는 **절대** 대상이 아니다.
    bad_status = sorted({t["status"] for t in targets} & set(DOC_STATUS_HAS_ARTIFACT))
    check("★ 산출물이 있는 상태(READY/NO_IMAGE)를 대상에 넣지 않는다", bad_status, [])

    # (2) 수집 버튼 개념이 없는 종류(IMAGE)는 이 스크립트의 소관이 아니다.
    bad_types = sorted({t["doc_type"] for t in targets if t["doc_type"] == "IMAGE"})
    check("★ 사진(IMAGE)을 미지원 문서로 분류하지 않는다", bad_types, [])

    # 버튼 종류 정본과 어긋나지 않는다.
    from config.settings import DOC_BUTTON_DOC_TYPES
    check("버튼 있는 종류 정본이 사진을 포함하지 않는다",
          sorted(DOC_BUTTON_DOC_TYPES), ["appraisal", "spec", "status"])
    print("    대상 %d행 / 산출물 보유로 건너뜀 %d행 / 미지원 총 %d행"
          % (len(targets), skipped, total))

    # ------------------------------------------------------------------
    # (2)번을 **독립적으로** 태운다.
    #
    #   위 블록만으로는 부족했다 — (1)번 수정이 사진을 먼저 걸러 내므로 상태 분기에
    #   도달하는 행이 없고, 그래서 `DOC_STATUS_HAS_ARTIFACT` 를 `== "READY"` 로
    #   되돌리는 변이가 **살아남았다**(2026-09-04 확인). 공허한 검사였다.
    #
    #   이 스크립트의 원래 대상은 "버튼을 가진 종류인데 그 item_no 의 버튼 id 를
    #   모르는 경우"다. 지금 실코드에서는 그런 조합이 없으므로(전부 id 를 안다)
    #   판정 함수만 그 상황으로 바꿔 상태 분기를 직접 태운다.
    #   **규칙을 베끼는 것이 아니라 전제를 만드는 것**이다 - 대상 선정은 그대로 제품 코드가 한다.
    db2, path2 = fresh_db()
    spec2 = iu.spec_from_file_location(
        "rusd_qa2", os.path.join(root, "repair_unsupported_status_docs.py"))
    m2 = iu.module_from_spec(spec2)
    spec2.loader.exec_module(m2)
    m2.get_doc_button_id = lambda doc_type, item_no: None   # 버튼 id 미확보 상황

    seeded2 = [("SPEC", "READY"), ("SPEC", "NO_IMAGE"), ("SPEC", "COLLECTING")]
    ids2 = []
    c = sqlite3.connect(path2)
    try:
        now = datetime.now().isoformat()
        c.execute("INSERT INTO auction_case (court_code, case_no, created_at, updated_at)"
                  " VALUES ('QA법원','2099타경2',?,?)", (now, now))
        cid = c.execute(
            "SELECT id FROM auction_case WHERE case_no='2099타경2'").fetchone()[0]
        for idx, (dt, st) in enumerate(seeded2, start=1):
            c.execute("INSERT INTO auction_item (case_id, case_no, item_no, court_name,"
                      " created_at, updated_at) VALUES (?,?,?,?,?,?)",
                      (cid, '2099타경2', str(idx), 'QA법원', now, now))
            iid = c.execute("SELECT id FROM auction_item WHERE case_id=? AND item_no=?",
                            (cid, str(idx))).fetchone()[0]
            ids2.append(iid)
            c.execute("INSERT INTO document_status"
                      " (item_id, doc_type, status, updated_at) VALUES (?,?,?,?)",
                      (iid, dt, st, now))
        c.commit()
    finally:
        c.close()

    conn = sqlite3.connect(path2)
    conn.row_factory = sqlite3.Row
    try:
        t2, skipped2, total2 = m2.plan(conn)
    finally:
        conn.close()

    # 검사가 공허하지 않다 — 이번에는 상태 분기에 **실제로 도달**한다.
    check("검사가 공허하지 않다 - 미지원으로 잡힌 행이 있다", total2, len(seeded2))
    check_true("검사가 공허하지 않다 - 대상이 하나는 나온다(COLLECTING)",
               len(t2) >= 1, [(x["doc_type"], x["status"]) for x in t2])

    got = sorted((x["doc_type"], x["status"]) for x in t2)
    check("★ READY / NO_IMAGE 는 건너뛰고 COLLECTING 만 대상이다",
          got, [("SPEC", "COLLECTING")])
    check("★ 산출물 보유로 건너뛴 행이 정확히 둘이다(READY + NO_IMAGE)", skipped2, 2)


# ---------------------------------------------------------------------------
# 9. `unlock_retry.py` 는 **대기 상태만** 푼다 (2026-09-04)
# ---------------------------------------------------------------------------
def test_unlock_retry_only_clears_waiting_rows():
    """재시도 잠금 해제 도구가 회수 근거를 지우지 않는가.

    ## 왜 이 검사가 필요한가

    `document_queue.last_attempt_at` 은 한 컬럼으로 **두 가지**를 겸한다.

        pending / refresh   재시도 잠금 (`claim_next_queue_item()` 의 30분 간격)
        그 밖의 상태         회수·소유권의 유일한 근거
                            - `reset_stale_queue()` 의 `in_progress` 회수와
                              `failed` -> `pending` 복구가 둘 다
                              `last_attempt_at IS NOT NULL` 을 요구한다
                            - `_claim_is_still_ours()` 의 claim 토큰이다(BUGS #181)

    `unlock_retry.py` 는 조건에 맞는 **모든** 행의 값을 NULL 로 만들었다. 그래서
    운영자가 "재시도를 앞당기려고" 부른 도구가 정반대 결과를 냈다 — 임시 DB 재현:

        in_progress + NULL  -> reset_stale_queue() 가 영원히 회수 못 한다.
                               in_progress 는 claim 대상도 아니므로 **영구 정지 행**이다.
        failed      + NULL  -> 하루 뒤 pending 복구가 영원히 일어나지 않는다.

    조용한 결함이다 — 도구는 "해제했다"고 출력하고, 큐는 줄지 않으며, 로그에도
    아무 오류가 없다. 그래서 검사로 묶는다.
    """
    print(chr(10) + "--- unlock_retry 는 대기 상태만 푼다 ---")
    import unlock_retry

    db, path = fresh_db()
    old = (datetime.now() - timedelta(days=3)).isoformat()
    seed_queue(path, [
        ("QA법원", "2099타경7", "1", "spec", "in_progress", 1, old),
        ("QA법원", "2099타경7", "1", "appraisal", "failed", 3, old),
        ("QA법원", "2099타경7", "1", "status", "pending", 1, old),
    ])

    saved_argv, saved_db = sys.argv, unlock_retry.DB_PATH
    try:
        unlock_retry.DB_PATH = path
        sys.argv = ["unlock_retry.py", "QA법원", "2099타경7", "--apply"]
        with contextlib.redirect_stdout(io.StringIO()):
            rc = unlock_retry.main()
    finally:
        sys.argv, unlock_retry.DB_PATH = saved_argv, saved_db
    check("도구가 정상 종료한다", rc, 0)

    def att(doc_type):
        return q(path, "SELECT last_attempt_at FROM document_queue WHERE doc_type=?",
                 (doc_type,))

    # 하려던 일은 실제로 한다 — 그러지 않으면 이 검사는 "아무것도 안 하기"도 통과시킨다.
    check("대기(pending) 행의 잠금은 풀린다", att("status"), None)
    # 회수 근거는 지우지 않는다.
    check_true("in_progress 행의 회수 근거는 남는다", att("spec") == old, att("spec"))
    check_true("failed 행의 복구 근거는 남는다", att("appraisal") == old, att("appraisal"))

    # ★ 결과로 확인한다 — 값이 남아 있다는 것만으로는 회수가 실제로 되는지 모른다.
    with contextlib.redirect_stdout(io.StringIO()):
        db.reset_stale_queue()

    def st(doc_type):
        return q(path, "SELECT status FROM document_queue WHERE doc_type=?", (doc_type,))

    check("★ in_progress 행이 회수된다(영구 정지 아님)", st("spec"), "pending")
    check("★ failed 행이 재시도로 복구된다", st("appraisal"), "pending")

    # ★ 어휘를 손으로 적지 않았는지 확인한다. `UNLOCKABLE_STATUSES` 가 claim 가능
    #   상태와 갈라지면 refresh 행이 조용히 안 풀리거나, 진행 중인 행이 풀린다.
    check("풀 수 있는 상태 = claim 가능 상태",
          sorted(unlock_retry.UNLOCKABLE_STATUSES),
          sorted(db.QUEUE_CLAIMABLE_STATUSES))


# ---------------------------------------------------------------------------
# 10. `release_queue_rows()` 는 **남의 claim** 을 풀지 않는다 (2026-09-04)
# ---------------------------------------------------------------------------
def test_release_does_not_steal_a_reclaimed_row():
    """되돌리는 경로에도 claim 토큰 확인이 걸려 있는가.

    ## 왜 필요한가

    BUGS #181 은 "회수당한 뒤 다시 집힌 행을 남의 실행이 종결하면 안 된다"를 세우고
    종결하는 네 함수에 `_claim_is_still_ours()` 를 걸었다. **되돌리는 함수만
    빠져 있었다.**

        A 가 묶음으로 4행을 집는다 -> 실행 창이 닫힌다
        그 사이 회수돼 B 가 그중 한 행을 다시 집어 실제로 문서를 받고 있다
        A 의 finally 가 `release_queue_rows()` 로 그 행을 'pending' 으로 푼다
        -> C 가 같은 문서를 동시에 받는다. B 의 종결은 토큰에 걸려 조용히 버려진다.

    상태(`in_progress`)로는 구별할 수 없다는 것이 #181 의 요지 그대로다 —
    회수 후 다시 집은 행도 `in_progress` 다. 그래서 토큰으로 판정해야 한다.
    """
    print(chr(10) + "--- release_queue_rows 는 남의 claim 을 풀지 않는다 ---")
    db, path = fresh_db()
    seed_queue(path, [
        ("QA법원", "2099타경8", "1", "spec", "pending", 0, None),
        ("QA법원", "2099타경8", "1", "appraisal", "pending", 0, None),
    ])

    mine = db.claim_next_queue_item()
    check_true("전제: 한 행을 집었다", mine is not None, mine)
    other = db.claim_next_queue_item()
    check_true("전제: 다른 행도 집었다", other is not None, other)

    # 내 행이 회수됐다가 다른 실행에 다시 집혔다 — 토큰만 달라지고 상태는 그대로다.
    stolen_token = (datetime.now() + timedelta(seconds=1)).isoformat()
    c = sqlite3.connect(path)
    try:
        c.execute("UPDATE document_queue SET last_attempt_at=? WHERE id=?",
                  (stolen_token, mine["id"]))
        c.commit()
    finally:
        c.close()
    check("전제: 상태로는 구별되지 않는다(둘 다 진행 중)",
          q(path, "SELECT status FROM document_queue WHERE id=?", (mine["id"],)),
          "in_progress")

    released = db.release_queue_rows(
        [mine["id"], other["id"]],
        {mine["id"]: mine["claim_token"], other["id"]: other["claim_token"]})

    check("★ 남에게 넘어간 행은 풀지 않는다",
          q(path, "SELECT status FROM document_queue WHERE id=?", (mine["id"],)),
          "in_progress")
    check("★ 남에게 넘어간 행의 claim 토큰도 그대로다",
          q(path, "SELECT last_attempt_at FROM document_queue WHERE id=?", (mine["id"],)),
          stolen_token)
    # 검사가 공허하지 않다 — 내 것인 행은 실제로 풀려야 한다.
    check("아직 내 것인 행은 되돌린다",
          q(path, "SELECT status FROM document_queue WHERE id=?", (other["id"],)),
          "pending")
    check("되돌린 행 수는 하나다", released, 1)

    # 토큰을 넘기지 않는 예전 호출부의 계약은 그대로다(하위호환).
    db2, path2 = fresh_db()
    seed_queue(path2, [("QA법원", "2099타경9", "1", "spec", "pending", 0, None)])
    got = db2.claim_next_queue_item()
    check("토큰 없이 부르면 예전처럼 되돌린다", db2.release_queue_rows([got["id"]]), 1)


# ---------------------------------------------------------------------------
# 11. `reset_failures.py` — 되살리지 않는 행의 **근거**를 지우지 않는다 (2026-09-04)
# ---------------------------------------------------------------------------
def test_reset_failures_keeps_evidence_for_rows_it_leaves_failed():
    """실패 해제 도구가 보호한 행의 사유까지 지우지는 않는가.

    ## 두 가지를 함께 본다

    (1) **보호** — 큐가 `SKIPPED_EXPIRED` / `SKIPPED_UNSUPPORTED` 로 종결된 행은
        화면 상태를 `COLLECTING` 으로 되돌리지 않는다. 되돌리면 큐는 종결인데 화면은
        영원히 "수집중"인, 앞뒤가 안 맞는 상태가 된다(BUGS #69 계열).

    (2) **근거** — 예전에는 `DELETE FROM document_collect_failures` 로 사유를 **통째로**
        지웠다. 그래서 (1) 이 일부러 FAILED 로 남긴 행까지 이유가 사라졌다. 화면은
        "수집실패"라고 말하는데 왜인지는 아무 데도 없다 — 그 표는 정확히 그 침묵을
        없애려고 채우기 시작한 것이다(`_record_collect_failure()`, 2026-09-02).

    둘은 같은 결정의 앞뒤다. 한쪽만 검사하면 다른 쪽이 조용히 되돌아간다.
    """
    print(chr(10) + "--- reset_failures 는 보호한 행의 근거를 지우지 않는다 ---")
    import runpy
    import storage.database as _db

    db, path = fresh_db()
    now = datetime.now().isoformat()
    c = sqlite3.connect(path)
    try:
        c.execute("INSERT INTO auction_case (court_code, case_no, created_at, updated_at)"
                  " VALUES ('QA법원','2099타경11',?,?)", (now, now))
        cid = c.execute("SELECT id FROM auction_case WHERE case_no='2099타경11'").fetchone()[0]
        c.execute("INSERT INTO auction_item (case_id, case_no, item_no, court_name,"
                  " created_at, updated_at) VALUES (?,?,?,?,?,?)",
                  (cid, '2099타경11', '1', 'QA법원', now, now))
        iid = c.execute("SELECT id FROM auction_item WHERE case_id=?", (cid,)).fetchone()[0]
        # 같은 물건의 두 문서: 하나는 큐가 종결(보호), 하나는 재시도 소진(되살림).
        for doc_type, qstatus in (("appraisal", "SKIPPED_UNSUPPORTED"), ("spec", "failed")):
            c.execute("INSERT INTO document_queue (court_code, case_no, item_no, doc_type,"
                      " priority, auction_date, status, retry_count, enqueued_at)"
                      " VALUES ('QA법원','2099타경11','1',?,1,?,?,3,?)",
                      (doc_type, future(), qstatus, now))
            c.execute("INSERT INTO document_status (item_id, doc_type, status, updated_at)"
                      " VALUES (?,?, 'FAILED', ?)", (iid, doc_type.upper(), now))
            c.execute("INSERT INTO document_collect_failures"
                      " (item_id, doc_type, error_message, created_at)"
                      " VALUES (?,?, 'qa-seeded-reason', ?)", (iid, doc_type, now))
        c.commit()
    finally:
        c.close()

    saved_argv, saved_db = sys.argv, _db.DB_PATH
    try:
        _db.DB_PATH = path
        sys.argv = ["reset_failures.py", "--apply"]
        with contextlib.redirect_stdout(io.StringIO()):
            runpy.run_path(
                os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "reset_failures.py"),
                run_name="__main__")
    except SystemExit:
        pass
    finally:
        sys.argv, _db.DB_PATH = saved_argv, saved_db

    def ds(doc_type):
        return q(path, "SELECT status FROM document_status WHERE doc_type=?",
                 (doc_type,))

    def reasons(doc_type):
        return q(path, "SELECT COUNT(*) FROM document_collect_failures"
                       " WHERE UPPER(doc_type)=UPPER(?)", (doc_type,))

    # (1) 보호 — 검사가 공허하지 않도록 되살리는 쪽도 함께 본다.
    check("★ 큐가 종결된 행은 FAILED 그대로 둔다", ds("APPRAISAL"), "FAILED")
    check("되살릴 행은 COLLECTING 이 된다", ds("SPEC"), "COLLECTING")

    # (2) 근거
    check("★ 보호한 행의 실패 사유는 남는다", reasons("appraisal"), 1)
    check("되살린 행의 사유는 지운다(다시 시도하므로)", reasons("spec"), 0)


if __name__ == "__main__":
    try:
        test_claim_cas_rejects_row_taken_meanwhile()
        test_retry_budget_is_finite()
        test_retry_interval_uses_local_clock()
        test_claim_race_retries_other_rows()
        test_checkpoint_overwrite_is_atomic()
        test_resume_position()
        test_queue_status_vocabulary_is_declared_in_one_place()
        test_document_status_vocabulary_is_declared_in_one_place()
        test_unsupported_repair_never_touches_confirmed_answers()
        test_unlock_retry_only_clears_waiting_rows()
        test_release_does_not_steal_a_reclaimed_row()
        test_reset_failures_keeps_evidence_for_rows_it_leaves_failed()
    finally:
        for d in _TMP:
            shutil.rmtree(d, ignore_errors=True)
    print("")
    if failures:
        print("FAILED %d: %s" % (len(failures), ", ".join(failures)))
        sys.exit(1)
    print("ALL PASS")
    sys.exit(0)
