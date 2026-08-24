# -*- coding: utf-8 -*-
"""`crawler/court_crawler.py` 의 오케스트레이션·복구 회귀 ― 2026-08-24 Sprint 254 신설.

## 왜 이 파일이 생겼나

전체 스위트 합산 커버리지에서 이 모듈이 **26%** 였다(93문 중 69 미실행). 미실행
구간이 정확히 `crawl_detail()` + `crawl_court()` 둘이다 ― 즉 **매일 06:00 크롤의
본체 판단이 통째로 미검증**이었다. `test_crawl_error_log.py` 는 `log_error()` 만,
`test_crawl_orchestration.py` 는 그 **위층**(`crawl_court` 를 가짜로 갈아 끼운
`run_courts()`)만 본다. 가운데가 비어 있었다.

그 빈칸에서 결함이 하나 나왔다 (BUGS #182):

    crawl_court() 에는 드라이버 재시작 복구가 있다.
    그런데 crawl_detail() 이 **모든 예외를 잡아** 재시도했기 때문에,
    브라우저가 죽어도 그것이 "이 사건을 못 읽었다"로 처리됐다.
    -> 복구가 한 번도 실행되지 않는다 (실측: 항목 4 x 재시도 3 = 12회 헛돌고 restart 0회)
    -> 그 법원은 빈 목록을 돌려주고, run_courts() 는 그것을 **"기일 없어 스킵"**
       으로 요약한다. 브라우저가 죽은 것을 "그 법원은 경매가 없었다"고 말한다.

## Selenium 없이 어떻게 도나

`crawl_court()` 가 부르는 것은 `base_crawler` 의 함수 몇 개뿐이다. 그 이름들을
모듈 속성으로 갈아 끼운다(네트워크·브라우저 없음). 브라우저의 죽음은 **실제
selenium 예외 클래스**로 흉내 낸다 ― 판정이 그 클래스를 보기 때문이다.

    python test_court_crawl_recovery.py
"""
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

FAILS = []
CHECKS = [0]


def check(label, got, expected):
    CHECKS[0] += 1
    if got == expected:
        print("[PASS] %s: %r (expected %r)" % (label, got, expected))
    else:
        print("[FAIL] %s: %r (expected %r)" % (label, got, expected))
        FAILS.append(label)


def check_true(label, cond, detail=""):
    CHECKS[0] += 1
    if cond:
        print("[PASS] %s" % label)
    else:
        print("[FAIL] %s -- %s" % (label, detail))
        FAILS.append(label)


# ---------------------------------------------------------------------------
# fixture ― 브라우저만 가짜다. 판단은 전부 제품 코드가 한다.
# ---------------------------------------------------------------------------
class _Driver(object):
    def __init__(self, tag, alive=True, quit_raises=False):
        self.tag = tag
        self.alive = alive
        self.quit_raises = quit_raises
        self.quit_called = 0

    def execute_script(self, *a, **kw):
        return None

    def quit(self):
        self.quit_called += 1
        if self.quit_raises:
            raise RuntimeError("qa-quit-failure")


def _items(n):
    return [{"case_no": "2024타경%d" % (1000 + i), "dtl_idx": i, "addr": "서울시 중구",
             "date": "2026-09-01", "status": "신건", "obj_no": "1", "appraisal": "1"}
            for i in range(n)]


class _Harness(object):
    """`crawler.court_crawler` 의 협력자들을 갈아 끼운다. 원상복구를 보장한다."""

    NAMES = ("build_driver", "restart_driver", "go_to_list", "go_to_schedule",
             "collect_list_items", "wait_for_detail", "parse_basic_info",
             "parse_section_table", "parse_gamjung", "CheckpointManager",
             "ERROR_LOG_PATH", "time")

    def __init__(self, **overrides):
        import crawler.court_crawler as cc
        import storage.checkpoint as cpmod
        self.cc = cc
        self.tmp = tempfile.mkdtemp(prefix="qa_court_crawl_")
        self.calls = {"build": 0, "restart": 0, "detail": 0, "quit": 0}
        self.drivers = []

        cp_path = os.path.join(self.tmp, "cp.json")
        real_cm = cpmod.CheckpointManager

        base = {
            "go_to_schedule": lambda d, c: (True, True),
            "collect_list_items": lambda d, n: _items(3),
            "wait_for_detail": lambda d, case_no: True,
            "parse_basic_info": lambda d: {"물건번호": "1", "물건종류": "아파트"},
            "parse_section_table": lambda d, name: [],
            "parse_gamjung": lambda d: {},
            "CheckpointManager": lambda *a, **kw: real_cm(cp_path),
            "ERROR_LOG_PATH": os.path.join(self.tmp, "errors.jsonl"),
            # 재시도 대기를 없앤다 ― 이 검사는 시간이 아니라 **판단**을 본다.
            "time": type("_T", (), {"sleep": staticmethod(lambda s: None)})(),
        }
        base.update(overrides)
        self.plan = base
        self.cp_path = cp_path

    def __enter__(self):
        self._orig = {}
        for name in self.NAMES:
            self._orig[name] = getattr(self.cc, name, None)
        for name, value in self.plan.items():
            setattr(self.cc, name, value)
        return self

    def __exit__(self, *a):
        for name, value in self._orig.items():
            if value is not None:
                setattr(self.cc, name, value)
        shutil.rmtree(self.tmp, ignore_errors=True)
        return False


def _court():
    from config.settings import CourtInfo
    return CourtInfo(code="B000210", name="QA법원", region="서울")


def _dead(kind="InvalidSessionIdException", msg="invalid session id"):
    from selenium.common import exceptions as sel_exc
    klass = getattr(sel_exc, kind)
    return klass(msg)


# ---------------------------------------------------------------------------
# 1. 세션 사망 판정 ― 무엇을 '브라우저가 죽었다'로 볼 것인가
# ---------------------------------------------------------------------------
def test_session_dead_classification():
    """판정이 **너무 넓으면** 멀쩡한 브라우저를 매번 재시작한다.

    `NoSuchElementException` / `TimeoutException` 은 `WebDriverException` 의
    자식이다. 부모를 통째로 잡으면 "이 화면에 그 요소가 없다"까지 세션 사망이 된다.
    그래서 넓은 쪽과 좁은 쪽을 **둘 다** 검사한다.
    """
    print("\n--- 1. 세션 사망 판정 (Sprint 254) ---")
    import crawler.court_crawler as cc
    from selenium.common import exceptions as E

    dead = [
        E.InvalidSessionIdException("invalid session id"),
        E.NoSuchWindowException("no such window"),
        E.SessionNotCreatedException("session not created"),
        # 클래스는 세션 사망인데 **문구에 아는 표지가 없는** 경우.
        # 판정이 문구 대조만 하고 있으면 여기서 걸린다 - 드라이버 버전이나 로케일에
        # 따라 메시지는 얼마든지 달라지므로 클래스 대조가 따로 필요하다.
        E.InvalidSessionIdException("qa-unrecognized-driver-text"),
        # 반대쪽: 클래스는 밋밋한 WebDriverException 인데 **문구가 세션 사망**인 경우.
        # 클래스 대조만 하고 있으면 여기서 걸린다. 실제 드라이버가 이렇게 던진다.
        E.WebDriverException("chrome not reachable"),
        E.WebDriverException("disconnected: not connected to DevTools"),
    ]
    alive = [
        E.NoSuchElementException("Unable to locate element: .foo"),
        E.TimeoutException("timeout"),
        E.StaleElementReferenceException("stale element"),
        Exception("go_to_list failed"),
        Exception("wait_for_detail timeout"),
    ]
    check("★ 세션이 죽은 예외를 전부 잡는다",
          [type(e).__name__ for e in dead if not cc.is_session_dead(e)], [])
    check("★ 평범한 항목 실패를 세션 사망으로 오판하지 않는다",
          [type(e).__name__ for e in alive if cc.is_session_dead(e)], [])
    check_true("검사가 공허하지 않다(양쪽 다 표본이 있다)",
               len(dead) >= 5 and len(alive) >= 5, (len(dead), len(alive)))


# ---------------------------------------------------------------------------
# 2. 죽은 브라우저 ― 복구가 실제로 돈다
# ---------------------------------------------------------------------------
def test_dead_browser_triggers_restart_and_recovers():
    print("\n--- 2. 브라우저가 죽으면 재시작하고, 되살아나면 계속한다 (Sprint 254) ---")
    import crawler.court_crawler as cc

    state = {"alive": False, "restart": 0, "detail": 0}

    def build_driver():
        return _Driver("first", alive=False)

    def restart_driver(old):
        state["restart"] += 1
        state["alive"] = True          # 재시작하면 살아난다
        return _Driver("restarted", alive=True)

    def go_to_list(driver, court):
        state["detail"] += 1
        if not state["alive"]:
            raise _dead()
        return True

    with _Harness(build_driver=build_driver, restart_driver=restart_driver,
                  go_to_list=go_to_list):
        items = cc.crawl_court(_court())

    print("    재시작 %d회 / go_to_list %d회 / 수집 %d건"
          % (state["restart"], state["detail"], len(items)))
    check("★ 드라이버 재시작 복구가 실제로 돈다", state["restart"], 1)
    check("★ 재시작 뒤 남은 물건을 전부 수집한다", len(items), 3)
    check_true("★ 죽은 세션으로 재시도를 낭비하지 않는다(첫 항목은 1회 시도)",
               state["detail"] == 1 + 3, "-> go_to_list %d회" % state["detail"])


def test_permanently_dead_browser_is_reported_as_failure_not_skip():
    """★ 이 검사가 BUGS #182 의 본체다.

    복구해도 브라우저가 계속 죽어 있으면 예외가 위로 올라가야 한다.
    삼키고 빈 목록을 돌려주면 `run_courts()` 가 그것을 **"기일 없어 스킵"**으로
    요약한다 ― 브라우저가 죽은 것을 "그 법원은 경매가 없었다"고 말하는 셈이다
    (BUGS #47 계열: 배치 요약이 사실이 아닌 것을 말한다).
    """
    print("\n--- 3. 끝까지 죽어 있으면 '스킵'이 아니라 '실패'다 (Sprint 254, BUGS #182) ---")
    import crawler.court_crawler as cc

    state = {"restart": 0}

    def restart_driver(old):
        state["restart"] += 1
        return _Driver("still-dead", alive=False)

    def go_to_list(driver, court):
        raise _dead("NoSuchWindowException", "no such window")

    raised = None
    with _Harness(build_driver=lambda: _Driver("dead", alive=False),
                  restart_driver=restart_driver, go_to_list=go_to_list):
        try:
            cc.crawl_court(_court())
        except Exception as e:      # noqa: BLE001 - 예외가 올라오는 것이 검사 대상이다
            raised = e

    check_true("★ 빈 목록으로 삼키지 않고 예외를 올린다('스킵'과 구별된다)",
               raised is not None,
               "-> None. run_courts 는 이것을 '기일 없어 스킵'으로 센다")
    check("★ 올라온 예외가 '브라우저가 죽었다'임을 밝힌다",
          type(raised).__name__, "BrowserSessionLost")
    check("한 번은 재시작을 시도한다(포기 전에 복구를 시도했다)", state["restart"], 1)


def test_ordinary_item_failure_does_not_restart_the_browser():
    """평범한 실패는 **재시작 없이** 재시도한다 ― 그리고 나머지 물건은 살아남는다."""
    print("\n--- 4. 항목 실패는 브라우저를 재시작하지 않는다 (Sprint 254) ---")
    import crawler.court_crawler as cc
    from config.settings import MAX_RETRY

    state = {"restart": 0, "attempts": 0}
    bad_case = _items(3)[1]["case_no"]

    def go_to_list(driver, court):
        state["attempts"] += 1
        return True

    def wait_for_detail(driver, case_no):
        if case_no == bad_case:
            return False        # 이 사건만 상세가 안 뜬다
        return True

    with _Harness(build_driver=lambda: _Driver("ok"),
                  restart_driver=lambda d: (state.__setitem__("restart",
                                                              state["restart"] + 1)
                                            or _Driver("restarted")),
                  go_to_list=go_to_list, wait_for_detail=wait_for_detail):
        items = cc.crawl_court(_court())

    print("    수집 %d건 / 재시작 %d회 / go_to_list %d회"
          % (len(items), state["restart"], state["attempts"]))
    check("★ 항목 실패로 브라우저를 재시작하지 않는다", state["restart"], 0)
    check("★ 실패한 하나만 빠지고 나머지는 수집된다", len(items), 2)
    check("★ 실패한 항목은 MAX_RETRY 만큼 재시도한다",
          state["attempts"], 2 + MAX_RETRY)
    check("★ 빠진 것이 그 사건이 맞다",
          sorted(i.case_no for i in items),
          sorted(x["case_no"] for x in _items(3) if x["case_no"] != bad_case))

    # `go_to_list` 는 **예외 대신 False** 를 돌려줄 수도 있다(base_crawler 의 계약).
    # 그 경우도 "이 항목의 실패" 로 다뤄야 한다 - 세션 사망으로 오판해 브라우저를
    # 재시작하면 멀쩡한 실행을 매번 죽였다 살린다.
    state2 = {"restart": 0, "attempts": 0}

    def go_to_list_false(driver, court):
        state2["attempts"] += 1
        return False

    with _Harness(build_driver=lambda: _Driver("ok"),
                  restart_driver=lambda d: (state2.__setitem__("restart",
                                                               state2["restart"] + 1)
                                            or _Driver("restarted")),
                  go_to_list=go_to_list_false):
        items2 = cc.crawl_court(_court())

    check("★ go_to_list 가 False 를 줘도 세션 사망으로 오판하지 않는다",
          state2["restart"], 0)
    check("전부 실패하지만 예외 없이 빈 목록으로 끝난다", items2, [])
    check("항목마다 MAX_RETRY 만큼 시도한다", state2["attempts"], 3 * MAX_RETRY)


# ---------------------------------------------------------------------------
# 5. 그 밖의 조기 반환 경로
# ---------------------------------------------------------------------------
def test_early_returns():
    print("\n--- 5. 조기 반환 경로 (Sprint 254) ---")
    import crawler.court_crawler as cc

    quit_counts = []

    def make_driver():
        d = _Driver("ok")
        quit_counts.append(d)
        return d

    with _Harness(build_driver=make_driver,
                  go_to_schedule=lambda d, c: (False, False)):
        check("접속 실패면 빈 목록", cc.crawl_court(_court()), [])
    with _Harness(build_driver=make_driver,
                  go_to_schedule=lambda d, c: (True, False)):
        check("기일이 없으면 빈 목록", cc.crawl_court(_court()), [])
    with _Harness(build_driver=make_driver,
                  collect_list_items=lambda d, n: []):
        check("목록이 비면 빈 목록", cc.crawl_court(_court()), [])

    check("★ 어느 경로로 나가든 브라우저를 닫는다",
          [d.quit_called for d in quit_counts], [1, 1, 1])

    # dtl_idx 가 없는 항목은 상세로 들어가지 않는다.
    rows = _items(3)
    rows[1]["dtl_idx"] = None
    seen = []
    with _Harness(build_driver=lambda: _Driver("ok"),
                  collect_list_items=lambda d, n: rows,
                  go_to_list=lambda d, c: True,
                  wait_for_detail=lambda d, case_no: seen.append(case_no) or True):
        items = cc.crawl_court(_court())
    check("★ dtl_idx 가 없는 항목은 건너뛴다(상세로 들어가지 않는다)",
          rows[1]["case_no"] in seen, False)
    check("나머지는 수집된다", len(items), 2)


def test_quit_failure_does_not_mask_the_real_cause():
    """`quit()` 이 던지면 **원래 오류가 그것으로 바뀐다** ― 죽은 세션에서 실제로 일어난다.

    그러면 `run_courts()` 의 로그가 엉뚱한 원인(`qa-quit-failure`)을 가리키고,
    운영자는 브라우저가 죽었다는 사실을 영영 못 본다.
    """
    print("\n--- 6. 종료 실패가 원인을 덮지 않는다 (Sprint 254) ---")
    import crawler.court_crawler as cc

    def go_to_list(driver, court):
        raise _dead()

    raised = None
    with _Harness(build_driver=lambda: _Driver("dead", alive=False, quit_raises=True),
                  restart_driver=lambda d: _Driver("still-dead", alive=False,
                                                   quit_raises=True),
                  go_to_list=go_to_list):
        try:
            cc.crawl_court(_court())
        except Exception as e:      # noqa: BLE001
            raised = e

    check("★ 올라오는 것은 원래 원인이다(종료 실패가 아니다)",
          type(raised).__name__, "BrowserSessionLost")
    check_true("★ 종료 실패 메시지가 원인을 대신하지 않는다",
               "qa-quit-failure" not in str(raised), str(raised))


# ---------------------------------------------------------------------------
# 7. 체크포인트 재시작
# ---------------------------------------------------------------------------
def test_checkpoint_resume_and_clear():
    print("\n--- 7. 체크포인트 재시작 (Sprint 254) ---")
    import crawler.court_crawler as cc
    import storage.checkpoint as cpmod

    rows = _items(4)
    seen = []

    tmp = tempfile.mkdtemp(prefix="qa_court_cp_")
    cp_path = os.path.join(tmp, "cp.json")
    try:
        cm = cpmod.CheckpointManager(cp_path)
        cm.save(_court().code, rows[1]["case_no"], 2, len(rows))

        with _Harness(build_driver=lambda: _Driver("ok"),
                      collect_list_items=lambda d, n: rows,
                      go_to_list=lambda d, c: True,
                      CheckpointManager=lambda *a, **kw: cpmod.CheckpointManager(cp_path),
                      wait_for_detail=lambda d, case_no: seen.append(case_no) or True):
            items = cc.crawl_court(_court())

        print("    상세로 들어간 사건: %s" % seen)
        check("★ 체크포인트 다음 항목부터 시작한다", seen,
              [rows[2]["case_no"], rows[3]["case_no"]])
        check("이미 끝낸 항목은 다시 긁지 않는다", len(items), 2)
        check("★ 끝까지 돌면 체크포인트를 지운다(다음 실행이 처음부터 돈다)",
              cpmod.CheckpointManager(cp_path).get(_court().code), None)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# 8. 배선 ― run_courts 가 이 구별을 실제로 쓰는가
# ---------------------------------------------------------------------------
def test_run_courts_counts_a_dead_browser_as_failure():
    """제품의 요약이 **사실**이 되는가. 이것이 이 결함의 사용자 쪽 얼굴이다."""
    print("\n--- 8. run_courts 요약: 죽은 브라우저는 '스킵'이 아니다 (Sprint 254) ---")
    import mvp_scraper as ms
    from models.crawl_outcome import CrawlOutcome

    court = _court()
    real = ms.crawl_court
    outcome = CrawlOutcome()
    try:
        def boom(c):
            import crawler.court_crawler as cc
            raise cc.BrowserSessionLost("invalid session id")

        ms.crawl_court = boom
        ms.run_courts([court], outcome)
    finally:
        ms.crawl_court = real

    check("★ 실패로 센다", outcome.failed, [court.name])
    check("★ '기일 없어 스킵'으로 세지 않는다(사실이 아닌 요약을 만들지 않는다)",
          outcome.skipped, [])
    check("수집 0건", outcome.collected, 0)
    check_true("★ 이 실행은 성공이 아니다(종료 코드가 0이면 안 된다)",
               outcome.exit_code() != 0, outcome.exit_code())


def main():
    print("=" * 63)
    print(" court_crawler 오케스트레이션·복구 회귀 (Sprint 254)")
    print("=" * 63)
    test_session_dead_classification()
    test_dead_browser_triggers_restart_and_recovers()
    test_permanently_dead_browser_is_reported_as_failure_not_skip()
    test_ordinary_item_failure_does_not_restart_the_browser()
    test_early_returns()
    test_quit_failure_does_not_mask_the_real_cause()
    test_checkpoint_resume_and_clear()
    test_run_courts_counts_a_dead_browser_as_failure()

    print("\n" + "=" * 63)
    if FAILS:
        print("FAILED (%d/%d): %s" % (len(FAILS), CHECKS[0], ", ".join(FAILS)))
        return 1
    print("ALL COURT CRAWL RECOVERY TESTS PASSED (%d checks)" % CHECKS[0])
    return 0


if __name__ == "__main__":
    sys.exit(main())
