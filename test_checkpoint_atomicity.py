"""
storage/checkpoint.py(CheckpointManager) 순수 로직 회귀 테스트.

Selenium/실제 브라우저는 전혀 쓰지 않는다 — crawl_court()의 재시작 이어받기 상태 저장소만
파일시스템 레벨에서 직접 검증한다.

배경(2026-08-10 Sprint 42, Crawler TOCTOU Audit — crawler/court_crawler.py +
crawler/base_crawler.py 확장 감사): CheckpointManager.save()/clear()가 checkpoint.json에
직접 open(path, "w")로 쓰고 있어, `crawl_court()`가 법원 하나를 처리할 때마다(사건 하나
끝날 때마다) 반복 호출되는 이 저장 도중 프로세스가 강제 종료되면(전원 차단/OOM kill 등)
파일 전체가 손상될 수 있었다. `_load_all()`은 JSON 파싱 실패를 "체크포인트 없음"으로
처리하므로, 손상되면 지금 저장 중이던 법원뿐 아니라 이미 저장돼 있던 **다른 모든 법원**의
체크포인트까지 사라져(재시작 시 이어받기 불가) 불필요한 전체 재크롤링이 발생했다 —
crawler/doc_crawler.py:collect_status()(Sprint 40, docs/BUGS.md #22)에서 발견한 것과
동일한 부류의 결함이라 같은 원자적 교체(임시파일+os.replace()) 패턴으로 고쳤다.

동시 접근(다중 프로세스/스레드) 레이스는 검증 대상이 아니다 — CheckpointManager는
mvp_scraper.py의 단일 프로세스, 법원 순차 루프(`for court in courts: crawl_court(court)`)
안에서만 호출되어 실제 동시 호출 경로가 없다(이론적 레이스만 있고 실제 재현 불가).

    python test_checkpoint_atomicity.py
"""
import sys
import os
import json
import shutil
import tempfile
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from storage.checkpoint import CheckpointManager

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


# 2026-08-11 Sprint 52 — 저장소 안(`logs/`)이 아니라 **시스템 임시 디렉터리**에 쓴다.
#
# 왜 옮겼나: 이 저장소는 OneDrive 동기화 폴더 안에 있고, `logs/`에 쓰면 OneDrive가 그 파일을
# 실시간으로 스캔·동기화한다. 그 상태에서 `os.replace()` 직후 읽으면 **간헐적으로 교체 이전
# 내용이 보였다** — 15종 순차 실행에서 재현(`before_crash`가 `{}`로 읽혀 다음 단언이
# TypeError). 단독 실행 5회는 전부 통과해 원인 파악이 늦어질 수 있는 형태의 flaky였다.
#
# 이 테스트가 검증하는 것은 `CheckpointManager`의 **순수 로직**(임시파일 + os.replace)이지
# 저장소의 `logs/` 디렉터리가 아니다. 동기화 폴더를 벗어나면 그 무관한 실패 요인이 사라진다.
# (제품 코드는 그대로 저장소의 `logs/checkpoint.json`을 쓴다 — 테스트 경로만 바꾼 것이다.
#  2026-08-27 BUGS #263 이후 그 기본값은 **모듈 파일 기준 절대경로**다. 아래
#  `test_default_path_does_not_follow_cwd()` 가 그것을 고정한다.)
QA_DIR = tempfile.mkdtemp(prefix="dojoonpass-qa-checkpoint-")
QA_PATH = os.path.join(QA_DIR, "qa-checkpoint-" + uuid.uuid4().hex[:8] + ".json")


def test_save_get_clear_roundtrip():
    print("\n--- 1. save / get / clear round-trip ---")
    cm = CheckpointManager(path=QA_PATH)
    check("no checkpoint initially", cm.get("COURT_A"), None)

    cm.save("COURT_A", "2026TA1234", 5, 20)
    cp = cm.get("COURT_A")
    check("saved last_case_no", cp["last_case_no"], "2026TA1234")
    check("saved completed", cp["completed"], 5)
    check("saved total", cp["total"], 20)
    check_true("no .tmp file left after save", not os.path.exists(QA_PATH + ".tmp"))

    # 여러 법원이 같은 파일을 공유한다 — 다른 법원 저장이 기존 법원 데이터를 지우면 안 된다
    cm.save("COURT_B", "2026TB5678", 1, 10)
    check("COURT_A untouched by COURT_B save", cm.get("COURT_A")["last_case_no"], "2026TA1234")
    check("COURT_B saved", cm.get("COURT_B")["last_case_no"], "2026TB5678")

    cm.clear("COURT_A")
    check("COURT_A cleared", cm.get("COURT_A"), None)
    check("COURT_B still present after clearing COURT_A", cm.get("COURT_B")["last_case_no"], "2026TB5678")
    check_true("no .tmp file left after clear", not os.path.exists(QA_PATH + ".tmp"))

    cm.clear("COURT_B")


def test_atomic_write_survives_simulated_crash():
    """collect_status()와 동일한 방식으로 "임시파일 쓰기 후 replace 호출 전에 죽음"을
    시뮬레이션해, checkpoint.json이 손상되지 않고 이전 상태 그대로 남는지 검증한다.
    """
    print("\n--- 2. atomic write (temp file + os.replace) survives simulated crash ---")
    cm = CheckpointManager(path=QA_PATH)
    cm.save("COURT_C", "2026TC0001", 1, 100)

    with open(QA_PATH, encoding="utf-8") as f:
        before_crash = f.read()

    # 두 번째 저장이 tmp 쓰기까지만 하고 replace()는 호출하지 않은 채 죽었다고 가정한다.
    tmp_path = QA_PATH + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump({"COURT_C": {"last_case_no": "2026TC9999-CORRUPT", "completed": 999, "total": 999}}, f)
    # <- 여기서 프로세스가 죽었다고 가정. os.replace()를 호출하지 않는다.

    with open(QA_PATH, encoding="utf-8") as f:
        after_simulated_crash = f.read()
    check("destination untouched by the crashed write (old content intact, not corrupted)",
          after_simulated_crash, before_crash)
    cm_after_crash = CheckpointManager(path=QA_PATH)
    check("get() still returns the pre-crash value, not the half-written one",
          cm_after_crash.get("COURT_C")["last_case_no"], "2026TC0001")

    # 다음 실행이 정상적으로 재시도하면(진짜 save() 호출) 새 내용으로 정확히 교체된다.
    cm_after_crash.save("COURT_C", "2026TC0002", 2, 100)
    check("real retry completes cleanly with the NEW value",
          cm_after_crash.get("COURT_C")["last_case_no"], "2026TC0002")
    check_true("orphaned tmp from the simulated crash is gone (overwritten by the real save's own tmp)",
               not os.path.exists(tmp_path))

    cm_after_crash.clear("COURT_C")


def test_corrupted_file_does_not_crash_get():
    """_load_all()이 파싱 실패 시 빈 dict로 안전하게 폴백하는지 확인한다(기존 동작,
    회귀 없음 재확인) — 손상된 파일이 남아도 크래시하지 않고 "체크포인트 없음"으로
    처리돼 크롤러가 처음부터 다시 수집할 뿐 예외로 죽지는 않는다.
    """
    print("\n--- 3. corrupted checkpoint file does not crash get() ---")
    with open(QA_PATH, "w", encoding="utf-8") as f:
        f.write("{not valid json,,,")

    cm = CheckpointManager(path=QA_PATH)
    result = None
    raised = False
    try:
        result = cm.get("ANY_COURT")
    except Exception:
        raised = True
    check_true("get() on corrupted file does not raise", not raised)
    check("get() on corrupted file returns None (treated as no checkpoint)", result, None)

    # ★ 죽지 않는 것만으로는 부족하다 — **보이는가** (2026-08-27, docs/BUGS.md #244).
    #
    #   이 폴백은 "60개 법원을 전부 처음부터 다시 긁는다"는 뜻이다. 그런데 예전에는
    #   `except Exception: return {}` 이라 **로그가 한 줄도 남지 않았다**(실측: 빈 문자열).
    #   운영자는 밤새 돈 재크롤을 보고도 원인을 알 수 없었다. 위 테스트는 "크래시하지
    #   않는다"만 봤기 때문에 그 침묵을 통과시켰다.
    import logging as _logging
    import io as _io
    _buf = _io.StringIO()
    _h = _logging.StreamHandler(_buf)
    _cp_logger = _logging.getLogger("storage.checkpoint")
    _prev_level, _prev_prop = _cp_logger.level, _cp_logger.propagate
    _cp_logger.addHandler(_h)
    _cp_logger.setLevel(_logging.DEBUG)
    try:
        with open(QA_PATH, "w", encoding="utf-8") as f:
            f.write('{"법원A": {"last_case_no": "2026타')      # 반쯤 잘린 JSON
        _buf.truncate(0); _buf.seek(0)
        again = CheckpointManager(path=QA_PATH)._load_all()
        logged = _buf.getvalue()
        check("손상 파일은 여전히 빈 dict 로 폴백한다(동작 무변경)", again, {})
        check_true("★ 손상을 읽지 못했다는 사실이 로그에 남는다", bool(logged.strip()),
                   repr(logged))
        check_true("★ 로그가 '전부 다시 수집한다'는 결과를 말한다",
                   "다시 수집" in logged, repr(logged[:160]))
        check_true("★ 로그에 경로가 들어 있다(어느 파일인지 알 수 있다)",
                   QA_PATH in logged or os.path.basename(QA_PATH) in logged,
                   repr(logged[:160]))

        # 대조군 — **파일이 없는 정상 첫 실행은 조용해야 한다.**
        #   매일 남는 소음은 진짜 신호를 묻는다.
        if os.path.exists(QA_PATH):
            os.remove(QA_PATH)
        _buf.truncate(0); _buf.seek(0)
        empty = CheckpointManager(path=QA_PATH)._load_all()
        check("파일이 없으면 빈 dict", empty, {})
        check_true("★ 파일이 없는 것은 사고가 아니므로 로그를 남기지 않는다",
                   _buf.getvalue().strip() == "", repr(_buf.getvalue()))
    finally:
        _cp_logger.removeHandler(_h)
        _cp_logger.setLevel(_prev_level)
        _cp_logger.propagate = _prev_prop


def test_write_failure_does_not_stop_the_crawl():
    """저장 실패가 **크롤을 멈추지 않는가** (2026-08-13 Sprint 85 신설).

    커버리지가 지목한 두 곳(`save()`/`clear()`의 `except Exception` -> 로그)이었다. 이 두
    분기는 의도된 설계다 ― 체크포인트는 "다음 실행이 이어받기 위한 편의"이고, 그 저장이
    실패했다고 **이미 성공한 크롤을 중단시키면 손해가 더 크다**(60개 법원 순차 루프가
    디스크 일시 오류로 통째로 멈춘다). 그래서 예외를 삼키고 로그만 남긴다.

    다만 삼키는 코드는 위험하다 ― 조용해지면 "왜 이어받기가 안 되는지" 알 수 없다. 그래서
    (1) 예외가 밖으로 나가지 않고 (2) ERROR 로그가 남고 (3) 기존 파일이 망가지지 않는지를
    함께 고정한다. 특히 (3)이 핵심이다: 실패한 저장이 기존 내용을 반쯤 덮어쓰면 다른 법원의
    진행 상황까지 사라진다(이 파일 상단이 설명하는 바로 그 사고).
    """
    import logging
    import storage.checkpoint as cp_mod

    print("\n--- 4. 저장 실패는 크롤을 멈추지 않는다 (Sprint 85) ---")
    path = os.path.join(QA_DIR, "qa-writefail-" + uuid.uuid4().hex[:8] + ".json")
    cm = CheckpointManager(path=path)
    cm.save("COURT_KEEP", "2026TA0001", 3, 30)
    before = open(path, encoding="utf-8").read()

    records = []

    class _Capture(logging.Handler):
        def emit(self, record):
            records.append(record)

    handler = _Capture(level=logging.ERROR)
    logger = logging.getLogger(cp_mod.__name__)
    logger.addHandler(handler)

    real_write = CheckpointManager._write_atomic

    def boom(self, data):
        raise OSError("디스크 쓰기 실패(주입)")

    CheckpointManager._write_atomic = boom
    try:
        raised = None
        try:
            cm.save("COURT_NEW", "2026TA9999", 1, 10)
        except Exception as exc:  # noqa: BLE001
            raised = exc
        check("save 실패가 호출자에게 전파되지 않는다", raised, None)
        check_true("save 실패에 ERROR 로그가 남는다",
                   any("save failed" in r.getMessage() for r in records),
                   [r.getMessage() for r in records])

        records.clear()
        raised = None
        try:
            cm.clear("COURT_KEEP")
        except Exception as exc:  # noqa: BLE001
            raised = exc
        check("clear 실패도 전파되지 않는다", raised, None)
        check_true("clear 실패에 ERROR 로그가 남는다",
                   any("clear failed" in r.getMessage() for r in records),
                   [r.getMessage() for r in records])
    finally:
        CheckpointManager._write_atomic = real_write
        logger.removeHandler(handler)

    # 실패한 쓰기가 기존 파일을 건드리지 않았는가 ― 이어받기 자산을 잃지 않는 것이 요점이다.
    check("실패한 저장이 기존 파일을 바꾸지 않는다", open(path, encoding="utf-8").read(), before)
    check("다른 법원의 진행 상황이 그대로 남는다",
          CheckpointManager(path=path).get("COURT_KEEP")["last_case_no"], "2026TA0001")
    check_true("실패 후 .tmp 잔재가 남지 않는다", not os.path.exists(path + ".tmp"))

    # 복구 후에는 정상 동작해야 한다(주입이 영구 영향을 남기지 않았는지 확인).
    cm.save("COURT_NEW", "2026TA9999", 1, 10)
    check("주입 해제 후 정상 저장된다", cm.get("COURT_NEW")["last_case_no"], "2026TA9999")
    os.remove(path)


def cleanup():
    print("\n--- cleanup (qa checkpoint file only) ---")
    for p in (QA_PATH, QA_PATH + ".tmp"):
        if os.path.exists(p):
            os.remove(p)
    check_true("qa checkpoint file removed", not os.path.exists(QA_PATH))
    # 임시 디렉터리째 정리한다(시스템 temp라 저장소에는 아무것도 남기지 않는다).
    shutil.rmtree(QA_DIR, ignore_errors=True)
    check_true("qa temp dir removed", not os.path.exists(QA_DIR), QA_DIR)




# ===========================================================================
# RunLock — 동시 실행 방지 (2026-08-21 Sprint 242 신설)
#
# ## 왜 뒤늦게 생겼나
#
# `RunLock` 은 `storage/checkpoint.py` 에 있는데 이 파일은 checkpoint 저장/조회만
# 검사하고 있었다. 락 자체는 `test_doc_worker_recovery.py` 가 **간접적으로만** 지나갔다.
#
# mutation 으로 그 공백을 확인했다(2026-08-21):
#
#     O_EXCL 제거 (보고 나서 쓴다 = 경쟁 창 생성)
#         -> doc_worker_recovery 만 잡는다. 이 파일은 통과.
#     `age_hours < stale_hours` 를 항상 거짓으로 (신선한 락도 뺏는다)
#         -> ★ **어떤 검사도 잡지 못했다.**
#
# 두 번째가 위험하다. 그 상태에서는 **지금 돌고 있는 워커의 락을 다음 실행이 빼앗는다.**
# 그러면 doc_worker 두 개가 동시에 뜨고, 이 락이 애초에 막으려던 것 —
# Selenium 다운로드 폴더 교차 오염(한쪽이 받은 파일을 다른 쪽이 자기 것으로 착각해
# **엉뚱한 물건에 연결**) — 이 그대로 일어난다. 조용히 틀리는 데이터가 된다.
#
# 그래서 락의 **판정 경계**를 여기서 못 박는다.
# ===========================================================================

def _lock_env():
    """락 검사용 임시 디렉터리와 RunLock 클래스."""
    import tempfile
    from storage.checkpoint import RunLock
    return tempfile.mkdtemp(prefix="qa_runlock_"), RunLock


def test_runlock_refuses_a_second_holder():
    print("\n--- 5. RunLock: 두 번째 실행은 들어오지 못한다 ---")
    import os
    import shutil
    tmp, RunLock = _lock_env()
    try:
        path = os.path.join(tmp, "x.lock")
        a = RunLock(path, stale_hours=5, label="A")
        b = RunLock(path, stale_hours=5, label="B")

        check("첫 실행은 락을 잡는다", a.acquire(), True)
        check_true("락 파일이 실제로 생긴다", os.path.exists(path), path)
        check("★ 두 번째 실행은 잡지 못한다", b.acquire(), False)
        check_true("두 번째가 실패해도 락 파일은 그대로다(남의 것을 지우지 않는다)",
                   os.path.exists(path), path)

        a.release()
        check_true("해제하면 락 파일이 사라진다", not os.path.exists(path), path)
        check("해제 뒤에는 두 번째가 잡을 수 있다", b.acquire(), True)
        b.release()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_runlock_does_not_steal_a_fresh_lock():
    """★ 이 검사가 없어서 mutation 이 살아남았다.

    `age_hours < stale_hours` 판정을 없애면 **신선한 락도 회수 대상**이 되어
    실행 중인 워커의 락을 다음 실행이 빼앗는다. 그 상태는 조용하다 — 로그도
    "오래된 락 회수"라고만 남고, 두 워커가 같은 다운로드 폴더를 쓰기 시작한다.
    """
    print("\n--- 6. RunLock: 살아 있는 락을 빼앗지 않는다 (경계) ---")
    import os
    import shutil
    import time
    tmp, RunLock = _lock_env()
    try:
        path = os.path.join(tmp, "y.lock")
        STALE = 5.0
        owner = RunLock(path, stale_hours=STALE, label="owner")
        other = RunLock(path, stale_hours=STALE, label="other")
        check("소유자가 락을 잡는다", owner.acquire(), True)

        # 방금 만든 락 — 절대 뺏기면 안 된다
        check("★ 갓 만든 락은 빼앗기지 않는다", other.acquire(), False)

        # 임계 **직전**: 아직 살아 있다고 봐야 한다
        just_under = time.time() - (STALE - 0.5) * 3600
        os.utime(path, (just_under, just_under))
        check("★ 임계 직전(%.1f시간)에도 빼앗기지 않는다" % (STALE - 0.5),
              other.acquire(), False)
        check_true("빼앗지 못했으므로 회수 토큰도 남기지 않는다",
                   not os.path.exists(path + ".reclaim"), "reclaim 토큰이 남았다")

        # 임계 **초과**: 죽은 실행으로 보고 회수해야 한다
        just_over = time.time() - (STALE + 1) * 3600
        os.utime(path, (just_over, just_over))
        check("★ 임계를 넘으면(%.1f시간) 회수한다" % (STALE + 1), other.acquire(), True)
        check_true("회수 후 락 파일은 존재한다(새 소유자 것)", os.path.exists(path), path)
        other.release()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_runlock_is_atomic_under_concurrency():
    """동시에 들어와도 **정확히 하나만** 이긴다.

    `os.path.exists()` 로 보고 나서 `open()` 으로 쓰면 그 사이가 열려 있어
    동시에 들어온 실행이 전부 통과한다(이 저장소 실측: 스레드 8 x 200라운드에서
    **200라운드 전부** 8개가 동시에 성공). `O_CREAT|O_EXCL` 은 커널이 한 번에
    판정하므로 그 창이 없다.
    """
    print("\n--- 7. RunLock: 동시 진입에서 하나만 이긴다 ---")
    import os
    import shutil
    import threading
    tmp, RunLock = _lock_env()
    try:
        path = os.path.join(tmp, "z.lock")
        ROUNDS, THREADS = 60, 8
        multi = 0
        for _ in range(ROUNDS):
            winners = []
            barrier = threading.Barrier(THREADS)
            lock = threading.Lock()

            def worker():
                rl = RunLock(path, stale_hours=5, label="t")
                barrier.wait()
                if rl.acquire():
                    with lock:
                        winners.append(rl)

            ts = [threading.Thread(target=worker) for _ in range(THREADS)]
            for t in ts: t.start()
            for t in ts: t.join()
            if len(winners) != 1:
                multi += 1
            for w in winners:
                w.release()
            try: os.remove(path)
            except OSError: pass

        print("    %d라운드 x %d스레드: 동시 성공이 일어난 라운드 %d" % (ROUNDS, THREADS, multi))
        check("★ 어떤 라운드에서도 둘 이상이 동시에 잡지 못한다", multi, 0)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

def test_runlock_reclaim_token_contention():
    """오래된 락을 **두 실행이 동시에 회수하려 할 때** 한 쪽만 들어간다
    (2026-08-24 Sprint 254 신설).

    ## 왜 이것까지 봐야 하나

    회수 자체는 위 6번이 본다. 그런데 회수는 "오래된 락 파일을 지우고 새로 만드는"
    **여러 단계**라, 두 실행이 같이 들어오면 둘 다 성공할 수 있다. 그래서 제품은
    `<lock>.reclaim` 토큰을 배타적으로 만들어 회수 구간 자체를 하나로 좁힌다.

    그 토큰 경합 경로가 합산 커버리지에서 **한 줄도 실행되지 않고 있었다**
    (`storage/checkpoint.py` 148-166). 하필 이 구간이 뚫리면 **두 워커가 동시에
    돈다** — 그것이 BUGS #181(회수당한 행을 옛 실행이 종결한다)의 전제 조건이다.
    즉 이 검사는 #181 의 **한 층 위**를 지킨다.

    토큰 파일을 직접 만들어 두면 확률 없이 그 경로를 밟을 수 있다.
    """
    print("\n--- 8. RunLock: 회수 토큰 경합 (Sprint 254) ---")
    import os
    import shutil
    import time
    tmp, RunLock = _lock_env()
    try:
        path = os.path.join(tmp, "z.lock")
        token = path + ".reclaim"
        STALE = 5.0
        old = time.time() - (STALE + 1) * 3600

        owner = RunLock(path, stale_hours=STALE, label="owner")
        check("설정: 소유자가 락을 잡는다", owner.acquire(), True)
        os.utime(path, (old, old))       # 그 소유자는 죽었다고 치자

        # (1) 다른 실행이 **지금 회수 중**이다 — 갓 만든 토큰이 있다.
        with open(token, "w") as f:
            f.write("qa-other-reclaimer")
        check("★ 회수가 진행 중이면 물러난다(둘이 동시에 회수하지 않는다)",
              RunLock(path, STALE, "late").acquire(), False)
        check_true("남의 회수 토큰을 지우지 않는다", os.path.exists(token), token)

        # (2) 회수하다 **죽은** 토큰 — 토큰 자체가 오래됐다.
        os.utime(token, (old, old))
        check("★ 죽은 회수 토큰은 넘어서 회수한다(영구 교착이 되지 않는다)",
              RunLock(path, STALE, "recoverer").acquire(), True)
        check_true("회수가 끝나면 토큰을 치운다(다음 실행을 막지 않는다)",
                   not os.path.exists(token), "토큰이 남았다: %s" % token)
        check_true("회수한 쪽이 락을 가진다", os.path.exists(path), path)

        # (3) 죽은 토큰을 **둘이 동시에** 넘어서려 할 때. 하나가 지우고 새로 만드는
        #     사이에 다른 하나가 먼저 가져가면, 진 쪽은 물러나야 한다.
        #     여기가 뚫리면 둘 다 회수 구간에 들어가고 = 두 워커가 동시에 돈다.
        os.utime(path, (old, old))
        with open(token, "w") as f:
            f.write("qa-dead-reclaimer")
        os.utime(token, (old, old))

        loser = RunLock(path, STALE, "loser")
        real_create = loser._create_exclusive
        seen = {"reclaim_calls": 0, "stolen": False}

        def create_but_lose_the_token(target):
            # 순서를 따라간다:
            #   1회차  이미 있는 죽은 토큰 때문에 실패 -> 제품이 그것을 지운다
            #   2회차  제품이 새 토큰을 만들려는 **그 순간** 경쟁자가 먼저 만든다
            if target.endswith(".reclaim"):
                seen["reclaim_calls"] += 1
                if seen["reclaim_calls"] == 2:
                    seen["stolen"] = True
                    with open(target, "w") as fh:
                        fh.write("qa-winner")
            return real_create(target)

        loser._create_exclusive = create_but_lose_the_token
        got = loser.acquire()
        check_true("검사가 공허하지 않다(2회차에서 경쟁자가 실제로 토큰을 가져갔다)",
                   seen["stolen"], seen)
        check("★ 토큰 경쟁에서 지면 회수하지 않고 물러난다", got, False)
        check_true("진 쪽이 이긴 쪽의 토큰을 지우지 않는다", os.path.exists(token), token)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_runlock_reclaim_rechecks_after_taking_the_token():
    """토큰을 잡은 뒤 **다시 확인한다** — 그 사이 정상적으로 잡힌 락을 빼앗지 않는다.

    토큰을 얻기까지 시간이 걸리는 동안 원래 락이 정상적으로 갱신·재취득될 수 있다.
    그때 확인 없이 지우면 **살아 있는 실행의 락을 빼앗는다** — 두 워커가 같은
    다운로드 폴더를 쓰기 시작하고, 큐 행도 서로 뺏는다(BUGS #181 의 전제).
    """
    print("\n--- 9. RunLock: 토큰을 잡은 뒤 다시 확인한다 (Sprint 254) ---")
    import os
    import shutil
    import time
    tmp, RunLock = _lock_env()
    try:
        path = os.path.join(tmp, "w.lock")
        STALE = 5.0
        old = time.time() - (STALE + 1) * 3600

        # 오래된 락을 만들어 두고, **회수 판정과 실제 회수 사이에** 락을 새것으로 바꾼다.
        RunLock(path, STALE, "dead").acquire()
        os.utime(path, (old, old))

        late = RunLock(path, STALE, "late")
        real_create = late._create_exclusive
        flipped = {"done": False}

        def create_and_flip(target):
            ok = real_create(target)
            # 회수 토큰을 막 잡은 순간 — 그 사이 원래 락이 정상 갱신됐다고 만든다.
            if ok and target.endswith(".reclaim") and not flipped["done"]:
                flipped["done"] = True
                now = time.time()
                os.utime(path, (now, now))
            return ok

        late._create_exclusive = create_and_flip
        got = late.acquire()

        check_true("검사가 공허하지 않다(끼어들기가 실제로 일어났다)",
                   flipped["done"], flipped)
        check("★ 그 사이 정상 갱신된 락을 빼앗지 않는다", got, False)
        check_true("★ 물러날 때 회수 토큰을 남기지 않는다(다음 회수를 막지 않는다)",
                   not os.path.exists(path + ".reclaim"), "토큰이 남았다")

        # 대조군: 끼어들기가 없으면 같은 상황에서 회수에 성공한다.
        os.utime(path, (old, old))
        check("대조군: 끼어들기가 없으면 회수한다",
              RunLock(path, STALE, "clean").acquire(), True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_runlock_reclaims_when_the_lock_vanishes_mid_reclaim():
    """토큰을 잡은 뒤 락 파일이 **사라져 있으면** 그냥 잡는다.

    소유자가 정상 종료하며 `release()` 한 경우다. "없어졌으니 잡아도 된다" 가
    맞는 판단이고, 여기서 물러나면 아무도 안 쓰는 락 때문에 한 번을 통째로 건너뛴다.
    """
    print("\n--- 10. RunLock: 회수 도중 락이 사라지면 잡는다 (Sprint 254) ---")
    import os
    import shutil
    import time
    tmp, RunLock = _lock_env()
    try:
        path = os.path.join(tmp, "v.lock")
        STALE = 5.0
        old = time.time() - (STALE + 1) * 3600
        RunLock(path, STALE, "dead").acquire()
        os.utime(path, (old, old))

        late = RunLock(path, STALE, "late")
        real_create = late._create_exclusive
        removed = {"done": False}

        def create_and_remove(target):
            ok = real_create(target)
            if ok and target.endswith(".reclaim") and not removed["done"]:
                removed["done"] = True
                os.remove(path)      # 소유자가 그 사이 정상 종료했다
            return ok

        late._create_exclusive = create_and_remove
        got = late.acquire()

        check_true("검사가 공허하지 않다(락이 실제로 사라졌다)", removed["done"], removed)
        check("★ 사라진 락 때문에 한 번을 건너뛰지 않는다", got, True)
        check_true("회수 토큰은 치운다", not os.path.exists(path + ".reclaim"), "토큰 잔존")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_runlock_takes_a_lock_that_vanishes_while_being_inspected():
    """락이 **있다고 본 직후 사라지면** 곧바로 다시 잡는다 (2026-08-24 Sprint 254).

    소유자가 정확히 그 순간 `release()` 한 경우다. 여기서 물러나면 아무도 쓰지 않는
    락 때문에 그 실행을 통째로 건너뛴다 - 하루치 수집이 사라진다는 뜻이다.

    ★ 이 경로는 원래 `test_doc_worker_recovery.py` 의 **스레드 8개 검사**가
      "가끔" 밟고 있었다(합산 커버리지가 실행마다 달라지는 것으로 드러났다).
      가끔 밟는 것은 방어선이 아니다 - 창을 직접 벌려 확률을 없앤다.
    """
    print("\n--- 11. RunLock: 확인하는 사이 락이 사라지면 잡는다 (Sprint 254) ---")
    import os
    import shutil
    tmp, RunLock = _lock_env()
    try:
        path = os.path.join(tmp, "u.lock")
        check("설정: 소유자가 락을 잡는다", RunLock(path, 5, "owner").acquire(), True)

        late = RunLock(path, 5, "late")
        real_create = late._create_exclusive
        vanished = {"done": False}

        def create_then_vanish(target):
            ok = real_create(target)
            # 첫 시도는 실패한다(락이 있다). 그 직후 소유자가 정상 종료한다.
            if not ok and target == path and not vanished["done"]:
                vanished["done"] = True
                os.remove(path)
            return ok

        late._create_exclusive = create_then_vanish
        got = late.acquire()

        check_true("검사가 공허하지 않다(확인 직후 실제로 사라졌다)",
                   vanished["done"], vanished)
        check("★ 사라진 락 때문에 실행을 건너뛰지 않는다", got, True)
        check_true("잡았으면 락 파일이 있다", os.path.exists(path), path)
        check_true("불필요한 회수 토큰을 만들지 않는다",
                   not os.path.exists(path + ".reclaim"), "토큰이 남았다")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_runlock_backs_off_when_the_filesystem_is_weird():
    """지울 수 없는 것이 락/토큰 자리에 있으면 **조용히 물러난다** (2026-08-24 Sprint 254).

    OneDrive 동기화 폴더에서 도는 저장소라 잔여물이 남는 일이 실제로 있다(이 파일
    상단이 그 사고를 이미 기록하고 있다). 그 자리에 디렉터리가 남아 있으면
    `os.remove()` 가 던진다 - 그때 예외를 위로 올리면 **배치 전체가 죽는다.**
    락을 못 얻는 것은 실패가 아니라 "이번엔 안 한다" 이므로 False 로 물러나야 한다.

    디렉터리를 파일 자리에 두면 Windows/POSIX 양쪽에서 `os.remove()` 가 OSError 를
    낸다 - 표준 라이브러리를 갈아 끼우지 않고 그 방어선을 밟을 수 있다.
    """
    print("\n--- 12. RunLock: 이상한 파일시스템 상태에서 물러난다 (Sprint 254) ---")
    import os
    import shutil
    import time
    tmp, RunLock = _lock_env()
    try:
        STALE = 5.0
        old = time.time() - (STALE + 1) * 3600

        # (1) 락 자리에 **디렉터리**가 있다 - 오래됐지만 지울 수 없다.
        path = os.path.join(tmp, "dir.lock")
        os.mkdir(path)
        os.utime(path, (old, old))
        raised = None
        got = None
        try:
            got = RunLock(path, STALE, "weird").acquire()
        except Exception as exc:  # noqa: BLE001 - 예외가 나가지 않는 것이 검사 대상이다
            raised = exc
        check("★ 락을 지울 수 없어도 예외를 올리지 않는다", raised, None)
        check("★ 잡지 못했다고 정직하게 답한다", got, False)
        check_true("치우지 못한 회수 토큰을 남기지 않는다",
                   not os.path.exists(path + ".reclaim"), "토큰 잔존")

        # (2) 회수 토큰 자리에 **디렉터리**가 있다 - 역시 오래됐지만 지울 수 없다.
        path2 = os.path.join(tmp, "t.lock")
        check("설정: 오래된 락을 만든다", RunLock(path2, STALE, "dead").acquire(), True)
        os.utime(path2, (old, old))
        token_dir = path2 + ".reclaim"
        os.mkdir(token_dir)
        os.utime(token_dir, (old, old))
        raised = None
        got = None
        try:
            got = RunLock(path2, STALE, "weird2").acquire()
        except Exception as exc:  # noqa: BLE001
            raised = exc
        check("★ 회수 토큰을 지울 수 없어도 예외를 올리지 않는다", raised, None)
        check("★ 그때도 잡지 못했다고 답한다", got, False)
        check_true("★ 남의 것을 지우려다 락까지 날리지 않는다", os.path.exists(path2), path2)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_default_path_does_not_follow_cwd():
    """★ 기본 체크포인트 경로가 **cwd 를 따라가지 않는가** (2026-08-27, BUGS #263).

    ## 무엇이 문제였나

    예전 기본값은 `"logs/checkpoint.json"` 이라 **cwd 기준**이었다. 저장소가 아닌 곳에서
    크롤러를 띄우면 그 폴더에 `logs/checkpoint.json` 이 새로 생기고:

        저장소의 진짜 체크포인트를 **못 찾는다** -> resume_from=None -> **처음부터 다시 긁는다**
        진행 상황은 엉뚱한 폴더에 쌓인다        -> 다음 실행도 못 찾는다

    즉 **재개가 조용히 무력화된다.** 오류도 경고도 없다 — 어제 다 한 법원을 오늘
    처음부터 다시 돈다(상세페이지 이동 실측 중앙값 10.9초/건).

    Sprint 245/246/252 가 같은 계열을 네 곳에서 고쳤는데(`api/auth.py` 의 load_dotenv,
    `storage/database.py` 의 DB_PATH, `doc_worker.py` 의 LOCK_PATH, `mvp_scraper.py` 의
    CSV) **여기만 남아 있었다.**

    ## 정적 검사가 왜 못 잡았나

    `test_schema_hygiene.py` 의 cwd 감사는 (A) 모듈 최상위 상수 할당과 (B) 경로 호출의
    문자열 리터럴을 봤다. 여기는 **함수 기본 인자값**이라 둘 다 비껴갔다.
    그 감사도 함께 고쳤지만(갈래 C/D 추가), 정적 검사만 믿지 않는다 —
    **다른 cwd 에서 실제로 만들어 본다.**
    """
    print("\n--- 기본 경로가 cwd 를 따라가지 않는가 (BUGS #263) ---")
    import subprocess
    import shutil as _shutil

    root = os.path.dirname(os.path.abspath(__file__))
    probe = tempfile.mkdtemp(prefix="cp-cwd-probe-")
    code = (
        "import sys, os, json;"
        " sys.path.insert(0, r'%s');"
        " from storage.checkpoint import CheckpointManager;"
        " cm = CheckpointManager();"
        " print(json.dumps({'path': os.path.abspath(cm.path), 'cwd': os.getcwd()}))"
    ) % root
    try:
        r = subprocess.run([sys.executable, "-c", code], cwd=probe,
                           capture_output=True, timeout=120,
                           env=dict(os.environ, PYTHONIOENCODING="utf-8"))
        out = (r.stdout or b"").decode("utf-8", "replace").strip().splitlines()
        payload = None
        for line in reversed(out):
            if line.startswith("{"):
                payload = json.loads(line)
                break
        check_true("다른 cwd 에서 CheckpointManager 를 실제로 만들었다", payload is not None,
                   "-> stdout=%r stderr=%r" % (out[-3:], (r.stderr or b"")[-300:]))
        if payload:
            check_true("전제: 정말 다른 cwd 에서 돌았다",
                       os.path.normcase(payload["cwd"]) != os.path.normcase(root),
                       payload["cwd"])
            check_true("★ 기본 경로가 저장소 안을 가리킨다(cwd 가 아니라)",
                       os.path.normcase(os.path.dirname(payload["path"]))
                       == os.path.normcase(os.path.join(root, "logs")),
                       "-> %s" % payload["path"])
        # cwd 에 logs/ 가 새로 생기지 않았는지도 본다 - 경로만 맞고 부수효과가 남으면 반쪽이다.
        check("★ 실행 폴더에 logs/ 가 생기지 않는다",
              sorted(os.listdir(probe)), [])
    finally:
        _shutil.rmtree(probe, ignore_errors=True)

    # 명시 경로를 넘기던 기존 계약은 그대로다(이 파일의 다른 검사 전부가 그것을 쓴다).
    check("명시 경로는 그대로 쓰인다", CheckpointManager(path="X/y.json").path, "X/y.json")


def run():
    try:
        test_default_path_does_not_follow_cwd()
        test_save_get_clear_roundtrip()
        test_atomic_write_survives_simulated_crash()
        test_corrupted_file_does_not_crash_get()
        test_write_failure_does_not_stop_the_crawl()
        test_runlock_refuses_a_second_holder()
        test_runlock_does_not_steal_a_fresh_lock()
        test_runlock_is_atomic_under_concurrency()
        test_runlock_reclaim_token_contention()
        test_runlock_reclaim_rechecks_after_taking_the_token()
        test_runlock_reclaims_when_the_lock_vanishes_mid_reclaim()
        test_runlock_takes_a_lock_that_vanishes_while_being_inspected()
        test_runlock_backs_off_when_the_filesystem_is_weird()
    finally:
        cleanup()

    print("\n" + "=" * 55)
    if failures:
        print("FAILED (%d): %s" % (len(failures), ", ".join(failures)))
        return 1
    print("ALL TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(run())
