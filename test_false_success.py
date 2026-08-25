"""
"DB/API는 성공인데 실제로는 못 쓴다" (false success) 회귀 테스트.

    python test_false_success.py

Sprint 95는 등기부 admin이 `doc_url`의 **파일 존재를 확인하지 않아** "발급 완료인데
다운로드 404"를 만들 수 있던 결함을 막았다. 이 파일은 그 **패턴**을 다른 경로로 확장해
잡아 둔다(2026-08-13 Sprint 98).

수록 대상:

    1. 등기부 신청 - 물건 행이 사라지면 **소유자에게만** 사라진다
       (목록/상세는 없다는데 다운로드는 200으로 파일을 준다)
    2. 문서 뷰어 - **0바이트 파일을 200으로** 내려준다
       (프런트는 HEAD의 res.ok만 보고 뷰어를 띄우므로 사용자는 빈 화면을 본다)

설계 원칙 두 가지:

- **실 DB를 건드리지 않는다.** 등기부 검사는 `auction.db`의 **임시 복사본**에 대고 돈다.
  고아 상태(FK를 끄고 물건 행 삭제)는 운영 DB에서 재현할 성질의 것이 아니고, 다른 세션이
  같은 DB로 테스트를 돌리고 있을 수도 있다.
- **모든 검사에 대조군을 둔다.** 대조군이 없으면 "고쳐서 404"인지 "원래 경로가 틀려서
  404"인지 구별할 수 없다 — 통과해도 아무것도 증명하지 못하는 검사가 된다.

출력은 ASCII 라벨 + 한글 설명을 섞어 쓴다(기존 테스트들과 동일).
"""
import os
import sys
import uuid
import shutil
import sqlite3
import secrets
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))

# admin 인증/JWT는 이 프로세스 환경에만 주입한다(.env 무수정) — test_api_regression.py와 동일.
TEST_ADMIN_KEY = "qa-false-success-admin-key"
os.environ["ADMIN_API_KEY"] = TEST_ADMIN_KEY
os.environ.setdefault("SUPER_ADMIN_API_KEY", "qa-false-success-super-key")
if not os.getenv("SUPABASE_JWT_SECRET"):
    os.environ["SUPABASE_JWT_SECRET"] = "qa-false-success-" + secrets.token_hex(16)

failures = []


def check(name, actual, expected):
    if actual == expected:
        print("[PASS] %s: %r (expected %r)" % (name, actual, expected))
    else:
        print("[FAIL] %s: %r (expected %r)" % (name, actual, expected))
        failures.append(name)


def check_true(name, cond, detail=""):
    if cond:
        print("[PASS] %s" % name)
    else:
        print("[FAIL] %s -> %r" % (name, detail))
        failures.append(name)


# ---------------------------------------------------------------------------
# 1. 물건 행이 사라진 등기부 신청의 가시성
# ---------------------------------------------------------------------------
def test_registry_orphan_visibility():
    """`auction_item`이 사라져도 **소유자에게** 신청이 계속 보여야 한다.

    Sprint 95는 "COMPLETED인데 파일이 없어 못 받는" 방향을 막았다. 이건 그 **반대
    방향**이다 — 파일도 있고 다운로드도 200인데, 목록이 신청을 지워 버려 사용자가
    거기에 **도달할 수 없다.**

    프런트가 request_id를 얻는 경로는 `GET /registry-requests` 하나뿐이다
    (`mypage/page.tsx`, `properties/[id]/page.tsx`). 목록에서 빠지면 다운로드 URL을
    만들 수 없으므로, 돈을 내고 발급받은 문서가 영영 사라진다.

    **네 경로를 함께** 본다. 하나라도 빼면 불일치를 못 잡는다:
    사용자 목록 / 사용자 상세 / 관리자 목록 / 다운로드.
    JOIN을 INNER로 되돌리면 앞의 두 개만 실패하고 뒤의 두 개는 계속 통과한다 —
    그 모순이 곧 이 결함의 정의다.
    """
    print("\n--- 1. 물건 행이 사라진 등기부 신청의 가시성 (Sprint 98) ---")

    tmp_dir = tempfile.mkdtemp(prefix="qa_false_success_")
    test_db = os.path.join(tmp_dir, "auction_copy.db")
    # 온라인 백업 스냅샷 - 워커가 쓰는 중이어도 일관된 사본을 만든다
    # (shutil.copy2 는 찢어질 수 있다. 사유: storage/database.py:snapshot_live_db)
    import storage.database as _dbmod
    _dbmod.snapshot_live_db(test_db)

    import storage.database as dbmod
    saved_db_path = dbmod.DB_PATH
    dbmod.DB_PATH = test_db

    doc_path = None
    try:
        from fastapi.testclient import TestClient
        from jose import jwt
        import api_server
        from api.auth import SUPABASE_JWT_SECRET
        from api.v1.registry import REGISTRY_DOCUMENT_ROOT

        client = TestClient(api_server.app)
        user = "qa-orphan-" + uuid.uuid4().hex[:10]
        headers = {"Authorization": "Bearer " + jwt.encode(
            {"sub": user, "aud": "authenticated"}, SUPABASE_JWT_SECRET, algorithm="HS256")}

        raw = sqlite3.connect(test_db)
        item_id = raw.execute(
            # 시각은 로컬로 넣는다 — 이 저장소의 모든 운영 코드가
            # `datetime.now().isoformat()`(로컬)로 쓰므로, 픽스처만 UTC면 같은 컬럼에
            # 9시간 어긋난 값이 섞인다.
            "INSERT INTO auction_item (case_no, item_no, court_name, full_address, created_at)"
            " VALUES (?,?,?,?,datetime('now','localtime'))",
            ("2026타경-qa-orphan", "1", "서울중앙지방법원", "서울시 QA구 고아동 1-1"),
        ).lastrowid
        doc_name = "qa-false-success-%s.pdf" % uuid.uuid4().hex[:8]
        req_id = raw.execute(
            "INSERT INTO registry_requests"
            " (user_id, item_id, status, doc_url, requested_at, completed_at)"
            " VALUES (?,?,?,?,datetime('now','localtime'),datetime('now','localtime'))",
            (user, item_id, "COMPLETED", doc_name),
        ).lastrowid
        raw.commit()

        # 문서 파일은 **실제로** 둔다 — "받을 수는 있는데 안 보인다"를 보이는 것이 요지다.
        os.makedirs(REGISTRY_DOCUMENT_ROOT, exist_ok=True)
        doc_path = os.path.join(REGISTRY_DOCUMENT_ROOT, doc_name)
        with open(doc_path, "wb") as fh:
            fh.write(b"%PDF-1.4 qa false-success fixture")

        # ── 대조군: 물건 행이 살아 있을 때 ──
        listed = [x["id"] for x in client.get(
            "/api/v1/registry-requests", headers=headers).json()["data"]]
        check_true("대조군: 물건이 있으면 목록에 보인다", req_id in listed, listed[:5])
        check("대조군: 상세도 200",
              client.get("/api/v1/registry-requests/%d" % req_id, headers=headers).status_code,
              200)

        # 테이블 재작성 마이그레이션(011~013)이 하듯 FK를 끄고 물건 행만 지운다.
        raw.execute("PRAGMA foreign_keys = OFF")
        raw.execute("DELETE FROM auction_item WHERE id=?", (item_id,))
        raw.commit()
        still = raw.execute(
            "SELECT COUNT(*) FROM registry_requests WHERE id=?", (req_id,)).fetchone()[0]
        check("신청 행 자체는 남아 있다", still, 1)
        raw.close()

        # ── 여기부터가 회귀 대상 ──
        listed = [x["id"] for x in client.get(
            "/api/v1/registry-requests", headers=headers).json()["data"]]
        check_true("물건이 사라져도 사용자 목록에 남는다", req_id in listed, listed[:5])

        detail = client.get("/api/v1/registry-requests/%d" % req_id, headers=headers)
        check("사용자 상세도 200", detail.status_code, 200)
        # 본문 검사는 200일 때만 한다 — 회귀로 404가 되면 `data` 키가 없어 KeyError로
        # 테스트가 죽고, 아래 관리자/다운로드 검사가 아예 실행되지 않는다.
        # 회귀는 트레이스백이 아니라 FAIL 목록으로 보여야 한다.
        body = detail.json().get("data") if detail.status_code == 200 else None
        # 물건 정보는 없어졌지만 신청 자체는 온전해야 한다. 프런트는 두 필드를
        # `string | null`로 선언하고 `|| '-'`로 그리므로 None이 계약 위반이 아니다.
        check("사라진 물건의 case_no는 null", body["case_no"] if body else "<no body>", None)
        check("신청 상태는 그대로", body["status"] if body else "<no body>", "COMPLETED")

        admin_ids = [x["id"] for x in client.get(
            "/api/v1/admin/registry-requests?user_id=%s&size=200" % user,
            headers={"X-Admin-Key": TEST_ADMIN_KEY}).json()["data"]["items"]]
        check_true("관리자 목록에는 남는다(Sprint 97 LEFT JOIN)", req_id in admin_ids, admin_ids[:5])

        # 이 검사가 이 테스트의 핵심이다 — 목록이 "없다"고 한 신청의 문서가 실제로는 내려온다.
        dl = client.get("/api/v1/registry-requests/%d/download" % req_id, headers=headers)
        check("문서는 실제로 받을 수 있다(모순의 증거)", dl.status_code, 200)
    finally:
        dbmod.DB_PATH = saved_db_path
        if doc_path and os.path.exists(doc_path):
            os.remove(doc_path)
        shutil.rmtree(tmp_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# 2. 0바이트 문서는 "있다"로 치지 않는다
# ---------------------------------------------------------------------------
def test_zero_byte_document_is_not_served():
    """0바이트 문서를 200으로 주면 사용자는 **설명 없는 빈 화면**을 본다.

    프런트(`properties/[id]/page.tsx`)는 뷰어를 열기 전 HEAD로 존재만 확인하고
    `res.ok`만 본다. 200이면 iframe을 띄우므로 "문서가 없다"는 안내조차 못 받는다.

    쓰는 쪽은 이미 크기를 본다 — `crawler/doc_paths.doc_exists()`는
    `exists() and getsize() > 0`이라야 "수집됨"으로 친다. 읽는 쪽만 기준이 느슨하면
    **크롤러는 "없음"이라 재수집 대상으로 보는 파일을 API는 "있음"이라 답한다.**

    실 DB를 쓰지 않는다 — 메모리 DB를 끼워 넣어 물건 행만 흉내낸다.
    """
    print("\n--- 2. 0바이트 문서 서빙 (Sprint 98) ---")

    from fastapi.testclient import TestClient
    import api_server
    import api.v1.documents as docs_mod

    client = TestClient(api_server.app)

    mem = sqlite3.connect(":memory:", check_same_thread=False)
    mem.row_factory = sqlite3.Row
    mem.execute("CREATE TABLE auction_item (id INTEGER PRIMARY KEY, court_name TEXT,"
                " case_no TEXT, item_no TEXT)")
    mem.executemany(
        "INSERT INTO auction_item (id, court_name, case_no, item_no) VALUES (?,?,?,?)",
        [
            (9101, "QA법원", "2026타경-empty", "1"),      # 0바이트
            (9102, "QA법원", "2026타경-nonempty", "1"),   # 대조군
        ],
    )
    mem.commit()

    class _NoCloseConn:
        """엔드포인트는 finally에서 conn.close()를 부른다 — 메모리 DB가 그때 사라지면
        다음 호출이 빈 DB를 보게 된다. close만 무시하고 나머지는 위임한다."""

        def __init__(self, conn):
            self._conn = conn

        def close(self):
            pass

        def __getattr__(self, name):
            return getattr(self._conn, name)

    empty_dir = docs_mod.get_doc_dir("QA법원", "2026타경-empty", "1")
    nonempty_dir = docs_mod.get_doc_dir("QA법원", "2026타경-nonempty", "1")
    os.makedirs(empty_dir, exist_ok=True)
    os.makedirs(nonempty_dir, exist_ok=True)
    with open(os.path.join(empty_dir, "spec.pdf"), "wb") as fh:
        fh.write(b"")
    with open(os.path.join(nonempty_dir, "spec.pdf"), "wb") as fh:
        fh.write(b"%PDF-1.4 qa nonempty")

    real_get_connection = docs_mod.get_connection
    docs_mod.get_connection = lambda *a, **kw: _NoCloseConn(mem)
    try:
        # 대조군이 200이어야 이 검사가 의미를 갖는다. 둘 다 404면 경로가 틀린 것이고,
        # 둘 다 200이면 크기 검사가 없는 것이다.
        r = client.get("/api/v1/item/9102/documents/SPEC")
        check("대조군: 내용이 있는 문서는 200", r.status_code, 200)
        check_true("대조군: 실제 내용이 실려 온다", r.content.startswith(b"%PDF"), r.content[:20])

        check("0바이트 문서는 404(빈 200이 아니다)",
              client.get("/api/v1/item/9101/documents/SPEC").status_code, 404)
        # HEAD가 특히 중요하다 — 프런트는 HEAD의 res.ok만 보고 뷰어를 띄운다.
        check("HEAD도 0바이트를 404로 본다",
              client.head("/api/v1/item/9101/documents/SPEC").status_code, 404)
        check("대조군: HEAD는 200",
              client.head("/api/v1/item/9102/documents/SPEC").status_code, 200)
    finally:
        docs_mod.get_connection = real_get_connection
        mem.close()
        shutil.rmtree(os.path.join(docs_mod.DOCUMENT_ROOT, "QA법원"), ignore_errors=True)


# ---------------------------------------------------------------------------
# 3. 유료 등기부 문서도 0바이트를 "있다"로 치지 않는다 (2026-08-14 신설)
#
# §2는 **무료 법원문서**(`api/v1/documents.py`)만 덮고 있었다. 같은 저장소의 다른 파일
# 서빙 경로인 `api/v1/registry.py`(유료 등기부)에는 그 방어가 없었고, 실측으로 재현됐다.
#
#     0바이트 등기부 파일  ->  HTTP 200 / 0 bytes
#
# **돈이 걸린 쪽이 더 느슨했다.** 사용자는 등기부 발급 비용을 내고 빈 파일을 받는다.
# 게다가 `os.path.exists()`는 디렉터리에도 True라, 그 경우 FileResponse가 터져 500이 된다.
#
# 기준은 이 저장소가 이미 합의해 둔 것 하나뿐이어야 한다 —
# `crawler/doc_paths.py:doc_exists()` = `exists() and getsize() > 0`.
#
# 저장소 전체 검색 결과 파일을 서빙하는 자리는 이 둘뿐이다(FileResponse 2곳).
# 이제 둘 다 같은 정의를 쓴다.
# ---------------------------------------------------------------------------
def test_zero_byte_registry_document_is_not_served():
    print("\n--- 3. 0바이트 유료 등기부 서빙 (2026-08-14) ---")

    # jwt / SUPABASE_JWT_SECRET 은 환경변수 주입 뒤에 import 해야 한다(§1과 동일한 순서).
    from fastapi.testclient import TestClient
    from jose import jwt
    import api_server
    import api.v1.registry as reg_mod
    from api.auth import SUPABASE_JWT_SECRET

    client = TestClient(api_server.app)
    user = "qa-zero-reg-" + uuid.uuid4().hex[:8]
    headers = {"Authorization": "Bearer " + jwt.encode(
        {"sub": user, "aud": "authenticated"}, SUPABASE_JWT_SECRET, algorithm="HS256")}

    mem = sqlite3.connect(":memory:", check_same_thread=False)
    mem.row_factory = sqlite3.Row
    mem.execute("CREATE TABLE registry_requests (id INTEGER PRIMARY KEY, user_id TEXT,"
                " item_id INTEGER, status TEXT, doc_url TEXT)")
    empty_name = "qa-zero-%s.pdf" % uuid.uuid4().hex[:8]
    full_name = "qa-full-%s.pdf" % uuid.uuid4().hex[:8]
    mem.executemany(
        "INSERT INTO registry_requests (id,user_id,item_id,status,doc_url) VALUES (?,?,?,?,?)",
        [(9201, user, 1, "COMPLETED", empty_name),
         (9202, user, 1, "COMPLETED", full_name)])
    mem.commit()

    class _NoCloseConn:
        def __init__(self, conn):
            self._conn = conn

        def close(self):
            pass

        def __getattr__(self, name):
            return getattr(self._conn, name)

    os.makedirs(reg_mod.REGISTRY_DOCUMENT_ROOT, exist_ok=True)
    p_empty = os.path.join(reg_mod.REGISTRY_DOCUMENT_ROOT, empty_name)
    p_full = os.path.join(reg_mod.REGISTRY_DOCUMENT_ROOT, full_name)
    with open(p_empty, "wb") as fh:
        fh.write(b"")
    with open(p_full, "wb") as fh:
        fh.write(b"%PDF-1.4 qa registry")

    real_get_connection = reg_mod.get_connection
    reg_mod.get_connection = lambda *a, **kw: _NoCloseConn(mem)
    try:
        # 대조군이 200이어야 이 검사가 의미를 갖는다(둘 다 404면 경로가 틀린 것이다).
        r = client.get("/api/v1/registry-requests/9202/download", headers=headers)
        check("대조군: 내용이 있는 등기부는 200", r.status_code, 200)
        check_true("대조군: 실제 내용이 실려 온다", r.content.startswith(b"%PDF"), r.content[:20])

        r0 = client.get("/api/v1/registry-requests/9201/download", headers=headers)
        check("0바이트 등기부는 404(빈 200이 아니다)", r0.status_code, 404)
        check_true("빈 본문을 200으로 주지 않는다", not (r0.status_code == 200 and not r0.content),
                   (r0.status_code, len(r0.content)))
    finally:
        reg_mod.get_connection = real_get_connection
        mem.close()
        for p in (p_empty, p_full):
            try:
                os.remove(p)
            except OSError:
                pass


# ---------------------------------------------------------------------------
# 4. 파일을 서빙하는 모든 경로가 **같은 "있다" 정의**를 쓴다 (2026-08-14 신설)
#
# §2/§3은 각 엔드포인트의 동작을 고정한다. 이 검사는 **새 서빙 경로가 생겼을 때**를 막는다.
# 세 번째 FileResponse가 추가되면서 크기 검사를 빠뜨리면 같은 결함이 또 생긴다 —
# 실제로 registry.py가 documents.py보다 뒤늦게 그 상태였다.
# ---------------------------------------------------------------------------
def test_all_file_serving_paths_check_size():
    print("\n--- 4. 모든 파일 서빙 경로가 크기를 검사하는가 ---")
    import glob
    import re

    serving = []
    for path in sorted(glob.glob(os.path.join(REPO_ROOT, "api", "**", "*.py"), recursive=True)):
        src = open(path, encoding="utf-8-sig").read()
        # 주석이 아니라 실제 호출만 센다.
        code = "\n".join(l.split("#")[0] for l in src.splitlines())
        if re.search(r"\bFileResponse\s*\(", code):
            serving.append((os.path.relpath(path, REPO_ROOT), code))

    check_true("파일을 서빙하는 경로를 찾았다", len(serving) >= 2, [s[0] for s in serving])
    missing = [rel for rel, code in serving if "getsize" not in code]
    check("모든 서빙 경로가 0바이트를 거른다", missing, [])
    print("    서빙 경로: %s" % ", ".join(rel for rel, _ in serving))

    # `exists()`만으로 서빙을 판단하면 디렉터리도 통과한다 — isfile 을 쓰는지도 본다.
    no_isfile = [rel for rel, code in serving if "isfile" not in code]
    check("모든 서빙 경로가 isfile로 판단한다(디렉터리 통과 방지)", no_isfile, [])

    # ── 쓰는 쪽과 읽는 쪽이 같은 정의를 쓰는가 ────────────────────────────
    #
    # `api/v1/admin.py:_require_existing_registry_document()`의 docstring은
    # "검사 방식은 다운로드 경로와 **똑같이** 맞춘다"고 약속한다. 그런데 그 약속을
    # **강제하는 것이 아무것도 없었고**, 실제로 어긋났다(둘 다 0바이트를 통과시켰다).
    #
    # 더 위험한 것은 한쪽만 고칠 때다. 다운로드만 조이면 admin은 COMPLETED를 허용하는데
    # 사용자는 404를 받는다 — Sprint 95가 없앤 "등록은 됐는데 못 받는" 상태가 되돌아온다.
    # (이 검사는 그 사고를 실제로 겪고 나서 붙였다.)
    admin_src = open(os.path.join(REPO_ROOT, "api", "v1", "admin.py"),
                     encoding="utf-8-sig").read()
    admin_code = "\n".join(l.split("#")[0] for l in admin_src.splitlines())
    idx = admin_code.find("def _require_existing_registry_document")
    check_true("admin의 등기부 문서 검사 함수를 찾았다", idx >= 0, idx)
    if idx >= 0:
        # 함수 본문만 잘라 본다(다음 최상위 def 까지).
        rest = admin_code[idx:]
        nxt = rest.find("\ndef ", 1)
        body = rest[:nxt if nxt > 0 else len(rest)]
        check_true("admin도 0바이트를 거부한다(다운로드와 같은 정의)",
                   "getsize" in body,
                   "admin이 0바이트를 통과시키면 COMPLETED인데 다운로드는 404가 된다")
        check_true("admin도 isfile로 판단한다", "isfile" in body, body[-200:])

    # ── "문서가 있다"를 판단하는 **모든** 자리가 같은 정의를 쓰는가 ──────────
    #
    # 서빙(읽기)과 admin(쓰기) 말고도 판정하는 곳이 하나 더 있다 —
    # `repair_document_status.py:document_exists()`가 디스크를 보고 `document_status`를
    # READY로 바꾼다. 즉 **화면 상태를 정하는 쓰기 경로**다.
    #
    # 여기가 느슨하면(0바이트를 "있다"로 보면) 그 함수 자신의 주석이 예고한 상태가 된다:
    # **화면은 "수집완료", 실제 다운로드는 404.** 이 스크립트의 목적이 바로 그 불일치를
    # 없애는 것이므로 기준이 다르면 목적과 반대로 동작한다.
    #
    # 기준은 하나뿐이어야 한다 — `crawler/doc_paths.py:doc_exists()`.
    DECIDERS = [
        (os.path.join("crawler", "doc_paths.py"), "doc_exists"),
        ("repair_document_status.py", "document_exists"),
    ]
    for rel, fname in DECIDERS:
        path = os.path.join(REPO_ROOT, rel)
        if not os.path.exists(path):
            check_true("%s 가 존재한다" % rel, False, path)
            continue
        src = open(path, encoding="utf-8-sig").read()
        code = "\n".join(l.split("#")[0] for l in src.splitlines())
        i = code.find("def %s" % fname)
        check_true("%s:%s 를 찾았다" % (rel, fname), i >= 0, i)
        if i < 0:
            continue
        rest = code[i:]
        nxt = rest.find("\ndef ", 1)
        body = rest[:nxt if nxt > 0 else len(rest)]
        check_true("%s:%s 가 0바이트를 '없음'으로 본다" % (rel, fname),
                   "getsize" in body,
                   "이 자리가 느슨하면 화면은 '수집완료'인데 다운로드는 404가 된다")


def test_success_is_never_recorded_without_evidence():
    """수집기가 `success=True` 를 쓰는 **모든 자리**가 실체를 함께 알리는가 (Sprint 217).

    ## 왜 구조 검사인가

    BUGS #144 는 시나리오 하나를 끝까지 흘려보내다 나왔다 — `collect_spec()` 의
    "이미 존재. 스킵" 분기가 `success=True` 만 쓰고 `files_saved` 는 빈 채로 돌려줬고,
    그 빈 목록 때문에 `_record_doc_raw()` 가 실체 기록을 통째로 건너뛰었다
    (파일은 있는데 `doc_raw` 0행, 화면은 READY, **다음 수집도 같은 분기라 영구**).

    같은 모양의 분기가 두 수집기에 **11곳** 있다. 하나를 고쳤다고 나머지가 안전하다는
    보장은 없고, 새 분기가 생길 때 조용히 되돌아갈 수도 있다. 그래서 시나리오가 아니라
    **모양**을 건다.

    ## 규칙

        같은 문장 목록(같은 분기) 안에서 `result["success"] = True` 를 쓰면,
        그 목록 어딘가에 `files_saved` / `images` / `no_asset` 중 하나도 함께 있어야 한다.

    `no_asset` 을 증거로 인정하는 이유: "법원에 자산이 없다"는 **저장할 것이 없다는
    사실 자체가 결과**다(사진 미제공 물건이 실제로 있다). 그것까지 실패로 뒤집으면
    재시도 예산만 태운다.

    ## 이 검사가 못 보는 것 (적어 둔다)

    정적 검사라 **실행 순서와 도달 가능성은 보지 않는다.** 증거가 같은 분기 안에
    "있기만" 하면 통과한다. 실제로 그 값이 옳은지는 fixture 가 본다
    (`test_asset_pipeline.py` 12-G/H/I/J). 이 검사는 **빠뜨림**을 잡는 그물이다.
    """
    print(chr(10) + "--- 5. 성공 기록에는 실체가 따라붙는가 (구조 검사) ---")
    import ast

    TARGETS = [os.path.join("crawler", "doc_crawler.py"),
               os.path.join("crawler", "image_crawler.py")]
    EVIDENCE = ("files_saved", "images", "no_asset")

    def result_key(node):
        """`result["<키>"]` 이면 그 키, 아니면 None."""
        if (isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name)
                and node.value.id == "result"):
            sl = node.slice
            if isinstance(sl, ast.Constant) and isinstance(sl.value, str):
                return sl.value
        return None

    def statement_lists(fn):
        """함수 안의 모든 **문장 목록**(본문/분기별 suite)을 모은다."""
        found = []

        def walk(node):
            for _, val in ast.iter_fields(node):
                if isinstance(val, list) and val and isinstance(val[0], ast.stmt):
                    found.append(val)
                    for st in val:
                        walk(st)
                elif isinstance(val, ast.AST):
                    walk(val)
        walk(fn)
        return found

    flagged = []
    checked = 0
    for rel in TARGETS:
        path = os.path.join(REPO_ROOT, rel)
        check_true("%s 가 존재한다" % rel, os.path.exists(path), path)
        if not os.path.exists(path):
            continue
        tree = ast.parse(open(path, encoding="utf-8-sig").read())
        for fn in [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]:
            for lst in statement_lists(fn):
                keys = set()
                success_lines = []
                for st in lst:
                    if isinstance(st, ast.Assign) and len(st.targets) == 1:
                        key = result_key(st.targets[0])
                        if not key:
                            continue
                        keys.add(key)
                        if (key == "success" and isinstance(st.value, ast.Constant)
                                and st.value.value is True):
                            success_lines.append(st.lineno)
                for ln in success_lines:
                    checked += 1
                    if not (keys & set(EVIDENCE)):
                        flagged.append("%s:%s:%d" % (rel, fn.name, ln))

    # 검사기 자신이 눈이 멀지 않았는지부터 본다 — 0곳을 훑고 "이상 없음"이라고
    # 말하는 것이 이 저장소가 반복해 경계해 온 실패 방식이다.
    check_true("success=True 를 쓰는 자리를 실제로 찾았다", checked >= 8, checked)
    check("★ 실체 없이 성공을 기록하는 자리", sorted(set(flagged)), [])
    print("    훑은 자리 %d곳 / 대상 파일 %d개" % (checked, len(TARGETS)))


def run():
    print("=" * 60)
    print("false success 회귀 테스트 (Sprint 98)")
    print("=" * 60)

    test_registry_orphan_visibility()
    test_zero_byte_document_is_not_served()
    test_zero_byte_registry_document_is_not_served()
    test_all_file_serving_paths_check_size()
    test_success_is_never_recorded_without_evidence()

    print("\n" + "=" * 60)
    if failures:
        print("FAILED (%d): %s" % (len(failures), ", ".join(failures)))
        return 1
    print("ALL FALSE-SUCCESS TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(run())
