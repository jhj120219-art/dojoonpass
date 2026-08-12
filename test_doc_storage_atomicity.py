"""
문서 저장 파일시스템 계층(crawler/doc_paths.py, 구 crawler/doc_crawler.py) 순수 로직 회귀 테스트.

Selenium/실제 브라우저는 전혀 쓰지 않는다 — get_doc_dir()/doc_exists()/원자적 쓰기(os.replace())
패턴만 파일시스템 레벨에서 직접 검증한다. test_docs.py/test_docs2.py(실제 courtauction.go.kr
크롤링)와는 무관하고 별개다.

배경(2026-08-09 Sprint 40, File/DB Consistency Audit): collect_status()가 status.html/
status.json을 목적지 경로에 직접 open().write()하고 있어, 쓰기 도중 프로세스가 강제 종료되면
(전원 차단/OOM kill 등 — except로 못 잡는 죽음) 잘려나간 파일이 목적지에 남을 수 있었다.
doc_exists()는 status.json의 존재+0바이트초과만으로 "완료"를 판정하므로, 손상됐지만 크기는
0이 아닌 파일이 하나라도 생기면 그 물건은 영구히 재수집 대상에서 빠진다 — 임시 파일에 먼저
쓰고 os.replace()로 원자적 교체하도록 고쳤다. 이 파일은 그 원자성 자체를 검증한다.

    python test_doc_storage_atomicity.py
"""
import sys
import os
import shutil
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 경로 규칙은 crawler/doc_paths.py(순수 로직)에 있다. 예전에는 crawler/doc_crawler에서
# 가져왔는데, 그 모듈이 최상단에서 selenium을 import하는 탓에 selenium이 없는 환경에서는
# 이 테스트가 ModuleNotFoundError로 아예 실행되지 못했다(2026-08-10 Sprint 47).
# 검증 대상 함수는 **동일한 그 함수**다 — 우회가 아니라 불필요한 의존성을 끊은 것이다.
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

    # status는 primary 확장자가 json이다(html만 있고 json이 없으면 미완료로 취급) —
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


def test_atomic_replace_never_leaves_truncated_file():
    """collect_status()가 실제로 쓰는 것과 동일한 패턴(임시 파일 쓰기 -> os.replace())을
    재현해, "쓰기 도중 죽음"을 시뮬레이션해도 목적지 파일이 손상되지 않음을 확인한다.
    """
    print("\n--- 2. atomic write (temp file + os.replace) ---")
    path = get_doc_dir(QA_COURT, QA_CASE, "2")
    json_path = os.path.join(path, "status.json")
    json_tmp = json_path + ".tmp"

    # 1) 최초 정상 저장 — 실제 collect_status()와 동일한 순서(tmp 쓰기 -> replace)
    with open(json_tmp, "w", encoding="utf-8") as f:
        f.write('{"fields": {"a": "1"}}')
    os.replace(json_tmp, json_path)
    check_true("after first save, tmp file does not linger", not os.path.exists(json_tmp))
    with open(json_path, encoding="utf-8") as f:
        check("destination has full first content", f.read(), '{"fields": {"a": "1"}}')

    # 2) "재수집" 도중 프로세스가 tmp 쓰기 이후, replace 이전에 죽었다고 가정한다 —
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
    덕분에 앞서 실행된 UPDATE까지 전부 버려져야 한다 — "파일은 저장됐지만 DB가 절반만
    반영되는" 상태(예: 큐는 done인데 auction.has_status_doc은 그대로 0)가 생기면 안 된다는
    2026-08-10 Sprint 40+ 재현 확인용 회귀 테스트다(doc_worker.py:main()의 최소 재현 구성 —
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

    # doc_type을 일부러 잘못 넘겨 col 매핑에서 KeyError를 강제로 유발한다 — 실제로는
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
    # 완전히 성공해야 한다 — 부분 상태가 남아 재시도를 방해하지 않는다.
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

    # 실제 빈 캡처 파일에서 확인된 골격 — 라벨과 안내문은 있지만 사건 데이터가 없다.
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
    # 표기 흔들림(공백)도 허용해야 한다 — 원본 서식이 글자 사이 공백을 넣는 경우가 있다
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
    **배치 편입을 Backlog로 올려 둔 스크립트**다 — 스케줄에 넣는 순간 손대는 문서마다
    "화면에는 열람 가능인데 뷰어는 404"가 된다(Sprint 55가 고친 BUGS #50의 재발).
    """
    print("\n--- 5. collect_documents 저장 경로 (Sprint 66) ---")

    # 뷰어가 찾는 파일명과 canonical 정의가 같아야 한다. 두 곳에 정의가 있는 이유는
    # doc_paths가 fastapi 무의존이어야 하기 때문이다 — 그래서 소스를 대조해 고정한다.
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

    # STATUS는 PDF 다운로드 대상이 아니다 — 시도하면 매번 FAILED가 찍힌다
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


def run():
    try:
        test_get_doc_dir_and_doc_exists()
        test_atomic_replace_never_leaves_truncated_file()
        test_mark_queue_done_rolls_back_on_partial_failure()
        test_status_overlay_has_data()
        test_collect_documents_saves_where_viewer_serves()
        test_finalize_download_moves_file()
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
