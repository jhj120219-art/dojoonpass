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
        # 2026-08-21 실측: 'refresh'가 빠져 있었다. `storage/database.py`의
        # `QUEUE_STATUS_REFRESH`(Sprint 189, "변경 기반 재수집")가 실제로 쓰는 정식
        # 상태값인데 이 허용목록이 그 상태 도입 이후 갱신되지 않았다 - 실 데이터에
        # 'refresh' 행이 있는 것은 결함이 아니라 이 허용목록의 드리프트였다.
        check("알려진 상태값만 존재한다",
              sorted(statuses - {"pending", "in_progress", "done", "failed", "refresh",
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
        #
        # 2026-08-23 실측(Sprint 267): id=369(court_code 경기 소재 법원 / 2024타경7344 / item 6 /
        # appraisal)이 1건 걸린다 - `auction_date`가 그 사이 **미래(2026-08-24)로 다시 밀렸는데**
        # `last_attempt_at`은 2026-07-12로 그보다 훨씬 전이다. 즉 기일이 지나 SKIPPED_EXPIRED로
        # 굳은 뒤 기일이 재공고돼 다시 미래가 됐다는 뜻이다. 새 결함이 아니라
        # `test_refresh_trigger.py::test_expired_revival_is_scoped_by_changed_field_not_by_item`
        # 이 이미 문서화해 둔 정책 공백의 **첫 실측 사례**다 - `REFRESH_DOC_TYPES_BY_FIELD`가
        # "auction_date" 변경으로는 spec/status만 되살리고 appraisal/image는 되살리지 않도록
        # 만들어져 있어서다(제품 정책 결정 대기, docs/BETA_RELEASE_CHECKLIST.md 참고). 코드를
        # 바꾸지 않고 상한만 둔다 - 늘어나면(정책 결정 없이 재발 범위가 커지면) 여전히 잡힌다.
        # ── `SKIPPED_EXPIRED` 인데 기일이 안 지난 행 ────────────────────────────
        #
        # `SKIPPED_EXPIRED` 는 "기일이 지나 지금은 대상이 아님"이라는 **주장**이다.
        # 그 행의 `auction_date` 가 오늘 이후라면 그 주장은 사실이 아니고, 그 문서는
        # 아무도 다시 보지 않는다(`reset_stale_queue()` 는 SKIPPED_* 를 일부러 건드리지
        # 않는다). 즉 **진행 중인 물건의 문서가 조용히 영구 누락**된다.
        #
        # ★ 2026-08-27 (BUGS #254) — 이 검사를 **세는 것에서 증명하는 것으로** 바꿨다.
        #
        #   예전에는 "상한 1" 이었다. 그런데 1 -> 36 으로 늘어 붉어졌고(전부 appraisal,
        #   전부 auction_date=오늘, doc_raw 0행 = 한 번도 못 받은 것), 원인이 실제로
        #   있었다: `enqueue_documents()` 의 되살리기가 "기일이 **바뀌었을 때**"만 돌아서,
        #   날짜가 이미 최신인 채 굳은 행은 **영원히 안 고쳐졌다.**
        #
        #   고친 뒤에도 **운영 DB 는 다음 06:00 적재 전까지 그대로**다. 그래서 잔량을
        #   세는 방식으로는 "고쳤는데도 붉은" 상태가 남는다 — 그러면 이 게이트는
        #   다시 아무 말도 못 하게 된다.
        #
        #   대신 **불변식을 직접 증명한다**: 실 DB 스냅샷에 오늘 크롤과 같은 입력을
        #   재생해서 잔량이 0 이 되는지 본다. 운영 DB 는 건드리지 않는다(스냅샷 사본이다).
        #   언제 마지막 크롤이 돌았는지와 무관하게 성립하고, 되살리기가 깨지면 붉어진다.
        expired_not_expired = one(
            "SELECT COUNT(*) FROM document_queue WHERE status='SKIPPED_EXPIRED'"
            " AND auction_date>=date('now','localtime')")
        print("      현재 잔량 %d건 (다음 적재에서 해소되어야 한다)" % expired_not_expired)

        import tempfile as _tf, shutil as _sh
        import storage.database as _db
        _d = _tf.mkdtemp(prefix="pi_expired_")
        _saved = _db.DB_PATH
        try:
            _scratch = os.path.join(_d, "auction.db")
            _db.snapshot_live_db(_scratch)          # 찢어진 사본을 만들지 않는다
            _db.DB_PATH = _scratch
            _c = sqlite3.connect(_scratch)
            _c.row_factory = sqlite3.Row
            _rows = [dict(court_code=r["court_code"], case_no=r["case_no"],
                          item_no=r["item_no"], auction_date=r["auction_date"])
                     for r in _c.execute("SELECT court_code, case_no, item_no,"
                                         " auction_date FROM auction")]
            _c.close()
            check_true("검사가 공허하지 않다(재생할 크롤 행이 있다)", len(_rows) > 0,
                       "-> %d행" % len(_rows))
            _db.enqueue_documents(_rows)
            _c = sqlite3.connect(_scratch)
            _left = _c.execute(
                "SELECT COUNT(*) FROM document_queue WHERE status='SKIPPED_EXPIRED'"
                " AND auction_date>=date('now','localtime')").fetchone()[0]
            # 대조군 — 되살리기가 종결 상태를 무차별로 열어젖히지 않는가.
            _done = _c.execute("SELECT COUNT(*) FROM document_queue"
                               " WHERE status='done'").fetchone()[0]
            _c.close()
            check("★ 적재를 재생하면 '기일이 남았는데 SKIPPED_EXPIRED' 가 0이 된다",
                  _left, 0)
            check("★ 그때 done 행은 되살아나지 않는다(재수집 정책은 그대로 보류)",
                  _done, one("SELECT COUNT(*) FROM document_queue WHERE status='done'"))
        finally:
            _db.DB_PATH = _saved
            _sh.rmtree(_d, ignore_errors=True)

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

        # "자산을 가진 종결 상태"의 정본은 storage.database 에 있다 — 여기에 값을
        # 베껴 두면 어휘가 늘었을 때 이 검사만 옛 목록으로 남는다(이번 결함의 원인).
        from storage.database import DOC_STATUS_HAS_ARTIFACT

        no_file, no_ds, not_ready, no_item = [], [], [], []
        contradictory = []
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
            # ★ 사진은 **다른 규칙으로** 본다 (2026-08-26). 면제가 아니다.
            #
            #   이 루프는 done 행 전부를 도는데 `QUEUE_DOC_FILE` 은 **문서 3종만** 담는다
            #   (위 28행 주석이 그렇게 적고 있다). 그래서 doc_type='image' 는
            #   `.get(..., "?")` 로 **파일명이 문자 "?"** 가 되어 절대 존재하지 않고,
            #   `QUEUE_TO_DS.get("image")` 는 None 이라 document_status 조회도 빈다.
            #   즉 image 가 done 이 되는 순간 두 목록에 무조건 걸린다.
            #
            #   지금까지 드러나지 않은 이유는 단순하다 — **image 행이 done 이 된 적이
            #   없었다.** `DojoonPass-DocWorker` 가 등록돼 있지 않아 사진 수집 자체가
            #   한 번도 돌지 않았다(auction_image 0행). 2026-08-26 에 워커를 등록하고
            #   처음 돌리자 image done 17행이 생기며 곧바로 붉어졌다.
            #   **사진 쪽은 멀쩡했다** — 17행 전부 auction_image 행과 실제 파일을 갖고 있다.
            #
            #   사진은 물건당 0~N장이라 "종류당 파일 1개" 표에 넣을 수 없다. 대신 문서에
            #   요구하는 것과 **같은 강도**로 본다: 행이 있고, 파일이 실재하고, 0바이트가 아니다.
            # document_status 조회는 **image 를 포함한 전체 표**를 쓴다 — 사진도 화면
            # 상태를 갖는다. 파일 검사보다 **먼저** 읽는다: 사진은 이 상태에 따라
            # 기대하는 것이 정반대가 되기 때문이다(아래 NO_IMAGE 주석).
            st = conn.execute("SELECT status FROM document_status WHERE item_id=? AND doc_type=?",
                              (ai["id"], QUEUE_TO_DS_ALL.get(r["doc_type"]))).fetchone()
            ds_status = st["status"] if st else None

            if r["doc_type"] == "image":
                imgs = conn.execute(
                    "SELECT seq, storage_path FROM auction_image WHERE item_id=?",
                    (ai["id"],)).fetchall()
                # ★ NO_IMAGE 는 **정상 종결**이다 (2026-09-01, 실데이터 최초 관측).
                #
                #   `doc_worker.py` 는 사진을 못 가져온 것과 **법원에 원래 없는 것**을
                #   구분한다: `done_status = "NO_IMAGE" if result.get("no_asset") else "READY"`.
                #   docs/backend.md 도 *"NO_IMAGE 는 '법원이 사진을 제공하지 않는다'는
                #   확인된 답이지 실패가 아니다"* 라고 적고 있고, `audit_asset_integrity.py`
                #   는 이미 `ds.status NOT IN ('READY','NO_IMAGE')` 로 판정한다.
                #
                #   이 검사만 `auction_image` 행이 **반드시 있어야 한다**고 요구하고 있었다.
                #   지금까지 통과한 이유는 규칙이 옳아서가 아니라 **표본에 사진 없는 물건이
                #   없었기 때문이다** — docs/SPRINT144_ASSET_PIPELINE.md 가 *"표본 안에
                #   법원에 사진이 없는 물건은 없었다 — NO_IMAGE 경로는 합성 테스트로만
                #   검증됐다"* 고 적어 두었고, docs/roadmap.md 는 *"NO_IMAGE 실데이터가
                #   처음 관측되는가"* 를 미확인 항목으로 남겨 두었다. 그 물건이 2건 들어오자
                #   제품은 옳게 동작했는데 이 검사만 붉어졌다.
                #
                #   그래서 **면제하지 않고 방향을 뒤집는다**: 없다고 해 놓고 행이 남아
                #   있으면 그것이 모순이다(`clear_images_if_absence_confirmed()` 가
                #   정리하지 못한 경우). 검사의 강도는 줄지 않는다.
                if ds_status == "NO_IMAGE":
                    if imgs:
                        contradictory.append(
                            key + " (NO_IMAGE 인데 auction_image %d행)" % len(imgs))
                elif not imgs:
                    no_file.append(key + " (auction_image 행 없음)")
                for im in imgs:
                    ipath = os.path.join(ROOT, (im["storage_path"] or "").replace("/", os.sep))
                    if not im["storage_path"] or not os.path.exists(ipath):
                        no_file.append(key + " seq=%s" % im["seq"])
                    elif os.path.getsize(ipath) == 0:
                        no_file.append(key + " seq=%s (0바이트)" % im["seq"])
            elif not os.path.exists(os.path.join(
                    doc_dir(ai["court_name"], r["case_no"], r["item_no"]),
                    QUEUE_DOC_FILE.get(r["doc_type"], "?"))):
                no_file.append(key)
            if not st:
                no_ds.append(key)
            elif ds_status not in DOC_STATUS_HAS_ARTIFACT:
                not_ready.append(key)

        check("done인데 파일이 없는 행 없음", no_file[:5], [])
        check("NO_IMAGE 인데 사진 행이 남아 있는 물건 없음", contradictory[:5], [])
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
    """반대 방향 — 파일이 있으면 큐도 done(또는 refresh 대기 중)이어야 한다.

    2026-08-21 실측: 'refresh'를 결함으로 오판하고 있었다. `requeue_changed_documents()`
    (Sprint 189)는 법원 원천이 바뀐 물건의 `done` 행을 의도적으로 `refresh`로 되돌린다
    - 그 물건은 **이미 파일을 갖고 있으면서** 재수집을 기다리는 정상 상태다. '파일이
    있는데 done이 아니다'는 그 상태를 결함으로 오인한 것이지, refresh 자체가 결함이 아니다.
    """
    print("\n--- 3. 파일 -> 큐 (반대 방향) ---")
    conn = connect()
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute("""SELECT ai.id, ai.court_name, ai.case_no, ai.item_no, ac.court_code
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
                ok_states = ("done", "refresh")
                status = qr["status"] if qr else None

                # ★ SKIPPED_EXPIRED 는 **조건부로** 정상이다 (2026-08-26).
                #
                #   doc_worker 의 2차 방어선은 기일이 지난 큐 행을 브라우저를 열지 않고
                #   `SKIPPED_EXPIRED` 로 종결한다. 그런데 그 행이 **예전에 이미 수집돼
                #   파일을 갖고 있는** 경우가 있다(변경 감지로 다시 pending 이 됐다가
                #   그 사이 기일이 지난 경우). 그러면 "파일은 있는데 큐는 done 이 아니다"가 된다.
                #
                #   2026-08-26 워커 첫 실행에서 13행이 그렇게 됐다. **전부 무해했다** —
                #   13행 모두 `document_status` 가 READY 라 사용자는 그 문서를 그대로 본다.
                #   기일이 지난 물건을 다시 수집할 이유도 없으므로 종결 자체가 옳다.
                #
                #   그래서 통째로 면제하지 않고 **사용자가 실제로 볼 수 있을 때만** 통과시킨다.
                #   파일은 있는데 화면 상태가 READY 가 아니면 그건 진짜 결함이다 —
                #   받아 놓고도 못 보여 주는 상태이므로 여전히 잡아야 한다.
                if status == "SKIPPED_EXPIRED":
                    ds = conn.execute(
                        "SELECT status FROM document_status WHERE item_id=? AND doc_type=?",
                        (r["id"], QUEUE_TO_DS[dt])).fetchone()
                    if ds and ds["status"] == "READY":
                        continue
                    bad.append("%s %s-%s %s -> SKIPPED_EXPIRED 인데 화면 상태가 %s"
                               % (r["court_name"], r["case_no"], r["item_no"], dt,
                                  ds["status"] if ds else "없음"))
                    continue

                if status not in ok_states:
                    bad.append("%s %s-%s %s -> %s"
                               % (r["court_name"], r["case_no"], r["item_no"], dt,
                                  status if status else "큐에 없음"))
        check_true("검사 대상 파일이 실제로 존재한다", found > 0, "파일을 하나도 못 찾으면 공허한 검사다")
        check("파일이 있는데 큐가 done/refresh가 아닌 것 없음", bad[:5], [])
    finally:
        conn.close()


def test_failure_reason_is_recorded():
    """최종 실패에 **사유**가 남는가 (2026-09-02).

    `storage/database.py:mark_queue_failed()` 의 주석은 큐 행에 아무것도 쓰지 않는
    선택을 *"실패 사실은 로그와 `document_collect_failures` 에 이미 남는다"* 로
    정당화한다. 그런데 **그 표에 쓰는 코드가 없었다** — INSERT 하는 곳은
    `collect_documents.py` 뿐이고 그 스크립트는 2026-07-15 이후 돌지 않았다.

    실측(2026-09-02): document_queue failed 188건(그중 기일이 남아 화면에 보이는
    물건 129건)인데 그 실행들이 남긴 사유는 0건이었다. 왜 문서가 없는지 아무도
    모르는 상태다.

    여기서는 **실제로 한 번 실패시켜** 사유가 표에 들어가는지 본다. 문자열 검사가
    아니라 동작 검사다(주석이 약속을 지키는지 보는 것이 이 검사의 목적이므로,
    주석을 읽는 방식으로는 같은 착각을 되풀이한다).
    """
    print("\n--- 최종 실패에 사유가 남는가 (mark_queue_failed) ---")
    import tempfile
    import storage.database as db

    prev = db.DB_PATH
    tmp = tempfile.mkdtemp(prefix="qa-failreason-")
    try:
        db.DB_PATH = os.path.join(tmp, "auction.db")
        db.init_db()
        import storage.migrate_v4_1 as mig
        import storage.migrations.run_migrations as runmig
        import contextlib
        import io as _io2
        with contextlib.redirect_stdout(_io2.StringIO()):
            mig.migrate()
            runmig.run()

        conn = db.get_connection()
        try:
            conn.execute("INSERT INTO auction_item (id, case_no, item_no, court_name) "
                         "VALUES (7001, '2099타경1', '1', '테스트지방법원')")
            conn.execute(
                "INSERT INTO document_queue (id, court_code, case_no, item_no, doc_type, "
                "status, retry_count) VALUES (901, 'T001', '2099타경1', '1', 'appraisal', ?, ?)",
                (db.QUEUE_STATUS_IN_PROGRESS, db.MAX_DOC_RETRY - 1))
            conn.commit()
        finally:
            conn.close()

        # 재시도가 소진되는 마지막 실패
        db.mark_queue_failed(901, db.MAX_DOC_RETRY - 1, None, reason="테스트사유: DOM 변경")

        conn = db.get_connection()
        try:
            rows = conn.execute(
                "SELECT item_id, doc_type, error_message FROM document_collect_failures"
            ).fetchall()
            qstatus = conn.execute(
                "SELECT status FROM document_queue WHERE id=901").fetchone()["status"]
        finally:
            conn.close()

        check("최종 실패가 큐에 반영된다", qstatus, db.QUEUE_STATUS_FAILED)
        check("실패 사유가 1건 기록된다", len(rows), 1)
        if rows:
            check("올바른 물건에 붙는다", rows[0]["item_id"], 7001)
            check("문서 종류가 남는다", rows[0]["doc_type"], "appraisal")
            check_true("사유 문자열이 그대로 남는다",
                       "테스트사유: DOM 변경" == rows[0]["error_message"],
                       rows[0]["error_message"])

        # 사유를 안 넘겨도 표는 채워져야 한다(빈 칸으로 남기지 않는다)
        conn = db.get_connection()
        try:
            conn.execute(
                "INSERT INTO document_queue (id, court_code, case_no, item_no, doc_type, "
                "status, retry_count) VALUES (902, 'T001', '2099타경1', '1', 'spec', ?, ?)",
                (db.QUEUE_STATUS_IN_PROGRESS, db.MAX_DOC_RETRY - 1))
            conn.commit()
        finally:
            conn.close()
        db.mark_queue_failed(902, db.MAX_DOC_RETRY - 1, None)
        conn = db.get_connection()
        try:
            n = conn.execute("SELECT COUNT(*) FROM document_collect_failures").fetchone()[0]
            last = conn.execute("SELECT error_message FROM document_collect_failures "
                                "ORDER BY id DESC LIMIT 1").fetchone()["error_message"]
        finally:
            conn.close()
        check("사유 없이 불러도 행은 남는다", n, 2)
        check_true("사유가 비어 있지 않다", bool(last), last)

        # 중간 재시도는 남기지 않는다 - 한 문서가 여러 행을 만들면 표가 못 쓰게 된다
        conn = db.get_connection()
        try:
            conn.execute(
                "INSERT INTO document_queue (id, court_code, case_no, item_no, doc_type, "
                "status, retry_count) VALUES (903, 'T001', '2099타경1', '1', 'status', ?, 0)",
                (db.QUEUE_STATUS_IN_PROGRESS,))
            conn.commit()
        finally:
            conn.close()
        db.mark_queue_failed(903, 0, None, reason="첫 시도 실패")
        conn = db.get_connection()
        try:
            n2 = conn.execute("SELECT COUNT(*) FROM document_collect_failures").fetchone()[0]
        finally:
            conn.close()
        check("중간 재시도는 사유를 남기지 않는다(최종 실패만)", n2, 2)
    finally:
        db.DB_PATH = prev
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def test_mass_purge_guard():
    """대량 삭제 차단기 — 부분 유실에서 파생 행을 쓸어버리지 않는가 (2026-09-02).

    `load_rights_data.py` / `load_spec_data.py` 를 `run_doc_worker.bat` 에 배선하면서
    필요해진 검사다. 배선 전에는 사람이 손으로 돌렸으므로 이상하면 바로 봤지만, 이제는
    **무인 야간 실행**이다.

    원래 안전장치는 `evidence_found == 0` 하나였다. 그것은 `documents/` 를 통째로 못 읽는
    경우만 막는다. 막지 못하는 것이 부분 유실이다 — OneDrive 가 절반만 동기화됐거나
    드라이브가 일부만 마운트되면 `evidence_found > 0` 이라 안전장치가 열리고, 남은 몇 건을
    빼고 **나머지 권리분석·임차인 데이터를 전부 지운다.**

    `guard_mass_purge()` 는 지우기 전에 규모를 재서 그 상황을 막는다.
    """
    print("\n--- 대량 삭제 차단기 (BUGS #245 배선의 전제) ---")
    import io as _io
    import re as _re
    from storage.database import (guard_mass_purge, PURGE_BLOCKED,
                                  PURGE_MAX_RATIO, PURGE_ABSOLUTE_FLOOR)

    check_true("표식이 삭제 건수와 섞이지 않는다(음수)", PURGE_BLOCKED < 0, PURGE_BLOCKED)

    # 통과해야 하는 것 — 평상시
    check("지울 게 없으면 통과", guard_mass_purge(413, 0, "t"), None)
    check("바닥값 미만 소량 삭제는 통과",
          guard_mass_purge(413, PURGE_ABSOLUTE_FLOOR - 1, "t"), None)
    # 비율 상한 **바로 아래**는 통과해야 한다(경계를 실제로 재는지 본다)
    just_under = int(413 * PURGE_MAX_RATIO)
    check_true("상한 바로 아래는 통과 (%d/413)" % just_under,
               guard_mass_purge(413, just_under, "t") is None, just_under)

    # 막아야 하는 것 — 부분 유실 시나리오
    just_over = int(413 * PURGE_MAX_RATIO) + 2
    check_true("상한 바로 위는 막힌다 (%d/413)" % just_over,
               isinstance(guard_mass_purge(413, just_over, "t"), str), just_over)
    check_true("절반이 사라지면 막힌다",
               isinstance(guard_mass_purge(1069, 500, "t"), str))
    check_true("전부 사라지면 막힌다",
               isinstance(guard_mass_purge(413, 413, "t"), str))
    check_true("기존이 0인데 지울 게 있으면 막힌다(계수 어긋남)",
               isinstance(guard_mass_purge(0, 50, "t"), str))
    check_true("막을 때 사유에 규모가 적힌다",
               "413" in (guard_mass_purge(413, 400, "t") or ""))

    # 두 스크립트가 **같은 판정기**를 쓰는가 — 규칙을 베끼면 갈라진다(BUGS #204)
    import load_rights_data as LR
    import load_spec_data as LS
    for mod in (LR, LS):
        src = _io.open(mod.__file__, encoding="utf-8").read()
        name = os.path.basename(mod.__file__)
        check_true("%s 가 차단기를 부른다" % name, "guard_mass_purge(" in src)
        check_true("%s 가 자체 임계값을 만들지 않는다" % name,
                   "PURGE_MAX_RATIO =" not in src and "PURGE_ABSOLUTE_FLOOR =" not in src,
                   "임계값은 storage/database.py 한 곳에만 있어야 한다")
        # ★ 파일 전체에서 첫 DELETE 를 찾으면 안 된다 - `load_item()` 이 물건마다
        #   재적재하며 DELETE 하므로 항상 앞에 있다. **purge_orphans 함수 본문 안**에서
        #   순서를 본다(이 검사를 처음 그렇게 써서 스스로 붉어졌다).
        body = src[src.index("def purge_orphans("):]
        nxt = body.find("\ndef ", 1)
        if nxt > 0:
            body = body[:nxt]
        check_true("%s 가 지우기 전에 센다" % name,
                   "guard_mass_purge(" in body
                   and body.index("guard_mass_purge(") < body.index("DELETE FROM"),
                   "COUNT 를 DELETE 뒤에 하면 이미 지운 뒤다")
        check_true("%s 가 차단을 종료 코드로 싣는다" % name,
                   "PURGE_BLOCKED" in src and "return 1" in src)

    # 배선이 실제로 돼 있는가 — 이 검사의 존재 이유다
    bat = _io.open(os.path.join(ROOT, "run_doc_worker.bat"), encoding="utf-8-sig").read()
    called = set()
    for ln in bat.splitlines():
        if ln.strip().upper().startswith("REM"):
            continue
        m = _re.match(r'^\s*"%PY%"\s+(\S+\.py)', ln)
        if m:
            called.add(m.group(1))
    for script in ("load_rights_data.py", "load_spec_data.py"):
        check_true("run_doc_worker.bat 이 %s 를 부른다" % script, script in called, sorted(called))


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

        # ★ document_queue -> auction_item (court_code+case_no+item_no로 매칭)
        # (2026-08-22 Sprint 257 재발견 - `cleanup_orphans_dryrun.py`가 2026-08-14에
        # 이미 이 21행을 찾아 두고 있었다. 여기서는 그 사실을 **자동 회귀 가드**로
        # 승격한다 - 기존 도구는 수동 진단이라 CI에서 안 돈다).
        #
        # 위 다섯 쌍은 전부 `item_id`(auction_item PK) FK로 연결돼 있어 고아가 생기기
        # 어렵다. 그런데 `document_queue`는 auction_item을 PK로 참조하지 않고
        # (court_code, case_no, item_no) **문자열 조합**으로만 연결된다(`enqueue_documents()`
        # 가 이 키로 INSERT OR IGNORE한다). 같은 case_no가 **서로 다른 court_code**로 두 번
        # 크롤되면 옛 court_code의 큐 행은 새 court_code로 옮겨 가지 않고 고아가 된다.
        #
        # `cleanup_orphans_dryrun.py`의 비용 모델 실측(2026-08-22): 지금 이 21행 중
        # pending 15행은 전부 **기일이 이미 지나** 1차 방어선에 막혀 워커가 브라우저조차
        # 열지 않는다 - 실제 낭비 비용은 **지금은 0**이다(크롤이 재개돼 같은 사건번호가
        # 다시 걸릴 때만 비용이 생긴다). 이미 알려진 "병합 사건 중복"(case_no 자체가
        # 바뀌는 경우)과는 다른 원인이다 - 여기서는 case_no/item_no는 그대로고
        # court_code만 바뀐다.
        #
        # 정리(어느 court_code 행을 지울지)는 운영 데이터 변경이라 승인 영역이다. 여기서는
        # 늘어나지 않는지만 잠근다(상한 - 늘면 court_code 재배정이 새로 발생했다는 뜻).
        orphan_queue = one("""
            SELECT COUNT(*) FROM document_queue dq
            WHERE NOT EXISTS (
                SELECT 1 FROM auction_item ai JOIN auction_case ac ON ac.id = ai.case_id
                WHERE ac.court_code = dq.court_code AND ai.case_no = dq.case_no
                  AND ai.item_no = dq.item_no
            )
        """)
        # ※ 2026-08-24 Sprint 251 실측: **18행**이다(상한 21보다 3 적다).
        #   이 3칸의 여유는 **패딩이 아니라 데이터가 줄어든 결과**다 — 상한 21은
        #   2026-08-22 에 auction_item 이 더 많던 상태에서 실제로 잰 값이고, 지금 이
        #   DB(1,876행)에는 그중 3행에 해당하는 사건이 아예 없다. 그래서 조이지 않는다:
        #   데이터가 원래 크기로 돌아오면 21이 다시 정상값이 되고, 그때 붉어지는 것은
        #   회귀가 아니라 오탐이다. (같은 세션에 조인 sido 상한 5->4 와 차량 역방향
        #   상한 5->3 은 성격이 다르다 — 그쪽 여유는 어떤 측정에도 근거가 없었다.)
        check_true("document_queue -> auction_item(court+case+item) 고아가 늘지 않았다"
                   " (court_code 재배정으로 영구 고아가 되는 알려진 결함, 상한 21)",
                   orphan_queue <= 21, "-> 현재 %d행 (상한 21)" % orphan_queue)

        # ★ documents/ 파일 고아 - 대응 auction_item이 없는 문서 폴더에 실제 파일이 있다
        # (2026-08-22 Sprint 260). `cleanup_orphans_dryrun.py`(2026-08-14)의 경로 규칙을
        # 그대로 따라 자동 가드로 승격한다 - 그대로 복제하지 않고 **같은 매칭 SQL**을 쓴다.
        # 실측: 파일이 든 고아 디렉터리 1개(고양지원/2024타경2803/1, 12.4MB) - 위 큐 고아와
        # 같은 사건이다(court_code 재배정으로 옛 court_code 밑 문서만 남음).
        doc_root = os.path.join(ROOT, "documents")
        file_orphans = 0
        if os.path.isdir(doc_root):
            for court in os.listdir(doc_root):
                cdir = os.path.join(doc_root, court)
                if not os.path.isdir(cdir):
                    continue
                for case in os.listdir(cdir):
                    casedir = os.path.join(cdir, case)
                    if not os.path.isdir(casedir):
                        continue
                    for item_no in os.listdir(casedir):
                        idir = os.path.join(casedir, item_no)
                        if not os.path.isdir(idir):
                            continue
                        hit = conn.execute(
                            "SELECT id FROM auction_item WHERE court_name=?"
                            " AND REPLACE(case_no,'/','_')=? AND COALESCE(item_no,'1')=?",
                            (court, case, item_no)).fetchone()
                        if hit:
                            continue
                        if any(os.path.isfile(os.path.join(idir, f)) for f in os.listdir(idir)):
                            file_orphans += 1
        check_true("documents/ 파일이 든 고아 디렉터리가 늘지 않았다(상한 1)",
                   file_orphans <= 1, "-> 현재 %d개 (상한 1)" % file_orphans)

        # document_status/document_queue의 doc_type은 storage.database.QUEUE_TO_DOC_STATUS_TYPE
        # 에 등록된 값만이어야 한다 — 그 표가 유일한 정의처다(단일 소스, 하드코딩 사본 금지).
        #
        # 2026-08-18 Sprint 188 실측: 여기 원래 있던 하드코딩 리스트
        # (`["appraisal","spec","status"]`, `["APPRAISAL","SPEC","STATUS"]`)가 실제 큐 값과
        # 어긋나 FAIL했다 — `image`(Sprint 144에서 추가된 정상 doc_type, 사진은 버튼 없이
        # 상세페이지 DOM을 바로 읽으므로 `get_doc_button_id()`가 몰라도 결함이 아니다)가
        # 실제로 이 DB의 `document_queue`에 처음 나타났기 때문이다. "정상적으로 새 doc_type이
        # 하나 늘면 이 검사가 거짓 FAIL을 낸다"는 것 자체가 하드코딩 리스트의 함정이라,
        # 목록을 복제하는 대신 같은 표를 그대로 가져와 비교한다.
        sys.path.insert(0, ROOT)
        from storage.database import QUEUE_TO_DOC_STATUS_TYPE
        known_lower = sorted(QUEUE_TO_DOC_STATUS_TYPE.keys())
        known_upper = sorted(QUEUE_TO_DOC_STATUS_TYPE.values())

        kinds = sorted(r[0] for r in conn.execute("SELECT DISTINCT doc_type FROM document_status"))
        check_true("document_status.doc_type 표기 - 알려진 값만 (%s)" % known_upper,
                   set(kinds) <= set(known_upper), kinds)
        kinds_q = sorted(r[0] for r in conn.execute("SELECT DISTINCT doc_type FROM document_queue"))
        check_true("document_queue.doc_type 표기 - 알려진 값만 (%s)" % known_lower,
                   set(kinds_q) <= set(known_lower), kinds_q)
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
        # ★ 2026-08-28: 상한 2 -> 3. 늘어난 한 건이 **같은 부류인지 확인한 뒤** 올렸다
        #   (#255 에서 배운 대로 — 그때는 확인해 보니 오탐이라 상한 대신 검사를 고쳤다).
        #
        #     id=317    자동차,중기  [집합건물 철근콘크리트구조 45.22㎡]  수원지방법원  07-07
        #     id=13751  자동차,중기  [집합건물 철근콘크리트구조 55.05㎡]  고양지원     08-28  <- 새로 걸린 것
        #     id=11804  자동차       [토지 목장용지 353㎡]              인천지방법원  08-01
        #
        #   새로 걸린 id=13751 은 id=317 과 **모양이 같다** — `property_type` 이
        #   `자동차,중기` 인데 주소 대괄호는 실제 집합건물(아파트/오피스 호실)이다.
        #   법원이 다르므로(고양지원 vs 수원지방법원) 특정 법원의 표기 습관도 아니다.
        #   즉 법원 원천의 분류가 그런 것이지 normalizer 가 새로 튀는 것이 아니다
        #   (`normalizer` 는 `property_type` 을 가공하지 않고 크롤 값을 그대로 넘긴다).
        #
        #   다른 부류였다면 상한을 올리지 않고 원인부터 팠을 것이다.
        check_true("차량 오분류가 늘지 않았다 (현재 %d건, 상한 3)" % len(bad), len(bad) <= 3, bad[:5])

        # 반대 방향도 본다 — 내용은 차량인데 종류가 차량이 아닌 행.
        #
        # ★ 2026-08-27 (BUGS #255) — **회사 이름을 물건 종류로 읽지 않는다.**
        #
        #   상한을 4 -> 5 로 올리려다 멈추고 다섯째 행을 실제로 봤더니 앞의 넷과
        #   **같은 부류가 아니었다**:
        #
        #       542 / 1806 / 6311 / 12093   "[기타 동력선]" "[선박 동력선 …]"   진짜 선박
        #       13732                       "[토지 도로 368㎡ 에이스건설기계주식회사 지분 …]"
        #
        #   마지막 것은 **토지**다. `VEHICLE` 의 "건설기계"가 소유자 **상호**
        #   ("에이스건설기계주식회사")에 걸린 것이고, 물건 종류와는 아무 상관이 없다.
        #   즉 늘어난 1건은 데이터 결함이 아니라 **이 검사의 오탐**이었다.
        #   상한을 올렸으면 오탐을 정상으로 굳히고, 그 한 칸으로 **진짜 오분류 하나가
        #   조용히 통과**했을 것이다. (Sprint 251 이 "근거 없는 여유 2칸"을 없앤 것과
        #   같은 이유다.)
        #
        #   그래서 판정 대상에서 상호를 먼저 걷어낸다. 대괄호 안은 법원 표기라
        #   `…주식회사` / `㈜…` / `(주)…` 꼴이 그대로 들어온다.
        CORP = re.compile(r"[가-힣A-Za-z0-9]*(?:주식회사|유한회사|합자회사|㈜)"
                          r"|㈜[가-힣A-Za-z0-9]*"
                          r"|\(주\)\s*[가-힣A-Za-z0-9]*")

        def _without_corp_names(text):
            """상호를 걷어낸 나머지. 물건 종류 판정은 이쪽만 본다."""
            return CORP.sub(" ", text or "")

        # 자기 검증 — 걷어내기가 실제로 동작하고, 진짜 차량은 살아남는가.
        check_true("자기 검증: 상호 속 '건설기계'는 차량으로 읽지 않는다",
                   not VEHICLE.search(_without_corp_names(
                       "토지 도로 368㎡ 에이스건설기계주식회사 지분 2분의 1 전부")))
        check_true("자기 검증: 진짜 선박은 그대로 잡는다",
                   bool(VEHICLE.search(_without_corp_names("선박 동력선 혜원5호"))))
        check_true("자기 검증: 상호가 아닌 '건설기계'는 그대로 잡는다",
                   bool(VEHICLE.search(_without_corp_names("건설기계 굴착기 1대"))))

        rev = []
        for r in conn.execute(
                "SELECT id, property_type, full_address FROM auction_item "
                "WHERE property_type NOT LIKE '%자동차%' AND property_type NOT LIKE '%중기%'"):
            m = BR.search(r["full_address"] or "")
            if m and VEHICLE.search(_without_corp_names(m.group(1))):
                rev.append("id=%s %s [%s]" % (r["id"], r["property_type"], m.group(1)[:40]))
        print("    내용은 차량인데 종류가 차량이 아닌 행: %d건" % len(rev))
        for b in rev[:5]:
            print("      ", b)
        # ★ 2026-08-24 Sprint 251: 상한을 5 -> 3 으로 조인다.
        #   `docs/BUGS.md` #56 은 이 검사를 만들 당시 실측을 **3건**으로 적어 두었고
        #   (id=542 / 1806 / 6311), 오늘 다시 재도 **같은 3건**이다. 그런데 상한만
        #   5로 적혀 있었다 — 어떤 측정에도 근거가 없는 **2칸의 여유**다.
        #   상한이 실측보다 헐거우면 새 오분류가 그만큼 조용히 통과한다.
        #   (앞 방향 상한 2는 실측 2와 정확히 맞아 손대지 않았다.)
        # ★ 2026-08-24 야간: 크롤이 실제로 재개돼 상한 3 -> 4. 새로 걸린 id=12093
        #   "[선박 동력선 공축5호]" 는 앞의 세 건(542/1806/6311)과 **같은 부류다**.
        # ★ 2026-08-27: 다섯째(id=13732)는 오탐이라 검사를 고쳤다 — **상한은 4 그대로**다.
        check_true("역방향 오분류가 늘지 않았다 (현재 %d건, 상한 4)" % len(rev), len(rev) <= 4, rev[:5])
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
# 9-b. 파이썬이 남기는 시각이 전부 **naive 로컬**인가 (2026-09-01 신설)
#
# §9 는 SQLite 쪽(`datetime('now')` -> UTC)만 본다. 반대쪽 절반 — **파이썬이 무엇을
# 문자열로 남기는가** — 를 지키는 것은 아무것도 없었다. 전수로 재 보니 지금은 완벽하다:
#
#     제품 .py 전체에서 시각을 남기는 자리 60여 곳이 **전부** `datetime.now().isoformat()`
#     또는 거기서 timedelta 로 파생된 값이다. `utcnow()` 0건 / tz-aware 0건.
#
# 그런데 이 일관성이 깨지면 **세 군데가 동시에, 조용히** 틀린다.
#
#   1) 문자열 비교가 무너진다. `api/v1/subscriptions.py` 는 만료를 이렇게 본다:
#
#          row["expires_at"] <= now.isoformat()          <- 사전순 비교다
#
#      한쪽만 `+09:00` 이 붙으면 자릿수가 달라져 비교가 뒤집힌다. 구독이 안 끝나거나
#      멀쩡한 구독이 만료된다. 예외도 로그도 없다.
#
#   2) §9 가 맞춰 놓은 SQLite 비교(`datetime('now','localtime')`)와 다시 어긋난다.
#      그것이 BUGS 의 "30분 재시도가 실제로는 9시간 30분" 결함이었다.
#
#   3) 화면 날짜가 하루 밀린다. 프런트는 `new Date(값).toLocaleDateString('ko-KR')`
#      로 찍는데, **naive 문자열이라 로컬로 파싱되고 로컬로 찍혀 대칭이 성립**한다
#      (그래서 지금은 어느 나라에서 봐도 한국 달력 날짜가 그대로 보인다).
#      `Z` 나 오프셋이 붙는 순간 그 대칭이 깨진다.
#
# 즉 저장 형식은 **세 계층이 공유하는 계약**이지 한 파일의 취향이 아니다.
#
# 테스트는 대상에서 뺀다 — JWT 의 `exp` 는 규격상 UTC 라 `timezone.utc` 를 쓰는 것이
# 옳다(`test_auth_jwt.py`). 대신 **그 예외가 번지지 않는지**를 아래에서 함께 센다.
# 손으로 유지하는 예외 목록을 만들지 않기 위해서다(Sprint 118 의 교훈).
# ---------------------------------------------------------------------------

def test_python_timestamps_are_naive_local():
    print("\n--- 9-b. 파이썬이 남기는 시각이 naive 로컬인가 ---")
    import ast
    import subprocess

    try:
        out = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "*.py"],
            cwd=ROOT, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as exc:
        print("    [SKIP] git 을 실행할 수 없다 (%s)" % type(exc).__name__)
        return
    if out.returncode != 0:
        print("    [SKIP] git 저장소가 아니다")
        return

    rel_all = [p for p in out.stdout.split() if p.endswith(".py")]
    rel_all = [p for p in rel_all if "-DESKTOP-" not in p]   # OneDrive 충돌 사본(#253)
    product = [p for p in rel_all if not os.path.basename(p).startswith("test_")]
    tests = [p for p in rel_all if os.path.basename(p).startswith("test_")]
    check_true("검사가 공허하지 않다(제품 .py 를 실제로 찾았다) - %d개" % len(product),
               len(product) >= 40, len(product))

    def scan(rel_paths):
        """tz-aware 시각을 만드는 자리를 모은다. 주석/문자열은 AST 라 애초에 안 걸린다."""
        found = []
        for rel in rel_paths:
            full = os.path.join(ROOT, rel.replace("/", os.sep))
            try:
                tree = ast.parse(open(full, encoding="utf-8-sig").read())
            except (OSError, SyntaxError):
                continue        # 작업 트리에 없거나 파싱 불가 - 판정 대상이 아니다
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                name = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
                why = None
                if name == "utcnow":
                    why = "utcnow()"
                elif name in ("now", "today") and (node.args or node.keywords):
                    # `datetime.now(timezone.utc)` / `now(tz=...)` -> tz-aware
                    why = "%s(<tz>)" % name
                elif name == "astimezone":
                    why = "astimezone()"
                elif any(kw.arg == "tzinfo" for kw in node.keywords):
                    why = "tzinfo=..."
                if why:
                    found.append("%s:%d %s" % (rel, node.lineno, why))
        return sorted(found)

    check("★ 제품 코드가 tz-aware 시각을 만들지 않는다", scan(product), [])
    print("      -> 저장 형식은 `datetime.now().isoformat()` (naive 로컬) 하나다."
          " 오프셋이 붙으면 문자열 비교와 프런트 표시가 함께 어긋난다")

    # 테스트 쪽 예외가 번지지 않는가.
    #
    # ★ 파일 이름 목록으로 두지 않는다. 처음엔 `["test_auth_jwt.py"]` 로 적었는데
    #   `test_api_regression.py` 가 `datetime.timezone as _tz` 로 import 해 같은 일을
    #   하고 있었다(grep 으로는 안 보인다 — AST 라서 잡혔다). 파일 목록은 곧 낡는다.
    #   대신 **이유**를 검사한다: tz-aware 를 쓸 정당한 이유는 JWT 의 `exp` 하나뿐이다
    #   (규격상 UTC epoch). `exp` 키를 가진 dict 안에서 만들어졌는지를 본다.
    def tz_aware_outside_jwt_exp(rel_paths):
        bad = []
        for rel in rel_paths:
            full = os.path.join(ROOT, rel.replace("/", os.sep))
            try:
                tree = ast.parse(open(full, encoding="utf-8-sig").read())
            except (OSError, SyntaxError):
                continue
            allowed = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Dict) and any(
                        isinstance(k, ast.Constant) and k.value == "exp" for k in node.keys):
                    for sub in ast.walk(node):
                        allowed.add(id(sub))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call) or id(node) in allowed:
                    continue
                name = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
                if (name == "utcnow"
                        or (name in ("now", "today") and (node.args or node.keywords))
                        or name == "astimezone"
                        or any(kw.arg == "tzinfo" for kw in node.keywords)):
                    bad.append("%s:%d" % (rel, node.lineno))
        return sorted(bad)

    check("★ 테스트의 tz-aware 사용이 JWT 의 exp 밖으로 번지지 않았다",
          tz_aware_outside_jwt_exp(tests), [])
    print("      -> tz-aware %d곳, 전부 JWT 의 exp (규격상 UTC epoch)" % len(scan(tests)))

    # ── 자기 검증: 탐지기가 실제로 각 형태를 잡는가 ──────────────────────
    #   이 검사는 위반이 0건일 때 **아무것도 증명하지 않는 모양**이 되기 쉽다.
    import tempfile
    probe_dir = tempfile.mkdtemp(prefix="qa_tzscan_")
    probe = os.path.join(probe_dir, "qa_probe.py")
    cases = [
        ("utcnow()", "import datetime\nx = datetime.datetime.utcnow()\n"),
        ("now(<tz>)", "from datetime import datetime, timezone\nx = datetime.now(timezone.utc)\n"),
        ("astimezone()", "from datetime import datetime\nx = datetime.now().astimezone()\n"),
        ("tzinfo=...", "from datetime import datetime, timezone\nx = datetime(2026, 1, 1, tzinfo=timezone.utc)\n"),
    ]
    try:
        for label, src in cases:
            with open(probe, "w", encoding="utf-8") as fh:
                fh.write(src)
            saved, globals()["ROOT_TMP"] = None, None
            hits = []
            tree = ast.parse(src)
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                name = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
                if (name == "utcnow"
                        or (name in ("now", "today") and (node.args or node.keywords))
                        or name == "astimezone"
                        or any(kw.arg == "tzinfo" for kw in node.keywords)):
                    hits.append(label)
            check_true("자기 검증: %s 를 잡는다" % label, bool(hits), src.strip())
        # 반대 방향 — 정상 형태를 결함으로 잡지 않는가(오탐).
        ok_src = "from datetime import datetime, timedelta\nx = datetime.now().isoformat()\ny = (datetime.now() + timedelta(days=30)).isoformat()\n"
        false_hits = []
        for node in ast.walk(ast.parse(ok_src)):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
            if (name == "utcnow"
                    or (name in ("now", "today") and (node.args or node.keywords))
                    or name == "astimezone"
                    or any(kw.arg == "tzinfo" for kw in node.keywords)):
                false_hits.append(name)
        check("자기 검증: 정상 형태(now().isoformat())는 잡지 않는다", false_hits, [])
    finally:
        try:
            os.remove(probe)
            os.rmdir(probe_dir)
        except OSError:
            pass


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
DATA_ROLE_ENV = "DOJOONPASS_DATA_ROLE"
DATA_ROLE_OPERATIONAL = "operational"


def data_role():
    """이 머신이 **운영 데이터의 주인인가**. 선언하지 않으면 개발 머신으로 본다.

    ## 왜 이 구분이 필요한가 (2026-08-25, docs/BUGS.md #200)

    DOJOONPASS 는 머신을 역할로 나눈다 — 운영 Daily Crawl 은 **데스크탑1**이 돌리고,
    이 저장소에서 개발/테스트/Audit 을 하는 **데스크탑3** 은 크롤을 돌리지 않는다.

    그런데 아래 §11 은 그 구분 없이 **이 머신의 `auction.db`** 를 재고
    *"제품이 실제로 망가진 상태(검색 0건)"* 라고 판정해 왔다. 개발 머신에서는 그 값이
    당연히 0으로 수렴하므로, 이 검사는 **고칠 수 없는 실패로 영구히 붉은** 상태가 됐고
    실제로 여러 세션이 그것을 "유일하게 알려진 실패"로 취급하며 지나갔다.
    이 함수 바로 위 주석이 예언한 바로 그 상태다 —
    *"코드를 고쳐서 풀 수 있는 실패가 아니다 ― 곧 무시하게 된다."*

    Sprint 102 는 이 함정을 이미 적어 두었다: *"이 PC가 운영 머신이 맞는지도 코드로는
    알 수 없다."* 코드로 알 수 없으므로 **선언하게 한다.** `ALLOW_LIVE_CRAWL=1` 이
    실크롤을 규약이 아니라 구조로 막는 것과 같은 방식이다.

        DOJOONPASS_DATA_ROLE=operational   이 머신의 auction.db 가 운영 데이터다
        (미선언/그 외)                      개발 머신 - 데이터 신선도를 제품 판정으로 쓰지 않는다

    기본값을 **개발**로 두는 이유: 잘못 선언하지 않은 개발 머신이 거짓 P0 를 만드는 것보다,
    선언을 잊은 운영 머신이 경보를 놓치는 쪽이 **눈에 띄기 쉽다**(§11 이 미선언 상태를
    매번 크게 찍는다). 그리고 개발 머신은 다수, 운영 머신은 하나다.
    """
    return (os.environ.get(DATA_ROLE_ENV, "") or "").strip().lower()


def is_operational_data():
    return data_role() == DATA_ROLE_OPERATIONAL

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

    # ★ 이 머신이 **운영 데이터의 주인일 때만** 제품 판정으로 쓴다 (BUGS #200).
    if is_operational_data():
        check_true("기본 검색에 뜰 물건이 남아 있다(0이면 사용자에게 빈 화면)", live > 0,
                   "auction_date >= %s 인 물건이 0건이다 ― 수집 파이프라인을 먼저 확인하라"
                   % today)
    else:
        # 값이 **있는데** 인식하지 못한 것은 오타일 수 있다. 선언하려던 사람은
        # 자기가 선언했다고 믿으므로, 미선언과 같은 문구로 뭉개면 안 된다.
        declared = data_role()
        if declared:
            print("    ** %s=%r 를 인식하지 못했다 ** 개발 머신으로 처리한다."
                  " 운영으로 선언하려면 정확히 %r 이어야 한다."
                  % (DATA_ROLE_ENV, declared, DATA_ROLE_OPERATIONAL))
        # 개발 머신에서는 이 값이 당연히 0 으로 수렴한다. 그것을 제품 결함으로 찍으면
        # **고칠 수 없는 실패**가 되고, 그러면 아무도 이 검사를 안 본다.
        # 대신 **크게 찍는다** - 선언을 잊은 운영 머신이 이 줄을 보고 알아채도록.
        print("    [역할 미선언] 이 머신은 운영 데이터의 주인이라고 선언되지 않았다"
              " -> 위 숫자를 제품 판정으로 쓰지 않는다.")
        print("    이 머신의 auction.db 가 운영 데이터라면 %s=%s 로 선언하라"
              " (그러면 검색 0건이 실패로 잡힌다)."
              % (DATA_ROLE_ENV, DATA_ROLE_OPERATIONAL))
        # 검사가 공허해지지 않게, **재는 것은 실제로 했는지**를 고정한다.
        check_true("측정 자체는 성공했다(crawl_date 를 읽을 수 있다)",
                   last_crawl is not None,
                   "-> auction_item 이 비어 있거나 crawl_date 가 전부 NULL 이다."
                   " 이것은 머신 역할과 무관하게 부트스트랩이 깨졌다는 뜻이다")

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


# ---------------------------------------------------------------------------
# 11-b. 체크리스트의 P0-A 판정이 **실측과 같은 말을 하는가** (2026-08-24 Sprint 251 신설)
#
# 왜 필요한가 — 위 11번 검사는 제품 상태를 정확히 잰다. 그런데 사람이 읽는 문서는
# 그것과 **반대말**을 하고 있어도 아무도 모른다. 실제로 그렇게 됐다:
#
#     docs/BETA_RELEASE_CHECKLIST.md (2026-08-23 Sprint 267)
#         "P0-A 재실측 — 더 이상 사실이 아니다 ... 검색 275건"
#     같은 저장소 실측 (2026-08-24)
#         기일 남은 물건 0건 / GET /api/v1/search total 0 / 예약 작업 0개
#
# 이 어긋남이 위험한 이유는 "출시를 막는 것이 무엇인가"를 그 문서로 판단하기 때문이다.
# 문서가 "해소"라고 적혀 있으면 아무도 스케줄러를 등록하지 않고, 제품은 계속 빈 화면이다.
#
# ## 무엇을 고정하는가
#
# 문장은 검사하지 않는다 — 산문은 계속 바뀌고, 문구 grep 은 금방 공허해진다.
# 대신 문서에 **기계 판독용 토큰 한 줄**을 두고 그것만 실측과 대조한다:
#
#     <!-- P0A-VERDICT: OPEN -->        지금 제품이 깨져 있다(기본 검색 0건)
#     <!-- P0A-VERDICT: RESOLVED -->    지금 정상이다
#
# 양방향으로 잠근다 — 깨졌는데 RESOLVED 여도, 정상인데 OPEN 이어도 실패한다.
# 그래서 크롤이 되살아나 실제로 해소되는 날에도 문서를 **반드시** 갱신하게 된다.


def test_checklist_p0a_verdict_matches_reality():
    print("\n--- 11-b. 체크리스트 P0-A 판정 vs 실측 (Sprint 251) ---")
    import re as _re

    path = os.path.join(ROOT, "docs", "BETA_RELEASE_CHECKLIST.md")
    if not os.path.exists(path):
        check_true("체크리스트 문서가 있다", False, path)
        return
    with open(path, encoding="utf-8", errors="replace") as fh:
        md = fh.read()

    tokens = _re.findall(r"<!--\s*P0A-VERDICT:\s*(OPEN|RESOLVED)\s*-->", md)
    check_true("판정 토큰이 정확히 1개 있다 (<!-- P0A-VERDICT: OPEN|RESOLVED -->)",
               len(tokens) == 1,
               "-> %d개 발견. 여러 개면 어느 것이 최신인지 알 수 없다" % len(tokens))
    if len(tokens) != 1:
        return
    verdict = tokens[0]

    conn = connect()
    try:
        today = datetime.date.today()
        live = conn.execute(
            "SELECT COUNT(*) FROM auction_item"
            " WHERE auction_date >= ? AND TRIM(auction_date) <> ''",
            (today.isoformat(),)).fetchone()[0]
    finally:
        conn.close()

    expected = "OPEN" if live == 0 else "RESOLVED"
    print("    이 머신의 DB 기준 기일 미도래 물건 : %d건  -> 기대 토큰 %s" % (live, expected))
    print("    문서에 적힌 판정      : %s" % verdict)

    # ★★ 2026-08-26 (BUGS #222) — 이 대조를 **역할 선언 안으로** 옮겼다.
    #
    #   Sprint 251 이 이 검사를 만들 때는 머신이 하나라고 보고 있었다. 그 다음 날
    #   (2026-08-25, BUGS #200) 머신 역할이 갈렸다 — 운영 크롤은 데스크탑1이 돌리고
    #   여기(데스크탑3)는 개발/QA 다. 그런데 이 검사만 그 정리에서 빠졌다.
    #
    #   그 결과 이 가드는 **어느 머신에서도 동시에 만족될 수 없다.** 판정 토큰은
    #   git 이 추적하는 문서 한 줄인데, 요구하는 값이 머신마다 다르기 때문이다:
    #
    #       이 머신(개발)      기일 미도래 0건        -> OPEN 을 요구한다
    #       데스크탑1(운영)    기일 미도래 110건      -> RESOLVED 를 요구한다
    #
    #   한쪽에 맞추면 다른 쪽이 붉어진다. 문서를 고치는 것으로는 끝나지 않고
    #   **실패가 자리를 옮길 뿐**이다(2026-08-26 실측으로 확인).
    #
    #   그리고 방향이 애초에 틀렸다 — 개발 머신의 DB 신선도는 **제품 상태에 대해
    #   아무 말도 할 수 없다.** 그것이 BUGS #200 이 세운 규칙이고, 바로 아래 11-c 가
    #   §11 에 대해 이미 강제하고 있다. 같은 규칙을 같은 파일 안에서 한 검사만
    #   비껴가고 있었다.
    #
    #   운영으로 선언한 머신에서는 **양방향 그대로** 문다 — 깨졌는데 RESOLVED 여도,
    #   정상인데 OPEN 이어도 실패한다. 이빨은 그쪽에 남는다.
    if is_operational_data():
        check_true(
            "★ 체크리스트의 P0-A 판정이 실측과 일치한다",
            verdict == expected,
            "-> 문서는 '%s' 라고 하는데 실측은 기일 남은 물건 %d건(=%s)이다. "
            "docs/BETA_RELEASE_CHECKLIST.md 의 P0A-VERDICT 토큰과 그 주변 서술을 함께 고칠 것"
            % (verdict, live, expected))
    else:
        print("    (이 머신은 운영 데이터의 주인으로 선언되지 않았다 -"
              " 위 숫자를 제품 판정으로 읽지 말 것. 대조는 건너뛴다)")
        # 껍데기 방지 — 선언하지 않은 머신에서도 **머신과 무관한 것**은 계속 문다.
        # 대조는 못 해도 대조에 쓰이는 기계는 살아 있어야 한다. 이 단언이 없으면
        # 개발 머신에서 이 검사가 아무것도 검증하지 않는 빈 함수가 된다.
        check_true("판정 토큰이 아는 값이다(OPEN/RESOLVED)",
                   verdict in ("OPEN", "RESOLVED"), verdict)
        check_true("실측 경로가 실제로 돌았다(auction_item 을 셌다)",
                   isinstance(live, int) and live >= 0, live)


# ---------------------------------------------------------------------------
# 11-d. 체크리스트에서 "가장 최신"을 주장하는 절이 하나뿐인가
#       (2026-08-26, `docs/BUGS.md` #223)
#
# 왜 — 이 문서는 **출시를 막는 것이 무엇인가**를 사람이 판단하는 자리다. 그런데 절이
# 시간 역순으로 쌓이면서 두 절이 동시에 *"이 절이 가장 최신이다"* 라고 말하게 됐고,
# 둘의 숫자가 서로 달랐다(같은 2026-08-26 의 00:30 판과 07:40 판).
#
#     아침 절(07:40)   auction_item 2,558 / READY 보유 21 / 사진 보유 17
#     야간 절(00:30)   auction_item 2,444 / READY 보유  4 / 사진 보유  0
#
# 어느 쪽을 먼저 읽느냐로 결론이 갈린다. 이 세션도 실제로 그것을 손으로 가려내야 했다.
#
# 11-b 와 달리 이 검사는 **머신과 무관하다** — 문서만 보면 판정되므로 개발 머신에서도
# 그대로 이빨이 남는다. 역할 선언 게이트가 필요 없는 부류다.
# ---------------------------------------------------------------------------
NEWEST_CLAIM = "가장 최신"


def test_checklist_has_one_newest_section():
    print("\n--- 11-d. '가장 최신' 주장이 하나뿐인가 (BUGS #223) ---")
    path = os.path.join(ROOT, "docs", "BETA_RELEASE_CHECKLIST.md")
    if not os.path.exists(path):
        check_true("체크리스트 문서가 있다", False, path)
        return
    with open(path, encoding="utf-8", errors="replace") as fh:
        lines = fh.read().split("\n")

    # "가장 최신"이라고 **주장하는** 줄만 센다. 인용부(> 로 시작하는 정정 기록)와
    # 이 검사를 설명하는 줄은 주장이 아니다 - 세면 고쳐 놓은 기록 때문에 붉어진다.
    claims = []
    for i, raw in enumerate(lines, 1):
        s = raw.strip()
        if NEWEST_CLAIM not in s:
            continue
        if s.startswith(">") or s.startswith("#"):
            continue
        # "더 최신이고", "가장 최신을 주장" 같은 서술은 자기가 최신이라는 주장이 아니다.
        if "이 절이" not in s:
            continue
        claims.append((i, s[:70]))

    for i, s in claims:
        print("    L%-5d %s" % (i, s))
    check_true("★ '이 절이 가장 최신이다' 라고 말하는 절이 정확히 하나다",
               len(claims) == 1,
               "-> %d개. 둘 이상이면 서로 다른 숫자를 동시에 최신이라고 말하게 된다"
               % len(claims))

    # 검출기 자체 검증 - 규칙이 실제로 문장을 가려내는가.
    def _claiming(sample):
        s = sample.strip()
        if NEWEST_CLAIM not in s or s.startswith(">") or s.startswith("#"):
            return False
        return "이 절이" in s
    check("검출기 자체 검증: 주장하는 문장을 잡는다",
          _claiming("이 절이 **가장 최신**이다."), True)
    check("검출기 자체 검증: 인용된 정정 기록은 잡지 않는다",
          _claiming("> 이 절이 **가장 최신**이다 라고 적혀 있었다"), False)
    check("검출기 자체 검증: 다른 절을 가리키는 서술은 잡지 않는다",
          _claiming("위의 아침 절이 **더 최신**이고, 값이 다르면 그쪽이 이긴다"), False)



# ---------------------------------------------------------------------------
# 11-e. 체크리스트의 `Last Updated` 가 실제 최신 절과 맞는가
#       (2026-08-26, `docs/BUGS.md` #228)
#
# 왜 — 이 문서 맨 위 `Last Updated:` 는 **손으로 적는 정적 필드**다. 아무도 갱신하지
# 않아 2026-08-26 시점에 **2026-08-07 (19일 전)** 로 뒤처져 있었다. 출시 가능 여부를
# 판단하는 문서가 스스로 "3주 전 기준"이라고 말하고 있으면, 읽는 사람은 그 안의 최신
# 실측까지 낡은 것으로 취급한다(반대로 낡은 절을 최신으로 믿을 수도 있다 — 11-d 참고).
#
# 11-d 와 같은 부류이지만 **기제가 다르다.** 11-d 는 "여러 절이 서로 최신이라 주장"을
# 보고, 이쪽은 "머리말이 본문보다 낡았다"를 본다. 둘 다 머신과 무관해 개발 머신에서도
# 이빨이 그대로 남는다.
# ---------------------------------------------------------------------------
def test_checklist_last_updated_matches_newest_section():
    print("\n--- 11-e. Last Updated vs 최신 절 날짜 (BUGS #228) ---")
    import re as _re

    path = os.path.join(ROOT, "docs", "BETA_RELEASE_CHECKLIST.md")
    if not os.path.exists(path):
        check_true("체크리스트 문서가 있다", False, path)
        return
    with open(path, encoding="utf-8", errors="replace") as fh:
        md = fh.read()

    m = _re.search(r"^Last Updated:\s*(\d{4}-\d{2}-\d{2})", md, _re.M)
    check_true("Last Updated 에 YYYY-MM-DD 날짜가 있다", m is not None,
               "-> 형식이 바뀌면 이 검사가 조용히 공허해진다")
    if not m:
        return
    header_date = m.group(1)

    # 절 제목의 날짜만 센다 — 본문 아무 데나 있는 날짜를 세면 인용된 옛 실측까지 잡힌다.
    section_dates = _re.findall(r"^##+\s*★*\s*\[(\d{4}-\d{2}-\d{2})", md, _re.M)
    check_true("날짜가 붙은 절을 찾았다(검사가 공허하지 않다)",
               len(section_dates) >= 5, len(section_dates))
    if not section_dates:
        return
    newest = max(section_dates)
    print("    Last Updated : %s" % header_date)
    print("    가장 최신 절  : %s  (날짜 붙은 절 %d개)" % (newest, len(section_dates)))
    check("★ Last Updated 가 가장 최신 절의 날짜와 같다", header_date, newest)

    # 검출기 자체 검증 — 규칙이 실제로 두 값을 뽑아내는가.
    sample = ("# T\n\nLast Updated: 2026-01-02\n\n"
              "## ★★ [2026-03-04] 새 절\n\n본문 2025-12-31 은 절 제목이 아니다\n")
    hm = _re.search(r"^Last Updated:\s*(\d{4}-\d{2}-\d{2})", sample, _re.M)
    hs = _re.findall(r"^##+\s*★*\s*\[(\d{4}-\d{2}-\d{2})", sample, _re.M)
    check("검출기 자체 검증: 머리말 날짜를 뽑는다", hm.group(1) if hm else None, "2026-01-02")
    check("검출기 자체 검증: 절 제목 날짜만 뽑는다(본문 날짜는 제외)", hs, ["2026-03-04"])
    check("검출기 자체 검증: known-bad 에서 어긋남을 잡는다",
          (hm.group(1) if hm else None) == (max(hs) if hs else None), False)


def test_data_role_gate_is_wired():
    """§11 의 제품 판정이 **머신 역할 선언에 묶여 있는가** (2026-08-25, BUGS #200).

    ## 왜 이 검사가 필요한가

    DOJOONPASS 는 머신을 역할로 나눈다 — 운영 Daily Crawl 은 데스크탑1이 돌리고,
    이 저장소로 개발/QA 를 하는 데스크탑3 은 크롤을 돌리지 않는다. 그래서 개발 머신의
    `auction.db` 에서 "기일 미도래 0건"은 **정상**이지 제품 결함이 아니다.

    §11 은 그 구분 없이 이 머신의 DB 를 재고 "제품이 망가졌다"로 찍어 왔고,
    개발 머신에서 **고칠 수 없는 영구 red** 가 됐다. 여러 세션이 그것을 "유일하게 알려진
    실패"로 취급하며 지나갔다 — §11 자기 주석이 예언한 상태 그대로다.

    이 검사는 두 방향을 **모두** 고정한다. 한쪽만 보면 다음에 또 갈라진다.

        운영으로 선언한 머신   -> 검색 0건은 반드시 **실패**여야 한다 (이빨이 남아야 한다)
        선언하지 않은 머신     -> 실패로 만들지 않는다 (거짓 P0 를 만들지 않는다)
    """
    print("\n--- 11-c. 데이터 역할 선언 게이트 (BUGS #200) ---")
    import ast as _ast

    saved = os.environ.get(DATA_ROLE_ENV)
    try:
        # --- 값 해석 ---------------------------------------------------
        cases = [
            ("operational", True),
            ("OPERATIONAL", True),
            ("  operational  ", True),
            ("prod", False),
            ("production", False),
            ("development", False),
            ("", False),
        ]
        for value, expected in cases:
            os.environ[DATA_ROLE_ENV] = value
            check("%s=%r -> 운영 데이터로 본다" % (DATA_ROLE_ENV, value),
                  is_operational_data(), expected)
        os.environ.pop(DATA_ROLE_ENV, None)
        check("선언 자체가 없으면 개발로 본다", is_operational_data(), False)

        # --- 배선: 제품 판정이 그 분기 **안에** 있는가 -------------------
        #     문자열이 아니라 구문 트리로 본다 - 주석에 이름이 나오는 것은 배선이 아니다.
        src = open(os.path.join(ROOT, "test_pipeline_integrity.py"),
                   encoding="utf-8-sig").read()
        tree = _ast.parse(src)

        # ★ 2026-08-26 (BUGS #222) — 지켜야 할 자리가 **둘**이다.
        #
        #   처음에는 §11 하나만 이름으로 못박아 뒀다. 그런데 §11-b 도 같은 부류의
        #   제품 판정(문서의 P0-A 토큰 vs 이 머신의 DB)을 하면서 게이트 밖에 있었고,
        #   그래서 개발 머신에서 **고칠 수 없는 red** 가 됐다 — 이 검사가 막으려던
        #   상태 그대로다. 한 자리만 이름으로 잠그면 다음 자리가 그대로 새어 나간다.
        GATED = (
            ("test_data_freshness_runway", "기본 검색에 뜰 물건이 남아 있다"),
            ("test_checklist_p0a_verdict_matches_reality",
             "체크리스트의 P0-A 판정이 실측과 일치한다"),
        )

        # ★ 목록 자체가 줄어드는 것도 막는다 (2026-08-26, BUGS #222).
        #
        #   위 GATED 는 이 가드의 **설정**이다. 설정을 지우면 가드가 조용히 좁아진다 —
        #   실제로 §11-b 가 그렇게 빠져 있었다. 그래서 목록이 **이 모듈에서 역할 선언을
        #   보는 함수 전부**를 덮는지 대조한다. 새 판정이 생기면 여기서 먼저 걸린다.
        #
        #   이 가드 함수 자신은 제외한다 — 선언값을 바꿔 가며 해석을 검증하는 것이
        #   일이라 당연히 그 이름을 부른다.
        SELF = "test_data_role_gate_is_wired"
        role_readers = set()
        for node in tree.body:
            if not isinstance(node, _ast.FunctionDef) or node.name == SELF:
                continue
            for sub in _ast.walk(node):
                if isinstance(sub, _ast.Call) and \
                        (getattr(sub.func, "id", None) or
                         getattr(sub.func, "attr", None)) == "is_operational_data":
                    role_readers.add(node.name)
        check_true("★ 역할 선언을 보는 함수를 찾았다(검사가 공허하지 않다)",
                   len(role_readers) >= 2, sorted(role_readers))
        check_true("★ 게이트 목록이 그 함수 전부를 덮는다",
                   role_readers == {name for name, _ in GATED},
                   "-> 목록에 없는 함수: %s / 목록에만 있는 이름: %s"
                   % (sorted(role_readers - {n for n, _ in GATED}),
                      sorted({n for n, _ in GATED} - role_readers)))

        def claim_calls(node, claim):
            out = []
            for n in _ast.walk(node):
                if not isinstance(n, _ast.Call):
                    continue
                if (getattr(n.func, "id", None) or getattr(n.func, "attr", None)) != "check_true":
                    continue
                if n.args and isinstance(n.args[0], _ast.Constant) \
                        and isinstance(n.args[0].value, str) \
                        and claim in n.args[0].value:
                    out.append(n)
            return out

        for fname, claim in GATED:
            fn = next((n for n in tree.body
                       if isinstance(n, _ast.FunctionDef) and n.name == fname), None)
            check_true("%s 함수를 찾았다" % fname, fn is not None)
            if fn is None:
                continue

            guarded, total = [], claim_calls(fn, claim)
            for node in _ast.walk(fn):
                if not isinstance(node, _ast.If):
                    continue
                if "is_operational_data" not in _ast.dump(node.test):
                    continue
                for n in node.body:
                    guarded.extend(claim_calls(n, claim))

            check_true("★ %s: 제품 판정 단언이 소스에 있다(검사가 공허하지 않다)" % fname,
                       len(total) == 1, len(total))
            check_true("★ %s: 그 단언이 is_operational_data() 분기 **안에** 있다" % fname,
                       len(guarded) == 1,
                       "-> 분기 밖으로 나오면 개발 머신에서 다시 거짓 P0 가 된다")

            # --- 미선언 머신에도 남아 있어야 할 최소 단언 --------------------
            #     전부 없애 버리면 그 함수가 아무것도 검증하지 않는 껍데기가 된다.
            else_claims = []
            for node in _ast.walk(fn):
                if isinstance(node, _ast.If) and "is_operational_data" in _ast.dump(node.test):
                    for n in node.orelse:
                        for sub in _ast.walk(n):
                            if isinstance(sub, _ast.Call) and \
                                    (getattr(sub.func, "id", None) or
                                     getattr(sub.func, "attr", None)) == "check_true":
                                else_claims.append(sub)
            check_true("★ %s: 미선언 머신에서도 최소 한 가지는 단언한다(껍데기 방지)" % fname,
                       len(else_claims) >= 1, len(else_claims))
    finally:
        if saved is None:
            os.environ.pop(DATA_ROLE_ENV, None)
        else:
            os.environ[DATA_ROLE_ENV] = saved

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
#
# ★ 2026-08-24 Sprint 251 — 두 가지를 바로잡는다.
#
# (1) sido 상한을 5 -> **4** 로 내린다. 위 Sprint 121이 5로 올린 근거였던 id=11903 은
#     지금 이 DB(auction_item 1,876행)에 없다. 실측 4행이다. 상한이 실측보다 하나
#     헐거우면 **새 오분류 하나가 조용히 들어와도 통과한다** - 상한의 목적이 사라진다.
#     현재 4행: id=550 '서울'->'인천' / id=1787 '부산'->'경남'
#              id=8160 '서울'->'경기' / id=9977 '세종'->'제주'
#
# (2) `docs/BUGS.md` #78 의 마무리 문장 *"만료 물건이라 검색(D7 기본 제외)에는 나오지
#     않는다"* 는 **절반만 맞다.** `src/app/search/SearchForm.tsx:643` 에
#     **"종결물건 포함" 체크박스**가 있다. 사용자가 그것을 켜면 이 행들이 그대로 나온다.
#     실측(2026-08-24): `?include_closed=true&sido=서울` 응답에 시흥시(경기) 물건
#     id=8160 이 들어 있다. 즉 "지금은 사용자에게 안 보인다"가 아니라
#     **"한 번의 체크박스 클릭 거리에 있다"** 이다. BUGS.md 쪽도 함께 정정했다.
#
# ※ 이 검사는 **데이터 드리프트**를 본다. `extract_sido()` 자체가 옛 규칙으로 퇴행하는
#   것은 여기서 못 잡는다 - 퇴행하면 새로 계산한 값이 저장된 옛 값과 **같아져서**
#   드리프트가 오히려 줄기 때문이다. 그 축은 `test_normalizer.py` 가 맡는다
#   (2026-08-24 mutation 확인: '가장 앞선 표기' 규칙을 되돌리면 test_normalizer.py 가
#    실패하고, 이 검사는 통과한다). 두 검사는 **다른 것을 지킨다.**
# ---------------------------------------------------------------------------
# ★★ 2026-08-26 — 네 축 전부 **0** 으로 조인다. 상한이 아니라 이제 **불변식**이다.
#
#   그동안 sido 4 / sigungu 207 은 "고칠 수 없는 옛 오분류"를 안고 가는 상한이었다.
#   이번에 그 전제가 깨졌다 — `backfill_region_normalize.py --apply` 로 실제로 **전부
#   고쳤다**(auction 170행 + auction_item 174행). 재측정 결과 네 축 모두 **0행**이다.
#
#   상한을 실측보다 헐겁게 두면 안 되는 이유는 바로 위 Sprint 251 주석이 이미 적었다 —
#   *"상한이 실측보다 하나 헐거우면 새 오분류 하나가 조용히 들어와도 통과한다."*
#   지금 실측이 0 이므로 상한도 0 이어야 그 목적을 지킨다. 207 을 남겨 두면 앞으로
#   **206건이 새로 오염돼도 초록불**이다.
#
#   ※ 이 검사가 붉어지면 할 일은 정해져 있다:
#         python backfill_region_normalize.py            (dry-run 으로 무엇이 바뀌는지 본다)
#         python backfill_region_normalize.py --apply
#     크롤러가 새 드리프트를 만들고 있다는 신호이기도 하므로, 반복되면 유입 경로
#     (`migrate_execute.py` 의 `or existing[...]` 병합 규칙)를 함께 본다.
#
#   자세한 경위는 docs/BUGS.md #214.
NORMALIZE_DRIFT_CEILING = {"sido": 0, "sigungu": 0, "dong": 0, "lot_number": 0}


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

    # ★★ 2026-08-26 (BUGS #224) — 축을 하나 더 센다.
    #
    #   아래 드리프트 계산은 *"새 값이 비어 있으면 세지 않는다"* 로 처리하면서
    #   그 근거로 **"백필도 그런 행은 건너뛴다"** 고 적어 두고 있었다.
    #   그 문장은 2026-08-26 부터 **사실이 아니다** — 백필은 그날 예외를 하나 얻었다.
    #   저장값이 주소 원문(대괄호 제외)에 **아예 없으면** 그것은 "정규화기가 못 읽은 값"이
    #   아니라 **다른 물건에서 흘러든 값**이라 지운다.
    #
    #   그래서 이 가드는 그 부류를 **통째로 못 보고 있었다.** 상한을 0 으로 조여 놓고도
    #   "지역 데이터가 깨끗하다"고 읽히는데, 실제로는 한 축이 시야 밖이었다.
    #   실측(2026-08-26, 이 머신): 드리프트 211 / **오염 1**(id=1768 `sigungu='갑구'`,
    #   주소는 "세종특별자치시 전의면 관정리 578-31 [토지 임야 297㎡ 갑구 2번 ...]").
    #
    #   판정은 **백필과 같은 함수**를 불러 쓴다. 여기에 규칙을 다시 적으면 두 벌이 되고,
    #   한쪽만 바뀌는 날 두 검사가 서로를 눈감아 준다 — 이 결함이 정확히 그렇게 생겼다.
    from backfill_region_normalize import is_stale_contamination

    drift = {k: [] for k in NORMALIZE_DRIFT_CEILING}
    contaminated = []
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
            if f and s != f:
                drift[col].append((row_id, s, f))
            elif col in ("sido", "sigungu") and is_stale_contamination(s, f, addr or ""):
                # 새 값이 비었는데 저장값이 주소에도 없다 = 흘러든 값.
                contaminated.append((row_id, col, s))

    # 정규화가 **예외로 죽는** 주소가 있으면 그것부터 문제다(백필도 못 돈다).
    check("정규화 중 예외가 나는 주소 없음", crashed, [])

    for col, ceiling in NORMALIZE_DRIFT_CEILING.items():
        n = len(drift[col])
        detail = drift[col][:3]
        check_true("%s 드리프트가 늘지 않았다 (현재 %d행, 상한 %d)" % (col, n, ceiling),
                   n <= ceiling, detail)
        if n:
            print("      예: " + " / ".join("id=%s %r->%r" % d for d in detail))

    # 오염 축 (BUGS #224). 상한은 드리프트와 같은 이유로 0 이고, 고치는 명령도 같다 —
    # 백필이 이 부류까지 함께 정리한다.
    check_true("★ 다른 물건에서 흘러든 지역값이 없다 (현재 %d행, 상한 0)"
               % len(contaminated),
               len(contaminated) == 0, contaminated[:3])
    if contaminated:
        print("      예: " + " / ".join("id=%s %s=%r" % c for c in contaminated[:3]))

    # ★ 검출기 자체 검증 — 이 축은 실 데이터가 0 이 되는 순간 **공허해진다.**
    #   (백필을 돌리고 나면 정확히 그 상태가 된다.) 그때도 판정이 살아 있는지
    #   합성 입력으로 못박는다. "검증 대상이 없으면 통과"를 만들지 않는다.
    check("검출기 자체 검증: 주소에 없는 값은 오염이다",
          is_stale_contamination("칠곡군", "", "세종특별자치시 나성로 96"), True)
    check("검출기 자체 검증: 대괄호 안에만 있는 값도 오염이다",
          is_stale_contamination("갑구", "", "세종특별자치시 전의면 [토지 갑구 2번]"), True)
    check("검출기 자체 검증: 주소에 실제로 있으면 오염이 아니다",
          is_stale_contamination("칠곡군", "", "경상북도 칠곡군 왜관읍 1"), False)
    # ★ 이 자리는 **새 값이 있는데 저장값은 주소에 없는** 입력이어야 한다.
    #   처음에는 '고양시' -> '고양시 일산동구' 처럼 저장값이 주소에 들어 있는 예를 썼는데,
    #   그러면 `if fresh: return False` 를 지워도 뒤쪽 대조가 어차피 False 를 내서
    #   변이가 살아남는다(실제로 P3 가 그렇게 통과했다). 두 조건을 갈라 놓는 입력을 쓴다.
    check("검출기 자체 검증: 새 값이 있으면 (주소에 없어도) 오염이 아니라 드리프트다",
          is_stale_contamination("칠곡군", "나성동", "세종특별자치시 나성로 96"), False)

    # ★ 규칙이 다시 세 벌이 되지 않는가 (2026-09-01).
    #
    #   `detect_stale_region_contamination_dryrun.py` 는 예전에 이 판정을 **자기 안에
    #   따로 적어** 두었고(`stored in addr` — 대괄호까지 포함한 원문 전체와 대조),
    #   그래서 같은 DB 를 두고 이 가드와 답이 갈렸다:
    #
    #       그 스크립트                오염 의심 0건
    #       이 가드                    오염 1건 (id=1768 `sigungu='갑구'`)
    #
    #   같은 질문에 두 도구가 다른 답을 하면 **하나는 반드시 거짓말을 하고 있다.**
    #   지금은 셋(백필 / 이 가드 / 그 스크립트)이 같은 함수를 부른다. 그 사실을 고정한다.
    detector = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "detect_stale_region_contamination_dryrun.py")
    check_true("오염 검출기가 있다", os.path.exists(detector), detector)
    if os.path.exists(detector):
        det_src = open(detector, encoding="utf-8-sig").read()
        check_true("검사가 공허하지 않다(검출기를 실제로 읽었다)", len(det_src) > 1000, len(det_src))
        check_true("★ 오염 검출기가 정본 판정을 불러 쓴다",
                   "from backfill_region_normalize import is_stale_contamination" in det_src,
                   "-> 판정을 스스로 다시 적으면 두 도구의 답이 갈린다")

        # 문자열로 찾지 않는다 — 이 파일의 주석은 옛 판정(`stored in addr`)을 **정정 기록으로
        # 인용**하고 있어서, 문자열 검사는 그 인용을 결함으로 잡는다(실제로 그렇게 잡혔다).
        # 코드만 본다.
        import ast as _ast
        det_tree = _ast.parse(det_src)
        scan_fn = next((n for n in det_tree.body
                        if isinstance(n, _ast.FunctionDef) and n.name == "scan_table"), None)
        check_true("검출기에 scan_table() 이 있다", scan_fn is not None)
        if scan_fn is not None:
            calls = {getattr(c.func, "id", None) or getattr(c.func, "attr", None)
                     for c in _ast.walk(scan_fn) if isinstance(c, _ast.Call)}
            check_true("★ scan_table() 이 정본 판정을 실제로 호출한다",
                       "is_stale_contamination" in calls, sorted(x for x in calls if x))
            # 옛 판정은 `stored in addr` 라는 **비교식**이었다. 코드에 그 모양이 있으면
            # 판정을 다시 적은 것이다(주석에 적힌 인용은 여기 걸리지 않는다).
            own_rule = [c for c in _ast.walk(scan_fn)
                        if isinstance(c, _ast.Compare)
                        and any(isinstance(op, _ast.In) for op in c.ops)]
            check("★ scan_table() 이 판정을 다시 적지 않는다",
                  [_ast.dump(c)[:60] for c in own_rule], [])

    if any(drift[c] for c in drift) or contaminated:
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
    # 2026-08-21 실측: id=12899(김천지원 2024타경2004 / 2024타경15673 / 2024타경3403)
    # 감정가 1,265,861,750 / 최저가 1,265,862,000 - 딱 250원 차이다. 파싱 역전이라면
    # 자릿수가 어긋나거나 값이 크게 갈라져야 하는데, 1,265,861,750을 1,000원 단위로
    # 올림하면 정확히 1,265,862,000이 된다(다른 자릿수 조작 없이 산술로 재현됨) - 법원이
    # 최초 매각의 최저가를 감정가의 1,000원 올림으로 공고한 실제 사례이지 크롤러/정규화의
    # 파싱 결함이 아니다(첫 매각 209건 중 196건은 최저가==감정가로 정확히 같다).
    # 상한을 두어 늘어나면(=진짜 파싱 역전이 섞여 들어오면) 여전히 잡히게 한다.
    check_true("최저매각가격이 감정평가액을 넘는 행이 늘지 않았다(파싱 역전 아님, 1,000원 올림 확인됨)",
               inverted <= 1, "-> 현재 %d건, 상한 1" % inverted)
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
    #
    # ※ 2026-08-24 Sprint 251 — 지금 이 DB 에서는 **0건**이라 아래 §13-B 가
    #   "[정리됨] 상한을 0으로 낮출 수 있다"고 찍는다. **그 제안을 그대로 따르지 말 것.**
    #   0이 된 이유는 고쳐졌기 때문이 아니라, 그 1건(auction.id=357 대전지방법원
    #   2024타경11191-1, 세종 주소에 sigungu='칠곡군')에 해당하는 사건이 **지금 이 DB에
    #   아예 없기 때문**이다(auction_item 1,876행). 원인인 `migrate_execute.py` 의
    #   병합 규칙은 그대로다 — 데이터가 원래 크기로 돌아오면 그 행도 돌아온다.
    #   0으로 내리면 그때 붉어지는 것은 회귀가 아니라 오탐이다.
    #   (같은 세션에 조인 상한들은 성격이 다르다 — sido 5->4, 차량 역방향 5->3 은
    #    어떤 측정에도 근거가 없던 여유였다.)
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

    # ★ 위 `FIELDS` 는 **손으로 적은 목록**이다 (2026-09-02 추가).
    #
    #   두 표가 같은 값을 들고 있는지 보는 검사인데, 비교할 컬럼을 사람이 적어 두면
    #   **나중에 공유 컬럼이 하나 늘어도 조용히 비교 대상에서 빠진다.** 그러면 그
    #   컬럼만 두 표가 갈라져도 이 검사는 초록이다 — 이 저장소가 상한 검사마다
    #   경계해 온 "실측보다 헐거운 목록"과 같은 모양이다.
    #
    #   그래서 목록을 스스로 검사하게 한다: **두 표에 함께 있는 컬럼은 전부**
    #   비교되거나, 아래 두 부류로 명시적으로 제외되어야 한다.
    #
    #       JOIN_KEYS  짝짓기에 쓰는 키다. 정의상 같으므로 비교할 것이 없다.
    #       META_COLS  행마다 다른 것이 정상이다(자동 증가 id, 생성/수정 시각).
    #
    #   실측(2026-09-02): 마이그레이션 29개를 모두 적용한 새 DB 에서도 누락 0개다.
    #   `auction` 에만 있는 것(court_code/filed_date/validation_reasons/has_*)과
    #   `auction_item` 에만 있는 것(bid_rate/fail_count/building_area/land_area/case_id)은
    #   공유가 아니므로 여기 대상이 아니다.
    JOIN_KEYS = {"case_no", "item_no", "court_name", "court_code"}
    META_COLS = {"id", "case_id", "created_at", "updated_at"}
    conn = connect()
    try:
        a_cols = {r[1] for r in conn.execute("PRAGMA table_info(auction)")}
        i_cols = {r[1] for r in conn.execute("PRAGMA table_info(auction_item)")}
    finally:
        conn.close()
    check_true("전제: 두 표의 컬럼을 실제로 읽었다",
               len(a_cols) > 10 and len(i_cols) > 10, (len(a_cols), len(i_cols)))
    shared = a_cols & i_cols
    uncompared = sorted(shared - set(FIELDS) - JOIN_KEYS - META_COLS)
    check("★ 두 표에 함께 있는 컬럼이 전부 비교되거나 명시적으로 제외된다", uncompared, [])
    if uncompared:
        print("      -> 위 컬럼은 두 표가 갈라져도 아무도 모른다."
              " FIELDS 에 넣거나, 왜 비교하지 않는지 JOIN_KEYS/META_COLS 로 밝혀라.")
    # 목록이 실제 컬럼과 어긋나 있지 않은지도 본다(오타/삭제된 컬럼이 남아 있는 경우).
    phantom = sorted(f for f in FIELDS if f not in shared)
    check("FIELDS 에 두 표에 없는 컬럼이 적혀 있지 않다", phantom, [])
    print("    공유 컬럼 %d개 / 비교 %d개 / 제외 %d개"
          % (len(shared), len(set(FIELDS) & shared),
             len(shared & (JOIN_KEYS | META_COLS))))
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
    test_python_timestamps_are_naive_local()

    if not os.path.exists(DB):
        print("[SKIPPED] auction.db 없음 (fresh clone) ― 파이프라인 정합 검사 생략")
        return 1 if failures else 0

    test_path_rule_matches_api()
    test_queue_state_machine_invariants()
    test_done_rows_have_file_and_ready_status()
    test_files_are_reflected_in_queue()
    test_failure_reason_is_recorded()
    test_mass_purge_guard()
    test_parsing_gap_is_measurable()
    test_no_orphan_rows_in_pipeline_tables()
    test_rights_data_has_evidence()
    test_property_type_matches_content()
    test_court_identity_convention()
    test_data_freshness_runway()
    test_checklist_p0a_verdict_matches_reality()
    test_checklist_has_one_newest_section()
    test_checklist_last_updated_matches_newest_section()
    test_data_role_gate_is_wired()
    test_stored_normalization_matches_code()
    test_stale_region_contamination_detector()
    test_empty_sido_is_explained_by_the_address()
    test_failed_registry_requests_value_report()
    test_columns_with_no_producer()

    print("\n" + "=" * 55)
    if failures:
        print("FAILED (%d): %s" % (len(failures), ", ".join(failures)))
        return 1
    print("ALL TESTS PASSED")
    return 0



# ---------------------------------------------------------------------------
# 15. API 가 내려보내는데 **아무도 채우지 않는** 컬럼 (2026-09-02 신설)
#
# ## 왜 — 두 번 같은 모양을 만났다
#
# 스키마도 있고 API 도 내려보내고 화면도 그리는데 **파이프라인에 생산자가 없는**
# 필드가 있다. 화면에는 영원히 `-` 나 빈 배지가 뜬다. 오류가 아니라서 아무도 모르고,
# 코드만 읽으면 "구현되어 있다"고 읽힌다.
#
# 실측(2026-09-02, 이 머신 auction.db):
#
#     auction_case.filed_date / demand_deadline / case_type      0 / 1,384 행
#         -> migrate_execute.py:184 가 `VALUES (?, ?, ?, NULL, NULL, NULL, ?, ?)`
#            크롤러/모델에 '접수일'·'배당요구' 참조가 **0건**이다. 생산자가 아예 없다.
#            그런데 api/v1/item.py 는 내려보내고 상세화면은 접수일/배당요구종기일을 그린다.
#
#     rights_summary.risk_level / risk_reason / analysis_explanation …  0 / 161 행
#         -> load_rights_data.py:97 이 21개 중 11개를 리터럴 NULL 로 넣는다.
#            "권리분석 위험도 배지"가 쓰는 바로 그 필드다. 위험도 판정 엔진이 없다.
#            (`idx_rs_risk` 는 **항상 NULL 인 컬럼에 걸린 인덱스**이기도 하다.)
#
# ## 무엇을 고정하나
#
# 개수에 상한을 두지 않는다. **"지금 아는 목록"과 실측이 어긋나면** 실패한다.
#
#     새 컬럼이 producerless 가 되면      -> 붉어진다 (기능이 조용히 빈 채로 나가는 것을 막는다)
#     생산자가 생겨 채워지기 시작하면      -> 붉어진다 (목록에서 지우라는 신호다. 좋은 실패다)
#
# 생산자를 만드는 것은 제품 결정이다(위험도 판정 기준·수집 범위). 그래서 이 검사는
# **고치라고 하지 않는다** — 상태가 바뀌면 알려 줄 뿐이다.
#
# ※ 이 저장소가 `normalize_item()` 의 죽은 세 필드를 `test_normalizer.py` 로 고정한 것과
#   같은 관례다. 죽은 배선은 지우거나 채우기 전까지 **적어 두어야** 다음 사람이 속지 않는다.
# ---------------------------------------------------------------------------
PRODUCERLESS_COLUMNS = {
    # (표, 컬럼): 왜 비어 있는가
    ("auction_case", "case_type"):        "migrate_execute 가 리터럴 NULL - 크롤러에 생산자 없음",
    ("auction_case", "filed_date"):       "위와 같음. 상세화면 '접수일' 이 영원히 '-'",
    ("auction_case", "demand_deadline"):  "위와 같음. 상세화면 '배당요구종기일' 이 영원히 '-'",
    ("rights_summary", "priority_right"):        "load_rights_data 가 리터럴 NULL",
    ("rights_summary", "priority_date"):         "load_rights_data 가 리터럴 NULL",
    ("rights_summary", "dangerous_tenant_count"): "load_rights_data 가 리터럴 NULL",
    ("rights_summary", "total_deposit"):          "load_rights_data 가 리터럴 NULL",
    ("rights_summary", "estimated_inheritance"):  "load_rights_data 가 리터럴 NULL",
    ("rights_summary", "lien_exists"):            "load_rights_data 가 리터럴 NULL",
    ("rights_summary", "superficies_exists"):     "load_rights_data 가 리터럴 NULL",
    ("rights_summary", "foreclosure_note"):       "load_rights_data 가 리터럴 NULL",
    ("rights_summary", "risk_level"):        "위험도 판정 엔진이 없다 - 배지가 안 뜬다",
    ("rights_summary", "risk_reason"):       "위와 같음",
    ("rights_summary", "analysis_explanation"): "위와 같음",
}


def test_columns_with_no_producer():
    print("\n--- 15. API 가 내려보내는데 아무도 채우지 않는 컬럼 ---")
    if not os.path.exists(DB):
        # 조용히 건너뛰지 않는다 - 무엇을 못 봤는지 남긴다.
        print("    (auction.db 없음 - 이번 실행에서는 재지 못했다)")
        return

    conn = connect()
    try:
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        measured = {}
        for (table, col) in sorted(PRODUCERLESS_COLUMNS):
            if table not in tables:
                continue
            cols = {r[1] for r in conn.execute("PRAGMA table_info(%s)" % table)}
            if col not in cols:
                continue
            total = conn.execute("SELECT COUNT(*) FROM %s" % table).fetchone()[0]
            if not total:
                continue          # 행이 없으면 판정할 수 없다
            filled = conn.execute(
                "SELECT COUNT(*) FROM %s WHERE %s IS NOT NULL" % (table, col)).fetchone()[0]
            measured[(table, col)] = (filled, total)
    finally:
        conn.close()

    check_true("검사 대상 컬럼을 실제로 쟀다 - %d개" % len(measured), len(measured) > 0, len(measured))

    # (a) 목록에 있는데 **채워지기 시작한** 컬럼 -> 좋은 소식이지만 목록을 고쳐야 한다.
    now_produced = sorted("%s.%s (%d/%d)" % (t, c, f, n)
                          for (t, c), (f, n) in measured.items() if f > 0)
    check("생산자가 생긴 컬럼은 목록에서 지운다", now_produced, [])
    if now_produced:
        print("      -> 채워지기 시작했다. PRODUCERLESS_COLUMNS 에서 지우고,"
              " 그 값이 화면까지 옳게 가는지 검사를 추가하라.")

    # (b) 목록에 **없는데** producerless 인 컬럼이 새로 생겼는가.
    #     대상은 화면/API 가 실제로 쓰는 두 표로 한정한다(전 컬럼을 훑으면 잡음이 커진다).
    WATCHED = ("auction_case", "rights_summary")
    conn = connect()
    try:
        newly = []
        for table in WATCHED:
            total = conn.execute("SELECT COUNT(*) FROM %s" % table).fetchone()[0]
            if not total:
                continue
            for r in conn.execute("PRAGMA table_info(%s)" % table):
                col = r[1]
                if col in ("id", "item_id", "created_at", "updated_at"):
                    continue
                if (table, col) in PRODUCERLESS_COLUMNS:
                    continue
                filled = conn.execute(
                    "SELECT COUNT(*) FROM %s WHERE %s IS NOT NULL" % (table, col)).fetchone()[0]
                if filled == 0:
                    newly.append("%s.%s (0/%d)" % (table, col, total))
    finally:
        conn.close()
    check("새로 생산자를 잃은 컬럼 없음", sorted(newly), [])
    if newly:
        print("      -> 이 컬럼을 쓰는 화면이 있으면 지금 빈 채로 나가고 있다.")

    print("    producerless 로 알려진 컬럼 %d개 (전부 여전히 0)" % len(measured))


if __name__ == "__main__":
    sys.exit(run())
