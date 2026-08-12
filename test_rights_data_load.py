"""load_rights_data.py 회귀 테스트 (2026-08-12 Sprint 62 신설).

이 스크립트는 `rights_summary` / `tenant_rights(source='STATUS')`를 쓰는 **유일한 코드**인데
그동안 테스트가 0건이었다(pdfplumber/pandas 미설치로 실행 자체가 불가능하던 시기가 길었고,
Sprint 61에 의존성이 설치되면서 비로소 검증 가능해졌다).

검증하는 것:
    1. 정상 적재 — status.html의 근거대로 rights_summary/tenant_rights가 만들어진다
    2. 근거 없는 컬럼은 NULL로 남는다 (이 스크립트의 대원칙: 추정/생성 금지)
    3. 근거 문서가 사라지면 파생 행도 정리된다 (Sprint 62 수정 — 이전에는 영원히 남았다)
    4. **안전장치** — 문서를 하나도 못 찾으면 아무것도 지우지 않는다
       (documents/ 경로 문제로 전체 권리분석 데이터가 날아가는 것을 막는다)
    5. 파일은 있는데 추출 결과가 비면 지우지 않는다 (파서 회귀로도 같은 증상이 나므로 보수적)
    6. 멱등성 — 두 번 돌려도 결과가 같다

실제 `auction.db` / `documents/`는 건드리지 않는다 — 전부 임시 디렉터리에서 수행한다.

    python test_rights_data_load.py
"""
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

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


# 실제 현황조사서 HTML의 최소 구조. `load_rights_data.py`의 파서가 의존하는
# data-col_id / data-tr-id / _spn_possMngRltn 마크업을 그대로 재현한다.
def status_html(address, lease_count, occupancy="미상"):
    return """
    <table>
      <tr data-tr-id="row2">
        <td data-col_id="printSt"><nobr>%s</nobr></td>
        <td data-col_id="lesCnt"><nobr>%d명</nobr></td>
      </tr>
    </table>
    <span id="x_spn_possMngRltn">%s</span>
    """ % (address, lease_count, occupancy)


class Env:
    """임시 DB + 임시 documents/ 를 만들고 모듈 전역 경로를 갈아끼운다."""

    def __init__(self):
        self.dir = tempfile.mkdtemp(prefix="qa_rights_")
        self.db = os.path.join(self.dir, "t.db")
        self.docs = os.path.join(self.dir, "documents")
        os.makedirs(self.docs)

        import storage.database as dbmod
        import api.v1.documents as docsmod
        self.dbmod, self.docsmod = dbmod, docsmod
        self._db_orig, self._docs_orig = dbmod.DB_PATH, docsmod.DOCUMENT_ROOT
        dbmod.DB_PATH, docsmod.DOCUMENT_ROOT = self.db, self.docs

        # 스키마는 손으로 베끼지 않고 **실제 마이그레이션 코드**로 만든다
        # (test_document_queue.py와 같은 원칙 — 베껴 두면 진짜 스키마가 바뀌어도 통과한다).
        import storage.migrate_v4_1 as mig
        import io
        import contextlib
        with contextlib.redirect_stdout(io.StringIO()):
            mig.migrate()

    def close(self):
        self.dbmod.DB_PATH = self._db_orig
        self.docsmod.DOCUMENT_ROOT = self._docs_orig
        shutil.rmtree(self.dir, ignore_errors=True)

    def conn(self):
        return self.dbmod.get_connection()

    def add_item(self, item_id, court, case_no, item_no):
        c = self.conn()
        try:
            c.execute("INSERT INTO auction_item (id, court_name, case_no, item_no) VALUES (?,?,?,?)",
                      (item_id, court, case_no, item_no))
            c.commit()
        finally:
            c.close()

    def write_status(self, court, case_no, item_no, html):
        d = os.path.join(self.docs, court, case_no, item_no)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "status.html"), "w", encoding="utf-8") as f:
            f.write(html)

    def remove_status(self, court, case_no, item_no):
        os.remove(os.path.join(self.docs, court, case_no, item_no, "status.html"))

    def counts(self, item_id=None):
        c = self.conn()
        try:
            if item_id is None:
                rs = c.execute("SELECT COUNT(*) FROM rights_summary").fetchone()[0]
                tr = c.execute("SELECT COUNT(*) FROM tenant_rights WHERE source='STATUS'").fetchone()[0]
            else:
                rs = c.execute("SELECT COUNT(*) FROM rights_summary WHERE item_id=?", (item_id,)).fetchone()[0]
                tr = c.execute("SELECT COUNT(*) FROM tenant_rights WHERE source='STATUS' AND item_id=?",
                               (item_id,)).fetchone()[0]
            return rs, tr
        finally:
            c.close()


def run_loader():
    import importlib
    import load_rights_data
    importlib.reload(load_rights_data)  # 모듈 상단에서 캡처한 경로가 있어도 새로 읽게 한다
    import io
    import contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        load_rights_data.main()
    return buf.getvalue()


def test_normal_load():
    print("\n--- 1. 정상 적재 (성공 경로) ---")
    env = Env()
    try:
        env.add_item(1, "서울중앙지방법원", "2024타경1111", "1")
        env.write_status("서울중앙지방법원", "2024타경1111", "1",
                         status_html("서울특별시 강남구 테헤란로 1, 101호", 2))
        run_loader()

        c = env.conn()
        try:
            row = c.execute("SELECT * FROM rights_summary WHERE item_id=1").fetchone()
            check_true("rights_summary 행이 생성된다", row is not None)
            check("임차인 수가 근거대로 집계된다", row["total_tenant_count"], 2)
            check("임차인이 있으므로 공실 아님", row["is_vacant"], 0)
            check("점유관계 '미상' -> 판단보류", row["occupancy_difficulty"], "판단보류")
            # 대원칙: 근거 없는 컬럼은 추정하지 않고 NULL로 남긴다
            for col in ("priority_right", "total_deposit", "risk_level", "risk_reason",
                        "analysis_explanation", "estimated_inheritance", "lien_exists"):
                check("근거 없는 %s는 NULL" % col, row[col], None)

            trs = c.execute("SELECT * FROM tenant_rights WHERE item_id=1 AND source='STATUS'").fetchall()
            check("임차인 수만큼 tenant_rights 행 생성", len(trs), 2)
            check("보증금은 근거가 없어 NULL", trs[0]["deposit"], None)
        finally:
            c.close()
    finally:
        env.close()


def test_vacant_property():
    print("\n--- 2. 임차인 0명(공실) ---")
    env = Env()
    try:
        env.add_item(1, "서울중앙지방법원", "2024타경2222", "1")
        env.write_status("서울중앙지방법원", "2024타경2222", "1",
                         status_html("서울특별시 종로구 1", 0))
        run_loader()
        c = env.conn()
        try:
            row = c.execute("SELECT * FROM rights_summary WHERE item_id=1").fetchone()
            check("공실로 기록된다", row["is_vacant"], 1)
            check("임차인 수 0", row["total_tenant_count"], 0)
            n = c.execute("SELECT COUNT(*) FROM tenant_rights WHERE item_id=1").fetchone()[0]
            check("0명이면 tenant_rights 행을 만들지 않는다", n, 0)
        finally:
            c.close()
    finally:
        env.close()


def test_orphan_purge():
    print("\n--- 3. 근거 문서가 사라지면 파생 행도 정리된다 (Sprint 62 수정) ---")
    env = Env()
    try:
        # 두 물건 다 적재 -> 그중 하나의 근거 문서만 삭제 -> 그 물건만 정리되어야 한다
        env.add_item(1, "서울중앙지방법원", "2024타경1111", "1")
        env.add_item(2, "춘천지방법원", "2024타경2803", "1")
        env.write_status("서울중앙지방법원", "2024타경1111", "1", status_html("서울 A", 1))
        env.write_status("춘천지방법원", "2024타경2803", "1", status_html("춘천 B", 2))
        run_loader()
        check("적재 직후 두 물건 모두 존재", env.counts(), (2, 3))

        env.remove_status("춘천지방법원", "2024타경2803", "1")
        out = run_loader()

        check("근거 사라진 물건의 rights_summary 제거", env.counts(2)[0], 0)
        check("근거 사라진 물건의 tenant_rights 제거", env.counts(2)[1], 0)
        check("근거가 남아있는 물건은 그대로", env.counts(1), (1, 1))
        check_true("정리 건수를 보고한다", "정리한 파생 행: 3" in out, out)
    finally:
        env.close()


def test_safety_guard_no_mass_wipe():
    print("\n--- 4. 안전장치: 문서를 하나도 못 찾으면 절대 지우지 않는다 ---")
    env = Env()
    try:
        env.add_item(1, "서울중앙지방법원", "2024타경1111", "1")
        env.add_item(2, "춘천지방법원", "2024타경2803", "1")
        env.write_status("서울중앙지방법원", "2024타경1111", "1", status_html("서울 A", 1))
        env.write_status("춘천지방법원", "2024타경2803", "1", status_html("춘천 B", 2))
        run_loader()
        before = env.counts()
        check("적재 완료", before, (2, 3))

        # documents/ 가 통째로 사라진 상황(경로 변경 / 드라이브 미마운트 / 권한).
        # 이때 "전부 근거 없음"으로 판단해 지우면 전체 권리분석 데이터가 날아간다.
        env.docsmod.DOCUMENT_ROOT = os.path.join(env.dir, "gone")
        out = run_loader()

        check("전체 데이터가 그대로 보존된다", env.counts(), before)
        check_true("안전장치가 동작했음을 보고한다", "[안전장치]" in out, out)
    finally:
        env.close()


def test_no_extractable_data_is_not_purged():
    print("\n--- 5. 파일은 있는데 추출 결과가 비면 지우지 않는다(보수적) ---")
    env = Env()
    try:
        env.add_item(1, "서울중앙지방법원", "2024타경1111", "1")
        env.write_status("서울중앙지방법원", "2024타경1111", "1", status_html("서울 A", 1))
        run_loader()
        check("적재 완료", env.counts(), (1, 1))

        # 파서가 아무것도 못 뽑는 내용으로 교체(파서 회귀와 구분 불가한 상황)
        env.write_status("서울중앙지방법원", "2024타경1111", "1", "<html>내용 없음</html>")
        run_loader()
        check("파일이 존재하면 기존 파생 행을 지우지 않는다", env.counts(), (1, 1))
    finally:
        env.close()


def test_idempotent():
    print("\n--- 6. 멱등성 ---")
    env = Env()
    try:
        env.add_item(1, "서울중앙지방법원", "2024타경1111", "1")
        env.write_status("서울중앙지방법원", "2024타경1111", "1", status_html("서울 A", 3))
        run_loader()
        first = env.counts()
        run_loader()
        run_loader()
        check("여러 번 실행해도 결과가 같다(행 중복 없음)", env.counts(), first)
        check("임차인 3명이 3행으로 유지된다", first, (1, 3))
    finally:
        env.close()


def run_spec_loader():
    import importlib
    import load_spec_data
    importlib.reload(load_spec_data)
    import io
    import contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        load_spec_data.main()
    return buf.getvalue()


def seed_spec_rows(env, item_id, n):
    c = env.conn()
    try:
        for i in range(n):
            c.execute(
                "INSERT INTO tenant_rights (item_id, tenant_name, source, created_at)"
                " VALUES (?,?,'SPEC','2026-01-01')", (item_id, "임차인%d" % i))
        c.commit()
    finally:
        c.close()


def spec_count(env, item_id=None):
    c = env.conn()
    try:
        if item_id is None:
            return c.execute("SELECT COUNT(*) FROM tenant_rights WHERE source='SPEC'").fetchone()[0]
        return c.execute("SELECT COUNT(*) FROM tenant_rights WHERE source='SPEC' AND item_id=?",
                         (item_id,)).fetchone()[0]
    finally:
        c.close()


def write_spec(env, court, case_no, item_no, content=b"%PDF-1.4 not-a-real-pdf"):
    """유효하지 않은 PDF를 쓴다.

    `load_spec_data.load_item()`은 파싱 실패를 `parse_error`로 처리하므로, **파일이
    존재한다**는 사실만으로 "근거를 찾았다"에 해당한다. 덕분에 진짜 PDF를 만들지 않고도
    정리 로직과 안전장치를 검증할 수 있다.
    """
    d = os.path.join(env.docs, court, case_no, item_no)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "spec.pdf"), "wb") as f:
        f.write(content)


def test_spec_orphan_purge():
    print("\n--- 7. SPEC: 근거 문서가 사라지면 파생 행도 정리된다 (Sprint 62) ---")
    env = Env()
    try:
        env.add_item(1, "서울중앙지방법원", "2024타경1111", "1")   # spec.pdf 있음
        env.add_item(2, "춘천지방법원", "2024타경2803", "1")       # spec.pdf 없음
        write_spec(env, "서울중앙지방법원", "2024타경1111", "1")
        seed_spec_rows(env, 1, 2)
        seed_spec_rows(env, 2, 3)
        check("사전 상태", (spec_count(env, 1), spec_count(env, 2)), (2, 3))

        out = run_spec_loader()
        check("근거 파일이 없는 물건의 SPEC 행은 정리된다", spec_count(env, 2), 0)
        # 파일은 있으나 파싱 실패(parse_error)인 물건은 보수적으로 보존한다
        check("파일이 존재하면(파싱 실패여도) 기존 행을 지우지 않는다", spec_count(env, 1), 2)
        check_true("정리 건수를 보고한다", "정리한 파생 행: 3" in out, out)
    finally:
        env.close()


def test_spec_safety_guard():
    print("\n--- 8. SPEC 안전장치: 문서를 하나도 못 찾으면 지우지 않는다 ---")
    env = Env()
    try:
        env.add_item(1, "서울중앙지방법원", "2024타경1111", "1")
        env.add_item(2, "춘천지방법원", "2024타경2803", "1")
        seed_spec_rows(env, 1, 2)
        seed_spec_rows(env, 2, 3)
        before = spec_count(env)
        check("사전 상태", before, 5)

        out = run_spec_loader()   # spec.pdf가 저장소 어디에도 없다
        check("전체 SPEC 데이터가 보존된다", spec_count(env), before)
        check_true("안전장치가 동작했음을 보고한다", "[안전장치]" in out, out)
    finally:
        env.close()


def run():
    test_normal_load()
    test_vacant_property()
    test_orphan_purge()
    test_safety_guard_no_mass_wipe()
    test_no_extractable_data_is_not_purged()
    test_idempotent()
    test_spec_orphan_purge()
    test_spec_safety_guard()

    print("\n" + "=" * 55)
    if failures:
        print("FAILED (%d): %s" % (len(failures), ", ".join(failures)))
        return 1
    print("ALL TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(run())
