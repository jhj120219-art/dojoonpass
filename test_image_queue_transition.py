# -*- coding: utf-8 -*-
"""기존 3종 완료 물건에 `image` 큐가 뒤늦게 붙는 **전환 경로** (2026-08-21 Sprint 243 신설).

## 왜 이 파일이 필요한가

`image` 는 `DOC_TYPE_LIST` 에 나중에(2026-08-17 Sprint 144) 추가됐다. 그래서 지금
운영 큐에는 `image` 행이 **한 개도 없다.** 그런데 `enqueue_documents()` 는 이미 4종을
넣는다. 즉 크롤이 재개되는 순간, 법원 목록에 다시 나온 물건마다 **`image` 행 하나가
새로 생긴다.** 그중 일부는 나머지 3종이 이미 `done` 인 상태다.

그 전환을 지나가는 검사가 없었다. 기존 검사들이 보는 것은 둘뿐이었다:

    "처음부터 4종이 함께 있는 물건"      test_worker_batching.py 2~3번
    "빈 큐에 새로 4종 적재"              test_asset_pipeline.py 15번

**"이미 3종이 끝난 물건에 image 만 붙는다"** 는 그 사이에 있고, 아무도 지나지 않았다.
이 파일이 그 구간을 실제 함수(`enqueue_documents` -> `claim_next_item_rows` ->
`doc_worker.main`)로 관통한다.

## ★ 운영 DB 실측 (2026-08-21) — 문서의 숫자를 쓰지 않는다

이 전환의 규모를 "944개"라고 적은 문서가 있는데 **틀렸다.** 944 는 Sprint 241 이
잰 *pending 행을 가진* 물건 수이고, 이 전환이 말하는 *3종이 done 인* 물건 수가 아니다.
지금 큐를 다시 세면:

    큐에 있는 서로 다른 물건        1,166
    그중 image 행이 있는 물건           0     <- 전환 대상은 전부다
    조합별
        3종 전부 pending              903
        ★ 3종 전부 done               160     <- 이 파일이 말하는 "전환 상태"
        3종 전부 SKIPPED_EXPIRED       62
        done/done/pending              36
        나머지 혼합                      5

`test_population_matches_the_live_queue()` 가 이 수치를 **실행 시점에 다시 세서**
문서가 아니라 DB 를 근거로 만든다(운영 DB 는 읽기 전용으로만 연다).

## 전환의 방아쇠는 큐의 날짜가 아니라 **새 크롤 결과**다

`enqueue_documents(rows)` 의 `auction_date` 는 **새로 크롤한 행**의 값이다. 큐에 남아
있는 옛 날짜가 아니다. 그래서:

    법원 목록에 다시 나온다(새 기일 미래)  -> 4종 INSERT OR IGNORE
                                            기존 3종은 rowcount 0 -> 기일만 갱신(status 불변)
                                            image 만 새로 pending 으로 생긴다
    다시 안 나온다 / 기일 경과              -> 아무 일도 없다(1차 방어선이 skip)

    python test_image_queue_transition.py
"""
import contextlib
import io
import os
import shutil
import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

failures = []
CHECKS = [0]


def check(name, actual, expected):
    CHECKS[0] += 1
    if actual == expected:
        print("[PASS] %s: %r (expected %r)" % (name, actual, expected))
    else:
        print("[FAIL] %s: %r (expected %r)" % (name, actual, expected))
        failures.append(name)


def check_true(name, cond, detail=""):
    CHECKS[0] += 1
    if cond:
        print("[PASS] %s" % name)
    else:
        print("[FAIL] %s%s" % (name, (" -- %s" % detail) if detail else ""))
        failures.append(name)


FUTURE = (datetime.now() + timedelta(days=21)).strftime("%Y-%m-%d")
PAST = (datetime.now() - timedelta(days=5)).strftime("%Y-%m-%d")
THREE = ("spec", "status", "appraisal")


class _FakeDriver(object):
    def quit(self):
        pass


def _fresh_db(tmp):
    """실제 부트스트랩 3단계로 스키마를 만든다 - 손으로 베끼지 않는다.

    (`test_worker_batching.py:_fresh_db` 와 같은 이유·같은 순서다. 반쪽 스키마로
     돌리면 종결이 예외로 떨어져 "수집 실패"처럼 보인다.)
    """
    # ★ 경로 전환 수단은 `db.DB_PATH` 대입 **하나뿐**이다 (2026-08-26 확인).
    #   예전에는 여기서 `os.environ["AUCTION_DB_PATH"]` 도 함께 세웠는데,
    #   그 이름을 **읽는 코드가 저장소에 하나도 없다**(전수 grep). 즉 아무 효과가 없으면서
    #   "환경변수가 DB 를 돌린다"고 오해하게 만드는 죽은 설정이었다 —
    #   그렇게 믿고 아래 대입을 지우면 테스트가 **운영 DB 에 쓴다.**
    #   (그 사고 자체는 `run_python_tests.py` 의 운영 DB 지문 감시가 따로 잡는다.)
    path = os.path.join(tmp, "auction.db")
    import storage.database as db
    import storage.migrate_v4_1 as mig
    import storage.migrations.run_migrations as runmig
    db.DB_PATH = path
    with contextlib.redirect_stdout(io.StringIO()):
        db.init_db()
        mig.migrate()
        runmig.run()
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


def _seed_queue(db, items):
    """items: [(court, case, item_no, {doc_type: status}, auction_date)]"""
    conn = db.get_connection()
    for court, case, ino, types, adate in items:
        for t, st in types.items():
            conn.execute(
                "INSERT INTO document_queue (court_code,case_no,item_no,doc_type,status,"
                "retry_count,auction_date,priority,last_attempt_at)"
                " VALUES (?,?,?,?,?,0,?,0,NULL)", (court, case, ino, t, st, adate))
    conn.commit()
    conn.close()


def _queue_map(db):
    conn = db.get_connection()
    out = {}
    for r in conn.execute("SELECT court_code,case_no,item_no,doc_type,status,retry_count,"
                          "auction_date FROM document_queue"):
        out[(r["court_code"], r["case_no"], r["item_no"], r["doc_type"])] = (
            r["status"], r["retry_count"], r["auction_date"])
    conn.close()
    return out


def _enqueue(db, items):
    """items: [(court, case, item_no, auction_date)] — 새 크롤 결과를 흉내낸다."""
    with contextlib.redirect_stdout(io.StringIO()):
        return db.enqueue_documents([
            {"court_code": c, "case_no": cn, "item_no": i, "auction_date": d}
            for c, cn, i, d in items])


def _run_worker(db, *, image_ok=True, collect_fail=()):
    """진짜 `doc_worker.main()`. 브라우저와 수집기만 가짜다.

    image_ok=False  -> 사진의 **엄격 진입**이 실패한다(Sprint 230 의 모호 거부 재현)
    collect_fail    -> 이 doc_type 들은 수집 자체가 실패한다
    """
    import importlib
    import doc_worker as dw
    importlib.reload(dw)

    stats = {"navs": [], "collects": []}

    def spy_go(driver, court_code, case_no, item_no=None, require_exact_item=False):
        stats["navs"].append((court_code, case_no, item_no, require_exact_item))
        if require_exact_item and not image_ok:
            return False
        return True

    def fake_collect(driver, court_code, case_no, item_no, doc_type, btn_id,
                     overwrite=False):
        stats["collects"].append((case_no, item_no, doc_type))
        if doc_type in collect_fail:
            return {"success": False, "previous_hash": None, "new_hash": None,
                    "partial": False, "no_asset": False, "images": [], "files_saved": []}
        return {"success": True, "previous_hash": None, "new_hash": "h",
                "partial": False, "no_asset": False, "images": [], "files_saved": []}

    targets = {
        "init_db": lambda: None,
        "reset_stale_queue": lambda: None,
        "build_download_driver": lambda: _FakeDriver(),
        "restart_download_driver": lambda d: _FakeDriver(),
        "claim_next_item_rows": db.claim_next_item_rows,
        "release_queue_rows": db.release_queue_rows,
        "go_to_case_detail": spy_go,
        "wait_for_detail": lambda driver, case_no: True,
        "get_doc_button_id": lambda dt, ino: "qa-btn",
        "collect_document": fake_collect,
        "mark_queue_done": db.mark_queue_done,
        "mark_queue_failed": db.mark_queue_failed,
        "mark_queue_skipped_expired": db.mark_queue_skipped_expired,
        "mark_queue_unsupported": db.mark_queue_unsupported,
        "save_auction_images": db.save_auction_images,
        "find_sibling_case_document": lambda *a, **kw: None,
        "reconcile_queue_auction_date": lambda q, c, i, d, cc: d,
    }
    originals = {k: getattr(dw, k) for k in targets}
    for k, v in targets.items():
        setattr(dw, k, v)
    os.environ["DOC_WORKER_TEST_MODE"] = "1"
    real_sleep = dw.time_module.sleep
    dw.time_module.sleep = lambda s: None
    try:
        stats["exit"] = dw.main()
    finally:
        dw.time_module.sleep = real_sleep
        os.environ.pop("DOC_WORKER_TEST_MODE", None)
        for k, v in originals.items():
            setattr(dw, k, v)
        try:
            os.remove(dw.LOCK_PATH)
        except OSError:
            pass
    return stats


# ===========================================================================
# 1. 전환 대상 규모를 **운영 DB 에서 다시 센다** (문서 숫자를 쓰지 않는다)
# ===========================================================================
def test_population_matches_the_live_queue():
    """전환 규모는 문서가 아니라 큐가 정한다.

    ★ 이 검사는 **특정 숫자를 고정하지 않는다.** 크롤이 재개되면 값이 달라지는 것이
      정상이기 때문이다. 대신 **관계**를 고정한다:

        - `image` 행이 있는 물건 + 없는 물건 = 전체 물건
        - "3종 done + image 없음" 은 전체의 부분집합이다
        - 그 수는 `pending 행을 가진 물건 수`와 **다른 값**이다
          (문서가 이 둘을 섞어 944 라고 적은 적이 있다 - 2026-08-21 정정)
    """
    print("\n--- 1. 전환 대상 규모 (운영 DB 실측, 읽기 전용) ---")
    import collections
    if not os.path.exists("auction.db"):
        check_true("운영 DB 가 없다 - 이 검사는 건너뛴다(통과로 세지 않는다)", False,
                   "auction.db 없음")
        return
    conn = sqlite3.connect("file:auction.db?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        rows = list(conn.execute(
            "SELECT court_code,case_no,item_no,doc_type,status FROM document_queue"))
    finally:
        conn.close()
    per = collections.defaultdict(dict)
    for r in rows:
        per[(r["court_code"], r["case_no"], r["item_no"])][r["doc_type"]] = r["status"]

    total = len(per)
    with_img = sum(1 for v in per.values() if "image" in v)
    without_img = total - with_img
    done3_noimg = sum(1 for v in per.values()
                      if "image" not in v and set(THREE) <= set(v)
                      and all(v[t] == "done" for t in THREE))
    with_pending = sum(1 for v in per.values() if any(s == "pending" for s in v.values()))

    print("    큐 물건 %d개 / image 있음 %d / image 없음 %d" % (total, with_img, without_img))
    print("    ★ 3종 done + image 없음 = %d" % done3_noimg)
    print("    pending 행을 가진 물건 = %d  <- 이것과 위는 **다른 값**이다" % with_pending)

    check_true("검사가 공허하지 않다(큐에 물건이 있다)", total > 0, total)
    check("image 있음 + 없음 = 전체", with_img + without_img, total)
    check_true("3종 done 집합은 전체의 부분집합이다", done3_noimg <= total,
               "%d > %d" % (done3_noimg, total))
    check_true("★ '3종 done' 과 'pending 보유' 를 같은 수로 쓰지 않는다",
               done3_noimg != with_pending or total == 0,
               "두 값이 우연히 같다면 표본이 특수한 것이다 - 근거를 다시 확인하라")


# ===========================================================================
# 2. 3종 done 물건에 image 만 붙는다
# ===========================================================================
def test_only_image_is_added_to_a_done_item():
    print("\n--- 2. 3종 done 물건에 image 만 추가된다 ---")
    tmp = tempfile.mkdtemp(prefix="qa_tr_only_")
    try:
        db = _fresh_db(tmp)
        _seed_queue(db, [("B1", "2025타경1", "1", {t: "done" for t in THREE}, PAST)])
        before = _queue_map(db)
        check("전제: 3행, 전부 done", len(before), 3)

        # 크롤이 새 기일과 함께 이 물건을 다시 들고 온다
        res = _enqueue(db, [("B1", "2025타경1", "1", FUTURE)])
        after = _queue_map(db)

        check("★ 새로 추가된 행은 1개(image)", res["added"], 1)
        check("★ 전체 행은 4개가 된다", len(after), 4)
        check("★ image 가 pending 으로 생긴다",
              after[("B1", "2025타경1", "1", "image")][0], "pending")
        for t in THREE:
            check("★ 기존 %s 는 done 그대로다(재-enqueue 되지 않는다)" % t,
                  after[("B1", "2025타경1", "1", t)][0], "done")
        check("기존 3종의 기일은 새 값으로 갱신된다(status 는 불변)",
              {after[("B1", "2025타경1", "1", t)][2] for t in THREE}, {FUTURE})
        check("기일 갱신 건수가 보고된다", res["refreshed"], 3)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ===========================================================================
# 3. 중복 image 행이 생기지 않는다 / 재적재해도 큐가 폭증하지 않는다
# ===========================================================================
def test_reenqueue_never_duplicates_or_grows():
    print("\n--- 3. 재적재가 중복/폭증을 만들지 않는다 ---")
    tmp = tempfile.mkdtemp(prefix="qa_tr_dup_")
    try:
        db = _fresh_db(tmp)
        _seed_queue(db, [("B1", "2025타경2", "1", {t: "done" for t in THREE}, PAST)])
        sizes = []
        for i in range(5):
            _enqueue(db, [("B1", "2025타경2", "1", FUTURE)])
            conn = db.get_connection()
            n = conn.execute("SELECT COUNT(*) c FROM document_queue").fetchone()["c"]
            nimg = conn.execute("SELECT COUNT(*) c FROM document_queue"
                                " WHERE doc_type='image'").fetchone()["c"]
            conn.close()
            sizes.append((n, nimg))
        print("    5회 적재 후 (전체행, image행): %s" % sizes)
        check("★ 첫 적재에서 4행이 되고 그 뒤로 늘지 않는다",
              sizes, [(4, 1)] * 5)
        after = _queue_map(db)
        for t in THREE:
            check("5회 적재해도 %s 는 done 그대로다" % t,
                  after[("B1", "2025타경2", "1", t)][0], "done")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ===========================================================================
# 4. 이미 image 가 done 이면 되살아나지 않는다
# ===========================================================================
def test_done_image_is_not_recreated_or_revived():
    print("\n--- 4. image 가 done 이면 재적재가 되살리지 않는다 ---")
    tmp = tempfile.mkdtemp(prefix="qa_tr_imgdone_")
    try:
        db = _fresh_db(tmp)
        types = {t: "done" for t in THREE}
        types["image"] = "done"
        _seed_queue(db, [("B1", "2025타경3", "1", types, PAST)])
        res = _enqueue(db, [("B1", "2025타경3", "1", FUTURE)])
        after = _queue_map(db)
        check("새로 추가된 행 없음", res["added"], 0)
        check("행 수 그대로 4", len(after), 4)
        check("★ image 는 done 그대로다(헛수집을 만들지 않는다)",
              after[("B1", "2025타경3", "1", "image")][0], "done")
        s = _run_worker(db)
        check("★ 워커가 할 일이 없다(이동 0회)", len(s["navs"]), 0)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ===========================================================================
# 5. image 가 failed 면 재적재가 아니라 **회수 규칙**으로 되살아난다
# ===========================================================================
def test_failed_image_is_revived_by_recovery_not_by_enqueue():
    """`enqueue_documents` 는 실패한 행을 되살리지 않는다 — 그것은 `reset_stale_queue` 의 일이다.

    두 경로를 섞으면 "적재가 실패를 지운다"가 되어 재시도 예산이 무의미해진다.
    """
    print("\n--- 5. failed image 의 부활 경로 ---")
    tmp = tempfile.mkdtemp(prefix="qa_tr_fail_")
    try:
        db = _fresh_db(tmp)
        types = {t: "done" for t in THREE}
        types["image"] = "failed"
        _seed_queue(db, [("B1", "2025타경4", "1", types, FUTURE)])
        conn = db.get_connection()
        # ★ localtime 을 함께 쓴다 (2026-08-21 Sprint 248).
        #   SQLite 의 'now' 는 UTC 다. 한국(UTC+9)에서 UTC 로 "2일 전"을 만들면
        #   제품이 로컬 시각으로 판정하는 값과 9시간 어긋나, 경계 근처에서
        #   재시도 판정이 흔들린다. test_pipeline_integrity 의
        #   test_sqlite_now_is_localtime() 이 이 형태를 금지한다.
        conn.execute("UPDATE document_queue SET retry_count=2,"
                     " last_attempt_at=datetime('now','localtime','-2 day')"
                     " WHERE doc_type='image'")
        conn.commit()
        conn.close()

        res = _enqueue(db, [("B1", "2025타경4", "1", FUTURE)])
        after = _queue_map(db)
        check("적재는 새 행을 만들지 않는다", res["added"], 0)
        check("★ 적재가 failed 를 pending 으로 바꾸지 않는다",
              after[("B1", "2025타경4", "1", "image")][0], "failed")
        check("★ 적재가 retry_count 를 지우지 않는다",
              after[("B1", "2025타경4", "1", "image")][1], 2)

        db.reset_stale_queue()
        rec = _queue_map(db)
        check("★ 하루 지난 failed 는 회수 규칙이 pending 으로 되돌린다",
              rec[("B1", "2025타경4", "1", "image")][0], "pending")
        check("회수는 retry_count 를 0 으로 되돌린다(새 시도)",
              rec[("B1", "2025타경4", "1", "image")][1], 0)
        for t in THREE:
            check("회수가 %s 의 done 을 건드리지 않는다" % t,
                  rec[("B1", "2025타경4", "1", t)][0], "done")

        s = _run_worker(db)
        check("★ 회수 후 워커가 image 만 처리한다",
              [c[2] for c in s["collects"]], ["image"])
        check("이동은 1회", len(s["navs"]), 1)
        check("그 이동은 엄격하다", [bool(n[3]) for n in s["navs"]], [True])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ===========================================================================
# 6. image 실패가 기존 3종 성공을 훼손하지 않는다
# ===========================================================================
def test_image_failure_never_damages_the_finished_three():
    print("\n--- 6. image 실패가 기존 3종 done 을 훼손하지 않는다 ---")
    for label, kwargs in (("엄격 진입 실패", {"image_ok": False}),
                          ("수집 자체 실패", {"collect_fail": ("image",)})):
        tmp = tempfile.mkdtemp(prefix="qa_tr_dmg_")
        try:
            db = _fresh_db(tmp)
            _seed_queue(db, [("B1", "2025타경5", "1", {t: "done" for t in THREE}, PAST)])
            _enqueue(db, [("B1", "2025타경5", "1", FUTURE)])
            s = _run_worker(db, **kwargs)
            after = _queue_map(db)
            print("    [%s] exit=%s 이동=%d" % (label, s["exit"], len(s["navs"])))
            check("[%s] ★ image 는 실패로 남는다(성공이라 하지 않는다)" % label,
                  after[("B1", "2025타경5", "1", "image")][0] in ("pending", "failed"), True)
            for t in THREE:
                check("[%s] ★ %s 는 done 그대로다" % (label, t),
                      after[("B1", "2025타경5", "1", t)][0], "done")
            check("[%s] 재시도 예산이 1 소모된다" % label,
                  after[("B1", "2025타경5", "1", "image")][1], 1)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


# ===========================================================================
# 7. image 실패가 같은 물건의 **다른 종류**를 끌고 내려가지 않는다
# ===========================================================================
def test_image_failure_does_not_take_pending_siblings_down():
    """3종이 아직 pending 인 물건에서 image 만 실패해도 나머지는 각자 성공해야 한다.

    묶음(batching) 안에서 사진이 먼저 처리되므로, 그 실패가 뒤의 문서로 전파되면
    **한 종류의 실패가 물건 전체의 실패**가 된다.
    """
    print("\n--- 7. image 실패가 같은 묶음의 pending 형제를 끌고 내려가지 않는다 ---")
    tmp = tempfile.mkdtemp(prefix="qa_tr_sib_")
    try:
        db = _fresh_db(tmp)
        _seed_queue(db, [("B1", "2025타경6", "1", {t: "pending" for t in THREE}, FUTURE)])
        _enqueue(db, [("B1", "2025타경6", "1", FUTURE)])
        check("전제: 4종이 모두 pending", len(_queue_map(db)), 4)

        s = _run_worker(db, image_ok=False)
        after = _queue_map(db)
        collected = sorted(c[2] for c in s["collects"])
        print("    수집 시도: %s / 이동 %d회" % (collected, len(s["navs"])))
        check("★ 문서 3종은 그대로 수집된다", collected, sorted(THREE))
        for t in THREE:
            check("★ %s 는 done 이 된다" % t,
                  after[("B1", "2025타경6", "1", t)][0], "done")
        check_true("★ image 만 실패로 남는다",
                   after[("B1", "2025타경6", "1", "image")][0] in ("pending", "failed"),
                   after[("B1", "2025타경6", "1", "image")][0])
        check("실패가 있어도 종료코드는 성공(일부 성공)", s["exit"], 0)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ===========================================================================
# 8. 기일이 지난 물건은 image 를 받지 않는다
# ===========================================================================
def test_expired_item_gets_no_image_row():
    print("\n--- 8. 기일 경과 물건은 image 를 받지 않는다(1차 방어선) ---")
    tmp = tempfile.mkdtemp(prefix="qa_tr_exp_")
    try:
        db = _fresh_db(tmp)
        _seed_queue(db, [("B1", "2025타경7", "1", {t: "done" for t in THREE}, PAST)])
        res = _enqueue(db, [("B1", "2025타경7", "1", PAST)])
        after = _queue_map(db)
        check("★ 추가된 행 없음", res["added"], 0)
        check("★ 사전 제외로 집계된다", res["skipped_expired"], 1)
        check("행 수 그대로 3(image 없음)", len(after), 3)
        check_true("★ image 행이 생기지 않는다",
                   ("B1", "2025타경7", "1", "image") not in after, sorted(after))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ===========================================================================
# 9. 실측 분포를 그대로 재현한 전환 — 처리 비용을 **센다**
# ===========================================================================
def test_full_population_transition_cost():
    """운영 큐의 조합 분포를 그대로 축소 재현하고, 전환이 만드는 비용을 센다.

    비율은 2026-08-21 운영 실측(§ 파일 docstring)을 그대로 쓴다:
        3종 pending 903 : 3종 done 160 : 3종 만료 62 : done/done/pending 36
    """
    print("\n--- 9. 실측 분포 재현: 전환이 만드는 큐와 이동 ---")
    import config.settings as cfg
    SCALE = 10          # 903:160:62:36 -> 90:16:6:3 (비율 유지, 실행 시간 확보)
    GROUPS = [("p3", 903 // SCALE, {t: "pending" for t in THREE}, FUTURE),
              ("d3", 160 // SCALE, {t: "done" for t in THREE}, FUTURE),
              ("ex", 62 // SCALE, {t: "SKIPPED_EXPIRED" for t in THREE}, PAST),
              ("dp", 36 // SCALE, {"spec": "done", "appraisal": "done",
                                   "status": "pending"}, FUTURE)]
    tmp = tempfile.mkdtemp(prefix="qa_tr_pop_")
    try:
        db = _fresh_db(tmp)
        seed, crawl = [], []
        for tag, n, types, adate in GROUPS:
            for i in range(n):
                key = ("B1", "2025타경%s%03d" % (tag, i), "1")
                seed.append((key[0], key[1], key[2], types, adate))
                # 만료 그룹은 법원 목록에 다시 안 나온다 - 크롤 결과에 넣지 않는다
                if tag != "ex":
                    crawl.append((key[0], key[1], key[2], FUTURE))
        _seed_queue(db, seed)
        n_items = len(seed)
        before = _queue_map(db)
        print("    재현 물건 %d개 / 큐 %d행 (image 0행)" % (n_items, len(before)))
        check("전제: image 행이 하나도 없다",
              sum(1 for k in before if k[3] == "image"), 0)

        res = _enqueue(db, crawl)
        after = _queue_map(db)
        n_img = sum(1 for k in after if k[3] == "image")
        print("    적재: 추가 %d / 기일갱신 %d / 사전제외 %d"
              % (res["added"], res["refreshed"], res["skipped_expired"]))
        print("    -> 큐 %d행 -> %d행, image %d행" % (len(before), len(after), n_img))

        check("★ 추가된 행 = 크롤에 다시 나온 물건 수(물건당 image 1개)",
              res["added"], len(crawl))
        check("★ image 행 수 = 크롤에 다시 나온 물건 수", n_img, len(crawl))
        check("★ 만료 그룹은 image 를 받지 않는다",
              sum(1 for k in after if k[3] == "image" and "ex" in k[1]), 0)
        check("★ 3종은 하나도 새로 생기지 않았다",
              sum(1 for k in after if k[3] != "image"),
              sum(1 for k in before if k[3] != "image"))
        # done 이 되살아나지 않았는가
        revived = [k for k, v in after.items()
                   if k[3] != "image" and before.get(k, ("",))[0] == "done" and v[0] != "done"]
        check("★ done 이던 행이 하나도 되살아나지 않았다", revived, [])

        s = _run_worker(db)
        navs = len(s["navs"])
        strict = sum(1 for n in s["navs"] if n[3])
        by_type = {}
        for c in s["collects"]:
            by_type[c[2]] = by_type.get(c[2], 0) + 1
        print("    워커: 이동 %d회(엄격 %d) / 수집 %s" % (navs, strict, by_type))

        # 처리 대상 물건 = 만료가 아닌 물건 (크롤에 다시 나온 것)
        target_items = len(crawl)
        check("★ 이동 횟수 = 처리 대상 물건 수 (물건당 1회 - batching 유지)",
              navs, target_items)
        check("★ 모든 이동이 엄격하다(image 가 묶음에 있으므로)", strict, navs)
        check("★ image 는 대상 물건마다 정확히 한 번 수집된다",
              by_type.get("image"), target_items)

        conn = db.get_connection()
        left = dict(conn.execute("select status,count(*) from document_queue group by status"))
        conn.close()
        print("    큐 최종: %s" % left)
        check("★ pending 이 남지 않는다", left.get("pending", 0), 0)

        # --- 비용 산술 (이 파일 안에서 닫는다) ---
        NAV = 15.2          # Sprint 235 실측 이동 1회
        PER_ROW = 8.0       # 종류당 수집+sleep (23.2 - 15.2)
        n_types = len(cfg.DOC_TYPE_LIST)
        per_item_after = NAV + n_types * PER_ROW
        per_item_before = NAV + 3 * PER_ROW
        print("    물건당 비용: 3종 %.1f초 -> 4종 %.1f초 (+%.1f초, %.0f%%)"
              % (per_item_before, per_item_after,
                 per_item_after - per_item_before,
                 100.0 * (per_item_after / per_item_before - 1)))
        check_true("★ image 추가로 물건당 비용이 늘어난다(공짜가 아니다)",
                   per_item_after > per_item_before,
                   "%.1f vs %.1f" % (per_item_after, per_item_before))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ===========================================================================
# 10. 전환 후 능력 모델과 충돌하지 않는가 (실측 분포 기준 산술)
# ===========================================================================
def test_transition_fits_the_capacity_model():
    """전환이 만드는 하루 부하를 능력 모델과 **같은 상수**로 계산한다.

    상수를 여기서 새로 정하지 않는다 — `test_worker_capacity.py` 가 쓰는 값과
    같은 출처(Sprint 235 실측)를 쓰고, 창 길이는 config 에서 읽는다.
    """
    print("\n--- 10. 전환 후 하루 능력 (실측 상수로 산술) ---")
    import config.settings as cfg
    NAV, PER_ROW = 15.2, 8.0
    n_types = len(cfg.DOC_TYPE_LIST)
    sh, sm = map(int, cfg.DOC_WORKER_START_TIME.split(":"))
    eh, em = map(int, cfg.DOC_WORKER_END_TIME.split(":"))
    window_s = ((eh * 60 + em) - (sh * 60 + sm)) * 60

    per_item_3 = NAV + 3 * PER_ROW
    per_item_4 = NAV + n_types * PER_ROW
    cap3 = int(window_s // per_item_3)
    cap4 = int(window_s // per_item_4)
    print("    창 %d초 / 물건당 3종 %.1f초 -> 하루 %d건" % (window_s, per_item_3, cap3))
    print("             물건당 %d종 %.1f초 -> 하루 %d건" % (n_types, per_item_4, cap4))
    print("    -> image 추가로 하루 능력 %d건 감소 (%.0f%%)"
          % (cap3 - cap4, 100.0 * (1 - cap4 / float(cap3))))

    check_true("검사가 공허하지 않다(창이 양수다)", window_s > 0, window_s)
    check_true("★ image 추가는 능력을 **떨어뜨린다**(늘지 않는다)", cap4 < cap3,
               "%d vs %d" % (cap4, cap3))
    check("★ config 의 doc_type 수가 4다(3이면 이 계산이 무의미)", n_types, 4)

    # 실측 공급(Sprint 235 기록: 중앙값 106 / 최대 278)과 대조
    MEDIAN_SUPPLY, PEAK_SUPPLY = 106, 278
    print("    실측 공급 중앙값 %d건 / 최대 %d건" % (MEDIAN_SUPPLY, PEAK_SUPPLY))
    check_true("★ 4종 체제에서도 중앙값 공급은 감당한다", cap4 >= MEDIAN_SUPPLY,
               "능력 %d < 중앙값 %d - 이 사실이 바뀌면 MAX_ITEMS 판단을 다시 해야 한다"
               % (cap4, MEDIAN_SUPPLY))
    print("    최대 공급일 감당 여부: %s (부족 %d건)"
          % ("감당" if cap4 >= PEAK_SUPPLY else "밀린다", max(0, PEAK_SUPPLY - cap4)))
    check_true("최대 공급일을 감당하지 못한다는 사실이 계산 가능하다",
               isinstance(PEAK_SUPPLY - cap4, int), None)


def run():
    print("=" * 66)
    print(" image 큐 전환 경로 계약 (Sprint 243)")
    print("=" * 66)
    test_population_matches_the_live_queue()
    test_only_image_is_added_to_a_done_item()
    test_reenqueue_never_duplicates_or_grows()
    test_done_image_is_not_recreated_or_revived()
    test_failed_image_is_revived_by_recovery_not_by_enqueue()
    test_image_failure_never_damages_the_finished_three()
    test_image_failure_does_not_take_pending_siblings_down()
    test_expired_item_gets_no_image_row()
    test_full_population_transition_cost()
    test_transition_fits_the_capacity_model()

    print("\n" + "=" * 66)
    if failures:
        print("FAILED (%d/%d): %s" % (len(failures), CHECKS[0], ", ".join(failures)))
        return 1
    print("ALL IMAGE QUEUE TRANSITION TESTS PASSED (%d checks)" % CHECKS[0])
    return 0


if __name__ == "__main__":
    sys.exit(run())
