"""id 범위 경계 **전 라우트 스윕** — 2026-08-17 Sprint 154 신설.

## 왜 목록이 아니라 스윕인가

이 결함은 **세 번 연속 "빠뜨린 파일"에서 나왔다.**

```
Sprint 144   search / item / documents / images 를 고쳤다   <- 4개 파일만
Sprint 153   admin.py 가 빠져 있었다                        (6개 핸들러 500)
Sprint 154   favorites / registry / search_presets / payments 도 빠져 있었다  (8곳 500)
```

매번 "이번엔 다 고쳤다"고 적었지만 매번 남아 있었다. 원인은 방법이다 —
**사람이 파일을 나열해서 고치면 나열에서 빠진 것을 영원히 못 본다.**

그래서 이 파일은 핸들러를 나열하지 않는다. **OpenAPI 스키마에서 라우트를 뽑아**
경로변수를 범위 밖 정수로 채워 전부 두드린다. 새 라우트가 추가되면 **자동으로**
사정권에 들어온다 — 이 파일을 고치지 않아도 된다.

## 무엇이 문제였나

파이썬 int 는 임의 정밀도라 `2**63` 이 그대로 쿼리까지 내려가고 sqlite3 이 터진다.

```
OverflowError: Python int too large to convert to SQLite INTEGER  ->  500
```

Sprint 154 에서 실측한 **로그인 사용자만 있으면 되는** 500 (관리자 권한 불필요):

```
POST   /api/v1/favorites                  {"item_id": 2**63}   -> 500
POST   /api/v1/registry-requests          {"item_id": 2**63}   -> 500
DELETE /api/v1/favorites/{item_id}                             -> 500
DELETE /api/v1/search-presets/{preset_id}                      -> 500
GET    /api/v1/registry-requests/{request_id}                  -> 500
GET    /api/v1/registry-requests/{request_id}/download         -> 500
GET    /api/v1/payments/{payment_id}                           -> 500
GET    /api/v1/payments/{payment_id}/logs                      -> 500
```

Sprint 153 의 admin 6곳보다 **심각도가 높다** — 관리자 키가 필요 없다.

## 왜 인증을 걸고 두드리는가

처음 스윕은 무인증으로 돌렸고 5xx 0건이었다. **그 0건은 거짓이었다** —
사용자 라우트가 쿼리에 닿기 전에 401 로 끊겼기 때문이다. 인증을 통과시키자
같은 라우트에서 즉시 500 이 나왔다. 경계 검사는 **인증 뒤에** 있으므로
인증을 통과한 상태로 두드려야 의미가 있다.

## 운영 DB 를 건드리지 않는다

POST 는 쓰기 경로다. 그래서 `auction.db` 를 **임시 디렉터리에 복사**하고
`storage.database.DB_PATH` 를 그 사본으로 돌린 뒤에만 두드린다. 토큰과 Admin 키는
합성값이다 — 실제 credential 을 읽지도 출력하지도 않는다.

    python test_id_bounds_sweep.py
"""
import contextlib
import io
import os
import re
import secrets
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

_ADMIN_KEY = "qa-sweep-" + secrets.token_hex(16)
os.environ["ADMIN_API_KEY"] = _ADMIN_KEY
os.environ["SUPER_ADMIN_API_KEY"] = _ADMIN_KEY
if not os.getenv("SUPABASE_JWT_SECRET"):
    os.environ["SUPABASE_JWT_SECRET"] = "qa-sweep-" + secrets.token_hex(16)

# SQLite INTEGER 경계 밖. 문자열로 넣는 이유는 URL 경로에 그대로 실어야 하기 때문이다.
OUT_OF_RANGE = [
    ("2^63 (최대+1)", str(2 ** 63)),
    ("-2^63-1 (최소-1)", str(-2 ** 63 - 1)),
    ("2^200", str(2 ** 200)),
]
# 경계 자체는 **범위 안**이다 — 가드가 여기까지 막으면 off-by-one 이다.
BOUNDARY_IN_RANGE = str(2 ** 63 - 1)

failures = []
_tmpdir = None


def check(name, actual, expected):
    ok = actual == expected
    print("[%s] %s: %r (expected %r)" % ("PASS" if ok else "FAIL", name, actual, expected))
    if not ok:
        failures.append(name)


def check_true(name, cond, detail=""):
    print("[%s] %s%s" % ("PASS" if cond else "FAIL", name, ("" if cond else " -- " + str(detail))))
    if not cond:
        failures.append(name)


def _setup_temp_db():
    """운영 DB 사본으로 갈아끼운다. POST 가 쓰기를 하므로 필수다."""
    global _tmpdir
    import storage.database as dbmod
    _tmpdir = tempfile.mkdtemp(prefix="qa_idsweep_")
    tmpdb = os.path.join(_tmpdir, "scratch.db")
    # 온라인 백업 스냅샷 - 워커가 쓰는 중이어도 일관된 사본을 만든다
    # (shutil.copy2 는 찢어질 수 있다. 사유: storage/database.py:snapshot_live_db)
    dbmod.snapshot_live_db(tmpdb)
    dbmod.DB_PATH = tmpdb
    return tmpdb


def _client():
    import api_server
    from fastapi.testclient import TestClient
    with contextlib.redirect_stderr(io.StringIO()):
        return TestClient(api_server.app, raise_server_exceptions=False)


def _user_headers():
    from jose import jwt
    import api.auth as auth_mod
    token = jwt.encode({"sub": "qa-idsweep-user"}, auth_mod.SUPABASE_JWT_SECRET, algorithm="HS256")
    return {"Authorization": "Bearer " + token}


def _headers_for(path, user_headers):
    """admin 경로는 Admin 키로, 나머지는 사용자 토큰으로 두드린다.

    ★ 인증을 통과시키는 것이 핵심이다 — 무인증으로 두드리면 401 이 쿼리를 가려
      "5xx 0건"이라는 **거짓 안전 신호**가 나온다(실제로 처음에 그렇게 속았다).
    """
    if "/admin/" in path:
        return {"X-Admin-Key": _ADMIN_KEY}
    return dict(user_headers)


def _routes_with_path_params():
    import api_server
    spec = api_server.app.openapi()
    out = []
    for path, ops in spec.get("paths", {}).items():
        if "{" not in path:
            continue
        for method in ops:
            if method.upper() in ("GET", "DELETE"):
                out.append((method.upper(), path))
    return sorted(set(out))


# ---------------------------------------------------------------------------
# 1. ★★ 전 라우트 스윕 — 범위 밖 id 로 5xx 가 하나도 나오면 안 된다
# ---------------------------------------------------------------------------
def test_no_5xx_anywhere():
    print("\n--- 1. 전 라우트 경로변수 스윕 ---")
    client = _client()
    uh = _user_headers()
    routes = _routes_with_path_params()
    check_true("스윕 대상 라우트를 찾았다", len(routes) >= 8, routes)

    offenders = []
    total = 0
    for method, path in routes:
        headers = _headers_for(path, uh)
        for label, value in OUT_OF_RANGE:
            url = path
            for name in re.findall(r"\{(\w+)\}", path):
                url = url.replace("{%s}" % name, value)
            with contextlib.redirect_stderr(io.StringIO()):
                try:
                    r = client.request(method, url, headers=headers)
                    code = r.status_code
                except Exception as exc:  # noqa: BLE001 - 예외 누출도 결함이다
                    code = "EXC:" + type(exc).__name__
            total += 1
            if code == "EXC" or (isinstance(code, int) and code >= 500) or isinstance(code, str):
                offenders.append("%s %s [%s] -> %s" % (method, path, label, code))
    print("      두드린 횟수: %d" % total)
    check("★★ 5xx/예외를 내는 라우트", offenders, [])


# ---------------------------------------------------------------------------
# 2. 본문 필드도 같은 계열이다
# ---------------------------------------------------------------------------
def test_body_item_id_bounds():
    print("\n--- 2. 본문 item_id 경계 ---")
    client = _client()
    uh = _user_headers()
    for path in ("/api/v1/favorites", "/api/v1/registry-requests"):
        for label, value in OUT_OF_RANGE:
            with contextlib.redirect_stderr(io.StringIO()):
                r = client.post(path, headers=uh, json={"item_id": int(value)})
            check_true("★ POST %s item_id=%s -> 5xx 아님" % (path, label),
                       r.status_code < 500, r.status_code)
            # 존재할 수 없는 물건이므로 404 가 정확한 답이다.
            check("★ POST %s item_id=%s" % (path, label), r.status_code, 404)


# ---------------------------------------------------------------------------
# 3. 대조군 — 가드가 **의미를 바꾸지 않았다**
# ---------------------------------------------------------------------------
def test_in_range_behaviour_unchanged():
    print("\n--- 3. 범위 안 id 는 동작이 그대로다 ---")
    client = _client()
    uh = _user_headers()

    with contextlib.redirect_stderr(io.StringIO()):
        r = client.post("/api/v1/favorites", headers=uh, json={"item_id": 999999999})
    check("범위 안 미존재 물건 즐겨찾기 -> 404", r.status_code, 404)

    with contextlib.redirect_stderr(io.StringIO()):
        r = client.get("/api/v1/payments/999999999", headers=uh)
    check("범위 안 미존재 결제 -> 404", r.status_code, 404)

    # ★ 경계값 2^63-1 은 범위 **안**이므로 가드에 걸리지 않고 조회까지 가야 한다.
    with contextlib.redirect_stderr(io.StringIO()):
        r = client.get("/api/v1/payments/%s" % BOUNDARY_IN_RANGE, headers=uh)
    check("★ 경계값 2^63-1 은 통과해 조회까지 간다(off-by-one 방지)", r.status_code, 404)

    # 즐겨찾기 삭제는 error_response 봉투를 쓴다 — 범위 밖도 **같은 응답**이어야 한다.
    with contextlib.redirect_stderr(io.StringIO()):
        in_range = client.delete("/api/v1/favorites/999999999", headers=uh)
        out_range = client.delete("/api/v1/favorites/%d" % (2 ** 63), headers=uh)
    check("삭제: 범위 밖과 범위 안의 상태코드가 같다",
          out_range.status_code, in_range.status_code)


# ---------------------------------------------------------------------------
# 3-B. ★★ 쿼리 파라미터도 같은 계열이다 (Sprint 155)
#
# 경로변수와 본문을 막고 나서 **세 번째 입력면**인 쿼리 파라미터를 훑었더니 10곳이 더
# 나왔다 — admin 목록의 `page`(=`(page-1)*size` 가 OFFSET 으로 내려간다)와
# `item_id`/`payment_id` 필터다. `page` 에는 `ge=1` 하한만 있고 **상한이 없었다.**
#
# 여기도 라우트를 나열하지 않는다 — OpenAPI 에서 쿼리 파라미터를 읽어 전부 두드린다.
# ---------------------------------------------------------------------------
def test_query_params_no_5xx():
    print("\n--- 3-B. 쿼리 파라미터 스윕 ---")
    import api_server
    client = _client()
    uh = _user_headers()
    spec = api_server.app.openapi()

    hostile = [v for _, v in OUT_OF_RANGE] + ["abc", "1' OR '1'='1", "", "1.5", "-1"]
    offenders = []
    total = 0
    params_seen = 0
    for path, ops in spec.get("paths", {}).items():
        for method, op in ops.items():
            if method.upper() != "GET":
                continue
            names = [pr["name"] for pr in op.get("parameters", []) if pr.get("in") == "query"]
            if not names:
                continue
            params_seen += len(names)
            url = path
            for n in re.findall(r"\{(\w+)\}", path):
                url = url.replace("{%s}" % n, "1")
            headers = _headers_for(path, uh)
            for q in names:
                for value in hostile:
                    with contextlib.redirect_stderr(io.StringIO()):
                        try:
                            r = client.get(url, params={q: value}, headers=headers)
                            code = r.status_code
                        except Exception as exc:  # noqa: BLE001
                            code = "EXC:" + type(exc).__name__
                    total += 1
                    if not isinstance(code, int) or code >= 500:
                        offenders.append("%s?%s=%s -> %s" % (path, q, str(value)[:12], code))
    print("      쿼리 파라미터 %d개 / 요청 %d회" % (params_seen, total))
    check_true("쿼리 파라미터를 가진 라우트를 찾았다", params_seen > 0)
    check("★★ 쿼리 파라미터로 5xx 를 내는 라우트", offenders, [])


def test_pagination_still_works():
    print("\n--- 3-C. 정상 페이지네이션 회귀 ---")
    client = _client()
    headers = {"X-Admin-Key": _ADMIN_KEY}
    for url in ("/api/v1/admin/users?page=1&size=5",
                "/api/v1/admin/payments?page=2&size=10",
                "/api/v1/admin/registry-requests?page=1&size=5",
                "/api/v1/admin/payments/webhooks?page=1&size=5"):
        with contextlib.redirect_stderr(io.StringIO()):
            r = client.get(url, headers=headers)
        check("정상 페이지네이션 %s" % url.split("?")[0].replace("/api/v1/admin", ""), r.status_code, 200)

    # 범위 밖 page 는 400(조회 조건 값이므로 404 가 아니다).
    with contextlib.redirect_stderr(io.StringIO()):
        r = client.get("/api/v1/admin/users?page=%d" % (2 ** 63), headers=headers)
    check("★ 범위 밖 page -> 400", r.status_code, 400)
    check_true("사유가 담긴 메시지", "page" in r.text, r.text[:120])


# ---------------------------------------------------------------------------
# 4. 응답에 내부 정보가 새지 않는다
# ---------------------------------------------------------------------------
def test_no_internal_leak():
    print("\n--- 4. 내부 정보 노출 없음 ---")
    client = _client()
    uh = _user_headers()
    with contextlib.redirect_stderr(io.StringIO()):
        r = client.get("/api/v1/payments/%d" % (2 ** 63), headers=uh)
    for bad in ("OverflowError", "Traceback", "sqlite3", "site-packages"):
        check_true("응답에 %r 이 없다" % bad, bad not in r.text, r.text[:140])
    check_true("응답에 Admin 키가 없다", _ADMIN_KEY not in r.text)
    check_true("응답에 JWT 시크릿이 없다", os.environ["SUPABASE_JWT_SECRET"] not in r.text)


if __name__ == "__main__":
    _setup_temp_db()
    try:
        test_no_5xx_anywhere()
        test_body_item_id_bounds()
        test_in_range_behaviour_unchanged()
        test_query_params_no_5xx()
        test_pagination_still_works()
        test_no_internal_leak()
    finally:
        if _tmpdir:
            shutil.rmtree(_tmpdir, ignore_errors=True)

    print("\n" + "=" * 60)
    if failures:
        print("FAILED (%d): %s" % (len(failures), ", ".join(failures)))
        sys.exit(1)
    print("ALL ID BOUNDS SWEEP TESTS PASSED")
