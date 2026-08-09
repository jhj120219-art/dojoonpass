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


QA_PATH = "logs/qa-checkpoint-" + uuid.uuid4().hex[:8] + ".json"


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


def cleanup():
    print("\n--- cleanup (qa checkpoint file only) ---")
    for p in (QA_PATH, QA_PATH + ".tmp"):
        if os.path.exists(p):
            os.remove(p)
    check_true("qa checkpoint file removed", not os.path.exists(QA_PATH))


def run():
    try:
        test_save_get_clear_roundtrip()
        test_atomic_write_survives_simulated_crash()
        test_corrupted_file_does_not_crash_get()
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
