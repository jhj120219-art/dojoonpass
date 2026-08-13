"""
문서 저장 파일시스템 계층(crawler/doc_paths.py, 구 crawler/doc_crawler.py) 순수 로직 회귀 테스트.

Selenium/실제 브라우저는 전혀 쓰지 않는다 ― get_doc_dir()/doc_exists()/원자적 쓰기(os.replace())
패턴만 파일시스템 레벨에서 직접 검증한다. test_docs.py/test_docs2.py(실제 courtauction.go.kr
크롤링)와는 무관하고 별개다.

배경(2026-08-09 Sprint 40, File/DB Consistency Audit): collect_status()가 status.html/
status.json을 목적지 경로에 직접 open().write()하고 있어, 쓰기 도중 프로세스가 강제 종료되면
(전원 차단/OOM kill 등 ― except로 못 잡는 죽음) 잘려나간 파일이 목적지에 남을 수 있었다.
doc_exists()는 status.json의 존재+0바이트초과만으로 "완료"를 판정하므로, 손상됐지만 크기는
0이 아닌 파일이 하나라도 생기면 그 물건은 영구히 재수집 대상에서 빠진다 ― 임시 파일에 먼저
쓰고 os.replace()로 원자적 교체하도록 고쳤다. 이 파일은 그 원자성 자체를 검증한다.

    python test_doc_storage_atomicity.py
"""
import sys
import os
import shutil
import stat
import tempfile
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 경로 규칙은 crawler/doc_paths.py(순수 로직)에 있다. 예전에는 crawler/doc_crawler에서
# 가져왔는데, 그 모듈이 최상단에서 selenium을 import하는 탓에 selenium이 없는 환경에서는
# 이 테스트가 ModuleNotFoundError로 아예 실행되지 못했다(2026-08-10 Sprint 47).
# 검증 대상 함수는 **동일한 그 함수**다 ― 우회가 아니라 불필요한 의존성을 끊은 것이다.
from crawler.doc_paths import (
    get_doc_dir, doc_exists, DOCUMENT_ROOT, status_overlay_has_data,
    canonical_doc_path, CANONICAL_DOC_FILENAME, PDF_DOWNLOADABLE_DOC_TYPES,
)
from storage.database import get_connection, mark_queue_done

failures = []


def check(name, actual, expected):
    ok = actual == expected
    print("[%s] %s: %r (expected %r)" % ("PASS" if ok else "FAIL", name, actual, expected))
    if not ok:
        failures.append(name)


def check_true(name, cond, detail=""):
    ok = bool(cond)
    print("[%s] %s%s" % ("PASS" if ok else "FAIL", name, ("" if ok else " -> " + str(detail))))
    if not ok:
        failures.append(name)


QA_COURT = "qa-atomic-" + uuid.uuid4().hex[:8]
QA_CASE = "2026TEST1234"
QA_ITEM = "1"


def test_get_doc_dir_and_doc_exists():
    print("\n--- 1. get_doc_dir / doc_exists ---")
    path = get_doc_dir(QA_COURT, QA_CASE, QA_ITEM)
    check_true("doc dir created", os.path.isdir(path))
    check_true("doc dir under DOCUMENT_ROOT", path.startswith(DOCUMENT_ROOT))

    check("no spec.pdf yet -> doc_exists False", doc_exists(QA_COURT, QA_CASE, QA_ITEM, "spec"), False)

    spec_path = os.path.join(path, "spec.pdf")
    with open(spec_path, "wb") as f:
        f.write(b"%PDF-1.4 fake content")
    check("non-empty spec.pdf -> doc_exists True", doc_exists(QA_COURT, QA_CASE, QA_ITEM, "spec"), True)

    empty_path = os.path.join(path, "appraisal.pdf")
    open(empty_path, "wb").close()
    check("0-byte appraisal.pdf -> doc_exists False (size guard)",
          doc_exists(QA_COURT, QA_CASE, QA_ITEM, "appraisal"), False)

    # status는 primary 확장자가 json이다(html만 있고 json이 없으면 미완료로 취급) ―
    # crawler/doc_crawler.py:_PRIMARY_EXT 주석과 동일한 근거.
    html_path = os.path.join(path, "status.html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write("<div>fake overlay</div>")
    check("status.html alone -> doc_exists(status) still False (json is the primary marker)",
          doc_exists(QA_COURT, QA_CASE, QA_ITEM, "status"), False)

    json_path = os.path.join(path, "status.json")
    with open(json_path, "w", encoding="utf-8") as f:
        f.write('{"fields": {}}')
    check("status.json present -> doc_exists(status) True",
          doc_exists(QA_COURT, QA_CASE, QA_ITEM, "status"), True)

    # ── doc_type 대소문자 (2026-08-13 Sprint 73) ────────────────────────────
    # 이 저장소는 문서 종류를 **대문자**로 다루는 곳이 더 많다(document_status.doc_type,
    # api/v1/documents.py:DOC_TYPE_FILES, doc_paths.CANONICAL_DOC_FILENAME).
    # 그런데 doc_exists()만 소문자 키를 쓰면서 `.get(doc_type, "pdf")`로 **조용히 기본값**을
    # 썼다. 그래서 DB 값을 그대로 넘기면 종류마다 다르게 틀렸다:
    #
    #   "SPEC"/"APPRAISAL" -> "SPEC.pdf" (Windows는 대소문자 무시라 우연히 정답)
    #   "STATUS"           -> "STATUS.pdf" (status의 기준 파일은 json ― **항상 False**)
    #
    # 2/3이 우연히 맞는 것이 가장 위험하다. 게다가 오답 방향이 "완료됐는데 미완료"라
    # 이미 수집된 문서를 영구히 재수집 대상으로 남긴다.
    #
    # 여기서 고정하는 것: 대소문자에 관계없이 **같은 답**을 내고, 모르는 종류는
    # 그럴듯한 답을 지어내지 않고 예외를 던진다(canonical_doc_path()와 같은 태도).
    for lower, upper in (("spec", "SPEC"), ("status", "STATUS"), ("appraisal", "APPRAISAL")):
        check("doc_exists: %s와 %s가 같은 답" % (lower, upper),
              doc_exists(QA_COURT, QA_CASE, QA_ITEM, upper),
              doc_exists(QA_COURT, QA_CASE, QA_ITEM, lower))
    check("doc_exists(STATUS) 대문자도 True (기준 파일 json을 제대로 본다)",
          doc_exists(QA_COURT, QA_CASE, QA_ITEM, "STATUS"), True)
    check("doc_exists(Status) 혼합 표기도 True",
          doc_exists(QA_COURT, QA_CASE, QA_ITEM, "Status"), True)

    for bad in ("registry", "", None):
        raised = False
        try:
            doc_exists(QA_COURT, QA_CASE, QA_ITEM, bad)
        except ValueError:
            raised = True
        check("doc_exists(%r)는 조용히 답하지 않고 예외" % (bad,), raised, True)

    # 파일명이 항상 소문자로 만들어지는가 ― 대소문자를 구분하는 파일시스템에서도
    # 같은 파일을 가리켜야 한다(Windows에서는 이 검사가 없으면 차이가 드러나지 않는다).
    check("생성 파일명은 소문자다(대소문자 구분 FS 대비)",
          sorted(n for n in os.listdir(path) if n.startswith(("spec", "status", "appraisal"))),
          ["appraisal.pdf", "spec.pdf", "status.html", "status.json"])


def test_atomic_replace_never_leaves_truncated_file():
    """collect_status()가 실제로 쓰는 것과 동일한 패턴(임시 파일 쓰기 -> os.replace())을
    재현해, "쓰기 도중 죽음"을 시뮬레이션해도 목적지 파일이 손상되지 않음을 확인한다.
    """
    print("\n--- 2. atomic write (temp file + os.replace) ---")
    path = get_doc_dir(QA_COURT, QA_CASE, "2")
    json_path = os.path.join(path, "status.json")
    json_tmp = json_path + ".tmp"

    # 1) 최초 정상 저장 ― 실제 collect_status()와 동일한 순서(tmp 쓰기 -> replace)
    with open(json_tmp, "w", encoding="utf-8") as f:
        f.write('{"fields": {"a": "1"}}')
    os.replace(json_tmp, json_path)
    check_true("after first save, tmp file does not linger", not os.path.exists(json_tmp))
    with open(json_path, encoding="utf-8") as f:
        check("destination has full first content", f.read(), '{"fields": {"a": "1"}}')

    # 2) "재수집" 도중 프로세스가 tmp 쓰기 이후, replace 이전에 죽었다고 가정한다 ―
    #    replace()를 아예 호출하지 않고 tmp만 만든 채로 둔다(강제종료를 흉내).
    with open(json_tmp, "w", encoding="utf-8") as f:
        f.write('{"fields": {"a": "2", "b": "3"}}')
    # <- 여기서 프로세스가 죽었다고 가정. os.replace()를 호출하지 않는다.

    with open(json_path, encoding="utf-8") as f:
        content_after_crash = f.read()
    check("destination untouched after simulated crash (still the OLD full content, not truncated/mixed)",
          content_after_crash, '{"fields": {"a": "1"}}')
    check_true("orphaned .tmp file exists but destination was never exposed to a partial write",
               os.path.exists(json_tmp))

    # 3) 다음 실행이 재시도해 정상적으로 replace까지 마치면 새 내용으로 정확히 교체된다
    #    (기존 collect_status()가 매번 새 tmp 경로에 덮어쓰므로 orphan은 자동으로 정리됨).
    os.replace(json_tmp, json_path)
    with open(json_path, encoding="utf-8") as f:
        check("after real retry completes, destination has the NEW full content",
              f.read(), '{"fields": {"a": "2", "b": "3"}}')
    check_true("tmp file gone after replace", not os.path.exists(json_tmp))


def test_mark_queue_done_rolls_back_on_partial_failure():
    """mark_queue_done()은 document_queue.status='done' -> auction.has_*_pdf=1 ->
    (조건부) document_version_log INSERT 3단계를 한 트랜잭션으로 묶고 마지막에만 commit()한다.
    중간 단계에서 예외가 나면 sqlite3의 기본 동작(커밋 안 된 채 close()하면 암묵적 rollback)
    덕분에 앞서 실행된 UPDATE까지 전부 버려져야 한다 ― "파일은 저장됐지만 DB가 절반만
    반영되는" 상태(예: 큐는 done인데 auction.has_status_doc은 그대로 0)가 생기면 안 된다는
    2026-08-10 Sprint 40+ 재현 확인용 회귀 테스트다(doc_worker.py:main()의 최소 재현 구성 ―
    Selenium 없이 storage/database.py만 직접 호출).
    """
    print("\n--- 3. mark_queue_done() partial-failure rollback ---")
    conn = get_connection()
    court_code = "qa-toctou-" + uuid.uuid4().hex[:8]
    case_no = "QA-CASE-1"
    item_no = "1"
    now = __import__("datetime").datetime.now().isoformat()
    qid = conn.execute(
        "INSERT INTO document_queue (court_code,case_no,item_no,doc_type,priority,status,retry_count,enqueued_at)"
        " VALUES (?,?,?,?,?,?,?,?)",
        (court_code, case_no, item_no, "status", 3, "in_progress", 0, now),
    ).lastrowid
    conn.commit()
    conn.close()

    # doc_type을 일부러 잘못 넘겨 col 매핑에서 KeyError를 강제로 유발한다 ― 실제로는
    # 어떤 예외든(DB 잠금 등) 같은 rollback-on-close 경로를 타므로 예외 종류는 상관없다.
    raised = False
    try:
        mark_queue_done(qid, court_code, case_no, item_no, "not_a_real_doc_type", "", "newhash")
    except KeyError:
        raised = True
    check_true("mark_queue_done raised as expected", raised)

    conn = get_connection()
    try:
        row = conn.execute("SELECT status FROM document_queue WHERE id=?", (qid,)).fetchone()
        check("no partial write leaked -- queue still in_progress, not falsely done",
              row["status"], "in_progress")
    finally:
        conn.close()

    # 정상 doc_type으로 재시도하면(doc_worker.py가 실패 후 재시도하는 것과 동일한 시나리오)
    # 완전히 성공해야 한다 ― 부분 상태가 남아 재시도를 방해하지 않는다.
    mark_queue_done(qid, court_code, case_no, item_no, "status", "", "newhash2")
    conn = get_connection()
    try:
        row2 = conn.execute("SELECT status FROM document_queue WHERE id=?", (qid,)).fetchone()
        check("retry after rollback completes cleanly", row2["status"], "done")
    finally:
        conn.execute("DELETE FROM document_queue WHERE id=?", (qid,))
        conn.commit()
        conn.close()


def test_status_overlay_has_data():
    """빈 현황조사서 캡처를 "수집 완료"로 저장하지 않는가 (2026-08-12 Sprint 62 신설).

    `collect_status()`는 오버레이 텍스트가 **비어 있지만 않으면** 저장했다. 그런데
    오버레이 골격에는 "사건번호"/"조사일시"/"검색결과가 없습니다" 같은 **고정 라벨**이
    처음부터 들어 있어 데이터 도착 전에도 그 조건이 참이 됐고, 내용 없는 페이지가
    정상 수집으로 저장됐다(실측: status.html 194건 중 33건).

    그리고 한 번 저장되면 `doc_exists()`가 완료로 판정해 **영구히 재수집에서 빠진다**
    (BUGS #22/#50과 같은 부류). 그래서 "빈 캡처는 저장하지 않는다"가 불변식이다.
    """
    print("\n--- 4. 빈 현황조사서 캡처 판별 (Sprint 62) ---")

    # 실제 빈 캡처 파일에서 확인된 골격 ― 라벨과 안내문은 있지만 사건 데이터가 없다.
    empty_skeleton = (
        '<div id="curstExmndcPopUp"><table>'
        '<tr><th>사건번호</th><td></td><th>조사일시</th><td></td></tr>'
        '<tr><td>번호</td><td>소재지</td><td>임대차관계</td></tr>'
        '<tr><td>검색결과가 없습니다</td></tr></table>'
        '<span>부동산의 현황 및 점유관계 조사서</span></div>'
    )
    filled = empty_skeleton.replace(
        '<th>사건번호</th><td></td>', '<th>사건번호</th><td>2023타경5035 부동산임의경매</td>')

    check("빈 골격은 데이터 없음으로 판정", status_overlay_has_data(empty_skeleton), False)
    check("사건번호가 채워지면 데이터 있음으로 판정", status_overlay_has_data(filled), True)
    check("빈 문자열", status_overlay_has_data(""), False)
    check("None 안전", status_overlay_has_data(None), False)
    # 라벨만으로는 절대 통과하면 안 된다(이것이 원래 버그의 정확한 형태다)
    check("'검색결과가 없습니다'만으로는 통과하지 않는다",
          status_overlay_has_data("사건번호 조사일시 검색결과가 없습니다"), False)
    # 표기 흔들림(공백)도 허용해야 한다 ― 원본 서식이 글자 사이 공백을 넣는 경우가 있다
    check("공백이 섞인 사건번호도 인식", status_overlay_has_data("사건번호 2023 타경 5035"), True)

    # collect_status()가 이 판정을 **저장 전에** 실제로 쓰고 있는지 (배선 확인).
    # 함수만 있고 호출되지 않으면 이 저장소에 반복된 "준비만 되고 배선 안 됨" 패턴이 된다.
    crawler_py = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "crawler", "doc_crawler.py")
    src = open(crawler_py, encoding="utf-8-sig").read()
    body = src[src.index("def collect_status("):src.index("def collect_appraisal(")]
    check("collect_status가 대기 조건에서 데이터 유무를 본다",
          body.count("status_overlay_has_data") >= 2, True)
    save_idx = body.index("html_tmp = html_path")
    guard_idx = body.rindex("status_overlay_has_data", 0, save_idx)
    check_true("저장 직전에 빈 캡처 관문이 있다", guard_idx < save_idx)


def test_collect_documents_saves_where_viewer_serves():
    """`collect_documents.py`가 뷰어가 서빙하는 경로에 저장하는가 (2026-08-12 Sprint 66).

    이 스크립트는 다운로드한 PDF를 `storage/docs/<type>/<원본파일명>`에 둔 채로
    `document_status`를 READY로 바꿨다. 그런데 `api/v1/documents.py`가 서빙하는 경로는
    `documents/<법원>/<사건>/<물건>/spec.pdf`라 **완전히 다른 위치**다.

    지금은 이 스크립트가 한 번도 실행된 적이 없어 무해하지만, `docs/roadmap.md` 16-A가
    **배치 편입을 Backlog로 올려 둔 스크립트**다 ― 스케줄에 넣는 순간 손대는 문서마다
    "화면에는 열람 가능인데 뷰어는 404"가 된다(Sprint 55가 고친 BUGS #50의 재발).
    """
    print("\n--- 5. collect_documents 저장 경로 (Sprint 66) ---")

    # 뷰어가 찾는 파일명과 canonical 정의가 같아야 한다. 두 곳에 정의가 있는 이유는
    # doc_paths가 fastapi 무의존이어야 하기 때문이다 ― 그래서 소스를 대조해 고정한다.
    docs_py = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "api", "v1", "documents.py")
    src = open(docs_py, encoding="utf-8-sig").read()
    import re as _re
    viewer = dict(_re.findall(r'"(SPEC|STATUS|APPRAISAL)":\s*\("([^"]+)"', src))
    check("뷰어 파일명과 canonical 정의가 일치한다", CANONICAL_DOC_FILENAME, viewer)

    # canonical 경로가 실제로 뷰어 루트(documents/) 아래에 만들어지는가
    p = canonical_doc_path("서울중앙지방법원", "2024타경126346", "1", "SPEC")
    check_true("canonical 경로가 documents/ 아래에 있다",
               os.path.commonpath([os.path.abspath(p), os.path.abspath(DOCUMENT_ROOT)])
               == os.path.abspath(DOCUMENT_ROOT), p)
    check("canonical 파일명이 spec.pdf", os.path.basename(p), "spec.pdf")
    check("STATUS는 status.html",
          os.path.basename(canonical_doc_path("A", "B", "1", "STATUS")), "status.html")

    # STATUS는 PDF 다운로드 대상이 아니다 ― 시도하면 매번 FAILED가 찍힌다
    check("PDF 다운로드 대상에 STATUS가 없다", "STATUS" in PDF_DOWNLOADABLE_DOC_TYPES, False)
    check("SPEC/APPRAISAL은 대상이다",
          sorted(PDF_DOWNLOADABLE_DOC_TYPES), ["APPRAISAL", "SPEC"])

    # collect_documents가 실제로 그 규칙을 쓰고 있는지 (배선 확인)
    cd_py = os.path.join(os.path.dirname(os.path.abspath(__file__)), "collect_documents.py")
    cd = open(cd_py, encoding="utf-8-sig").read()
    body = cd[cd.index("def collect_all("):]
    check_true("collect_all이 STATUS를 건너뛴다",
               "PDF_DOWNLOADABLE_DOC_TYPES" in body,
               "STATUS를 그대로 시도하면 매번 FAILED가 기록됩니다")
    check_true("save_doc_raw에 최종 경로를 넘긴다",
               "finalize_download(" in body and "save_doc_raw(conn, item_id, doc_type, final_path)" in body,
               "다운로드 위치를 그대로 기록하면 뷰어가 404입니다")
    # 원자적 이동을 쓰는가(옮기는 도중 강제 종료 시 잘린 파일 방지)
    check_true("finalize_download가 os.replace로 원자적 이동",
               "os.replace(downloaded_path, final_path)" in cd)


def test_finalize_download_moves_file():
    """실제로 파일이 뷰어 경로로 옮겨지는가 (동작 검증)."""
    print("\n--- 6. finalize_download 실동작 (Sprint 66) ---")
    import collect_documents as CD

    tmp_dir = os.path.join(DOCUMENT_ROOT, "..", "storage", "docs", "SPEC")
    os.makedirs(tmp_dir, exist_ok=True)
    src_path = os.path.join(tmp_dir, "qa_sprint66_download.pdf")
    with open(src_path, "wb") as f:
        f.write(b"%PDF-1.4 qa fixture")

    court, case_no, item_no = QA_COURT, QA_CASE, "1"
    try:
        final = CD.finalize_download(src_path, court, case_no, item_no, "SPEC")
        check("최종 경로가 canonical과 같다", final,
              canonical_doc_path(court, case_no, item_no, "SPEC"))
        check_true("파일이 실제로 옮겨졌다", os.path.exists(final))
        check_true("원본 위치에는 남지 않는다", not os.path.exists(src_path))
        check("내용이 보존된다", open(final, "rb").read(), b"%PDF-1.4 qa fixture")
        # 이 경로는 doc_exists()가 "수집 완료"로 인정하는 바로 그 경로여야 한다
        check("doc_exists가 완료로 인정한다", doc_exists(court, case_no, item_no, "spec"), True)
    finally:
        for p in (src_path, canonical_doc_path(court, case_no, item_no, "SPEC")):
            if os.path.exists(p):
                os.remove(p)


def cleanup():
    print("\n--- cleanup (qa test doc dir only) ---")
    root = os.path.join(DOCUMENT_ROOT, QA_COURT)
    if os.path.isdir(root):
        shutil.rmtree(root)
    check_true("qa test doc dir removed", not os.path.isdir(root))

    # ── 이전 실행이 강제 종료돼 남긴 잔해도 쓸어낸다 (2026-08-13 Sprint 96) ──
    #
    # `QA_COURT`는 실행마다 난수라, 이 정리는 **이번 실행 것만** 지운다. 그런데 이 정리는
    # `finally`에 있어도 프로세스가 밖에서 죽으면(변이 실행의 타임아웃 kill 등) 돌지 않는다.
    # 실제로 `documents/`에 qa-atomic-* 두 벌이 남아 있었고, 문서 상태와 디스크를 대조하는
    # 점검에서 "READY가 아닌데 디스크에 있는 문서"로 잡혔다 ― 실 데이터 점검을 오염시킨다.
    #
    # 남의 실행 중인 디렉터리를 지우지 않도록 **이번 것은 건드리지 않는다**(이미 위에서 지웠다).
    # ★ 읽기 전용 속성을 풀고 지운다. 이 저장소는 OneDrive 폴더 안에 있고, OneDrive는
    #   `documents/` 아래 디렉터리에 **R 속성**을 붙인다(정상 법원 디렉터리도 전부 그렇다).
    #   그 상태에서 `shutil.rmtree`는 `PermissionError [WinError 5]`로 실패한다 ―
    #   `ignore_errors=True`는 그 실패를 **조용히 삼켜** 지운 줄 알게 만든다.
    #   갓 만든 디렉터리는 아직 속성이 붙기 전이라 성공하고, 오래 남은 것만 실패한다.
    def _force_rmtree(path):
        def onerror(func, target, _exc):
            try:
                os.chmod(target, stat.S_IWRITE)
                func(target)
            except OSError:
                pass
        shutil.rmtree(path, onerror=onerror)

    stale = []
    if os.path.isdir(DOCUMENT_ROOT):
        for name in os.listdir(DOCUMENT_ROOT):
            if name.startswith("qa-atomic-") and name != QA_COURT:
                path = os.path.join(DOCUMENT_ROOT, name)
                if os.path.isdir(path):
                    _force_rmtree(path)
                    stale.append(name)
    if stale:
        print("   이전 실행 잔해 %d개 정리: %s" % (len(stale), ", ".join(sorted(stale))))
    check_true("qa-atomic-* 잔해가 남지 않았다",
               not [n for n in (os.listdir(DOCUMENT_ROOT) if os.path.isdir(DOCUMENT_ROOT) else [])
                    if n.startswith("qa-atomic-")])


def test_document_hash_functions_agree():
    """문서 변경 감지의 근거인 해시 두 함수가 일치하는가 (2026-08-13 Sprint 85 신설).

    커버리지로 찾은 미검증 경로다 ― `crawler/doc_crawler.py`의 `calc_file_hash()`(파일 경로,
    8KB 청크 루프)와 `_hash_bytes()`(메모리 바이트)가 **둘 다 검사 0건**이었다.

    이 두 값이 `mark_queue_done(previous_hash, new_hash)`으로 들어가고, 다르면
    `document_version_log`에 개정 이력이 남는다(Sprint 78 §8이 그 경로를 고정했다).
    그래서 해시가 틀리는 방식이 곧 두 가지 결함이 된다.

        내용이 달라도 같은 값   -> 개정이 영원히 기록되지 않는다(정정 공고를 놓친다)
        내용이 같은데 다른 값   -> 재수집마다 개정으로 기록돼 진짜 개정을 찾을 수 없다

    특히 `calc_file_hash()`의 청크 루프는 **조용히 잘리는** 형태로 틀릴 수 있다(첫 청크만
    읽고 끝내도 작은 파일에서는 정답이 나온다). 그래서 8KB 경계를 넘는 크기로 검증한다.
    """
    from crawler.doc_crawler import calc_file_hash, _hash_bytes
    import hashlib

    print("\n--- 7. 문서 해시 두 함수의 일치 (Sprint 78) ---")
    # 저장소 루트를 더럽히지 않는다 ― 임시 디렉터리에서만 쓴다.
    tmp = tempfile.mkdtemp(prefix="qa_hash_")
    try:
        # 8KB 청크 경계를 확실히 넘긴다 ― 첫 청크만 읽는 구현을 잡기 위해서다.
        data = (b"PDF-CONTENT-" + uuid.uuid4().bytes) * 2000   # 약 56KB
        path = os.path.join(tmp, "doc.pdf")
        with open(path, "wb") as fh:
            fh.write(data)

        expected = hashlib.sha256(data).hexdigest()
        check("calc_file_hash가 표준 sha256과 일치", calc_file_hash(path), expected)
        check("_hash_bytes가 표준 sha256과 일치", _hash_bytes(data), expected)
        check("두 함수가 같은 내용에 같은 값을 준다(경로/메모리 경로 교차 사용)",
              calc_file_hash(path), _hash_bytes(data))

        # 1바이트만 달라도 값이 달라야 한다 ― 개정 감지의 민감도.
        changed = data[:-1] + bytes([data[-1] ^ 0x01])
        changed_path = os.path.join(tmp, "doc2.pdf")
        with open(changed_path, "wb") as fh:
            fh.write(changed)
        check_true("1바이트 변경도 다른 해시를 만든다",
                   calc_file_hash(path) != calc_file_hash(changed_path))

        # 빈 파일도 예외 없이 표준값을 준다(0바이트 격리 경로가 해시를 먼저 계산할 수 있다).
        empty = os.path.join(tmp, "empty.pdf")
        open(empty, "wb").close()
        check("빈 파일 해시는 sha256('')", calc_file_hash(empty),
              hashlib.sha256(b"").hexdigest())

        # 청크 경계 정확히 걸치는 크기(8192의 배수 +-1)에서도 맞아야 한다.
        for size in (8191, 8192, 8193, 16384):
            blob = b"x" * size
            p2 = os.path.join(tmp, "sz%d.bin" % size)
            with open(p2, "wb") as fh:
                fh.write(blob)
            check("청크 경계 크기 %d 정확" % size, calc_file_hash(p2),
                  hashlib.sha256(blob).hexdigest())
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_wait_for_download_completion_rules():
    """다운로드 완료 판정 규칙 (2026-08-13 Sprint 85 신설).

    `crawler/doc_crawler.py:wait_for_download()`는 브라우저를 쓰지 않는 **파일시스템 폴링**
    함수인데 검사 0건이었다(selenium 의존이 아니므로 여기서 검증할 수 있다).

    이 판정이 틀리는 방식이 곧 두 가지 결함이다.

        너무 이르게 성공     -> 다운로드 중인 파일을 최종 문서로 저장한다(잘린 PDF).
                                doc_exists()는 0바이트만 보므로 그 파일은 "완료"로 굳는다
                                (Sprint 40이 원자적 쓰기로 막은 것과 같은 계열의 사고)
        영원히 실패          -> 정상 다운로드를 놓쳐 매번 재시도하고 큐가 소진된다

    규칙 세 개를 고정한다: (1) `.crdownload`(진행 중)는 후보가 아니다, (2) 0바이트는 아니다,
    (3) **연속 2회 같은 크기**여야 완료다. 시간을 실제로 흘리지 않으려고 `time.sleep`을
    대역으로 바꾸고, 호출 횟수에 따라 파일 상태를 진행시킨다 ― 폴링 루프의 의미를 그대로 검증한다.
    """
    import crawler.doc_crawler as dc

    print("\n--- 8. wait_for_download 완료 판정 (Sprint 85) ---")
    tmp = tempfile.mkdtemp(prefix="qa_dl_")
    saved_dir, saved_sleep = dc.DOWNLOAD_DIR, dc.time.sleep
    try:
        dc.DOWNLOAD_DIR = tmp

        # ── 폴링 횟수에 상한을 씌운다 (2026-08-13 Sprint 96) ──────────────────
        #
        # 아래 검사들은 전부 `time.sleep`을 대역으로 바꿔 **실시간을 쓰지 않는다.** 덕분에
        # 빠르지만, 그 대가로 `while elapsed < timeout:`의 종료 조건이 사라지는 변이가
        # **실패가 아니라 정지**가 된다 ― 실제로 `while True:`로 바꿔 보니 이 파일이 멈춰
        # 하위 프로세스 타임아웃(45초)에 걸릴 때까지 돌았다. 정지는 회귀 스위트 전체를
        # 먹고, 무엇이 깨졌는지 가리키지도 못한다.
        #
        # 그래서 대역을 **하나로 모으고** 총 폴링 횟수를 센다. 아래에서 쓰는 가장 긴
        # timeout이 20이므로 60이면 정상 사용을 절대 막지 않는다.
        class _Overrun(Exception):
            pass

        pump = {"fn": lambda _s: None, "n": 0}

        def bounded_sleep(sec):
            pump["n"] += 1
            if pump["n"] > 60:
                raise _Overrun("폴링 %d회 - 종료 조건이 사라졌다" % pump["n"])
            pump["fn"](sec)

        def set_sleep(fn):
            """이후 폴링에서 실행할 대역을 갈아 끼운다(횟수 카운터는 유지)."""
            pump["fn"] = fn

        dc.time.sleep = bounded_sleep

        # (1) 새 파일이 없으면 타임아웃 후 None. sleep을 무력화해 즉시 끝낸다.
        set_sleep(lambda _s: None)
        check("새 파일이 없으면 None(타임아웃)", dc.wait_for_download(set(), timeout=3), None)

        # (2) 진행 중 파일(.crdownload)만 있으면 후보가 아니다 ― 이르게 성공하면 잘린 PDF를
        #     최종 문서로 저장한다.
        #     주의(변이 테스트로 확인): 이 결과는 `.crdownload` 제외 줄이 아니라 그 다음의
        #     `.pdf` 확장자 필터가 만든다("doc.pdf.crdownload"는 .pdf로 끝나지 않는다).
        #     즉 제외 줄은 현재 **효과가 없는 이중 방어**다 ― 지우면 이 검사는 그대로 통과한다.
        #     그래도 유지할 값이 있다: 나중에 후보 조건이 확장자 대신 mtime 등으로 바뀌면
        #     그 줄이 유일한 방어가 된다. 지우려면 그때 판단할 일이므로 여기서는 사실만 남긴다.
        part = os.path.join(tmp, "doc.pdf.crdownload")
        with open(part, "wb") as fh:
            fh.write(b"partial")
        check(".crdownload만 있으면 None", dc.wait_for_download(set(), timeout=3), None)
        os.remove(part)

        # (2-b) PDF가 아닌 새 파일은 문서가 아니다. 법원 사이트가 PDF 대신 오류 안내
        #       페이지나 안내 텍스트를 내려주는 경우가 이 모양이 된다 ― 그것을 "수집 완료"로
        #       저장하면 doc_exists()가 0바이트만 보므로 그 물건은 영구히 재수집에서 빠진다.
        #       (이 검사가 없으면 `.pdf` 확장자 필터를 지운 변이가 살아남았다.)
        notice = os.path.join(tmp, "notice.html")
        with open(notice, "wb") as fh:
            fh.write(b"<html>error</html>")
        check("PDF가 아닌 새 파일은 None", dc.wait_for_download(set(), timeout=3), None)
        os.remove(notice)

        # (3) 0바이트 PDF는 완료가 아니다.
        empty = os.path.join(tmp, "empty.pdf")
        open(empty, "wb").close()
        check("0바이트 PDF는 None", dc.wait_for_download(set(), timeout=3), None)
        os.remove(empty)

        # (4) **크기가 계속 자라면** 완료로 보지 않는다(연속 2회 동일 조건).
        growing = os.path.join(tmp, "growing.pdf")
        with open(growing, "wb") as fh:
            fh.write(b"a")

        def grow(_s):
            with open(growing, "ab") as fh:
                fh.write(b"a")

        set_sleep(grow)
        check("크기가 계속 자라면 완료로 보지 않는다", dc.wait_for_download(set(), timeout=5), None)

        # (5) 크기가 안정되면 그 경로를 돌려준다. 처음 두 번은 자라고 그 뒤로 멈춘다 ―
        #     "자라다가 멈추는" 실제 다운로드 모양이다.
        calls = {"n": 0}

        def grow_then_stop(_s):
            calls["n"] += 1
            if calls["n"] <= 2:
                with open(growing, "ab") as fh:
                    fh.write(b"b")

        set_sleep(grow_then_stop)
        result = dc.wait_for_download(set(), timeout=10)
        check("안정되면 그 파일 경로를 돌려준다", result, growing)

        # (5-b) "2회"가 정말 필요한지 ― 중간에 **한 번 쉬었다가 다시 자라는** 다운로드.
        #       네트워크가 잠깐 멈추면 실제로 이 모양이 된다. 1회로 만족하면 이 순간에
        #       반환해버리고, 호출자는 아직 절반인 PDF를 최종 문서로 복사한다.
        #       경로만 비교하면 두 경우가 구별되지 않으므로(같은 파일이다) **반환 시점의
        #       크기**를 본다.
        #       크기 대본을 **두 번 쉬는** 모양으로 짠 이유(변이 테스트로 확정): 한 번만
        #       쉬면 "안정 카운터를 리셋하지 않는" 변이가 살아남는다 ― 그 변이는 떨어져 있는
        #       두 번의 일치를 연속으로 착각하므로, 쉼이 두 번 있어야 정답보다 이르게(20바이트)
        #       반환하며 드러난다. "1회면 충분"으로 바꾼 변이는 10바이트에서 반환한다.
        #       정상 코드만 다 받은 40바이트에서 반환한다.
        paused = os.path.join(tmp, "paused.pdf")
        sizes = [10, 10, 20, 20, 30, 40, 40, 40]
        step = {"i": 0}

        def replay_sizes(_s):
            i = step["i"]
            step["i"] += 1
            n = sizes[i] if i < len(sizes) else sizes[-1]
            with open(paused, "wb") as fh:
                fh.write(b"p" * n)

        set_sleep(replay_sizes)
        result = dc.wait_for_download({growing}, timeout=20)
        check("잠깐 멈췄다 다시 자라는 파일도 그 경로를 돌려준다", result, paused)
        check("반환 시점에 이미 끝까지 받아져 있다(연속 2회 규칙이 필요한 이유)",
              os.path.getsize(paused) if result else None, 40)
        os.remove(paused)

        # (6) 이미 있던 파일(before_files)은 새 다운로드가 아니다 ― 직전 회차의 잔재를
        #     이번 문서로 저장하면 **다른 사건의 PDF가 섞인다.**
        set_sleep(lambda _s: None)
        check("before_files에 있던 파일은 후보가 아니다",
              dc.wait_for_download({growing}, timeout=3), None)

        # (7) **timeout이 정말 루프를 끝내는가** (2026-08-13 Sprint 96 추가).
        #
        #     위 (1)~(6)이 전부 통과해도, 루프 종료 조건이 사라진 코드는 여기까지 오지
        #     못하고 (1)에서 이미 멈춘다 ― 그래서 검사는 본문 바깥에서 상한으로 받는다.
        #     이 자리에서는 "정상 코드는 상한에 한참 못 미친다"만 확인한다.
        check_true("정상 코드는 폴링 상한에 닿지 않는다", pump["n"] <= 60, pump["n"])
    except _Overrun as exc:
        # 종료 조건이 사라졌다 ― 예전에는 이 자리에서 **스위트가 멈췄다.**
        check_true("wait_for_download의 폴링이 끝난다", False, exc)
    finally:
        dc.DOWNLOAD_DIR = saved_dir
        dc.time.sleep = saved_sleep
        shutil.rmtree(tmp, ignore_errors=True)


def test_wait_for_download_callers_check_the_result():
    """`wait_for_download()`의 **호출부가 타임아웃(None)을 반드시 확인하는가** ― 구조 검사
    (2026-08-13 Sprint 85 신설).

    함수 자체는 §8이 고정했다. 그런데 이 함수의 계약은 "실패하면 None"이고, 호출부가
    그것을 확인하지 않으면 다음 줄이 `calc_file_hash(None)` / `shutil.move(None, dest)`가
    된다 ― 크롤 도중 예외가 나면서 그 물건은 `success=False`도 아닌 **알 수 없는 상태**로
    끝난다(원인은 스택트레이스 한 줄로만 남는다).

    호출부는 selenium 드라이버를 요구하는 함수 안에 있어 여기서 실행할 수 없다. 그래서
    `test_race_conditions.py`의 구조 검사와 같은 방법을 쓴다 ― 소스를 AST로 읽어
    **모든 호출 지점**이 (1) 결과를 변수에 담고 (2) 바로 다음 문장에서 그 변수의 거짓값을
    확인하며 (3) 그 분기에서 함수를 빠져나가는지 본다. 문자열 검색이 아니라 AST라서
    주석이나 비슷한 이름에 속지 않는다.
    """
    import ast

    print("\n--- 9. wait_for_download 호출부의 None 처리 (Sprint 85) ---")
    src_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "crawler", "doc_crawler.py")
    tree = ast.parse(open(src_path, encoding="utf-8-sig").read())

    def is_target_call(node):
        return (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "wait_for_download")

    call_sites = [n for n in ast.walk(tree) if is_target_call(n)]
    # 호출부가 0개면 아래 검사는 공허하게 참이 된다(함수가 사라졌거나 이름이 바뀐 것이다).
    check_true("호출 지점이 존재한다(검사가 공허하지 않다)", len(call_sites) >= 1, len(call_sites))

    guarded = 0
    problems = []
    for parent in ast.walk(tree):
        body = getattr(parent, "body", None)
        if not isinstance(body, list):
            continue
        for i, stmt in enumerate(body):
            if not (isinstance(stmt, ast.Assign) and is_target_call(stmt.value)):
                continue
            target = stmt.targets[0]
            name = target.id if isinstance(target, ast.Name) else None
            if name is None:
                problems.append("line %d: 결과를 단순 변수에 담지 않는다" % stmt.lineno)
                continue
            nxt = body[i + 1] if i + 1 < len(body) else None
            if not isinstance(nxt, ast.If):
                problems.append("line %d: 다음 문장이 확인 분기가 아니다" % stmt.lineno)
                continue
            checked = any(isinstance(n, ast.Name) and n.id == name for n in ast.walk(nxt.test))
            exits = any(isinstance(n, (ast.Return, ast.Continue, ast.Raise))
                        for n in ast.walk(ast.Module(body=nxt.body, type_ignores=[])))
            if not checked:
                problems.append("line %d: 확인 분기가 %s를 보지 않는다" % (stmt.lineno, name))
            elif not exits:
                problems.append("line %d: 확인만 하고 빠져나가지 않는다" % stmt.lineno)
            else:
                guarded += 1

    check("모든 호출 지점이 None을 확인하고 빠져나간다", problems, [])
    check("확인된 호출 지점 수 == 전체 호출 지점 수", guarded, len(call_sites))


def run():
    try:
        test_get_doc_dir_and_doc_exists()
        test_atomic_replace_never_leaves_truncated_file()
        test_mark_queue_done_rolls_back_on_partial_failure()
        test_status_overlay_has_data()
        test_collect_documents_saves_where_viewer_serves()
        test_finalize_download_moves_file()
        test_document_hash_functions_agree()
        test_wait_for_download_completion_rules()
        test_wait_for_download_callers_check_the_result()
    finally:
        cleanup()

    print("\n" + "=" * 55)
    if failures:
        print("FAILED (%d): %s" % (len(failures), ", ".join(failures)))
        return 1
    print("ALL TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(run())
