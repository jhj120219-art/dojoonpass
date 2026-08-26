# -*- coding: utf-8 -*-
"""물건 단위 batching 이 **실제로** 이동을 줄이는지, 그러면서 큐 의미를 깨지 않는지.

2026-08-20 Sprint 236 (BUGS #173).

이 검사가 존재하는 이유
-----------------------
batching 의 이득은 "이동 횟수가 준다"는 **구조적** 사실이다. 그 사실은 시간을 재지
않고도 셀 수 있고, 세는 편이 훨씬 정확하다(시간은 그날 법원 서버 상태에 좌우된다).

그래서 여기서는 **진짜 `doc_worker.main()` 을 돌린다.** 가짜 워커를 만들어
"이동이 줄었다"고 세면 아무것도 증명하지 못한다 - 세고 있는 것이 제품 코드가
아니기 때문이다. 브라우저와 수집기만 가짜로 두고, claim / 순서 / 페이지 재사용 /
종결 처리는 전부 제품 코드를 그대로 태운다.

그리고 **전/후를 같은 방식으로 잰다.** 예전 구조(행 하나씩 claim)를 흉내 내는
경로를 함께 돌려서 같은 fixture 에서 이동 횟수를 비교한다. 한쪽만 재고
"몇 배 좋아졌다"고 말하지 않는다.

깨지면 안 되는 것 (batching 이 흔히 깨뜨리는 것들)
--------------------------------------------------
    행마다 종결       한 종류가 실패해도 나머지는 각자 성공/실패로 끝난다
    행마다 재시도     retry_count 는 행의 것이다 - 물건 단위로 뭉치지 않는다
    행마다 refresh    재수집 의도(overwrite)가 행별로 유지된다
    사진 정확일치     느슨하게 들어간 페이지를 사진이 재사용하지 않는다
    남는 행 없음      집었으면 끝내거나 되돌린다 - in_progress 로 방치하지 않는다
"""
import io
import os
import shutil
import sys
import tempfile
from datetime import datetime, timedelta

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
# fixture
# ---------------------------------------------------------------------------
class _FakeDriver(object):
    """브라우저만 가짜다. 워커의 판단은 전부 제품 코드가 한다."""

    def __init__(self, tag="d"):
        self.tag = tag

    def quit(self):
        pass


def _fresh_db(tmp):
    """실제 부트스트랩 3단계로 스키마를 만든다 - 손으로 베끼지 않는다.

    ★ `init_db()` 만으로는 부족하다. 그 함수는 legacy 테이블(auction /
      document_queue / document_version_log)만 만들고, `mark_queue_done()` 이 쓰는
      `document_status` 는 v4.1 쪽이다. 반쪽 스키마로 돌리면 종결이 매번 예외로
      떨어지고, 워커는 그것을 "수집 실패"로 처리한 뒤 드라이버를 재시작한다 -
      그러면 페이지 기억이 지워져 **이동이 줄지 않은 것처럼 보인다.**
      (이 검사를 쓰다가 실제로 그렇게 됐다. 아래 자체 검증이 그 재발을 막는다.)
    """
    import contextlib
    # 경로 전환 수단은 `db.DB_PATH` 대입 하나뿐이다 — `AUCTION_DB_PATH` 는 읽는 곳이
    # 없어 지웠다(2026-08-26, `test_image_queue_transition._fresh_db` 주석 참고).
    path = os.path.join(tmp, "auction.db")
    import storage.database as db
    import storage.migrate_v4_1 as mig
    import storage.migrations.run_migrations as runmig
    db.DB_PATH = path
    with contextlib.redirect_stdout(io.StringIO()):
        db.init_db()
        mig.migrate()
        runmig.run()

    # 자체 검증: 종결 경로가 쓰는 테이블이 실제로 있는가
    conn = db.get_connection()
    try:
        have = {r["name"] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        conn.close()
    missing = {"document_queue", "document_status", "auction_image"} - have
    if missing:
        raise AssertionError("fixture 스키마가 불완전하다: %s" % sorted(missing))
    return db


def _seed(db, n_items, doc_types, status="pending"):
    """물건 n_items 개 x doc_types 종류를 큐에 넣는다."""
    future = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")
    conn = db.get_connection()
    for i in range(n_items):
        for t in doc_types:
            conn.execute(
                "INSERT INTO document_queue (court_code, case_no, item_no, doc_type,"
                " status, retry_count, auction_date, priority, last_attempt_at)"
                " VALUES (?,?,?,?,?,0,?,?,NULL)",
                ("B0002%02d" % i, "2024타경%d" % (1000 + i), "1", t, status, future, i))
    conn.commit()
    conn.close()


NL = chr(10)


def _queue_rows(db):
    conn = db.get_connection()
    rows = [dict(r) for r in conn.execute(
        "SELECT id, case_no, doc_type, status, retry_count FROM document_queue"
        " ORDER BY case_no, doc_type")]
    conn.close()
    return rows


def _spy(sink, real):
    """호출 인자를 기록하고 그대로 넘긴다(제품 동작은 바꾸지 않는다)."""
    def wrapper(*a, **kw):
        sink.append((a, kw))
        return real(*a, **kw)
    return wrapper


def _run_worker(db, *, legacy=False, collect_result=None, exact_nav_ok=True,
                detail_ok=None):
    """진짜 `doc_worker.main()` 을 돌린다. 브라우저/수집기만 가짜.

    legacy=True 면 claim 을 **행 하나씩**으로 되돌려 예전 구조를 재현한다
    (전/후를 같은 fixture, 같은 계측으로 비교하기 위해서다).
    """
    import doc_worker as dw

    # 종결에 **무엇을 넘겼는지** 기록한다. 결과만 보면 배선 누락이 안 보인다
    # (claim_token 을 빼도 단일 실행에서는 결과가 같다 - mutation T7, Sprint 254).
    stats = {"navs": [], "collects": [], "reused": 0, "done": [], "failed": []}

    def spy_go(driver, court_code, case_no, item_no=None, require_exact_item=False):
        stats["navs"].append((court_code, case_no, item_no, require_exact_item))
        return exact_nav_ok or not require_exact_item

    def fake_collect(driver, court_code, case_no, item_no, doc_type, btn_id,
                     overwrite=False):
        stats["collects"].append((case_no, doc_type, overwrite))
        if collect_result is not None:
            r = collect_result(case_no, doc_type)
            if r is not None:
                return r
        return {"success": True, "previous_hash": None, "new_hash": "h",
                "partial": False, "no_asset": False, "images": [], "files_saved": []}

    real_claim = db.claim_next_item_rows

    def legacy_claim(*a, **kw):
        # 예전 구조: 한 번에 한 행. 같은 선택 규칙을 그대로 쓴다.
        rows = real_claim(max_rows=1)
        return rows

    targets = {
        "init_db": lambda: None,
        "reset_stale_queue": lambda: None,
        "build_download_driver": lambda: _FakeDriver("main"),
        "restart_download_driver": lambda d: _FakeDriver("restarted"),
        "claim_next_item_rows": (legacy_claim if legacy else real_claim),
        "release_queue_rows": db.release_queue_rows,
        "go_to_case_detail": spy_go,
        # ★ 기본은 True 지만 **고정이 아니다** (2026-08-21 Sprint 240).
        #   여기가 상수로 박혀 있어서 `_ensure_detail_page()` 의 "재사용 전에
        #   화면을 확인한다" 분기가 어떤 검사에도 걸리지 않았다 — mutation 으로
        #   `if wait_for_detail(...)` 을 `if True:` 로 바꿔도 전 검사가 통과했다.
        "wait_for_detail": (detail_ok if detail_ok is not None
                            else (lambda driver, case_no: True)),
        "get_doc_button_id": lambda doc_type, item_no: "qa-btn",
        "collect_document": fake_collect,
        "mark_queue_done": _spy(stats["done"], db.mark_queue_done),
        "mark_queue_failed": _spy(stats["failed"], db.mark_queue_failed),
        "mark_queue_skipped_expired": db.mark_queue_skipped_expired,
        "mark_queue_unsupported": db.mark_queue_unsupported,
        "save_auction_images": db.save_auction_images,
        "find_sibling_case_document": lambda *a, **kw: None,
        "reconcile_queue_auction_date": lambda qid, c, i, d, cc: d,
    }
    originals = {}
    for k, v in targets.items():
        originals[k] = getattr(dw, k)
        setattr(dw, k, v)
    # 실행 창(02:00~04:00) 밖에서도 돌 수 있게 한다. 이 검사는 시각이 아니라
    # **이동 횟수**를 본다. 창 자체의 동작은 6번 검사가 따로 본다.
    prev_mode = os.environ.get("DOC_WORKER_TEST_MODE")
    os.environ["DOC_WORKER_TEST_MODE"] = "1"
    # sleep 을 없앤다 - 이 검사는 시간이 아니라 **횟수**를 본다
    import time as _t
    real_sleep = dw.time_module.sleep
    dw.time_module.sleep = lambda s: None
    try:
        code = dw.main()
    finally:
        dw.time_module.sleep = real_sleep
        if prev_mode is None:
            os.environ.pop("DOC_WORKER_TEST_MODE", None)
        else:
            os.environ["DOC_WORKER_TEST_MODE"] = prev_mode
        for k, v in originals.items():
            setattr(dw, k, v)
        try:
            os.remove(dw.LOCK_PATH)
        except OSError:
            pass
    stats["exit"] = code
    return stats


# ---------------------------------------------------------------------------
# 1. 이동 횟수 - 전/후를 같은 fixture 에서 비교한다
# ---------------------------------------------------------------------------
def test_batching_reduces_navigations():
    print("\n--- 1. 물건 단위 batching 이 이동을 줄이는가 (같은 fixture, 전/후) ---")
    import config.settings as cfg
    types = list(cfg.DOC_TYPE_LIST)
    N = 12

    tmp = tempfile.mkdtemp(prefix="qa_batch_before_")
    try:
        db = _fresh_db(tmp)
        _seed(db, N, types)
        before = _run_worker(db, legacy=True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    tmp = tempfile.mkdtemp(prefix="qa_batch_after_")
    try:
        db = _fresh_db(tmp)
        _seed(db, N, types)
        after = _run_worker(db, legacy=False)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    n_rows = N * len(types)
    print("    물건 %d개 x %d종 = 큐 %d행" % (N, len(types), n_rows))
    print("    예전 구조  이동 %3d회 / 수집 %3d회" % (len(before["navs"]), len(before["collects"])))
    print("    지금 구조  이동 %3d회 / 수집 %3d회" % (len(after["navs"]), len(after["collects"])))

    check_true("검사가 공허하지 않다(실제로 처리했다)",
               len(after["collects"]) == n_rows and n_rows >= 24,
               (len(after["collects"]), n_rows))

    # ★ Sprint 236 **이전**의 이동 횟수는 시뮬레이션하지 않는다 - 실측이 있다.
    #   예전 코드는 행마다 무조건 `go_to_case_detail()` 을 불렀고, 운영 로그가
    #   그것을 그대로 보여 준다: 의미 있는 실행 7회 전부에서 행/이동 = 1.00
    #   (합계 897행 / 897이동). 그러므로 예전 이동 횟수 = 행 수다.
    legacy_navs = n_rows
    check("★ 지금 구조는 물건마다 한 번만 이동한다", len(after["navs"]), N)
    check("수집 횟수는 그대로다(일을 덜 한 것이 아니다)",
          len(after["collects"]), n_rows)

    ratio = legacy_navs / float(len(after["navs"]))
    print("    -> 이동 %d회 -> %d회 = **%.1f배 감소** (실측 기준선: 행마다 1회)"
          % (legacy_navs, len(after["navs"]), ratio))
    check("이동 감소 배수 = doc_type 수", round(ratio, 2), float(len(types)))

    # 재사용이 실제로 일어났는지(이동을 건너뛴 횟수)
    check("한 물건에서 재사용한 횟수 = 종류 수 - 1",
          len(after["collects"]) - len(after["navs"]), N * (len(types) - 1))

    # ★ 곁다리 발견 - 페이지 재사용만으로도 절반이 준다.
    #   `before` 는 claim 을 행 하나씩으로 되돌렸지만 페이지 재사용은 켜 둔 실행이다.
    #   그래서 "예전 구조"가 아니라 **batching 없이 재사용만 켠 구조**를 보여 준다.
    #   여기서 이동이 행 수보다 적게 나오는 것이 정상이다 - 같은 물건의 행이
    #   연달아 나오면 재사용되기 때문이다. 이 값을 예전 기준선으로 쓰면 안 된다.
    print("    (참고) claim 은 행 단위 + 페이지 재사용만: 이동 %d회"
          % len(before["navs"]))
    check_true("참고 실행은 재사용 덕에 행 수보다 적게 이동한다",
               len(before["navs"]) < n_rows, (len(before["navs"]), n_rows))
    check_true("★ 그래도 물건 단위 claim 이 더 적게 이동한다(정렬이 사진을 앞에 둔다)",
               len(after["navs"]) < len(before["navs"]),
               (len(after["navs"]), len(before["navs"])))


# ---------------------------------------------------------------------------
# 2. 사진 정확일치가 batching 으로 느슨해지지 않는다
# ---------------------------------------------------------------------------
def test_image_still_requires_exact_item():
    print("\n--- 2. 사진의 정확 일치가 유지되는가 ---")
    import config.settings as cfg
    if "image" not in cfg.DOC_TYPE_LIST:
        check_true("config 에 image 가 있다(이 검사가 의미 있으려면)", False,
                   cfg.DOC_TYPE_LIST)
        return

    tmp = tempfile.mkdtemp(prefix="qa_batch_exact_")
    try:
        db = _fresh_db(tmp)
        _seed(db, 5, list(cfg.DOC_TYPE_LIST))
        s = _run_worker(db)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    exacts = [n[3] for n in s["navs"]]
    print("    이동 %d회, 그중 엄격 %d회" % (len(exacts), sum(1 for e in exacts if e)))
    check_true("검사가 공허하지 않다(이동이 있었다)", len(exacts) == 5, len(exacts))
    check("★ 물건당 단 한 번의 이동이 **엄격하게** 이뤄진다",
          [bool(e) for e in exacts], [True] * 5)

    first = [c[1] for c in s["collects"][:1]]
    check("사진을 가장 먼저 처리한다(엄격한 이동을 나머지가 재사용하도록)",
          first, ["image"])


def test_image_failure_does_not_take_documents_down():
    print("\n--- 3. 엄격 진입이 실패해도 문서는 각자 처리된다 ---")
    import config.settings as cfg
    types = list(cfg.DOC_TYPE_LIST)
    tmp = tempfile.mkdtemp(prefix="qa_batch_exactfail_")
    try:
        db = _fresh_db(tmp)
        _seed(db, 3, types)
        # 엄격 진입만 실패시킨다(모호한 다중물건 상황의 재현)
        s = _run_worker(db, exact_nav_ok=False)
        rows = _queue_rows(db)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    img = [r for r in rows if r["doc_type"] == "image"]
    doc = [r for r in rows if r["doc_type"] != "image"]
    collected = set(c[1] for c in s["collects"])
    print("    수집이 도달한 종류: %s" % sorted(collected))
    check_true("검사가 공허하지 않다(행이 있다)", len(rows) == 3 * len(types), len(rows))
    check("★ 사진은 수집기에 도달하지 않는다(엄격 진입 실패)",
          "image" in collected, False)
    check_true("★ 문서는 정상적으로 수집된다(사진 실패에 끌려가지 않는다)",
               all(t in collected for t in types if t != "image"),
               sorted(collected))
    check_true("사진 행은 재시도로 남는다(영구 실패로 굳지 않는다)",
               all(r["status"] in ("pending", "refresh", "failed") for r in img),
               [(r["doc_type"], r["status"]) for r in img])
    check_true("문서 행은 종결됐다",
               all(r["status"] == "done" for r in doc),
               [(r["doc_type"], r["status"]) for r in doc])


# ---------------------------------------------------------------------------
# 4. 부분 실패 - 한 종류가 실패해도 나머지는 각자 끝난다
# ---------------------------------------------------------------------------
def test_partial_failure_is_per_row():
    print("\n--- 4. 부분 실패가 행 단위로 남는가 ---")
    import config.settings as cfg
    types = list(cfg.DOC_TYPE_LIST)
    victim = "spec" if "spec" in types else types[0]

    tmp = tempfile.mkdtemp(prefix="qa_batch_partial_")
    try:
        db = _fresh_db(tmp)
        _seed(db, 4, types)

        def result(case_no, doc_type):
            if doc_type == victim:
                return {"success": False, "previous_hash": None, "new_hash": None,
                        "partial": False, "no_asset": False, "images": [],
                        "files_saved": []}
            return None

        s = _run_worker(db, collect_result=result)
        rows = _queue_rows(db)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    bad = [r for r in rows if r["doc_type"] == victim]
    good = [r for r in rows if r["doc_type"] != victim]
    check_true("검사가 공허하지 않다", len(bad) == 4 and len(good) == 4 * (len(types) - 1),
               (len(bad), len(good)))
    check_true("★ 실패한 종류만 재시도로 남는다",
               all(r["status"] in ("pending", "refresh") and r["retry_count"] == 1
                   for r in bad),
               [(r["doc_type"], r["status"], r["retry_count"]) for r in bad])
    check_true("★ 같은 물건의 나머지 종류는 성공으로 끝난다",
               all(r["status"] == "done" for r in good),
               [(r["doc_type"], r["status"]) for r in good])
    check_true("성공한 행의 재시도 예산은 깎이지 않았다",
               all(r["retry_count"] == 0 for r in good),
               [(r["doc_type"], r["retry_count"]) for r in good])
    check("실패해도 그 물건에 다시 들어가지 않는다(이동은 여전히 물건당 1회)",
          len(s["navs"]), 4)


# ---------------------------------------------------------------------------
# 5. refresh 의도가 행별로 유지된다
# ---------------------------------------------------------------------------
def test_refresh_intent_is_per_row():
    print("\n--- 5. 재수집 의도가 행마다 유지되는가 ---")
    import config.settings as cfg
    types = list(cfg.DOC_TYPE_LIST)
    tmp = tempfile.mkdtemp(prefix="qa_batch_refresh_")
    try:
        db = _fresh_db(tmp)
        _seed(db, 2, types)
        # 절반만 refresh 로 바꾼다
        conn = db.get_connection()
        conn.execute("UPDATE document_queue SET status='refresh' WHERE doc_type IN (?,?)",
                     (types[0], types[-1]))
        conn.commit()
        conn.close()
        s = _run_worker(db)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    seen = {}
    for case_no, doc_type, overwrite in s["collects"]:
        seen.setdefault(doc_type, set()).add(overwrite)
    print("    수집기가 받은 overwrite: %s"
          % {k: sorted(v) for k, v in sorted(seen.items())})
    check_true("검사가 공허하지 않다(모든 종류가 수집기에 닿았다)",
               set(seen) == set(types), sorted(seen))
    check("★ refresh 행만 overwrite=True 로 간다",
          sorted(t for t in seen if seen[t] == {True}),
          sorted({types[0], types[-1]}))
    check("★ pending 행은 overwrite=False 로 간다",
          sorted(t for t in seen if seen[t] == {False}),
          sorted(set(types) - {types[0], types[-1]}))


# ---------------------------------------------------------------------------
# 6. 집은 행을 방치하지 않는다
# ---------------------------------------------------------------------------
def test_no_row_is_left_claimed():
    print("\n--- 6. 집어 두고 방치한 행이 없는가 ---")
    import config.settings as cfg
    import doc_worker as dw
    types = list(cfg.DOC_TYPE_LIST)

    tmp = tempfile.mkdtemp(prefix="qa_batch_leftover_")
    try:
        db = _fresh_db(tmp)
        _seed(db, 6, types)
        # 실행 창을 첫 물건 처리 도중에 닫는다
        calls = {"n": 0}
        real_time_up = dw.is_time_up

        def closing_window():
            calls["n"] += 1
            return calls["n"] > 2      # 두 행 처리 후 창이 닫힌다

        dw.is_time_up = closing_window
        try:
            s = _run_worker(db)
        finally:
            dw.is_time_up = real_time_up
        rows = _queue_rows(db)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    stuck = [r for r in rows if r["status"] in ("in_progress", "in_progress_refresh")]
    print("    처리한 행 %d / 남은 in_progress %d" % (len(s["collects"]), len(stuck)))
    check_true("검사가 공허하지 않다(창이 실제로 중간에 닫혔다)",
               0 < len(s["collects"]) < 6 * len(types),
               (len(s["collects"]), 6 * len(types)))
    check("★ 시도하지 않은 행을 in_progress 로 방치하지 않는다", len(stuck), 0)
    waiting = [r for r in rows if r["status"] in ("pending", "refresh")]
    check_true("★ 되돌린 행은 재시도 예산을 잃지 않았다",
               all(r["retry_count"] == 0 for r in waiting),
               [(r["doc_type"], r["retry_count"]) for r in waiting][:5])


# ---------------------------------------------------------------------------
# 7. 드라이버가 깨지면 페이지 기억도 버린다
# ---------------------------------------------------------------------------
def test_driver_restart_invalidates_page_memory():
    print("\n--- 7. 드라이버 재시작 후 페이지 기억을 버리는가 ---")
    import doc_worker as dw

    seen = []
    orig = (dw.go_to_case_detail, dw.wait_for_detail)
    try:
        dw.go_to_case_detail = lambda d, c, cn, i=None, require_exact_item=False: (
            seen.append(1) or True)
        dw.wait_for_detail = lambda d, cn: True

        page = {}
        dw._ensure_detail_page(object(), page, "B1", "2024타경1", "1", require_exact=False)
        check("첫 진입은 이동한다", len(seen), 1)
        dw._ensure_detail_page(object(), page, "B1", "2024타경1", "1", require_exact=False)
        check("두 번째는 재사용한다", len(seen), 1)

        page.clear()          # 워커가 드라이버 재시작 때 하는 일
        dw._ensure_detail_page(object(), page, "B1", "2024타경1", "1", require_exact=False)
        check("★ 기억을 버리면 다시 이동한다(빈 페이지에서 긁지 않는다)", len(seen), 2)
    finally:
        dw.go_to_case_detail, dw.wait_for_detail = orig

    src = io.open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "doc_worker.py"), encoding="utf-8-sig").read()
    # 주석이 아니라 **코드**에 있는지 본다
    code = "\n".join(l for l in src.splitlines()
                     if not l.lstrip().startswith("#"))
    check_true("★ 드라이버 재시작 경로가 페이지 기억을 실제로 비운다(코드)",
               "page.clear()" in code,
               "주석이 아니라 코드에 있어야 한다")


# ---------------------------------------------------------------------------
# 8. claim 자체의 계약 (묶어 온다고 규칙을 건너뛰지 않는다)
# ---------------------------------------------------------------------------
def test_claim_groups_one_item_only():
    print("\n--- 8. 묶음 claim 이 한 물건만 집는가 ---")
    tmp = tempfile.mkdtemp(prefix="qa_batch_claim_")
    try:
        db = _fresh_db(tmp)
        future = (datetime.now() + timedelta(days=5)).strftime("%Y-%m-%d")
        conn = db.get_connection()

        def add(court, case, item, dtype, status="pending", last=None, prio=1):
            conn.execute(
                "INSERT INTO document_queue (court_code, case_no, item_no, doc_type,"
                " status, retry_count, auction_date, priority, last_attempt_at)"
                " VALUES (?,?,?,?,?,0,?,?,?)",
                (court, case, item, dtype, status, future, prio, last))

        for t in ("spec", "status", "appraisal", "image"):
            add("B1", "2024타경1", "1", t, prio=0)
        add("B1", "2024타경1", "2", "spec", prio=0)   # 같은 사건, 다른 물건
        add("B1", "2024타경2", "1", "spec", prio=0)   # 다른 사건
        add("B2", "2024타경1", "1", "spec", prio=0)   # 다른 법원, 같은 사건번호
        conn.commit()
        conn.close()

        rows = db.claim_next_item_rows()
        keys = {(r["court_code"], r["case_no"], r["item_no"]) for r in rows}
        check("★ 한 물건의 4종을 집는다", len(rows), 4)
        check("★ 물건 키가 하나다(다른 법원/사건/물건이 섞이지 않는다)", len(keys), 1)
        check("집은 것은 첫 물건이다", sorted(keys)[0], ("B1", "2024타경1", "1"))

        conn = db.get_connection()
        untouched = conn.execute(
            "SELECT COUNT(*) c FROM document_queue WHERE status='pending'").fetchone()["c"]
        conn.close()
        check("★ 나머지 3행은 건드리지 않았다", untouched, 3)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_claim_keeps_retry_interval_for_siblings():
    print("\n--- 9. 형제 행에도 재시도 간격이 걸리는가 ---")
    tmp = tempfile.mkdtemp(prefix="qa_batch_interval_")
    try:
        db = _fresh_db(tmp)
        future = (datetime.now() + timedelta(days=5)).strftime("%Y-%m-%d")
        recent = (datetime.now() - timedelta(minutes=5)).isoformat()
        old = (datetime.now()
               - timedelta(minutes=db.RETRY_INTERVAL_MINUTES * 3)).isoformat()
        conn = db.get_connection()
        for t, last in (("spec", None), ("status", recent), ("appraisal", old)):
            conn.execute(
                "INSERT INTO document_queue (court_code, case_no, item_no, doc_type,"
                " status, retry_count, auction_date, priority, last_attempt_at)"
                " VALUES (?,?,?,?,'pending',1,?,0,?)",
                ("B1", "2024타경7", "1", t, future, last))
        conn.commit()
        conn.close()

        got = sorted(r["doc_type"] for r in db.claim_next_item_rows())
        print("    집은 것: %s (간격 %d분)" % (got, db.RETRY_INTERVAL_MINUTES))
        check_true("검사가 공허하지 않다(뭔가 집었다)", len(got) >= 1, got)
        check("★ 방금 실패한 형제는 집지 않는다(예산을 몇 분 만에 태우지 않는다)",
              "status" in got, False)
        check("간격이 지난 형제는 집는다", "appraisal" in got, True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# 10. 묶음 안에 **종결 대상**이 섞여 있을 때
# ---------------------------------------------------------------------------
def test_terminated_row_does_not_take_the_batch_down():
    """기일 경과/미지원으로 종결되는 행이 묶음 첫 자리에 와도 나머지는 처리된다.

    예전 구조에서는 종결 행이 `continue` 로 다음 **claim** 으로 넘어갔다.
    지금은 같은 `continue` 가 **같은 묶음의 다음 행**으로 간다 - 그 차이가
    조용히 나머지를 버리지 않는지 확인한다.
    """
    print("\n--- 10. 묶음에 종결 대상이 섞여 있을 때 ---")
    import config.settings as cfg
    types = list(cfg.DOC_TYPE_LIST)
    victim = types[0]

    tmp = tempfile.mkdtemp(prefix="qa_batch_expired_")
    try:
        db = _fresh_db(tmp)
        _seed(db, 3, types)
        # 한 종류만 기일이 지난 것으로 만든다(같은 물건의 나머지는 미래 기일)
        past = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d")
        conn = db.get_connection()
        conn.execute("UPDATE document_queue SET auction_date=?, priority=-1"
                     " WHERE doc_type=?", (past, victim))
        conn.commit()
        conn.close()

        s = _run_worker(db)
        rows = _queue_rows(db)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    collected = [c[1] for c in s["collects"]]
    dead = [r for r in rows if r["doc_type"] == victim]
    rest = [r for r in rows if r["doc_type"] != victim]
    print("    수집 도달: %s" % sorted(set(collected)))
    print("    종결 대상 상태: %s" % sorted(set(r["status"] for r in dead)))

    check_true("검사가 공허하지 않다(행이 다 있다)",
               len(rows) == 3 * len(types), len(rows))
    check("★ 기일 지난 종류는 수집기에 가지 않는다", victim in collected, False)
    check("★ 종결 대상은 SKIPPED_EXPIRED 로 끝난다",
          sorted(set(r["status"] for r in dead)), ["SKIPPED_EXPIRED"])
    check_true("★ 같은 묶음의 나머지 종류는 정상 처리된다(조용히 버려지지 않는다)",
               all(r["status"] == "done" for r in rest),
               [(r["doc_type"], r["status"]) for r in rest][:6])
    check("나머지 수집 횟수 = 물건 3 x (종류-1)",
          len(collected), 3 * (len(types) - 1))
    check("이동은 여전히 물건당 1회", len(s["navs"]), 3)


# ---------------------------------------------------------------------------
# 11. 종료 시각 초과가 **행 하나**로 제한되는가
# ---------------------------------------------------------------------------
def test_time_check_happens_per_row_not_per_batch():
    """`is_time_up()` 이 **행마다** 검사되는가 (2026-08-20 Sprint 237).

    왜 중요한가 - 워커는 종료 시각에 딱 멈추지 않는다. 이미 처리 중이던 것은
    끝까지 처리하고 나간다. 그 **초과분**이 06:00 사건 크롤과 겹치면 Chrome 두 개가
    같은 법원을 동시에 두드린다(둘은 서로의 락을 보지 않는다).

    `test_schema_hygiene.py` 의 '종료와 크롤 시작 사이 5분 여유' 가드는
    **초과분이 행 하나뿐**이라는 전제 위에 서 있다. batching 이 그 전제를
    물건 하나(= 최대 4행)로 키웠다면 그 여유 계산이 무너진다.

    묶음을 집은 뒤에도 **행을 꺼낼 때마다** 시각을 보는지 호출 횟수로 확인한다.
        행마다 검사   -> 호출 = 처리한 행 + 1 (마지막에 루프를 끝내는 검사)
        묶음마다 검사 -> 호출 = 묶음 수 + 1   (그러면 초과분이 최대 4행이 된다)
    """
    print("\n--- 11. 종료 시각 검사가 행마다 일어나는가 ---")
    import config.settings as cfg
    import doc_worker as dw
    types = list(cfg.DOC_TYPE_LIST)
    N = 3

    tmp = tempfile.mkdtemp(prefix="qa_batch_timecheck_")
    calls = {"n": 0}
    real = dw.is_time_up
    try:
        db = _fresh_db(tmp)
        _seed(db, N, types)

        def counting_time_up():
            calls["n"] += 1
            return False          # 창은 열려 있다 - 큐가 비어서 끝나게 둔다

        dw.is_time_up = counting_time_up
        try:
            s = _run_worker(db)
        finally:
            dw.is_time_up = real
    finally:
        dw.is_time_up = real
        shutil.rmtree(tmp, ignore_errors=True)

    rows = N * len(types)
    batches = N
    print("    처리한 행 %d / 묶음 %d / is_time_up 호출 %d회"
          % (len(s["collects"]), batches, calls["n"]))
    check_true("검사가 공허하지 않다(행을 전부 처리했다)",
               len(s["collects"]) == rows, (len(s["collects"]), rows))
    # 호출 = 기동 전 1회(드라이버를 띄우기 전 창이 닫혔는지 본다)
    #      + 루프 조건 (행마다 + 큐가 비어 끝나는 1회)
    # 이 +2 는 코드를 읽고 센 것이 아니라 **틀렸다가 맞춘 값**이다 - 처음에 기동 전
    # 검사를 빼먹고 rows+1 로 기대했다가 14 != 13 으로 울었다.
    check("★ 시각 검사가 **행마다** 일어난다(초과분이 행 하나로 제한된다)",
          calls["n"], rows + 2)
    check_true("★ 묶음 단위로만 검사하지 않는다(그러면 초과분이 최대 %d행)" % len(types),
               calls["n"] > batches + 1, (calls["n"], batches + 1))


def test_window_end_leaves_margin_before_crawl():
    """설정된 종료 시각이 사건 크롤 시작보다 **충분히** 앞서는가.

    같은 관계를 `test_schema_hygiene.py` 가 config 와 PS1 문자열로 본다.
    여기서는 **실측 초과분**과 함께 본다 - 두 파일이 같은 사실을 다른 근거로
    잡아야 한 쪽이 조용히 무뎌져도 다른 쪽이 운다.
    """
    print("\n--- 12. 종료 시각과 크롤 시작 사이 여유 ---")
    import config.settings as cfg
    import re as _re

    ps1 = io.open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "register_scheduler_tasks.ps1"),
                  encoding="utf-8-sig").read()
    m = _re.search(r"DailyCrawl[^\n]*?Time\s*=\s*'([0-9:]+)'", ps1)
    check_true("등록 스크립트에서 크롤 시각을 찾았다(검사가 공허하지 않다)", bool(m), None)
    if not m:
        return

    def mins(hhmm):
        h, mm = hhmm.split(":")
        return int(h) * 60 + int(mm)

    gap_min = mins(m.group(1)) - mins(cfg.DOC_WORKER_END_TIME)
    # 실측: logs/doc_run.log 907구간에서 행 1개 처리 최대 42.2초.
    # 이론 최대는 그보다 크다(wait_for_detail 20초 + 오버레이 15초 + 새창 15초).
    WORST_ROW_SECONDS = 50
    print("    종료 %s / 크롤 %s -> 여유 %d분 (행 1개 최악 %d초)"
          % (cfg.DOC_WORKER_END_TIME, m.group(1), gap_min, WORST_ROW_SECONDS))
    check_true("★ 여유가 행 1개 최악 처리시간보다 크다",
               gap_min * 60 > WORST_ROW_SECONDS,
               "여유 %d초 <= 최악 %d초 - 마지막 행이 크롤과 겹친다"
               % (gap_min * 60, WORST_ROW_SECONDS))
    print("    -> 안전 상한: 크롤 %s 에서 5분 뺀 **%02d:%02d**"
          % (m.group(1), (mins(m.group(1)) - 5) // 60, (mins(m.group(1)) - 5) % 60))



# ---------------------------------------------------------------------------
# 13. 재사용하기 전에 **화면을 실제로 확인**하는가 (2026-08-21 Sprint 240)
# ---------------------------------------------------------------------------
def test_reuse_verifies_the_page_before_trusting_it():
    """`_ensure_detail_page()` 는 "아까 들어갔으니 아직 그 페이지일 것"을 **믿지 않는다.**

    ## 왜 이 검사가 새로 필요했나 — mutation 이 공백을 잡았다

    2026-08-21 실측: `doc_worker.py` 의

        if wait_for_detail(driver, case_no):

    를 `if True:` 로 바꾸는 mutation 을 걸었더니 **`test_worker_batching.py`(268단언)
    와 `test_doc_worker_recovery.py` 가 둘 다 그대로 통과했다.** 이유는 단순하다 —
    두 파일의 모든 harness 가 `wait_for_detail` 을 `lambda: True` 상수로 스텁해서,
    False 분기(= 화면을 벗어나 있다 -> 다시 이동한다)를 **한 번도 지나가지 않았다.**

    Sprint 236 이 이 확인을 넣은 이유는 그 함수의 docstring 에 이미 적혀 있다:
    문서 수집기는 새 창을 열고 닫은 뒤 원래 창으로 돌아오는데 그 복구가 전부
    `try/except: pass` 다(`crawler/doc_crawler.py` 의 finally 두 곳). 돌아오지 못한
    채 다음 종류를 처리하면 **엉뚱한 화면에서 남의 문서를 긁는다** — 이 저장소가
    사진에서 겪은(Sprint 230) 것과 같은 계열의, 조용히 틀리는 결함이다.

    즉 **가장 비싼 최적화(batching)가 가장 위험한 가정 위에 서 있는데, 그 가정을
    지키는 유일한 가드에 검사가 없었다.** 지우면 아무도 울지 않는 가드는 없는 것과
    같다. 그래서 여기서 False 분기를 실제로 태운다.
    """
    print(NL + "--- 13. 재사용 전에 화면을 실제로 확인하는가 (mutation 공백) ---")
    import doc_worker as dw

    # ── (A) 단위: 확인이 False 면 재사용하지 않고 다시 이동한다 ──────────────
    navs = []
    detail_answer = [True]
    orig = (dw.go_to_case_detail, dw.wait_for_detail)
    try:
        dw.go_to_case_detail = lambda d, c, cn, i=None, require_exact_item=False: (
            navs.append((cn, i, require_exact_item)) or True)
        dw.wait_for_detail = lambda d, cn: detail_answer[0]

        page = {}
        dw._ensure_detail_page(object(), page, "B1", "2024타경1", "1", require_exact=False)
        check("첫 진입은 이동한다", len(navs), 1)

        # 화면이 그대로다 -> 이동하지 않는다 (최적화가 실제로 동작한다)
        dw._ensure_detail_page(object(), page, "B1", "2024타경1", "1", require_exact=False)
        check("화면이 그대로면 재사용한다(이동 없음)", len(navs), 1)

        # ★ 화면을 벗어났다(수집기가 원래 창으로 못 돌아왔다) -> 반드시 다시 이동한다
        detail_answer[0] = False
        ok = dw._ensure_detail_page(object(), page, "B1", "2024타경1", "1",
                                    require_exact=False)
        check("★ 화면을 벗어나 있으면 재사용하지 않고 다시 이동한다", len(navs), 2)
        check_true("다시 이동에 성공하면 True 를 돌려준다", ok, None)

        # 확인이 계속 False 여도 **매번** 다시 이동한다 — 한 번 실패했다고
        # 확인을 포기하고 재사용으로 떨어지면 안 된다.
        dw._ensure_detail_page(object(), page, "B1", "2024타경1", "1", require_exact=False)
        check("★ 확인 실패가 반복돼도 매번 다시 이동한다", len(navs), 3)

        # ── (B) 확인이 False 이고 재이동도 실패하면 성공이라고 말하지 않는다 ──
        navs2 = []
        dw.go_to_case_detail = lambda d, c, cn, i=None, require_exact_item=False: (
            navs2.append(1) or False)
        page2 = {"key": ("B1", "2024타경9", "1"), "exact": True}
        ok2 = dw._ensure_detail_page(object(), page2, "B1", "2024타경9", "1",
                                     require_exact=False)
        check_true("★ 재이동이 실패하면 False 를 돌려준다(빈 화면에서 긁지 않는다)",
                   ok2 is False, "ok2=%r" % (ok2,))
        check_true("★ 실패 후 페이지 기억을 남기지 않는다(다음 행이 재사용하지 못한다)",
                   page2.get("key") is None,
                   "page.key=%r 가 남았다" % (page2.get("key"),))
    finally:
        dw.go_to_case_detail, dw.wait_for_detail = orig

    # ── (C) 워커 전체: 확인이 항상 False 면 batching 이 이동을 줄이지 못한다 ──
    #   이것이 이 가드의 **의미**다 — 확인이 통과할 때만 이동이 줄어든다.
    #   (확인 없이 무조건 재사용하면 아래 두 수가 같아진다 = mutation 이 살아난다)
    import config.settings as cfg
    types = list(cfg.DOC_TYPE_LIST)
    N = 3

    tmp = tempfile.mkdtemp(prefix="qa_batch_verify_ok_")
    try:
        db = _fresh_db(tmp)
        _seed(db, N, types)
        verified = _run_worker(db, detail_ok=lambda d, cn: True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    tmp = tempfile.mkdtemp(prefix="qa_batch_verify_drift_")
    try:
        db = _fresh_db(tmp)
        _seed(db, N, types)
        drifted = _run_worker(db, detail_ok=lambda d, cn: False)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    n_rows = N * len(types)
    print("    물건 %d개 x %d종 = 큐 %d행" % (N, len(types), n_rows))
    print("    화면 확인 통과  이동 %3d회 / 수집 %3d회"
          % (len(verified["navs"]), len(verified["collects"])))
    print("    화면 벗어남     이동 %3d회 / 수집 %3d회"
          % (len(drifted["navs"]), len(drifted["collects"])))

    check("★ 확인이 통과하면 물건당 이동 1회", len(verified["navs"]), N)
    check_true("★ 화면을 벗어나 있으면 행마다 다시 이동한다(맹신하지 않는다)",
               len(drifted["navs"]) == n_rows,
               "이동 %d회 != 큐 %d행 - 확인 없이 재사용했다"
               % (len(drifted["navs"]), n_rows))
    check_true("두 경우 모두 수집 자체는 정상 수행된다(가드가 기능을 죽이지 않는다)",
               len(verified["collects"]) == n_rows == len(drifted["collects"]),
               "수집 %d / %d (기대 %d)"
               % (len(verified["collects"]), len(drifted["collects"]), n_rows))

    # ── (D) 코드에 실제로 있는가 — 주석만 남고 코드가 사라지는 것을 막는다 ──
    src = io.open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "doc_worker.py"), encoding="utf-8-sig").read()
    code = NL.join(l for l in src.splitlines()
                   if not l.lstrip().startswith("#"))
    check_true("★ 재사용 분기가 실제로 wait_for_detail 을 호출한다(코드)",
               "if wait_for_detail(driver, case_no):" in code,
               "주석이 아니라 코드에 있어야 한다")



# ---------------------------------------------------------------------------
# 14. 기존 큐(3종)에 image 가 뒤늦게 붙는 전환 상태 (2026-08-21 Sprint 242)
# ---------------------------------------------------------------------------
def test_image_row_added_later_to_an_already_done_item():
    """spec/status/appraisal 이 **이미 done** 인 물건에 `image` 행만 새로 붙는 상태.

    ## 왜 이것이 실제 상태인가

    2026-08-21 운영 DB 실측:

        document_queue doc_type 분포 = {appraisal: 1166, spec: 1166, status: 1166}
        image = **0행**

    즉 지금 큐에 쌓인 2,753 pending 행은 전부 `image` 가 `DOC_TYPE_LIST` 에 추가되기
    **전에** 적재된 것이다. 그런데 `enqueue_documents()` 는 지금 4종을 넣는다
    (`for doc_type in ("spec","status","appraisal","image")`). 따라서 크롤이 재개되면
    **기존 물건 전부가 `image` 행 하나씩을 새로 받는다** — 그중 상당수는 나머지 3종이
    이미 `done` 인 상태다.

    그 전환 상태는 지금까지 어떤 검사도 지나가지 않았다. 기존 검사들은
    "처음부터 4종이 함께 있는 물건"(2번/3번 검사)이나 "빈 큐에 새로 적재"
    (`test_asset_pipeline.py` 15번)만 본다.

    ## 무엇이 틀릴 수 있나

        1. 새 enqueue 가 **이미 done 인 3종을 되살려** 헛수집을 만든다
        2. 워커가 image 한 행만 든 묶음을 처리하지 못한다
        3. image 단독인데 **느슨하게** 진입해 다른 물건의 사진을 가져온다(Sprint 230)
        4. 이미 받아 둔 문서를 다시 받는다
    """
    print("\n--- 14. 이미 done 인 물건에 image 행만 뒤늦게 붙는다 (Sprint 242) ---")
    import config.settings as cfg
    from datetime import datetime as _dt, timedelta as _td

    if "image" not in cfg.DOC_TYPE_LIST:
        check_true("config 에 image 가 있다(이 검사가 의미 있으려면)", False, cfg.DOC_TYPE_LIST)
        return

    tmp = tempfile.mkdtemp(prefix="qa_img_transition_")
    try:
        db = _fresh_db(tmp)
        future = (_dt.now() + _td(days=7)).strftime("%Y-%m-%d")
        court, case_no, item_no = "B0002", "2025타경777", "1"

        # --- 1단계: image 가 없던 시절의 큐를 재현한다 (3종, 전부 done) ---
        conn = db.get_connection()
        for t in ("spec", "status", "appraisal"):
            conn.execute(
                "INSERT INTO document_queue (court_code,case_no,item_no,doc_type,status,"
                "retry_count,auction_date,priority,last_attempt_at) VALUES (?,?,?,?,'done',0,?,0,NULL)",
                (court, case_no, item_no, t, future))
        conn.commit()
        before = {r["doc_type"]: r["status"] for r in conn.execute(
            "SELECT doc_type,status FROM document_queue")}
        conn.close()
        check("전제: 옛 큐는 3종뿐이고 전부 done", sorted(before), ["appraisal", "spec", "status"])
        check_true("전제: 전부 done", set(before.values()) == {"done"}, before)

        # --- 2단계: 크롤 재개 = enqueue_documents 가 4종으로 다시 적재한다 ---
        import contextlib, io as _io
        with contextlib.redirect_stdout(_io.StringIO()):
            db.enqueue_documents([{"court_code": court, "case_no": case_no,
                                   "item_no": item_no, "auction_date": future}])

        conn = db.get_connection()
        after = {r["doc_type"]: r["status"] for r in conn.execute(
            "SELECT doc_type,status FROM document_queue")}
        conn.close()
        print("    적재 후 큐:", after)
        check_true("★ image 행이 새로 생긴다", "image" in after, str(after))
        check("★ image 만 pending 이다", after.get("image"), "pending")
        for t in ("spec", "status", "appraisal"):
            check("★ 이미 받아 둔 %s 는 done 그대로다(되살아나지 않는다)" % t,
                  after.get(t), "done")

        # --- 3단계: 워커가 그 한 행을 어떻게 처리하는가 ---
        s = _run_worker(db)
        print("    이동 %d회 / 수집 %d회 / exit %s"
              % (len(s["navs"]), len(s["collects"]), s["exit"]))

        check("★ 이동은 **한 번**이다(묶음에 한 행뿐이다)", len(s["navs"]), 1)
        check("★ 그 이동은 **엄격**하다(image 단독이어도 정확 일치를 요구한다)",
              [bool(n[3]) for n in s["navs"]], [True])
        check("★ 수집한 것은 image 하나뿐이다(done 문서를 다시 받지 않는다)",
              [c[1] for c in s["collects"]], ["image"])

        conn = db.get_connection()
        final = {r["doc_type"]: r["status"] for r in conn.execute(
            "SELECT doc_type,status FROM document_queue")}
        conn.close()
        check("★ image 가 종결된다", final.get("image"), "done")
        check_true("★ 나머지 3종은 여전히 done(손대지 않았다)",
                   all(final.get(t) == "done" for t in ("spec", "status", "appraisal")),
                   final)

        # --- 4단계: 다시 적재해도 아무 일도 일어나지 않는다(멱등) ---
        with contextlib.redirect_stdout(_io.StringIO()):
            db.enqueue_documents([{"court_code": court, "case_no": case_no,
                                   "item_no": item_no, "auction_date": future}])
        conn = db.get_connection()
        again = {r["doc_type"]: r["status"] for r in conn.execute(
            "SELECT doc_type,status FROM document_queue")}
        n_rows = conn.execute("SELECT COUNT(*) c FROM document_queue").fetchone()["c"]
        conn.close()
        check("★ 재적재해도 행 수가 늘지 않는다(UNIQUE + OR IGNORE)", n_rows, 4)
        check_true("★ 재적재가 done 을 되살리지 않는다(헛수집을 만들지 않는다)",
                   all(v == "done" for v in again.values()), again)

        s2 = _run_worker(db)
        check("★ 재적재 후 워커가 할 일이 없다", len(s2["navs"]), 0)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

# ---------------------------------------------------------------------------
# 11-12. claim **경쟁에서 졌을 때** (2026-08-24 Sprint 254 신설)
#
# 전체 스위트 합산 커버리지에서 `storage/database.py` 의 미실행 41줄을 훑다가 두 곳을
# 찾았다. 둘 다 **동시 실행 워커가 있을 때만** 지나가는 자리고, 둘 다 미검증이었다.
#
#   claim_next_item_rows  형제 행을 경쟁자가 먼저 집어간 경우 (rowcount=0 -> continue)
#       -> 그 행을 묶음에서 빼야 한다. 안 빼면 두 워커가 같은 문서를 중복 수집한다
#          (법원 부하 2배 + 같은 다운로드 폴더를 동시에 만진다).
#
#   claim_next_queue_item  상한(CLAIM_RACE_MAX_ATTEMPTS)까지 매번 진 경우
#       -> None 을 돌려주되 **왜인지 경고를 남겨야** 한다.
#          이게 BUGS #130 이다: 예전에는 경쟁 한 번에 곧바로 None 을 돌려줬고,
#          호출부(`doc_worker.main`)가 그것을 "대기열 비어있음"으로 읽어 **그날 남은
#          큐를 통째로 다음 날로 미뤘다.** 로그에도 사실이 아닌 문장이 남았다.
#          Sprint 191 이 재조회 + 경고로 고쳤는데, 그 경고 경로가 미검증이었다.
#
# 경쟁 창은 SELECT 와 조건부 UPDATE 사이 수 마이크로초라 스레드로는 안정 재현이 안 된다.
# `test_race_conditions.py` 가 결제에 쓰는 방식(`_InterleavingConn`)을 그대로 가져온다 -
# UPDATE 를 대행하기 **직전에** 다른 커넥션으로 상태를 바꿔 rowcount=0 을 강제한다.
# 확률이 개입하지 않는다.
# ---------------------------------------------------------------------------
class _QueueInterleavingConn(object):
    """`UPDATE document_queue` 직전에 콜백을 실행하는 커넥션 래퍼.

    `once=True` 면 첫 UPDATE 에만 끼어든다(형제 행 시나리오).
    `once=False` 면 매번 끼어든다(재시도 상한 시나리오).
    """

    def __init__(self, conn, on_update, once=True):
        self._conn = conn
        self._on_update = on_update
        self._once = once
        self.fired = 0

    def execute(self, sql, *a, **kw):
        if sql.lstrip().upper().startswith("UPDATE DOCUMENT_QUEUE") \
                and (not self._once or self.fired == 0):
            self.fired += 1
            self._on_update()
        return self._conn.execute(sql, *a, **kw)

    def __getattr__(self, name):
        return getattr(self._conn, name)


def _patch_nth_connection(db, nth, on_update, once):
    """`get_connection()` 의 **n번째** 호출만 래퍼로 감싼다.

    n을 지정하는 이유: `claim_next_item_rows()` 는 커넥션을 두 번 연다 - 첫 번째는
    머리 행을 집는 `claim_next_queue_item()` 것이고, 형제 행 루프는 두 번째다.
    아무거나 감싸면 재현하려는 것과 다른 자리에 끼어든다.
    """
    real_get = db.get_connection
    state = {"n": 0, "wrapper": None}

    def fake_get(*a, **kw):
        state["n"] += 1
        conn = real_get(*a, **kw)
        if state["n"] == nth:
            state["wrapper"] = _QueueInterleavingConn(conn, on_update, once=once)
            return state["wrapper"]
        return conn

    db.get_connection = fake_get
    return real_get, state


def test_sibling_lost_to_a_competitor_is_dropped_from_the_batch():
    print("\n--- 11. 형제 행을 경쟁자가 먼저 집어가면 묶음에서 뺀다 (Sprint 254) ---")
    import config.settings as cfg

    tmp = tempfile.mkdtemp(prefix="qa_claim_sibling_")
    try:
        db = _fresh_db(tmp)
        types = list(cfg.DOC_TYPE_LIST)
        check_true("검사가 공허하지 않다(형제가 생기려면 문서 종류가 3개 이상)",
                   len(types) >= 3, types)
        # 물건 1개 x 전 종류 -> 머리 1행 + 형제 (len(types)-1) 행
        _seed(db, 1, types)

        real_get = db.get_connection      # 경쟁자는 **감싸지 않은** 커넥션을 쓴다
        stolen = {"row": None}

        def competitor():
            """형제 하나를 다른 실행이 먼저 집어간 것으로 만든다.

            형제 루프는 이미 SELECT 를 끝냈으므로, 여기서 훔친 행은 뒤쪽 반복에서
            rowcount=0 으로 걸린다 - 그게 재현하려는 그 분기다.

            ★ **중간** 형제를 훔친다(OFFSET 1). 마지막 형제를 훔치면 `continue` 와
              `return rows` 가 같은 결과를 내서 검사가 둘을 구별하지 못한다 - 그런데
              `return` 은 Sprint 191 이 고친 결함(경쟁 1회로 남은 행을 포기)의 재발이다.
              중간을 훔치면 뒤에 남은 형제가 집혔는지로 그것이 드러난다.
            """
            if stolen["row"]:
                return
            c2 = real_get()
            try:
                row = c2.execute(
                    "SELECT id, doc_type FROM document_queue WHERE status='pending'"
                    " ORDER BY id ASC LIMIT 1 OFFSET 1").fetchone()
                if row:
                    c2.execute("UPDATE document_queue SET status='in_progress' WHERE id=?",
                               (row["id"],))
                    c2.commit()
                    stolen["row"] = dict(row)
            finally:
                c2.close()

        # 2번째 커넥션 = 형제 루프. (1번째는 머리 행을 집는 claim_next_queue_item)
        real_get, state = _patch_nth_connection(db, 2, competitor, once=True)
        try:
            rows = db.claim_next_item_rows()
        finally:
            db.get_connection = real_get

        got = sorted(r["doc_type"] for r in rows)
        print("    경쟁자가 가져간 것: %s / 이 실행이 집은 것: %s"
              % (stolen["row"] and stolen["row"]["doc_type"], got))
        check_true("래퍼가 형제 루프의 UPDATE 를 실제로 가로챘다",
                   state["wrapper"] is not None and state["wrapper"].fired >= 1,
                   state["wrapper"] and state["wrapper"].fired)
        check_true("검사가 공허하지 않다(경쟁자가 실제로 한 행을 가져갔다)",
                   stolen["row"] is not None, stolen)
        check("★ 경쟁에서 진 형제는 묶음에 들어오지 않는다(중복 수집 방지)",
              stolen["row"]["doc_type"] in got, False)
        check("★ 나머지는 그대로 집힌다(형제 하나가 밀려도 묶음이 무너지지 않는다)",
              len(got), len(types) - 1)
        # ★ 밀린 형제 **뒤에 있던** 행까지 집혔는가. 여기서 멈추면(`continue` 대신
        #   `return`/`break`) 경쟁 1회가 남은 행을 포기하는 Sprint 191 결함이 되살아난다.
        conn = db.get_connection()
        try:
            after = [r["doc_type"] for r in conn.execute(
                "SELECT doc_type FROM document_queue WHERE id>? ORDER BY id",
                (stolen["row"]["id"],))]
        finally:
            conn.close()
        check_true("검사가 공허하지 않다(밀린 형제 뒤에 행이 남아 있다)",
                   len(after) >= 1, after)
        check("★ 밀린 형제 뒤의 행도 집는다(경쟁 1회로 묶음을 포기하지 않는다)",
              sorted(t for t in after if t in got), sorted(after))

        # 진 형제는 경쟁자의 상태(in_progress)로 남아야 한다 - 되돌려 놓으면 중복이 된다.
        conn = db.get_connection()
        try:
            left = conn.execute(
                "SELECT status FROM document_queue WHERE id=?",
                (stolen["row"]["id"],)).fetchone()["status"]
            unclaimed = conn.execute(
                "SELECT COUNT(*) c FROM document_queue WHERE status='pending'"
            ).fetchone()["c"]
        finally:
            conn.close()
        check("★ 경쟁자가 집은 행의 상태를 덮어쓰지 않는다", left, "in_progress")
        check("★ 집지 않은 채 pending 으로 남겨 둔 행이 없다", unclaimed, 0)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_claim_exhaustion_warns_instead_of_pretending_empty():
    """상한까지 매번 지면 None 을 돌려주되 **경고를 남긴다** (BUGS #130 회귀 방어).

    이 검사의 핵심은 반환값이 아니라 **로그**다. None 만 보면 호출부는 "큐가 비었다"로
    읽는다 - 그게 정확히 BUGS #130 이 만든 사고였다(그날 남은 큐를 통째로 미뤘고,
    로그에는 "대기열 비어있음"이라는 사실이 아닌 문장이 남았다).
    """
    print("\n--- 12. claim 재시도 상한: 비었다고 위장하지 않는다 (Sprint 254) ---")
    import logging as _logging
    import config.settings as cfg

    tmp = tempfile.mkdtemp(prefix="qa_claim_exhaust_")
    try:
        db = _fresh_db(tmp)
        limit = db.CLAIM_RACE_MAX_ATTEMPTS
        check_true("상한이 유한하다(무한 재시도면 이 검사가 끝나지 않는다)",
                   isinstance(limit, int) and 1 <= limit <= 100, limit)
        # 경쟁자가 매번 하나씩 가져가도 남아 있을 만큼 넉넉히 넣는다.
        _seed(db, limit + 3, list(cfg.DOC_TYPE_LIST)[:1])

        real_get = db.get_connection

        def competitor():
            """이 실행이 방금 SELECT 한 그 행을 먼저 가져간다 - 매번.

            제품의 SELECT 와 **같은 정렬**을 쓴다. 다른 행을 훔치면 경쟁이 아니라
            그냥 다른 작업이 되고, rowcount=0 분기에 닿지 않는다.
            """
            c2 = real_get()
            try:
                row = c2.execute(
                    "SELECT id FROM document_queue WHERE status='pending'"
                    " ORDER BY priority ASC, auction_date ASC LIMIT 1").fetchone()
                if row:
                    c2.execute("UPDATE document_queue SET status='in_progress' WHERE id=?",
                               (row["id"],))
                    c2.commit()
            finally:
                c2.close()

        captured = []

        class _Capture(_logging.Handler):
            def emit(self, record):
                # ★ 레벨도 같이 담는다. debug 로 낮추면 운영 로그에는 안 나오는데
                #   메시지만 보는 검사는 그것을 통과시킨다.
                captured.append((record.levelno, record.getMessage()))

        handler = _Capture()
        db_logger = _logging.getLogger("storage.database")
        prev_level = db_logger.level
        db_logger.setLevel(_logging.DEBUG)
        db_logger.addHandler(handler)
        # 1번째 커넥션 = claim_next_queue_item 이 상한까지 재사용하는 그 커넥션.
        real_get, state = _patch_nth_connection(db, 1, competitor, once=False)
        try:
            got = db.claim_next_queue_item()
        finally:
            db.get_connection = real_get
            db_logger.removeHandler(handler)
            db_logger.setLevel(prev_level)

        fired = state["wrapper"] and state["wrapper"].fired
        print("    반환값: %r / 가로챈 UPDATE 수: %s (상한 %s)" % (got, fired, limit))
        check("★ 상한만큼만 시도한다(무한 루프가 아니다)", fired, limit)
        check("★ 상한까지 지면 None 을 돌려준다", got, None)
        exhausted = [(lv, m) for lv, m in captured
                     if "밀렸" in m and "%d회" % limit in m]
        check_true("★ 상한 소진을 로그에 남긴다 - '비었다'와 구별된다 (BUGS #130)",
                   len(exhausted) >= 1, "-> 잡힌 로그 %r" % (captured[-3:],))
        check_true("★ 그것이 WARNING 이상이다(debug 는 운영에서 안 보인다)",
                   any(lv >= _logging.WARNING for lv, _m in exhausted),
                   "-> %r" % (exhausted[:2],))
        check_true("★ 경고가 '큐가 빈 것이 아니다'를 명시한다",
                   any("빈 것이 아니다" in m for _lv, m in exhausted),
                   "-> %r" % (exhausted[:2],))

        # 큐에는 아직 행이 남아 있다 - "비었다"가 사실이 아님을 데이터로도 확인한다.
        conn = db.get_connection()
        try:
            left = conn.execute(
                "SELECT COUNT(*) c FROM document_queue WHERE status='pending'").fetchone()["c"]
        finally:
            conn.close()
        check("★ 실제로는 큐에 대기 행이 남아 있다(None 이 '비었다'는 뜻이 아니다)",
              left, 3)

        # 그리고 다음 실행은 정상적으로 집어 온다 - 상한에 걸린 것이 상태를 오염시키지 않았다.
        again = db.claim_next_queue_item()
        check_true("★ 경쟁이 사라지면 곧바로 다시 집어 온다(영구 손상이 아니다)",
                   again is not None, again)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_losing_one_race_still_claims_another_row():
    """★ BUGS #130 의 본문: **한 번 밀렸다고 빈손으로 돌아오지 않는다.**

    검사 12는 상한까지 매번 지는 극단을 본다. 그런데 그 검사는 기대값을
    `CLAIM_RACE_MAX_ATTEMPTS` 에서 끌어오기 때문에, 그 상수를 1로 낮추는 변경을
    통과시킨다(mutation R4 로 확인, 2026-08-24). 상한이 1이면 재조회는 사라지고
    경쟁 1회가 곧바로 None 이 된다 - 정확히 Sprint 191 이 고친 그 결함이다.

    그래서 여기서는 상수를 보지 않는다. **경쟁자가 한 번만 이기는** 상황을 만들고,
    이 실행이 다른 행을 집어 오는지만 본다. 상수가 2든 5든 참이어야 하는 문장이다.
    """
    print("\n--- 13. 한 번 밀려도 다른 행을 집는다 (Sprint 254, BUGS #130) ---")
    import config.settings as cfg

    tmp = tempfile.mkdtemp(prefix="qa_claim_once_")
    try:
        db = _fresh_db(tmp)
        _seed(db, 2, list(cfg.DOC_TYPE_LIST)[:1])   # 서로 다른 물건 2행

        real_get = db.get_connection
        stolen = {"id": None}

        def competitor():
            """제품이 방금 고른 그 행을 **한 번만** 가로챈다."""
            c2 = real_get()
            try:
                row = c2.execute(
                    "SELECT id FROM document_queue WHERE status='pending'"
                    " ORDER BY priority ASC, auction_date ASC LIMIT 1").fetchone()
                c2.execute("UPDATE document_queue SET status='in_progress' WHERE id=?",
                           (row["id"],))
                c2.commit()
                stolen["id"] = row["id"]
            finally:
                c2.close()

        real_get, state = _patch_nth_connection(db, 1, competitor, once=True)
        try:
            got = db.claim_next_queue_item()
        finally:
            db.get_connection = real_get

        print("    경쟁자가 가져간 id: %s / 이 실행이 집은 것: %s"
              % (stolen["id"], got and got["id"]))
        check_true("검사가 공허하지 않다(경쟁자가 실제로 한 행을 가져갔다)",
                   stolen["id"] is not None, stolen)
        check_true("★ 한 번 밀렸다고 빈손으로 돌아오지 않는다(그날 큐를 미루지 않는다)",
                   got is not None,
                   "-> None 을 받았다. 호출부는 이것을 '대기열 비어있음'으로 읽는다")
        check("★ 경쟁자가 가져간 행이 아니라 다른 행을 집는다",
              got and got["id"] != stolen["id"], True)
        check("★ 집은 행은 진행 상태다", got and got["status"], "in_progress")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# 14-15. **회수당한 뒤 뒤늦게 끝난 실행**(좀비 워커) — 2026-08-24 Sprint 254, BUGS #181
#
# 위 11-13 이 "집을 때"의 경쟁을 본다면, 여기는 "끝낼 때"의 경쟁이다.
#
#   `reset_stale_queue()` 는 10분 넘게 in_progress 인 행을 회수한다.
#   `doc_worker` 의 락은 5시간(LOCK_STALE_HOURS)이 지나면 죽은 것으로 보고 넘어간다.
#   -> 오래 도는 실행 A 가 있고 그 사이 B 가 시작하면, B 는 A 가 붙들고 있던 행을
#      회수해 자기 것으로 만든다. 그 뒤 A 가 종결을 부른다.
#
# 종결 함수는 `WHERE id=?` 만 걸었기 때문에 **그 행이 아직 자기 것인지 몰랐다.**
# 상태로는 구별할 수 없다 — 회수 후 다시 집힌 행도 똑같이 'in_progress' 다.
# 그래서 claim 시점의 `last_attempt_at` 을 토큰으로 돌려주고, 종결할 때 다시 건다.
# 스키마는 바꾸지 않는다(이미 있는 컬럼이다).
# ---------------------------------------------------------------------------
class _CapturedLogs(object):
    """`storage.database` 로거를 잠깐 가로챈다.

    이 fixture 에는 `auction_item` 이 없어 `document_status` 테이블로는 "문서 기록을
    시도했는가"를 볼 수 없다(대상이 없어 갱신이 생략된다). 그 생략 자체가 로그로
    남으므로, **로그로 경로를 확인한다** — 확인하려는 것은 값이 아니라 "거기까지
    갔는가"이기 때문이다.
    """

    def __init__(self):
        import logging
        self.messages = []
        self._logging = logging
        outer = self

        class _H(logging.Handler):
            def emit(self, record):
                outer.messages.append(record.getMessage())

        self._handler = _H()
        self._logger = logging.getLogger("storage.database")

    def __enter__(self):
        self._prev = self._logger.level
        self._logger.setLevel(self._logging.DEBUG)
        self._logger.addHandler(self._handler)
        return self

    def __exit__(self, *a):
        self._logger.removeHandler(self._handler)
        self._logger.setLevel(self._prev)
        return False

    def has(self, needle):
        return any(needle in m for m in self.messages)


def _steal_by_stale_recovery(db, queue_id):
    """A 가 집은 행을 stale 회수로 빼앗아 B 가 다시 집게 만든다. B 의 item 을 돌려준다."""
    import contextlib
    conn = db.get_connection()
    try:
        conn.execute("UPDATE document_queue SET last_attempt_at=? WHERE id=?",
                     ((datetime.now() - timedelta(minutes=30)).isoformat(), queue_id))
        conn.commit()
    finally:
        conn.close()
    with contextlib.redirect_stdout(io.StringIO()):
        db.reset_stale_queue()
    return db.claim_next_queue_item()


def test_late_success_does_not_steal_a_reclaimed_row():
    print("\n--- 14. 회수당한 뒤의 늦은 성공이 남의 행을 종결하지 않는다 (Sprint 254) ---")
    import config.settings as cfg

    tmp = tempfile.mkdtemp(prefix="qa_zombie_done_")
    try:
        db = _fresh_db(tmp)
        _seed(db, 1, list(cfg.DOC_TYPE_LIST)[:1])
        a = db.claim_next_queue_item()
        check_true("claim 이 토큰을 돌려준다(없으면 소유권을 확인할 수 없다)",
                   bool(a.get("claim_token")), a)

        b = _steal_by_stale_recovery(db, a["id"])
        check_true("설정: 회수 뒤 다른 실행이 같은 행을 집었다",
                   b is not None and b["id"] == a["id"], b)
        check_true("설정: 두 claim 의 토큰이 다르다(상태로는 구별되지 않는다)",
                   a["claim_token"] != b["claim_token"],
                   (a["claim_token"], b["claim_token"]))

        # A 가 이제야 성공으로 끝난다.
        with _CapturedLogs() as logs:
            db.mark_queue_done(a["id"], a["court_code"], a["case_no"], a["item_no"],
                               a["doc_type"], None, "hash-A", files_saved=[],
                               claim_token=a["claim_token"])

        conn = db.get_connection()
        try:
            row = dict(conn.execute(
                "SELECT status, last_attempt_at FROM document_queue WHERE id=?",
                (a["id"],)).fetchone())
        finally:
            conn.close()

        check("★ 남의 claim 을 done 으로 덮지 않는다", row["status"], "in_progress")
        check("★ 남의 claim 토큰을 건드리지 않는다", row["last_attempt_at"], b["claim_token"])
        check_true("★ 왜 종결하지 않았는지 로그에 남긴다(조용히 넘기지 않는다)",
                   logs.has("회수돼 다른 실행이 집어갔다"), logs.messages[-3:])
        # ★ 그래도 **문서 기록 경로는 계속 간다** — 파일은 실제로 받아졌기 때문이다.
        #   이 fixture 에는 auction_item 이 없어 갱신은 생략되지만, 그 생략 로그가
        #   "거기까지 갔다"는 증거다. 조기 return 으로 바뀌면 이 로그가 사라진다.
        check_true("★ 받은 문서를 기록하는 경로는 그대로 탄다",
                   logs.has("document_status 갱신 대상 없음"), logs.messages)

        # 대조군: 회수가 없었다면 같은 호출이 정상으로 종결한다(검사가 공허하지 않다).
        c = db.claim_next_queue_item()
        check_true("설정: 대조군을 위해 다시 집었다", c is None or c["id"] == a["id"], c)
        if c is None:
            conn = db.get_connection()
            try:
                conn.execute("UPDATE document_queue SET status='pending',"
                             " last_attempt_at=NULL WHERE id=?", (a["id"],))
                conn.commit()
            finally:
                conn.close()
            c = db.claim_next_queue_item()
        db.mark_queue_done(c["id"], c["court_code"], c["case_no"], c["item_no"],
                           c["doc_type"], None, "hash-C", files_saved=[],
                           claim_token=c["claim_token"])
        conn = db.get_connection()
        try:
            final = conn.execute("SELECT status FROM document_queue WHERE id=?",
                                 (a["id"],)).fetchone()["status"]
        finally:
            conn.close()
        check("대조군: 자기 claim 이면 정상 종결한다", final, "done")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_late_failure_does_not_burn_someone_elses_retry_budget():
    """늦은 실패는 **아무것도 쓰지 않는다** — 성공 쪽과 규칙이 다른 이유가 있다.

    회수 뒤 다시 집힌 행을 실패로 처리하면 세 가지가 한꺼번에 망가진다:
      - 지금 받고 있는 실행의 claim 이 'pending' 으로 풀려 제3의 실행이 또 집는다
      - 그 실행의 몫이 아닌 `retry_count` 가 깎인다(예산 3회는 행의 것이다)
      - 그쪽이 성공할 문서가 잠깐 화면에서 '수집실패' 로 보인다
    """
    print("\n--- 15. 회수당한 뒤의 늦은 실패가 남의 예산을 깎지 않는다 (Sprint 254) ---")
    import config.settings as cfg

    tmp = tempfile.mkdtemp(prefix="qa_zombie_fail_")
    try:
        db = _fresh_db(tmp)
        _seed(db, 1, list(cfg.DOC_TYPE_LIST)[:1])
        a = db.claim_next_queue_item()
        b = _steal_by_stale_recovery(db, a["id"])
        check_true("설정: 회수 뒤 다른 실행이 같은 행을 집었다",
                   b is not None and b["id"] == a["id"], b)

        with _CapturedLogs() as logs:
            db.mark_queue_failed(a["id"], a["retry_count"], a["claim_token"])

        conn = db.get_connection()
        try:
            row = dict(conn.execute(
                "SELECT status, retry_count, last_attempt_at FROM document_queue"
                " WHERE id=?", (a["id"],)).fetchone())
        finally:
            conn.close()

        check("★ 남이 받고 있는 행을 대기로 풀지 않는다", row["status"], "in_progress")
        check("★ 남의 재시도 예산을 깎지 않는다", row["retry_count"], 0)
        check("★ 남의 claim 토큰을 건드리지 않는다", row["last_attempt_at"], b["claim_token"])
        check_true("★ 왜 건너뛰었는지 로그에 남긴다", logs.has("실패 처리를 건너뛴다"),
                   logs.messages[-3:])
        # ★ 성공 쪽과 규칙이 다르다: 여기서는 **아무것도 쓰지 않는다.** 그쪽이 성공할
        #   문서를 실패로 표시하면 안 되기 때문이다. 문서 기록 경로에 닿지 않아야 한다.
        check_true("★ 문서 상태에 손대지 않는다(그쪽이 성공할 수 있다)",
                   not logs.has("document_status"), logs.messages)

        # 대조군: 자기 claim 이면 예전 그대로 실패 처리한다.
        db.mark_queue_failed(b["id"], b["retry_count"], b["claim_token"])
        conn = db.get_connection()
        try:
            after = dict(conn.execute(
                "SELECT status, retry_count FROM document_queue WHERE id=?",
                (a["id"],)).fetchone())
        finally:
            conn.close()
        check("대조군: 자기 claim 이면 재시도 대기로 돌린다",
              (after["status"], after["retry_count"]), ("pending", 1))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_worker_passes_the_claim_token_to_both_terminations():
    """★ 워커가 종결에 claim 토큰을 넘긴다 (Sprint 254, BUGS #181 배선 확인).

    제품의 방어가 아무리 옳아도 호출부가 토큰을 안 넘기면 그 방어는 꺼져 있는 것과
    같다(`claim_token=None` 이면 예전 동작으로 되돌아간다). 그래서 **실제**
    `doc_worker.main()` 을 돌려 넘어간 값을 본다.
    """
    print("\n--- 16. 워커가 종결에 claim 토큰을 넘긴다 (Sprint 254) ---")
    import config.settings as cfg

    tmp = tempfile.mkdtemp(prefix="qa_token_wiring_")
    try:
        db = _fresh_db(tmp)
        types = list(cfg.DOC_TYPE_LIST)
        _seed(db, 2, types)

        # 한 종류는 실패시켜 **두 종결 경로**를 다 태운다.
        fail_type = types[0]

        def collect_result(case_no, doc_type):
            if doc_type == fail_type:
                return {"success": False}
            return None

        stats = _run_worker(db, collect_result=collect_result)

        check_true("검사가 공허하지 않다(성공 종결이 실제로 일어났다)",
                   len(stats["done"]) >= 1, stats["done"])
        check_true("검사가 공허하지 않다(실패 종결도 실제로 일어났다)",
                   len(stats["failed"]) >= 1, stats["failed"])

        def token_of(call, kw_name, pos):
            args, kwargs = call
            if kw_name in kwargs:
                return kwargs[kw_name]
            return args[pos] if len(args) > pos else None

        done_tokens = [token_of(c, "claim_token", 8) for c in stats["done"]]
        failed_tokens = [token_of(c, "claim_token", 2) for c in stats["failed"]]
        print("    성공 종결 %d회 / 실패 종결 %d회" % (len(done_tokens), len(failed_tokens)))

        check("★ 성공 종결에 토큰 없이 부른 호출이 없다",
              [t for t in done_tokens if not t], [])
        check("★ 실패 종결에 토큰 없이 부른 호출이 없다",
              [t for t in failed_tokens if not t], [])

        # 토큰이 **그 행의 claim 값**인가 — 아무 문자열이나 넘기고 있지 않은지 본다.
        conn = db.get_connection()
        try:
            seen = {r["last_attempt_at"] for r in conn.execute(
                "SELECT last_attempt_at FROM document_queue")}
        finally:
            conn.close()
        # 성공 종결한 행은 last_attempt_at 이 claim 값 그대로 남아 있다(종결이 안 바꾼다).
        check("★ 성공 종결의 토큰이 실제 claim 값이다",
              [t for t in done_tokens if t not in seen], [])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    test_batching_reduces_navigations()
    test_image_still_requires_exact_item()
    test_image_failure_does_not_take_documents_down()
    test_partial_failure_is_per_row()
    test_refresh_intent_is_per_row()
    test_no_row_is_left_claimed()
    test_driver_restart_invalidates_page_memory()
    test_claim_groups_one_item_only()
    test_claim_keeps_retry_interval_for_siblings()
    test_terminated_row_does_not_take_the_batch_down()
    test_time_check_happens_per_row_not_per_batch()
    test_window_end_leaves_margin_before_crawl()
    test_reuse_verifies_the_page_before_trusting_it()
    test_image_row_added_later_to_an_already_done_item()
    test_sibling_lost_to_a_competitor_is_dropped_from_the_batch()
    test_claim_exhaustion_warns_instead_of_pretending_empty()
    test_losing_one_race_still_claims_another_row()
    test_late_success_does_not_steal_a_reclaimed_row()
    test_late_failure_does_not_burn_someone_elses_retry_budget()
    test_worker_passes_the_claim_token_to_both_terminations()

    print("\n" + "=" * 55)
    if FAILS:
        print("FAILED (%d/%d): %s" % (len(FAILS), CHECKS[0], ", ".join(FAILS)))
        return 1
    print("ALL BATCHING TESTS PASSED (%d checks)" % CHECKS[0])
    return 0


if __name__ == "__main__":
    sys.exit(main())
