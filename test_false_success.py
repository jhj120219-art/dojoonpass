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
    shutil.copy(os.path.join(REPO_ROOT, "auction.db"), test_db)

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
            "INSERT INTO auction_item (case_no, item_no, court_name, full_address, created_at)"
            " VALUES (?,?,?,?,datetime('now'))",
            ("2026타경-qa-orphan", "1", "서울중앙지방법원", "서울시 QA구 고아동 1-1"),
        ).lastrowid
        doc_name = "qa-false-success-%s.pdf" % uuid.uuid4().hex[:8]
        req_id = raw.execute(
            "INSERT INTO registry_requests"
            " (user_id, item_id, status, doc_url, requested_at, completed_at)"
            " VALUES (?,?,?,?,datetime('now'),datetime('now'))",
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


def run():
    print("=" * 60)
    print("false success 회귀 테스트 (Sprint 98)")
    print("=" * 60)

    test_registry_orphan_visibility()
    test_zero_byte_document_is_not_served()

    print("\n" + "=" * 60)
    if failures:
        print("FAILED (%d): %s" % (len(failures), ", ".join(failures)))
        return 1
    print("ALL FALSE-SUCCESS TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(run())
