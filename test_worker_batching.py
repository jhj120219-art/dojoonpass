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
    path = os.path.join(tmp, "auction.db")
    os.environ["AUCTION_DB_PATH"] = path
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


def _queue_rows(db):
    conn = db.get_connection()
    rows = [dict(r) for r in conn.execute(
        "SELECT id, case_no, doc_type, status, retry_count FROM document_queue"
        " ORDER BY case_no, doc_type")]
    conn.close()
    return rows


def _run_worker(db, *, legacy=False, collect_result=None, exact_nav_ok=True):
    """진짜 `doc_worker.main()` 을 돌린다. 브라우저/수집기만 가짜.

    legacy=True 면 claim 을 **행 하나씩**으로 되돌려 예전 구조를 재현한다
    (전/후를 같은 fixture, 같은 계측으로 비교하기 위해서다).
    """
    import doc_worker as dw

    stats = {"navs": [], "collects": [], "reused": 0}

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
        "wait_for_detail": lambda driver, case_no: True,
        "get_doc_button_id": lambda doc_type, item_no: "qa-btn",
        "collect_document": fake_collect,
        "mark_queue_done": db.mark_queue_done,
        "mark_queue_failed": db.mark_queue_failed,
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

    print("\n" + "=" * 55)
    if FAILS:
        print("FAILED (%d/%d): %s" % (len(FAILS), CHECKS[0], ", ".join(FAILS)))
        return 1
    print("ALL BATCHING TESTS PASSED (%d checks)" % CHECKS[0])
    return 0


if __name__ == "__main__":
    sys.exit(main())
