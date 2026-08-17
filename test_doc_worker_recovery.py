"""
doc_worker.py의 브라우저/드라이버 장애 복구 회귀 테스트 (2026-08-16, Sprint 137).

`doc_worker.py`는 selenium을 import하므로(BUGS #47이 CrawlOutcome/DocWorkerOutcome을
`models/crawl_outcome.py`로 분리한 것과 같은 이유), 실제 브라우저를 띄우지 않고
`doc_worker.main()`을 돌리려면 모든 브라우저 호출부(claim_next_queue_item/
go_to_case_detail/collect_document/restart_download_driver/build_download_driver 등)를
가짜로 바꿔야 한다. 이 파일은 그 몽키패치만 담당하고, 실제 검증 대상은
"드라이버 재시작 자체가 실패했을 때 나머지 큐 항목을 계속 갉아먹지 않는가"다.

    python test_doc_worker_recovery.py
"""
import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["DOC_WORKER_TEST_MODE"] = "1"

import doc_worker

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


class _FakeDriver:
    def __init__(self, label):
        self.label = label
        self.quit_called = False

    def quit(self):
        self.quit_called = True


def _make_fake_queue(n):
    return [
        {
            "id": 100 + i, "court_code": "QA법원", "case_no": "2026타경QA%03d" % i,
            "item_no": "1", "doc_type": "spec", "retry_count": 0, "auction_date": "2099-01-01",
        }
        for i in range(n)
    ]


def _patch_all(monkeypatch_targets):
    originals = {}
    for name, value in monkeypatch_targets.items():
        originals[name] = getattr(doc_worker, name)
        setattr(doc_worker, name, value)
    return originals


def _restore_all(originals):
    for name, value in originals.items():
        setattr(doc_worker, name, value)


def test_driver_restart_failure_stops_run_instead_of_burning_retry_budget():
    """드라이버 재시작 자체가 실패하면, 남은 큐 항목은 아예 손대지 않고 이번 실행을
    끝내야 한다 - 손대면 그 항목들의 retry_count가 자기 문제와 무관하게 소모된다."""
    print("\n--- 1. 드라이버 재시작 실패 시 남은 큐를 갉아먹지 않는다 (Sprint 137) ---")

    queue = _make_fake_queue(3)
    claimed_calls = []
    failed_calls = []
    restart_calls = []

    def fake_claim_next_queue_item():
        if queue:
            item = queue.pop(0)
            claimed_calls.append(item["id"])
            return item
        return None

    # 2026-08-17 Sprint 144: doc_worker가 item_no까지 넘긴다(물건 사진은 버튼 없이
    # 상세 DOM을 읽으므로 **어느 물건의 페이지인지가 곧 결과**다). 스텁도 받아야 한다.
    def fake_go_to_case_detail(driver, court_code, case_no, item_no=None):
        raise Exception("qa-simulated-browser-crash")

    def fake_restart_download_driver(driver):
        restart_calls.append(1)
        raise Exception("qa-simulated-chromedriver-launch-failure")

    def fake_mark_queue_failed(queue_id, retry_count):
        failed_calls.append(queue_id)

    originals = _patch_all({
        "init_db": lambda: None,
        "reset_stale_queue": lambda: None,
        "build_download_driver": lambda: _FakeDriver("initial"),
        "claim_next_queue_item": fake_claim_next_queue_item,
        "get_doc_button_id": lambda doc_type, item_no: "qa-fake-btn-id",
        "go_to_case_detail": fake_go_to_case_detail,
        "restart_download_driver": fake_restart_download_driver,
        "mark_queue_failed": fake_mark_queue_failed,
        "mark_queue_skipped_expired": lambda *a, **kw: None,
        "mark_queue_unsupported": lambda *a, **kw: None,
        "mark_queue_done": lambda *a, **kw: None,
    })
    orig_sleep = doc_worker.time_module.sleep
    doc_worker.time_module.sleep = lambda *_a, **_kw: None
    try:
        exit_code = doc_worker.main()
    finally:
        _restore_all(originals)
        doc_worker.time_module.sleep = orig_sleep

    check("첫 번째 항목만 claim됐다(나머지 2건은 손대지 않음)", claimed_calls, [100])
    check("드라이버 재시작 시도는 정확히 1번뿐이다(재시도 폭주 없음)", len(restart_calls), 1)
    check("mark_queue_failed는 정확히 1번만 호출된다(관련 없는 나머지 항목의 "
          "retry_count를 갉아먹지 않는다)", failed_calls, [100])
    check("큐에 2건이 그대로 남아 있다(데이터 유실이 아니라 조기 중단)", len(queue), 2)
    check("전부 실패했으므로 종료 코드는 1이다(BUGS #47 - 조용한 성공 금지)", exit_code, 1)


def test_driver_restart_success_continues_processing():
    """드라이버 재시작이 성공하면(일시적 장애) 나머지 큐 항목은 정상적으로 계속
    처리돼야 한다 - 위 테스트가 "항상 멈춘다"로 과잉 수정되지 않았는지 확인한다."""
    print("\n--- 2. 드라이버 재시작 성공 시에는 계속 처리한다(과잉 중단 아님) ---")

    queue = _make_fake_queue(2)
    claimed_calls = []
    failed_calls = []
    done_calls = []
    restart_calls = []
    call_count = {"go_to_case_detail": 0}

    def fake_claim_next_queue_item():
        if queue:
            item = queue.pop(0)
            claimed_calls.append(item["id"])
            return item
        return None

    seen_item_nos = []

    def fake_go_to_case_detail(driver, court_code, case_no, item_no=None):
        call_count["go_to_case_detail"] += 1
        seen_item_nos.append(item_no)
        if call_count["go_to_case_detail"] == 1:
            raise Exception("qa-simulated-one-off-crash")
        return True

    def fake_collect_document(driver, court_code, case_no, item_no, doc_type, btn_id):
        return {"success": True, "previous_hash": None, "new_hash": "qa-hash", "partial": False}

    def fake_restart_download_driver(driver):
        restart_calls.append(1)
        return _FakeDriver("restarted")

    def fake_mark_queue_failed(queue_id, retry_count):
        failed_calls.append(queue_id)

    def fake_mark_queue_done(queue_id, *a, **kw):
        done_calls.append(queue_id)

    originals = _patch_all({
        "init_db": lambda: None,
        "reset_stale_queue": lambda: None,
        "build_download_driver": lambda: _FakeDriver("initial"),
        "claim_next_queue_item": fake_claim_next_queue_item,
        "get_doc_button_id": lambda doc_type, item_no: "qa-fake-btn-id",
        "go_to_case_detail": fake_go_to_case_detail,
        "collect_document": fake_collect_document,
        "restart_download_driver": fake_restart_download_driver,
        "mark_queue_failed": fake_mark_queue_failed,
        "mark_queue_skipped_expired": lambda *a, **kw: None,
        "mark_queue_unsupported": lambda *a, **kw: None,
        "mark_queue_done": fake_mark_queue_done,
    })
    orig_sleep = doc_worker.time_module.sleep
    doc_worker.time_module.sleep = lambda *_a, **_kw: None
    try:
        exit_code = doc_worker.main()
    finally:
        _restore_all(originals)
        doc_worker.time_module.sleep = orig_sleep

    # 물건번호를 실제로 넘기는지 고정한다 — 넘기지 않으면 다중물건 사건에서 첫 물건의
    # 상세페이지에 들어가 **다른 물건의 사진**을 저장하게 된다 (Sprint 144).
    check("go_to_case_detail에 물건번호를 넘긴다", seen_item_nos, ["1", "1"])
    check("두 항목 다 claim됐다(재시작 성공 후 계속 진행)", claimed_calls, [100, 101])
    check("재시작은 1번만 일어났다", len(restart_calls), 1)
    check("첫 항목만 실패로 기록된다", failed_calls, [100])
    check("두 번째 항목은 정상 성공한다", done_calls, [101])
    check("성공 건이 있으므로 종료 코드는 0이다", exit_code, 0)


def test_lock_prevents_concurrent_run():
    """락 파일이 이미 있으면(신선함) 큐를 전혀 건드리지 않고 즉시 종료해야 한다.

    2026-08-16 Sprint 142 (Scheduler/Worker Audit) ― DOWNLOAD_DIR가 모든
    doc_worker.py 실행이 공유하는 경로라, 두 인스턴스가 동시에 돌면 한쪽이 받은
    파일을 다른 쪽이 자기 것으로 착각할 수 있다(교차 오염). 이 테스트는 그
    시나리오 자체를 막는 락이 실제로 큐 접근을 막는지 확인한다 — claim이 한 번이라도
    불리면 즉시 실패하도록 만들어서, "락이 있으면 아예 손대지 않는다"를 강하게 검증한다.
    """
    print("\n--- 3. 락 파일이 있으면 큐를 전혀 건드리지 않는다 (Sprint 142) ---")
    os.makedirs("logs", exist_ok=True)
    with open(doc_worker.LOCK_PATH, "w", encoding="utf-8") as f:
        f.write("99999 qa-fake-lock")

    def fail_if_called(*_a, **_kw):
        raise AssertionError("claim_next_queue_item이 불렸다 - 락이 큐 접근을 막지 못했다")

    originals = _patch_all({
        "init_db": fail_if_called,
        "reset_stale_queue": fail_if_called,
        "build_download_driver": fail_if_called,
        "claim_next_queue_item": fail_if_called,
    })
    try:
        exit_code = doc_worker.main()
    finally:
        _restore_all(originals)
        try:
            os.remove(doc_worker.LOCK_PATH)
        except OSError:
            pass

    check("락 충돌 시 큐/브라우저를 전혀 건드리지 않고 종료 코드 0", exit_code, 0)


def test_stale_lock_is_taken_over():
    """락 파일이 LOCK_STALE_HOURS보다 오래됐으면 죽은 실행으로 보고 회수해야 한다."""
    print("\n--- 4. 오래된 락은 죽은 실행으로 간주하고 회수한다 (Sprint 142) ---")
    os.makedirs("logs", exist_ok=True)
    with open(doc_worker.LOCK_PATH, "w", encoding="utf-8") as f:
        f.write("88888 qa-stale-lock")
    stale_time = time.time() - (doc_worker.LOCK_STALE_HOURS + 1) * 3600
    os.utime(doc_worker.LOCK_PATH, (stale_time, stale_time))

    acquired = doc_worker._acquire_lock()
    check("오래된 락은 회수해 새로 잡을 수 있다", acquired, True)

    try:
        os.remove(doc_worker.LOCK_PATH)
    except OSError:
        pass


def test_lock_released_after_normal_run():
    """정상 실행이 끝나면(성공이든 실패든) 락 파일이 남지 않아야 한다 — 다음 날 실행이
    "이미 실행 중"으로 영원히 막히면 안 된다."""
    print("\n--- 5. 정상 종료 후에는 락이 해제된다 (Sprint 142) ---")
    if os.path.exists(doc_worker.LOCK_PATH):
        os.remove(doc_worker.LOCK_PATH)

    originals = _patch_all({
        "init_db": lambda: None,
        "reset_stale_queue": lambda: None,
        "build_download_driver": lambda: _FakeDriver("initial"),
        "claim_next_queue_item": lambda: None,  # 큐가 비어 즉시 종료
    })
    orig_sleep = doc_worker.time_module.sleep
    doc_worker.time_module.sleep = lambda *_a, **_kw: None
    try:
        doc_worker.main()
    finally:
        _restore_all(originals)
        doc_worker.time_module.sleep = orig_sleep

    check("실행 종료 후 락 파일이 남지 않는다", os.path.exists(doc_worker.LOCK_PATH), False)


def test_driver_startup_failure_releases_lock():
    """드라이버 **기동** 실패도 락을 남기면 안 된다 (2026-08-17 Sprint 148, BUGS #109).

    5번은 "정상 종료"를 본다. 그런데 예전에는 `build_download_driver()` 호출이 락을
    해제하는 두 구간 사이에 끼어 있었다 — 위쪽 try/except(init_db/reset_stale_queue용)
    **밖**이고, 아래쪽 while의 try/finally **앞**이었다. 그래서 기동이 실패하면 락이
    그대로 남았다(실측 재현: logs/doc_worker.lock에 죽은 PID가 남음).

    `LOCK_STALE_HOURS=5`가 있어 영구 정지는 아니지만, 하필 곧바로 재시도하고 싶은 5시간
    동안 후속 실행이 "다른 인스턴스 실행 중"으로 건너뛴다. 드라이버 기동 실패는 크롬
    업데이트 같은 일시적 원인이 많아 재시도 가치가 큰데, 그 창을 스스로 막고 있었다.

    예외는 그대로 전파돼야 한다 — 스케줄러가 실패를 인지해야 하므로 삼키면 안 된다.
    """
    print("\n--- 6. 드라이버 기동 실패도 락을 해제한다 (Sprint 148) ---")
    if os.path.exists(doc_worker.LOCK_PATH):
        os.remove(doc_worker.LOCK_PATH)

    class _StartupBoom(Exception):
        pass

    def _boom():
        raise _StartupBoom("드라이버 기동 실패 모사")

    originals = _patch_all({
        "init_db": lambda: None,
        "reset_stale_queue": lambda: None,
        "build_download_driver": _boom,
        "claim_next_queue_item": lambda: None,
    })
    raised = None
    try:
        doc_worker.main()
    except _StartupBoom as exc:
        raised = exc
    except Exception as exc:            # noqa: BLE001 - 어떤 예외인지 그대로 보고한다
        raised = exc
    finally:
        _restore_all(originals)

    check_true("기동 실패 예외가 전파된다(스케줄러가 실패로 인지)",
               isinstance(raised, _StartupBoom), repr(raised))
    check("기동 실패 후에도 락 파일이 남지 않는다",
          os.path.exists(doc_worker.LOCK_PATH), False)


def test_out_of_window_run_does_not_start_browser():
    """실행 창이 지났으면 브라우저를 띄우지 않고 끝나야 한다 (Sprint 148).

    예전에는 시간 검사가 `while not is_time_up()` 루프 조건에만 있어서, 창 밖에서
    기동하면 Selenium을 **띄운 뒤** 첫 조건에서 곧바로 빠져나왔다. 스케줄러 실행이
    밀렸거나 수동으로 돌릴 때 실제로 도달한다(2026-08-17 14:22 실측).
    """
    print("\n--- 7. 실행 창 밖에서는 브라우저를 띄우지 않는다 (Sprint 148) ---")
    if os.path.exists(doc_worker.LOCK_PATH):
        os.remove(doc_worker.LOCK_PATH)

    started = {"driver": False, "reset": False}

    def _spy_driver():
        started["driver"] = True
        return _FakeDriver("should-not-happen")

    def _spy_reset():
        started["reset"] = True

    # is_time_up()이 True가 되도록 테스트 모드를 끄고 종료시각을 지난 값으로 만든다.
    prev_mode = os.environ.pop("DOC_WORKER_TEST_MODE", None)
    prev_end = doc_worker.DOC_WORKER_END_TIME
    doc_worker.DOC_WORKER_END_TIME = "00:00"      # 항상 지난 시각
    originals = _patch_all({
        "init_db": lambda: None,
        "reset_stale_queue": _spy_reset,
        "build_download_driver": _spy_driver,
        "claim_next_queue_item": lambda: None,
    })
    try:
        rc = doc_worker.main()
    finally:
        _restore_all(originals)
        doc_worker.DOC_WORKER_END_TIME = prev_end
        if prev_mode is not None:
            os.environ["DOC_WORKER_TEST_MODE"] = prev_mode

    check("창 밖 실행도 성공 종료코드", rc, 0)
    check("브라우저를 띄우지 않는다", started["driver"], False)
    check("큐 상태도 건드리지 않는다", started["reset"], False)
    check("창 밖 실행 후 락이 남지 않는다",
          os.path.exists(doc_worker.LOCK_PATH), False)


def test_driver_setup_failure_does_not_orphan_browser():
    """드라이버 생성 후 설정이 실패하면 브라우저를 닫아야 한다 (Sprint 149, BUGS #110).

    `build_download_driver()`는 `webdriver.Chrome(...)`으로 **프로세스를 이미 띄운 뒤**
    `set_page_load_timeout(30)`을 부른다. 예전에는 이 설정이 실패하면 예외만 나가고
    프로세스는 고아로 남았다 — 호출자는 `driver` 참조를 받지 못했으니 quit()을 부를
    방법도 없다.

    BUGS #109와 같은 계열이고 실제로 맞물린다. #109 수정으로 기동 실패 시 락은 풀리지만,
    실패 지점이 여기라면 좀비 크롬이 남는다. 재시도마다 하나씩 쌓인다.

    `crawler/doc_crawler.py`는 실브라우저 의존이라 커버리지가 0%지만, 이 함수만은
    selenium 진입점을 갈아끼워 실제 브라우저 없이 검증할 수 있다.
    """
    print("\n--- 8. 드라이버 설정 실패가 브라우저를 고아로 남기지 않는다 (Sprint 149) ---")
    import selenium.webdriver as wd
    import selenium.webdriver.chrome.service as svcmod
    import webdriver_manager.chrome as wdm
    import crawler.doc_crawler as dc

    state = {"quit": 0}

    class _FakeChrome:
        def __init__(self, *a, **kw):
            pass

        def set_page_load_timeout(self, _t):
            raise RuntimeError("설정 중 브라우저 사망 모사")

        def quit(self):
            state["quit"] += 1

    class _FakeManager:
        def install(self):
            return "fake-driver-path"

    orig = (wd.Chrome, svcmod.Service, wdm.ChromeDriverManager)
    wd.Chrome = _FakeChrome
    svcmod.Service = lambda *a, **kw: None
    wdm.ChromeDriverManager = _FakeManager
    raised = None
    try:
        dc.build_download_driver()
    except Exception as exc:            # noqa: BLE001 - 어떤 예외인지 그대로 본다
        raised = exc
    finally:
        wd.Chrome, svcmod.Service, wdm.ChromeDriverManager = orig

    check_true("설정 실패 예외가 전파된다(호출자가 기동 실패를 인지)",
               isinstance(raised, RuntimeError), repr(raised))
    check("실패 시 브라우저를 닫는다(좀비 프로세스 없음)", state["quit"], 1)


def run():
    test_driver_restart_failure_stops_run_instead_of_burning_retry_budget()
    test_driver_restart_success_continues_processing()
    test_lock_prevents_concurrent_run()
    test_stale_lock_is_taken_over()
    test_lock_released_after_normal_run()
    test_driver_startup_failure_releases_lock()
    test_out_of_window_run_does_not_start_browser()
    test_driver_setup_failure_does_not_orphan_browser()

    print("\n" + "=" * 55)
    if failures:
        print("FAILED (%d): %s" % (len(failures), ", ".join(failures)))
        return 1
    print("ALL TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(run())
