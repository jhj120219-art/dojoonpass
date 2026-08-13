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
# (제품 코드는 그대로 `logs/checkpoint.json`을 쓴다 — 테스트 경로만 바꾼 것이다.)
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


def run():
    try:
        test_save_get_clear_roundtrip()
        test_atomic_write_survives_simulated_crash()
        test_corrupted_file_does_not_crash_get()
        test_write_failure_does_not_stop_the_crawl()
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
