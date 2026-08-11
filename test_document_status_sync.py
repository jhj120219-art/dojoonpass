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


def run():
    test_done_marks_ready()
    test_doc_type_mapping()
    test_final_failure_marks_failed()
    test_unknown_item_does_not_crash()
    test_unknown_doc_type_is_rejected()
    test_repair_script_path_guard()
    test_live_db_drift_is_measurable()

    print("\n" + "=" * 55)
    if failures:
        print("FAILED (%d): %s" % (len(failures), ", ".join(failures)))
        return 1
    print("ALL TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(run())
