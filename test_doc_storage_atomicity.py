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
import hashlib
import os
import json
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

    # ── 조회는 디스크를 건드리지 않는다 (2026-08-14 신설) ────────────────────
    #
    # `doc_exists()`는 **조회**인데 예전에는 `get_doc_dir()`을 불렀고, 그 함수는
    # `os.makedirs()`를 한다. 즉 "이 문서 있어요?"라고 묻기만 해도 디스크에 빈 디렉터리가
    # 생겼다. 실측: 없는 물건 하나를 조회하면 3단계 디렉터리가 생기고, 물어볼 때마다 쌓인다.
    #
    # 그 쓰레기가 실제로 남아 있었다 — `documents/` 아래 **대응 물건이 없는 빈 디렉터리
    # 5개**(`A/B/1` 같은 테스트 흔적 포함)가 그렇게 만들어진 것이다.
    #
    # 여기서 고정하는 것: **조회는 아무것도 만들지 않는다.** 만드는 것은 쓰기 직전에
    # `get_doc_dir()`이 한다(위 첫 줄이 그것을 검사한다 — 둘 다 지켜야 한다).
    import tempfile as _tempfile
    import crawler.doc_paths as _dp

    _probe_root = _tempfile.mkdtemp(prefix="qa_noside_")
    _real_root = _dp.DOCUMENT_ROOT
    _dp.DOCUMENT_ROOT = _probe_root
    try:
        before = sum(len(d) for _, d, _ in os.walk(_probe_root))
        r = _dp.doc_exists("QA조회법원", "2099타경0", "1", "spec")
        after = sum(len(d) for _, d, _ in os.walk(_probe_root))
        check("조회 결과는 False(파일이 없다)", r, False)
        check("doc_exists 는 디렉터리를 만들지 않는다", after, before)

        # 대조군: 쓰기용 헬퍼는 여전히 만들어야 한다(크롤러가 이것에 의존한다).
        made = _dp.get_doc_dir("QA쓰기법원", "2099타경1", "1")
        check_true("get_doc_dir 은 여전히 디렉터리를 만든다", os.path.isdir(made), made)
    finally:
        _dp.DOCUMENT_ROOT = _real_root
        shutil.rmtree(_probe_root, ignore_errors=True)

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
    # 저장 지점을 **함수 이름**으로 찾는다 (2026-08-18 Sprint 189 정정).
    #   예전에는 `html_tmp = html_path` 라는 **구현 세부**를 찾았다. Sprint 189가 그 두 줄을
    #   `_write_text_if_changed()` 헬퍼로 옮기자 이 검사가 ValueError로 죽었다 — 제품 결함이
    #   아니라 검사가 리팩터링에 부러진 것이다. 지키려는 불변식("빈 캡처 관문이 저장보다
    #   앞에 있다")은 그대로 두고, 저장을 가리키는 표지만 덜 부서지는 것으로 바꾼다.
    save_idx = body.index("_write_text_if_changed(html_path")
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
    # ★ `canonical_doc_path()` 는 쓰기 대상 경로라 **디렉터리를 만든다.**
    #   그래서 이 검사를 실 DOCUMENT_ROOT 에 대고 돌리면 저장소의 `documents/` 아래에
    #   쓰레기가 남는다 — 실제로 `documents/A/B/1` 이 이 줄 때문에 생겨 있었다
    #   (2026-08-14 실측: 최상위에 법원이 아닌 `A` 디렉터리가 존재).
    #   경로 규칙만 보는 검사이므로 임시 루트에서 돌린다.
    import tempfile as _tf
    import crawler.doc_paths as _dpm

    _probe = _tf.mkdtemp(prefix="qa_canon_")
    _saved_root = _dpm.DOCUMENT_ROOT
    _dpm.DOCUMENT_ROOT = _probe
    try:
        p = canonical_doc_path("서울중앙지방법원", "2024타경126346", "1", "SPEC")
        check_true("canonical 경로가 DOCUMENT_ROOT 아래에 있다",
                   os.path.commonpath([os.path.abspath(p), os.path.abspath(_probe)])
                   == os.path.abspath(_probe), p)
        check("canonical 파일명이 spec.pdf", os.path.basename(p), "spec.pdf")
        check("STATUS는 status.html",
              os.path.basename(canonical_doc_path("A", "B", "1", "STATUS")), "status.html")
    finally:
        _dpm.DOCUMENT_ROOT = _saved_root
        shutil.rmtree(_probe, ignore_errors=True)

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


def _force_rmtree(path):
    """읽기 전용 속성을 풀어 가며 지운다.

    ★ 2026-08-18 Sprint 189: 이 헬퍼는 원래 아래 "이전 실행 잔해" 정리에만 있었고,
      **이번 실행 자기 디렉터리는 맨 `shutil.rmtree()`로 지우고 있었다.** 그래서
      OneDrive 가 R 속성을 붙일 만큼 시간이 지난 실행은 cleanup 에서 `PermissionError`로
      죽었고 — 테스트 전체가 exit 1 이 되면서 **지우지 못한 디렉터리가 그대로 남아
      다음 실행도 같은 자리에서 죽었다.** 실제로 6벌이 쌓여 있었다(2026-08-18 실측,
      Sprint 189 작업 중 실제로 이 연쇄를 겪었다).

      방어는 이미 있었는데 **두 호출 지점 중 하나만 쓰고 있었다** — 이 저장소가
      #110/#112 에서 배운 것과 같은 모양이라, 여기서도 호출 지점을 하나로 합친다.
    """
    def onerror(func, target, _exc):
        try:
            os.chmod(target, stat.S_IWRITE)
            func(target)
        except OSError:
            pass
    shutil.rmtree(path, onerror=onerror)


def cleanup():
    print("\n--- cleanup (qa test doc dir only) ---")
    root = os.path.join(DOCUMENT_ROOT, QA_COURT)
    if os.path.isdir(root):
        _force_rmtree(root)
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


def test_looks_like_pdf_rejects_non_pdf_bytes():
    """★ Sprint 187 신설. `_looks_like_pdf()` — 확장자가 아니라 내용으로 PDF를 판정한다.

    `wait_for_download()`는 크기 > 0과 두 번 연속 안정된 크기만 본다. 법원 서버가 오류
    페이지(HTML)를 `Content-Type: application/pdf`로 잘못 내려주거나 다운로드가 중간에
    끊기면, 그 파일도 "0바이트 아님 + 안정됨" 조건은 통과한다. 이미지 파이프라인이 선언된
    MIME을 안 믿고 매직 바이트로 판정하는 것(`sniff_image_ext`)과 같은 결함 계열이라,
    문서 쪽에도 같은 방식의 방어를 둔다.
    """
    from crawler.doc_crawler import _looks_like_pdf

    print("\n--- 7b. PDF 매직 바이트 판정 (Sprint 187) ---")
    tmp = tempfile.mkdtemp(prefix="qa_pdfmagic_")
    try:
        real_pdf = os.path.join(tmp, "real.pdf")
        with open(real_pdf, "wb") as f:
            f.write(b"%PDF-1.4\n" + b"x" * 500)
        check_true("실제 PDF는 통과", _looks_like_pdf(real_pdf))

        html_error = os.path.join(tmp, "error.pdf")
        with open(html_error, "wb") as f:
            f.write(b"<html><body>500 Internal Server Error</body></html>")
        check_true("HTML 오류 페이지는 거부", not _looks_like_pdf(html_error))

        empty = os.path.join(tmp, "empty.pdf")
        open(empty, "wb").close()
        check_true("빈 파일은 거부", not _looks_like_pdf(empty))

        truncated = os.path.join(tmp, "truncated.pdf")
        with open(truncated, "wb") as f:
            f.write(b"\x00\x01\x02garbage-no-header")
        check_true("PDF 헤더 없는 바이너리는 거부", not _looks_like_pdf(truncated))

        missing = os.path.join(tmp, "does_not_exist.pdf")
        check_true("존재하지 않는 파일은 거부(예외 없이)", not _looks_like_pdf(missing))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


class _FakeSpecViewerDriver:
    """`collect_spec()`이 요구하는 최소한의 driver 표면만 흉내낸다.

    실제 timing(새 탭 대기 0.5초 폴링)은 그대로 두되, 첫 execute_script 호출(=문서 보기
    버튼 클릭)에서 곧바로 새 창 핸들을 추가해 최악의 경우에도 0.5~1초 안에 대기가 끝나게
    한다 - `NEW_WINDOW_TIMEOUT`(15초) 전부를 태우지 않는다.
    """
    def __init__(self):
        self.current_window_handle = "main"
        self._handles = ["main"]

    @property
    def window_handles(self):
        return list(self._handles)

    def find_element(self, by, value):
        return object()

    def find_elements(self, by, value):
        return [object()]

    def execute_script(self, script, *args):
        if "viewer" not in self._handles:
            self._handles.append("viewer")
        return None

    class _SwitchTo:
        def __init__(self, outer):
            self._outer = outer

        def window(self, handle):
            self._outer.current_window_handle = handle

    @property
    def switch_to(self):
        return self._SwitchTo(self)

    def close(self):
        if self.current_window_handle in self._handles:
            self._handles.remove(self.current_window_handle)


def test_collect_spec_refuses_non_pdf_download():
    """★ Sprint 187. `collect_spec()`이 `wait_for_download()`가 돌려준 파일을 그대로
    믿지 않고, `_looks_like_pdf()`로 다시 확인하는 실제 호출 경로를 고정한다.

    `wait_for_download()`를 몽키패치해 "다운로드가 끝났다"고 보고하되 그 파일은 HTML
    오류 페이지로 만든다 — 이 함수가 실제로 도달 가능한 유일한 실패 모드다(서버가
    `Content-Type: application/pdf`를 잘못 붙이는 경우). 대조군으로 같은 경로에 실제
    PDF를 흘려보내 정상 저장까지 함께 고정한다(반대 상황을 구분하지 못하면 이 검사는
    공허하다).
    """
    import crawler.doc_crawler as doc_crawler_mod
    import crawler.doc_paths as doc_paths_mod

    print("\n--- 7c. collect_spec이 가짜 PDF를 저장하지 않는다 (Sprint 187) ---")
    docs_root = tempfile.mkdtemp(prefix="qa_specfake_docs_")
    download_dir = None
    orig_document_root = doc_paths_mod.DOCUMENT_ROOT
    orig_download_dir = doc_crawler_mod.DOWNLOAD_DIR
    orig_wait = doc_crawler_mod.wait_for_download
    try:
        court, case_no, item_no = "QA법원", "2026타경1", "1"
        doc_paths_mod.DOCUMENT_ROOT = docs_root  # get_doc_dir()이 이 경로 아래에만 쓰게 격리
        dest_path = os.path.join(doc_paths_mod.get_doc_dir(court, case_no, item_no), "spec.pdf")

        download_dir = tempfile.mkdtemp(prefix="qa_specfake_dl_")
        doc_crawler_mod.DOWNLOAD_DIR = download_dir

        # --- 1) 오류 페이지가 .pdf로 떨어진 경우: 저장을 거부해야 한다 ---
        bad_file = os.path.join(download_dir, "bad.pdf")
        with open(bad_file, "wb") as f:
            f.write(b"<html>error</html>")
        doc_crawler_mod.wait_for_download = lambda before, timeout=30: bad_file

        driver = _FakeSpecViewerDriver()
        result = doc_crawler_mod.collect_spec(driver, court, case_no, item_no, "btn-id")

        check("가짜 PDF는 success=False", result["success"], False)
        check_true("가짜 PDF는 목적지에 저장되지 않는다", not os.path.exists(dest_path))
        check_true("가짜 PDF는 다운로드 폴더에서도 치워진다", not os.path.exists(bad_file))

        # --- 2) 대조군: 진짜 PDF는 정상 저장된다 ---
        good_file = os.path.join(download_dir, "good.pdf")
        with open(good_file, "wb") as f:
            f.write(b"%PDF-1.4\n" + b"y" * 300)
        doc_crawler_mod.wait_for_download = lambda before, timeout=30: good_file

        driver2 = _FakeSpecViewerDriver()
        result2 = doc_crawler_mod.collect_spec(driver2, court, case_no, item_no, "btn-id")

        check("진짜 PDF는 success=True", result2["success"], True)
        check_true("진짜 PDF는 목적지에 저장된다", os.path.isfile(dest_path))
        check("저장된 내용이 실제 다운로드 내용과 일치",
              open(dest_path, "rb").read(), b"%PDF-1.4\n" + b"y" * 300)
    finally:
        doc_crawler_mod.wait_for_download = orig_wait
        doc_crawler_mod.DOWNLOAD_DIR = orig_download_dir
        doc_paths_mod.DOCUMENT_ROOT = orig_document_root
        shutil.rmtree(docs_root, ignore_errors=True)
        if download_dir:
            shutil.rmtree(download_dir, ignore_errors=True)


def test_overwrite_of_existing_pdf_is_atomic():
    """재수집으로 **기존 PDF를 덮어쓸 때**도 원자적이어야 한다 (2026-08-18 Sprint 189, BUGS #121).

    ## 왜 이 검사가 생겼나

    여기는 원래 `shutil.move(downloaded_path, dest_path)`였다. 목적지가 없을 때는
    `os.rename()` 한 번이라 원자적이다. 문제는 **목적지가 이미 있을 때**다 —
    Windows의 `os.rename()`은 기존 파일이 있으면 `FileExistsError`를 내고,
    `shutil.move()`는 그 예외를 잡아 조용히 `copy2()` 폴백으로 넘어간다.
    실측(2026-08-18, Python 3.12.10):

        목적지 없음 -> RENAME (원자적)
        목적지 있음 -> COPY   (비원자적)   <- **재수집이 항상 여기로 온다**

    비원자적 복사 도중 프로세스가 죽으면 잘린 PDF가 목적지에 남는다. 그리고
    `doc_exists()`는 "존재 + 크기 0 초과"만 보므로 그 잘린 파일을 **완성된 문서로
    취급**해, 다음 수집이 "이미 있다"고 건너뛴다 — 깨진 문서가 영구히 남는다.
    Sprint 189가 재수집을 켠 순간 실제로 도달하는 경로가 됐다.

    같은 일을 하는 `collect_documents.py:249`는 이미 `os.replace()`를 쓰고 있었다.
    **두 수집기만 빠져 있었다.**
    """
    import crawler.doc_crawler as dc

    print("\n--- 7d. 기존 PDF 덮어쓰기가 원자적이다 (Sprint 189, BUGS #121) ---")
    tmp = tempfile.mkdtemp(prefix="qa_atomic_overwrite_")
    try:
        dest = os.path.join(tmp, "spec.pdf")
        old_bytes = b"%PDF-1.4-old"
        new_bytes = b"%PDF-1.7-new"
        with open(dest, "wb") as f:
            f.write(old_bytes)

        # (1) 목적지가 이미 있어도 내용이 정확히 교체된다.
        src = os.path.join(tmp, "download.pdf")
        with open(src, "wb") as f:
            f.write(new_bytes)
        dc.move_into_place(src, dest)
        check("덮어쓰기 후 새 내용", open(dest, "rb").read(), new_bytes)
        check_true("원본(다운로드분)은 남지 않는다", not os.path.exists(src))
        check_true("임시 파일도 남지 않는다", not os.path.exists(dest + ".tmp"))

        # (2) 교체 **직전**에 죽어도 목적지는 옛 파일 그대로다(반쪽 파일이 아니다).
        #     os.replace()를 터뜨려 "복사는 끝났지만 교체 전에 죽은" 순간을 만든다.
        src2 = os.path.join(tmp, "download2.pdf")
        with open(src2, "wb") as f:
            f.write(b"%PDF-9.9-crash")

        calls = {"n": 0}
        orig_replace = dc.os.replace

        def boom(a, b):
            calls["n"] += 1
            if calls["n"] >= 2:          # 1회차는 다운로드분 -> .tmp 이동
                raise OSError("qa-simulated-crash-before-swap")
            return orig_replace(a, b)

        dc.os.replace = boom
        try:
            raised = False
            try:
                dc.move_into_place(src2, dest)
            except OSError:
                raised = True
        finally:
            dc.os.replace = orig_replace

        check_true("교체 실패는 호출자에게 알린다(조용한 성공 금지)", raised)
        check("교체 전에 죽으면 목적지는 이전 파일 그대로", open(dest, "rb").read(), new_bytes)
        check_true("실패해도 .tmp 잔재를 남기지 않는다", not os.path.exists(dest + ".tmp"))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_no_collector_uses_non_atomic_move():
    """같은 계열이 다른 곳에 없는지 **전수 검색**한다 (2026-08-18 Sprint 189).

    인스턴스만 고치면 반드시 다음이 남는다 — 이 저장소가 #110/#112에서 배운 것이다.
    목적지에 직접 쓰는 이동(`shutil.move`/`shutil.copy*`)이 수집 계층에 남아 있으면
    여기서 걸린다.
    """
    print("\n--- 7e. 수집 계층에 비원자적 이동이 남아 있지 않다 (Sprint 189) ---")
    root = os.path.dirname(os.path.abspath(__file__))
    targets = []
    for rel in ("crawler", "storage"):
        base = os.path.join(root, rel)
        for dp, dn, fn in os.walk(base):
            dn[:] = [d for d in dn if d != "__pycache__"]
            targets.extend(os.path.join(dp, f) for f in fn if f.endswith(".py"))
    targets.append(os.path.join(root, "collect_documents.py"))

    # ★ 텍스트 grep 이 아니라 AST 로 본다. 이 파일과 `doc_crawler.py` 자신이 결함을
    #   **설명하는 문장**에 `shutil.move(...)` 를 그대로 적고 있어서, 문자열 검색은
    #   산문을 코드로 오판한다(실제로 처음 작성했을 때 그렇게 걸렸다).
    import ast as _ast

    BANNED = {"move", "copy2", "copyfile", "copy"}
    offenders = []
    unparsed = []      # 못 읽은/못 판 파일 — **조용히 넘기지 않는다**
    for path in sorted(targets):
        # ★ `utf-8-sig` 여야 한다 (2026-08-18 Sprint 195, BUGS #133).
        #   BOM 이 있는 소스를 `utf-8` 로 읽으면 `\ufeff` 가 남아 `ast.parse` 가 거부하고,
        #   `except SyntaxError: continue` 가 그 파일을 감사에서 통째로 지운다.
        #   실측: 이 스캔 범위에서 `storage/database.py`, `crawler/image_crawler.py` 등
        #   16개가 빠져 있었다 — 전수 가드가 전수가 아니었다.
        try:
            with open(path, encoding="utf-8-sig") as fh:
                tree = _ast.parse(fh.read())
        except (OSError, UnicodeDecodeError, SyntaxError) as exc:
            unparsed.append("%s (%s)" % (
                os.path.relpath(path, root).replace(os.sep, "/"),
                type(exc).__name__))
            continue
        rel = os.path.relpath(path, root).replace(os.sep, "/")
        for node in _ast.walk(tree):
            if not isinstance(node, _ast.Call):
                continue
            fn = node.func
            if not (isinstance(fn, _ast.Attribute) and fn.attr in BANNED
                    and isinstance(fn.value, _ast.Name) and fn.value.id == "shutil"):
                continue
            # 목적지 옆 임시 이름으로 복사한 뒤 `os.replace()` 로 바꾸는 것은 정상 경로다
            # (`move_into_place()` 의 볼륨 간 폴백). 두 번째 인자가 tmp 변수인지로 가린다.
            dest_arg = node.args[1] if len(node.args) > 1 else None
            if isinstance(dest_arg, _ast.Name) and "tmp" in dest_arg.id.lower():
                continue
            offenders.append("%s:%d" % (rel, node.lineno))

    # ★ 못 본 파일이 있으면 "없다"는 결론이 성립하지 않는다.
    check("스캔 범위의 모든 파일을 실제로 읽고 팠다", unparsed, [])
    check("수집/저장 계층에 목적지 직접 쓰기가 없다", offenders, [])
    check_true("검색 대상 파일을 실제로 찾았다", len(targets) >= 8, len(targets))


def test_status_hash_ignores_our_own_timestamp():
    """현황조사서 지문이 **우리가 찍은 수집 시각**에 흔들리지 않는가 (Sprint 189, BUGS #124).

    ## 왜 이 검사가 생겼나

    `status.json` 에는 `extracted_at`(수집 시각)이 들어 있다. 예전에는 변경 감지 지문을
    그 파일 **전체**에서 떴다(`calc_file_hash(json_path)`). 그러면 법원 자료가 하나도
    안 바뀌어도 지문이 매번 달라진다.

    재수집을 켜기 전에는 이 경로에 두 번 오지 않아 드러나지 않았다. 켜는 순간:

        document_version_log   매 수집마다 1행 (전부 거짓 개정)
        doc_raw.doc_version    매 수집마다 +1  (BUGS #115 가 막으려던 바로 그것,
                               `api/v1/item.py` 가 사용자 응답에 그대로 싣는다)

    이 저장소는 원인을 이미 알고 있었다 — Sprint 145 의 형제 재사용 주석이
    "차이는 우리가 찍는 extracted_at 하나뿐"이라고 실측해 적어 두었다.
    그 관찰이 변경 감지 쪽으로 연결되지 않았을 뿐이다.
    """
    import crawler.doc_crawler as dc

    print("\n--- 7f. 현황조사서 지문이 수집 시각에 흔들리지 않는다 (Sprint 189, BUGS #124) ---")
    tmp = tempfile.mkdtemp(prefix="qa_status_hash_")
    try:
        fields = {"b_id": "값2", "a_id": "값1"}
        jp = os.path.join(tmp, "status.json")

        def write(payload):
            with open(jp, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)

        write({"extracted_at": "2026-08-18T01:00:00", "fields": fields})
        h1 = dc.status_content_hash(jp)

        # 같은 내용, **다른 수집 시각** -> 지문이 같아야 한다
        write({"extracted_at": "2026-08-19T09:99:99", "fields": fields})
        h2 = dc.status_content_hash(jp)
        check("수집 시각이 달라도 지문은 같다", h2, h1)

        # 키 순서만 다른 같은 내용 -> 지문이 같아야 한다(표현의 차이가 내용의 차이로 둔갑 금지)
        write({"extracted_at": "2026-08-18T01:00:00",
               "fields": {"a_id": "값1", "b_id": "값2"}})
        check("키 순서가 달라도 지문은 같다", dc.status_content_hash(jp), h1)

        # 실제 내용이 바뀌면 지문이 달라야 한다(대조군 — 없으면 이 검사는 공허하다)
        write({"extracted_at": "2026-08-18T01:00:00",
               "fields": {"a_id": "값1", "b_id": "바뀐값"}})
        check_true("내용이 바뀌면 지문이 달라진다",
                   dc.status_content_hash(jp) != h1)

        # 디스크 쪽 공식과 수집 쪽 공식이 같아야 한다 (이미지 BUGS #113/#120 과 같은 책임)
        check("디스크 공식 == 수집 공식", dc.status_content_hash(jp),
              dc._fields_hash({"a_id": "값1", "b_id": "바뀐값"}))

        # 파일이 없거나 깨졌으면 "판단할 수 없다"는 뜻의 빈 문자열
        os.remove(jp)
        check("파일이 없으면 빈 지문", dc.status_content_hash(jp), "")
        with open(jp, "w", encoding="utf-8") as f:
            f.write("{ not json")
        check("깨진 JSON도 빈 지문", dc.status_content_hash(jp), "")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_unchanged_content_preserves_browser_cache():
    """내용이 그대로면 **파일을 다시 쓰지 않는다** (2026-08-18 Sprint 189).

    같은 내용을 다시 써도 mtime 이 바뀌고, 서빙 쪽 ETag 는 Starlette 가 (mtime, size) 로
    만들기 때문에 **모든 브라우저 캐시가 무의미하게 무효화된다**
    (`api/http_cache.py` 가 조건부 요청으로 아끼려던 바로 그 바이트다).
    재수집 대상은 정의상 "사용자가 지금 보고 있는" 물건이라 체감이 크다.

    대조군을 함께 고정한다 — 내용이 **바뀌면** 반드시 쓴다. 구분하지 못하면 공허하다.
    """
    import crawler.doc_crawler as dc

    print("\n--- 7g. 내용 무변경이면 파일을 다시 쓰지 않는다 (Sprint 189) ---")
    tmp = tempfile.mkdtemp(prefix="qa_cache_preserve_")
    try:
        path = os.path.join(tmp, "status.html")
        with open(path, "w", encoding="utf-8") as f:
            f.write("<div>같은 내용</div>")
        before = os.stat(path).st_mtime_ns

        check("같은 내용이면 쓰지 않는다",
              dc._write_text_if_changed(path, "<div>같은 내용</div>"), False)
        check("mtime 이 그대로다(ETag 보존)", os.stat(path).st_mtime_ns, before)

        check("다른 내용이면 쓴다",
              dc._write_text_if_changed(path, "<div>바뀐 내용</div>"), True)
        check("내용이 실제로 교체된다",
              open(path, encoding="utf-8").read(), "<div>바뀐 내용</div>")
        check_true("임시 파일을 남기지 않는다", not os.path.exists(path + ".tmp"))

        # 파일이 없으면 새로 쓴다
        fresh = os.path.join(tmp, "new.html")
        check("없던 파일은 쓴다", dc._write_text_if_changed(fresh, "x"), True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_identical_pdf_is_not_replaced():
    """같은 PDF 를 다시 받았을 때 목적지를 건드리지 않는가 (2026-08-18 Sprint 189).

    감정평가서 실측 3.4MB 다. 내용이 그대로인데 mtime 을 바꾸면 사용자가 그 3.4MB 를
    이유 없이 다시 내려받는다. 대조군(내용이 바뀌면 교체)을 함께 고정한다.
    """
    import crawler.doc_crawler as dc
    import crawler.doc_paths as dp

    print("\n--- 7h. 같은 PDF 는 목적지를 건드리지 않는다 (Sprint 189) ---")
    docs_root = tempfile.mkdtemp(prefix="qa_samepdf_docs_")
    download_dir = tempfile.mkdtemp(prefix="qa_samepdf_dl_")
    orig_root, orig_dl, orig_wait = dp.DOCUMENT_ROOT, dc.DOWNLOAD_DIR, dc.wait_for_download
    try:
        dp.DOCUMENT_ROOT = docs_root
        dc.DOWNLOAD_DIR = download_dir
        court, case_no, item_no = "QA법원", "2026타경2", "1"
        dest = os.path.join(dp.get_doc_dir(court, case_no, item_no), "spec.pdf")

        same = b"%PDF-1.4-same" + b"S" * 300
        with open(dest, "wb") as f:
            f.write(same)
        before = os.stat(dest).st_mtime_ns

        # 1) 법원이 **같은** 문서를 다시 준다 -> 목적지를 건드리지 않는다
        dl = os.path.join(download_dir, "again.pdf")
        with open(dl, "wb") as f:
            f.write(same)
        dc.wait_for_download = lambda before_files, timeout=30: dl

        r = dc.collect_spec(_FakeSpecViewerDriver(), court, case_no, item_no, "btn",
                            overwrite=True)
        check("무변경도 성공이다", r["success"], True)
        check("지문이 같다(개정 아님)", r["previous_hash"], r["new_hash"])
        check("mtime 이 그대로다(ETag 보존)", os.stat(dest).st_mtime_ns, before)
        check_true("다운로드분은 치운다", not os.path.exists(dl))

        # 2) 대조군 — 법원이 **바꾼** 문서를 준다 -> 교체된다
        changed = b"%PDF-1.7-changed" + b"C" * 400
        dl2 = os.path.join(download_dir, "changed.pdf")
        with open(dl2, "wb") as f:
            f.write(changed)
        dc.wait_for_download = lambda before_files, timeout=30: dl2

        r2 = dc.collect_spec(_FakeSpecViewerDriver(), court, case_no, item_no, "btn",
                             overwrite=True)
        check("변경은 성공", r2["success"], True)
        check_true("지문이 다르다(개정)", r2["previous_hash"] != r2["new_hash"])
        check("파일이 실제로 교체된다", open(dest, "rb").read(), changed)
    finally:
        dc.wait_for_download = orig_wait
        dc.DOWNLOAD_DIR = orig_dl
        dp.DOCUMENT_ROOT = orig_root
        shutil.rmtree(docs_root, ignore_errors=True)
        shutil.rmtree(download_dir, ignore_errors=True)


def test_completeness_matches_what_the_viewer_serves():
    """★ 구조적 가드: **"수집 완료" 기준**과 **뷰어가 서빙하는 파일**이 갈라지지 않는다.

    ## 왜 이 검사가 생겼나 (2026-08-18 Sprint 191, BUGS #129)

    완료 판정(`doc_exists`)은 `status.json` 하나만 봤는데, 뷰어가 내려 주는 것은
    `status.html` 이었다(`api/v1/documents.py:DOC_TYPE_FILES`). **두 정의가 서로 다른
    파일을 가리키고 있었다.**

        status.json 만 남은 상태 -> doc_exists()=True  (영원히 재수집 대상에서 제외)
                                 -> 뷰어는 404
                                 = "화면은 READY 인데 열면 없다"

    BUGS #22/#50/#61/#64 와 같은 계열이고, 이번에는 **정의가 두 벌**인 형태였다.
    실측(2026-08-18): 실데이터 json-only 0건 / html+json 163건 — 지금 터지는 버그는
    아니었지만, 두 벌인 상태 자체가 결함이다.

    이 검사는 목록을 손으로 맞추지 않는다 — **서빙 표에서 파일명을 읽어** 완료 기준에
    들어 있는지 확인한다. 새 문서 종류가 생겨도 저절로 따라간다.
    """
    from crawler.doc_paths import DOC_REQUIRED_FILES, doc_exists, get_doc_dir
    import crawler.doc_paths as dp_mod
    from api.v1.documents import DOC_TYPE_FILES

    print("\n--- 7i. 완료 기준 == 뷰어 서빙 대상 (Sprint 191, BUGS #129) ---")

    # (1) 구조: 뷰어가 서빙하는 파일은 반드시 완료 기준 안에 있어야 한다
    mismatched = []
    for doc_type, (filename, _mime) in sorted(DOC_TYPE_FILES.items()):
        required = DOC_REQUIRED_FILES.get(doc_type.lower())
        if not required or filename not in required:
            mismatched.append((doc_type, filename, required))
    check("서빙 파일이 전부 완료 기준에 포함된다", mismatched, [])
    check_true("검사 대상 문서 종류를 실제로 찾았다", len(DOC_TYPE_FILES) >= 3,
               sorted(DOC_TYPE_FILES))

    # 반대 방향도 본다 — 완료 기준의 종류가 서빙 표에 전부 있는가
    missing_serve = sorted(set(DOC_REQUIRED_FILES) - {k.lower() for k in DOC_TYPE_FILES})
    check("완료 기준의 모든 종류를 서빙한다", missing_serve, [])

    # (2) 동작: status 는 두 파일이 다 있어야 완료다
    docs_root = tempfile.mkdtemp(prefix="qa_reqfiles_")
    orig = dp_mod.DOCUMENT_ROOT
    try:
        dp_mod.DOCUMENT_ROOT = docs_root
        court, case_no, item_no = "QA법원", "2026타경9", "1"
        d = get_doc_dir(court, case_no, item_no)
        html = os.path.join(d, "status.html")
        js = os.path.join(d, "status.json")

        check("아무것도 없으면 미완료", doc_exists(court, case_no, item_no, "status"), False)

        with open(js, "w", encoding="utf-8") as f:
            f.write('{"fields": {"a": "1"}}')
        # ★ 이것이 이번에 고친 자리다 — 예전에는 여기서 True 였다(뷰어는 404인데).
        check("json 만 있으면 미완료(뷰어가 서빙할 것이 없다)",
              doc_exists(court, case_no, item_no, "status"), False)

        with open(html, "w", encoding="utf-8") as f:
            f.write("<div>2023타경5035</div>")
        check("둘 다 있어야 완료", doc_exists(court, case_no, item_no, "status"), True)

        os.remove(js)
        check("json 이 사라지면 다시 미완료",
              doc_exists(court, case_no, item_no, "status"), False)

        # 대조군 — 파일 하나짜리 종류는 그 하나로 판정한다
        with open(os.path.join(d, "spec.pdf"), "wb") as f:
            f.write(b"%PDF-1.4 x")
        check("spec 은 파일 하나로 완료", doc_exists(court, case_no, item_no, "spec"), True)
        check("appraisal 은 아직 미완료",
              doc_exists(court, case_no, item_no, "appraisal"), False)
    finally:
        dp_mod.DOCUMENT_ROOT = orig
        shutil.rmtree(docs_root, ignore_errors=True)


class _FakeNoTabDriver:
    """PDF 를 **탭 없이 곧바로 내려받는** 브라우저. BUGS #135 의 실제 조건이다.

    `plugins.always_open_pdf_externally: True` 인 Chrome 은 PDF 를 렌더링하지 않고
    다운로드한다. `window.open()` 으로 연 탭은 그릴 것이 없어 **뜨지도 않는다.**
    즉 다운로드가 성공할수록 탭은 안 생긴다.
    """

    def __init__(self):
        self.current_window_handle = "main"
        self._handles = ["main"]

    @property
    def window_handles(self):
        return list(self._handles)

    class _El:
        """iframe 대역. `collect_appraisal` 은 src 에서 PDF 주소를 뽑는다."""

        def __init__(self, src=""):
            self._src = src

        def get_attribute(self, name):
            return self._src if name == "src" else ""

    def find_element(self, by, value):
        return self._El()

    def find_elements(self, by, value):
        # 안쪽 iframe 의 src 가 PDF 를 가리켜야 pdf_url 이 만들어진다.
        return [self._El("/viewer/HR2025-0609-0001.pdf")]

    def execute_script(self, script, *args):
        return None          # 탭을 만들지 않는다 (핵심)

    class _SwitchTo:
        def __init__(self, outer):
            self._outer = outer

        def window(self, handle):
            self._outer.current_window_handle = handle

        def default_content(self):
            # 실제 collect_appraisal 이 부른다 - 대역이 실물보다 좁으면 TypeError/
            # AttributeError 가 "수집 실패"로 삼켜진다(Sprint 189 에 같은 일을 겪었다).
            return None

        def frame(self, *a, **kw):
            return None

    @property
    def switch_to(self):
        return self._SwitchTo(self)

    def close(self):
        pass


def test_appraisal_saves_when_tab_never_opens():
    """감정평가서: **탭이 안 떠도 다운로드가 왔으면 저장한다** (Sprint 201, BUGS #135).

    ## 무엇이 잘못돼 있었나

    `collect_appraisal()` 은 `window.open(pdf_url)` 뒤 새 탭이 뜨기를 기다리고,
    안 뜨면 **`wait_for_download()` 를 부르지도 않고 실패로 끝냈다.**

    그런데 이 드라이버는 `plugins.always_open_pdf_externally: True` 로 만들어진다 —
    Chrome 은 PDF 를 그리지 않고 내려받고, 그리면 될 것이 없는 탭은 뜨지 않는다.
    **다운로드가 성공할수록 탭이 안 생기는 구조**였다.

    ## 실측 (2026-08-18)

    실브라우저로 이 경로를 태우자 로그는 `appraisal PDF 탭 생성 실패` 였는데
    `downloads/` 에는 2,528,908 바이트 PDF 가 도착해 있었고, 그 물건의 기존
    `appraisal.pdf` 와 **sha256 이 일치**했다. 받아 놓고 버린 것이다.

    그리고 `downloads/` 최상위에 고아 PDF 8개가 쌓여 있었다. 그중 4개는 같은 문서의
    Chrome 중복 이름(`... (1).pdf` ~ `(3).pdf`) 이었다 —
    **같은 문서를 네 번 받아 네 번 버렸다는 증거다.**

    ## 대조군

    "탭도 없고 다운로드도 없으면" 은 여전히 실패여야 한다. 그것까지 성공으로 만들면
    아무것도 안 받고 성공했다고 말하는, 이 저장소가 BUGS #47 이래 잡아 온 부류가 된다.
    """
    import crawler.doc_crawler as dc
    import crawler.doc_paths as dp_mod

    print("\n--- 7j. 탭이 안 떠도 다운로드가 왔으면 저장한다 (Sprint 201, BUGS #135) ---")
    docs_root = tempfile.mkdtemp(prefix="qa_notab_docs_")
    download_dir = tempfile.mkdtemp(prefix="qa_notab_dl_")
    orig = (dp_mod.DOCUMENT_ROOT, dc.DOWNLOAD_DIR, dc.wait_for_download,
            dc.NEW_WINDOW_TIMEOUT)
    try:
        dp_mod.DOCUMENT_ROOT = docs_root
        dc.DOWNLOAD_DIR = download_dir
        dc.NEW_WINDOW_TIMEOUT = 1        # 탭을 기다리느라 테스트가 느려지지 않게
        court, case_no, item_no = "QA법원", "2026타경11", "1"
        dest = os.path.join(dp_mod.get_doc_dir(court, case_no, item_no), "appraisal.pdf")

        # --- 1) 탭은 안 뜨지만 PDF 가 도착한 경우 -> 저장돼야 한다 ---
        arrived = os.path.join(download_dir, "HR2025-0609-0001.pdf")
        payload = b"%PDF-1.7" + b"A" * 400
        with open(arrived, "wb") as f:
            f.write(payload)
        dc.wait_for_download = lambda before, timeout=30: arrived

        r = dc.collect_appraisal(_FakeNoTabDriver(), court, case_no, item_no, "btn-id")
        check("탭이 없어도 성공으로 끝난다", r["success"], True)
        check_true("목적지에 저장된다", os.path.isfile(dest))
        check("저장된 내용이 받은 내용과 같다",
              hashlib.sha256(open(dest, "rb").read()).hexdigest(),
              hashlib.sha256(payload).hexdigest())
        check_true("다운로드 폴더에 고아를 남기지 않는다", not os.path.exists(arrived))

        # --- 2) 대조군: 탭도 없고 다운로드도 없으면 여전히 실패 ---
        os.remove(dest)
        dc.wait_for_download = lambda before, timeout=30: None
        r2 = dc.collect_appraisal(_FakeNoTabDriver(), court, case_no, item_no, "btn-id")
        check("아무것도 안 왔으면 실패다", r2["success"], False)
        check_true("아무것도 저장하지 않는다", not os.path.exists(dest))

        # --- 3) 대조군: 받은 것이 PDF 가 아니면 저장하지 않는다(기존 방어 유지) ---
        bad = os.path.join(download_dir, "bad.pdf")
        with open(bad, "wb") as f:
            f.write(b"<html>error</html>")
        dc.wait_for_download = lambda before, timeout=30: bad
        r3 = dc.collect_appraisal(_FakeNoTabDriver(), court, case_no, item_no, "btn-id")
        check("가짜 PDF 는 여전히 거부한다", r3["success"], False)
        check_true("가짜 PDF 는 목적지에 안 남는다", not os.path.exists(dest))
    finally:
        (dp_mod.DOCUMENT_ROOT, dc.DOWNLOAD_DIR, dc.wait_for_download,
         dc.NEW_WINDOW_TIMEOUT) = orig
        shutil.rmtree(docs_root, ignore_errors=True)
        shutil.rmtree(download_dir, ignore_errors=True)


def test_spec_saves_when_tab_never_opens():
    """명세서: **탭이 안 떠도 다운로드가 왔으면 저장한다** (Sprint 202, BUGS #136).

    BUGS #135(감정평가서)를 고친 뒤 **같은 모양이 명세서에도 있는지** 전수로 훑다 나왔다.
    `collect_spec()` 도 새 탭을 성공 조건으로 삼고, 안 뜨면 `wait_for_download()` 를
    부르지도 않고 실패로 끝냈다.

    ## 근거

    `downloads/` 최상위 고아 8개 중 **5개가 매각물건명세서**였다(2026-08-18 실측,
    전체 14.0MB). 즉 명세서 다운로드가 도착했는데 저장되지 않은 전례가 실제로 있다.
    Chrome 은 `plugins.always_open_pdf_externally: True` 로 만들어지므로, 법원이 명세서를
    뷰어 대신 PDF 로 바로 내려 주면 **그릴 것이 없어 탭이 뜨지 않고 파일만 도착한다.**

    ## 대조군을 함께 둔다

    뷰어 경로(탭이 뜨는 정상 경로)가 그대로 동작해야 한다. 탭이 뜨면 예전처럼
    '파일저장' 버튼을 찾아 눌러야 하고, 그 경로를 건드리면 안 된다.
    """
    import crawler.doc_crawler as dc
    import crawler.doc_paths as dp_mod

    print("\n--- 7k. 명세서도 탭 없이 도착하면 저장한다 (Sprint 202, BUGS #136) ---")
    docs_root = tempfile.mkdtemp(prefix="qa_specnotab_docs_")
    download_dir = tempfile.mkdtemp(prefix="qa_specnotab_dl_")
    orig = (dp_mod.DOCUMENT_ROOT, dc.DOWNLOAD_DIR, dc.wait_for_download,
            dc.NEW_WINDOW_TIMEOUT)
    try:
        dp_mod.DOCUMENT_ROOT = docs_root
        dc.DOWNLOAD_DIR = download_dir
        dc.NEW_WINDOW_TIMEOUT = 1
        court, case_no, item_no = "QA법원", "2026타경12", "1"
        dest = os.path.join(dp_mod.get_doc_dir(court, case_no, item_no), "spec.pdf")

        # --- 1) 탭은 안 뜨지만 PDF 가 도착 -> 저장 ---
        arrived = os.path.join(download_dir, "명세서.pdf")
        payload = b"%PDF-1.4" + b"S" * 300
        with open(arrived, "wb") as f:
            f.write(payload)
        dc.wait_for_download = lambda before, timeout=30: arrived

        r = dc.collect_spec(_FakeNoTabDriver(), court, case_no, item_no, "btn-id")
        check("탭이 없어도 성공으로 끝난다", r["success"], True)
        check_true("목적지에 저장된다", os.path.isfile(dest))
        check("내용이 받은 것과 같다",
              hashlib.sha256(open(dest, "rb").read()).hexdigest(),
              hashlib.sha256(payload).hexdigest())
        check_true("고아를 남기지 않는다", not os.path.exists(arrived))

        # --- 2) 대조군: 탭도 없고 다운로드도 없으면 실패 ---
        os.remove(dest)
        dc.wait_for_download = lambda before, timeout=30: None
        r2 = dc.collect_spec(_FakeNoTabDriver(), court, case_no, item_no, "btn-id")
        check("아무것도 안 왔으면 실패다", r2["success"], False)
        check_true("아무것도 저장하지 않는다", not os.path.exists(dest))

        # --- 3) 대조군: 뷰어 경로(탭이 뜨는 정상 경로)는 그대로 동작한다 ---
        arrived2 = os.path.join(download_dir, "viewer.pdf")
        with open(arrived2, "wb") as f:
            f.write(payload)
        dc.wait_for_download = lambda before, timeout=30: arrived2
        r3 = dc.collect_spec(_FakeSpecViewerDriver(), court, case_no, item_no, "btn-id")
        check("뷰어 경로도 여전히 성공한다", r3["success"], True)
        check_true("뷰어 경로도 목적지에 저장한다", os.path.isfile(dest))
    finally:
        (dp_mod.DOCUMENT_ROOT, dc.DOWNLOAD_DIR, dc.wait_for_download,
         dc.NEW_WINDOW_TIMEOUT) = orig
        shutil.rmtree(docs_root, ignore_errors=True)
        shutil.rmtree(download_dir, ignore_errors=True)


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
    # ★ `body` 만 보면 `else:` / `except:` / `finally:` 안의 호출을 통째로 놓친다
    #   (2026-08-18 Sprint 202 정정). 실제로 `collect_spec()` 의 뷰어 경로를 `else:` 로
    #   옮기자 그 호출 지점이 **가드에서 사라졌다** — 검사는 통과하는데 보지 않는 상태다.
    #   문장 리스트를 갖는 속성을 전부 훑는다. 새 문법이 생겨도 속성 이름으로 따라간다.
    STMT_LISTS = ("body", "orelse", "finalbody")
    blocks = []
    for parent in ast.walk(tree):
        for attr in STMT_LISTS:
            lst = getattr(parent, attr, None)
            if isinstance(lst, list) and lst and isinstance(lst[0], ast.stmt):
                blocks.append(lst)

    for body in blocks:
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
        test_looks_like_pdf_rejects_non_pdf_bytes()
        test_collect_spec_refuses_non_pdf_download()
        test_overwrite_of_existing_pdf_is_atomic()
        test_no_collector_uses_non_atomic_move()
        test_status_hash_ignores_our_own_timestamp()
        test_unchanged_content_preserves_browser_cache()
        test_identical_pdf_is_not_replaced()
        test_completeness_matches_what_the_viewer_serves()
        test_appraisal_saves_when_tab_never_opens()
        test_spec_saves_when_tab_never_opens()
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
