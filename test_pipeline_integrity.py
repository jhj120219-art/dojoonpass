"""문서 파이프라인 단계 간 정합 회귀 테스트 (2026-08-11 Sprint 56 신설).

Sprint 55에서 파이프라인의 세 결함(BUGS #47/#48/#50)을 고친 뒤 각 단계가 서로 맞는지
실측했더니 불일치가 0이 됐다. 이 파일은 **그 상태를 불변식으로 못 박는다.**

추적하는 경로:

    auction_item -> document_queue -> worker -> 파일 -> document_status -> 파싱 -> 권리분석

이 검사는 실제 `auction.db`와 `documents/`를 읽는다. 데이터를 만들지도 고치지도 않는다
(읽기 전용 커넥션). fresh clone에는 DB가 없을 수 있으므로 그때는 건너뛴다.

selenium 불필요.

    python test_pipeline_integrity.py
"""
import sys
import os
import sqlite3
import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

ROOT = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(ROOT, "auction.db")

# api/v1/documents.py:DOC_TYPE_FILES / storage.database:QUEUE_TO_DOC_STATUS_TYPE 와 같아야 한다.
QUEUE_DOC_FILE = {"spec": "spec.pdf", "status": "status.html", "appraisal": "appraisal.pdf"}
QUEUE_TO_DS = {"spec": "SPEC", "status": "STATUS", "appraisal": "APPRAISAL"}

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


def doc_dir(court_name, case_no, item_no):
    """`api/v1/documents.py:get_doc_dir()` 와 같은 규칙.

    규칙이 갈라지면 이 테스트가 통과해도 뷰어는 404다 — 그래서 여기 복제하지 않고
    실제 모듈에서 가져오는 편이 낫지만, `api.v1.documents`는 fastapi를 끌어온다.
    대신 아래 `test_path_rule_matches_api()`가 두 구현이 같은 결과를 내는지 대조한다.
    """
    return os.path.join(ROOT, "documents", court_name or "",
                        (case_no or "").replace("/", "_").strip(),
                        (item_no or "1").replace("/", "_").strip())


def connect():
    return sqlite3.connect("file:%s?mode=ro" % DB.replace("?", "%3f"), uri=True)


# ---------------------------------------------------------------------------
def test_path_rule_matches_api():
    """이 파일의 경로 규칙이 API 서빙 규칙과 같은가.

    아래 모든 검사가 이 규칙 위에 서 있다. 규칙이 어긋나면 "파일 없음"을 잘못 세고,
    그 결과 진짜 불일치를 놓친다.
    """
    print("\n--- 0. 경로 규칙이 API와 일치하는가 ---")
    import re
    src = open(os.path.join(ROOT, "api", "v1", "documents.py"), encoding="utf-8-sig").read()

    files = dict(re.findall(r'"(SPEC|STATUS|APPRAISAL)":\s*\("([^"]+)"', src))
    check("문서 파일명이 API와 같다",
          {k: files.get(v) for k, v in QUEUE_TO_DS.items()},
          {k: QUEUE_DOC_FILE[k] for k in QUEUE_TO_DS})

    # 경로 조립 규칙(슬래시 치환 + strip)이 그대로인지
    check_true("case_no의 '/'를 '_'로 치환한다", 'case_no.replace("/", "_")' in src, src[:0])
    check_true("item_no 기본값이 '1'이다", '(item_no or "1")' in src)

    # storage.database의 doc_type 매핑과도 같아야 한다
    dbsrc = open(os.path.join(ROOT, "storage", "database.py"), encoding="utf-8-sig").read()
    m = re.search(r"QUEUE_TO_DOC_STATUS_TYPE\s*=\s*\{([^}]*)\}", dbsrc, re.S)
    check_true("QUEUE_TO_DOC_STATUS_TYPE가 존재한다", m is not None)
    if m:
        mapping = dict(re.findall(r'"(\w+)":\s*"(\w+)"', m.group(1)))
        check("큐->화면 doc_type 매핑이 같다", mapping, QUEUE_TO_DS)


def test_queue_state_machine_invariants():
    print("\n--- 1. document_queue 상태 자체의 정합 ---")
    conn = connect()
    try:
        one = lambda s: conn.execute(s).fetchone()[0]

        statuses = {r[0] for r in conn.execute("SELECT DISTINCT status FROM document_queue")}
        check("알려진 상태값만 존재한다",
              sorted(statuses - {"pending", "in_progress", "done", "failed", "SKIPPED_EXPIRED"}), [])

        # MAX_DOC_RETRY를 실제 코드에서 읽는다(테스트에 상수를 복제하면 값이 바뀌어도 통과한다)
        import re
        dbsrc = open(os.path.join(ROOT, "storage", "database.py"), encoding="utf-8-sig").read()
        m = re.search(r"MAX_DOC_RETRY\s*=\s*(\d+)", dbsrc)
        check_true("MAX_DOC_RETRY를 코드에서 읽었다", m is not None)
        max_retry = int(m.group(1)) if m else 3

        check("failed인데 재시도가 남아 있는 행 없음",
              one("SELECT COUNT(*) FROM document_queue WHERE status='failed' AND retry_count<%d" % max_retry), 0)
        check("pending인데 재시도가 소진된 행 없음",
              one("SELECT COUNT(*) FROM document_queue WHERE status='pending' AND retry_count>=%d" % max_retry), 0)
        check("retry_count가 음수인 행 없음",
              one("SELECT COUNT(*) FROM document_queue WHERE retry_count<0"), 0)

        # SKIPPED_EXPIRED는 "기일이 지나 대상이 아님"이라는 뜻이다.
        check("기일이 남았는데 SKIPPED_EXPIRED인 행 없음",
              one("SELECT COUNT(*) FROM document_queue WHERE status='SKIPPED_EXPIRED' AND auction_date>=date('now')"), 0)

        # in_progress로 오래 멈춘 행은 reset_stale_queue가 회수해야 한다.
        stuck = one("""SELECT COUNT(*) FROM document_queue WHERE status='in_progress'
                       AND (last_attempt_at IS NULL
                            OR datetime(last_attempt_at) < datetime('now','-1 day'))""")
        check("하루 넘게 in_progress로 멈춘 행 없음", stuck, 0)
    finally:
        conn.close()


def test_done_rows_have_file_and_ready_status():
    """큐가 done이면 파일이 있고 화면 상태도 READY여야 한다 (BUGS #50 회귀)."""
    print("\n--- 2. done -> 파일 -> document_status 정합 ---")
    conn = connect()
    conn.row_factory = sqlite3.Row
    try:
        done = conn.execute(
            "SELECT court_code, case_no, item_no, doc_type FROM document_queue WHERE status='done'"
        ).fetchall()
        check_true("검사 대상이 실제로 존재한다", len(done) > 0, "done 행이 0건이면 이 검사는 공허하다")

        no_file, no_ds, not_ready, no_item = [], [], [], []
        for r in done:
            ai = conn.execute(
                """SELECT ai.id, ai.court_name FROM auction_item ai
                   JOIN auction_case ac ON ac.id = ai.case_id
                   WHERE ac.court_code=? AND ai.case_no=? AND ai.item_no=?""",
                (r["court_code"], r["case_no"], r["item_no"])).fetchone()
            key = "%s/%s-%s/%s" % (r["court_code"], r["case_no"], r["item_no"], r["doc_type"])
            if not ai:
                no_item.append(key)
                continue
            if not os.path.exists(os.path.join(
                    doc_dir(ai["court_name"], r["case_no"], r["item_no"]),
                    QUEUE_DOC_FILE.get(r["doc_type"], "?"))):
                no_file.append(key)
            st = conn.execute("SELECT status FROM document_status WHERE item_id=? AND doc_type=?",
                              (ai["id"], QUEUE_TO_DS.get(r["doc_type"]))).fetchone()
            if not st:
                no_ds.append(key)
            elif st["status"] != "READY":
                not_ready.append(key)

        check("done인데 파일이 없는 행 없음", no_file[:5], [])
        check("done인데 document_status 행이 없는 것 없음", no_ds[:5], [])
        check("done인데 화면 상태가 READY가 아닌 것 없음", not_ready[:5], [])

        # 큐는 auction_item을 FK로 참조하지 않는다 — 물건이 사라져도 큐 행은 남는다.
        # 지금은 3건이며 전부 2026-07-10에 적재된 옛 행이다(법원 귀속이 바뀐 사건).
        # 늘어나면 크롤러가 만들어 내고 있다는 뜻이므로 상한을 둔다.
        check_true("대응 물건이 없는 done 행이 늘지 않았다 (현재 %d건)" % len(no_item),
                   len(no_item) <= 3, no_item[:5])
    finally:
        conn.close()


def test_files_are_reflected_in_queue():
    """반대 방향 — 파일이 있으면 큐도 done이어야 한다."""
    print("\n--- 3. 파일 -> 큐 (반대 방향) ---")
    conn = connect()
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute("""SELECT ai.court_name, ai.case_no, ai.item_no, ac.court_code
                               FROM auction_item ai JOIN auction_case ac ON ac.id = ai.case_id""").fetchall()
        found, bad = 0, []
        for r in rows:
            d = doc_dir(r["court_name"], r["case_no"], r["item_no"])
            if not os.path.isdir(d):
                continue
            for dt, fn in QUEUE_DOC_FILE.items():
                if not os.path.exists(os.path.join(d, fn)):
                    continue
                found += 1
                qr = conn.execute("""SELECT status FROM document_queue
                                     WHERE court_code=? AND case_no=? AND item_no=? AND doc_type=?""",
                                  (r["court_code"], r["case_no"], r["item_no"], dt)).fetchone()
                if qr is None or qr["status"] != "done":
                    bad.append("%s %s-%s %s -> %s"
                               % (r["court_name"], r["case_no"], r["item_no"], dt,
                                  qr["status"] if qr else "큐에 없음"))
        check_true("검사 대상 파일이 실제로 존재한다", found > 0, "파일을 하나도 못 찾으면 공허한 검사다")
        check("파일이 있는데 큐가 done이 아닌 것 없음", bad[:5], [])
    finally:
        conn.close()


def test_parsing_gap_is_measurable():
    """READY인데 파싱 결과가 없는 문서 수 — 화면의 SPEC_NOT_PARSED 대상이다.

    이 값은 파싱 스크립트가 스케줄러에 연결돼 있지 않아 0이 되지 않는다(운영 조치 필요).
    **0을 요구하지 않는다.** 대신 조회 경로가 살아 있는지와, 값이 갑자기 튀지 않는지만 본다.
    """
    print("\n--- 4. 문서 READY -> 파싱 결과 연결 (측정) ---")
    conn = connect()
    try:
        one = lambda s: conn.execute(s).fetchone()[0]
        spec_ready = one("SELECT COUNT(*) FROM document_status WHERE doc_type='SPEC' AND status='READY'")
        spec_parsed = one("""SELECT COUNT(*) FROM document_status ds
            WHERE ds.doc_type='SPEC' AND ds.status='READY'
              AND EXISTS (SELECT 1 FROM tenant_rights t WHERE t.item_id=ds.item_id AND t.source='SPEC')""")
        status_ready = one("SELECT COUNT(*) FROM document_status WHERE doc_type='STATUS' AND status='READY'")
        status_parsed = one("""SELECT COUNT(*) FROM document_status ds
            WHERE ds.doc_type='STATUS' AND ds.status='READY'
              AND EXISTS (SELECT 1 FROM rights_summary r WHERE r.item_id=ds.item_id)""")
        print("    SPEC   READY %d / 파싱됨 %d (미파싱 %d)" % (spec_ready, spec_parsed, spec_ready - spec_parsed))
        print("    STATUS READY %d / 파싱됨 %d (미파싱 %d)" % (status_ready, status_parsed, status_ready - status_parsed))

        check_true("조회 경로가 유효하다(READY 문서가 존재)", spec_ready > 0 and status_ready > 0)
        check_true("파싱된 것이 하나라도 있다", spec_parsed > 0 and status_parsed > 0)
        # 파싱 결과가 문서보다 많으면 어딘가 잘못 붙은 것이다.
        check_true("파싱 결과가 READY 문서 수를 넘지 않는다",
                   spec_parsed <= spec_ready and status_parsed <= status_ready)
    finally:
        conn.close()


def test_no_orphan_rows_in_pipeline_tables():
    print("\n--- 5. 파이프라인 테이블의 고아 행 ---")
    conn = connect()
    try:
        one = lambda s: conn.execute(s).fetchone()[0]
        for label, sql in (
            ("document_status -> auction_item",
             """SELECT COUNT(*) FROM document_status d
                WHERE NOT EXISTS (SELECT 1 FROM auction_item a WHERE a.id=d.item_id)"""),
            ("tenant_rights -> auction_item",
             """SELECT COUNT(*) FROM tenant_rights t
                WHERE NOT EXISTS (SELECT 1 FROM auction_item a WHERE a.id=t.item_id)"""),
            ("rights_summary -> auction_item",
             """SELECT COUNT(*) FROM rights_summary r
                WHERE NOT EXISTS (SELECT 1 FROM auction_item a WHERE a.id=r.item_id)"""),
            ("document_collect_failures -> auction_item",
             """SELECT COUNT(*) FROM document_collect_failures d
                WHERE NOT EXISTS (SELECT 1 FROM auction_item a WHERE a.id=d.item_id)"""),
            ("auction_item -> auction_case",
             """SELECT COUNT(*) FROM auction_item a
                WHERE a.case_id IS NOT NULL
                  AND NOT EXISTS (SELECT 1 FROM auction_case k WHERE k.id=a.case_id)"""),
        ):
            check(label, one(sql), 0)

        # document_status의 doc_type은 세 종류만이어야 한다(대문자 표기).
        kinds = sorted(r[0] for r in conn.execute("SELECT DISTINCT doc_type FROM document_status"))
        check("document_status.doc_type 표기", kinds, ["APPRAISAL", "SPEC", "STATUS"])
        kinds_q = sorted(r[0] for r in conn.execute("SELECT DISTINCT doc_type FROM document_queue"))
        check("document_queue.doc_type 표기", kinds_q, ["appraisal", "spec", "status"])
    finally:
        conn.close()


def test_property_type_matches_content():
    """물건 종류와 주소 끝 대괄호 내용이 서로 모순되지 않는가.

    2026-08-11 Sprint 56 발견: `property_type='자동차'`인데 주소가 `[토지 목장용지 353㎡]`인
    행이 있다(id=11804). `[집합건물 ... 45.22㎡]`인데 `자동차,중기`인 행도 있다(id=317).

    `normalizer`는 `property_type`을 가공하지 않고 크롤 값을 그대로 넘긴다. 따라서 원인은
    법원 사이트의 원본 분류이거나 크롤 파싱 어긋남인데, **어느 쪽인지는 실제 페이지를
    다시 열어 봐야** 안다(외부 네트워크 — 이번 Sprint SKIP).

    고칠 수 없더라도 **늘어나는 것은 막아야 한다.** 지금 2건이고, 이 수치가 커지면
    크롤러가 계속 잘못 분류하고 있다는 신호다.
    """
    import re
    print("\n--- 6. property_type과 실제 내용의 모순 (데이터 품질) ---")
    conn = connect()
    conn.row_factory = sqlite3.Row
    try:
        BR = re.compile(r"\[([^\]]*)\]\s*$")
        VEHICLE = re.compile(r"승용차|화물차|승합|굴착기|중기|건설기계|동력선|이륜|특수차|덤프|년식")
        bad = []
        for r in conn.execute(
                "SELECT id, property_type, full_address FROM auction_item "
                "WHERE property_type LIKE '%자동차%' OR property_type LIKE '%중기%'"):
            m = BR.search(r["full_address"] or "")
            inner = m.group(1) if m else ""
            if not VEHICLE.search(inner):
                bad.append("id=%s %s [%s]" % (r["id"], r["property_type"], inner[:40]))

        print("    차량으로 분류됐지만 내용이 차량이 아닌 행: %d건" % len(bad))
        for b in bad[:5]:
            print("      ", b)
        check_true("차량 오분류가 늘지 않았다 (현재 %d건, 상한 2)" % len(bad), len(bad) <= 2, bad[:5])

        # 반대 방향도 본다 — 내용은 차량인데 종류가 차량이 아닌 행.
        rev = []
        for r in conn.execute(
                "SELECT id, property_type, full_address FROM auction_item "
                "WHERE property_type NOT LIKE '%자동차%' AND property_type NOT LIKE '%중기%'"):
            m = BR.search(r["full_address"] or "")
            if m and VEHICLE.search(m.group(1)):
                rev.append("id=%s %s [%s]" % (r["id"], r["property_type"], m.group(1)[:40]))
        print("    내용은 차량인데 종류가 차량이 아닌 행: %d건" % len(rev))
        for b in rev[:5]:
            print("      ", b)
        check_true("역방향 오분류가 늘지 않았다 (현재 %d건, 상한 5)" % len(rev), len(rev) <= 5, rev[:5])
    finally:
        conn.close()


def run():
    if not os.path.exists(DB):
        print("[SKIPPED] auction.db 없음 (fresh clone) — 파이프라인 정합 검사 생략")
        return 0

    test_path_rule_matches_api()
    test_queue_state_machine_invariants()
    test_done_rows_have_file_and_ready_status()
    test_files_are_reflected_in_queue()
    test_parsing_gap_is_measurable()
    test_no_orphan_rows_in_pipeline_tables()
    test_property_type_matches_content()

    print("\n" + "=" * 55)
    if failures:
        print("FAILED (%d): %s" % (len(failures), ", ".join(failures)))
        return 1
    print("ALL TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(run())
