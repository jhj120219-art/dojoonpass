"""
doc_worker.py의 브라우저/드라이버 장애 복구 회귀 테스트 (2026-08-16, Sprint 137).

`doc_worker.py`는 selenium을 import하므로(BUGS #47이 CrawlOutcome/DocWorkerOutcome을
`models/crawl_outcome.py`로 분리한 것과 같은 이유), 실제 브라우저를 띄우지 않고
`doc_worker.main()`을 돌리려면 모든 브라우저 호출부(claim_next_item_rows/
go_to_case_detail/collect_document/restart_download_driver/build_download_driver 등)를
가짜로 바꿔야 한다. 이 파일은 그 몽키패치만 담당하고, 실제 검증 대상은
"드라이버 재시작 자체가 실패했을 때 나머지 큐 항목을 계속 갉아먹지 않는가"다.

    python test_doc_worker_recovery.py
"""
import contextlib
import io
import re
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

    def fake_claim_next_item_rows():
        # 2026-08-20 Sprint 236: claim 단위가 행 -> 물건으로 바뀌어 **목록**을 돌려준다.
        # 여기서는 여전히 한 번에 한 행만 준다 - 이 검사가 보는 것(재시작 실패 / 진입 실패)은
        # 묶음 크기와 무관하고, 기존 검증을 그대로 유지해야 비교가 성립한다.
        if queue:
            item = queue.pop(0)
            claimed_calls.append(item["id"])
            return [item]
        return []

    # 2026-08-17 Sprint 144: doc_worker가 item_no까지 넘긴다(물건 사진은 버튼 없이
    # 상세 DOM을 읽으므로 **어느 물건의 페이지인지가 곧 결과**다). 스텁도 받아야 한다.
    # 2026-08-20 Sprint 230: `require_exact_item` 이 함께 넘어온다(사진일 때만 True).
    #   `**kwargs` 로 뭉개지 않는다 — 그러면 다음에 인자가 바뀌어도 조용히 통과한다.
    def fake_go_to_case_detail(driver, court_code, case_no, item_no=None,
                               require_exact_item=False):
        raise Exception("qa-simulated-browser-crash")

    def fake_restart_download_driver(driver):
        restart_calls.append(1)
        raise Exception("qa-simulated-chromedriver-launch-failure")

    def fake_mark_queue_failed(queue_id, retry_count):
        failed_calls.append(queue_id)

    originals = _patch_all({
        "init_db": lambda: None,
        "reset_stale_queue": lambda: None,
        "release_queue_rows": lambda ids: 0,
        "build_download_driver": lambda: _FakeDriver("initial"),
        "claim_next_item_rows": fake_claim_next_item_rows,
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

    def fake_claim_next_item_rows():
        # 2026-08-20 Sprint 236: claim 단위가 행 -> 물건으로 바뀌어 **목록**을 돌려준다.
        # 여기서는 여전히 한 번에 한 행만 준다 - 이 검사가 보는 것(재시작 실패 / 진입 실패)은
        # 묶음 크기와 무관하고, 기존 검증을 그대로 유지해야 비교가 성립한다.
        if queue:
            item = queue.pop(0)
            claimed_calls.append(item["id"])
            return [item]
        return []

    seen_item_nos = []

    overwrite_seen = []

    # 2026-08-20 Sprint 230: `require_exact_item` 이 함께 넘어온다(사진일 때만 True).
    #   `**kwargs` 로 뭉개지 않는다 — 그러면 다음에 인자가 바뀌어도 조용히 통과한다.
    def fake_go_to_case_detail(driver, court_code, case_no, item_no=None,
                               require_exact_item=False):
        call_count["go_to_case_detail"] += 1
        seen_item_nos.append(item_no)
        if call_count["go_to_case_detail"] == 1:
            raise Exception("qa-simulated-one-off-crash")
        return True

    # ★ 실제 `collect_document()`와 **호출 호환**이어야 한다 (2026-08-18 Sprint 189).
    #   Sprint 189가 `overwrite=` 인자를 배선하자 이 대역이 TypeError를 냈고, doc_worker의
    #   except가 그것을 "수집 실패"로 삼켜 이 테스트가 4건 FAIL로 뒤집혔다 — 제품 결함이
    #   아니라 **대역이 실물보다 좁았던 것**이다. 앞으로 같은 드리프트에 흔들리지 않도록
    #   키워드를 그대로 받는다(그리고 넘어온 값을 기록해 검증에 쓸 수 있게 한다).
    def fake_collect_document(driver, court_code, case_no, item_no, doc_type, btn_id,
                              overwrite=False):
        overwrite_seen.append(bool(overwrite))
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
        "release_queue_rows": lambda ids: 0,
        "build_download_driver": lambda: _FakeDriver("initial"),
        "claim_next_item_rows": fake_claim_next_item_rows,
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


def test_case_not_reachable_does_not_restart_the_driver():
    """사건을 못 찾은 것으로 **드라이버를 재시작하지 않는다** (2026-08-20 Sprint 232).

    ## 왜 이것이 결함이었나

    `go_to_case_detail()` 이 False 를 돌려주는 이유는 둘 다 **정상적인 판단 결과**다.

        1. 그 사건이 법원 목록에 없다 (기일이 지나 빠졌거나 취하/변경)
        2. 물건번호가 모호해 **일부러 진입하지 않았다** (Sprint 230 의 사진 오염 방어)

    브라우저는 멀쩡하다. 그런데 예전 코드는 이것을 그냥 `Exception` 으로 올려
    `except` 절이 드라이버를 통째로 재시작했다.

    실측(`logs/doc_run.log` 11일치): "사건 매칭 실패" **255회**, 전부 재시작이 뒤따랐고
    재개까지 평균 **5.9초**(합계 25.1분 = 하루 평균 2.3분).

    시간 자체는 크지 않다. **진짜 문제는 연쇄다** — 재시작이 실패하면 Sprint 137 의
    방어가 발동해 **그 날 실행 전체를 중단**한다. "사건 하나를 못 찾았다"가
    하루치 수집을 죽일 이유가 없다. 게다가 Sprint 230 의 *의도적 거부* 도 같은 경로를
    타서 **옳은 판단이 재시작을 부르는** 모양이 됐다.

    ## 무엇을 고정하나

        못 찾은 항목만 실패 처리하고 **재시작 0회**
        다음 항목은 **그대로 계속** 처리된다(과잉 중단이 아니다)
        재시도 예산은 종전대로 소모한다(큐 의미론 불변)
        진짜 예외는 여전히 재시작한다(아래 대조군)
    """
    print("\n--- 8. 사건 미발견은 드라이버를 재시작하지 않는다 (Sprint 232) ---")

    queue = _make_fake_queue(2)
    claimed, failed, done, restarts = [], [], [], []

    def fake_claim():
        if queue:
            it = queue.pop(0)
            claimed.append(it["id"])
            return [it]           # Sprint 236: 물건 단위 claim 은 목록을 돌려준다
        return []

    calls = {"nav": 0}

    def fake_go(driver, court_code, case_no, item_no=None, require_exact_item=False):
        calls["nav"] += 1
        # 첫 항목은 못 찾는다(=False), 두 번째는 정상 진입한다.
        return calls["nav"] != 1

    def fake_collect(driver, court_code, case_no, item_no, doc_type, btn_id,
                     overwrite=False):
        return {"success": True, "previous_hash": None, "new_hash": "h", "partial": False}

    originals = _patch_all({
        "init_db": lambda: None,
        "reset_stale_queue": lambda: None,
        "release_queue_rows": lambda ids: 0,
        "build_download_driver": lambda: _FakeDriver("initial"),
        "claim_next_item_rows": fake_claim,
        "get_doc_button_id": lambda doc_type, item_no: "qa-fake-btn-id",
        "go_to_case_detail": fake_go,
        "collect_document": fake_collect,
        "restart_download_driver": lambda d: (restarts.append(1), _FakeDriver("r"))[1],
        "mark_queue_failed": lambda qid, rc: failed.append(qid),
        "mark_queue_skipped_expired": lambda *a, **kw: None,
        "mark_queue_unsupported": lambda *a, **kw: None,
        "mark_queue_done": lambda qid, *a, **kw: done.append(qid),
    })
    orig_sleep = doc_worker.time_module.sleep
    doc_worker.time_module.sleep = lambda *_a, **_kw: None
    try:
        exit_code = doc_worker.main()
    finally:
        _restore_all(originals)
        doc_worker.time_module.sleep = orig_sleep

    check("두 항목 다 claim 됐다(검사가 공허하지 않다)", claimed, [100, 101])
    check("★ 사건 미발견으로는 드라이버를 재시작하지 않는다", restarts, [])
    check("못 찾은 항목만 실패로 기록된다", failed, [100])
    check("★ 다음 항목은 그대로 성공 처리된다(과잉 중단 아님)", done, [101])
    check("성공 건이 있으므로 종료 코드는 0", exit_code, 0)


def test_real_exception_still_restarts_the_driver():
    """대조군 - **진짜 예외**는 여전히 드라이버를 재시작한다 (Sprint 232).

    위 검사가 "이제 아무것도 재시작하지 않는다"로 과잉 수정되지 않았는지 본다.
    이것이 없으면 재시작 경로가 통째로 죽어도 통과한다.
    """
    print("\n--- 9. 진짜 예외는 여전히 재시작한다 (대조군) ---")

    queue = _make_fake_queue(2)
    claimed, failed, done, restarts = [], [], [], []
    calls = {"nav": 0}

    def fake_claim():
        if queue:
            it = queue.pop(0)
            claimed.append(it["id"])
            return [it]           # Sprint 236: 물건 단위 claim 은 목록을 돌려준다
        return []

    def fake_go(driver, court_code, case_no, item_no=None, require_exact_item=False):
        calls["nav"] += 1
        if calls["nav"] == 1:
            raise Exception("qa-simulated-browser-crash")   # 진짜 예외
        return True

    def fake_collect(driver, court_code, case_no, item_no, doc_type, btn_id,
                     overwrite=False):
        return {"success": True, "previous_hash": None, "new_hash": "h", "partial": False}

    originals = _patch_all({
        "init_db": lambda: None,
        "reset_stale_queue": lambda: None,
        "release_queue_rows": lambda ids: 0,
        "build_download_driver": lambda: _FakeDriver("initial"),
        "claim_next_item_rows": fake_claim,
        "get_doc_button_id": lambda doc_type, item_no: "qa-fake-btn-id",
        "go_to_case_detail": fake_go,
        "collect_document": fake_collect,
        "restart_download_driver": lambda d: (restarts.append(1), _FakeDriver("r"))[1],
        "mark_queue_failed": lambda qid, rc: failed.append(qid),
        "mark_queue_skipped_expired": lambda *a, **kw: None,
        "mark_queue_unsupported": lambda *a, **kw: None,
        "mark_queue_done": lambda qid, *a, **kw: done.append(qid),
    })
    orig_sleep = doc_worker.time_module.sleep
    doc_worker.time_module.sleep = lambda *_a, **_kw: None
    try:
        doc_worker.main()
    finally:
        _restore_all(originals)
        doc_worker.time_module.sleep = orig_sleep

    check("★ 진짜 예외는 재시작을 부른다", len(restarts), 1)
    check("그 항목은 실패로 기록된다", failed, [100])
    check("다음 항목은 계속 처리된다", done, [101])


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
        raise AssertionError("claim_next_item_rows가 불렸다 - 락이 큐 접근을 막지 못했다")

    originals = _patch_all({
        "init_db": fail_if_called,
        "reset_stale_queue": fail_if_called,
        "build_download_driver": fail_if_called,
        "claim_next_item_rows": fail_if_called,
    })
    try:
        exit_code = doc_worker.main()
    finally:
        _restore_all(originals)
        _clear_real_lock_files()

    check("락 충돌 시 큐/브라우저를 전혀 건드리지 않고 종료 코드 0", exit_code, 0)


def _clear_real_lock_files():
    """운영 `logs/` 에 만든 락 흔적을 지운다 (2026-08-19 Sprint 217).

    이 파일의 락 검사들은 **운영 경로**(`doc_worker.LOCK_PATH` = `logs/doc_worker.lock`)
    를 그대로 쓴다 — 모듈 상수를 갈아 끼우면 검사 대상이 실물이 아니게 되기 때문이다.
    대신 값을 치른다: 검사가 중간에 죽어 락이 남으면 **다음 실제 doc_worker 실행이
    `LOCK_STALE_HOURS`(5시간) 동안 "이미 실행 중"으로 건너뛴다.** 테스트가 운영을
    멈추는 셈이다.

    회수 토큰(`.reclaim`)도 함께 지운다 — 그것이 남으면 **회수 자체가** 같은 시간만큼
    막힌다(변이 시험에서 실제로 그 상태를 만들어 확인했다).
    """
    for path in (doc_worker.LOCK_PATH, doc_worker.LOCK_PATH + ".reclaim"):
        try:
            os.remove(path)
        except OSError:
            pass

def test_stale_lock_is_taken_over():
    """락 파일이 LOCK_STALE_HOURS보다 오래됐으면 죽은 실행으로 보고 회수해야 한다."""
    print("\n--- 4. 오래된 락은 죽은 실행으로 간주하고 회수한다 (Sprint 142) ---")
    os.makedirs("logs", exist_ok=True)
    with open(doc_worker.LOCK_PATH, "w", encoding="utf-8") as f:
        f.write("88888 qa-stale-lock")
    stale_time = time.time() - (doc_worker.LOCK_STALE_HOURS + 1) * 3600
    os.utime(doc_worker.LOCK_PATH, (stale_time, stale_time))

    try:
        acquired = doc_worker._acquire_lock()
        check("오래된 락은 회수해 새로 잡을 수 있다", acquired, True)
        check_true("회수 토큰이 남지 않는다",
                   not os.path.exists(doc_worker.LOCK_PATH + ".reclaim"))
    finally:
        # ★ finally 다. 예전에는 검사가 죽으면 락이 그대로 남아
        #   **다음 실제 배치가 5시간 막혔다.**
        _clear_real_lock_files()


def test_lock_released_after_normal_run():
    """정상 실행이 끝나면(성공이든 실패든) 락 파일이 남지 않아야 한다 — 다음 날 실행이
    "이미 실행 중"으로 영원히 막히면 안 된다."""
    print("\n--- 5. 정상 종료 후에는 락이 해제된다 (Sprint 142) ---")
    if os.path.exists(doc_worker.LOCK_PATH):
        os.remove(doc_worker.LOCK_PATH)

    originals = _patch_all({
        "init_db": lambda: None,
        "reset_stale_queue": lambda: None,
        "release_queue_rows": lambda ids: 0,
        "build_download_driver": lambda: _FakeDriver("initial"),
        "claim_next_item_rows": lambda: [],  # 큐가 비어 즉시 종료
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
        "release_queue_rows": lambda ids: 0,
        "build_download_driver": _boom,
        "claim_next_item_rows": lambda: [],
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
        "claim_next_item_rows": lambda: [],
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


def test_runlock_primitive():
    """공유 잠금(`storage/checkpoint.py:RunLock`) 자체의 계약 (2026-08-18 Sprint 194).

    doc_worker 가 갖고 있던 구현을 그대로 옮긴 것이라 **동작이 바뀌면 안 된다.**
    위 §3~§5 가 doc_worker 경로로 그것을 확인하고, 여기서는 원시 동작을 직접 고정한다.
    """
    import tempfile
    import shutil
    from storage.checkpoint import RunLock

    print("\n--- 9. 공유 잠금 RunLock 계약 (Sprint 194) ---")
    d = tempfile.mkdtemp(prefix="qa_runlock_")
    try:
        path = os.path.join(d, "sub", "x.lock")      # 디렉터리가 없어도 만들어야 한다
        lock = RunLock(path, stale_hours=5, label="qa")

        check("처음에는 잡힌다", lock.acquire(), True)
        check_true("락 파일이 만들어진다", os.path.isfile(path))
        check("이미 잡혀 있으면 실패한다", RunLock(path, 5).acquire(), False)

        lock.release()
        check_true("놓으면 파일이 사라진다", not os.path.exists(path))
        check("없는 락을 놓아도 예외가 없다", lock.release(), None)

        # 오래된 락은 죽은 실행으로 보고 회수한다
        lock.acquire()
        stale = time.time() - (5 + 1) * 3600
        os.utime(path, (stale, stale))
        check("오래된 락은 회수된다", RunLock(path, 5).acquire(), True)

        # 락 파일에는 소유자를 알 수 있는 흔적이 남는다(사고 때 추적용)
        with open(path, encoding="utf-8") as f:
            content = f.read()
        check_true("락 파일에 PID 가 남는다", str(os.getpid()) in content, content)
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_runlock_is_exclusive_under_concurrency():
    """★ 락이 **동시에 시작한 실행**을 실제로 막는가 (2026-08-19 Sprint 217, BUGS #145).

    ## 왜 새로 필요한가

    §9 는 이 락을 **순서대로** 시험한다 — 잡고, 또 잡아 보고, 놓고, 오래된 것을 회수한다.
    그 순서에서는 전부 옳게 동작했다. 그런데 이 락이 막으려는 상황은 순서가 아니다:
    *"운영자가 수동으로 `python doc_worker.py` 를 실행하는 동안 스케줄된 실행이
    겹치는 경우"* (`doc_worker.py` 모듈 주석). 그것은 **같은 순간**이다.

    실측(수정 전, 스레드 8 x 200라운드): **200라운드 전부에서 8개가 동시에 성공.**
    `os.path.exists()` 로 보고 `open(..., "w")` 로 쓰는 사이가 통째로 열려 있었다.
    즉 이 락은 "몇 초 차이"만 막고 "같은 순간"은 하나도 막지 못했다 —
    그리고 그것을 검사하는 것이 하나도 없었다.

    ## 두 경우를 나눠 본다

        평범한 경쟁      락이 없는 상태에서 동시에 들어온다
        회수 경쟁        **오래된 락이 있는 상태**에서 동시에 들어온다

    두 번째가 따로 필요하다. 회수(`지우고 -> 새로 만들기`)는 그 자체가 두 단계라,
    늦게 온 쪽이 **먼저 회수한 쪽의 새 락을 지우고** 자기 것을 만든다. 세 가지를
    차례로 재 봤다.

        os.remove 로 회수                1,000라운드 중 4라운드에서 둘이 성공
        지우기 직전 mtime 재확인 추가     그대로 4/1,000 — 창이 좁아진 게 아니라 종류가 같다
        os.rename 로 회수 권한 중재       8스레드에서 2/40 — 셋 이상이면 되돌리기가 남을 친다

    지금 구현은 **회수 구역 자체를 배타 토큰(`.reclaim`)으로 감싼다.** 토큰을
    `O_EXCL` 로 만든 실행만 회수하고 나머지는 조용히 물러난다.
    실측: 1,000라운드 전부 정확히 하나(로깅을 끈 최악 조건에서도).

    ## 하나도 못 잡는 것도 결함이다

    "둘 다 실패"는 겉보기에 안전해 보이지만 **그날 배치가 통째로 안 도는 것**이다.
    그래서 라운드마다 성공 수가 **정확히 1** 인지 본다.
    """
    import shutil
    import tempfile
    import threading
    from collections import Counter
    from storage.checkpoint import RunLock

    print(chr(10) + "--- 11. 락은 동시 실행을 막는가 (Sprint 217) ---")
    ROUNDS, THREADS, STALE_H = 40, 8, 5

    def race(seed_stale):
        wins = []
        for _ in range(ROUNDS):
            d = tempfile.mkdtemp(prefix="qa_runlock_race_")
            try:
                path = os.path.join(d, "x.lock")
                if seed_stale:
                    with open(path, "w", encoding="utf-8") as f:
                        f.write("9999 dead")
                    old = time.time() - (STALE_H + 1) * 3600
                    os.utime(path, (old, old))

                barrier = threading.Barrier(THREADS)
                won, guard = [], threading.Lock()

                def worker():
                    lock = RunLock(path, stale_hours=STALE_H, label="qa")
                    barrier.wait()          # 최대한 같은 순간에 들어가게 한다
                    if lock.acquire():
                        with guard:
                            won.append(1)

                threads = [threading.Thread(target=worker) for _ in range(THREADS)]
                for t in threads:
                    t.start()
                for t in threads:
                    t.join()
                wins.append(len(won))
            finally:
                shutil.rmtree(d, ignore_errors=True)
        return Counter(wins)

    with contextlib.redirect_stderr(io.StringIO()):   # 회수 경고가 화면을 덮지 않게
        plain = race(False)
        stale = race(True)

    check("평범한 경쟁: 라운드마다 정확히 하나만 잡는다",
          dict(plain), {1: ROUNDS})
    check("회수 경쟁: 라운드마다 정확히 하나만 잡는다",
          dict(stale), {1: ROUNDS})

    # ★ 회수 토큰이 **남지 않는가.** 남으면 다음 회수가 "진행 중"으로 오해해
    #   `stale_hours` 동안 물러난다 — 고치려던 것과 같은 종류의 정지를 만든다.
    leftovers = []
    for _ in range(10):
        d = tempfile.mkdtemp(prefix="qa_runlock_token_")
        try:
            path = os.path.join(d, "x.lock")
            with open(path, "w", encoding="utf-8") as f:
                f.write("9999 dead")
            old = time.time() - (STALE_H + 1) * 3600
            os.utime(path, (old, old))
            barrier = threading.Barrier(THREADS)

            def worker():
                lock = RunLock(path, stale_hours=STALE_H, label="qa")
                barrier.wait()
                lock.acquire()

            threads = [threading.Thread(target=worker) for _ in range(THREADS)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            names = sorted(os.listdir(d))
            if names != ["x.lock"]:
                leftovers.append(names)
        finally:
            shutil.rmtree(d, ignore_errors=True)
    check("회수 토큰/임시 파일이 남지 않는다", leftovers, [])
    print("    스레드 %d x %d라운드 x 2경우 + 잔재 확인 10라운드" % (THREADS, ROUNDS))


def test_both_batches_share_the_same_lock_rule():
    """★ 구조적 가드: **락이 필요한 배치가 전부 같은 구현을 쓴다.**

    2026-08-18 Sprint 194. `doc_worker.py` 는 2026-08-16 부터 락을 갖고 있었는데
    `mvp_scraper.py` 에는 **없었다.** 이 배치도 공유 자원을 건드린다:

        logs/checkpoint.json   전체를 읽어 고쳐 쓴다 -> 겹치면 진행 상황이 서로 덮인다
        법원 서버              전체 크롤 약 3.1시간(Sprint 190 실측) -> 겹칠 창이 넓다

    구현을 베끼지 않고 `storage/checkpoint.py` 로 올렸다(2026-08-19 Sprint 217 정정 —
    옛 주석은 `storage/runlock.py` 라고 적었지만 그런 파일은 없다. 가드에 걸려 이미
    추적된 모듈로 옮긴 것이다). 이 검사는 **두 배치가 정말로
    그것을 쓰는지**, 그리고 락 경로가 서로 다른지(같으면 서로를 막는다) 확인한다.
    """
    print("\n--- 10. 두 배치가 같은 잠금 구현을 쓴다 (Sprint 194) ---")
    import inspect
    import mvp_scraper
    from storage.checkpoint import RunLock

    for name, mod in (("doc_worker", doc_worker), ("mvp_scraper", mvp_scraper)):
        check_true("%s 가 LOCK_PATH 를 갖는다" % name, hasattr(mod, "LOCK_PATH"),
                   dir(mod))
        check_true("%s 가 공유 RunLock 을 쓴다" % name,
                   mod._lock().__class__ is RunLock, mod._lock().__class__)
        check_true("%s 의 락은 호출 시점에 만들어진다(스냅숏 아님)" % name,
                   mod._lock() is not mod._lock(),
                   "모듈 로드 때 굳히면 경로를 바꿔도 안 따라온다")

    check_true("두 배치의 락 경로가 다르다",
               doc_worker.LOCK_PATH != mvp_scraper.LOCK_PATH,
               (doc_worker.LOCK_PATH, mvp_scraper.LOCK_PATH))

    # 락을 못 잡았을 때 **실패가 아니다** — 다른 실행이 이미 그 일을 하고 있다.
    src = inspect.getsource(mvp_scraper.main)
    check_true("mvp_scraper 는 락을 브라우저보다 먼저 확인한다",
               src.index("lock.acquire()") < src.index("run_courts("), src[:200])
    check_true("락을 못 잡으면 0으로 끝낸다(실패 아님)",
               "return 0" in src[:src.index("try:")], src[:400])
    check_true("finally 에서 반드시 놓는다", "lock.release()" in src, src[-300:])


def test_mvp_scraper_lock_flow():
    """매일 크롤이 **실제로** 락을 잡고/양보하고/놓는가 (2026-08-18 Sprint 194).

    §10 은 소스 수준 계약을 본다. 여기서는 `main()` 을 진짜로 돌린다 —
    라이브 크롤은 하지 않고(`run_courts` 를 대역으로), DB 도 건드리지 않는다.

    세 경우를 고정한다. 두 번째가 특히 중요하다:

        정상 실행     잡고 -> 돌고 -> **놓는다**
        락 충돌       아무것도 하지 않고 0 으로 끝낸다.
                      ★ 그리고 **남의 락을 지우지 않는다** — 이걸 틀리면 잠금이
                        무의미해지는 정도가 아니라, 먼저 돌던 실행이 무방비가 된다.
        예외          예외는 그대로 올라가되 **락은 반드시 놓인다**(finally)
    """
    import tempfile
    import shutil
    import mvp_scraper as m

    print("\n--- 11. 매일 크롤의 락 흐름 (Sprint 194) ---")
    tmp = tempfile.mkdtemp(prefix="qa_mvp_lock_")
    saved = (m.LOCK_PATH, m.init_db, m.run_courts, m.enqueue_documents)
    try:
        m.LOCK_PATH = os.path.join(tmp, "mvp.lock")
        calls = []
        m.init_db = lambda: calls.append("init_db")
        m.run_courts = lambda courts, outcome=None: (calls.append("run_courts"), [])[1]
        m.enqueue_documents = lambda rows: calls.append("enqueue")

        # (1) 정상 실행
        m.main()
        check("정상 실행은 실제로 수집을 시도한다", calls, ["init_db", "run_courts"])
        check_true("정상 종료 후 락이 남지 않는다", not os.path.exists(m.LOCK_PATH))

        # (2) 다른 실행이 락을 쥐고 있다
        with open(m.LOCK_PATH, "w", encoding="utf-8") as f:
            f.write("other-process")
        calls.clear()
        rc = m.main()
        check("락 충돌이면 아무것도 하지 않는다", calls, [])
        check("락 충돌은 실패가 아니다(종료 코드 0)", rc, 0)
        check_true("★ 남의 락을 지우지 않는다", os.path.exists(m.LOCK_PATH))
        with open(m.LOCK_PATH, encoding="utf-8") as f:
            check("남의 락 내용도 그대로", f.read(), "other-process")
        os.remove(m.LOCK_PATH)

        # (3) 도중에 예외가 나도 락은 놓는다
        def boom(*a, **kw):
            raise RuntimeError("qa-simulated-crawl-crash")

        m.run_courts = boom
        raised = False
        try:
            m.main()
        except RuntimeError:
            raised = True
        check("예외는 호출자에게 그대로 전달된다", raised, True)
        check_true("예외가 나도 락은 놓인다", not os.path.exists(m.LOCK_PATH))
    finally:
        m.LOCK_PATH, m.init_db, m.run_courts, m.enqueue_documents = saved
        shutil.rmtree(tmp, ignore_errors=True)




def test_lock_is_not_defeated_by_a_different_cwd():
    """다른 작업 디렉터리에서 띄운 두 번째 인스턴스도 **락에 막히는가** (2026-08-21 Sprint 246).

    ## 이 검사가 없던 동안 무엇이 조용히 깨져 있었나

    `LOCK_PATH` 는 예전에 `os.path.join("logs", "doc_worker.lock")` 이었다. 상대경로라
    **cwd 기준**으로 풀린다. 그래서 두 인스턴스의 작업 디렉터리가 다르면 서로 **다른
    락 파일**을 보고, 둘 다 획득에 성공한다. 즉 중복 실행 방지가 무력화된다.

    실측(2026-08-21, 고치기 전):

        A(저장소 루트)에서 획득 -> True
        B(같은 cwd)에서 획득    -> False   <- 정상적으로 막힘
        C(다른 cwd)에서 획득    -> **True** <- 막히지 않는다

    위 `test_lock_prevents_concurrent_run` 은 이걸 못 잡는다 - **같은 프로세스, 같은
    cwd** 에서만 확인하기 때문이다. cwd 가 갈리는 순간이 바로 구멍이었다.

    ## 왜 심각한가

    `DOWNLOAD_DIR` 은 모든 실행이 공유한다(Sprint 142 참고). 두 워커가 동시에 돌면
    한쪽이 받은 파일을 다른 쪽이 자기 것으로 착각하고, `document_queue` 도 이중으로
    claim 된다. 그리고 이건 **로그에 아무 흔적도 남지 않는다** - 둘 다 "락 획득 성공"
    이라고 정상 동작처럼 기록한다.

    `.bat` 3개는 `cd /d %~dp0` 로 스스로를 보호하지만, 문서가 안내하는 수동 실행과
    서비스 등록(NSSM/작업 스케줄러의 '시작 위치')은 그렇지 않다.

    ## 검사 방법

    **별도 프로세스 2개를 서로 다른 cwd 에서 띄운다.** 같은 프로세스 안에서는 이미
    임포트된 `doc_worker.LOCK_PATH` 가 그대로라 재현되지 않는다 - 검사가 공허해진다.
    크롤은 하지 않는다. `RunLock` 만 직접 잡는다.
    """
    print("\n--- 다른 cwd 의 두 번째 인스턴스도 락에 막히는가 (Sprint 246) ---")
    import subprocess
    import tempfile
    import shutil

    repo = os.path.dirname(os.path.abspath(__file__))
    probe = (
        "import os, sys, time;"
        "sys.path.insert(0, os.environ['REPO']);"
        "import doc_worker as w;"
        "from storage.checkpoint import RunLock;"
        "lk = RunLock(w.LOCK_PATH, w.LOCK_STALE_HOURS, label='qa-cwd-probe');"
        "got = bool(lk.acquire());"
        "print('ACQUIRED=%d ABS=%s' % (got, os.path.abspath(w.LOCK_PATH)));"
        "sys.stdout.flush();"
        "time.sleep(float(os.environ.get('HOLD','0')));"
        "lk.release() if got else None"
    )

    def spawn(cwd, hold):
        env = dict(os.environ)
        env["REPO"] = repo
        env["HOLD"] = str(hold)
        env["PYTHONIOENCODING"] = "utf-8"
        return subprocess.Popen([sys.executable, "-c", probe], cwd=cwd, env=env,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def read(proc):
        line = proc.stdout.readline().decode("utf-8", "replace").strip()
        m = re.search(r"ACQUIRED=(\d) ABS=(.+)", line)
        if not m:
            return None, (line + proc.stderr.read().decode("utf-8", "replace"))[:200]
        return m.group(1) == "1", m.group(2)

    _clear_real_lock_files()
    other = tempfile.mkdtemp(prefix="qa_lockcwd_")
    holder = None
    try:
        holder = spawn(repo, 8)                       # A: 저장소 루트에서 잡고 유지
        got_a, abs_a = read(holder)
        check_true("저장소 루트에서 락을 잡는다(검사가 공허하지 않다)",
                   got_a is True, "-> %r" % (abs_a,))
        if got_a is not True:
            return

        b = spawn(repo, 0)                            # B: 같은 cwd -> 막혀야 정상
        got_b, abs_b = read(b)
        b.wait(timeout=120)
        check_true("같은 cwd 의 두 번째 인스턴스는 막힌다(기존 계약)",
                   got_b is False, "-> %r" % (abs_b,))

        c = spawn(other, 0)                           # C: 다른 cwd -> 여기가 구멍이었다
        got_c, abs_c = read(c)
        c.wait(timeout=120)
        check_true("★ **다른 cwd** 의 두 번째 인스턴스도 막힌다",
                   got_c is False,
                   "-> 획득됐다. LOCK_PATH 가 상대경로라 cwd 마다 다른 락 파일을 본다. "
                   "doc_worker 두 개가 같은 큐/다운로드 폴더를 동시에 만진다")
        check("★ 다른 cwd 에서도 **같은 락 파일**을 가리킨다", abs_c, abs_a)
        check_true("★ 다른 폴더에 logs/ 를 새로 만들지 않는다",
                   not os.path.exists(os.path.join(other, "logs")),
                   "-> 로그와 락이 그 폴더로 흩어진다")
    finally:
        if holder is not None:
            try:
                holder.wait(timeout=60)
            except Exception:
                holder.kill()
        shutil.rmtree(other, ignore_errors=True)
        _clear_real_lock_files()

    # 소스 수준 가드 - 편집 시점에 되돌리는 것을 잡는다(주석 제외)
    for rel, names in (("doc_worker.py", ("LOCK_PATH",)),
                       ("mvp_scraper.py", ("LOCK_PATH",))):
        src = io.open(os.path.join(repo, rel), encoding="utf-8-sig").read()
        code = "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("#"))
        for nm in names:
            m = re.search(r"^%s\s*=\s*(.+)$" % nm, code, re.M)
            check_true("★ %s 의 %s 가 파일 기준 절대경로다" % (rel, nm),
                       m is not None and "_HERE" in m.group(1),
                       "-> %r. cwd 기준 상대경로면 중복 실행 방지가 무력화된다"
                       % (m.group(1) if m else None,))

def run():
    test_driver_restart_failure_stops_run_instead_of_burning_retry_budget()
    test_driver_restart_success_continues_processing()
    test_case_not_reachable_does_not_restart_the_driver()
    test_real_exception_still_restarts_the_driver()
    test_lock_prevents_concurrent_run()
    test_lock_is_not_defeated_by_a_different_cwd()
    test_stale_lock_is_taken_over()
    test_lock_released_after_normal_run()
    test_driver_startup_failure_releases_lock()
    test_out_of_window_run_does_not_start_browser()
    test_driver_setup_failure_does_not_orphan_browser()
    test_runlock_primitive()
    test_runlock_is_exclusive_under_concurrency()
    test_both_batches_share_the_same_lock_rule()
    test_mvp_scraper_lock_flow()

    print("\n" + "=" * 55)
    if failures:
        print("FAILED (%d): %s" % (len(failures), ", ".join(failures)))
        return 1
    print("ALL TESTS PASSED")
    return 0


def _final_safety_net():
    """어느 검사가 죽더라도 운영 락 흔적을 남기지 않는다(마지막 그물)."""
    _clear_real_lock_files()


if __name__ == "__main__":
    try:
        code = run()
    finally:
        # ★ 어느 검사가 죽더라도 운영 `logs/` 에 락 흔적을 남기지 않는다.
        #   남기면 다음 실제 배치가 5시간 막힌다 — 테스트가 운영을 멈추는 셈이다.
        _final_safety_net()
    sys.exit(code)
