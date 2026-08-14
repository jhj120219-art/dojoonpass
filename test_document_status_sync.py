"""문서 수집 결과가 화면이 읽는 테이블까지 도달하는가 (2026-08-11 Sprint 55 신설, BUGS #50).

배경 — 문서 상태가 **두 곳에 따로** 기록되고 있었다.

    auction.has_*_pdf   doc_worker가 갱신 (스케줄러가 매일 실행하는 살아있는 경로)
    document_status     collect_documents.py만 갱신 (어떤 배치도 이 스크립트를 부르지 않음)

화면(`GET /api/v1/item/{id}`의 `documents`)이 읽는 것은 **후자**다. 그래서 PDF를 이미
받아 둔 물건도 상세 화면에서 계속 "수집중"으로 보였다.

    실측 2026-08-11 (수정 전)
        auction.has_spec_pdf=1                     197건
        그중 document_status != READY              192건  (97%)
        디스크에 파일이 있는 (법원,사건,물건) 조합    200개
        document_status READY                       14개

selenium 없이 실행된다. 임시 DB에 최소 스키마를 만들어 `storage.database`의 실제 함수를
호출한다 — 조회 SQL(JOIN 경로 포함)까지 함께 검증하기 위해서다.

    python test_document_status_sync.py
"""
import sys
import os
import sqlite3
import tempfile
import shutil

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import storage.database as dbmod

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


SCHEMA = """
CREATE TABLE auction_case (id INTEGER PRIMARY KEY, court_code TEXT, case_no TEXT);
CREATE TABLE auction_item (
    id INTEGER PRIMARY KEY, case_id INTEGER, case_no TEXT, item_no TEXT
);
CREATE TABLE document_status (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id INTEGER NOT NULL, doc_type TEXT NOT NULL,
    status TEXT NOT NULL, updated_at TEXT,
    UNIQUE(item_id, doc_type)
);
CREATE TABLE document_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    court_code TEXT NOT NULL, case_no TEXT NOT NULL, doc_type TEXT NOT NULL,
    priority INTEGER DEFAULT 3, auction_date TEXT, status TEXT DEFAULT 'pending',
    retry_count INTEGER DEFAULT 0, last_attempt_at TEXT, enqueued_at TEXT,
    item_no TEXT NOT NULL DEFAULT '1',
    UNIQUE(court_code, case_no, item_no, doc_type)
);
CREATE TABLE auction (
    court_code TEXT, case_no TEXT, item_no TEXT,
    has_spec_pdf INTEGER DEFAULT 0, has_status_doc INTEGER DEFAULT 0,
    has_appraisal_pdf INTEGER DEFAULT 0
);
CREATE TABLE document_version_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    court_code TEXT, case_no TEXT, item_no TEXT, doc_type TEXT,
    previous_hash TEXT, new_hash TEXT, file_version TEXT, updated_at TEXT
);
INSERT INTO auction_case (id, court_code, case_no) VALUES (1, 'B000210', '2024타경1636');
INSERT INTO auction_item (id, case_id, case_no, item_no) VALUES (111, 1, '2024타경1636', '1');
INSERT INTO auction (court_code, case_no, item_no) VALUES ('B000210', '2024타경1636', '1');
INSERT INTO document_status (item_id, doc_type, status, updated_at)
    VALUES (111, 'SPEC', 'COLLECTING', '2026-07-11T12:37:32'),
           (111, 'STATUS', 'COLLECTING', '2026-07-11T12:37:32'),
           (111, 'APPRAISAL', 'COLLECTING', '2026-07-11T12:37:32');
INSERT INTO document_queue (id, court_code, case_no, item_no, doc_type, status, retry_count)
    VALUES (900, 'B000210', '2024타경1636', '1', 'spec', 'in_progress', 0);
"""


class TempDB:
    """`storage.database.get_connection()`을 임시 DB로 갈아끼운다.

    실제 auction.db를 건드리지 않기 위해서다. 모듈의 실제 함수를 그대로 호출해야
    조회 SQL의 JOIN 경로까지 검증되므로, 함수를 흉내 내지 않고 커넥션만 바꾼다.
    """

    def __enter__(self):
        self.dir = tempfile.mkdtemp(prefix="qa_docstatus_")
        self.path = os.path.join(self.dir, "t.db")
        conn = sqlite3.connect(self.path)
        conn.executescript(SCHEMA)
        conn.commit()
        conn.close()

        self._orig = dbmod.get_connection

        def fake(enforce_foreign_keys=True):
            c = sqlite3.connect(self.path)
            c.row_factory = sqlite3.Row
            return c

        dbmod.get_connection = fake
        return self

    def __exit__(self, *exc):
        dbmod.get_connection = self._orig
        shutil.rmtree(self.dir, ignore_errors=True)

    def query(self, sql, *a):
        c = sqlite3.connect(self.path)
        c.row_factory = sqlite3.Row
        try:
            return c.execute(sql, a).fetchall()
        finally:
            c.close()

    def one(self, sql, *a):
        r = self.query(sql, *a)
        return r[0][0] if r else None


# ---------------------------------------------------------------------------
def test_done_marks_ready():
    print("\n--- 1. 수집 성공이 화면 테이블까지 도달하는가 (BUGS #50 회귀) ---")
    with TempDB() as db:
        check("시작 상태는 COLLECTING",
              db.one("SELECT status FROM document_status WHERE item_id=111 AND doc_type='SPEC'"),
              "COLLECTING")

        dbmod.mark_queue_done(900, "B000210", "2024타경1636", "1", "spec", "", "hash1")

        check("SPEC이 READY가 된다",
              db.one("SELECT status FROM document_status WHERE item_id=111 AND doc_type='SPEC'"),
              "READY")
        # 기존 동작도 그대로 유지돼야 한다.
        check("큐가 done으로", db.one("SELECT status FROM document_queue WHERE id=900"), "done")
        check("레거시 플래그도 유지",
              db.one("SELECT has_spec_pdf FROM auction WHERE case_no='2024타경1636'"), 1)
        # 다른 문서 종류를 건드리면 안 된다.
        check("STATUS는 그대로 COLLECTING",
              db.one("SELECT status FROM document_status WHERE item_id=111 AND doc_type='STATUS'"),
              "COLLECTING")


def test_doc_type_mapping():
    print("\n--- 2. 큐(소문자)와 document_status(대문자) 표기 변환 ---")
    with TempDB() as db:
        for q_type, ds_type in (("spec", "SPEC"), ("status", "STATUS"), ("appraisal", "APPRAISAL")):
            dbmod.mark_queue_done(900, "B000210", "2024타경1636", "1", q_type, "", "h")
            check("%s -> %s" % (q_type, ds_type),
                  db.one("SELECT status FROM document_status WHERE item_id=111 AND doc_type=?", ds_type),
                  "READY")


def test_final_failure_marks_failed():
    print("\n--- 3. 최종 실패만 FAILED로 반영된다 ---")
    with TempDB() as db:
        # 재시도가 남아 있는 실패 -> 화면은 아직 '수집중'이어야 한다.
        dbmod.mark_queue_failed(900, 0)
        check("중간 실패는 큐를 pending으로",
              db.one("SELECT status FROM document_queue WHERE id=900"), "pending")
        check("중간 실패에 화면 상태는 그대로",
              db.one("SELECT status FROM document_status WHERE item_id=111 AND doc_type='SPEC'"),
              "COLLECTING")

        # 재시도 소진 -> FAILED
        dbmod.mark_queue_failed(900, dbmod.MAX_DOC_RETRY - 1)
        check("재시도 소진 시 큐가 failed",
              db.one("SELECT status FROM document_queue WHERE id=900"), "failed")
        check("재시도 소진 시 화면도 FAILED",
              db.one("SELECT status FROM document_status WHERE item_id=111 AND doc_type='SPEC'"),
              "FAILED")


def test_unknown_item_does_not_crash():
    print("\n--- 4. 대응 물건이 없어도 수집 결과 기록이 깨지지 않는다 ---")
    with TempDB() as db:
        # auction_item에 없는 사건 — 조용히 죽으면 큐가 done으로도 안 가고 멈춘다.
        dbmod.mark_queue_done(900, "B999999", "9999타경1", "1", "spec", "", "h")
        check("큐는 정상적으로 done", db.one("SELECT status FROM document_queue WHERE id=900"), "done")
        check("엉뚱한 document_status 행을 만들지 않는다",
              db.one("SELECT COUNT(*) FROM document_status"), 3)


def test_unknown_doc_type_is_rejected():
    print("\n--- 4-B. 알 수 없는 doc_type은 기록하지 않는다 ---")
    # 큐에는 소문자('spec')가 들어가는 것이 계약이다. 어떤 경로로든 다른 값이 들어오면
    # 그대로 써 넣으면 안 된다 — document_status에 'spec'/'SPEC'이 뒤섞이면
    # 화면 조회(doc_type='SPEC')가 조용히 빗나가고, 원인 추적도 어려워진다.
    with TempDB() as db:
        conn = dbmod.get_connection()
        try:
            for bad in ("SPEC", "registry", "", None):
                ok = dbmod._set_document_status(conn, "B000210", "2024타경1636", "1", bad, "READY")
                check("doc_type=%r 는 거부된다" % bad, ok, False)
            conn.commit()
        finally:
            conn.close()

        rows = db.query("SELECT DISTINCT doc_type FROM document_status ORDER BY doc_type")
        check("document_status에 규격 외 표기가 생기지 않는다",
              [r[0] for r in rows], ["APPRAISAL", "SPEC", "STATUS"])

        # 정상 표기는 그대로 통과해야 한다(거부 로직이 과하게 잡지 않는지 확인).
        conn = dbmod.get_connection()
        try:
            check("정상 doc_type='spec'은 통과",
                  dbmod._set_document_status(conn, "B000210", "2024타경1636", "1", "spec", "READY"),
                  True)
            conn.commit()
        finally:
            conn.close()


def test_repair_script_path_guard():
    """1회성 보정 스크립트가 DOCUMENT_ROOT 밖 파일로 상태를 바꾸지 않는가.

    보정 판단 근거는 "파일이 실제로 있는가"다. 그 확인이 저장소 밖으로 새면
    **서빙은 404인데 화면만 '수집완료'** 인 상태가 만들어진다 — 고치려던 것과 정확히
    반대 방향의 어긋남이다. api/v1/documents.py가 쓰는 것과 같은 commonpath 검사를 둔다.
    """
    print("\n--- 6. 보정 스크립트의 경로 탈출 차단 ---")
    import importlib.util as iu

    root = os.path.dirname(os.path.abspath(__file__))
    spec = iu.spec_from_file_location("rds", os.path.join(root, "repair_document_status.py"))
    m = iu.module_from_spec(spec)
    spec.loader.exec_module(m)

    for court, case, item in (("..", "..", ".."),
                              ("강릉지원", "../../etc", "1"),
                              ("..\\..\\Windows", "system32", "1"),
                              ("", "", "")):
        check("탈출 경로 (%r,%r,%r) 는 거부" % (court, case, item),
              m.document_exists(court, case, item, "SPEC"), False)

    # 정상 경로는 통과해야 한다 — 가드가 과하게 잡으면 보정이 아무것도 못 한다.
    if os.path.isdir(os.path.join(root, "documents")):
        real = None
        for court in os.listdir(os.path.join(root, "documents"))[:200]:
            cdir = os.path.join(root, "documents", court)
            if not os.path.isdir(cdir):
                continue
            for case in os.listdir(cdir)[:5]:
                for item in os.listdir(os.path.join(cdir, case))[:3]:
                    if os.path.exists(os.path.join(cdir, case, item, "spec.pdf")):
                        real = (court, case, item)
                        break
                if real:
                    break
            if real:
                break
        if real:
            check_true("실제 존재하는 문서는 통과 %r" % (real,),
                       m.document_exists(real[0], real[1], real[2], "SPEC"),
                       "가드가 정상 경로까지 막고 있습니다")


def test_live_db_drift_is_measurable():
    print("\n--- 5. 실제 DB의 어긋남을 측정한다 (수정 전 상태 기록) ---")
    root = os.path.dirname(os.path.abspath(__file__))
    dbp = os.path.join(root, "auction.db")
    if not os.path.exists(dbp):
        print("[SKIP] auction.db 없음 (fresh clone)")
        return
    c = sqlite3.connect("file:%s?mode=ro" % dbp, uri=True)
    try:
        drift = c.execute("""
            SELECT COUNT(*) FROM auction a
            JOIN auction_item ai ON ai.case_no = a.case_no AND ai.item_no = a.item_no
            JOIN document_status ds ON ds.item_id = ai.id AND ds.doc_type = 'SPEC'
            WHERE a.has_spec_pdf = 1 AND ds.status <> 'READY'
        """).fetchone()[0]
        print("    현재 어긋난 행: %d건" % drift)
        # 이 값은 **과거에 쌓인 것**이라 코드 수정만으로 0이 되지 않는다.
        # 0이 되려면 doc_worker를 다시 돌려야 한다(외부 네트워크 — 이번 Sprint SKIP).
        # 그래서 '0이어야 한다'가 아니라 '측정 가능해야 한다'를 계약으로 둔다.
        check_true("어긋남을 측정할 수 있다(조회 경로가 유효)", drift >= 0)
    finally:
        c.close()


# ---------------------------------------------------------------------------
# 6. SKIPPED_EXPIRED는 화면에 도달하지 않는다 - 현재 동작을 그대로 고정 (Sprint 73 신설)
#
# 매각기일이 지난 문서는 doc_worker가 브라우저 작업 없이 SKIPPED_EXPIRED로 끝낸다.
# 그런데 `mark_queue_skipped_expired()`는 **document_queue만 바꾸고 document_status는
# 건드리지 않는다.** 그래서 화면이 읽는 값은 COLLECTING("수집중")으로 영원히 남는다.
#
# 이 문서는 다시 수집되지 않는다 - `enqueue_documents()`가 만료 물건을 애초에 큐에 넣지
# 않기 때문이다(storage/database.py의 1차 방어선). 즉 "수집중"은 **끝나지 않는 상태**다.
#
# 실측 (2026-08-13, auction.db)
#     SKIPPED_EXPIRED 큐 행                     186   그중 document_status=COLLECTING  183
#     document_status=COLLECTING & 물건 만료됨   5,049
#     document_status=COLLECTING & 물건 진행중      20
#     auction_item 1,876건 중 만료             1,867  (99.5%)
#
# 사용자에게 보이는가 - **보인다.** 검색(`/api/v1/search`)은 D7 기본값으로 만료 물건을
# 제외하지만, `favorites` / `recent_items`에는 날짜 필터가 없고 `GET /api/v1/item/{id}`도
# 만료 물건을 200으로 돌려준다. 실측으로 확인했다:
#
#     GET /api/v1/item/1 (auction_date=2026-07-07, 5주 전 만료) -> 200
#     documents: SPEC/STATUS/APPRAISAL 전부 COLLECTING
#     src/app/properties/[id]/page.tsx:68  COLLECTING -> '수집중'
#
# **왜 고치지 않았는가** - "대상이 아님"을 나타낼 상태가 없다. DocStatus는
# COLLECTING/OCR/PARSING/ANALYZING/READY/FAILED뿐이고, FAILED로 쓰면 실패가 아닌 것을
# 실패로 표기하게 된다. 새 상태를 만드는 것은 상태머신·화면 문구 결정이라 제품 판단이다
# (docs/roadmap.md에 결정 대기로 올렸다).
#
# 그래서 지금 동작을 **그대로 못박는다.** 누군가 이 정책을 정해 배선하는 순간 이 검사가
# 실패하면서 함께 고쳐야 할 지점을 지목한다:
#
#     storage/database.py:mark_queue_skipped_expired()   기록 지점
#     api/v1/item.py                                     화면에 내려주는 지점
#     src/app/properties/[id]/page.tsx                   문구 매핑
# ---------------------------------------------------------------------------
def test_skipped_expired_does_not_reach_screen():
    print("\n--- 6. SKIPPED_EXPIRED의 화면 상태 (현재 동작 고정) ---")
    with TempDB() as db:
        before = db.one(
            "SELECT status FROM document_status WHERE item_id=111 AND doc_type='SPEC'")
        check("시작 상태는 COLLECTING", before, "COLLECTING")

        dbmod.mark_queue_skipped_expired(
            900, "B000210", "2024타경1636", "1", "spec", "2020-01-01")

        check("큐는 SKIPPED_EXPIRED로 기록된다",
              db.one("SELECT status FROM document_queue WHERE id=900"), "SKIPPED_EXPIRED")
        # 실패가 아니므로 retry_count를 올리지 않는다(기존 계약).
        check("retry_count는 증가하지 않는다",
              db.one("SELECT retry_count FROM document_queue WHERE id=900"), 0)

        # ★ 현재 동작: 화면 테이블은 손대지 않는다 -> '수집중'이 영원히 남는다.
        check("document_status는 COLLECTING 그대로 (현재 동작)",
              db.one("SELECT status FROM document_status WHERE item_id=111 AND doc_type='SPEC'"),
              "COLLECTING")
        check("다른 문서 종류도 영향 없음",
              db.one("SELECT status FROM document_status WHERE item_id=111 AND doc_type='STATUS'"),
              "COLLECTING")

    # 이 상태가 사용자에게 도달할 수 있는 경로가 실제로 열려 있는지 소스로 확인한다.
    # (열려 있다는 사실이 위 동작을 "무해한 내부 상태"로 볼 수 없게 만드는 근거다.)
    root = os.path.dirname(os.path.abspath(__file__))
    for name in ("favorites.py", "recent_items.py"):
        src = open(os.path.join(root, "api", "v1", name), encoding="utf-8-sig").read()
        check_true("%s에 만료 물건 제외 필터가 없다(현재 동작)" % name,
                   "auction_date <" not in src and "auction_date >=" not in src,
                   "만료 필터가 생겼다면 위 주석의 노출 경로 서술을 갱신해야 한다")

    search_src = open(os.path.join(root, "api", "v1", "search.py"), encoding="utf-8-sig").read()
    check_true("검색은 여전히 만료 물건을 기본 제외한다(D7)",
               "auction_date >= ?" in search_src,
               "검색의 D7 기본 제외가 사라졌다면 노출 범위가 크게 넓어진다")


def test_live_expired_collecting_is_measurable():
    print("\n--- 7. 실제 DB에서 '끝나지 않는 수집중'을 측정한다 ---")
    root = os.path.dirname(os.path.abspath(__file__))
    dbp = os.path.join(root, "auction.db")
    if not os.path.exists(dbp):
        print("[SKIP] auction.db 없음 (fresh clone)")
        return
    c = sqlite3.connect("file:%s?mode=ro" % dbp, uri=True)
    try:
        expired_collecting = c.execute("""
            SELECT COUNT(*) FROM document_status ds
            JOIN auction_item ai ON ai.id = ds.item_id
            WHERE ds.status = 'COLLECTING'
              AND ai.auction_date < date('now','localtime')
        """).fetchone()[0]
        live_collecting = c.execute("""
            SELECT COUNT(*) FROM document_status ds
            JOIN auction_item ai ON ai.id = ds.item_id
            WHERE ds.status = 'COLLECTING'
              AND ai.auction_date >= date('now','localtime')
        """).fetchone()[0]
        print("    만료 물건의 COLLECTING: %d건 / 진행중 물건의 COLLECTING: %d건"
              % (expired_collecting, live_collecting))
        # 과거에 쌓인 값이라 코드 수정만으로 0이 되지 않는다(§5와 같은 이유).
        # 계약은 '0이어야 한다'가 아니라 '측정 경로가 유효해야 한다'다.
        check_true("측정할 수 있다(조회 경로가 유효)", expired_collecting >= 0)
        check_true("두 값을 구분해서 셀 수 있다", live_collecting >= 0)
    finally:
        c.close()


# ---------------------------------------------------------------------------
# 8. 문서 개정 감지 - document_version_log의 양성 경로 (2026-08-13 Sprint 77 신설)
#
# `mark_queue_done()`은 이전 해시와 새 해시가 **다를 때만** version log를 남긴다.
#
#     if previous_hash and previous_hash != new_hash:
#         INSERT INTO document_version_log ...
#
# 그런데 지금까지의 검사는 전부 `previous_hash=""`(최초 수집)로만 호출했다. 즉
# **"기록하지 않는다"는 쪽만 검증되고 "기록한다"는 쪽은 한 번도 실행된 적이 없었다.**
#
# 실제 auction.db도 이 테이블이 0행이다. 다만 그것은 결함이 아니라 정상이다 - 지금까지
# 수집된 559건이 전부 최초 수집이라 비교할 이전 해시가 없었을 뿐이다. 문제는 그래서
# **이 경로가 깨져 있어도 아무도 눈치챌 수 없다**는 점이다.
#
# 왜 중요한가 - 매각물건명세서는 매각기일 전에 **정정 공고**가 나는 일이 있다. 이 테이블은
# "우리가 받아 둔 문서가 그 뒤에 바뀌었다"를 남기는 유일한 기록이다. 사용자가 옛 문서를
# 보고 판단하는 것을 나중에 추적할 수 있는 근거가 여기밖에 없다.
# ---------------------------------------------------------------------------
def test_document_revision_is_logged():
    print("\n--- 8. 문서가 바뀌면 version log에 남는가 ---")
    with TempDB() as db:
        def vlog():
            return db.query("SELECT * FROM document_version_log ORDER BY id")

        # (1) 최초 수집: 비교할 이전 해시가 없으므로 기록하지 않는다.
        dbmod.mark_queue_done(900, "B000210", "2024타경1636", "1", "spec", "", "hash-v1")
        check("최초 수집은 version log를 남기지 않는다", len(vlog()), 0)

        # (2) 내용이 바뀌었다: 기록해야 한다.
        dbmod.mark_queue_done(900, "B000210", "2024타경1636", "1", "spec", "hash-v1", "hash-v2")
        rows = vlog()
        check("문서가 바뀌면 version log가 남는다", len(rows), 1)
        if rows:
            r = rows[0]
            check("법원이 기록된다", r["court_code"], "B000210")
            check("사건번호가 기록된다", r["case_no"], "2024타경1636")
            check("물건번호가 기록된다", r["item_no"], "1")
            check("문서종류가 기록된다", r["doc_type"], "spec")
            check("이전 해시가 기록된다", r["previous_hash"], "hash-v1")
            check("새 해시가 기록된다", r["new_hash"], "hash-v2")
            check_true("갱신 시각이 기록된다", bool(r["updated_at"]), r["updated_at"])

        # (3) 내용이 그대로다: 다시 수집해도 기록하지 않는다
        #     (같은 문서를 재수집할 때마다 로그가 쌓이면 진짜 개정을 찾을 수 없다).
        dbmod.mark_queue_done(900, "B000210", "2024타경1636", "1", "spec", "hash-v2", "hash-v2")
        check("내용이 같으면 기록하지 않는다", len(vlog()), 1)

        # (4) 다시 바뀌면 또 남는다 - 개정 이력이 누적돼야 추적이 된다.
        dbmod.mark_queue_done(900, "B000210", "2024타경1636", "1", "spec", "hash-v2", "hash-v3")
        rows = vlog()
        check("두 번째 개정도 누적된다", len(rows), 2)
        if len(rows) == 2:
            check("개정 이력이 순서대로 이어진다",
                  [(r["previous_hash"], r["new_hash"]) for r in rows],
                  [("hash-v1", "hash-v2"), ("hash-v2", "hash-v3")])

        # (5) 문서종류가 다르면 별개로 기록된다(한 물건의 세 문서가 서로 섞이면 안 된다).
        dbmod.mark_queue_done(900, "B000210", "2024타경1636", "1", "status", "s-v1", "s-v2")
        types = [r["doc_type"] for r in vlog()]
        check("문서종류별로 구분돼 기록된다", sorted(set(types)), ["spec", "status"])

        # 개정이 기록돼도 화면 상태는 READY 그대로여야 한다(개정은 실패가 아니다).
        check("개정 후에도 화면 상태는 READY",
              db.one("SELECT status FROM document_status WHERE item_id=111 AND doc_type='SPEC'"),
              "READY")


# ---------------------------------------------------------------------------
# 9. 재시도 복구가 화면 상태를 함께 되돌리는가 (2026-08-13 Sprint 78 신설, BUGS #73)
#
# `mark_queue_failed()`는 자기 규칙을 이렇게 적어 두었다 — "재시도가 소진된 **최종**
# 실패만 화면에 반영한다. 중간 재시도까지 FAILED로 바꾸면 다음 시도에서 성공할 문서가
# 잠깐 '실패'로 보였다가 돌아온다."
#
# 그런데 `reset_stale_queue()`가 하루 지난 failed 행을 `pending` + `retry_count=0`
# (완전히 새 시도)으로 되돌리면서 **화면 상태는 FAILED로 남겨두었다.** 실측:
#
#     복구 전  queue=failed   document_status=FAILED
#     복구 후  queue=pending  document_status=FAILED   <- 재시도 대기인데 "수집실패"
#
# 즉 위 규칙이 이 경로에서만 깨져 있었다. #50이 정한 "두 기록은 같은 트랜잭션에서 함께
# 갱신한다"도 함께 어긋난 상태다.
#
# 반대 방향의 과잉 수정을 막는 것이 이 섹션의 절반이다 — **READY를 COLLECTING으로
# 덮으면 파일이 실제로 있는 문서를 "수집중"으로 가린다**(사용자가 볼 수 있는 것을 못 보게
# 된다). 그래서 "지금 FAILED인 행만" 되돌리는지까지 검사한다.
# ---------------------------------------------------------------------------
def _make_stale(db, queue_status, doc_status, ago):
    """큐 900번을 원하는 상태로 만들고 화면 상태도 맞춘 뒤 복구를 실행한다."""
    conn = dbmod.get_connection()
    try:
        # ★ 'localtime' 필수. 운영 코드는 `last_attempt_at`을 파이썬
        #   `datetime.now().isoformat()`(로컬)으로 쓰고, `reset_stale_queue()`도 로컬로
        #   비교한다. 픽스처만 UTC로 넣으면 "-1 hours"라고 적어 둔 행이 한국 기준으로는
        #   **10시간 전**이 되어, 검사가 의도한 상황을 실제로는 만들지 못한다.
        conn.execute(
            "UPDATE document_queue SET status=?, retry_count=3,"
            " last_attempt_at=datetime('now','localtime', ?) WHERE id=900",
            (queue_status, ago))
        conn.execute(
            "UPDATE document_status SET status=? WHERE item_id=111 AND doc_type='SPEC'",
            (doc_status,))
        conn.commit()
    finally:
        conn.close()
    dbmod.reset_stale_queue()
    return (db.one("SELECT status FROM document_queue WHERE id=900"),
            db.one("SELECT status FROM document_status WHERE item_id=111 AND doc_type='SPEC'"))


def test_retry_recovery_restores_screen_status():
    print("\n--- 9. 재시도 복구가 화면 상태를 함께 되돌리는가 (BUGS #73) ---")

    # (1) 최종 실패 -> 재시도 대기: 화면도 수집중으로 돌아와야 한다
    with TempDB() as db:
        q, ds = _make_stale(db, "failed", "FAILED", "-2 days")
        check("하루 지난 failed는 pending으로 회수된다", q, "pending")
        check("화면 상태도 COLLECTING으로 되돌아온다", ds, "COLLECTING")

    # (2) 이미 수집 성공한 문서(READY)는 건드리지 않는다 — 가장 중요한 반대 방향이다.
    #     큐가 어떤 이유로 failed였더라도 파일이 있으면 사용자는 그것을 볼 수 있어야 한다.
    with TempDB() as db:
        q, ds = _make_stale(db, "failed", "READY", "-2 days")
        check("회수는 그대로 일어난다", q, "pending")
        check("READY는 COLLECTING으로 덮이지 않는다", ds, "READY")

    # (3) in_progress 회수(죽은 Worker)는 화면 상태를 건드릴 이유가 없다.
    #     그 행은 애초에 수집 중이었으므로 화면은 이미 맞다.
    with TempDB() as db:
        q, ds = _make_stale(db, "in_progress", "READY", "-30 minutes")
        check("죽은 Worker의 in_progress는 회수된다", q, "pending")
        check("in_progress 회수는 화면 상태를 바꾸지 않는다", ds, "READY")

    # (4) 회수 대상이 아닌 failed(재시도 간격 전)는 화면도 그대로여야 한다 —
    #     아직 최종 실패 상태이므로 "수집실패"가 맞다.
    with TempDB() as db:
        q, ds = _make_stale(db, "failed", "FAILED", "-1 hours")
        check("최근 failed는 회수하지 않는다", q, "failed")
        check("회수하지 않았으면 화면도 FAILED 그대로", ds, "FAILED")

    # (5) SKIPPED_EXPIRED는 회수 대상이 아니다(#69의 전제) — 화면도 불변이어야 한다.
    with TempDB() as db:
        q, ds = _make_stale(db, "SKIPPED_EXPIRED", "COLLECTING", "-2 days")
        check("SKIPPED_EXPIRED는 회수 대상이 아니다", q, "SKIPPED_EXPIRED")
        check("따라서 화면 상태도 변하지 않는다", ds, "COLLECTING")

    # (6) 화면 기록이 아예 없는 행(큐만 있는 상태)에서도 죽지 않아야 한다.
    #     `_current_document_status()`가 None을 돌려주는 경로다.
    with TempDB() as db:
        conn = dbmod.get_connection()
        try:
            conn.execute("DELETE FROM document_status WHERE item_id=111 AND doc_type='SPEC'")
            conn.execute("UPDATE document_queue SET status='failed', retry_count=3,"
                         " last_attempt_at=datetime('now','localtime','-2 days')"
                         " WHERE id=900")
            conn.commit()
        finally:
            conn.close()
        crashed = None
        try:
            dbmod.reset_stale_queue()
        except Exception as exc:  # noqa: BLE001
            crashed = exc
        check_true("화면 기록이 없어도 복구가 죽지 않는다", crashed is None, repr(crashed))
        check("회수는 정상 수행된다", db.one("SELECT status FROM document_queue WHERE id=900"),
              "pending")
        # 기록이 없던 행을 새로 만들지 않는다 — 큐만 있는 유령 행에 화면 상태를 지어내면
        # 그 자체가 #69가 지적한 "도착하지 않을 문서를 기다리는" 상태를 새로 만든다.
        check("없던 화면 기록을 새로 만들지는 않는다",
              db.one("SELECT COUNT(*) FROM document_status WHERE item_id=111 AND doc_type='SPEC'"),
              0)

    # (7) ★ 화면 동기화가 **깨져도 큐 회수는 살아남아야 한다.**
    #
    # 이 함수의 본 작업은 "재시도할 행을 pending으로 회수"이고 화면 반영은 딸린 작업이다.
    # 화면 쪽에서 예외가 나 커밋 전에 빠져나가면 회수 UPDATE까지 사라져 doc_worker가
    # 아무것도 회수되지 않은 채 시작한다 — 고치려던 것보다 나쁜 결과다.
    #
    # 이 시나리오는 가정이 아니다: `document_status`/`auction_item`이 없는 축소 스키마
    # (`test_document_queue.py`의 임시 DB)에서 실제로 이 경로가 통째로 죽는 것을
    # 기존 테스트가 잡아냈다(Sprint 78). 그 상황을 여기에 명시적으로 고정한다.
    with TempDB() as db:
        conn = dbmod.get_connection()
        try:
            conn.execute("UPDATE document_queue SET status='failed', retry_count=3,"
                         " last_attempt_at=datetime('now','localtime','-2 days')"
                         " WHERE id=900")
            conn.commit()
            # 화면 테이블을 없애 동기화가 반드시 실패하게 만든다.
            conn.execute("DROP TABLE document_status")
            conn.commit()
        finally:
            conn.close()

        crashed = None
        try:
            dbmod.reset_stale_queue()
        except Exception as exc:  # noqa: BLE001
            crashed = exc
        check_true("화면 테이블이 없어도 복구가 죽지 않는다", crashed is None, repr(crashed))
        check("화면 동기화가 실패해도 큐 회수는 커밋된다",
              db.one("SELECT status FROM document_queue WHERE id=900"), "pending")
        check("회수된 행의 retry_count도 초기화된다",
              db.one("SELECT retry_count FROM document_queue WHERE id=900"), 0)


# ---------------------------------------------------------------------------
# 10. 큐에만 있고 물건은 없는 행(고아)을 측정한다 (2026-08-13 Sprint 78 신설)
#
# `_set_document_status()`는 대상 `auction_item`을 못 찾으면 경고만 남기고 False를
# 돌려준다(수집 자체는 계속 진행). 그 경고가 실제로 발생하는 행이 **얼마나 있는지**는
# 아무도 세지 않았다. 세지 않으면 늘어나도 모른다.
#
# 실측(2026-08-13): 큐 3,498행 중 18행이 대응 `auction_item`을 갖지 않는다.
#
#     pending 12 / SKIPPED_EXPIRED 3 / done 3
#     6개 사건 중 5개는 auction_case 자체가 없고,
#     1개(성남지원 2024타경4973)는 사건은 있는데 물건번호 1이 없다(실제 물건은 2~10).
#
# 지금 피해는 사실상 없다 — pending 12행은 전부 기일이 지나 다음 Worker 실행에서
# 브라우저 작업 없이 SKIPPED_EXPIRED가 된다. 문제는 **조용히 쌓인다**는 것이다.
# 고아 행이 늘면 그만큼 화면에 도달하지 못하는 수집 작업이 늘고, pending 건수도 부풀린다.
#
# 운영 DB의 행을 지우는 것은 이 범위가 아니다(#70과 같은 판단 — 데이터 정리는 운영
# 결정이다). 대신 §5/§7과 같은 관례로 **측정 경로**를 고정해, 다음에 이 숫자를 볼 때
# 늘었는지 줄었는지 판단할 수 있게 한다.
# ---------------------------------------------------------------------------
def test_orphan_queue_rows_are_measurable():
    print("\n--- 10. 큐에만 있고 물건이 없는 행(고아)을 측정한다 ---")
    root = os.path.dirname(os.path.abspath(__file__))
    dbp = os.path.join(root, "auction.db")
    if not os.path.exists(dbp):
        print("[SKIP] auction.db 없음 (fresh clone)")
        return
    c = sqlite3.connect("file:%s?mode=ro" % dbp, uri=True)
    c.row_factory = sqlite3.Row   # §5/§7은 스칼라만 읽지만 여기는 컬럼명으로 읽는다
    try:
        # 프로덕션 `_document_status_item_id()`와 **같은 조인**을 쓴다 — 다른 조인으로 세면
        # 프로덕션이 못 찾는 행과 이 측정이 못 찾는 행이 달라진다.
        # (실제로 이 측정을 쓰다 court_code만으로 조인해 3,498행이 128,469행으로 불어난
        #  적이 있다. 조인 결과 행 수가 큐 행 수와 같은지 아래에서 함께 확인한다.)
        JOIN = """
            FROM document_queue q
            LEFT JOIN auction_item ai
                   ON ai.case_no = q.case_no AND ai.item_no = q.item_no
                  AND ai.case_id IN (SELECT id FROM auction_case WHERE court_code = q.court_code)
        """
        total = c.execute("SELECT COUNT(*) FROM document_queue").fetchone()[0]
        joined = c.execute("SELECT COUNT(*) " + JOIN).fetchone()[0]
        orphans = c.execute("SELECT COUNT(*) " + JOIN + " WHERE ai.id IS NULL").fetchone()[0]
        by_status = c.execute(
            "SELECT q.status s, COUNT(*) n " + JOIN + " WHERE ai.id IS NULL GROUP BY s"
        ).fetchall()

        print("    큐 %d행 중 고아 %d행  (%s)"
              % (total, orphans, ", ".join("%s=%d" % (r["s"], r["n"]) for r in by_status) or "없음"))

        # ★ 측정 자체의 건전성부터 본다. 조인이 행을 불리면 위 숫자는 전부 무의미하다.
        check("측정 조인이 큐 행을 부풀리거나 잃지 않는다", joined, total)
        check_true("고아 행을 셀 수 있다(조회 경로가 유효)", orphans >= 0)

        # 고아 중 pending인 것은 앞으로 Worker가 집는다 — 그 결과가 화면에 도달하지
        # 못하므로, 기일이 미래인 고아가 있으면 실제 낭비가 된다. 지금은 0이어야 한다.
        wasteful = c.execute(
            "SELECT COUNT(*) " + JOIN +
            " WHERE ai.id IS NULL AND q.status='pending'"
            # doc_worker가 만료를 판정할 때 쓰는 "오늘"은 로컬 기준
            # (`datetime.now().strftime("%Y-%m-%d")`)이다. 여기서 UTC로 물으면
            # 배치가 도는 02:00 KST에 날짜가 하루 어긋나 서로 다른 "오늘"을 보게 된다.
            "   AND q.auction_date IS NOT NULL"
            "   AND q.auction_date >= date('now','localtime')"
        ).fetchone()[0]
        print("    그중 기일이 미래인 pending(실제 낭비): %d행" % wasteful)
        check("기일이 미래인 고아 pending은 없다", wasteful, 0)
    finally:
        c.close()


def test_current_status_lookup_guards():
    """`_current_document_status()`의 "모르면 None" 두 갈래 (2026-08-13 Sprint 85 신설).

    커버리지가 지목한 두 줄이다. 이 함수는 `reset_stale_queue()`가 **조건부 복구**
    ("지금 FAILED인 행만 COLLECTING으로 되돌린다")를 하려고 현재 화면 상태를 읽는 데 쓴다.
    여기서 모르는 값에 예외를 던지면 큐 복구 전체가 중단되고(재시도 대기 행이 영구히
    멈춘다), 반대로 아무 값이나 지어내면 이미 READY인 문서를 COLLECTING으로 덮어
    **볼 수 있는 문서를 화면에서 가린다**. 그래서 "모르면 None"이 정답이고, 그 계약을 고정한다.
    """
    print("\n--- 12. 현재 화면 상태 조회의 방어 (Sprint 85) ---")
    with TempDB() as db:
        conn = dbmod.get_connection()
        try:
            check("정상 조회는 상태를 돌려준다",
                  dbmod._current_document_status(conn, "B000210", "2024타경1636", "1", "spec"),
                  "COLLECTING")
            # 큐 표기는 소문자 계약이다. 대문자/오타는 **모르는 값**이므로 None이어야 한다
            # (조용히 pdf로 떨어뜨렸던 doc_exists() 결함과 같은 부류를 여기서 막는다).
            for bad in ("SPEC", "registry", "", None):
                check("모르는 doc_type(%r)은 None" % (bad,),
                      dbmod._current_document_status(conn, "B000210", "2024타경1636", "1", bad),
                      None)
            # 대응 물건이 없는 키 ― 큐에만 있고 auction_item에는 없는 고아 행에서 실제로 발생한다.
            check("대응 물건이 없으면 None",
                  dbmod._current_document_status(conn, "B999999", "9999타경1", "1", "spec"),
                  None)
            # 물건은 있지만 아직 상태 기록이 없는 종류
            conn.execute("DELETE FROM document_status WHERE item_id=111 AND doc_type='STATUS'")
            conn.commit()
            check("상태 기록이 아직 없으면 None",
                  dbmod._current_document_status(conn, "B000210", "2024타경1636", "1", "status"),
                  None)
        finally:
            conn.close()


def test_ready_means_the_viewer_can_serve_it():
    """READY는 **뷰어가 실제로 열 수 있는 상태**여야 한다 (2026-08-13 Sprint 85 신설).

    "완료" 판정과 "서빙" 대상이 **서로 다른 파일**이라는 점이 이 검사의 이유다.

        doc_exists()/보정 스크립트   status.json 을 기준 파일로 본다 (READY 판정)
        api/v1/documents.py          status.html 을 내려준다      (뷰어가 여는 것)

    `collect_status()`가 둘을 함께 쓰기 때문에 지금은 어긋나지 않는다. 하지만 한쪽만 남는
    경우(html 쓰기 실패, 정리 스크립트가 html만 지움, 규칙이 갈라짐)가 생기면 화면은
    "완료"라고 말하고 뷰어는 404를 준다 — `repair_document_status.py`의 주석이 정확히
    그것을 경계한다("여기서 규칙이 갈라지면 READY인데 뷰어는 404가 된다").

    기존 일관성 검사는 **판정 쪽 파일**(json)만 봤다. 그래서 이 갈라짐은 어떤 검사에도
    걸리지 않았다. 여기서는 **뷰어가 서빙하는 파일 이름 그대로** 디스크를 확인한다.

    실측 2026-08-13: READY 556행 전부 서빙 가능(STATUS 162행은 json/html 둘 다 존재).
    그래서 여기서는 "측정 가능"이 아니라 **0건**을 계약으로 둔다 — 지금 0이므로, 1건이라도
    생기는 순간이 곧 회귀다.
    """
    print("\n--- 11. READY는 뷰어가 서빙할 수 있는 상태인가 (Sprint 85) ---")
    root = os.path.dirname(os.path.abspath(__file__))
    dbp = os.path.join(root, "auction.db")
    if not os.path.exists(dbp):
        print("[SKIP] auction.db 없음 (fresh clone)")
        return

    # 뷰어가 쓰는 것과 **같은** 매핑/경로 규칙을 그대로 가져온다. 여기서 복사해 적으면
    # 규칙이 갈라져도 이 검사가 통과해버린다(그게 막으려는 결함 자체다).
    from api.v1.documents import DOC_TYPE_FILES, get_doc_dir as viewer_doc_dir
    from crawler.doc_paths import CANONICAL_DOC_FILENAME, _PRIMARY_EXT

    check_true("뷰어 매핑이 3종을 덮는다", set(DOC_TYPE_FILES) == {"SPEC", "STATUS", "APPRAISAL"},
               sorted(DOC_TYPE_FILES))
    # 이 검사가 존재하는 근거를 사실로 고정한다 — STATUS만 **판정 파일과 서빙 파일이 다르다**.
    # (`doc_exists()`는 _PRIMARY_EXT로 status.json을 보고, 뷰어는 status.html을 내려준다.)
    check("STATUS: 판정은 json, 서빙은 html",
          ("status." + _PRIMARY_EXT["status"], DOC_TYPE_FILES["STATUS"][0]),
          ("status.json", "status.html"))
    check("SPEC/APPRAISAL은 판정 파일과 서빙 파일이 같다",
          [("%s.%s" % (k, _PRIMARY_EXT[k]), DOC_TYPE_FILES[k.upper()][0]) for k in ("spec", "appraisal")],
          [("spec.pdf", "spec.pdf"), ("appraisal.pdf", "appraisal.pdf")])
    # 크롤러가 완성하는 경로(canonical)와 뷰어가 여는 경로는 **반드시** 같아야 한다.
    # 갈라지면 크롤러는 저장에 성공하고 뷰어는 영원히 404를 준다.
    check("크롤러 저장 파일명 == 뷰어 서빙 파일명",
          {k: v for k, v in CANONICAL_DOC_FILENAME.items()},
          {k: v[0] for k, v in DOC_TYPE_FILES.items()})

    c = sqlite3.connect("file:%s?mode=ro" % dbp, uri=True)
    c.row_factory = sqlite3.Row
    try:
        rows = c.execute(
            "SELECT ds.doc_type, ai.court_name, ai.case_no, ai.item_no"
            " FROM document_status ds JOIN auction_item ai ON ds.item_id = ai.id"
            " WHERE ds.status = 'READY'"
        ).fetchall()
    finally:
        c.close()

    # 0행이면 "전부 서빙 가능"이 공허하게 참이 된다(빈 집합 함정 — 2026-08-13에 검색 필터
    # 검사에서 실제로 겪었다). 먼저 검사할 대상이 있는지 확인한다.
    check_true("READY 행이 존재한다(검사가 공허하지 않다)", len(rows) > 0, len(rows))

    unservable = []
    by_type = {}
    for r in rows:
        by_type[r["doc_type"]] = by_type.get(r["doc_type"], 0) + 1
        if r["doc_type"] not in DOC_TYPE_FILES:
            unservable.append("알 수 없는 doc_type: %s" % r["doc_type"])
            continue
        filename = DOC_TYPE_FILES[r["doc_type"]][0]
        if not r["court_name"] or not r["case_no"]:
            # 뷰어도 이 경우 404를 준다(경로를 만들 수 없다) — READY면 안 되는 상태다.
            unservable.append("경로를 만들 수 없다: %s/%s" % (r["court_name"], r["case_no"]))
            continue
        path = os.path.join(viewer_doc_dir(r["court_name"], r["case_no"], r["item_no"]), filename)
        if not os.path.exists(path):
            unservable.append("없음: %s" % path)
        elif os.path.getsize(path) == 0:
            # 0바이트는 뷰어가 200을 주지만 사용자에게는 빈 문서다 — READY의 뜻이 아니다.
            unservable.append("0바이트: %s" % path)

    print("    READY %d행 (%s)" % (len(rows), ", ".join("%s %d" % kv for kv in sorted(by_type.items()))))
    check("READY인데 뷰어가 서빙할 수 없는 행", len(unservable), 0)
    if unservable:
        for line in unservable[:5]:
            print("      " + line)

    # ── 반대 방향도 본다 (2026-08-14 추가) ──────────────────────────────────
    #
    # 위 검사는 "READY -> 파일이 있는가" 한 방향이다. 반대쪽도 결함이다 ―
    # **파일은 있는데 상태가 READY가 아니면**, 실제로 받아 둔 문서를 사용자가 못 본다.
    # 화면은 "수집중"을 띄우고, 뷰어를 여는 버튼도 나오지 않는다.
    #
    # 정상 경로에서는 생길 수 없다. `mark_queue_done()`이 파일 저장과 상태 갱신을
    # 같은 트랜잭션에서 하기 때문이다. 그래서 이 값이 0이 아니게 되는 경우는
    # **경로 밖에서 파일이 들어온 것**이다 ― 운영 스크립트, 수동 복사,
    # `collect_documents.py`(어떤 스케줄러도 실행하지 않는 모듈).
    # Sprint 111의 빈 캡처와 정확히 같은 부류의 입구다.
    #
    # 2026-08-14 실측: 서빙 가능한 파일 **556개** = READY **556행**, 양방향 모두 0건.
    # 지금 0이므로, 1건이라도 생기는 순간이 곧 회귀다(위와 같은 원칙).
    c = sqlite3.connect("file:%s?mode=ro" % dbp, uri=True)
    c.row_factory = sqlite3.Row
    try:
        others = c.execute(
            "SELECT ds.doc_type, ds.status, ai.court_name, ai.case_no, ai.item_no"
            " FROM document_status ds JOIN auction_item ai ON ds.item_id = ai.id"
            " WHERE ds.status != 'READY'"
        ).fetchall()
    finally:
        c.close()

    hidden = []
    for r in others:
        if r["doc_type"] not in DOC_TYPE_FILES:
            continue
        if not r["court_name"] or not r["case_no"]:
            continue
        path = os.path.join(viewer_doc_dir(r["court_name"], r["case_no"], r["item_no"]),
                            DOC_TYPE_FILES[r["doc_type"]][0])
        try:
            if os.path.isfile(path) and os.path.getsize(path) > 0:
                hidden.append("%s (status=%s): %s" % (r["doc_type"], r["status"], path))
        except OSError:
            continue

    print("    READY 아님 %d행 대조" % len(others))
    check("파일은 있는데 화면 상태가 READY가 아닌 행", len(hidden), 0)
    for line in hidden[:5]:
        print("      " + line)


# ---------------------------------------------------------------------------
# 13. 디스크에 빈 현황조사서 캡처가 남아 있지 않은가 (2026-08-14 신설)
#
# `test_doc_storage_atomicity.py` §4가 이미 두 가지를 지킨다 ― 판별 함수
# (`status_overlay_has_data`)가 빈 골격을 걸러 내는지, 그리고 `collect_status()`가
# **저장 직전에** 그 관문을 두는지. 둘 다 합성 HTML과 소스 검사다.
#
# 빠진 것은 **실제 디스크**다. 2026-08-12에 `status.html` 194건 중 33건이 빈 캡처였고
# (`crawler/doc_paths.py`의 근거), `repair_empty_status_capture.py`로 정리했다.
# 2026-08-14 재측정: **총 163건, 빈 캡처 0건.**
#
# 0으로 만들어 놓은 것을 0으로 지킨다. 이 파일 §11이 같은 자리에서 이미 세운 원칙이다 ―
# *"지금 0이므로, 1건이라도 생기는 순간이 곧 회귀다."*
#
# 왜 소스 검사만으로는 부족한가 — 관문은 `collect_status()` 하나에만 있다. 다른 경로로
# 파일이 들어오면(운영 스크립트, 수동 복사, `collect_documents.py`) 관문을 지나지 않는다.
# 그리고 한 번 저장되면 `doc_exists()`가 완료로 판정해 **영구히 재수집에서 빠진다.**
#
# 판정은 **운영 함수에 묻는다.** 기준을 여기 베끼면 두 기준이 갈라져도 통과한다.
# ---------------------------------------------------------------------------
def test_no_empty_status_captures_on_disk():
    print("\n--- 13. 디스크의 빈 현황조사서 캡처 (Sprint 111) ---")
    root = os.path.dirname(os.path.abspath(__file__))
    docroot = os.path.join(root, "documents")
    if not os.path.isdir(docroot):
        print("[SKIP] documents/ 없음 (fresh clone)")
        return

    from crawler.doc_crawler import status_overlay_has_data

    htmls = []
    for dirpath, dirnames, filenames in os.walk(docroot):
        htmls += [os.path.join(dirpath, f) for f in filenames if f == "status.html"]

    # 0건이면 "빈 캡처 없음"이 공허하게 참이 된다(§11이 경고한 빈 집합 함정).
    check_true("검사할 status.html이 존재한다(검사가 공허하지 않다)", len(htmls) > 0, len(htmls))

    empty, unreadable = [], []
    for path in htmls:
        try:
            with open(path, "rb") as f:
                text = f.read().decode("utf-8", "ignore")
        except OSError as exc:
            unreadable.append("%s (%s)" % (os.path.relpath(path, docroot), exc))
            continue
        if not status_overlay_has_data(text):
            empty.append(os.path.relpath(path, docroot))

    print("    status.html %d건" % len(htmls))
    check("빈 캡처가 디스크에 없다", len(empty), 0)
    for line in empty[:5]:
        print("      빈 캡처: " + line)
    check("읽을 수 없는 status.html이 없다", len(unreadable), 0)
    for line in unreadable[:3]:
        print("      " + line)


def run():
    test_done_marks_ready()
    test_doc_type_mapping()
    test_final_failure_marks_failed()
    test_unknown_item_does_not_crash()
    test_unknown_doc_type_is_rejected()
    test_repair_script_path_guard()
    test_live_db_drift_is_measurable()
    test_skipped_expired_does_not_reach_screen()
    test_live_expired_collecting_is_measurable()
    test_document_revision_is_logged()
    test_retry_recovery_restores_screen_status()
    test_orphan_queue_rows_are_measurable()
    test_current_status_lookup_guards()
    test_ready_means_the_viewer_can_serve_it()
    test_no_empty_status_captures_on_disk()

    print("\n" + "=" * 55)
    if failures:
        print("FAILED (%d): %s" % (len(failures), ", ".join(failures)))
        return 1
    print("ALL TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(run())
