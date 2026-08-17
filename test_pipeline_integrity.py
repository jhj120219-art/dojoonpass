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
# **파일 하나로 서빙되는 문서 종류**만 담는다. 이 파일의 경로 기반 검사(파일 존재/불일치
# 집계)가 전부 이 표를 돈다.
QUEUE_TO_DS = {"spec": "SPEC", "status": "STATUS", "appraisal": "APPRAISAL"}
# 2026-08-17 Sprint 144: 큐가 다루는 자산은 문서 3종 + **물건 사진**이다.
# 사진은 물건당 0~N장이라 `api/v1/documents.py:DOC_TYPE_FILES`(종류당 파일 1개)에
# 들어가지 않고 `auction_image` + `api/v1/images.py`가 담당한다 — 그래서 위 표와
# 분리해 둔다. 아래 매핑 검사만 이 전체 표를 쓴다.
QUEUE_TO_DS_ALL = dict(QUEUE_TO_DS, image="IMAGE")

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

    # 경로 조립 규칙이 그대로인지.
    #
    # 2026-08-17 Sprint 146: 예전에는 `'case_no.replace("/", "_")' in src`로 **리터럴**을
    # 찾았다. 그런데 Sprint 145/146에 그 치환이 `crawler/doc_paths.py:sanitize_path_segment()`
    # 한 곳으로 모이면서(역슬래시·`..`·빈 값까지 처리) documents.py에서 리터럴이 사라졌다.
    # 리터럴 검사를 그대로 두면 **규칙이 좋아졌는데 테스트가 실패**한다.
    #
    # 지키려는 것은 "이 문자열이 소스에 있다"가 아니라 **쓰는 쪽과 읽는 쪽이 같은 경로를
    # 본다**는 것이므로, 두 구현의 결과를 직접 대조하는 쪽으로 바꾼다(더 강한 검사다 —
    # 리터럴이 같아도 결과가 다를 수 있고, 리터럴이 달라도 결과가 같으면 문제없다).
    check_true("documents.py가 공용 정규화 함수를 쓴다", "sanitize_path_segment" in src, src[:0])
    check_true("item_no 기본값이 '1'이다", '(item_no or "1")' in src)

    from api.v1.documents import get_doc_dir as _api_dir
    from crawler.doc_paths import _doc_dir_path as _crawler_dir
    for _court, _case, _item in (("서울중앙지방법원", "2024타경1 / 2024타경2", "1"),
                                 ("고양지원", "2024\\타경1", "2"),
                                 ("A법원", "2024타경9", "")):
        check("쓰는 쪽/읽는 쪽 경로 일치 (case=%r item=%r)" % (_case, _item),
              _api_dir(_court, _case, _item), _crawler_dir(_court, _case, _item))

    # storage.database의 doc_type 매핑과도 같아야 한다
    dbsrc = open(os.path.join(ROOT, "storage", "database.py"), encoding="utf-8-sig").read()
    m = re.search(r"QUEUE_TO_DOC_STATUS_TYPE\s*=\s*\{([^}]*)\}", dbsrc, re.S)
    check_true("QUEUE_TO_DOC_STATUS_TYPE가 존재한다", m is not None)
    if m:
        mapping = dict(re.findall(r'"(\w+)":\s*"(\w+)"', m.group(1)))
        check("큐->화면 doc_type 매핑이 같다", mapping, QUEUE_TO_DS_ALL)
        # 사진은 문서 서빙 표에 **없어야** 한다 — 들어가면 documents.py가 종류당 파일
        # 하나를 찾으려 들고, 0~N장인 사진에는 그 가정이 성립하지 않는다.
        check_true("사진은 문서 파일 표에 없다", "IMAGE" not in files, sorted(files))


def test_queue_state_machine_invariants():
    print("\n--- 1. document_queue 상태 자체의 정합 ---")
    conn = connect()
    try:
        one = lambda s: conn.execute(s).fetchone()[0]

        statuses = {r[0] for r in conn.execute("SELECT DISTINCT status FROM document_queue")}
        check("알려진 상태값만 존재한다",
              sorted(statuses - {"pending", "in_progress", "done", "failed",
                                 "SKIPPED_EXPIRED", "SKIPPED_UNSUPPORTED"}), [])

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
        #
        # ★ `date('now','localtime')`이어야 한다. doc_worker가 만료를 판정할 때 쓰는 것은
        #   `datetime.now().strftime("%Y-%m-%d")`(로컬)인데, 여기서 UTC로 물으면 **한국
        #   기준 00:00~09:00 사이에 날짜가 하루 어긋난다.** 배치가 도는 02:00이 정확히 그
        #   구간이라, 검사와 운영이 서로 다른 "오늘"을 보게 된다.
        check("기일이 남았는데 SKIPPED_EXPIRED인 행 없음",
              one("SELECT COUNT(*) FROM document_queue WHERE status='SKIPPED_EXPIRED'"
                  " AND auction_date>=date('now','localtime')"), 0)

        # SKIPPED_UNSUPPORTED는 "수집 버튼 id가 없어 성공할 수 없음"이라는 뜻이다.
        # 버튼 id가 **있는** 행에 이 상태가 붙으면 수집 가능한 문서를 영구히 포기한 것이 된다
        # (SKIPPED_* 는 reset_stale_queue가 되살리지 않으므로 되돌아올 길이 없다).
        # 판정은 실제 코드에 물어본다 — 여기에 규칙을 베껴 두면 코드가 바뀌어도 통과한다.
        from config.settings import get_doc_button_id
        # connect()는 row_factory를 두지 않는다 — 튜플 인덱스로 읽는다.
        wrong = [r for r in conn.execute(
            "SELECT court_code, case_no, item_no, doc_type FROM document_queue"
            " WHERE status='SKIPPED_UNSUPPORTED'").fetchall()
            if get_doc_button_id(r[3], r[2]) is not None]
        check("버튼 id가 있는데 SKIPPED_UNSUPPORTED인 행 없음", wrong, [])

        # in_progress로 오래 멈춘 행은 reset_stale_queue가 회수해야 한다.
        # `last_attempt_at`은 파이썬이 쓴 **로컬 시각**이므로 비교도 로컬이어야 한다
        # (UTC로 물으면 한국 기준 33시간을 물어보는 셈이 되어 검사가 느슨해진다).
        stuck = one("""SELECT COUNT(*) FROM document_queue WHERE status='in_progress'
                       AND (last_attempt_at IS NULL
                            OR datetime(last_attempt_at)
                               < datetime('now','localtime','-1 day'))""")
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
        # "미파싱"이라고 부르지 않는다 — 2026-08-12 Sprint 62 실측 결과 SPEC의 차이분은
        # 파싱 실패가 아니라 표에 `조사된 임차내역없음`이라고 적힌 **임차인 없는 물건**이었다.
        # 정상 동작을 결함처럼 보이게 하는 표현이라 "결과 행 없음"으로 바꾼다.
        print("    SPEC   READY %d / 파싱결과 있음 %d (결과 행 없음 %d ― 임차인 없음 포함)"
              % (spec_ready, spec_parsed, spec_ready - spec_parsed))
        print("    STATUS READY %d / 파싱결과 있음 %d (결과 행 없음 %d)"
              % (status_ready, status_parsed, status_ready - status_parsed))

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


def test_rights_data_has_evidence():
    """권리분석 파생 데이터에 근거 문서가 실제로 남아 있는가 (2026-08-12 Sprint 62 신설).

    `rights_summary` / `tenant_rights(source='STATUS')`는 `load_rights_data.py`가
    현황조사서(status.html)만 근거로 만든다. 그런데 이 스크립트는 파일이 없으면 DELETE
    이전에 early return 해서, **한 번 적재된 뒤 근거 문서가 사라지면 파생 행이 영원히
    남았다**(Sprint 62에 1건 실측 발견 — item_id=540, 사건 디렉터리 자체가 부재).

    화면은 그 근거를 확인할 방법이 없는 "현황조사서 임차인 N명"을 계속 보여주게 되므로,
    "명시된 내용만 근거로 사용한다"는 이 도메인의 대원칙에 정면으로 어긋난다.
    """
    print("\n--- 6. 권리분석 파생 데이터의 근거 문서 존재 ---")
    conn = connect()
    try:
        rows = conn.execute("""
            SELECT rs.item_id, ai.court_name, ai.case_no, ai.item_no
            FROM rights_summary rs JOIN auction_item ai ON rs.item_id = ai.id
        """).fetchall()
        # connect()는 row_factory를 쓰지 않는다(이 파일의 다른 검사와 동일하게 인덱스 접근).
        missing = [r for r in rows
                   if not os.path.exists(os.path.join(doc_dir(r[1], r[2], r[3]), "status.html"))]
        for r in missing[:5]:
            print("    근거 없음: item_id=%s %s %s-%s" % (r[0], r[1], r[2], r[3]))
        check("rights_summary 전 행에 status.html이 존재한다 (%d행 검사)" % len(rows),
              len(missing), 0)

        # tenant_rights는 두 근거에서 온다 — 각각 자기 근거 파일이 있어야 한다.
        # (source별 파일이 다르므로 한쪽만 검사하면 나머지 절반을 놓친다)
        for source, filename in (("STATUS", "status.html"), ("SPEC", "spec.pdf")):
            trows = conn.execute("""
                SELECT DISTINCT tr.item_id, ai.court_name, ai.case_no, ai.item_no
                FROM tenant_rights tr JOIN auction_item ai ON tr.item_id = ai.id
                WHERE tr.source = ?
            """, (source,)).fetchall()
            tmissing = [r for r in trows
                        if not os.path.exists(os.path.join(doc_dir(r[1], r[2], r[3]), filename))]
            for r in tmissing[:3]:
                print("    근거 없음(%s): item_id=%s %s %s-%s" % (source, r[0], r[1], r[2], r[3]))
            check("tenant_rights(%s) 전 물건에 %s가 존재한다 (%d물건 검사)"
                  % (source, filename, len(trows)), len(tmissing), 0)

        # source 값 자체도 두 종류뿐이어야 한다 — 새 값이 생기면 위 검사가 그 행을 통째로
        # 건너뛰어(검사 대상에서 빠져) 조용히 커버리지 구멍이 된다.
        sources = sorted(r[0] for r in conn.execute("SELECT DISTINCT source FROM tenant_rights"))
        check("tenant_rights.source 표기", sources, ["SPEC", "STATUS"])
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


# ---------------------------------------------------------------------------
# 9. 시각 비교가 같은 시간대끼리 이뤄지는가 (2026-08-14 신설)
#
# 이 저장소는 시각을 **로컬 시각**으로 저장한다 — `datetime.now().isoformat()`.
# 그런데 SQLite의 `datetime('now')`는 **UTC**다. 둘을 그대로 비교하면 시차만큼 어긋난다.
#
# 실제로 그 결함이 있었다(2026-08-14 실측, 한국=UTC+9):
#
#     claim_next_queue_item()   "30분 뒤 재시도"      -> 실제로는 9시간 30분
#     reset_stale_queue()       "in_progress 10분"    -> 실제로는 9시간 10분
#     reset_stale_queue()       "failed 하루"         -> 실제로는 33시간
#
# doc_worker는 02:00~04:00 두 시간만 돈다. 재시도 간격이 9시간 반이면 **한 번 실패한
# 문서는 그날 밤 안에 다시 시도될 수 없고**, 죽은 Worker가 남긴 in_progress 행도 그날
# 밤에는 회수되지 않는다. 두 방어 장치가 설계대로 동작한 적이 없었다.
#
# 조용한 결함이다 — 아무 예외도 나지 않고 로그도 "30분 후 재시도 가능"이라고 말한다.
# 그래서 결과가 아니라 **형태**로 막는다: 운영 코드가 `datetime('now')`를 쓸 때는
# 반드시 `localtime`을 함께 써야 한다.
#
# `date('now')`도 같다 — 02:00 KST는 UTC로 전날이라 날짜가 하루 어긋난다.
#
# ## 검사 대상에 **테스트 파일도 포함한다** (2026-08-14 확장)
#
# 처음에는 운영 코드만 훑었다. 그런데 운영 코드를 고친 뒤 같은 패턴을 다시 찾아보니
# **테스트 4개 파일이 여전히 UTC로 픽스처를 만들고 있었다.** 그게 더 위험하다 —
# 픽스처가 "-1 hours"라고 적어 두고 실제로는 한국 기준 10시간 전을 만들면,
# 검사는 통과하면서 의도한 상황을 한 번도 만들지 못한다. 이번 결함이 오래 숨어 있던
# 방식이 정확히 그것이었다(운영과 검사가 **같은 잘못된 전제**를 공유하면 영원히 통과한다).
#
# 그래서 저장소의 모든 추적 대상 `.py`를 본다. 예외를 두지 않는다 —
# 예외 목록은 곧 "여기만 UTC여도 된다"는 두 번째 규약이 되고, 그것이 이 결함의 뿌리다.
# ---------------------------------------------------------------------------
PRODUCTION_PY = [
    os.path.join("storage", "database.py"),
    os.path.join("storage", "checkpoint.py"),
    os.path.join("storage", "migrate_v4_1.py"),
    os.path.join("storage", "migrations", "run_migrations.py"),
    "doc_worker.py", "mvp_scraper.py", "migrate_execute.py", "refresh_priority.py",
    "api_server.py", "collect_documents.py",
]


def test_sqlite_now_is_localtime():
    print("\n--- 9. SQLite 시각 비교가 로컬 시각인가 ---")
    import ast
    import glob
    import re

    # ★ 목록을 손으로 적지 않는다 (2026-08-14 확장).
    #
    #   위 주석은 "저장소의 모든 추적 대상 .py를 본다. 예외를 두지 않는다"고 적어 뒀는데,
    #   구현은 몇 개 디렉터리만 훑고 있었다 — **루트의 운영 스크립트 28개가 검사 밖**이었다
    #   (backfill_* / repair_* / load_* / reset_failures / revalidate / migrate_dryrun ...).
    #   전부 DB에 쓰는 스크립트다. 위반은 0건이었지만(2026-08-14 실측),
    #   범위가 좁다는 사실 자체가 주석이 경고한 "여기만 UTC여도 된다"는 두 번째 규약이다.
    #
    #   그래서 git에게 묻는다 — 추적 파일 + 아직 커밋 안 된 새 파일(무시 대상 제외).
    #   `step*/check_*/patch_*` 같은 일회성 조사 스크립트는 .gitignore 대상이라
    #   자동으로 빠진다. 새 파일이 생기면 다음 실행부터 바로 대상이 된다.
    import subprocess
    files = []
    try:
        out = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "*.py"],
            cwd=ROOT, capture_output=True, text=True, timeout=30)
        if out.returncode == 0:
            files = [os.path.join(ROOT, p.replace("/", os.sep))
                     for p in out.stdout.split() if p.endswith(".py")]
    except (OSError, subprocess.SubprocessError):
        files = []
    if len(files) < 20:
        # git이 없는 배포본 — 예전 방식으로 되돌린다(범위는 좁지만 0건보다 낫다).
        print("    (git 목록을 얻지 못해 디렉터리 훑기로 대체한다)")
        files = [os.path.join(ROOT, p) for p in PRODUCTION_PY]
        for pat_ in ("api/**/*.py", "crawler/*.py", "validator/*.py",
                     "normalizer/*.py", "filter/*.py", "test_*.py"):
            files += sorted(glob.glob(os.path.join(ROOT, pat_.replace("/", os.sep)),
                                      recursive=True))
    files = sorted(set(files))

    # ★ 검사 대상은 **주석과 독스트링을 지운 소스 전체**다. 두 함정이 있었다.
    #
    #   1) 소스 전체를 그냥 훑으면 이 결함을 *설명하는 주석*을 결함으로 잡는다
    #      (처음 붙였을 때 실제로 그랬다).
    #   2) 그렇다고 AST로 문자열 상수만 골라 보면 **문자열을 이어 붙여 만든 SQL을
    #      놓친다.** 그런데 원래 결함이 있던 자리가 바로 그 형태였다:
    #
    #          datetime(\"\"\" + _NOW_LOCAL + \"\"\", '-\"\"\" + str(RETRY_INTERVAL_MINUTES) + ...
    #
    #      상수 단위로 보면 `'now'`와 닫는 괄호가 서로 다른 조각에 있어 아무것도 걸리지
    #      않는다(변이 M6로 확인 — 검사가 조용히 통과했다).
    #
    #   그래서 주석/독스트링만 지우고 **원문 그대로** 훑는다.
    def strip_prose(path):
        import io
        import tokenize
        src = open(path, encoding="utf-8-sig").read()
        lines = src.splitlines()
        blanked = [list(ln) for ln in lines]

        def blank(srow, scol, erow, ecol):
            for r in range(srow, erow + 1):
                if r - 1 >= len(blanked):
                    break
                row = blanked[r - 1]
                a = scol if r == srow else 0
                b = ecol if r == erow else len(row)
                for i in range(a, min(b, len(row))):
                    row[i] = " "

        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if tok.type == tokenize.COMMENT:
                blank(tok.start[0], tok.start[1], tok.end[0], tok.end[1])

        tree = ast.parse(src, filename=path)
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                 ast.AsyncFunctionDef)):
                body = getattr(node, "body", None) or []
                if body and isinstance(body[0], ast.Expr) and \
                        isinstance(body[0].value, ast.Constant) and \
                        isinstance(body[0].value.value, str):
                    c = body[0].value
                    blank(c.lineno, c.col_offset, c.end_lineno, c.end_col_offset)
        return "\n".join("".join(r) for r in blanked)

    pat = re.compile(r"\b(?:datetime|date|strftime)\s*\(\s*(?:'[^']*'\s*,\s*)?'now'[^)]*\)")
    offenders = []
    scanned = 0
    for path in files:
        if not os.path.exists(path):
            continue
        scanned += 1
        text = strip_prose(path)
        for m in pat.finditer(text):
            if "localtime" in m.group(0):
                continue
            line = text[:m.start()].count("\n") + 1
            offenders.append("%s:%d  %s" % (os.path.relpath(path, ROOT), line,
                                            m.group(0).strip()))
    print("    .py %d개 검사" % scanned)
    # 범위가 조용히 좁아지지 않게 한다 — git 목록이면 100개 안팎이고,
    # 폴백(디렉터리 훑기)이라도 40개는 넘는다. 한 자릿수면 무언가 잘못된 것이다.
    check_true("검사 대상 파일이 실제로 있다", scanned > 40, scanned)
    check("`now`를 쓰면서 localtime을 빠뜨린 자리 없음", offenders, [])


# ---------------------------------------------------------------------------
# 10. 법원 식별자 규약 — 코드와 데이터가 같은 것을 가리키는가 (2026-08-14 신설)
#
# `doc_worker`는 큐에서 꺼낸 `court_code`로 법원을 찾는다.
#
#     crawler/base_crawler.py:go_to_case_detail()
#         court = next((c for c in ALL_COURTS if c.code == court_code), None)
#         if not court:
#             logger.error("법원 코드 매칭 실패: %s", court_code)
#             return False        <- 그 법원의 문서는 하나도 수집되지 않는다
#
# 실패해도 **예외가 아니라 로그 한 줄**이고, 큐 행은 그냥 실패로 쌓인다. 즉 규약이
# 어긋나면 조용히 멈춘다.
#
# 이 저장소의 규약은 "법원 식별자 = 한글 법원명"이다(ALL_COURTS 60개 전부 code == name).
# 그런데 `config/settings.py:COURTS`에는 **다른 규약**의 목록이 남아 있다
# (code="B000210" 같은 WebSquare 코드, 5개, code == name 인 항목 0개).
# 지금은 아무도 import 하지 않아 무해하지만, 누가 그쪽 규약으로 "정리"하면
# 위 매칭이 전부 실패한다. 그래서 **데이터와 대조해** 규약을 못 박는다.
# ---------------------------------------------------------------------------
def test_court_identity_convention():
    print("\n--- 10. 법원 식별자 규약 (코드 <-> 데이터) ---")
    from config.courts import ALL_COURTS

    check_true("ALL_COURTS 가 비어 있지 않다", len(ALL_COURTS) > 0, len(ALL_COURTS))
    mismatched = [c.code for c in ALL_COURTS if c.code != c.name]
    check("ALL_COURTS 는 code == name 규약을 지킨다", mismatched, [])

    codes = {c.code for c in ALL_COURTS}
    conn = connect()
    try:
        for table, col in (("document_queue", "court_code"),
                           ("auction_item", "court_name"),
                           ("auction", "court_code"),
                           ("auction", "court_name"),
                           ("auction_case", "court_code"),
                           ("auction_case", "court_name")):
            vals = {r[0] for r in conn.execute(
                "SELECT DISTINCT %s FROM %s" % (col, table)) if r[0]}
            if not vals:
                continue
            unknown = sorted(vals - codes)
            check("%s.%s 의 모든 값이 ALL_COURTS 에 있다" % (table, col), unknown, [])
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 11. 데이터 신선도 ― 검색 결과가 0이 되기까지 며칠 남았는가 (2026-08-14 신설)
#
# 이 저장소는 이 사고를 **이미 한 번 겪었다.** `run_daily.bat`의 주석이 그대로 적어 두었다:
#
#     Anaconda가 제거되면서 모든 배치가 즉시 실패했고, 실패가 로그에도 남지 않아
#     2026-08-03 ~ 08-11 동안 크롤이 멈춘 사실을 아무도 몰랐다. 그 사이 진행 중
#     물건이 41건까지 줄었다(전부 2026-08-12 만료 -> 그 다음날부터 검색 결과 0건).
#
# 배치 자체는 그때 고쳤다(인터프리터 폴백 + 실패 시 로그). 그런데 **"수집이 멈췄다"를
# 알려 주는 것은 여전히 아무것도 없다.** 배치가 안 돌면 로그도 안 생기므로, 로그를 보는
# 것으로는 알 수 없다 ― 없는 것은 눈에 띄지 않는다.
#
# 그래서 결과 쪽에서 본다. 사용자가 겪는 것은 하나다: **검색에 뜨는 물건이 몇 건인가.**
# 기본 검색은 `auction_date >= 오늘`이므로(D7), 수집이 멈추면 남은 물건이 하루하루
# 만료되다가 어느 날 0이 된다. 그 날짜를 미리 계산해 둔다.
#
# 실패 조건을 좁게 잡은 이유: "오늘 크롤이 안 돌았다"로 실패시키면 주말이나 개발 중에도
# 스위트가 빨개지고, 그건 코드를 고쳐서 풀 수 있는 실패가 아니다 ― 곧 무시하게 된다.
# **제품이 실제로 망가진 상태(검색 0건)만 실패**로 두고, 남은 기간은 크게 출력한다.
# ---------------------------------------------------------------------------
def test_data_freshness_runway():
    print("\n--- 11. 데이터 신선도 (검색 결과가 0이 되기까지) ---")
    conn = connect()
    try:
        today = datetime.date.today()
        rows = conn.execute(
            "SELECT auction_date, COUNT(*) FROM auction_item"
            " WHERE auction_date >= ? AND TRIM(auction_date) <> ''"
            " GROUP BY auction_date ORDER BY auction_date", (today.isoformat(),)).fetchall()
        live = sum(r[1] for r in rows)
        last_crawl = conn.execute("SELECT MAX(crawl_date) FROM auction_item").fetchone()[0]
    finally:
        conn.close()

    print("    마지막 crawl_date : %s" % last_crawl)
    print("    기본 검색에 뜨는 물건: %d건" % live)

    # ★ 제품이 망가진 상태. 이것만 실패로 둔다.
    check_true("기본 검색에 뜰 물건이 남아 있다(0이면 사용자에게 빈 화면)", live > 0,
               "auction_date >= %s 인 물건이 0건이다 ― 수집 파이프라인을 먼저 확인하라"
               % today)

    if not rows:
        return

    last_date = datetime.date.fromisoformat(rows[-1][0])
    runway = (last_date - today).days + 1        # 마지막 기일 다음 날 0이 된다
    print("    마지막 매각기일   : %s" % last_date)
    print("    ★ 수집이 멈춘 채로 두면 %s 부터 검색 결과 0건 (%d일 남음)"
          % (last_date + datetime.timedelta(days=1), runway))

    # 남은 기간이 짧으면 크게 알린다(실패는 아니다 ― 코드로 고칠 수 있는 것이 아니다).
    if runway <= 7:
        print("    " + "!" * 60)
        print("    !! 경고: 수집이 멈춰 있다. %d일 뒤 검색 결과가 0건이 된다." % runway)
        print("    !! 확인 순서: 스케줄러 등록 여부 -> logs/daily_run.log -> run_daily.bat")
        print("    " + "!" * 60)

    # 배치가 최근에 돈 적이 있는지도 함께 보고한다(없는 것은 눈에 띄지 않으므로).
    for name in ("daily_run.log", "doc_run.log"):
        p = os.path.join(ROOT, "logs", name)
        if os.path.exists(p):
            age = (datetime.datetime.now()
                   - datetime.datetime.fromtimestamp(os.path.getmtime(p))).days
            print("    %-16s 마지막 기록 %d일 전" % (name, age))
        else:
            print("    %-16s 없음 (배치가 한 번도 돌지 않았거나 logs가 정리됐다)" % name)

    # 2026-08-17 Sprint 145: 위 경고문이 "확인 순서: **스케줄러 등록 여부** -> ..."라고
    # 안내하면서 정작 그것을 확인해 주지는 않았다. 실측하니 등록 0건이었다 —
    # 249개 예약 작업 중 이 저장소를 가리키는 것이 하나도 없다(이름·경로·실행 인자
    # 전부로 검색). 로그가 5일째 없는 이유가 바로 이것이고, 로그 부재만으로는
    # "배치가 실패했다"와 "배치가 아예 등록되지 않았다"를 구분할 수 없다.
    #
    # 실패로 만들지 않는다 — 등록은 사용자 환경 변경이라 코드로 고칠 수 있는 것이
    # 아니고(Sprint 112가 같은 이유로 SKIP했다), 이 검사 블록의 설계 원칙도
    # "제품이 실제로 망가진 상태만 실패"다. 보고만 한다.
    _report_scheduler_registration()


def _report_scheduler_registration():
    """예약 작업에 이 저장소를 가리키는 항목이 있는지 **보고만** 한다(실패시키지 않는다)."""
    import subprocess
    try:
        out = subprocess.run(
            ["schtasks", "/query", "/fo", "csv"],
            capture_output=True, timeout=60,
        ).stdout.decode("utf-8", "replace")
    except (OSError, subprocess.SubprocessError):
        print("    예약 작업          확인 불가 (schtasks 없음: Windows가 아니거나 권한 없음)")
        return

    hits = [ln for ln in out.splitlines() if "DojoonPass" in ln]
    if hits:
        print("    예약 작업          등록 %d건" % len(hits))
        return
    print("    예약 작업          ★ 등록 0건. run_daily.bat / run_doc_worker.bat가")
    print("                       자동 실행되지 않는다. 이것이 로그가 없는 이유다.")
    print("                       조치: .\\register_scheduler_tasks.ps1 -Apply")
    print("                       (사용자 환경 변경이라 자동으로 하지 않는다: Sprint 112)")


# ---------------------------------------------------------------------------
# 12. 저장된 정규화 결과가 **지금 코드가 만드는 값**과 같은가 (2026-08-14 신설)
#
# `sido`/`sigungu`/`dong`/`lot_number`는 전부 `full_address` 하나에서 계산된 값이다.
# 정규화 규칙이 개선돼도 **이미 저장된 행을 다시 계산하지 않으면** 같은 컬럼에 옛 규칙과
# 새 규칙의 결과가 섞인다. 실제로 그 상태다(2026-08-14 실측, auction_item 1,876행).
#
#     sido       불일치     4행   ← 저장값이 틀렸다(도로명을 시도로 오매칭한 옛 버그의 잔재)
#     sigungu    불일치   207행   ← 저장값이 옛 형식(구가 빠짐)
#     dong        불일치    0행
#     lot_number  불일치    0행
#
# 사용자에게 어떻게 보이는가:
#
#     '경기도 시흥시 서울대학로 59-21' 이 sido='서울'로 저장돼 **서울 필터에 걸린다**
#     sigungu LIKE '안산시 단원구' -> 0행   (안산시 자체는 31행 존재)
#
# 후자가 더 나쁘다. 오류도 빈 화면도 아니고 **그냥 없는 것처럼 보인다.**
#
# ## 왜 "0이어야 한다"가 아니라 "늘지 않았다"인가
#
# 이건 코드 결함이 아니라 **쌓인 데이터**다. 코드는 이미 옳은 값을 낸다(재현 확인).
# 고치려면 백필을 돌려야 하고, 백필 실행은 PM 승인 영역이다
# (`backfill_dong_normalize.py`가 명시한 이 저장소의 관례).
# 그래서 같은 파일 §8(차량 오분류)이 쓰는 방식을 그대로 쓴다 ― **상한을 두어 증가만 막는다.**
# `backfill_region_normalize.py --apply` 를 돌려 0이 되면 아래 상한을 0으로 낮춰라.
#
# 2026-08-15 Sprint 121: sido 상한을 4→5로 올렸다. auction_item이 1,876→2,156행으로
# 늘면서(크롤 계속 진행) 원래 스캔 범위 밖에 있던 옛 행 하나가 새로 걸렸다 - 새로 생긴
# 결함이 아니라 같은 옛 버그의 다섯 번째 사례다.
#
#     id=11903  '경기도 성남시 분당구 구미로173번길 47 ... (구미동,서울시니어스분당타워)'
#               저장 '서울' -> 실제 '경기' (건물명 "서울시니어스분당타워"에 들어간
#               "서울"을 시도로 오매칭 - 도로명이 아니라 건물명이 원인이라는 점만 다르고
#               "문자열 아무 데나 있는 시도명과 매칭" 이라는 근본 원인은 #103-1과 같다)
# ---------------------------------------------------------------------------
NORMALIZE_DRIFT_CEILING = {"sido": 5, "sigungu": 207, "dong": 0, "lot_number": 0}


def test_stored_normalization_matches_code():
    print("\n--- 12. 저장된 정규화 결과 == 지금 코드의 결과 ---")
    from normalizer.normalizer import normalize_address

    conn = connect()
    try:
        rows = conn.execute(
            "SELECT id, full_address, sido, sigungu, dong, lot_number FROM auction_item"
        ).fetchall()
    finally:
        conn.close()
    check_true("검사 대상이 존재한다", len(rows) > 0, len(rows))

    drift = {k: [] for k in NORMALIZE_DRIFT_CEILING}
    crashed = []
    for row_id, addr, sido, sigungu, dong, lot in rows:
        try:
            fresh = normalize_address(addr or "")
        except Exception as exc:  # noqa: BLE001
            crashed.append("id=%s %r" % (row_id, exc))
            continue
        stored = {"sido": sido, "sigungu": sigungu, "dong": dong, "lot_number": lot}
        for col in drift:
            s = (stored[col] or "").strip()
            f = (fresh.get(col) or "").strip()
            # 새 값이 비어 있으면 "규칙이 못 잡는 주소"라 드리프트로 세지 않는다
            # (백필도 그런 행은 건너뛴다 ― 채워진 값을 빈 값으로 덮지 않는다).
            if f and s != f:
                drift[col].append((row_id, s, f))

    # 정규화가 **예외로 죽는** 주소가 있으면 그것부터 문제다(백필도 못 돈다).
    check("정규화 중 예외가 나는 주소 없음", crashed, [])

    for col, ceiling in NORMALIZE_DRIFT_CEILING.items():
        n = len(drift[col])
        detail = drift[col][:3]
        check_true("%s 드리프트가 늘지 않았다 (현재 %d행, 상한 %d)" % (col, n, ceiling),
                   n <= ceiling, detail)
        if n:
            print("      예: " + " / ".join("id=%s %r->%r" % d for d in detail))

    if any(drift[c] for c in drift):
        print("      고치려면: python backfill_region_normalize.py --apply"
              "  (기본은 dry-run)")

    # ── 계산해서 저장한 나머지 두 컬럼 ────────────────────────────────────
    #
    # `bid_rate` / `fail_count`도 같은 부류다 ― 다른 값에서 계산해 저장한다.
    # 계산식이 바뀌면 정규화와 똑같이 조용히 어긋난다. 지금은 **둘 다 완벽하므로**
    # 상한을 0으로 두어 그 상태를 못 박는다(어긋나는 순간 실패한다).
    #
    # 판정은 `migrate_execute.py`의 **실제 함수**에 물어본다. 여기에 공식을 베껴 두면
    # 코드가 바뀌어도 이 검사는 계속 통과한다 ― 그게 바로 드리프트가 생기는 방식이다.
    # (`migrate_execute.py`는 `if __name__ == "__main__"` 가드가 있어 import가 안전하다.)
    from migrate_execute import calc_bid_rate, extract_fail_count

    conn = connect()
    try:
        drows = conn.execute(
            "SELECT id, appraisal_price, minimum_bid_price, bid_rate, status, fail_count"
            " FROM auction_item").fetchall()
    finally:
        conn.close()

    rate_bad, fail_bad, range_bad = [], [], []
    for row_id, appraisal, minimum, rate, status, fail in drows:
        want_rate = calc_bid_rate(appraisal or 0, minimum or 0)
        if abs(float(want_rate) - float(rate or 0)) > 1e-9:
            rate_bad.append((row_id, rate, want_rate))
        want_fail = extract_fail_count(status or "")
        if (fail or 0) != want_fail:
            fail_bad.append((row_id, status, fail, want_fail))
        # 비율이므로 정의상 0~1을 벗어날 수 없다. 벗어나면 계산 자체가 깨진 것이다
        # (화면은 `bid_rate * 100`을 %로 그대로 보여 준다 ― 200% 같은 값이 뜬다).
        if rate is not None and not (0.0 <= float(rate) <= 1.0):
            range_bad.append((row_id, rate))

    check("bid_rate가 지금 공식과 일치한다", rate_bad[:3], [])
    check("fail_count가 status 문자열과 일치한다", fail_bad[:3], [])
    check("bid_rate가 0~1 범위 안이다(비율이므로)", range_bad[:3], [])

    # ── validation_status 는 왜 위 목록에 없는가 (2026-08-14 확인) ──────────
    #
    # 같은 "계산해서 저장한 값"인데 **다시 계산할 수가 없다.** 판정의 주 입력인
    # `appraisal_summary`(감정평가요항표 전문)가 **어느 테이블에도 저장되지 않기
    # 때문이다** — 크롤 중 메모리에만 존재한다(전 테이블 컬럼 전수 확인).
    #
    #     validator/validation_engine.py:74
    #         appraisal_sido = extract_sido(item.appraisal_summary)
    #
    # 그래서 `validation_status`는 **한 번 쓰이고 나면 검증도 재계산도 불가능한 값**이다.
    # `revalidate.py`가 있지만 (1) 하드코딩된 CSV를 읽고 (2) `appraisal_summary=""`로
    # 넘기며 (3) 결과를 DB에 쓰지 않는다 — 재검증 경로가 사실상 없다.
    #
    # 실제 영향: #103-1의 sido 오류로 `address_mismatch` 오탐이 2건 생겼는데,
    # 백필로 sido를 고쳐도 **저장된 FAIL은 그대로 남는다.**
    #
    # 재계산이 불가능하므로 여기서는 **값 자체가 알려진 범위 안인지만** 본다.
    # (`appraisal_summary`를 저장하게 되면 그때 드리프트 검사를 추가할 수 있다.)
    conn = connect()
    try:
        vs = {r[0] for r in conn.execute(
            "SELECT DISTINCT validation_status FROM auction_item") if r[0] is not None}
        reasons_cols = [r[1] for r in conn.execute("PRAGMA table_info(auction_item)")]
    finally:
        conn.close()
    check("validation_status가 알려진 값만 갖는다", sorted(vs - {"PASS", "FAIL"}), [])

    # ── 그런데 **일부는 재판정할 수 있다** (2026-08-14 추가) ────────────────
    #
    # 위에서 "재계산이 불가능하다"고 적었는데, 그것은 **전면 재검증** 이야기다.
    # `address_mismatch` 사유에 한해서는 다르다 ― 그 사유 문자열이 판정의
    # **양쪽 값을 모두 들고 있기** 때문이다.
    #
    #     "address_mismatch: addr=세종 appraisal=제주"
    #                             ^^^^          ^^^^
    #                        주소 쪽 판정    감정요항 쪽 판정
    #
    # 주소는 DB에 남아 있으므로 `addr` 쪽만 지금 함수로 다시 뽑아 `appraisal` 과
    # 비교하면 **그 행이 오늘 규칙으로도 FAIL인지** 알 수 있다. 감정요항 원문이 없어도 된다.
    # 실 DB의 FAIL 12건 중 **11건이 address_mismatch** 이므로 사각지대의 대부분이 덮인다.
    #
    # 2026-08-14 실측: 11건 중 **2건**이 옛 `extract_sido` 버그(BUGS #78)가 만든 오탐이다.
    # 백필로 sido를 고쳐도 저장된 FAIL은 남는다는 위 주석의 그 2건이고,
    # 상세 화면은 그 물건에 **"검증실패"** 를 그대로 띄운다
    # (`src/app/properties/[id]/page.tsx:74` 의 `FAIL: '검증실패'`).
    #
    #     2025타경513824-1  addr=서울 -> 인천   (뉴서울아파트의 "서울")
    #     2016타경3104-1    addr=세종 -> 제주   (세화리의 "세" 매칭)
    #
    # 둘 다 기일이 지나 기본 검색에는 안 나오지만 직접 URL/찜/최근 본 물건으로는 보인다.
    # §12의 나머지와 같은 이유로 **고치지 않고 상한만 둔다** ― 저장값을 바꾸는 것은
    # 백필이고 백필 실행은 승인 영역이다. 여기서 막는 것은 **증가**다:
    # 정규화 규칙을 또 건드려 새 오탐이 생기면 이 검사가 알려준다.
    VALIDATION_FALSE_FAIL_CEILING = 2

    import re as _re
    from validator.validation_engine import is_adjacent as _is_adjacent
    from normalizer.normalizer import extract_sido as _extract_sido

    # ★ `validation_reasons` 는 **레거시 `auction` 테이블에만** 있다(2026-08-14 확인).
    #   `auction_item` 에는 `validation_status` 만 넘어온다 ― 사유는 동기화되지 않는다.
    #   그래서 사유가 필요한 이 검사만 `auction` 을 읽는다.
    #   (두 테이블의 PASS/FAIL 건수는 1864/12로 같다 ― 같은 모집단이다.)
    conn = connect()
    try:
        frows = conn.execute(
            "SELECT case_no, item_no, full_address, validation_reasons"
            " FROM auction WHERE validation_status='FAIL'").fetchall()
    finally:
        conn.close()

    _MISMATCH = _re.compile(r"address_mismatch: addr=(\S+) appraisal=(\S+)")
    would_pass, mismatch_total = [], 0
    for case_no, item_no, addr, reasons in frows:
        m = _MISMATCH.search(reasons or "")
        if not m:
            continue
        mismatch_total += 1
        appraisal = m.group(2)
        # 다른 사유가 함께 있으면 주소를 고쳐도 FAIL은 남는다 ― 오탐으로 세지 않는다.
        extra = [x for x in (reasons or "").split(";")
                 if x.strip() and "address_mismatch" not in x]
        now_addr = _extract_sido(addr or "")
        if not extra and now_addr and (now_addr == appraisal or _is_adjacent(now_addr, appraisal)):
            would_pass.append("%s-%s (%s->%s vs %s)"
                              % (case_no, item_no, m.group(1), now_addr, appraisal))

    print("    FAIL %d행 중 address_mismatch %d행" % (len(frows), mismatch_total))
    check_true("지금 규칙으로는 통과할 FAIL이 늘지 않았다 (현재 %d, 상한 %d)"
               % (len(would_pass), VALIDATION_FALSE_FAIL_CEILING),
               len(would_pass) <= VALIDATION_FALSE_FAIL_CEILING, would_pass[:3])
    for line in would_pass[:3]:
        print("      오탐: " + line)

    # ── 가격: 재계산은 못 하지만 **불변식**은 지킬 수 있다 (2026-08-14) ──────
    #
    # `appraisal_price` / `minimum_bid_price`도 계산해서 저장한 값이다
    # (크롤 원문 문자열 -> `parse_price`). 그런데 **원문이 어디에도 저장되지 않아**
    # 재계산 대조가 불가능하다(전 테이블 컬럼 확인: 가격 원문 컬럼 0개, 타입 INTEGER).
    # `validation_status`와 같은 처지다.
    #
    # 그래서 "지금 값이 옳은가"는 물을 수 없다. 대신 **어떤 경우에도 성립해야 하는 것**만
    # 본다. 아래 둘은 데이터가 어떻게 바뀌어도 참이어야 한다.
    #
    #   * 음수 가격은 존재할 수 없다.
    #   * 최저매각가격이 감정평가액을 넘을 수 없다(경매 구조상). 넘으면 파싱이 두 값을
    #     뒤바꿔 넣었다는 뜻이고, 그러면 `bid_rate`(= 최저/감정)가 1을 넘어 화면에
    #     "120%" 같은 값이 뜬다.
    #
    # ★ "가격이 0인 행 없음"은 **일부러 실패 조건으로 두지 않는다.** 크롤이 "미상"을
    #   만나면 0이 될 수 있고(`upsert_batch`의 `int(... or 0)`), 그건 코드 결함이 아니라
    #   데이터 사정이다. 그것으로 스위트를 빨갛게 만들면 곧 무시하게 된다 — 숫자만 남긴다.
    conn = connect()
    try:
        one = lambda s: conn.execute(s).fetchone()[0]
        neg = one("SELECT COUNT(*) FROM auction_item"
                  " WHERE appraisal_price < 0 OR minimum_bid_price < 0")
        inverted = one("SELECT COUNT(*) FROM auction_item"
                       " WHERE appraisal_price > 0 AND minimum_bid_price > appraisal_price")
        zero_appraisal = one("SELECT COUNT(*) FROM auction_item WHERE appraisal_price = 0")
        zero_minimum = one("SELECT COUNT(*) FROM auction_item WHERE minimum_bid_price = 0")
    finally:
        conn.close()
    check("음수 가격인 행 없음", neg, 0)
    check("최저매각가격이 감정평가액을 넘는 행 없음(파싱 역전)", inverted, 0)
    print("    가격이 0인 행: 감정가 %d / 최저가 %d (실패 조건 아님 ― 참고용)"
          % (zero_appraisal, zero_minimum))

    # ── 크롤러가 쓰는 표와 API가 읽는 표가 같은 값을 들고 있는가 ─────────────
    #
    # `auction`(크롤 원본)과 `auction_item`(API가 읽는 표)은 `migrate_execute.py`가
    # 단방향 복사한다. 어긋나면 **"크롤은 됐는데 화면은 옛 값"**이 된다 ― 이 저장소가
    # 반복해서 잡아 온 "같은 의미를 두 곳이 다르게 들고 있는" 패턴의 원형이다.
    #
    # 값을 계산해 비교하지 않는다(그건 §12 앞부분이 한다). **두 표가 서로 같은가**만 본다.
    #
    # 2026-08-15 Sprint 121: 이 대조에서 sigungu 불일치 1건을 새로 찾았다 - 위 §12와는
    # 다른 결함이다. §12는 "옛 규칙으로 계산된 값이 남아 있다"(값이 존재하되 낡음)인데,
    # 이건 auction_item에 **주소 어디에도 없는 딴 지역 값**이 남아 있는 경우다.
    #
    #     id(auction)=357  대전지방법원 2024타경11191-1
    #     주소: '세종특별자치시 나성로 96 1층104호 (나성동,더센트럴) ...'
    #     auction.sigungu      = ''      (정상 - 세종은 구/군이 없다)
    #     auction_item.sigungu = '칠곡군' (경상북도 소속 - 이 주소 어디에도 없는 값)
    #
    # 원인은 `migrate_execute.py`의 병합 규칙이다:
    #
    #     sigungu = row["sigungu"] or existing["sigungu"]
    #
    # "크롤 값이 빈 문자열이면(파싱 실패로 보고) 기존 값을 지우지 않는다"는 의도인데,
    # **"주소상 원래 없어서 정당하게 비었다"는 경우와 구분하지 못한다.** 세종 주소는
    # 매번 다시 계산해도 sigungu가 영원히 빈 문자열이라, 한 번 다른 지역 값으로
    # 오염되면(court_code 복합키 도입 전 case_no 충돌 - docs/BUGS.md #14 계열로 추정,
    # 실제 유입 경로는 지금 로그로 확인 불가) 이후 아무리 재크롤해도 **절대 자연 치유되지
    # 않는다**. `backfill_region_normalize.py`도 이 케이스는 못 잡는다 - 그 스크립트는
    # 새 값이 비면 일부러 건너뛴다(§12 상단 주석 "새 값이 비어 있으면 ... 드리프트로 세지
    # 않는다"), 좋은 값을 빈 값으로 덮어쓰지 않으려는 안전장치인데 그 안전장치가 여기서는
    # 반대로 나쁜 값을 영구 보존한다.
    #
    # 검색 영향(api/v1/search.py:244-246): `?sigungu=칠곡군` 단독 검색에 sido와
    # 무관하게 LIKE 매칭되므로, 세종 물건이 경북 칠곡군 검색 결과에 섞여 나온다.
    #
    # 고치려면 migrate_execute.py의 병합 규칙 자체를 바꿔야 하는데(파싱 실패로 인한 빈
    # 값과 "원래 없음"으로 인한 빈 값을 구분할 방법이 지금 없다) 이건 핵심 파이프라인
    # 로직 변경이라 이 세션 범위를 벗어난다(승인 필요). 지금은 §12와 같은 방식으로
    # **알려진 1건**만 허용하고 새로 늘면 잡는다.
    SYNC_MISMATCH_CEILING = {"sigungu": 1}
    FIELDS = ["property_type", "sido", "sigungu", "dong", "lot_number", "full_address",
              "appraisal_price", "minimum_bid_price", "auction_date", "status",
              "validation_status", "crawl_date"]
    conn = connect()
    try:
        join = ("FROM auction a JOIN auction_item i"
                " ON i.court_name=a.court_name AND i.case_no=a.case_no"
                " AND IFNULL(i.item_no,'')=IFNULL(a.item_no,'')")
        paired = conn.execute("SELECT COUNT(*) " + join).fetchone()[0]
        mismatched = {}
        for f in FIELDS:
            n = conn.execute(
                "SELECT COUNT(*) %s WHERE IFNULL(TRIM(CAST(a.%s AS TEXT)),'')"
                " <> IFNULL(TRIM(CAST(i.%s AS TEXT)),'')" % (join, f, f)).fetchone()[0]
            if n:
                mismatched[f] = n
        only_a = conn.execute(
            "SELECT COUNT(*) FROM auction a WHERE NOT EXISTS (SELECT 1 FROM auction_item i"
            " WHERE i.court_name=a.court_name AND i.case_no=a.case_no"
            " AND IFNULL(i.item_no,'')=IFNULL(a.item_no,''))").fetchone()[0]
    finally:
        conn.close()
    check_true("두 표를 짝지을 수 있다", paired > 0, paired)
    check("auction 에만 있고 auction_item 에 없는 행 없음(API가 못 보는 크롤 결과)", only_a, 0)
    over_ceiling = {f: n for f, n in mismatched.items()
                    if n > SYNC_MISMATCH_CEILING.get(f, 0)}
    check("두 표의 값이 어긋난 필드가 알려진 상한을 넘지 않음", over_ceiling, {})
    if mismatched:
        print("    어긋난 필드(알려진 상한 포함): %s (상한 %s)"
              % (mismatched, SYNC_MISMATCH_CEILING))
    print("    짝지은 행 %d개 x %d필드 대조" % (paired, len(FIELDS)))
    # 화면이 읽는 표에는 사유가 없다 ― "왜 검증실패인지"를 API로는 알 수 없다는 사실을
    # 여기 고정해 둔다(사유는 레거시 `auction` 테이블에만 있다). 스키마가 바뀌면
    # 이 검사가 먼저 알려 준다.
    check("auction_item에는 validation_reasons가 없다(사유는 레거시 표에만 있다)",
          "validation_reasons" in reasons_cols, False)


# ---------------------------------------------------------------------------
# 13-B. `detect_stale_region_contamination_dryrun.py`가 실제로 오염만 잡고
# 정당한 사례(부분 문자열 오매칭 / 원래 빈 값)는 안 건드리는가 (2026-08-15 Sprint 121)
#
# 이 탐지 스크립트는 --apply가 없어 위 SYNC_MISMATCH_CEILING처럼 회귀를 막아 줄 장치가
# 스스로에게는 없다 ― 판정 기준(§안의 3조건)이 조용히 느슨해지면(오탐 증가) 또는
# 조용히 빡빡해지면(누락 증가) 아무도 모른다. 합성 데이터로 세 조건 각각을 검증하고,
# 실 DB 결과가 위 §13 ceiling과 일치하는지도 대조한다(둘이 따로 관리되므로 어긋날 수 있다).
# ---------------------------------------------------------------------------
def test_stale_region_contamination_detector():
    print("\n--- 13-B. 지역 필드 오염 탐지기 자체 검증 ---")
    import importlib
    detector = importlib.import_module("detect_stale_region_contamination_dryrun")

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, full_address TEXT,"
                 " sido TEXT, sigungu TEXT, dong TEXT, lot_number TEXT)")
    conn.executemany("INSERT INTO t (id, full_address, sido, sigungu, dong, lot_number)"
                      " VALUES (?,?,?,?,?,?)", [
        # (a) 오염: 세종 주소(sigungu 없음)인데 전혀 무관한 지역명이 남아 있다 - 잡아야 한다
        #     (조건1: fresh 비어 있음 / 조건2: stored 있음 / 조건3: 주소에 없음 -- 셋 다 성립)
        (1, "세종특별자치시 나성로 96 1층104호 (나성동,더센트럴)", "세종", "칠곡군", "나성동", "96"),
        # (b) 조건1로 보호: fresh가 채워진다(§12 영역, extract_sido는 문자열 어디든 찾으므로
        #     "뉴서울아파트"의 '서울'도 fresh 계산에 그대로 잡혀 애초에 fresh가 비지 않는다)
        (2, "인천광역시 계양구 새벌로 88 (효성동, 뉴서울아파트)", "서울", "계양구", "효성동", "88"),
        # (c) 조건2로 보호: 원래도 비어 있다(지울 것 자체가 없다)
        (3, "세종특별자치시 나성로 10 (나성동,어울림)", "세종", "", "나성동", "10"),
        # (d) 조건3으로 보호: fresh sigungu는 비지만(정규식이 '강남구청사거리점'을 못
        #     끊는다), stored '강남구'가 주소 문자열 안에 실제로 존재한다 - (a)와 반대로
        #     "정말 없는 값"이 아니라 "정규식이 놓쳤을 뿐 주소 안에 있는 값"이므로
        #     안전 쪽으로 판단해 건드리지 않아야 한다.
        (4, "세종특별자치시 나성로 96 1층104호 (나성동,강남구청사거리점)",
         "세종", "강남구", "나성동", "96"),
    ])
    conn.commit()

    hits = detector.scan_table(conn, "t")
    by_id = {(h[0], h[1]): h[2] for h in hits}
    check_true("합성 오염 사례(id=1, sigungu)를 잡는다", (1, "sigungu") in by_id, hits)
    check_true("조건1(fresh 비었나)로 보호되는 사례(id=2)는 잡지 않는다",
               (2, "sido") not in by_id, hits)
    check_true("조건2(stored 있나)로 보호되는 사례(id=3)는 잡지 않는다",
               (3, "sigungu") not in by_id, hits)
    check_true("조건3(주소 안에 있나)으로 보호되는 사례(id=4)는 잡지 않는다",
               (4, "sigungu") not in by_id, hits)
    check("합성 데이터에서 오탐/누락 없이 정확히 1건만 잡는다", len(hits), 1)
    conn.close()

    # 실 DB 결과가 §13의 알려진 상한과 같은 이야기를 하는지 대조한다.
    live = sqlite3.connect(DB)
    live.row_factory = sqlite3.Row
    try:
        live_hits = detector.scan_table(live, "auction_item")
    finally:
        live.close()
    # 2026-08-17 Sprint 144: `== 1`이었다. 이름과 주석은 "상한(ceiling)"이라고 말하는데
    # 비교만 등호라서, **오염이 실제로 사라지자 테스트가 실패했다**(실측 결과 0건 -
    # 2026-08-14 `backfill_region_normalize.py` 이후로 보인다). 이 파일의 다른 상한
    # 검사(§8 차량 오분류, §12 정규화 드리프트, §13 SYNC_MISMATCH_CEILING)는 전부
    # `<= ceiling`이며, 이 줄만 어긋나 있었다. 좋아진 것을 회귀로 보고하는 검사는
    # 아무도 못 믿게 되므로 같은 규약으로 맞춘다 - 늘어나는 것만 막는다.
    REGION_CONTAMINATION_CEILING = 1
    check_true("실 DB 오염 의심 건수가 §13 상한(sigungu:%d)을 넘지 않는다 (현재 %d건)"
               % (REGION_CONTAMINATION_CEILING, len(live_hits)),
               len(live_hits) <= REGION_CONTAMINATION_CEILING, live_hits)
    if len(live_hits) < REGION_CONTAMINATION_CEILING:
        print("   [정리됨] 오염이 상한보다 줄었다(%d < %d) - 위 상한을 %d으로 낮출 수 있다"
              % (len(live_hits), REGION_CONTAMINATION_CEILING, len(live_hits)))


# ---------------------------------------------------------------------------
# 14. `sido`가 비어 있는 행은 **주소에 시/도가 없어서**인가 (2026-08-14 신설)
#
# §12의 나머지 절반이다. §12는 "저장값이 지금 코드 결과와 다른가"를 보는데,
# **새 값이 비어 있으면 드리프트로 세지 않는다**(백필이 채워진 값을 빈 값으로 덮지 않으므로).
# 그래서 `sido`가 아예 비어 있는 행은 §12의 사각지대에 그대로 남는다.
#
# 왜 중요한가 ― `sido`가 비면 그 물건은 **어떤 시/도 필터에도 걸리지 않는다.**
# 오류도 빈 화면도 아니고 §12가 지적한 것과 같은 모양이다: **그냥 없는 것처럼 보인다.**
# 그리고 시/도 선택은 이 서비스의 가장 흔한 검색 진입점이다.
#
# 구분해야 할 두 가지가 있다.
#
#     (a) 주소에 시/도가 애초에 없다   -> 정상. 채울 방법이 없다.
#     (b) 주소에 시/도가 있는데 못 뽑았다 -> **결함.** 파서가 놓쳤거나 저장이 실패했다.
#
# 2026-08-14 실측(auction_item 1,876행): 비어 있는 행은 **3건**이고 **전부 (a)** 였다.
#
#     자동차  "사용본거지 : 순천시 삼산로 81, ..."     <- 소재지가 아니라 사용본거지
#     기타    "선적항 : 완도군 완도읍 [선박 동력선]"    <- 선박
#     기타    "선적항 : 여수시 삼산면 거문항 [선박]"
#
# 부동산 물건종류(아파트/다세대/전답/임야/상가/…)는 **결측 0건**이다.
#
# 그래서 개수에 상한을 두지 않는다(상한은 임의 정책이다). 대신 **(b)가 0건**임을
# 불변식으로 둔다 ― 판정은 운영 정규화기에 직접 물어본다. 시/도를 뽑을 수 있는데
# 저장값이 비어 있으면 그 순간 실패한다. 스케줄러가 켜져 새 데이터가 들어와도 같다.
#
# ("순천시 -> 전남" 처럼 시군구로 시도를 **추론**하는 것은 새 매핑 테이블이 필요한
#  설계 결정이라 여기서 하지 않는다. 이 저장소의 '추측하지 않는다' 방침과도 맞다.)
# ---------------------------------------------------------------------------
def test_empty_sido_is_explained_by_the_address():
    print("\n--- 14. sido 결측은 주소로 설명되는가 ---")
    from normalizer.normalizer import normalize_address

    conn = connect()
    try:
        rows = conn.execute(
            "SELECT id, property_type, full_address, sido, auction_date FROM auction_item"
        ).fetchall()
    finally:
        conn.close()
    check_true("검사 대상이 존재한다", len(rows) > 0, len(rows))

    recoverable, empty_rows = [], []
    for row_id, ptype, addr, sido, adate in rows:
        if (sido or "").strip():
            continue
        empty_rows.append((row_id, ptype, addr or "", adate))
        fresh = (normalize_address(addr or "").get("sido") or "").strip()
        if fresh:
            # 주소에서 뽑을 수 있는데 저장값이 비어 있다 = (b), 결함이다.
            recoverable.append((row_id, ptype, fresh, (addr or "")[:44]))

    print("    sido 결측 %d행 / 전체 %d행" % (len(empty_rows), len(rows)))
    for row_id, ptype, addr, adate in empty_rows[:5]:
        print("      id=%-6s %-8s 기일=%s  %s" % (row_id, ptype, adate, addr[:48]))

    check("주소에서 시/도를 뽑을 수 있는데 비어 있는 행", recoverable, [])
    if recoverable:
        for row_id, ptype, fresh, addr in recoverable[:5]:
            print("      id=%s %s -> %r 로 뽑히는데 저장값이 비었다: %s"
                  % (row_id, ptype, fresh, addr))
        print("      고치려면: python backfill_region_normalize.py --apply  (기본은 dry-run)")

    # 부동산 물건은 시/도가 반드시 있어야 한다 ― 결측은 자동차/선박처럼 소재지가
    # 아닌 주소(사용본거지/선적항)에만 허용된다. 이 구분이 무너지면 위 (a)/(b) 판정도
    # 의미를 잃는다.
    NON_PROPERTY_PREFIX = ("사용본거지", "선적항")
    realty_missing = [(r[0], r[1], r[2][:44]) for r in empty_rows
                      if not r[2].strip().startswith(NON_PROPERTY_PREFIX)]
    check("소재지 주소인데 시/도가 비어 있는 행", realty_missing, [])
    if realty_missing:
        for row_id, ptype, addr in realty_missing[:5]:
            print("      id=%s %s %s" % (row_id, ptype, addr))


# ---------------------------------------------------------------------------
# 13. 발급 실패로 끝난 등기부 신청이 사용자의 값을 가져갔는가 (2026-08-14 신설)
#
# 등기부 신청은 **값을 소비한다** — 무료 한도 1회이거나 초과 요금(OVERAGE_FEE)이다.
# 그리고 `registry_requests.status` 는 `FAILED` 로 끝날 수 있다(운영자가 사유와 함께 처리).
#
# 그런데 `FAILED` 전이는 **소비된 값을 되돌리지 않는다**(`api/v1/admin.py` 실측):
#
#     UPDATE registry_requests SET status='FAILED', reason=? WHERE id=? AND status=?
#     ...크레딧/결제를 건드리는 코드는 없다
#
# 그리고 무료 횟수 계산은 최종 상태를 보지 않는다:
#
#     get_free_count() = COUNT(registry_usage WHERE is_free=1 AND used_at >= 이번달)
#
# 즉 **시스템이 문서를 못 준 경우에도 그 달의 무료 1회는 쓴 것으로 남는다.**
#
# ## 정책을 여기서 정하지 않는다
#
# 보상 어휘는 이미 있다 — `RegistryCreditReason.REFUND`("환불로 인한 복구").
# 그러나 **그것을 자동으로 발생시키는 코드는 없다.** 운영자가
# `POST /admin/registry-credits` 로 수동 지급해야 한다.
#
# 자동 복구가 옳은지(재시도 여지가 있는 실패도 있다), 수동이 옳은지는 제품 판단이다.
# 그래서 이 검사는 **실패시키지 않는다.** 대신 "값은 갔는데 복구는 없는" 건수를
# 세어서 보여 준다 — 지금 아무도 그것을 볼 방법이 없다는 것이 문제이기 때문이다.
# ---------------------------------------------------------------------------
def test_failed_registry_requests_value_report():
    print("\n--- 13. 발급 실패 신청의 값 소비 (보고 전용) ---")
    conn = connect()
    try:
        one = lambda s, p=(): conn.execute(s, p).fetchone()[0]
        total = one("SELECT COUNT(*) FROM registry_requests")
        failed = one("SELECT COUNT(*) FROM registry_requests WHERE status='FAILED'")
        # 실패했는데 무료 사용 기록이 붙어 있는 건 (usage_id 가 연결돼 있다)
        failed_used_free = one(
            "SELECT COUNT(*) FROM registry_requests r JOIN registry_usage u ON u.id=r.usage_id"
            " WHERE r.status='FAILED' AND u.is_free=1")
        # 실패했는데 결제가 연결돼 있는 건
        failed_paid = one(
            "SELECT COUNT(*) FROM registry_requests WHERE status='FAILED' AND payment_id IS NOT NULL")
        # 그 사용자들에게 REFUND 보상이 기록됐는가
        #
        # ★ 컬럼을 조심해야 한다. `registry_credit_logs` 에는 비슷한 이름이 **둘** 있다.
        #     reason_type  GRANT/DEDUCT/USAGE/REFUND/...  <- enum (이것이 맞다)
        #     reason       "등기부 신청 (item_id=123)"      <- 사람이 읽는 자유 텍스트
        #   처음에 `reason` 으로 썼다가 사본 검증에서 잡았다 — 자유 텍스트에 'REFUND' 가
        #   들어갈 일이 없으니 **보상이 있어도 영원히 0으로 세는** 검사가 될 뻔했다.
        #   (`log_credit_event(conn, user, RegistryCreditReason.X, delta, reason="설명")`
        #    에서 3번째 인자가 reason_type, 키워드 `reason` 이 자유 텍스트다.)
        compensated = one(
            "SELECT COUNT(DISTINCT r.user_id) FROM registry_requests r"
            " JOIN registry_credit_logs l ON l.user_id = r.user_id AND l.reason_type = 'REFUND'"
            " WHERE r.status='FAILED'")
    finally:
        conn.close()

    check_true("등기부 신청 표를 읽을 수 있다", total >= 0, total)
    print("    등기부 신청 총 %d건 / 그중 FAILED %d건" % (total, failed))
    print("    FAILED 인데 무료 1회를 쓴 건 : %d" % failed_used_free)
    print("    FAILED 인데 결제가 연결된 건  : %d" % failed_paid)
    print("    REFUND 보상이 기록된 사용자   : %d" % compensated)

    unrecovered = failed_used_free + failed_paid
    if unrecovered and not compensated:
        print("    " + "!" * 60)
        print("    !! 값이 소비됐는데 복구 기록이 없는 신청 %d건." % unrecovered)
        # 출력 리터럴에는 U+2014(—) 대신 U+2015(―)를 쓴다 (cp949 콘솔 안전).
        print("    !! 자동 복구 경로는 없다 ― 보상하려면")
        print("    !!   POST /api/v1/admin/registry-credits (reason_type=REFUND, SUPER_ADMIN)")
        print("    " + "!" * 60)
    elif failed == 0:
        print("    (FAILED 신청이 없어 확인할 대상이 없다)")


def run():
    # 소스 형태 검사는 DB가 없어도 의미가 있으므로 fresh clone 분기보다 먼저 돌린다.
    test_sqlite_now_is_localtime()

    if not os.path.exists(DB):
        print("[SKIPPED] auction.db 없음 (fresh clone) ― 파이프라인 정합 검사 생략")
        return 1 if failures else 0

    test_path_rule_matches_api()
    test_queue_state_machine_invariants()
    test_done_rows_have_file_and_ready_status()
    test_files_are_reflected_in_queue()
    test_parsing_gap_is_measurable()
    test_no_orphan_rows_in_pipeline_tables()
    test_rights_data_has_evidence()
    test_property_type_matches_content()
    test_court_identity_convention()
    test_data_freshness_runway()
    test_stored_normalization_matches_code()
    test_stale_region_contamination_detector()
    test_empty_sido_is_explained_by_the_address()
    test_failed_registry_requests_value_report()

    print("\n" + "=" * 55)
    if failures:
        print("FAILED (%d): %s" % (len(failures), ", ".join(failures)))
        return 1
    print("ALL TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(run())
