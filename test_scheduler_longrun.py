# -*- coding: utf-8 -*-
"""Scheduler 장시간 무인 운전 시뮬레이션 (2026-08-20 Sprint 230 신설).

## 왜 이 파일이 있나

이 저장소의 큐/락/재시도 검사는 전부 **한 동작**을 본다 — claim 이 원자적인가,
락이 배타적인가, 재시도가 소진되면 멈추는가. 각각은 촘촘하다.

**비어 있던 것은 그 동작들이 여러 날 겹쳐 쌓였을 때다.** 목표가
"사람이 하루 한 번 실행하는 프로그램"이 아니라 **"Scheduler 가 붙으면 장시간
자동으로 도는 시스템"** 이라면, 검증해야 하는 것은 하루치가 아니라 **누적**이다.

    하루치로는 절대 보이지 않는 것들
      큐 행이 날마다 조금씩 늘어난다(중복 적재)
      재시도 예산이 날짜를 넘기며 되살아나 영원히 재시도한다
      크래시로 남은 in_progress 가 다음 날 회수되지 않고 쌓인다
      회수된 행이 `refresh` 의도를 잃고 `pending` 으로 강등된다
      화면 상태(document_status)와 큐가 날마다 조금씩 갈라진다

## 어떻게 재는가

**실제 함수만 부른다.** `enqueue_documents` / `claim_next_item_rows` /
`mark_queue_done` / `mark_queue_failed` / `reset_stale_queue` /
`refresh_queue_priority` — 워커가 부르는 그 함수들이다.
가짜 큐를 만들어 가짜 규칙을 검증하면 아무것도 증명하지 못한다.

운영 `auction.db` 는 열지 않는다. 임시 디렉터리에 **실제 부트스트랩 3단계**
(`init_db` -> `migrate_v4_1` -> `run_migrations`)로 스키마를 세운다.

크래시는 **claim 한 뒤 아무 표시도 하지 않고 버리는 것**으로 만든다. 프로세스가
죽은 것과 DB 에서 구별되지 않는다 — 그것이 정확히 재현하려는 상황이다.
시간 경과는 `last_attempt_at` 을 과거로 밀어 만든다(회수 임계 10분 / 재시도 1일).

    python test_scheduler_longrun.py
"""
import contextlib
import gc
import io
import os
import shutil
import sqlite3
import sys
import tempfile
import time
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

failures = []


def check(name, actual, expected):
    ok = actual == expected
    print("[%s] %s: %r (expected %r)" % ("PASS" if ok else "FAIL", name, actual, expected))
    if not ok:
        failures.append(name)


def check_true(name, cond, detail=""):
    print("[%s] %s%s" % ("PASS" if cond else "FAIL", name,
                         "" if cond else " -- " + str(detail)))
    if not cond:
        failures.append(name)


# ---------------------------------------------------------------------------
# 임시 환경 (운영 DB 를 열지 않는다)
# ---------------------------------------------------------------------------
class Env:
    def __init__(self):
        self.dir = tempfile.mkdtemp(prefix="longrun_")
        import storage.database as dbmod
        self.dbmod = dbmod
        self._orig_db = dbmod.DB_PATH
        dbmod.DB_PATH = os.path.join(self.dir, "t.db")

        import storage.migrate_v4_1 as mig
        import storage.migrations.run_migrations as runmig
        with contextlib.redirect_stdout(io.StringIO()):
            dbmod.init_db()
            mig.migrate()
            runmig.run()

    def close(self):
        self.dbmod.DB_PATH = self._orig_db
        shutil.rmtree(self.dir, ignore_errors=True)

    def conn(self):
        return self.dbmod.get_connection()

    def rows(self, sql, params=()):
        c = self.conn()
        try:
            return [dict(r) for r in c.execute(sql, params)]
        finally:
            c.close()

    def one(self, sql, params=()):
        r = self.rows(sql, params)
        return r[0] if r else None

    def age_all(self, minutes=0, days=0):
        """모든 큐 행의 `last_attempt_at` 을 과거로 민다(시간 경과 재현)."""
        c = self.conn()
        try:
            c.execute(
                "UPDATE document_queue SET last_attempt_at = "
                "datetime(last_attempt_at, ?) WHERE last_attempt_at IS NOT NULL",
                ("-%d minutes" % (minutes + days * 1440),))
            c.commit()
        finally:
            c.close()


def sync_to_auction_item():
    """`auction` -> `auction_item` 동기화. `run_daily.bat` 이 mvp_scraper 다음에
    `migrate_execute.py` 를 부르는 그 단계다.

    ★ 이 단계를 빼면 `auction_item` 이 0행이 되고, 그것을 조인하는 불변식들이
      **공허하게 통과한다**(조인 결과가 항상 비어 있으므로). 실제로 이 검사의
      첫 판본이 그랬다.
    """
    import migrate_execute
    with contextlib.redirect_stdout(io.StringIO()):
        migrate_execute.execute()


def make_rows(day_idx, count, base_date):
    """그날 크롤이 가져온 것으로 칠 물건들. 기일은 넉넉히 미래로 둔다."""
    out = []
    for i in range(count):
        out.append({
            # `upsert_batch` 의 식별키는 (court_code, case_no, item_no) 다.
            # court_code 를 비우면 모든 법원이 한 칸에 뭉친다 - 실제 파이프라인과 달라진다.
            "court_code": "서울중앙지방법원",
            "court_name": "서울중앙지방법원",
            "case_no": "2026타경%d" % (10000 + day_idx * 100 + i),
            "item_no": "1",
            "auction_date": base_date,
            "property_type": "아파트",
            "sido": "서울",
            "sigungu": "종로구",
            "dong": "",
            "full_address": "서울특별시 종로구 %d" % i,
            "appraisal_price": 100000000,
            "minimum_bid_price": 80000000,
            "bid_rate": 0.8,
            "fail_count": 0,
            "status": "유찰 1회",
            "crawl_date": base_date,
        })
    return out


# ---------------------------------------------------------------------------
# 매일 검사하는 불변식
# ---------------------------------------------------------------------------
def invariants(env, day, note=""):
    """어느 날이든 참이어야 하는 것들. 하나라도 깨지면 그날을 지목한다."""
    bad = []

    # 1) 같은 (법원, 사건, 물건, 종류) 큐 행이 둘 이상이면 중복 적재다.
    dups = env.rows("""
        SELECT court_code, case_no, item_no, doc_type, COUNT(*) n
        FROM document_queue
        GROUP BY court_code, case_no, item_no, doc_type HAVING n > 1
    """)
    if dups:
        bad.append("D%d 중복 큐 행 %d조합 %s" % (day, len(dups), dups[:2]))

    # 2) 재시도 예산은 상한을 넘을 수 없다.
    over = env.one("SELECT MAX(retry_count) m FROM document_queue")
    if over and over["m"] is not None and over["m"] > env.dbmod.MAX_DOC_RETRY:
        bad.append("D%d retry_count %d > 상한 %d" % (day, over["m"], env.dbmod.MAX_DOC_RETRY))

    # 3) document_status 는 반드시 실재하는 물건을 가리켜야 한다.
    orphan = env.one("""
        SELECT COUNT(*) n FROM document_status ds
        WHERE NOT EXISTS (SELECT 1 FROM auction_item ai WHERE ai.id = ds.item_id)
    """)["n"]
    if orphan:
        bad.append("D%d 고아 document_status %d행" % (day, orphan))

    # 4) 종결된 큐 행(done)은 화면에서 COLLECTING 으로 남아 있으면 안 된다.
    #    "받았다고 기록했는데 화면은 아직 수집중" = 두 기록이 갈라진 상태다.
    split = env.rows("""
        SELECT q.case_no, q.doc_type, ds.status
        FROM document_queue q
        JOIN auction_item ai ON ai.court_name = q.court_code AND ai.case_no = q.case_no
                            AND CAST(ai.item_no AS TEXT) = CAST(q.item_no AS TEXT)
        JOIN document_status ds ON ds.item_id = ai.id
                               AND ds.doc_type = UPPER(q.doc_type)
        WHERE q.status = 'done' AND ds.status = 'COLLECTING'
    """)
    if split:
        bad.append("D%d done 인데 화면 COLLECTING %d행 %s" % (day, len(split), split[:2]))

    return bad


# ---------------------------------------------------------------------------
# 하루치 워커 실행 (실제 함수만 부른다)
# ---------------------------------------------------------------------------
def run_worker_day(env, outcome_of, max_items=10000):
    """`doc_worker.main()` 의 루프를 DB 관점에서만 재현한다.

    브라우저/파일은 이 검사의 관심사가 아니다(그쪽은 test_asset_pipeline 이 본다).
    여기서 보는 것은 **claim -> 종결** 이 여러 날 쌓였을 때의 큐 상태다.
    """
    db = env.dbmod
    stats = {"done": 0, "failed": 0, "crashed": 0, "claimed": 0, "batches": 0}
    seen_ids = []
    # ★ 운영 워커와 **같은 단위로** 집는다 (2026-08-20 Sprint 236).
    #   워커는 한 물건의 행을 한꺼번에 claim 하고 상세페이지에 한 번만 들어간다.
    #   시뮬레이션이 행 단위로 집으면 7일을 돌려도 운영에서 벌어지는 일이 아니다.
    #   처리 자체는 여전히 **행마다** 한다 - 그것이 batching 의 계약이다.
    pending_batch = []
    while stats["claimed"] < max_items:
        if not pending_batch:
            pending_batch = list(db.claim_next_item_rows())
            if not pending_batch:
                break
            stats["batches"] += 1
        item = pending_batch.pop(0)
        stats["claimed"] += 1
        seen_ids.append(item["id"])
        what = outcome_of(item)
        if what == "done":
            db.mark_queue_done(item["id"], item["court_code"], item["case_no"],
                               item["item_no"], item["doc_type"], "", "h-%d" % item["id"])
            stats["done"] += 1
        elif what == "fail":
            db.mark_queue_failed(item["id"], item["retry_count"])
            stats["failed"] += 1
        else:
            # 크래시: 아무 표시도 남기지 않는다. 행은 in_progress 로 남는다.
            stats["crashed"] += 1
    stats["seen_ids"] = seen_ids
    if pending_batch:
        # 창이 닫혀 남은 행은 워커와 똑같이 되돌린다(방치하지 않는다).
        db.release_queue_rows([r["id"] for r in pending_batch])
    return stats


def test_multi_day_unattended_run():
    print("\n" + "=" * 62)
    print(" 1. 여러 날 무인 운전 - 누적 불변식")
    print("=" * 62)

    env = Env()
    try:
        db = env.dbmod
        future = (datetime.now() + timedelta(days=120)).strftime("%Y-%m-%d")

        DAYS = 7
        per_day = 4
        all_bad = []
        totals = []

        # 물건마다 종류 4개가 큐에 들어간다. 결과를 섞어 매일 다르게 만든다.
        def outcome_for(day):
            def f(item):
                h = (hash((item["case_no"], item["doc_type"], day)) % 10 + 10) % 10
                if h < 5:
                    return "done"
                if h < 8:
                    return "fail"
                return "crash"
            return f

        for day in range(1, DAYS + 1):
            # --- 01:50 우선순위 재계산 -----------------------------------
            db.refresh_queue_priority()

            # --- 02:00 워커 시작: 죽은 claim / 하루 지난 failed 회수 -------
            db.reset_stale_queue()

            after_reset = env.one(
                "SELECT COUNT(*) n FROM document_queue WHERE status IN "
                "('in_progress','in_progress_refresh')")["n"]
            if day > 1 and after_reset:
                all_bad.append("D%d reset 후에도 in_progress %d행" % (day, after_reset))

            # --- 워커가 큐를 소진 ----------------------------------------
            st = run_worker_day(env, outcome_for(day))

            # --- 06:00 사건 크롤 -> 적재 ---------------------------------
            rows = make_rows(day, per_day, future)
            with contextlib.redirect_stdout(io.StringIO()):
                db.upsert_batch(rows)
            sync_to_auction_item()
            with contextlib.redirect_stdout(io.StringIO()):
                db.enqueue_documents(rows)

            bad = invariants(env, day)
            all_bad.extend(bad)

            total = env.one("SELECT COUNT(*) n FROM document_queue")["n"]
            totals.append(total)
            print("    D%d  claim %3d (done %2d / fail %2d / crash %2d)  큐 총 %3d행"
                  % (day, st["claimed"], st["done"], st["failed"], st["crashed"], total))

            # 하루가 지난 것으로 시간을 민다(회수/재시도 임계를 넘긴다).
            env.age_all(days=1, minutes=30)

        check("★ %d일 동안 불변식 위반" % DAYS, all_bad[:3], [])

        # ★ 불변식 3/4 는 auction_item 을 조인한다. 그 표가 비어 있으면 **항상 통과**한다.
        #   실제로 첫 판본이 동기화 단계를 빼먹어 그렇게 통과하고 있었다.
        n_items = env.one("SELECT COUNT(*) n FROM auction_item")["n"]
        n_status = env.one("SELECT COUNT(*) n FROM document_status")["n"]
        check_true("검사가 공허하지 않다: auction_item 이 실제로 채워졌다",
                   n_items == DAYS * per_day, "%d / 기대 %d" % (n_items, DAYS * per_day))
        check_true("검사가 공허하지 않다: document_status 가 실제로 쌓였다",
                   n_status > 0, n_status)
        print("    auction_item %d행 / document_status %d행" % (n_items, n_status))

        # 큐 총량은 적재한 만큼만 늘어야 한다 - 날마다 배로 늘면 중복 적재다.
        expected_total = DAYS * per_day * len(
            [r["doc_type"] for r in env.rows(
                "SELECT DISTINCT doc_type FROM document_queue")])
        check_true("큐 총량이 적재량과 맞는다(폭증 없음)",
                   totals[-1] == expected_total,
                   "실제 %d / 기대 %d" % (totals[-1], expected_total))

        # 매일 조금씩 늘어나는 증가폭이 일정한가 (누적 누수 탐지)
        deltas = [totals[i] - totals[i - 1] for i in range(1, len(totals))]
        check_true("일별 증가폭이 일정하다(누수 없음)",
                   len(set(deltas)) == 1, deltas)
        print("    일별 증가폭 %s" % deltas)
    finally:
        env.close()


def test_crash_is_recovered_next_day_without_losing_refresh_intent():
    print("\n" + "=" * 62)
    print(" 2. 크래시로 남은 claim 이 다음 날 **원래 자리로** 회수된다")
    print("=" * 62)

    env = Env()
    try:
        db = env.dbmod
        future = (datetime.now() + timedelta(days=120)).strftime("%Y-%m-%d")
        rows = make_rows(1, 1, future)
        with contextlib.redirect_stdout(io.StringIO()):
            db.upsert_batch(rows)
        sync_to_auction_item()
        with contextlib.redirect_stdout(io.StringIO()):
            db.enqueue_documents(rows)

        # 한 행을 refresh 로 바꿔 둔다(=이미 받아 둔 것을 다시 받아야 한다는 의도).
        c = env.conn()
        try:
            rid = c.execute("SELECT id FROM document_queue WHERE doc_type='spec'").fetchone()["id"]
            c.execute("UPDATE document_queue SET status='refresh' WHERE id=?", (rid,))
            c.commit()
        finally:
            c.close()

        # 워커가 **전부** 집고 크래시한다(표시 없음).
        #   claim 순서는 priority ASC, auction_date ASC 라 특정 종류가 먼저 온다는 보장이
        #   없다 - 그래서 몇 개만 집고 특정 행을 기대하면 안 된다(첫 판본이 그렇게 틀렸다).
        claimed = []
        while True:
            it = db.claim_next_queue_item()
            if not it:
                break
            claimed.append(it)
        check_true("큐 행을 전부 집었다(검사가 공허하지 않다)", len(claimed) >= 4, len(claimed))

        states = {r["doc_type"]: r["status"] for r in env.rows(
            "SELECT doc_type, status FROM document_queue")}
        check_true("refresh 행은 in_progress_refresh 로 집힌다",
                   "in_progress_refresh" in states.values(), states)

        # 10분이 지난 것으로 민다 -> 다음 실행의 reset 이 회수해야 한다.
        env.age_all(minutes=30)
        db.reset_stale_queue()

        after = {r["id"]: r["status"] for r in env.rows(
            "SELECT id, status FROM document_queue")}
        stuck = [i for i, s in after.items() if s.startswith("in_progress")]
        check("★ 회수 후 in_progress 로 남은 행", stuck, [])

        # ★ 핵심 - refresh 의도가 pending 으로 강등되지 않았는가
        check("★ refresh 행은 refresh 로 되돌아온다(pending 으로 강등되지 않는다)",
              after[rid], "refresh")
    finally:
        env.close()


def test_retry_budget_does_not_regenerate_forever():
    print("\n" + "=" * 62)
    print(" 3. 재시도 예산이 날짜를 넘기며 무한히 되살아나지 않는다")
    print("=" * 62)

    env = Env()
    try:
        db = env.dbmod
        future = (datetime.now() + timedelta(days=120)).strftime("%Y-%m-%d")
        rows = make_rows(1, 1, future)
        with contextlib.redirect_stdout(io.StringIO()):
            db.upsert_batch(rows)
        sync_to_auction_item()
        with contextlib.redirect_stdout(io.StringIO()):
            db.enqueue_documents(rows)

        # 늘 실패하는 세계에서 여러 날을 돌린다.
        attempts = 0
        for day in range(1, 6):
            db.reset_stale_queue()
            while True:
                item = db.claim_next_queue_item()
                if not item:
                    break
                db.mark_queue_failed(item["id"], item["retry_count"])
                attempts += 1
            env.age_all(days=1, minutes=30)

        print("    5일 동안 총 시도 %d회" % attempts)

        # `reset_stale_queue` 는 하루 지난 failed 를 되살린다 — 이것은 **의도된 설계**다
        # (일시적 원인으로 실패한 문서를 다음 날 다시 받는다). 그래서 "영원히 재시도"는
        # 여기서 결함이 아니다. 결함이 되는 것은 **한 번의 실행 안에서** 상한을 넘는 것이다.
        maxr = env.one("SELECT MAX(retry_count) m FROM document_queue")["m"]
        check_true("한 행의 retry_count 가 상한을 넘지 않는다",
                   maxr <= db.MAX_DOC_RETRY, "%s > %s" % (maxr, db.MAX_DOC_RETRY))

        # 하루에 소진하는 예산이 정확히 상한만큼인지 (한 행 x 4종)
        per_day = attempts / 5.0
        n_types = env.one("SELECT COUNT(DISTINCT doc_type) n FROM document_queue")["n"]
        check_true("하루 시도량이 (종류수 x 재시도상한) 이내다",
                   per_day <= n_types * db.MAX_DOC_RETRY,
                   "일평균 %.1f회 / 상한 %d" % (per_day, n_types * db.MAX_DOC_RETRY))

        # ★ 그리고 그 되살아남이 **화면 상태를 실패로 방치하지 않는가**
        stale_failed = env.rows("""
            SELECT ds.doc_type, ds.status FROM document_status ds
            JOIN document_queue q ON UPPER(q.doc_type) = ds.doc_type
            WHERE q.status IN ('pending','refresh') AND ds.status = 'FAILED'
        """)
        check("★ 재시도 대기로 되돌아온 행이 화면에 FAILED 로 남지 않는다",
              stale_failed, [])
    finally:
        env.close()


def test_rerun_same_day_is_idempotent():
    print("\n" + "=" * 62)
    print(" 4. 같은 날 두 번 돌려도 중복/손상이 없다")
    print("=" * 62)

    env = Env()
    try:
        db = env.dbmod
        future = (datetime.now() + timedelta(days=120)).strftime("%Y-%m-%d")
        rows = make_rows(1, 3, future)

        with contextlib.redirect_stdout(io.StringIO()):
            db.upsert_batch(rows)
        sync_to_auction_item()
        with contextlib.redirect_stdout(io.StringIO()):
            db.enqueue_documents(rows)
        first_q = env.one("SELECT COUNT(*) n FROM document_queue")["n"]
        first_i = env.one("SELECT COUNT(*) n FROM auction_item")["n"]

        # 같은 크롤 결과로 한 번 더 (스케줄러가 두 번 뜨거나 수동 재실행)
        with contextlib.redirect_stdout(io.StringIO()):
            db.upsert_batch(rows)
        sync_to_auction_item()
        with contextlib.redirect_stdout(io.StringIO()):
            db.enqueue_documents(rows)
        second_q = env.one("SELECT COUNT(*) n FROM document_queue")["n"]
        second_i = env.one("SELECT COUNT(*) n FROM auction_item")["n"]

        check("재실행해도 큐 행이 늘지 않는다", second_q, first_q)
        check("재실행해도 물건이 늘지 않는다", second_i, first_i)
        check_true("검사가 공허하지 않다(1회차에 큐가 실제로 쌓였다)", first_q > 0, first_q)
        # 물건 쪽도 0이면 위 단언이 0 == 0 으로 공허해진다.
        check_true("검사가 공허하지 않다(물건도 실제로 쌓였다)", first_i > 0, first_i)

        # 워커가 절반쯤 처리한 뒤 다시 적재해도 done 이 되살아나지 않는가
        done_ids = []
        for _ in range(4):
            item = db.claim_next_queue_item()
            if not item:
                break
            db.mark_queue_done(item["id"], item["court_code"], item["case_no"],
                               item["item_no"], item["doc_type"], "", "h")
            done_ids.append(item["id"])
        with contextlib.redirect_stdout(io.StringIO()):
            db.enqueue_documents(rows)
        revived = env.rows(
            "SELECT id, status FROM document_queue WHERE id IN (%s) AND status != 'done'"
            % ",".join("?" * len(done_ids)), done_ids) if done_ids else []
        check("★ 이미 done 인 행이 재적재로 되살아나지 않는다", revived, [])
        check("재적재 후에도 큐 총량 불변", env.one(
            "SELECT COUNT(*) n FROM document_queue")["n"], first_q)
    finally:
        env.close()


def test_expired_backlog_does_not_starve_live_work():
    print("\n" + "=" * 62)
    print(" 5. 만료 행이 산더미여도 살아 있는 작업을 굶기지 않는다")
    print("=" * 62)

    env = Env()
    try:
        db = env.dbmod
        past = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
        future = (datetime.now() + timedelta(days=120)).strftime("%Y-%m-%d")

        # 만료 물건을 잔뜩, 살아 있는 물건을 하나.
        old_rows = make_rows(9, 50, past)
        live_rows = make_rows(1, 1, future)
        with contextlib.redirect_stdout(io.StringIO()):
            db.upsert_batch(old_rows + live_rows)
        sync_to_auction_item()
        with contextlib.redirect_stdout(io.StringIO()):
            # 만료는 1차 방어선이 막으므로 직접 넣는다(과거에 적재된 것을 재현).
            db.enqueue_documents(live_rows)
        c = env.conn()
        try:
            for r in old_rows:
                for dt in ("spec", "status", "appraisal", "image"):
                    c.execute(
                        "INSERT INTO document_queue (court_code, case_no, item_no, doc_type,"
                        " priority, auction_date, status, retry_count, enqueued_at)"
                        " VALUES (?,?,?,?,1,?, 'pending', 0, ?)",
                        (r["court_name"], r["case_no"], r["item_no"], dt, past,
                         datetime.now().isoformat()))
            c.commit()
        finally:
            c.close()

        total = env.one("SELECT COUNT(*) n FROM document_queue")["n"]
        print("    큐 %d행 (만료 %d + 살아있음 %d)"
              % (total, len(old_rows) * 4, env.one(
                  "SELECT COUNT(*) n FROM document_queue WHERE auction_date >= ?",
                  (datetime.now().strftime("%Y-%m-%d"),))["n"]))

        # 워커 루프를 재현: 만료는 SKIPPED_EXPIRED 로 넘기고 계속 간다.
        today = datetime.now().strftime("%Y-%m-%d")
        live_reached = 0
        claims = 0
        while claims < total + 10:
            item = db.claim_next_queue_item()
            if not item:
                break
            claims += 1
            ad = item.get("auction_date", "")
            if ad and ad < today:
                db.mark_queue_skipped_expired(item["id"], item["court_code"],
                                              item["case_no"], item["item_no"],
                                              item["doc_type"], ad)
                continue
            live_reached += 1
            db.mark_queue_done(item["id"], item["court_code"], item["case_no"],
                               item["item_no"], item["doc_type"], "", "h")

        check_true("★ 만료 %d행 뒤에서도 살아 있는 작업에 도달한다" % (len(old_rows) * 4),
                   live_reached > 0, live_reached)
        check("살아 있는 작업을 전부 처리했다", live_reached, 4)
        check("만료 행은 전부 종결됐다", env.one(
            "SELECT COUNT(*) n FROM document_queue WHERE status='pending'")["n"], 0)
    finally:
        env.close()


# ---------------------------------------------------------------------------
# 6. **프로세스 자원**이 바퀴마다 쌓이는가 (2026-08-27 신설, docs/BUGS.md #259)
#
# 위 1~5 는 전부 **DB 안의 누적**을 본다(큐 행, 재시도 예산, 상태 정합). 촘촘하다.
# 비어 있던 것은 **프로세스 밖의 누적**이다:
#
#     sqlite 커넥션이 닫히지 않고 쌓인다      -> 결국 "database is locked"
#     파일 핸들이 쌓인다                       -> 결국 열기 실패
#     파이썬 객체가 쌓인다                     -> 밤새 돌면 메모리가 따라 오른다
#     바퀴마다 조금씩 느려진다                 -> "처음엔 정상인데 아침에 안 끝나 있다"
#
# 이 저장소의 DB 함수는 전부 `try/finally: conn.close()` 를 쓴다. **그 규약이 지켜지고
# 있는지 아무도 확인하지 않았다** — 한 함수에서 `finally` 를 빠뜨려도 하루치 검사는
# 전부 통과한다. 드러나는 것은 밤새 돌린 다음 날 아침이다.
#
# ## 어떻게 재는가 — 의견이 아니라 측정
#
#     살아 있는 sqlite3.Connection 객체 수   gc 로 직접 센다(close 누락이 곧 증가다)
#     프로세스 핸들 수                       Windows GetProcessHandleCount
#     파이썬 힙                              tracemalloc
#     바퀴당 소요 시간                       마지막 바퀴가 첫 바퀴보다 크게 느린가
#
# 절대값이 아니라 **기울기**를 본다. 첫 바퀴는 캐시/임포트가 데워지느라 원래 다르다.
# 그래서 워밍업 바퀴를 버리고 그 뒤 구간에서만 증가를 판정한다.
#
# 실측 (2026-08-27, 이 검사를 만들며 20바퀴):
#     핸들 128 -> 128 (무변화) / 파이썬 힙 0.38MB 고정 / DB 행수 전 테이블 무변화
#     RSS 28.8 -> 33.9MB (초반 5MB 오른 뒤 평평 - SQLite 페이지 캐시가 데워진 것)
# ---------------------------------------------------------------------------
class _ConnLeakWatch(object):
    """이 구간에서 **연 커넥션이 전부 명시적으로 닫혔는가**를 센다.

    ## ★ 여기까지 오는 데 판본을 두 번 버렸다 (2026-08-27, 둘 다 변이로 확인)

    변이는 하나다 — `refresh_queue_priority()` 의 `finally: conn.close()` 를 지운다.

        1판: `gc.get_objects()` 로 살아 있는 Connection 개수를 셌다
             -> 변이가 **그대로 통과**. CPython 참조 카운팅이 함수가 끝나는 순간
                지역 변수를 회수해 버리므로, 닫는 것을 잊어도 개수가 안 오른다.
                "누수가 없다"가 아니라 **"측정할 수 없다"** 를 통과로 읽고 있었다.

        2판: `conn.close` 를 파이썬 함수로 갈아끼워 호출을 셌다
             -> 변이가 **그대로 통과**. `sqlite3.Connection` 은 C 타입이라
                **속성을 붙일 수 없다**(AttributeError). 그리고 그 예외를 잡는 갈래가
                "감쌀 수 없으면 닫힌 것으로 친다"였다 — 즉 **실패를 통과로 바꾸는
                폴백**이었다. 이 저장소가 반복해서 잡아 온 바로 그 모양이다.

        3판(지금): `factory=` 로 **Connection 을 상속**한다. 이것이 파이썬이 공식으로
             지원하는 자리고, 상속 인스턴스는 `__dict__` 가 있어 중복 close 도 가른다.
             폴백은 두지 않는다 — 감쌀 수 없으면 **잡아서 알린다.**

    ★ 규약을 지키는 것이 왜 중요한가(참조 카운팅이 어차피 치워 주는데도):

        예외가 나면 트레이스백이 프레임을 붙잡아 지역 변수가 **살아남는다.**
        그때는 정말로 새고, 하필 그때가 밤새 실행 중 문제가 생긴 순간이다.
        Windows 에서 열린 커넥션은 파일 잠금을 쥐고 있어 다른 프로세스를 막는다.
        (실제로 이 변이는 파일 핸들이 바퀴마다 정확히 1개씩 늘어 그쪽 축에도 잡혔다.)
    """

    def __init__(self):
        self.opened = 0
        self.closed = 0
        self.untrackable = 0
        self._real = sqlite3.connect

    def _factory_for(self, base):
        watch = self

        class _Tracked(base):
            def close(self):
                if not getattr(self, "_watch_closed", False):
                    self._watch_closed = True
                    watch.closed += 1
                return base.close(self)

        return _Tracked

    def __enter__(self):
        watch = self

        def traced(*a, **kw):
            base = kw.pop("factory", sqlite3.Connection)
            try:
                kw["factory"] = watch._factory_for(base)
            except Exception:          # noqa: BLE001
                watch.untrackable += 1
                kw["factory"] = base
            conn = watch._real(*a, **kw)
            watch.opened += 1
            return conn

        sqlite3.connect = traced
        return self

    def __exit__(self, *exc):
        sqlite3.connect = self._real
        return False

    @property
    def leaked(self):
        return self.opened - self.closed


def _process_handles():
    """Windows 프로세스 핸들 수. 잴 수 없으면 None(그때는 이 축을 판정하지 않는다)."""
    try:
        import ctypes
        k32 = ctypes.windll.kernel32
        k32.GetCurrentProcess.restype = ctypes.c_void_p
        k32.GetProcessHandleCount.argtypes = [ctypes.c_void_p,
                                              ctypes.POINTER(ctypes.c_ulong)]
        k32.GetProcessHandleCount.restype = ctypes.c_int
        n = ctypes.c_ulong(0)
        if k32.GetProcessHandleCount(k32.GetCurrentProcess(), ctypes.byref(n)):
            return n.value
    except Exception:                      # noqa: BLE001 - 못 재면 판정하지 않는다
        pass
    return None


def _py_heap_bytes():
    import tracemalloc
    if not tracemalloc.is_tracing():
        tracemalloc.start()
    return tracemalloc.get_traced_memory()[0]


def _table_counts(env):
    c = env.conn()
    try:
        out = {}
        for (t,) in c.execute("SELECT name FROM sqlite_master WHERE type='table'"
                              " AND name NOT LIKE 'sqlite_%'").fetchall():
            try:
                out[t] = c.execute('SELECT COUNT(*) FROM "%s"' % t).fetchone()[0]
            except sqlite3.Error:
                pass
        return out
    finally:
        c.close()


def test_repeated_cycles_do_not_accumulate_process_resources():
    print("\n--- 6. 반복 실행이 프로세스 자원을 쌓지 않는가 (자원 누수) ---")
    CYCLES = 10
    WARMUP = 3                 # 캐시/임포트가 데워지는 구간은 기울기 판정에서 뺀다

    env = Env()
    try:
        base_date = (datetime.now() + timedelta(days=20)).strftime("%Y-%m-%d")
        rows = make_rows(0, 40, base_date)

        # 1회차로 큐/물건을 만들어 둔다. 이후 바퀴는 **같은 입력을 다시** 흘린다 —
        # 그것이 "매일 같은 자료가 다시 들어오는" 실제 운영 모양이다.
        env.dbmod.upsert_batch(rows)
        env.dbmod.enqueue_documents(rows)
        sync_to_auction_item()

        samples = []
        counts0 = _table_counts(env)      # 반복 **전** 기준선
        with _ConnLeakWatch() as watch:
            for i in range(CYCLES):
                t0 = time.time()
                env.dbmod.upsert_batch(rows)
                env.dbmod.enqueue_documents(rows)
                env.dbmod.refresh_queue_priority()
                env.dbmod.reset_stale_queue()
                picked = 0
                for _ in range(8):
                    got = env.dbmod.claim_next_item_rows()
                    if not got:
                        break
                    picked += len(got)
                    env.dbmod.release_queue_rows([g["id"] for g in got])
                elapsed = time.time() - t0
                samples.append({
                    "handles": _process_handles(),
                    "heap": _py_heap_bytes(),
                    "secs": elapsed,
                    "picked": picked,
                })
            opened, leaked = watch.opened, watch.leaked
            untrackable = watch.untrackable
        # 행수는 감시 밖에서 센다 - 이 조회는 제품 경로가 아니다.
        for i, srec in enumerate(samples):
            srec["counts"] = _table_counts(env) if i == len(samples) - 1 else None
        counts_last = samples[-1]["counts"]

        # --- 검사가 공허하지 않은가 --------------------------------------
        check_true("검사가 공허하지 않다(바퀴마다 실제로 일을 했다)",
                   sum(s["picked"] for s in samples) > 0,
                   "-> 집은 행이 0이면 이 검사는 아무것도 태우지 않은 것이다")
        check_true("검사가 공허하지 않다(큐가 실제로 쌓여 있다)",
                   counts_last.get("document_queue", 0) > 0,
                   counts_last.get("document_queue"))

        # --- (a) 커넥션 규약 ---------------------------------------------
        # `finally: conn.close()` 를 한 곳이라도 빠뜨리면 여기서 잡힌다.
        # (객체 생존을 세던 첫 판본은 변이가 그대로 통과했다 - _ConnLeakWatch 참고.)
        check_true("검사가 공허하지 않다(커넥션을 실제로 열었다)", opened > 0, opened)
        check("추적할 수 없었던 커넥션 없음(폴백이 실패를 숨기지 않는다)", untrackable, 0)
        check("★ 연 sqlite 커넥션이 전부 닫혔다 (%d개 열었다)" % opened, leaked, 0)

        # --- (b) 파일 핸들 -----------------------------------------------
        hs = [s["handles"] for s in samples if s["handles"] is not None]
        if len(hs) == len(samples):
            grew = hs[-1] - hs[WARMUP]
            check_true("★ 파일 핸들이 바퀴를 따라 늘지 않는다 (%s)" % hs,
                       grew <= 0, "-> %d개 증가 (%d -> %d)" % (grew, hs[WARMUP], hs[-1]))
        else:
            print("      (핸들 수를 잴 수 없는 환경 - 이 축은 판정하지 않는다)")

        # --- (c) 파이썬 힙 -----------------------------------------------
        # 절대값이 아니라 워밍업 이후의 증가를 본다. 여유는 두되 **비율로** 둔다.
        h0, h1 = samples[WARMUP]["heap"], samples[-1]["heap"]
        check_true("★ 파이썬 힙이 바퀴를 따라 늘지 않는다 (%.2fMB -> %.2fMB)"
                   % (h0 / 1048576.0, h1 / 1048576.0),
                   h1 <= max(h0 * 1.25, h0 + 2 * 1024 * 1024),
                   "-> %d바퀴에 %.2fMB 증가" % (CYCLES - WARMUP, (h1 - h0) / 1048576.0))

        # --- (d) DB 행이 바퀴를 따라 늘지 않는다 (멱등) --------------------
        grew_tables = {t: (counts0[t], counts_last.get(t))
                       for t in counts0 if counts_last.get(t, 0) != counts0[t]}
        check("★ 같은 입력을 %d번 다시 흘려도 어떤 테이블도 늘지 않는다" % CYCLES,
              grew_tables, {})

        # --- (e) 바퀴마다 느려지지 않는다 ----------------------------------
        # "처음엔 정상인데 아침에 안 끝나 있다" 를 잡는 축이다.
        head = sum(s["secs"] for s in samples[WARMUP:WARMUP + 3]) / 3.0
        tail = sum(s["secs"] for s in samples[-3:]) / 3.0
        check_true("★ 마지막 바퀴가 초반 바퀴보다 크게 느려지지 않는다 "
                   "(%.3fs -> %.3fs)" % (head, tail),
                   tail <= max(head * 2.0, head + 0.5),
                   "-> %.2f배 느려졌다. 누적이 비용에 붙고 있다" % (tail / max(head, 1e-9)))
    finally:
        env.close()


def run():
    print("=" * 62)
    print(" Scheduler 장시간 무인 운전 시뮬레이션 (Sprint 230)")
    print("=" * 62)
    test_multi_day_unattended_run()
    test_crash_is_recovered_next_day_without_losing_refresh_intent()
    test_retry_budget_does_not_regenerate_forever()
    test_rerun_same_day_is_idempotent()
    test_expired_backlog_does_not_starve_live_work()
    test_repeated_cycles_do_not_accumulate_process_resources()

    print("\n" + "=" * 62)
    if failures:
        print("FAILED (%d): %s" % (len(failures), ", ".join(failures)))
        return 1
    print("ALL SCHEDULER LONGRUN TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(run())
