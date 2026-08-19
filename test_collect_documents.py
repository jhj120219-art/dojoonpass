"""collect_documents.py의 저장/실패 경로 회귀 테스트 (2026-08-12 Sprint 67 신설).

이 스크립트는 `docs/roadmap.md` 16-A가 **배치 편입 대상으로 올려 둔** 코드인데,
지금까지 실행된 적이 없어(`doc_raw` 0행) 저장·실패 경로가 한 번도 검증되지 않았다.
Sprint 66에서 경로 결함 2건(BUGS #64)을 고쳤지만, 그때 검증한 것은 경로 계산과
파일 이동까지였고 **DB 기록 쪽(성공/실패 상태 전이)은 여전히 미검증**이었다.

selenium 없이 실행된다 — 브라우저가 필요한 `download_doc()`은 대상이 아니고,
그 뒤의 `finalize_download()` / `save_doc_raw()` / `save_failure()`만 직접 호출한다.
실제 `auction.db` / `documents/`는 건드리지 않는다(임시 DB + 임시 문서 루트).

    python test_collect_documents.py
"""
import contextlib
import io
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

ROOT = os.path.dirname(os.path.abspath(__file__))
MIGRATIONS = os.path.join(ROOT, "storage", "migrations")

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


class Env:
    """임시 DB + 임시 documents 루트. 스키마는 실제 마이그레이션 코드로 만든다."""

    def __init__(self):
        self.dir = tempfile.mkdtemp(prefix="qa_collect_")
        self.docs = os.path.join(self.dir, "documents")
        os.makedirs(self.docs)

        import storage.database as dbmod
        import crawler.doc_paths as dp
        self.dbmod, self.dp = dbmod, dp
        self._db_orig, self._docs_orig = dbmod.DB_PATH, dp.DOCUMENT_ROOT
        dbmod.DB_PATH = os.path.join(self.dir, "t.db")
        dp.DOCUMENT_ROOT = self.docs

        # 스키마는 **실제 부트스트랩 절차 그대로** 만든다(docs/CLAUDE.md 참고).
        #   init_db()          legacy auction / document_queue / document_version_log
        #   migrate_v4_1()     auction_case / auction_item / document_status / doc_raw ...
        #   run_migrations()   번호 붙은 SQL 전체(011의 auction_case.court_code,
        #                      017의 document_collect_failures, 018의 큐 UNIQUE 등)
        # 테스트 안에 스키마를 손으로 베끼거나 필요한 마이그레이션만 골라 적용하면
        # 진짜 스키마가 바뀌어도 통과한다 — 실제로 011을 빠뜨려 `ac.court_code` 없음으로
        # 깨진 적이 있다(2026-08-12 Sprint 67).
        import storage.migrate_v4_1 as mig
        import storage.migrations.run_migrations as runmig
        with contextlib.redirect_stdout(io.StringIO()):
            dbmod.init_db()
            mig.migrate()
            runmig.run()

    def enqueue(self, court, case_no, item_no, doc_type="spec"):
        """`enqueue_documents()`와 같은 형태로 큐에 한 건 넣는다."""
        c = self.conn()
        try:
            qid = c.execute(
                "INSERT INTO document_queue (court_code, case_no, item_no, doc_type, priority,"
                " auction_date, status, retry_count, enqueued_at)"
                " VALUES (?,?,?,?,1,'2099-01-01','pending',0,'2026-08-12T00:00:00')",
                (court, case_no, item_no, doc_type)).lastrowid
            c.commit()
            return qid
        finally:
            c.close()

    def queue_status(self, qid):
        c = self.conn()
        try:
            row = c.execute("SELECT status, retry_count FROM document_queue WHERE id=?",
                            (qid,)).fetchone()
            return (row["status"], row["retry_count"]) if row else None
        finally:
            c.close()

    def close(self):
        self.dbmod.DB_PATH = self._db_orig
        self.dp.DOCUMENT_ROOT = self._docs_orig
        shutil.rmtree(self.dir, ignore_errors=True)

    def conn(self):
        return self.dbmod.get_connection()

    def seed_item(self, item_id=1, court="서울중앙지방법원", case_no="2024타경1", item_no="1"):
        """운영과 같은 형태로 물건을 심는다.

        ★ `auction_case`를 만들고 `auction_item.case_id`로 연결해야 한다 —
        `storage/database.py:_set_document_status()`가 큐의 (court_code, case_no, item_no)를
        `auction_case` JOIN으로 `auction_item.id`에 매핑하기 때문이다. 연결이 없으면
        `mark_queue_done()`이 큐만 done으로 바꾸고 document_status는 그대로 남는다
        (코드가 경고 로그를 남긴다: "document_status 갱신 대상 없음").
        운영에서는 `migrate_execute.py`가 항상 이 연결을 만들므로, fixture도 그렇게 맞춘다.
        """
        c = self.conn()
        try:
            case_id = c.execute(
                "INSERT INTO auction_case (court_code, case_no) VALUES (?,?)",
                (court, case_no)).lastrowid
            c.execute("INSERT INTO auction_item (id,case_id,court_name,case_no,item_no)"
                      " VALUES (?,?,?,?,?)",
                      (item_id, case_id, court, case_no, item_no))
            for dt in ("SPEC", "STATUS", "APPRAISAL"):
                c.execute("INSERT INTO document_status (item_id,doc_type,status)"
                          " VALUES (?,?,'COLLECTING')", (item_id, dt))
            c.commit()
        finally:
            c.close()
        return court, case_no, item_no

    def status_of(self, item_id, doc_type):
        c = self.conn()
        try:
            return c.execute("SELECT status FROM document_status WHERE item_id=? AND doc_type=?",
                             (item_id, doc_type)).fetchone()[0]
        finally:
            c.close()

    def make_pdf(self, name="downloaded.pdf", content=b"%PDF-1.4 qa"):
        p = os.path.join(self.dir, name)
        with open(p, "wb") as f:
            f.write(content)
        return p


def test_success_path_records_viewer_path_and_ready():
    """정상 저장: 파일이 뷰어 경로로 가고, doc_raw/document_status가 함께 맞는가."""
    print("\n--- 1. 정상 저장 경로 ---")
    env = Env()
    try:
        import collect_documents as CD
        court, case_no, item_no = env.seed_item()
        src = env.make_pdf()

        final = CD.finalize_download(src, court, case_no, item_no, "SPEC")
        check("최종 경로가 canonical", final,
              env.dp.canonical_doc_path(court, case_no, item_no, "SPEC"))

        conn = env.conn()
        try:
            ok = CD.save_doc_raw(conn, 1, "SPEC", final)
        finally:
            conn.close()
        check("save_doc_raw 성공", ok, True)
        check("document_status READY", env.status_of(1, "SPEC"), "READY")

        conn = env.conn()
        try:
            row = conn.execute("SELECT doc_version,file_size,storage_path FROM doc_raw"
                               " WHERE item_id=1 AND doc_type='SPEC'").fetchone()
        finally:
            conn.close()
        check("doc_version은 1부터", row["doc_version"], 1)
        check("file_size가 실제 크기", row["file_size"], os.path.getsize(final))
        # ★ 핵심: 기록된 경로가 **뷰어가 읽는 경로**여야 한다(BUGS #64의 본질)
        check("doc_raw.storage_path가 뷰어 경로", row["storage_path"], final)
        check_true("그 경로에 파일이 실제로 있다", os.path.exists(row["storage_path"]))
        check("doc_exists가 완료로 인정", env.dp.doc_exists(court, case_no, item_no, "spec"), True)
    finally:
        env.close()


def test_failure_path_does_not_mark_ready():
    """저장 실패 시 READY로 바뀌지 않는가.

    가장 위험한 오동작은 "실패했는데 READY"다 — 화면에는 열람 가능으로 뜨고 뷰어는 404다.
    """
    print("\n--- 2. 저장 실패는 READY를 만들지 않는다 ---")
    env = Env()
    try:
        import collect_documents as CD
        env.seed_item()

        conn = env.conn()
        try:
            ok = CD.save_doc_raw(conn, 1, "APPRAISAL", os.path.join(env.dir, "does_not_exist.pdf"))
        finally:
            conn.close()
        check("존재하지 않는 파일이면 실패 반환", ok, False)
        check("상태가 READY로 바뀌지 않는다", env.status_of(1, "APPRAISAL"), "COLLECTING")

        conn = env.conn()
        try:
            n = conn.execute("SELECT COUNT(*) FROM doc_raw WHERE item_id=1").fetchone()[0]
        finally:
            conn.close()
        check("실패 시 doc_raw 행도 남지 않는다", n, 0)
    finally:
        env.close()


def test_finalize_download_failure():
    """파일 이동 실패는 None을 돌려주고 원본을 건드리지 않는가."""
    print("\n--- 3. finalize_download 실패 경로 ---")
    env = Env()
    try:
        import collect_documents as CD
        court, case_no, item_no = env.seed_item()

        missing = os.path.join(env.dir, "nope.pdf")
        check("원본이 없으면 None", CD.finalize_download(missing, court, case_no, item_no, "SPEC"), None)
        check_true("목적지에 파일이 생기지 않는다",
                   not os.path.exists(env.dp.canonical_doc_path(court, case_no, item_no, "SPEC")))

        # 알 수 없는 doc_type도 조용히 성공하면 안 된다(KeyError -> None)
        src = env.make_pdf("other.pdf")
        check("모르는 doc_type이면 None", CD.finalize_download(src, court, case_no, item_no, "BOGUS"), None)
        check_true("그 경우 원본은 그대로 남는다", os.path.exists(src))
    finally:
        env.close()


def test_save_failure_records_failed():
    """실패 기록이 두 테이블에 함께 남는가."""
    print("\n--- 4. save_failure 상태 전이 ---")
    env = Env()
    try:
        import collect_documents as CD
        env.seed_item()

        conn = env.conn()
        try:
            CD.save_failure(conn, 1, "STATUS", "다운로드 실패")
        finally:
            conn.close()

        check("document_status가 FAILED", env.status_of(1, "STATUS"), "FAILED")
        conn = env.conn()
        try:
            rows = conn.execute("SELECT item_id,doc_type,error_message FROM document_collect_failures").fetchall()
        finally:
            conn.close()
        check("실패 이력 1건", len(rows), 1)
        check("사유가 보존된다", rows[0]["error_message"], "다운로드 실패")
        check("다른 문서 종류는 영향 없음", env.status_of(1, "SPEC"), "COLLECTING")
    finally:
        env.close()


def test_reruns_keep_version_history():
    """같은 문서를 다시 저장하면 버전이 쌓이고, 뷰어 경로는 하나로 유지되는가."""
    print("\n--- 5. 재실행(버전 이력) ---")
    env = Env()
    try:
        import collect_documents as CD
        court, case_no, item_no = env.seed_item()

        paths = []
        for i, content in enumerate((b"%PDF-1.4 v1", b"%PDF-1.4 version two"), start=1):
            src = env.make_pdf("dl%d.pdf" % i, content)
            final = CD.finalize_download(src, court, case_no, item_no, "SPEC")
            paths.append(final)
            conn = env.conn()
            try:
                CD.save_doc_raw(conn, 1, "SPEC", final)
            finally:
                conn.close()

        check("뷰어 경로는 항상 같은 파일 하나", len(set(paths)), 1)
        conn = env.conn()
        try:
            rows = conn.execute("SELECT doc_version,file_size FROM doc_raw"
                                " WHERE item_id=1 AND doc_type='SPEC' ORDER BY doc_version").fetchall()
        finally:
            conn.close()
        check("버전이 1,2로 쌓인다", [r["doc_version"] for r in rows], [1, 2])
        # 최신 버전의 크기가 마지막 내용과 같아야 한다(옛 내용이 기록되면 추적이 어긋난다)
        check("최신 버전 크기가 마지막 파일과 일치", rows[-1]["file_size"], len(b"%PDF-1.4 version two"))
        check("파일 내용도 마지막 것으로 교체됨",
              open(paths[0], "rb").read(), b"%PDF-1.4 version two")
        check("상태는 READY 유지", env.status_of(1, "SPEC"), "READY")
    finally:
        env.close()


def test_zero_byte_download_is_not_ready():
    """0바이트 파일이 '수집 완료'로 인정되면 안 된다.

    `doc_exists()`는 크기>0을 요구하므로, 0바이트가 READY로 남으면 화면(READY)과
    재수집 판정(미완료)이 영구히 어긋난다.
    """
    print("\n--- 6. 0바이트 다운로드 ---")
    env = Env()
    try:
        import collect_documents as CD
        court, case_no, item_no = env.seed_item()
        src = env.make_pdf("empty.pdf", b"")
        final = CD.finalize_download(src, court, case_no, item_no, "SPEC")
        check_true("이동 자체는 성공", bool(final))
        check("doc_exists는 0바이트를 완료로 보지 않는다",
              env.dp.doc_exists(court, case_no, item_no, "spec"), False)

        # 2026-08-12 Sprint 67 수정 — 0바이트는 실패로 처리한다.
        # 예전에는 크기를 보지 않고 READY로 기록해, 화면은 "열람 가능"인데 뷰어는
        # 0바이트 파일을 서빙하고 `doc_exists()`는 미완료로 보는 **3자 불일치**가 났다.
        conn = env.conn()
        try:
            ok = CD.save_doc_raw(conn, 1, "SPEC", final)
            n = conn.execute("SELECT COUNT(*) FROM doc_raw WHERE item_id=1").fetchone()[0]
        finally:
            conn.close()
        check("0바이트는 저장 실패로 처리된다", ok, False)
        check("doc_raw 행을 만들지 않는다", n, 0)
        check("READY로 바뀌지 않는다", env.status_of(1, "SPEC"), "COLLECTING")
        # 완료 기준이 doc_exists()와 일치해야 한다 — 둘 다 "아직 아님"으로 봐야 정합이다.
        check("doc_exists와 판정이 일치한다(둘 다 미완료)",
              env.dp.doc_exists(court, case_no, item_no, "spec"), False)
    finally:
        env.close()


def test_queue_converges_after_collect_documents():
    """collect_documents가 큐를 갱신하지 않아 생기는 불일치가 **자가 치유되는가**.

    2026-08-12 Sprint 67 — 소유권 매트릭스에서 나온 구조적 차이를 코드 읽기가 아니라
    **실제로 재현**한다. `collect_documents`는 `document_status`를 직접 READY로 바꾸지만
    `document_queue`는 건드리지 않는다. 그 순간 파이프라인 불변식
    ("파일이 있으면 큐도 done", `test_pipeline_integrity.py`)이 깨진다.

    여기서 확인하는 것은 "깨진다"가 아니라 **다음 doc_worker 실행에서 수렴하는가**다.
    selenium 없이 실제 함수로 재현할 수 있다 — `collect_spec()`은 `doc_exists()`가 참이면
    **driver를 건드리기 전에** success=True로 단락하기 때문이다(driver=None으로 호출 가능).
    """
    print("\n--- 7. collect_documents 이후 큐 수렴 (Sprint 67) ---")
    import collect_documents as CD
    from crawler.doc_crawler import collect_spec

    env = Env()
    try:
        court, case_no, item_no = env.seed_item()
        qid = env.enqueue(court, case_no, item_no, "spec")
        check("초기 큐 상태", env.queue_status(qid), ("pending", 0))

        # 1) collect_documents 경로로 수집 성공
        src = env.make_pdf()
        final = CD.finalize_download(src, court, case_no, item_no, "SPEC")
        conn = env.conn()
        try:
            CD.save_doc_raw(conn, 1, "SPEC", final)
        finally:
            conn.close()

        check("collect 후 document_status", env.status_of(1, "SPEC"), "READY")
        check_true("collect 후 파일 존재", os.path.exists(final))
        # ★ 여기가 불일치 지점 — 큐는 여전히 pending이다
        check("collect 후 큐는 아직 pending (구조적 차이 재현)", env.queue_status(qid)[0], "pending")

        # 2) doc_worker가 그 항목을 claim
        claimed = env.dbmod.claim_next_queue_item()
        check_true("worker가 같은 항목을 claim한다", claimed is not None and claimed["id"] == qid,
                   claimed)
        check("claim 직후 in_progress", env.queue_status(qid)[0], "in_progress")

        # 3) collect_spec은 파일이 이미 있으므로 **재다운로드 없이** 성공 반환
        before = os.stat(final)
        result = collect_spec(None, court, case_no, item_no, "btn-id")
        check("이미 있으면 재다운로드 없이 성공", result["success"], True)
        # ★ 2026-08-19 Sprint 217 (BUGS #144): 예전에는 `files_saved == []` 로
        #   "재다운로드 안 함"을 증명했다. 그 빈 목록 때문에 `_record_doc_raw()` 가
        #   실체 기록을 통째로 건너뛰는 결함이 있었다(파일은 있는데 doc_raw 0행).
        #   의도는 그대로 두고 증거를 바꾼다 — 다시 받지 않았다는 것은 **파일이
        #   그대로라는 사실**로 확인한다.
        after = os.stat(final)
        check("재다운로드 안 함(mtime/크기 그대로)",
              (after.st_mtime_ns, after.st_size), (before.st_mtime_ns, before.st_size))
        check("스킵 경로도 이미 가진 실체를 가리킨다",
              [os.path.basename(x) for x in result["files_saved"]], ["spec.pdf"])

        # 4) mark_queue_done이 큐/상태/플래그를 한 번에 맞춘다
        #    doc_worker 와 **같은 인자**로 부른다(files_saved 포함) — 여기서만 빼면
        #    실제 운영 경로와 다른 것을 검사하게 된다.
        env.dbmod.mark_queue_done(qid, court, case_no, item_no, "spec",
                                  result["previous_hash"], result["new_hash"],
                                  files_saved=result["files_saved"])

        check("최종 큐 상태 done", env.queue_status(qid)[0], "done")
        check("최종 document_status READY", env.status_of(1, "SPEC"), "READY")
        check_true("파일은 그대로", os.path.exists(final))
        conn = env.conn()
        try:
            raw = conn.execute("SELECT COUNT(*) FROM doc_raw WHERE item_id=1").fetchone()[0]
            vlog = conn.execute("SELECT COUNT(*) FROM document_version_log").fetchone()[0]
        finally:
            conn.close()
        check("doc_raw 행은 1건 유지(중복 생성 없음)", raw, 1)
        # previous_hash가 비어 있으므로 버전 로그는 남지 않아야 한다
        check("불필요한 version log가 생기지 않는다", vlog, 0)
    finally:
        env.close()


def test_worker_failure_then_retry_converges():
    """수집 실패 -> 재시도 -> 성공까지 큐/상태/파일이 함께 수렴하는가.

    실패가 남긴 상태가 다음 시도를 방해하면 그 문서는 영구히 미수집으로 남는다.
    """
    print("\n--- 8. 실패 -> 재시도 -> 성공 수렴 (Sprint 67) ---")
    from crawler.doc_crawler import collect_spec

    env = Env()
    try:
        court, case_no, item_no = env.seed_item()
        qid = env.enqueue(court, case_no, item_no, "spec")

        # 1회차: claim 후 실패(파일이 없으니 collect_spec은 driver를 쓰려다 실패한다).
        #        worker는 mark_queue_failed로 재시도 대기로 되돌린다.
        env.dbmod.claim_next_queue_item()
        env.dbmod.mark_queue_failed(qid, 0)
        st, retry = env.queue_status(qid)
        check("1회 실패 후 pending 복귀", st, "pending")
        check("재시도 횟수 1", retry, 1)
        check("실패해도 document_status는 READY가 아니다", env.status_of(1, "SPEC"), "COLLECTING")

        # 재시도 간격(30분) 전이라 즉시 다시 집히지 않아야 한다
        check("재시도 간격 전에는 claim되지 않는다", env.dbmod.claim_next_queue_item(), None)

        # 간격이 지난 것으로 만들고 재시도
        conn = env.conn()
        try:
            # 'localtime' 필수 — 운영 코드가 `last_attempt_at`을 로컬 시각으로 쓰고
            # claim도 로컬로 비교한다. UTC로 밀면 한국 기준 9시간 이상을 미는 셈이 되어
            # "간격 +5분"이라는 이 검사의 경계 의미가 사라진다.
            conn.execute("UPDATE document_queue SET"
                         " last_attempt_at=datetime('now','localtime','-%d minutes')"
                         " WHERE id=?" % (env.dbmod.RETRY_INTERVAL_MINUTES + 5), (qid,))
            conn.commit()
        finally:
            conn.close()
        again = env.dbmod.claim_next_queue_item()
        check_true("간격 경과 후 다시 claim된다", again is not None and again["id"] == qid, again)

        # 2회차: 이번엔 파일이 준비된 상태(수집 성공했다고 가정)
        dest = env.dp.canonical_doc_path(court, case_no, item_no, "SPEC")
        with open(dest, "wb") as f:
            f.write(b"%PDF-1.4 retry success")
        result = collect_spec(None, court, case_no, item_no, "btn-id")
        check("재시도에서 성공", result["success"], True)
        env.dbmod.mark_queue_done(qid, court, case_no, item_no, "spec",
                                  result["previous_hash"], result["new_hash"])

        check("최종 큐 done", env.queue_status(qid)[0], "done")
        check("최종 document_status READY", env.status_of(1, "SPEC"), "READY")
        check("doc_exists도 완료로 인정", env.dp.doc_exists(court, case_no, item_no, "spec"), True)
        # 실패 이력이 성공을 가리지 않아야 한다(재시도 횟수는 남아도 상태는 done)
        check("재시도 횟수는 이력으로 남는다", env.queue_status(qid)[1], 1)
    finally:
        env.close()


def run():
    test_success_path_records_viewer_path_and_ready()
    test_failure_path_does_not_mark_ready()
    test_finalize_download_failure()
    test_save_failure_records_failed()
    test_reruns_keep_version_history()
    test_zero_byte_download_is_not_ready()
    test_queue_converges_after_collect_documents()
    test_worker_failure_then_retry_converges()

    print("\n" + "=" * 55)
    if failures:
        print("FAILED (%d): %s" % (len(failures), ", ".join(failures)))
        return 1
    print("ALL TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(run())
