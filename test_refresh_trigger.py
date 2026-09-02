"""변경 기반 재수집(Change-driven refresh) 회귀 테스트 — 2026-08-18 Sprint 189 신설.

## 이 테스트가 지키는 것

이 저장소는 재수집 **기계**를 오래전에 다 만들어 놓고도 한 번도 돌린 적이 없었다.
`collect_spec/status/appraisal/images` 전부 `overwrite=True` 경로를 갖고 있었고,
해시 비교도 `document_version_log`도 부분수집 보호도 준비돼 있었지만 —
**아무도 `overwrite=True`를 넘기지 않았다.** 큐는 한 번 `done`이 되면 영원히 `done`이라
법원이 명세서를 다시 올려도 화면은 최초 수집분을 계속 보여 줬다.

Sprint 189가 그 트리거를 붙였다. 이 파일이 검증하는 사슬:

    법원 원천 변경
      -> migrate_execute 가 필드 단위로 무엇이 바뀌었는지 판정
      -> requeue_changed_documents(): done -> 'refresh'
      -> claim_next_queue_item(): 'refresh' -> 'in_progress_refresh' + overwrite=True
      -> doc_worker -> collect_document(..., overwrite=True)
      -> 실제 재다운로드 -> previous_hash != new_hash -> document_version_log

그리고 **끊어지기 쉬운 자리**를 특히 조인다:

    재시도(mark_queue_failed)      재수집 의도가 첫 실패에서 사라지지 않는가
    stale 회수(reset_stale_queue)  비정상 종료 뒤에도 살아남는가
    형제 복사 지름길               재수집인데 옛 사본을 복사해 오지 않는가
    상한                           조용히 자르지 않는가

selenium/DB 서버 없이 돈다. 실제 `auction.db` / `documents/`는 건드리지 않는다.

    python test_refresh_trigger.py
"""
import importlib.util
import inspect
import os
import shutil
import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))

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


# ---------------------------------------------------------------------------
# 스크래치 DB — 실제 스키마를 마이그레이션에서 그대로 만든다.
#
# 테스트 안에 스키마를 손으로 베끼면 진짜 스키마가 바뀌어도 테스트는 계속 통과한다
# (test_document_queue.py 의 같은 판단). 여기서는 아예 부트스트랩 3단계를 그대로 돌린다.
# ---------------------------------------------------------------------------

def _load_runner():
    path = os.path.join(REPO_ROOT, "storage", "migrations", "run_migrations.py")
    spec = importlib.util.spec_from_file_location("qa_refresh_run_migrations", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class ScratchDB:
    """`storage.database.DB_PATH`를 임시 파일로 갈아 끼운다. 원래 값은 반드시 되돌린다."""

    def __enter__(self):
        import storage.database as dbmod
        import storage.migrate_v4_1 as v41
        self.dbmod = dbmod
        self.tmp = tempfile.mkdtemp(prefix="qa_refresh_")
        self.saved = dbmod.DB_PATH
        dbmod.DB_PATH = os.path.join(self.tmp, "t.db")
        dbmod.init_db()
        v41.migrate()
        _load_runner().run()
        return self

    def __exit__(self, *exc):
        self.dbmod.DB_PATH = self.saved
        shutil.rmtree(self.tmp, ignore_errors=True)
        return False

    def conn(self):
        c = sqlite3.connect(self.dbmod.DB_PATH)
        c.row_factory = sqlite3.Row
        return c

    def seed_item(self, court="B000210", case_no="2024타경1", item_no="1",
                  auction_date="2099-01-01"):
        """auction / auction_case / auction_item 한 벌을 만든다(문서상태 갱신 경로가 요구한다)."""
        now = datetime.now().isoformat()
        c = self.conn()
        try:
            c.execute("""INSERT INTO auction
                (court_code, court_name, case_no, item_no, auction_date, status,
                 created_at, updated_at)
                VALUES (?,?,?,?,?,?,?,?)""",
                      (court, "테스트지원", case_no, item_no, auction_date, "신건", now, now))
            c.execute("""INSERT OR IGNORE INTO auction_case
                (case_no, court_code, court_name, created_at, updated_at)
                VALUES (?,?,?,?,?)""", (case_no, court, "테스트지원", now, now))
            case_id = c.execute(
                "SELECT id FROM auction_case WHERE court_code=? AND case_no=?",
                (court, case_no)).fetchone()["id"]
            c.execute("""INSERT INTO auction_item
                (case_id, case_no, item_no, court_name, auction_date, status,
                 created_at, updated_at)
                VALUES (?,?,?,?,?,?,?,?)""",
                      (case_id, case_no, item_no, "테스트지원", auction_date, "신건", now, now))
            c.commit()
        finally:
            c.close()

    def queue_row(self, court, case_no, item_no, doc_type, status,
                  auction_date="2099-01-01", last_attempt_at=None, retry_count=0):
        c = self.conn()
        try:
            cur = c.execute("""INSERT INTO document_queue
                (court_code, case_no, item_no, doc_type, priority, auction_date,
                 status, retry_count, last_attempt_at, enqueued_at)
                VALUES (?,?,?,?,3,?,?,?,?,?)""",
                            (court, case_no, item_no, doc_type, auction_date, status,
                             retry_count, last_attempt_at, datetime.now().isoformat()))
            c.commit()
            return cur.lastrowid
        finally:
            c.close()

    def status_of(self, queue_id):
        c = self.conn()
        try:
            r = c.execute("SELECT status FROM document_queue WHERE id=?", (queue_id,)).fetchone()
            return r["status"] if r else None
        finally:
            c.close()


# ---------------------------------------------------------------------------
def test_field_to_doc_type_mapping():
    print("\n--- 1. 어떤 필드가 바뀌면 무엇을 다시 받는가 (매핑 단일 소스) ---")
    import storage.database as db

    check("매각기일 변경 -> 명세서/현황조사서",
          db.doc_types_for_changed_fields(["auction_date"]), ("spec", "status"))
    check("최저매각가격 변경 -> 명세서",
          db.doc_types_for_changed_fields(["minimum_bid_price"]), ("spec",))
    check("사건상태 변경 -> 명세서/현황조사서",
          db.doc_types_for_changed_fields(["status"]), ("spec", "status"))
    check("감정가 변경 -> 감정평가서 + 사진(재감정은 재촬영을 동반한다)",
          db.doc_types_for_changed_fields(["appraisal_price"]), ("appraisal", "image"))
    check("여러 필드는 합집합",
          db.doc_types_for_changed_fields(["auction_date", "appraisal_price"]),
          ("appraisal", "image", "spec", "status"))
    check("자산과 무관한 필드는 아무것도 되돌리지 않는다",
          db.doc_types_for_changed_fields(["full_address", "dong"]), ())
    check("빈 입력", db.doc_types_for_changed_fields(None), ())

    # 매핑이 큐가 실제로 다루는 종류만 낸다 — 오타가 들어가면 영원히 수집되지 않는
    # 유령 doc_type 이 큐에 생긴다.
    bad = sorted({t for ts in db.REFRESH_DOC_TYPES_BY_FIELD.values() for t in ts
                  if t not in db.QUEUE_TO_DOC_STATUS_TYPE})
    check("매핑의 모든 doc_type 이 큐 어휘에 있다", bad, [])

    # 사진을 기일/최저가에 넣지 않는다는 결정을 고정한다(넣으면 매일 수천 장을 다시 받는다).
    only_price = db.doc_types_for_changed_fields(
        ["auction_date", "minimum_bid_price", "status"])
    check_true("유찰(기일/최저가)만으로는 사진을 다시 받지 않는다",
               "image" not in only_price, only_price)

    # ★ 그 결정의 **대가**를 함께 못 박는다 (2026-08-18 Sprint 216).
    #
    #   `image` 로 가는 길은 `appraisal_price` **하나뿐**이다. 그런데 그 필드는
    #   실측에서 움직이지 않는다 — CSV 백업 25개(2026-07-02~08-12)로 물건별
    #   처음<->마지막을 비교하니 **0/1,228 (0.0%)** 였다(나머지 세 필드는 각 3.6%).
    #   감정평가액은 재감정이 없으면 고정이기 때문이다.
    #
    #   즉 **이미지 재수집은 41일 관측에서 한 번도 발동할 수 없었다.**
    #   "이미지가 안 바뀌었다"가 아니라 "발동할 수 없었다"이다.
    #
    #   이 검사는 그 사실을 고정한다. 매핑을 넓히려는 사람은 여기서 먼저 멈추고
    #   위 측정을 마주하게 된다 — 넓히는 것은 사진 갱신 정책 + 재크롤 부하를
    #   정하는 **제품 결정**이라 조용히 일어나면 안 된다.
    image_sources = sorted(f for f, ts in db.REFRESH_DOC_TYPES_BY_FIELD.items()
                           if "image" in ts)
    check("사진으로 가는 길은 감정가 하나뿐이다 (실측 변경률 0.0%)",
          image_sources, ["appraisal_price"])


def test_requeue_only_touches_done():
    print("\n--- 2. 재수집 예약은 done 만 되돌리고 나머지는 건드리지 않는다 ---")
    import storage.database as db

    with ScratchDB() as s:
        s.seed_item()
        ids = {}
        for doc_type, st in (("spec", "done"), ("status", "failed"),
                             ("appraisal", "SKIPPED_UNSUPPORTED"), ("image", "in_progress")):
            ids[doc_type] = s.queue_row("B000210", "2024타경1", "1", doc_type, st)

        out = db.requeue_changed_documents([{
            "court_code": "B000210", "case_no": "2024타경1", "item_no": "1",
            "fields": ["auction_date", "appraisal_price"],   # 네 종류 모두 대상이 된다
        }])

        check("되돌린 행 수", out["refreshed"], 1)
        check("대상 물건 수", out["items"], 1)
        check("done -> refresh", s.status_of(ids["spec"]), "refresh")
        check("failed 은 그대로(자기 재시도 경로가 있다)", s.status_of(ids["status"]), "failed")
        check("SKIPPED_UNSUPPORTED 는 그대로(영구 종결을 되살리지 않는다)",
              s.status_of(ids["appraisal"]), "SKIPPED_UNSUPPORTED")
        check("in_progress 는 그대로(워커가 소유 중)", s.status_of(ids["image"]), "in_progress")


def test_requeue_skips_items_whose_date_already_passed():
    """기일이 지난 물건은 되돌리지 않는다 (2026-08-18 실측으로 추가한 조건).

    되돌리면 워커가 집어가서 2차 방어선(`auction_date < today`)에 걸려 곧바로
    SKIPPED_EXPIRED 로 종결한다 — **아무것도 다시 받지 못한 채 성공 기록(done)만 잃는다.**
    실제 `auction.db` 사본으로 돌려 보다가 발견했다(대상 물건의 기일이 2026-07-15였다).
    """
    print("\n--- 3b. 기일이 지난 물건은 되돌리지 않는다 ---")
    import storage.database as db

    future = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")
    past = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")

    with ScratchDB() as s:
        s.seed_item()
        live = s.queue_row("B000210", "2024타경1", "1", "spec", "done", auction_date=future)
        gone = s.queue_row("B000210", "2024타경1", "1", "status", "done", auction_date=past)
        blank = s.queue_row("B000210", "2024타경1", "1", "appraisal", "done", auction_date="")

        out = db.requeue_changed_documents([{
            "court_code": "B000210", "case_no": "2024타경1", "item_no": "1",
            "fields": ["auction_date", "appraisal_price"],
        }])

        check("기일이 남았으면 되돌린다", s.status_of(live), "refresh")
        check("기일이 지났으면 done 그대로(성공 기록을 잃지 않는다)",
              s.status_of(gone), "done")
        check("기일을 알 수 없으면 되돌린다(단정할 근거가 없다)",
              s.status_of(blank), "refresh")
        check("되돌린 행 수", out["refreshed"], 2)


def test_requeue_revives_expired_only_when_date_moved_forward():
    print("\n--- 3. 기일 경과로 종결된 행은 기일이 미래로 다시 잡혔을 때만 되살린다 ---")
    import storage.database as db

    future = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")
    past = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")

    with ScratchDB() as s:
        s.seed_item()
        live = s.queue_row("B000210", "2024타경1", "1", "spec", "SKIPPED_EXPIRED",
                           auction_date=future)
        dead = s.queue_row("B000210", "2024타경1", "1", "status", "SKIPPED_EXPIRED",
                           auction_date=past)

        out = db.requeue_changed_documents([{
            "court_code": "B000210", "case_no": "2024타경1", "item_no": "1",
            "fields": ["auction_date"],
        }])

        check("부활한 행 수", out["revived_expired"], 1)
        # 한 번도 받은 적 없으므로 'refresh'(=overwrite)가 아니라 'pending' 이 맞다.
        check("기일이 미래면 pending 으로 부활", s.status_of(live), "pending")
        check("기일이 과거면 그대로", s.status_of(dead), "SKIPPED_EXPIRED")


def test_expired_revival_is_scoped_by_changed_field_not_by_item():
    """★ SKIPPED_EXPIRED 부활은 **doc_type이 아니라 '어떤 필드가 바뀌었나'**로 갈린다
    (2026-08-21 Sprint 252 실측, 운영 auction.db에서 재현).

    `REFRESH_DOC_TYPES_BY_FIELD["auction_date"] = ("spec", "status")`다 - appraisal/image가
    빠져 있다. 그런데 `requeue_changed_documents()`의 SKIPPED_EXPIRED->pending 부활 경로는
    `doc_types_for_changed_fields(fields)`가 돌려주는 **그 목록 안의 doc_type만** 되살린다.
    즉 유찰 후 재매각(=auction_date만 바뀌는 흔한 경우)으로는 **appraisal/image가
    SKIPPED_EXPIRED에서 절대 못 빠져나온다** - "기일이 미래로 돌아오면 되살린다"는
    §3(위 테스트)의 계약이 spec/status에는 적용되고 appraisal/image에는 적용되지 않는다.

    운영에서 실제로 걸린 사례(id=921/927/930, 광주지방법원 2024타경2065/4887/5217,
    전부 유찰 2~4회): appraisal만 2026-07-12에 SKIPPED_EXPIRED로 종결된 뒤, 기일이
    2026-08-21로 다시 잡혀도(spec/status는 정상 pending) appraisal만 여전히
    SKIPPED_EXPIRED에 갇혀 있다 - 그 물건의 감정평가서를 영구히 못 받는다.

    **이 검사는 정책을 바꾸지 않는다** - appraisal/image도 되살려야 하는지는 재수집
    정책(docs/roadmap.md 결정 대기, `test_document_queue.py:495-497` 참고)이라 제품
    판단이다. 이 검사는 **지금 실제로 이렇게 동작한다**는 사실만 잠근다 - 아무도 모르는
    사이에 이 경계가 넓어지거나 좁아지면(의도했든 실수든) 반드시 이 검사가 먼저 반응해야
    하고, 그러면 그 변경이 "정책 결정"이었는지 확인하는 계기가 된다.
    """
    print("\n--- 3-B. 부활은 doc_type이 아니라 바뀐 필드로 갈린다 (Sprint 252) ---")
    import storage.database as db

    future = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")

    with ScratchDB() as s:
        s.seed_item()
        spec = s.queue_row("B000210", "2024타경1", "1", "spec", "SKIPPED_EXPIRED",
                           auction_date=future)
        status = s.queue_row("B000210", "2024타경1", "1", "status", "SKIPPED_EXPIRED",
                             auction_date=future)
        appraisal = s.queue_row("B000210", "2024타경1", "1", "appraisal", "SKIPPED_EXPIRED",
                                auction_date=future)
        image = s.queue_row("B000210", "2024타경1", "1", "image", "SKIPPED_EXPIRED",
                            auction_date=future)

        # 실제 재매각에서 가장 흔한 변경 - auction_date만 바뀐다(감정가는 그대로).
        out = db.requeue_changed_documents([{
            "court_code": "B000210", "case_no": "2024타경1", "item_no": "1",
            "fields": ["auction_date"],
        }])

        check("부활한 행 수 (spec+status만)", out["revived_expired"], 2)
        check("spec은 되살아난다", s.status_of(spec), "pending")
        check("status도 되살아난다", s.status_of(status), "pending")
        check_true("★ appraisal은 기일이 미래인데도 SKIPPED_EXPIRED에 갇혀 있다"
                   " (auction_date 변경이 appraisal을 트리거하지 않는다)",
                   s.status_of(appraisal) == "SKIPPED_EXPIRED",
                   "-> %r (재수집 정책이 바뀌었다면 이 검사를 의도적으로 갱신할 것)"
                   % s.status_of(appraisal))
        check_true("★ image도 같은 이유로 갇혀 있다",
                   s.status_of(image) == "SKIPPED_EXPIRED",
                   "-> %r" % s.status_of(image))


def test_claim_returns_overwrite_and_separate_in_progress():
    print("\n--- 4. claim: refresh 는 overwrite=True + 별도 진행상태로 간다 ---")
    import storage.database as db

    with ScratchDB() as s:
        s.seed_item()
        pending_id = s.queue_row("B000210", "2024타경1", "1", "spec", "pending")
        item = db.claim_next_queue_item()
        check("pending 을 집는다", item["id"], pending_id)
        check("pending 은 overwrite=False", item["overwrite"], False)
        check("pending -> in_progress", s.status_of(pending_id), "in_progress")

    with ScratchDB() as s:
        s.seed_item()
        refresh_id = s.queue_row("B000210", "2024타경1", "1", "spec", "refresh")
        item = db.claim_next_queue_item()
        check("refresh 도 집는다(대기 상태로 취급)", item["id"], refresh_id)
        check("refresh 는 overwrite=True", item["overwrite"], True)
        check("refresh -> in_progress_refresh", s.status_of(refresh_id), "in_progress_refresh")

        # 두 번째 claim 은 없다 — 원자적 클레임이 같은 행을 다시 주지 않는다.
        check("이미 집어간 행은 다시 안 준다", db.claim_next_queue_item(), None)


def test_refresh_intent_survives_retry_and_stale_recovery():
    print("\n--- 5. 재수집 의도가 실패/비정상종료에서 사라지지 않는다 ---")
    import storage.database as db

    # (a) 재시도 — mark_queue_failed 가 'pending' 으로 고정하면 다음 시도는 overwrite=False 가
    #     되어 "이미 존재. 스킵"으로 조용히 성공한다. 바뀐 문서가 영원히 옛것으로 남는 경로다.
    with ScratchDB() as s:
        s.seed_item()
        rid = s.queue_row("B000210", "2024타경1", "1", "spec", "refresh")
        db.claim_next_queue_item()
        db.mark_queue_failed(rid, 0)
        check("재시도는 refresh 로 되돌아간다", s.status_of(rid), "refresh")

        pid = s.queue_row("B000210", "2024타경1", "1", "status", "pending")
        db.claim_next_queue_item()
        db.mark_queue_failed(pid, 0)
        check("최초 수집 재시도는 pending 그대로", s.status_of(pid), "pending")

    # (b) stale 회수 — 10분 넘게 진행 중인 행을 되살릴 때도 각자 제자리로.
    with ScratchDB() as s:
        s.seed_item()
        old = (datetime.now() - timedelta(minutes=30)).isoformat()
        a = s.queue_row("B000210", "2024타경1", "1", "spec", "in_progress_refresh",
                        last_attempt_at=old)
        b = s.queue_row("B000210", "2024타경1", "1", "status", "in_progress",
                        last_attempt_at=old)
        db.reset_stale_queue()
        check("in_progress_refresh -> refresh", s.status_of(a), "refresh")
        check("in_progress -> pending", s.status_of(b), "pending")


def test_max_retry_still_terminates_refresh():
    print("\n--- 6. 재수집도 재시도 예산을 무한히 쓰지 않는다 ---")
    import storage.database as db

    with ScratchDB() as s:
        s.seed_item()
        rid = s.queue_row("B000210", "2024타경1", "1", "spec", "refresh")
        db.claim_next_queue_item()
        db.mark_queue_failed(rid, db.MAX_DOC_RETRY - 1)   # 마지막 시도
        check("예산 소진 시 failed 로 종결(refresh 로 무한 순환하지 않는다)",
              s.status_of(rid), "failed")


def test_refresh_failure_does_not_destroy_what_we_already_show():
    """재수집이 실패해도 **이미 보여 주던 것**을 실패로 덮지 않는다 (2026-08-18 Sprint 189).

    재수집을 켜기 전까지 최종 실패 자리는 언제나 "한 번도 못 받은 문서"였다. 이제는
    **이미 READY인 문서를 다시 받으려다 실패**하는 경우가 생긴다(법원이 문서를 내렸거나,
    버튼 DOM이 바뀌었거나, 그날 서버가 불안정했거나).

    그때 화면 상태를 FAILED로 쓰면 — 화면은 "수집실패"인데 파일 서빙은 여전히 200으로
    옛 문서를 내려 준다. 사용자 입장에서는 **볼 수 있던 것이 갑자기 사라지는** 순수한
    퇴행이고, 화면과 실체가 갈라지는 BUGS #50 계열이다.

    대조군을 함께 고정한다 — **한 번도 못 받은 문서**의 최종 실패는 지금처럼 FAILED다.
    구분하지 못하면 이 검사는 공허하다.
    """
    print("\n--- 6b. 재수집 실패가 이미 가진 자산을 지우지 않는다 ---")
    import storage.database as db

    def screen_status(s, doc_type):
        c = s.conn()
        try:
            r = c.execute(
                "SELECT status FROM document_status WHERE item_id=1 AND doc_type=?",
                (db.QUEUE_TO_DOC_STATUS_TYPE[doc_type],)).fetchone()
            return r["status"] if r else None
        finally:
            c.close()

    def set_screen(s, doc_type, status):
        c = s.conn()
        try:
            c.execute("INSERT OR REPLACE INTO document_status (item_id, doc_type, status,"
                      " updated_at) VALUES (1, ?, ?, ?)",
                      (db.QUEUE_TO_DOC_STATUS_TYPE[doc_type], status,
                       datetime.now().isoformat()))
            c.commit()
        finally:
            c.close()

    for held, doc_type, expected in (("READY", "spec", "READY"),
                                     ("NO_IMAGE", "image", "NO_IMAGE"),
                                     ("COLLECTING", "appraisal", "FAILED")):
        with ScratchDB() as s:
            s.seed_item()
            set_screen(s, doc_type, held)
            rid = s.queue_row("B000210", "2024타경1", "1", doc_type, "refresh")
            db.claim_next_queue_item()
            db.mark_queue_failed(rid, db.MAX_DOC_RETRY - 1)   # 최종 실패

            check("화면 %s 인 상태에서 재수집 최종 실패 -> %s" % (held, expected),
                  screen_status(s, doc_type), expected)
            # 실패 사실 자체는 큐에 그대로 남는다(조용히 묻히지 않는다).
            check("큐는 어느 경우든 failed 로 남는다 (%s)" % held, s.status_of(rid), "failed")


def test_priority_refresh_covers_refresh_rows():
    print("\n--- 7. 우선순위 재계산이 refresh 행을 빠뜨리지 않는다 ---")
    import storage.database as db

    with ScratchDB() as s:
        s.seed_item()
        today = datetime.now().strftime("%Y-%m-%d")
        rid = s.queue_row("B000210", "2024타경1", "1", "spec", "refresh", auction_date=today)
        changed = db.refresh_queue_priority()
        c = s.conn()
        try:
            pr = c.execute("SELECT priority FROM document_queue WHERE id=?", (rid,)).fetchone()[0]
        finally:
            c.close()
        check_true("refresh 행도 재계산 대상이다", changed >= 1, changed)
        check("임박 물건이 최우선 순위로 올라간다", pr, db.calc_priority(today))


def test_cap_is_loud_not_silent():
    print("\n--- 8. 상한은 조용히 자르지 않는다 ---")
    import storage.database as db

    with ScratchDB() as s:
        s.seed_item(case_no="2024타경1")
        s.seed_item(case_no="2024타경2")
        for case_no in ("2024타경1", "2024타경2"):
            s.queue_row("B000210", case_no, "1", "spec", "done")

        changes = [{"court_code": "B000210", "case_no": c, "item_no": "1",
                    "fields": ["auction_date"]} for c in ("2024타경1", "2024타경2")]
        out = db.requeue_changed_documents(changes, max_items=1)
        check("상한만큼만 처리한다", out["items"], 1)
        check("잘린 건수를 반환값에 남긴다", out["skipped_over_cap"], 1)
        # 잘린 쪽은 done 그대로 남아 다음 실행의 후보가 된다(유실 아님).
        check("되돌린 행", out["refreshed"], 1)

    check_true("기본 상한이 정의돼 있다",
               isinstance(db.REFRESH_MAX_ITEMS_PER_RUN, int) and db.REFRESH_MAX_ITEMS_PER_RUN > 0,
               db.REFRESH_MAX_ITEMS_PER_RUN)


# ---------------------------------------------------------------------------
# doc_worker 배선 검증용 공통 대역
# ---------------------------------------------------------------------------

def test_cap_no_longer_drops_changed_items():
    """상한이 **의도 기록**에서 사라졌다 - 바뀐 물건은 전부 예약된다 (BUGS #278).

    ## 방향이 뒤집혔다

    이 자리는 원래 정반대를 고정하고 있었다 — *"잘린 물건은 끝내 예약되지 않는다
    (유실이다)"*. 그 검사는 고쳐지는 날 실패하도록 일부러 그렇게 썼고, 그 날이 왔다.

    ## 무엇이 달라졌나

    상한 60 의 근거는 **워커가 하룻밤에 처리할 수 있는 양**이다. 그건 소비의 한계인데
    생산(큐에 적는 일) 쪽에 걸려 있었다. 잘린 물건은 `auction_item` 이 이미 갱신돼
    다음 실행의 `changes` 에 들어오지 못했다 — 미룬 것이 아니라 잃은 것이었다.

    이제 전부 적는다. 소비 쪽은 이미 스스로 제한한다(워커 창 + 긴급도 순 claim).

    ## 그래도 상한이 필요한 곳은 남는다

    `max_items` 를 **명시적으로** 넘기면 여전히 조인다 — 운영자 수동 실행과 검사용이다.
    그 경로가 살아 있는지도 함께 건다(§8 과 짝).
    """
    print("\n--- 8-B. 바뀐 물건은 상한과 무관하게 전부 예약된다 (#278) ---")
    import contextlib
    import io as _io
    import storage.database as db

    ITEMS = 5
    CAP = 3

    with ScratchDB() as s:
        cases = ["2024타경%d" % (i + 1) for i in range(ITEMS)]
        for case_no in cases:
            s.seed_item(case_no=case_no)
            s.queue_row("B000210", case_no, "1", "spec", "done")

        import importlib
        import migrate_execute as me
        importlib.reload(me)
        me.get_connection = s.conn

        def run_pipeline():
            with contextlib.redirect_stdout(_io.StringIO()):
                me.execute()

        def refresh_rows():
            c = s.conn()
            try:
                return c.execute(
                    "SELECT COUNT(*) FROM document_queue WHERE status='refresh'"
                ).fetchone()[0]
            finally:
                c.close()

        def refreshed_cases():
            c = s.conn()
            try:
                return sorted(r[0] for r in c.execute(
                    "SELECT DISTINCT case_no FROM document_queue WHERE status='refresh'"))
            finally:
                c.close()

        def bump_price(value):
            c = s.conn()
            try:
                c.execute("UPDATE auction SET minimum_bid_price=?", (value,))
                c.commit()
            finally:
                c.close()

        saved_cap = db.REFRESH_MAX_ITEMS_PER_RUN
        db.REFRESH_MAX_ITEMS_PER_RUN = CAP      # 하룻밤 처리량 추정치를 낮춰 둔다
        try:
            run_pipeline()
            check("시작 시점 refresh 행", refresh_rows(), 0)

            bump_price(50000000)
            run_pipeline()
            check("★★ 하룻밤 처리량(%d)을 넘어도 **전부** 예약된다" % CAP,
                  refresh_rows(), ITEMS)
            check("★★ 특정 물건만 뽑히지 않는다 - 바뀐 물건 전부다",
                  refreshed_cases(), sorted(cases))

            # 처리량을 넘는다는 사실은 **로그로** 알린다(자르지 않고).
            # 값이 그대로면 다시 예약하지 않는다 - 멱등하다.
            before = refresh_rows()
            run_pipeline()
            check("값이 그대로면 예약이 늘지 않는다(멱등)", refresh_rows(), before)

            # ★ 명시적 상한은 **여전히 동작한다** - 운영자 수동 실행용 경로다.
            c = s.conn()
            try:
                c.execute("UPDATE document_queue SET status='done'")
                c.commit()
            finally:
                c.close()
            changes = [{"court_code": "B000210", "case_no": cn, "item_no": "1",
                        "fields": ["auction_date"]} for cn in cases]
            out = db.requeue_changed_documents(changes, max_items=2)
            check("★ max_items 를 넘기면 그만큼만 예약한다", out["items"], 2)
            check("★ 제외된 건수를 반환값에 남긴다", out["skipped_over_cap"], ITEMS - 2)

            # 기본 실행(=인자 없음)은 **자르지 않는다.**
            c = s.conn()
            try:
                c.execute("UPDATE document_queue SET status='done'")
                c.commit()
            finally:
                c.close()
            out2 = db.requeue_changed_documents(changes)
            check("★★ 기본 실행은 자르지 않는다", out2["items"], ITEMS)
            check("★★ 그래서 제외 건수가 0 이다", out2["skipped_over_cap"], 0)
        finally:
            db.REFRESH_MAX_ITEMS_PER_RUN = saved_cap


class _FakeDriver:
    def quit(self):
        pass


def _run_doc_worker(patches):
    """doc_worker.main() 을 대역으로 감싸 한 번 돌린다. 원래 속성은 반드시 되돌린다."""
    import doc_worker

    base = {
        "init_db": lambda: None,
        "reset_stale_queue": lambda: None,
        "build_download_driver": lambda: _FakeDriver(),
        "get_doc_button_id": lambda doc_type, item_no: "qa-btn",
        "go_to_case_detail": lambda *a, **kw: True,
        "mark_queue_done": lambda *a, **kw: None,
        "mark_queue_failed": lambda *a, **kw: None,
        "mark_queue_skipped_expired": lambda *a, **kw: None,
        "mark_queue_unsupported": lambda *a, **kw: None,
        "reconcile_queue_auction_date": lambda *a, **kw: a[3],
        "save_auction_images": lambda *a, **kw: {"saved": 0, "skipped_missing": 0,
                                                 "removed_stale": 0},
        "find_sibling_case_document": lambda *a, **kw: None,
    }
    base.update(patches)

    saved = {}
    for k, v in base.items():
        saved[k] = getattr(doc_worker, k)
        setattr(doc_worker, k, v)
    old_env = os.environ.get("DOC_WORKER_TEST_MODE")
    os.environ["DOC_WORKER_TEST_MODE"] = "1"
    old_sleep = doc_worker.time_module.sleep
    doc_worker.time_module.sleep = lambda *_a, **_k: None
    try:
        return doc_worker.main()
    finally:
        doc_worker.time_module.sleep = old_sleep
        for k, v in saved.items():
            setattr(doc_worker, k, v)
        if old_env is None:
            os.environ.pop("DOC_WORKER_TEST_MODE", None)
        else:
            os.environ["DOC_WORKER_TEST_MODE"] = old_env
        try:
            os.remove(doc_worker.LOCK_PATH)
        except OSError:
            pass


def _claim(queue_id, case_no, doc_type, overwrite):
    return {"id": queue_id, "court_code": "B000210", "case_no": case_no, "item_no": "1",
            "doc_type": doc_type, "retry_count": 0, "auction_date": "2099-01-01",
            "status": "in_progress_refresh" if overwrite else "in_progress",
            "overwrite": overwrite}


def test_overwrite_reaches_the_collector():
    print("\n--- 9. overwrite 가 실제로 수집기까지 도달한다 (계약 + 배선) ---")
    from crawler.doc_crawler import collect_document

    # (a) 계약: 수집기가 overwrite 를 받는다
    sig = inspect.signature(collect_document)
    check_true("collect_document(overwrite=) 인자가 있다", "overwrite" in sig.parameters,
               sorted(sig.parameters))

    # (b) 배선: doc_worker 가 claim 결과를 그대로 넘긴다
    seen = []
    claims = [_claim(1, "2024타경1", "spec", True), _claim(2, "2024타경2", "spec", False)]

    def fake_collect(driver, court_code, case_no, item_no, doc_type, btn_id, overwrite=False):
        seen.append((case_no, overwrite))
        return {"success": True, "previous_hash": "", "new_hash": "h", "partial": False}

    _run_doc_worker({
        "claim_next_item_rows": lambda: ([claims.pop(0)] if claims else []),
        "collect_document": fake_collect,
    })

    check("재수집 항목은 overwrite=True 로, 최초 수집은 False 로 내려간다",
          seen, [("2024타경1", True), ("2024타경2", False)])


def test_refresh_skips_sibling_shortcut():
    print("\n--- 10. 재수집일 때는 형제 물건 사본을 복사해 오지 않는다 ---")
    # 형제 사본도 **같은 옛 수집분**이다. 복사해 오면 법원이 갱신한 새 문서 대신 옛
    # 내용을 다시 저장하고 큐는 done 이 되어 재수집 기회가 사라진다.
    sibling_lookups = []
    seen = []
    claims = [_claim(1, "2024타경1", "status", True), _claim(2, "2024타경2", "status", False)]

    def fake_sibling(court_code, case_no, item_no, doc_type, **kw):
        sibling_lookups.append(case_no)
        return "/qa/sibling/dir"

    def fake_collect(driver, court_code, case_no, item_no, doc_type, btn_id, overwrite=False):
        seen.append((case_no, driver is None, overwrite))
        # driver 가 None 이면 형제 복사 경로다 — 그때만 reused_from 을 채운다.
        return {"success": True, "previous_hash": "", "new_hash": "h", "partial": False,
                "reused_from": "/qa/sibling/dir" if driver is None else ""}

    _run_doc_worker({
        "claim_next_item_rows": lambda: ([claims.pop(0)] if claims else []),
        "collect_document": fake_collect,
        "find_sibling_case_document": fake_sibling,
    })

    check("재수집 건은 형제 조회 자체를 하지 않는다", sibling_lookups, ["2024타경2"])
    check("재수집은 실제 브라우저 수집, 최초 수집은 형제 복사",
          seen, [("2024타경1", False, True), ("2024타경2", True, False)])


def test_queue_status_vocabulary_is_single_sourced():
    print("\n--- 11. 큐 상태 어휘가 한 곳에서만 정의된다 (BUGS #119 계열 방지) ---")
    import storage.database as db

    check("claim 매핑과 복귀 매핑이 서로의 역이다",
          {v: k for k, v in db.QUEUE_CLAIM_STATUS.items()}, db.QUEUE_RESUME_STATUS)
    check("집을 수 있는 상태 = claim 매핑의 키",
          set(db.QUEUE_CLAIMABLE_STATUSES), set(db.QUEUE_CLAIM_STATUS))
    check("진행 상태 = claim 매핑의 값",
          set(db.QUEUE_IN_PROGRESS_STATUSES), set(db.QUEUE_CLAIM_STATUS.values()))
    check("overwrite 상태는 refresh 계열 둘뿐",
          set(db.QUEUE_OVERWRITE_STATUSES), {"refresh", "in_progress_refresh"})
    check("placeholder 개수가 상태 개수와 같다",
          db.QUEUE_CLAIMABLE_PLACEHOLDERS.count("?"), len(db.QUEUE_CLAIMABLE_STATUSES))

    # 적체를 세는 쪽이 새 어휘를 흘리지 않는가 — 하드코딩 목록이 남아 있으면 여기서 걸린다.
    import measure_endless_collecting as mec
    check("measure_endless_collecting 이 단일 소스를 쓴다",
          mec.ACTIVE_QUEUE, set(db.QUEUE_ACTIVE_STATUSES))

    src = open(os.path.join(REPO_ROOT, "api", "v1", "doc_stats.py"), encoding="utf-8-sig").read()
    hardcoded = [lit for lit in ('"pending"', "'pending'", '"in_progress"', "'in_progress'")
                 if lit in src]
    check("doc_stats 가 큐 상태 문자열을 하드코딩하지 않는다", hardcoded, [])


def test_migrate_execute_wires_the_trigger():
    print("\n--- 12. 매일 배치가 실제로 트리거를 부른다 (관측 -> 행동) ---")
    import migrate_execute

    src = inspect.getsource(migrate_execute)
    check_true("migrate_execute 가 requeue_changed_documents 를 호출한다",
               "requeue_changed_documents(changed_items)" in src, "호출부 없음")
    check_true("커밋 뒤에 부른다",
               src.index("conn.commit()") < src.index("requeue_changed_documents(changed_items)"),
               "커밋 전에 부르면 방금 갱신한 값을 못 본다")
    check_true("재수집 예약 실패가 매일 크롤링을 실패로 만들지 않는다",
               "재수집 예약 실패" in src, "예외 격리 없음")

    # 스위치는 기본 켬이다 — 없으면 최초 1회 수집으로 끝나는 것이 곧 제품 결함이다.
    old = os.environ.pop(migrate_execute.REFRESH_ON_CHANGE_ENV, None)
    try:
        check("미설정이면 켜져 있다", migrate_execute.refresh_on_change_enabled(), True)
        os.environ[migrate_execute.REFRESH_ON_CHANGE_ENV] = "0"
        check("'0' 이면 꺼진다", migrate_execute.refresh_on_change_enabled(), False)
        os.environ[migrate_execute.REFRESH_ON_CHANGE_ENV] = "false"
        check("'false' 도 꺼진다", migrate_execute.refresh_on_change_enabled(), False)
        os.environ[migrate_execute.REFRESH_ON_CHANGE_ENV] = "1"
        check("'1' 이면 켜진다", migrate_execute.refresh_on_change_enabled(), True)
    finally:
        os.environ.pop(migrate_execute.REFRESH_ON_CHANGE_ENV, None)
        if old is not None:
            os.environ[migrate_execute.REFRESH_ON_CHANGE_ENV] = old


def test_daily_enqueue_does_not_clobber_pending_refresh():
    """매일 06:00 `enqueue_documents()` 가 대기 중인 `refresh` 를 지우지 않는가.

    ## 왜 이 자리가 위험한가

    재수집 예약은 **09:00 전후**(크롤 -> migrate)에 붙고, 그것을 소진하는 doc_worker 는
    **다음 날 02:00**에 돈다. 그 사이에 06:00 `enqueue_documents()` 가 한 번 지나간다.
    즉 모든 refresh 행은 **반드시 enqueue 를 한 번 통과한다** — 여기서 상태가 덮이면
    재수집은 실행되기도 전에 사라진다.

    `INSERT OR IGNORE` 라 새로 넣지는 않지만, 그 뒤에 기존 행의 `auction_date`/`priority`
    를 갱신하는 UPDATE 가 있다(Sprint 74). 그 UPDATE 가 status 를 건드리지 않는다는 것이
    지금은 주석으로만 보장돼 있었다. 여기서 고정한다.

    기일이 바뀌는 경우와 안 바뀌는 경우를 **둘 다** 본다 — UPDATE 가 실제로 실행되는
    경로를 지나야 의미가 있다.
    """
    print("\n--- 13. 매일 enqueue 가 대기 중인 refresh 를 덮지 않는다 ---")
    import storage.database as db

    future = (datetime.now() + timedelta(days=40)).strftime("%Y-%m-%d")
    later = (datetime.now() + timedelta(days=60)).strftime("%Y-%m-%d")

    with ScratchDB() as s:
        s.seed_item()
        keep = s.queue_row("B000210", "2024타경1", "1", "spec", "refresh",
                           auction_date=future)
        moved = s.queue_row("B000210", "2024타경1", "1", "status", "refresh",
                            auction_date=future)
        plain = s.queue_row("B000210", "2024타경1", "1", "appraisal", "pending",
                            auction_date=future)

        out = db.enqueue_documents([{
            "court_code": "B000210", "case_no": "2024타경1", "item_no": "1",
            "auction_date": later,          # 기일이 바뀌어 UPDATE 경로를 실제로 탄다
        }])

        check("기일 갱신이 실제로 일어났다(검사가 UPDATE 경로를 지났다)",
              out["refreshed"] >= 2, True)
        check("refresh 가 그대로 남는다", s.status_of(keep), "refresh")
        check("기일이 바뀐 refresh 도 그대로", s.status_of(moved), "refresh")
        check("pending 도 그대로", s.status_of(plain), "pending")

        c = s.conn()
        try:
            rows = {r["doc_type"]: r["auction_date"] for r in c.execute(
                "SELECT doc_type, auction_date FROM document_queue")}
        finally:
            c.close()
        check("refresh 행의 기일도 최신값으로 따라간다", rows["spec"], later)

        # 기일이 그대로인 날(UPDATE 가 아무 행도 안 건드리는 날)에도 마찬가지다.
        out2 = db.enqueue_documents([{
            "court_code": "B000210", "case_no": "2024타경1", "item_no": "1",
            "auction_date": later,
        }])
        check("같은 기일이면 갱신 0건", out2["refreshed"], 0)
        check("그래도 refresh 는 그대로", s.status_of(keep), "refresh")


def test_doc_stats_counts_every_queue_status():
    """`GET /api/v1/document-stats` 가 **새 어휘를 어느 칸에도 안 흘리는가**.

    §11 은 소스에 하드코딩이 없는지를 본다. 여기서는 **실제로 호출해** 숫자를 맞춘다.
    두 검사가 필요한 이유: 하드코딩을 없애도 합산 대상을 잘못 고르면 여전히 틀린다.

    실 `auction.db` 는 건드리지 않는다 — 스크래치 DB 에 네 상태를 전부 심는다.
    `test_api_regression.py` 의 같은 검사는 실 DB 를 보므로 refresh 행이 0인 동안
    **틀렸는데도 통과할 수 있다**(BUGS #119 계열). 그 공백을 이 절이 메운다.
    """
    print("\n--- 14. doc-stats 가 모든 큐 상태를 센다 (스크래치 DB) ---")
    from fastapi.testclient import TestClient
    from fastapi import FastAPI
    from api.v1.doc_stats import router as doc_stats_router
    import storage.database as db

    with ScratchDB() as s:
        s.seed_item()
        plan = {
            "pending": 3,
            "refresh": 2,
            "in_progress": 1,
            "in_progress_refresh": 4,
            "failed": 5,
        }
        n = 0
        for status, count in plan.items():
            for _ in range(count):
                n += 1
                # 같은 (법원,사건,물건,문서) 는 UNIQUE 라 사건번호를 흘려 준다.
                s.queue_row("B000210", "2024타경%d" % n, "1", "spec", status)

        app = FastAPI()
        app.include_router(doc_stats_router, prefix="/api/v1")
        body = TestClient(app).get("/api/v1/document-stats").json()

        check("queue_pending", body["queue_pending"], plan["pending"])
        check("queue_refresh", body["queue_refresh"], plan["refresh"])
        check("queue_in_progress = 진행 두 갈래의 합",
              body["queue_in_progress"],
              plan["in_progress"] + plan["in_progress_refresh"])
        check("queue_failed", body["queue_failed"], plan["failed"])

        # 어느 칸에도 안 들어간 행이 없어야 한다 — 이것이 이 검사의 핵심이다.
        counted = (body["queue_pending"] + body["queue_refresh"]
                   + body["queue_in_progress"] + body["queue_failed"])
        check("적재된 모든 행이 어느 칸엔가 잡힌다", counted, sum(plan.values()))

        # 기존 필드가 사라지지 않았는지(Breaking Change 금지)
        for key in ("total_items", "spec_success", "total_failures",
                    "queue_pending", "queue_in_progress", "queue_failed"):
            check_true("기존 필드 유지: %s" % key, key in body, sorted(body))


def test_concurrent_claim_never_duplicates_and_never_lies():
    """동시 claim: **중복 claim 0** 이고, 진 쪽을 "큐 비었음"으로 오해하지 않는다.

    ## 두 가지를 한 번에 본다 (2026-08-18 Sprint 191, BUGS #130)

    (1) **중복 claim 이 없다** — 같은 행을 둘이 집으면 같은 문서를 두 번 받고,
        두 번째 `mark_queue_done` 이 첫 번째 결과를 덮는다. 원자적 클레임
        (`UPDATE ... WHERE id=? AND status=<집을 때 본 값>`)이 이것을 막는다.

    (2) **진 쪽이 None 을 받아서는 안 된다(행이 남아 있는 한)** — 예전에는 경쟁에서
        지면 곧바로 None 이었고, `doc_worker.main()` 은 None 을 "대기열 비어있음"으로
        읽어 **그 실행 전체를 끝냈다.** claim 충돌 한 번이 그날 남은 큐를 통째로
        다음 날로 미루고, 로그에는 사실이 아닌 "대기열 비어있음"이 남았다.

        실측(수정 전, 스레드 12 / 대기 행 4): 중복 claim 0건으로 (1)은 정상이었지만
        **행이 남아 있는데 None 을 받은 스레드가 9개**였고 claim 성공은 3건뿐이었다.
        수정 후 4건 전부 claim 된다.

    `doc_worker` 는 락 파일로 동시 실행을 막지만, 5시간 stale 락 회수 경로와
    운영자의 수동 실행이 겹치는 창이 있다 — 그때 이 방어가 쓰인다.
    """
    print("\n--- 15. 동시 claim: 중복 없음 + 거짓 '큐 비었음' 없음 ---")
    import threading
    import storage.database as db

    N_ROWS, N_THREADS = 4, 12

    with ScratchDB() as s:
        s.seed_item()
        ids = [s.queue_row("B000210", "2024타경%d" % i, "1", "spec", "pending")
               for i in range(N_ROWS)]

        got, errors = [], []
        barrier = threading.Barrier(N_THREADS)

        def worker():
            try:
                barrier.wait()
                r = db.claim_next_queue_item()
                got.append(r["id"] if r else None)
            except Exception as exc:      # noqa: BLE001
                errors.append("%s: %s" % (type(exc).__name__, exc))

        threads = [threading.Thread(target=worker) for _ in range(N_THREADS)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        claimed = [g for g in got if g is not None]

        check("예외 없이 끝난다", errors, [])
        check("중복 claim 이 없다", len(claimed), len(set(claimed)))
        check("남은 행을 전부 집어간다(거짓 '비었음' 없음)",
              sorted(claimed), sorted(ids))
        check("행보다 많은 스레드는 정직하게 빈손", len(got) - len(claimed),
              N_THREADS - N_ROWS)

        c = s.conn()
        try:
            dist = {r["status"]: r["n"] for r in c.execute(
                "SELECT status, COUNT(*) n FROM document_queue GROUP BY status")}
        finally:
            c.close()
        check("모든 행이 진행 상태로 넘어갔다", dist, {"in_progress": N_ROWS})

    # 재수집 행도 같은 방어를 받는가 — 어휘가 늘었으니 함께 본다.
    with ScratchDB() as s:
        s.seed_item()
        rid = s.queue_row("B000210", "2024타경R", "1", "spec", "refresh")
        results = []
        barrier2 = threading.Barrier(4)

        def worker2():
            barrier2.wait()
            results.append(db.claim_next_queue_item())

        ts = [threading.Thread(target=worker2) for _ in range(4)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()

        won = [r for r in results if r]
        check("refresh 행도 정확히 한 번만 집힌다", len(won), 1)
        check("이긴 쪽은 overwrite=True 를 받는다", won[0]["overwrite"], True)
        check("행 상태는 in_progress_refresh", s.status_of(rid), "in_progress_refresh")


def test_every_volatile_field_is_observed_or_derived():
    """★ 구조적 가드: **사용자에게 보이는 변동 필드**가 전부 변경 감지에 닿는가.

    ## 왜 목록이 아니라 규칙인가

    목표는 매각기일·최저가·상태·**유찰횟수**·감정가의 변경 감지를 요구한다. 그런데
    `migrate_execute()` 가 실제로 비교하는 것은 **네 개**다:

        auction_date / minimum_bid_price / status / appraisal_price

    `fail_count`(유찰횟수)와 `bid_rate` 는 목록에 없다. 빠뜨린 것이 아니라
    **파생 필드**이기 때문이다 — 관측 대상에서 순수 함수로 계산된다:

        fail_count = extract_fail_count(status)
        bid_rate   = calc_bid_rate(appraisal_price, minimum_bid_price)

    즉 이 둘은 **입력이 안 바뀌면 절대 안 바뀐다.** 그래서 따로 관측할 필요가 없다.

    이 검사는 그 논증을 **코드로 고정**한다. 파생 관계가 깨지는 순간
    (예: fail_count 가 status 와 무관한 다른 입력을 받게 되면) 여기서 실패한다 —
    그때는 관측 목록에 추가해야 한다는 뜻이다.
    """
    print("\n--- 16. 변동 필드가 전부 관측되거나 파생이다 ---")
    import inspect
    import migrate_execute as me
    import storage.database as db

    OBSERVED = ("auction_date", "minimum_bid_price", "status", "appraisal_price")

    # (1) 관측 목록이 실제 소스와 일치하는가 — 검사에 목록을 복제해 두면 갈라진다.
    src = inspect.getsource(me.execute)
    block = src[src.index("for _f, _old, _new in ("):]
    # 튜플이 끝나는 지점까지만 자른다. 단순히 첫 ")" 를 찾으면 `existing["..."]` 안쪽에서
    # 잘려 뒤쪽 필드를 못 본다(처음 작성했을 때 실제로 그렇게 3건이 거짓 FAIL 났다).
    block = block[:block.index("):")]
    for name in OBSERVED:
        check_true("%s 를 실제로 비교한다" % name, '("%s"' % name in block, block[:200])

    # (2) 파생 필드는 **오직 관측 대상만** 입력으로 받는다.
    check("fail_count 의 입력은 status 하나",
          list(inspect.signature(me.extract_fail_count).parameters), ["status"])
    check("bid_rate 의 입력은 감정가/최저가",
          list(inspect.signature(me.calc_bid_rate).parameters), ["appraisal", "minimum"])

    # (3) 파생이 **순수 함수**인가 — 같은 입력이면 같은 출력(관측만으로 충분하다는 근거).
    for status_text in ("신건", "유찰", "유찰 1회", "유찰 9회", "", None):
        a = me.extract_fail_count(status_text)
        b = me.extract_fail_count(status_text)
        check("fail_count(%r) 가 결정적이다" % (status_text,), a, b)

    # (4) 실제로 유찰횟수가 오르면 **status 가 반드시 함께 바뀐다**(그래서 감지된다).
    check("유찰 4회 -> 5회 는 status 문자열이 다르다",
          me.extract_fail_count("유찰 4회") != me.extract_fail_count("유찰 5회"), True)
    check_true("그 두 status 는 서로 다른 문자열이다", "유찰 4회" != "유찰 5회")

    # (5) 파생 필드만 바뀌는 일은 구조적으로 불가능하다 — status 가 같으면 fail_count 도 같다.
    same = {me.extract_fail_count("유찰 3회") for _ in range(5)}
    check("같은 status 에서 fail_count 는 항상 같다", len(same), 1)

    # (6) 관측 대상 4개가 전부 재수집 매핑에 연결돼 있는가(관측만 하고 행동이 없으면 무의미).
    unmapped = [f for f in OBSERVED if not db.doc_types_for_changed_fields([f])]
    check("관측하는 모든 필드가 재수집 대상을 갖는다", unmapped, [])


def test_refresh_cap_fits_the_execution_window():
    """★ 구조적 가드: **재수집 상한의 최악 소요가 실행 창을 넘지 않는다.**

    ## 왜 숫자가 아니라 산술을 고정하나

    `REFRESH_MAX_ITEMS_PER_RUN` 은 처음에 **근거 없이 300** 으로 정해져 있었다.
    2026-08-18 에 재 보니 최악 소요가 8.0시간 — 실행 창(2시간)의 **400%** 였다
    (BUGS #134). 상한이 창을 넘으면 상한이 상한 노릇을 못 한다.

    숫자만 60 으로 바꾸면 다음에 누가 창을 줄이거나(END_TIME), 수집이 느려지거나
    (DOC_COLLECT_SECONDS_PER_ROW), 재수집 대상 종류를 늘리면(REFRESH_DOC_TYPES_BY_FIELD)
    **조용히 다시 넘친다.** 그래서 네 상수의 관계를 검사한다.

        상한 x (물건당 최악 행 수) x (행당 초) <= 실행 창

    ## 왜 평균이 아니라 최악인가

    어느 필드가 바뀔지 미리 알 수 없다. 평균으로 잡으면 "기일·최저가·상태·감정가가
    한꺼번에 바뀐 날"에 창을 넘는데, 그런 날이 바로 재수집이 가장 필요한 날이다.

    ## 이 검사가 잡지 못하는 것 (정직하게)

    `DOC_COLLECT_SECONDS_PER_ROW` 는 **실측을 사람이 옮겨 적은 값**이다. 실제 수집이
    느려졌는데 이 상수를 갱신하지 않으면 검사는 통과하면서 현실은 넘친다.
    그 갱신은 운영 로그를 봐야 알 수 있고, 여기서 자동으로 확인할 방법은 없다.
    """
    print("\n--- 17. 재수집 상한이 실행 창 안에 들어간다 (BUGS #134) ---")
    from config.settings import (DOC_WORKER_START_TIME, DOC_WORKER_END_TIME,
                                 DOC_COLLECT_SECONDS_PER_ROW)
    import storage.database as db

    def _hhmm(v):
        h, m = v.split(":")
        return int(h) * 3600 + int(m) * 60

    window = _hhmm(DOC_WORKER_END_TIME) - _hhmm(DOC_WORKER_START_TIME)
    check_true("실행 창이 양수다", window > 0, (DOC_WORKER_START_TIME, DOC_WORKER_END_TIME))

    worst_rows_per_item = len({t for ts in db.REFRESH_DOC_TYPES_BY_FIELD.values()
                               for t in ts})
    check_true("물건당 최악 행 수를 실제로 구했다", worst_rows_per_item >= 1,
               db.REFRESH_DOC_TYPES_BY_FIELD)

    worst = (db.REFRESH_MAX_ITEMS_PER_RUN * worst_rows_per_item
             * DOC_COLLECT_SECONDS_PER_ROW)
    print("    창 %d초 / 상한 %d물건 x %d행 x %.1f초 = %.0f초 (%.0f%%)"
          % (window, db.REFRESH_MAX_ITEMS_PER_RUN, worst_rows_per_item,
             DOC_COLLECT_SECONDS_PER_ROW, worst, worst / window * 100))
    check_true("상한의 최악 소요가 실행 창을 넘지 않는다", worst <= window,
               "%.0f초 > %d초 - 상한을 낮추거나 창을 늘려야 한다" % (worst, window))

    # 상한이 0 이면 재수집이 아예 안 돈다 — "안전"이 아니라 기능 정지다.
    check_true("상한이 0 이 아니다", db.REFRESH_MAX_ITEMS_PER_RUN > 0,
               db.REFRESH_MAX_ITEMS_PER_RUN)

    # 한 번도 못 받은 물건이 밀리지 않도록, 창의 전부를 재수집에 쓰지 않는다.
    check_true("재수집이 창의 90%를 넘게 쓰지 않는다(최초 수집분 여유)",
               worst <= window * 0.9,
               "%.0f초 / 창 %d초 = %.0f%%" % (worst, window, worst / window * 100))


def test_every_refresh_capability_is_actually_wired():
    """★ 구조적 가드: 재수집 사슬의 각 능력이 **실행 경로에서 실제로 호출되는가.**

    ## 왜 이 검사가 필요한가

    이 저장소가 반복해 겪은 최악의 결함 유형은 "고장"이 아니라 **"만들었는데 아무도
    안 부른다"** 였다.

        Sprint 144  doc_raw 를 채우는 코드가 있는데 운영 경로에 없었다(556행 -> 0행)
        Sprint 150  get_auction_images() 가 참조 0건이었다
        Sprint 189  collect_document(overwrite=True) 경로가 완성돼 있는데
                    **아무도 True 를 넘기지 않았다** — 재수집이 통째로 죽어 있었다

    셋 다 **테스트는 전부 통과하고 있었다.** 함수를 직접 호출해 검사했기 때문이다.
    그래서 여기서는 함수의 동작이 아니라 **배선**을 본다: 운영 진입점에서 출발해
    호출 그래프를 따라가며 각 능력에 도달하는지 확인한다.

    ## 방법

    AST 로 모듈별 "이 함수가 부르는 이름들"을 만들고, 진입점에서 도달 가능한 이름
    집합을 구한다. 목록을 손으로 적지 않는다 — 도달 불가면 어느 링크가 끊겼는지 나온다.
    
    ## 이 검사가 잡지 못하는 것 (정직하게)

    "어딘가에서 호출된다"까지만 본다. 호출하는 쪽이 **자기도 죽은 함수**라면 이 검사는
    통과한다(간접 죽은 코드). 완전한 도달성 분석은 진입점에서 전이적으로 따라가야 하는데,
    동적 디스패치가 섞이면 정확히 하기 어렵다. 여기서 잡으려는 것은 **Sprint 189 형태의
    결함** - "만들어 놓고 배선을 아예 안 한" 경우 - 이고 그것은 이 수준에서 잡힌다.
    """
    print("\n--- 18. 재수집 능력이 실행 경로에 실제로 배선돼 있다 ---")
    import ast as _ast

    root = os.path.dirname(os.path.abspath(__file__))

    # ★ 진입점을 손으로 적지 않는다 (2026-08-18 Sprint 200 정정).
    #
    #   처음에는 doc_worker/mvp_scraper/migrate_execute 만 적었다. 그랬더니
    #   `refresh_queue_priority` 가 **"배선 끊김"으로 잡혔다** — 실제로는
    #   `refresh_priority.py`(run_priority_refresh.bat 이 실행) 가 부르고 있었다.
    #   **가드가 거짓 경보를 내는 것은 아무 경보도 안 내는 것만큼 나쁘다.**
    #
    #   그래서 운영 배치(`run_*.bat`)가 실제로 실행하는 .py 를 읽어 진입점을 만들고,
    #   파이프라인 라이브러리(crawler/ storage/)를 통째로 더한다. 새 배치가 생기면
    #   저절로 따라간다.
    import re as _re

    entry_scripts = set()
    bat_files = [f for f in os.listdir(root) if f.lower().endswith(".bat")]
    for bat in bat_files:
        with open(os.path.join(root, bat), encoding="utf-8-sig", errors="replace") as fh:
            for line in fh:
                code = line.split("REM", 1)[0]
                for m in _re.finditer(r"([A-Za-z_][A-Za-z0-9_]*\.py)", code):
                    if os.path.isfile(os.path.join(root, m.group(1))):
                        entry_scripts.add(m.group(1))
    check_true("운영 배치에서 진입점을 실제로 찾았다", len(entry_scripts) >= 3,
               (sorted(bat_files), sorted(entry_scripts)))

    MODULES = {os.path.splitext(f)[0]: f for f in sorted(entry_scripts)}
    for pkg in ("crawler", "storage"):
        base = os.path.join(root, pkg)
        for dp_, dn, fn in os.walk(base):
            dn[:] = [d for d in dn if d != "__pycache__"]
            for f_ in sorted(fn):
                if f_.endswith(".py"):
                    rel = os.path.relpath(os.path.join(dp_, f_), root)
                    MODULES[rel.replace(os.sep, ".")[:-3]] = rel

    called = set()          # 저장소 어디에선가 **호출되는** 이름
    defined = {}            # 이름 -> 정의된 모듈
    unparsed = []
    for mod, rel in sorted(MODULES.items()):
        path = os.path.join(root, rel)
        try:
            with open(path, encoding="utf-8-sig") as fh:
                tree = _ast.parse(fh.read())
        except (OSError, UnicodeDecodeError, SyntaxError) as exc:
            unparsed.append("%s (%s)" % (rel, type(exc).__name__))
            continue
        for node in _ast.walk(tree):
            if isinstance(node, (_ast.FunctionDef, _ast.AsyncFunctionDef)):
                defined.setdefault(node.name, mod)
            if isinstance(node, _ast.Call):
                f = node.func
                nm = (f.id if isinstance(f, _ast.Name)
                      else f.attr if isinstance(f, _ast.Attribute) else None)
                if nm:
                    called.add(nm)

    # ★ 못 읽은 파일이 있으면 "배선돼 있다"는 결론이 성립하지 않는다(BUGS #133 의 교훈).
    check("배선 검사 대상을 전부 읽고 팠다", unparsed, [])
    check_true("진입점 모듈을 실제로 찾았다", len(defined) >= 40, len(defined))

    # 재수집 사슬의 각 능력 — 이름은 코드에서 가져오고 여기에는 **역할만** 적는다
    CAPABILITIES = {
        "requeue_changed_documents": "변경 -> 큐 되돌림 (Sprint 189)",
        "doc_types_for_changed_fields": "필드 -> 자산 종류 매핑",
        "claim_next_queue_item": "큐 claim (overwrite 판정 포함)",
        "claim_next_item_rows": "물건 단위 묶음 claim (Sprint 236)",
        "collect_document": "자산 수집 진입점",
        "collect_images": "사진 수집",
        "mark_queue_done": "성공 종결 + version log",
        "mark_queue_failed": "실패/재시도",
        "reset_stale_queue": "stale 회수",
        "save_auction_images": "사진 DB 기록",
        "clear_images_if_absence_confirmed": "법원이 사진 전부 내림 (BUGS #128)",
        "remove_stored_image_files": "사진 파일 정리 (BUGS #128)",
        "_remove_files_not_in": "사라진 순번 파일 정리 (BUGS #127)",
        "_remove_other_ext_for_seq": "형식 변경 시 옛 파일 정리 (BUGS #120)",
        "move_into_place": "원자적 문서 저장 (BUGS #121)",
        "status_content_hash": "문서 내용 지문 (BUGS #124)",
        "_write_text_if_changed": "무변경 시 미기록 (BUGS #125)",
        "_same_bytes_on_disk": "무변경 사진 미기록 (BUGS #125)",
        "enqueue_documents": "매일 큐 적재(image 포함)",
        "refresh_queue_priority": "우선순위 재계산",
    }

    missing_def = sorted(n for n in CAPABILITIES if n not in defined)
    check("모든 능력이 실제로 정의돼 있다", missing_def, [])

    never_called = sorted(n for n in CAPABILITIES if n not in called)
    if never_called:
        for n in never_called:
            print("      배선 끊김: %s  (%s)" % (n, CAPABILITIES[n]))
    check("모든 능력이 어딘가에서 실제로 호출된다", never_called, [])

    # ★ 특히 재수집의 심장 — overwrite 가 doc_worker 에서 collect_document 로 넘어가는가.
    #   Sprint 189 이전에는 이 한 줄이 없어서 재수집 전체가 죽어 있었다.
    with open(os.path.join(root, "doc_worker.py"), encoding="utf-8-sig") as fh:
        dw = fh.read()
    check_true("doc_worker 가 overwrite 를 collect_document 로 넘긴다",
               "overwrite=overwrite" in dw,
               "이 한 줄이 없으면 재수집은 '이미 존재. 스킵'으로 조용히 끝난다")
    check_true("doc_worker 가 claim 결과의 overwrite 를 읽는다",
               'item.get("overwrite")' in dw, dw[:200])

    print("    능력 %d개 전부 정의 + 호출 확인 (정의된 함수 %d개 중)"
          % (len(CAPABILITIES), len(defined)))


def test_full_image_chain_reaches_the_api():
    """법원 원천 변경부터 **API 응답까지** 한 fixture 로 잇는다 (Sprint 215).

    19번은 수집기 진입까지만 본다(`images: []` 를 돌려주므로 저장/해시/DB/API 는
    타지 않는다). 여기서는 그 뒤를 잇는다 — **대역은 브라우저 한 곳뿐**이고
    저장·해시·DB 기록·큐 종결·API 응답은 전부 실함수다.

        auction 변경 -> migrate_execute -> 변경 감지 -> refresh 큐
        -> 진짜 claim -> doc_worker -> 수집기(대역: 실제 파일 2장을 만든다)
        -> save_auction_images -> auction_image -> mark_queue_done
        -> API /api/v1/item/{id}

    한 단계라도 실제로 실행되지 않으면 그 단계의 단언이 실패한다 —
    "각 부품은 멀쩡한데 배선이 없다"(Sprint 189 이전 상태)를 다시 놓치지 않기 위한 검사다.

    상세페이지 자체(React)는 여기 범위가 아니다. 그 화면이 읽는 **응답 계약**
    (`images` / `image_count` / `representative_image` / `images_status`)을 확인하고,
    렌더링은 `tests/frontend-contract.test.mjs` 가 본다 — 경계를 분명히 적어 둔다.
    """
    print()
    print("--- 21. 원천 변경 -> ... -> API 전 구간 관통 (Sprint 215) ---")
    import contextlib as _ctx
    import hashlib as _hash
    import io as _io
    import storage.database as db
    import migrate_execute as me
    import crawler.doc_paths as dp

    with ScratchDB() as s:
        court, case_no, item_no = "B000210", "2024타경888", "1"
        future = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")
        now = datetime.now().isoformat()

        saved_root = dp.DOCUMENT_ROOT
        docs_root = os.path.join(s.tmp, "documents")
        os.makedirs(docs_root, exist_ok=True)
        dp.DOCUMENT_ROOT = docs_root
        try:
            # --- [1] 법원 원천 ------------------------------------------------
            c = s.conn()
            try:
                c.execute("""INSERT INTO auction
                    (court_code, court_name, case_no, item_no, auction_date, status,
                     appraisal_price, minimum_bid_price, crawl_date, created_at, updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                          (court, "테스트지원", case_no, item_no, future, "신건",
                           100000000, 70000000, "2026-08-18", now, now))
                c.commit()
            finally:
                c.close()
            with _ctx.redirect_stdout(_io.StringIO()):
                me.execute()
            c = s.conn()
            try:
                item_id = c.execute("SELECT id FROM auction_item WHERE case_no=? AND item_no=?",
                                    (case_no, item_no)).fetchone()["id"]
            finally:
                c.close()
            check_true("[1] auction -> auction_item 이 만들어졌다", bool(item_id), item_id)

            # --- [2] 이미 수집돼 있던 상태 ------------------------------------
            qid = s.queue_row(court, case_no, item_no, "image", "done", auction_date=future)

            # --- [3] 원천 변경 -> 변경 감지 -> refresh -------------------------
            c = s.conn()
            try:
                c.execute("UPDATE auction SET appraisal_price=? WHERE court_code=? AND"
                          " case_no=? AND item_no=?", (123456789, court, case_no, item_no))
                c.commit()
            finally:
                c.close()
            with _ctx.redirect_stdout(_io.StringIO()):
                me.execute()
            check("[3] 감정가 변경이 관측된다", me.LAST_FIELD_CHANGES.get("appraisal_price"), 1)
            check("[3] image 행이 refresh 로 돌아간다", s.status_of(qid), "refresh")

            # --- [4] 진짜 claim -> 수집기(대역이 실제 파일을 만든다) ------------
            img_dir = os.path.join(dp.get_doc_dir(court, case_no, item_no), "images")
            os.makedirs(img_dir, exist_ok=True)
            seen = []

            def collecting_stub(driver, cc, cn, ino, doc_type, btn_id, overwrite=False):
                seen.append((doc_type, overwrite))
                if doc_type != "image":
                    return {"success": True, "previous_hash": "", "new_hash": "h",
                            "partial": False, "images": [], "files_saved": []}
                imgs = []
                for i in (1, 2):
                    p = os.path.join(img_dir, "%02d.jpg" % i)
                    with open(p, "wb") as fh:
                        # MIN_IMAGE_BYTES(1,024) 초과여야 한다 (BUGS #148) —
                        # 그 아래는 저장 계층이 기록하지 않고 서빙도 404 다.
                        fh.write(b"\xff\xd8\xff" + bytes([i]) * 2048)
                    imgs.append({"seq": i, "kind": "전경도", "path": p,
                                 "file_size": os.path.getsize(p),
                                 "file_hash": _hash.sha256(open(p, "rb").read()).hexdigest(),
                                 "width": 10, "height": 10})
                combined = _hash.sha256(
                    "".join(x["file_hash"] for x in imgs).encode("ascii")).hexdigest()
                return {"success": True, "previous_hash": "old", "new_hash": combined,
                        "partial": False, "images": imgs, "files_saved": [],
                        "no_asset": False}

            _run_doc_worker({
                "claim_next_item_rows": db.claim_next_item_rows,     # 진짜 claim(물건 단위)
                "collect_document": collecting_stub,
                "mark_queue_done": db.mark_queue_done,               # 진짜 종결
                "save_auction_images": db.save_auction_images,       # 진짜 기록
            })

            check("[4] 수집기에 image 가 overwrite=True 로 도달한다",
                  [x for x in seen if x[0] == "image"], [("image", True)])

            # --- [5] 파일 / [6] DB asset / [7] 큐 종결 -------------------------
            on_disk = sorted(f for f in os.listdir(img_dir) if f.endswith(".jpg"))
            check("[5] 파일이 실제로 저장됐다", on_disk, ["01.jpg", "02.jpg"])

            c = s.conn()
            try:
                rows = c.execute("SELECT seq, file_hash, file_size FROM auction_image"
                                 " WHERE item_id=? ORDER BY seq", (item_id,)).fetchall()
                ds = c.execute("SELECT status FROM document_status WHERE item_id=?"
                               " AND doc_type='IMAGE'", (item_id,)).fetchone()
                vlog = c.execute("SELECT COUNT(*) FROM document_version_log").fetchone()[0]
            finally:
                c.close()
            check("[6] auction_image 2행", [r["seq"] for r in rows], [1, 2])
            check_true("[6] 해시가 비어 있지 않다", all(r["file_hash"] for r in rows), rows)
            check_true("[6] 크기가 실제 파일과 같다",
                       all(r["file_size"] == os.path.getsize(os.path.join(img_dir, "%02d.jpg" % r["seq"]))
                           for r in rows), rows)
            check("[7] 큐가 done 으로 종결된다", s.status_of(qid), "done")
            check("[7] 화면 상태 READY", ds["status"] if ds else None, "READY")
            check_true("[7] 지문이 달라 개정 이력이 남는다 (%d행)" % vlog, vlog >= 1, vlog)

            # --- [8] API 응답 계약 --------------------------------------------
            from fastapi.testclient import TestClient
            from api_server import app
            client = TestClient(app)
            body = client.get("/api/v1/item/%d" % item_id).json()
            check("[8] image_count", body.get("image_count"), 2)
            check("[8] images_status", body.get("images_status"), "READY")
            check_true("[8] 대표 이미지가 있다", bool(body.get("representative_image")),
                       body.get("representative_image"))
            urls = [im.get("url") for im in (body.get("images") or [])]
            check("[8] 상세페이지가 읽는 URL 이 순번대로 온다", urls,
                  ["/api/v1/item/%d/images/1" % item_id,
                   "/api/v1/item/%d/images/2" % item_id])
        finally:
            dp.DOCUMENT_ROOT = saved_root


def test_refresh_intent_survives_retry_exhaustion():
    """재시도가 **소진된 뒤에도** 재수집 의도가 살아남는가 (Sprint 210).

    ## 무엇이 문제였나

    Sprint 189 는 **중간 재시도**에서 의도가 사라지는 것을 막았다
    (`QUEUE_RESUME_STATUS`: `in_progress_refresh` -> `refresh`).
    막지 못한 것은 **재시도 소진** 경로다.

        refresh -> in_progress_refresh -> 실패 x3 -> failed      (refresh 정보 소실)
                -> 하루 뒤 reset_stale_queue() -> pending        (refresh 아님)
                -> claim(overwrite=False) -> "이미 존재. 스킵" -> done

    `collect_spec()` 은 `doc_exists(...) and not overwrite` 이면 즉시
    `success=True` 로 돌아온다. 즉 그 재시도는 **구조적으로 아무 일도 하지 않고**
    큐만 성공으로 종결시킨다. 법원이 바꾼 문서는 영원히 옛것으로 남는다.
    오류도 경고도 없다 — 이 저장소가 반복해서 잡아 온 "조용한 성공"이다.

    ## 어떻게 고쳤나 (상태값을 새로 만들지 않는다)

    `document_status` 가 READY 라는 것은 **볼 수 있는 실체가 있다**는 뜻이다.
    그런 행을 `pending` 으로 되돌리면 위와 같이 반드시 헛돈다. 그래서
    `reset_stale_queue()` 가 그 행만 `refresh` 로 되돌린다. 실체가 없는 행은
    `pending` 이 맞다(처음 받는 것이다).

    ## 픽스처가 실물보다 좁으면 이 검사는 거짓 통과한다

    `refresh` 행은 원래 `done` 이었고, `done` 이면 화면 상태는 READY 다.
    그 READY 를 심지 않으면 수정 코드가 판정할 근거가 없어 **고쳤는데도 실패**한다.
    처음에 실제로 그렇게 한 번 헛짚었다.
    """
    print()
    print("--- 20. 재시도 소진 뒤에도 재수집 의도가 남는가 (Sprint 210) ---")
    import storage.database as dbmod

    with ScratchDB() as db:
        court, case_no, item_no = "B000210", "2024타경1", "1"
        db.seed_item(court=court, case_no=case_no, item_no=item_no)

        # 이미 받아 둔 문서(= done 이었던 행)를 재수집으로 되돌린 상태를 만든다.
        qid = db.queue_row(court, case_no, item_no, "spec", "refresh",
                           last_attempt_at=None, retry_count=0)
        c = db.conn()
        try:
            item_id = c.execute(
                "SELECT id FROM auction_item WHERE case_no=? AND item_no=?",
                (case_no, item_no)).fetchone()["id"]
            c.execute("INSERT INTO document_status (item_id, doc_type, status)"
                      " VALUES (?,?,?)", (item_id, "SPEC", "READY"))
            c.commit()
        finally:
            c.close()

        # 재시도를 소진시킨다. 매번 claim -> 실패로, 실제 워커와 같은 순서를 밟는다.
        for _ in range(dbmod.MAX_DOC_RETRY):
            c = db.conn()
            try:
                c.execute("UPDATE document_queue SET last_attempt_at=NULL WHERE id=?", (qid,))
                c.commit()
            finally:
                c.close()
            claimed = dbmod.claim_next_queue_item()
            if claimed is None:
                break
            c = db.conn()
            try:
                rc = c.execute("SELECT retry_count FROM document_queue WHERE id=?",
                               (qid,)).fetchone()["retry_count"]
            finally:
                c.close()
            dbmod.mark_queue_failed(qid, rc)

        check("재시도 소진 뒤 큐 상태", db.status_of(qid), "failed")

        # 하루가 지났다고 두고 복구를 돌린다.
        c = db.conn()
        try:
            # 'localtime' 필수 — 운영 코드는 last_attempt_at 을 파이썬 로컬 시각으로
            # 쓰고 reset_stale_queue() 도 로컬로 비교한다. UTC 로 넣으면 한국 기준
            # 9시간이 어긋난다(`test_pipeline_integrity.py` 의 localtime 가드가 잡았다).
            c.execute("UPDATE document_queue"
                      " SET last_attempt_at=datetime('now','localtime','-2 day')"
                      " WHERE id=?", (qid,))
            c.commit()
        finally:
            c.close()
        import contextlib as _ctx, io as _io
        with _ctx.redirect_stdout(_io.StringIO()):
            dbmod.reset_stale_queue()

        check("★ 실체가 있는 행은 pending 이 아니라 refresh 로 돌아온다",
              db.status_of(qid), "refresh")

        c = db.conn()
        try:
            c.execute("UPDATE document_queue SET last_attempt_at=NULL WHERE id=?", (qid,))
            c.commit()
        finally:
            c.close()
        again = dbmod.claim_next_queue_item()
        check_true("★ 다시 집었을 때 overwrite=True (헛돌지 않는다)",
                   bool(again and again.get("overwrite")), again)

        # --- 대조군: 실체가 없는 행은 pending 이 맞다 -------------------------
        qid2 = db.queue_row(court, case_no, item_no, "appraisal", "failed",
                            last_attempt_at="2020-01-01T00:00:00", retry_count=3)
        import contextlib as _ctx, io as _io
        with _ctx.redirect_stdout(_io.StringIO()):
            dbmod.reset_stale_queue()
        check("대조군: 한 번도 못 받은 행은 pending 으로 복귀",
              db.status_of(qid2), "pending")


def test_image_trigger_reaches_the_collector_end_to_end():
    """★ 이미지 재수집이 **migrate_execute 부터 수집기까지** 실함수로 관통하는가.

    ## 왜 이 검사가 따로 필요한가

    기존 검사들은 각 구간을 따로 본다.

        §1     필드 -> 자산 종류 매핑 (표만 본다)
        §2/§3  requeue 가 큐를 되돌리는가 (큐만 본다)
        §9     doc_worker 가 overwrite 를 넘기는가 (claim 결과를 **가짜로 주입**한다)
        §18    각 능력이 어딘가에서 호출되는가 (배선만 본다. 간접 죽은 코드는 못 잡는다)

    **어느 것도 "법원이 감정가를 바꾸면 사진 수집기에 overwrite=True 가 도달한다"를
    끝까지 확인하지 않는다.** 중간 한 링크만 끊겨도 전부 통과한다 —
    Sprint 189 이전에 정확히 그런 상태였다(각 부품은 멀쩡했고 배선만 없었다).

    여기서는 **가짜 claim 을 주입하지 않는다.** 실제 `auction` 값을 바꾸고,
    실제 `migrate_execute.execute()` 를 돌리고, 실제 `claim_next_queue_item()` 이
    돌려준 것을 그대로 `doc_worker` 에 태운다. 수집기만 대역이다(브라우저가 필요하므로).

    ## 문서 쪽 대조군을 함께 둔다

    이미지만 검사하면 "이미지 경로가 특별히 깨졌는지"를 알 수 없다.
    같은 실행에서 문서(spec)도 함께 확인해 **두 경로가 모두 살아 있음**을 본다.
    """
    print("\n--- 19. 이미지 트리거가 수집기까지 관통한다 (실함수) ---")
    import sqlite3
    import storage.database as db
    import migrate_execute as me
    import doc_worker

    with ScratchDB() as s:
        court, case_no, item_no = "B000210", "2024타경777", "1"
        future = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")
        now = datetime.now().isoformat()

        # --- 1) auction 에 물건 하나. migrate_execute 가 auction_item 을 만들게 둔다 ---
        c = s.conn()
        try:
            c.execute("""INSERT INTO auction
                (court_code, court_name, case_no, item_no, auction_date, status,
                 appraisal_price, minimum_bid_price, crawl_date, created_at, updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                      (court, "테스트지원", case_no, item_no, future, "신건",
                       100000000, 70000000, "2026-08-18", now, now))
            c.commit()
        finally:
            c.close()

        import contextlib
        import io as _io
        with contextlib.redirect_stdout(_io.StringIO()):
            me.execute()          # auction -> auction_case/auction_item 최초 동기화
        check("최초 실행은 변경 관측이 없다(신규 삽입이므로)",
              me.LAST_FIELD_CHANGES, {})

        # --- 2) 사진/문서를 이미 수집해 둔 상태를 만든다 (done + 기일 남음) ---
        for dt in ("image", "spec"):
            s.queue_row(court, case_no, item_no, dt, "done", auction_date=future)

        # --- 3) 법원이 **감정가**를 바꿨다 (= 재감정). 실제 auction 을 갱신한다 ---
        c = s.conn()
        try:
            c.execute("UPDATE auction SET appraisal_price=? WHERE court_code=? AND"
                      " case_no=? AND item_no=?", (123456789, court, case_no, item_no))
            c.commit()
        finally:
            c.close()

        with contextlib.redirect_stdout(_io.StringIO()):
            me.execute()          # ★ 여기서 관측 -> requeue 가 일어나야 한다

        check("감정가 변경이 관측된다",
              me.LAST_FIELD_CHANGES.get("appraisal_price"), 1)
        check_true("재수집이 예약된다", (me.LAST_REQUEUE or {}).get("refreshed", 0) >= 1,
                   me.LAST_REQUEUE)

        c = s.conn()
        try:
            statuses = {r["doc_type"]: r["status"] for r in c.execute(
                "SELECT doc_type, status FROM document_queue")}
        finally:
            c.close()
        # 감정가 -> (appraisal, image). spec 은 대상이 아니므로 done 그대로여야 한다.
        check("image 행이 refresh 로 돌아간다", statuses.get("image"), "refresh")
        check("spec 은 감정가 변경 대상이 아니라 done 그대로", statuses.get("spec"), "done")

        # --- 4) 실제 claim -> doc_worker -> 수집기까지 태운다 (수집기만 대역) ---
        seen = []

        def fake_collect(driver, court_code, case_no_, item_no_, doc_type, btn_id,
                         overwrite=False):
            seen.append((doc_type, overwrite, btn_id))
            return {"success": True, "previous_hash": "", "new_hash": "h",
                    "partial": False, "images": [], "files_saved": []}

        _run_doc_worker({
            "claim_next_item_rows": db.claim_next_item_rows,     # ★ 진짜 claim(물건 단위)
            "collect_document": fake_collect,
        })

        check("수집기에 image 가 overwrite=True 로 도달한다",
              [x for x in seen if x[0] == "image"], [("image", True, "")])
        check_true("사진은 버튼 id 없이 간다(버튼이 없는 유일한 종류)",
                   all(x[2] == "" for x in seen if x[0] == "image"), seen)

        # --- 5) 대조군: 문서(spec)도 같은 방식으로 살아 있는가 ---
        c = s.conn()
        try:
            c.execute("UPDATE auction SET auction_date=? WHERE court_code=? AND"
                      " case_no=? AND item_no=?",
                      ((datetime.now() + timedelta(days=60)).strftime("%Y-%m-%d"),
                       court, case_no, item_no))
            c.commit()
        finally:
            c.close()
        with contextlib.redirect_stdout(_io.StringIO()):
            me.execute()
        c = s.conn()
        try:
            spec_status = c.execute(
                "SELECT status FROM document_queue WHERE doc_type='spec'").fetchone()[0]
        finally:
            c.close()
        check("기일 변경은 spec 을 refresh 로 되돌린다", spec_status, "refresh")

        seen.clear()
        _run_doc_worker({
            "claim_next_item_rows": db.claim_next_item_rows,
            "collect_document": fake_collect,
        })
        check("수집기에 spec 이 overwrite=True 로 도달한다",
              [x for x in seen if x[0] == "spec"][:1], [("spec", True, "qa-btn")])



def test_refresh_cycle_respects_the_version_policy():
    """재수집이 실제로 돌 때 **문서 버전이 어떻게 되는가** (2026-08-25, docs/BUGS.md #203).

    ## 왜 이 검사가 없었나

    이 파일은 재수집 **기계**(예약·claim·retry·상한·배선)를 24개 검사로 덮는다.
    그런데 `doc_version` 을 **한 번도 보지 않는다**(2026-08-25 실측: 이 파일에
    `doc_version` 0회). 반대쪽(`record_doc_raw_row` 의 버전 규칙)은 BUGS #197/#199 가
    덮는다. **두 축의 이음매만 비어 있었다.**

    그 이음매가 일상 운영 경로다 — 매일 크롤이 값을 바꾸면 `refresh` 가 예약되고,
    워커가 그 문서를 **다시 받는다.** 그때:

        법원이 실제로는 안 바꿨다(같은 파일)  -> 버전이 오르면 안 된다
                                              (`api/v1/item.py` 가 MAX(doc_version) 을
                                               사용자에게 노출한다 - BUGS #115)
        법원이 진짜로 바꿨다                  -> 새 버전이 생기고 **옛 버전은 남아야** 한다

    후자가 중요하다. 이 저장소의 정책은 "덮어쓰기"가 아니라 "버전 쌓기"이고,
    옛 행을 지우면 무엇이 언제 바뀌었는지 되짚을 수 없다.

    ## 무엇을 고정하는가

        refresh -> 같은 내용 재수집   doc_raw 행 수 그대로 / MAX(doc_version) 그대로
        refresh -> 바뀐 내용 재수집   행 +1 / MAX +1 / **옛 버전 행이 그대로 존재**
                                     document_version_log 에 1행
    """
    print("\n--- 25. 재수집 사이클의 버전 정책 (BUGS #203) ---")
    import crawler.doc_paths as dp
    from storage.database import (claim_next_queue_item, mark_queue_done)

    with ScratchDB() as db:
        saved_root = dp.DOCUMENT_ROOT
        docs_root = os.path.join(db.tmp, "documents")
        os.makedirs(docs_root, exist_ok=True)
        dp.DOCUMENT_ROOT = docs_root
        try:
            COURT, CASE, ITEM = "B000210", "2024타경1", "1"
            db.seed_item(COURT, CASE, ITEM)

            def counts():
                c = db.conn()
                try:
                    n = c.execute("SELECT COUNT(*) FROM doc_raw").fetchone()[0]
                    mx = c.execute("SELECT COALESCE(MAX(doc_version),0) FROM doc_raw").fetchone()[0]
                    log = c.execute("SELECT COUNT(*) FROM document_version_log").fetchone()[0]
                    return n, mx, log
                finally:
                    c.close()

            def collect(body, prev_hash, new_hash, expect_overwrite):
                """예약된 spec 을 claim 해서 실제로 받아 온 것처럼 종결한다.

                `expect_overwrite` 를 인자로 받는 이유: 첫 수집은 `pending`(overwrite=False)이고
                재수집은 `refresh`(overwrite=True)다. 둘을 같은 값으로 단언하면 검사가
                **둘 중 하나를 반드시 틀리게** 만든다 - 그 구분이 이 파일의 핵심 어휘다.
                """
                it = claim_next_queue_item()
                check_true("claim 이 그 행을 집었다", it is not None and it["doc_type"] == "spec",
                           it)
                if it is None:
                    return None
                check("claim 의 overwrite 가 큐 상태와 맞는다(%s)"
                      % ("refresh" if expect_overwrite else "pending"),
                      it["overwrite"], expect_overwrite)
                d = dp.get_doc_dir(COURT, CASE, ITEM)
                os.makedirs(d, exist_ok=True)
                p = os.path.join(d, "spec.pdf")
                with open(p, "wb") as fh:
                    fh.write(body)
                mark_queue_done(it["id"], COURT, CASE, ITEM, "spec", prev_hash, new_hash,
                                files_saved=[p], claim_token=it.get("claim_token"))
                return p

            # --- 첫 수집 -------------------------------------------------
            db.queue_row(COURT, CASE, ITEM, "spec", "pending")
            first = b"%PDF-1.4 ORIGINAL" + b"a" * 120
            collect(first, "", "h1", expect_overwrite=False)   # 첫 수집은 pending
            n0, mx0, log0 = counts()
            check("첫 수집 후 doc_raw 1행", n0, 1)
            check("첫 수집 후 버전 1", mx0, 1)
            check("첫 수집은 변경 이력을 남기지 않는다(이전 값이 없다)", log0, 0)

            # --- 재수집 1: 법원이 실제로는 안 바꿨다 ----------------------
            c = db.conn()
            try:
                c.execute("UPDATE document_queue SET status='refresh', last_attempt_at=NULL"
                          " WHERE doc_type='spec'")
                c.commit()
            finally:
                c.close()
            collect(first, "h1", "h1", expect_overwrite=True)   # 같은 파일, 같은 지문
            n1, mx1, log1 = counts()
            check("★ 같은 내용 재수집은 행을 늘리지 않는다", n1, 1)
            check("★ 같은 내용 재수집은 버전을 올리지 않는다", mx1, 1)
            check("같은 내용이면 변경 이력도 남지 않는다", log1, 0)

            # --- 재수집 2: 법원이 진짜로 바꿨다 ---------------------------
            c = db.conn()
            try:
                c.execute("UPDATE document_queue SET status='refresh', last_attempt_at=NULL"
                          " WHERE doc_type='spec'")
                c.commit()
            finally:
                c.close()
            collect(b"%PDF-1.4 REVISED" + b"b" * 400, "h1", "h2", expect_overwrite=True)
            n2, mx2, log2 = counts()
            check("★ 바뀐 내용은 새 행을 만든다", n2, 2)
            check("★ 버전이 2로 오른다", mx2, 2)
            check("★ 변경 이력이 1행 남는다", log2, 1)

            # ★ 옛 버전을 **지우지 않는다** — 이 저장소의 정책은 덮어쓰기가 아니라 쌓기다.
            c = db.conn()
            try:
                rows = [(r["doc_version"], r["file_size"]) for r in c.execute(
                    "SELECT doc_version, file_size FROM doc_raw ORDER BY doc_version")]
            finally:
                c.close()
            check("★ 옛 버전 행이 그대로 남아 있다", [v for v, _s in rows], [1, 2])
            check_true("두 버전의 크기가 실제로 다르다(검사가 공허하지 않다)",
                       rows[0][1] != rows[1][1], rows)

            # 화면은 재수집 내내 READY 를 유지해야 한다(사용자가 보던 것을 뺏지 않는다)
            c = db.conn()
            try:
                st = c.execute("SELECT status FROM document_status WHERE doc_type='SPEC'"
                               ).fetchone()
            finally:
                c.close()
            check("재수집이 끝난 뒤에도 화면은 READY", st["status"] if st else None, "READY")
        finally:
            dp.DOCUMENT_ROOT = saved_root

def main():
    print("=" * 55)
    print(" 변경 기반 재수집 회귀 (Sprint 189)")
    print("=" * 55)
    test_field_to_doc_type_mapping()
    test_requeue_only_touches_done()
    test_requeue_skips_items_whose_date_already_passed()
    test_requeue_revives_expired_only_when_date_moved_forward()
    test_expired_revival_is_scoped_by_changed_field_not_by_item()
    test_claim_returns_overwrite_and_separate_in_progress()
    test_refresh_intent_survives_retry_and_stale_recovery()
    test_max_retry_still_terminates_refresh()
    test_refresh_failure_does_not_destroy_what_we_already_show()
    test_priority_refresh_covers_refresh_rows()
    test_cap_is_loud_not_silent()
    test_cap_no_longer_drops_changed_items()
    test_overwrite_reaches_the_collector()
    test_refresh_skips_sibling_shortcut()
    test_queue_status_vocabulary_is_single_sourced()
    test_migrate_execute_wires_the_trigger()
    test_daily_enqueue_does_not_clobber_pending_refresh()
    test_doc_stats_counts_every_queue_status()
    test_concurrent_claim_never_duplicates_and_never_lies()
    test_every_volatile_field_is_observed_or_derived()
    test_refresh_cap_fits_the_execution_window()
    test_every_refresh_capability_is_actually_wired()
    test_image_trigger_reaches_the_collector_end_to_end()
    test_refresh_intent_survives_retry_exhaustion()
    test_full_image_chain_reaches_the_api()
    test_refresh_cycle_respects_the_version_policy()

    print("\n" + "=" * 55)
    if failures:
        print("FAILED (%d): %s" % (len(failures), ", ".join(failures)))
        return 1
    print("ALL TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
