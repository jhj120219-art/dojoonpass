# -*- coding: utf-8 -*-
"""Admin Secret 계약 회귀 (2026-08-20 Sprint 234 신설).

## 왜 이 파일이 있나

이 환경에서 `ADMIN_API_KEY` / `SUPER_ADMIN_API_KEY` 가 **또** 사라졌다
(`.env` 변동 4회째: 08-08 있음 -> 08-13 없음 -> 08-16 있음 -> 08-20 없음).
그 결과 `/api/v1/admin/*` 13개 라우트가 전부 500 이다.

`test_api_regression.py` 31-B 가 **"두 키가 모두 없으면 500"** 과 **"되돌리면 200"** 은
이미 잠그고 있다. 비어 있던 것은 그 사이의 상태들이다.

    잘못된 키를 줬을 때                  -> 403 이어야 한다 (500 도 200 도 아니다)
    ADMIN 만 있고 SUPER_ADMIN 이 없을 때  -> 등급 분리가 실제로 되는가
    Secret 이 없을 때 **일반 사용자 API** -> 영향을 받으면 안 된다

마지막 줄이 이 파일의 핵심이다. Admin 키는 운영자용인데, 그것이 없다고
**로그인 사용자의 관심물건/검색이 같이 죽으면** 장애 범위가 완전히 달라진다.

## 원칙

`.env` 는 **읽지도 쓰지도 않는다.** 키는 이 프로세스 환경에만 주입하고 끝나면 되돌린다
(`test_api_regression.py` 가 쓰는 것과 같은 방식). 운영 Secret 을 만들지 않는다.

    python test_admin_secret_contract.py
"""
import io
import os
import secrets
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

# ---------------------------------------------------------------------------
# 이 프로세스 안에서만 유효한 합성 키. 운영 값이 아니다.
# `api/auth.py` 가 모듈 최상단에서 JWT 비밀값을 한 번만 읽으므로 import 전에 넣는다.
# ---------------------------------------------------------------------------
TEST_ADMIN = "qa-admin-" + secrets.token_hex(12)
TEST_SUPER = "qa-super-" + secrets.token_hex(12)
if not os.getenv("SUPABASE_JWT_SECRET"):
    os.environ["SUPABASE_JWT_SECRET"] = "qa-jwt-" + secrets.token_hex(16)

from fastapi.testclient import TestClient          # noqa: E402
from jose import jwt                               # noqa: E402
import api_server                                  # noqa: E402
from api.auth import SUPABASE_JWT_SECRET           # noqa: E402

client = TestClient(api_server.app)
failures = []


def check(name, actual, expected):
    ok = actual == expected
    print("[%s] %s: %r (expected %r)" % ("PASS" if ok else "FAIL", name, actual, expected))
    if not ok:
        failures.append(name)


def check_true(name, cond, detail=""):
    print("[%s] %s%s" % ("PASS" if cond else "FAIL", name, "" if cond else " -- " + str(detail)))
    if not cond:
        failures.append(name)


class Keys:
    """관리자 키를 이 프로세스 환경에만 세팅한다(끝나면 원복)."""

    def __init__(self, admin=None, super_admin=None):
        self.want = {"ADMIN_API_KEY": admin, "SUPER_ADMIN_API_KEY": super_admin}
        self.saved = {}

    def __enter__(self):
        for k, v in self.want.items():
            self.saved[k] = os.environ.get(k)
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        return self

    def __exit__(self, *a):
        for k, old in self.saved.items():
            if old is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = old


# 등급별 대표 라우트 (소스에서 확인: Depends(require_admin) / require_super_admin)
ADMIN_ROUTE = "/api/v1/admin/users"                     # require_admin
SUPER_ROUTE = "/api/v1/admin/registry-credits"          # require_super_admin (POST)


def hit(route, key=None, method="GET", json_body=None):
    h = {"X-Admin-Key": key} if key is not None else {}
    if method == "POST":
        return client.post(route, headers=h, json=json_body or {})
    return client.get(route, headers=h)


# ---------------------------------------------------------------------------
def test_no_keys_is_500_not_403():
    """두 키가 모두 없으면 **500**(서버 설정 오류)이지 403 이 아니다.

    이것은 의도된 구분이다 — 키를 안 준 것이 아니라 **서버가 설정되지 않은 것**이라
    사용자 탓처럼 보이는 403 을 주면 원인을 못 찾는다(`api/v1/admin.py` 주석).
    """
    print("\n--- 1. 키가 하나도 없을 때 ---")
    with Keys(None, None):
        for route, method in ((ADMIN_ROUTE, "GET"), (SUPER_ROUTE, "POST")):
            r = hit(route, key=None, method=method)
            check("키 없음 + 헤더 없음 %s -> 500" % route.split("/")[-1], r.status_code, 500)
            r2 = hit(route, key="qa-wrong-key", method=method)
            check("키 없음 + 헤더 있음 %s -> 500" % route.split("/")[-1], r2.status_code, 500)
            check_true("500 응답이 키 값을 흘리지 않는다",
                       TEST_ADMIN not in r2.text and TEST_SUPER not in r2.text, r2.text[:80])


def test_wrong_key_is_403_not_500():
    """키가 설정돼 있는데 **틀린 키**를 주면 403 이다.

    500(설정 오류)과 구분돼야 한다 — 운영자가 "서버가 고장났다"와 "내 키가 틀렸다"를
    구별할 수 있어야 한다. 여기가 비어 있던 자리다.
    """
    print("\n--- 2. 키는 있는데 틀린 키를 줄 때 ---")
    with Keys(TEST_ADMIN, TEST_SUPER):
        # ★ 헤더 값은 ASCII 여야 한다(httpx 가 ascii 로 인코딩한다).
        r = hit(ADMIN_ROUTE, key="qa-wrong-key")
        check("★ 틀린 키 -> 403 (500 아님)", r.status_code, 403)
        r2 = hit(ADMIN_ROUTE, key=None)
        check("★ 헤더 자체가 없음 -> 403 (500 아님)", r2.status_code, 403)
        check_true("403 응답이 정답 키를 흘리지 않는다",
                   TEST_ADMIN not in r.text, r.text[:80])
        # 맞는 키는 통과한다 — 검사가 공허하지 않다
        check("대조군: 맞는 키 -> 200", hit(ADMIN_ROUTE, key=TEST_ADMIN).status_code, 200)


def test_role_separation_is_real():
    """ADMIN 키로 SUPER_ADMIN 전용 작업을 하면 403 이다.

    ADMIN 만 설정하고 SUPER_ADMIN 을 비워 두면, ADMIN 라우트는 열리고
    SUPER 라우트는 막혀야 한다. 둘이 같이 열리면 **과금 조작(환불 등)이 하위 등급에
    노출**된다.
    """
    print("\n--- 3. 등급 분리 ---")
    with Keys(TEST_ADMIN, TEST_SUPER):
        check("ADMIN 키로 ADMIN 라우트 -> 200",
              hit(ADMIN_ROUTE, key=TEST_ADMIN).status_code, 200)
        r = hit(SUPER_ROUTE, key=TEST_ADMIN, method="POST",
                json_body={"user_id": "qa-x", "reason_type": "TEST", "amount": 1})
        check("★ ADMIN 키로 SUPER 전용 라우트 -> 403", r.status_code, 403)
        # SUPER 키는 ADMIN 라우트도 쓸 수 있어야 한다(상위 등급 포함 관계)
        check("SUPER 키로 ADMIN 라우트 -> 200",
              hit(ADMIN_ROUTE, key=TEST_SUPER).status_code, 200)

    # ADMIN 만 있고 SUPER 가 아예 없을 때
    with Keys(TEST_ADMIN, None):
        check("SUPER 미설정 + ADMIN 키로 ADMIN 라우트 -> 200",
              hit(ADMIN_ROUTE, key=TEST_ADMIN).status_code, 200)
        r = hit(SUPER_ROUTE, key=TEST_ADMIN, method="POST",
                json_body={"user_id": "qa-x", "reason_type": "TEST", "amount": 1})
        check("★ SUPER 미설정이어도 SUPER 라우트는 열리지 않는다 -> 403", r.status_code, 403)


def test_missing_admin_secret_does_not_break_user_apis():
    """★ 이 파일의 핵심 — Admin Secret 이 없어도 **일반 사용자 API 는 멀쩡해야 한다.**

    Admin 키는 운영자용이다. 그것이 없다고 로그인 사용자의 관심물건/검색/상세가 같이
    죽으면 장애 범위가 완전히 달라진다(운영 불편 -> 서비스 장애).

    지금 이 환경이 정확히 그 상태다(ADMIN/SUPER 둘 다 없음). 그래서 이 검사는
    **가정이 아니라 현재 상태를 그대로 확인**한다.
    """
    print("\n--- 4. Admin Secret 부재가 일반 사용자 API 에 영향을 주지 않는다 ---")
    token = jwt.encode({"sub": "qa-secret-contract"}, SUPABASE_JWT_SECRET, algorithm="HS256")
    auth = {"Authorization": "Bearer " + token}

    with Keys(None, None):          # Admin 키를 완전히 없앤 상태에서
        # 공개 API
        for path in ("/api/v1/search?size=1&include_closed=true",
                     "/api/v1/stats", "/api/v1/plans"):
            check("공개 API 정상: %s" % path.split("?")[0], hit(path).status_code, 200)

        # 인증 필요 API — 토큰이 있으면 200 이어야 한다
        for path in ("/api/v1/favorites", "/api/v1/recent-items",
                     "/api/v1/search-presets", "/api/v1/subscriptions/me"):
            r = client.get(path, headers=auth)
            check("★ 로그인 사용자 API 정상: %s" % path, r.status_code, 200)

        # 토큰이 없으면 401 — Admin 키 부재가 401 을 500 으로 바꾸지 않는다
        for path in ("/api/v1/favorites", "/api/v1/recent-items"):
            check("토큰 없으면 401(500 아님): %s" % path,
                  client.get(path).status_code, 401)

        # Admin 만 500 이다 — 대조군(검사가 공허하지 않다)
        check("대조군: 같은 조건에서 Admin 은 500", hit(ADMIN_ROUTE).status_code, 500)


def test_admin_routes_all_share_the_same_guard():
    """Admin 라우트 **전체**가 같은 가드를 지나는가 (하드코딩 목록을 믿지 않는다).

    OpenAPI 스키마에서 `/admin/` 라우트를 전부 뽑아, 키가 없을 때 **하나도 빠짐없이**
    500 인지 본다. 한 라우트만 가드를 빠뜨리면 **키 없이 열리는 관리자 API** 가 된다.
    """
    print("\n--- 5. Admin 라우트 전체가 같은 가드를 지난다 ---")
    spec = client.get("/openapi.json").json()
    admin_paths = [(p, m) for p, ops in spec.get("paths", {}).items()
                   if "/admin/" in p for m in ops
                   if m.upper() in ("GET", "POST", "PATCH", "DELETE", "PUT")]
    check_true("Admin 라우트를 실제로 찾았다(검사가 공허하지 않다)",
               len(admin_paths) >= 10, len(admin_paths))

    def concrete(p):
        return (p.replace("{user_id}", "qa-x").replace("{request_id}", "1")
                 .replace("{payment_id}", "1").replace("{webhook_id}", "1")
                 .replace("{subscription_id}", "1"))

    leaked = []
    with Keys(None, None):
        for p, m in admin_paths:
            cp = concrete(p)
            if "{" in cp:
                continue
            r = (client.post(cp, json={}) if m.upper() == "POST"
                 else client.patch(cp, json={}) if m.upper() == "PATCH"
                 else client.delete(cp) if m.upper() == "DELETE"
                 else client.get(cp))
            # 키가 없으면 500 이어야 한다. 200 이면 **키 없이 열린 것**이다.
            if r.status_code != 500:
                leaked.append("%s %s -> %d" % (m.upper(), p, r.status_code))
    check("★ 키 없이 500 이 아닌 Admin 라우트", leaked, [])
    print("    검사한 Admin 라우트 %d개" % len(admin_paths))


def test_boot_warns_when_admin_keys_are_missing():
    """관리자 키가 없을 때 **부팅 시점에** 경고를 남기는가 (2026-08-21 Sprint 246).

    ## 왜 필요한가

    두 키가 모두 없으면 Admin API 16개가 전부 500 이다(위 `test_no_keys_is_500_not_403`
    가 고정하는 의도된 동작). 문제는 **그걸 알게 되는 시점**이다 - 예전에는 운영자가
    Admin 화면을 열어 500 을 볼 때까지 서버가 아무 말도 하지 않았다.

    이번 세션에서 고친 것들과 같은 계열이다: **조용한 실패를 시끄럽게 만든다.**

    ## 값이 새지 않는지도 함께 본다

    키 값이 로그에 들어가면 로그 유출이 곧 관리자 권한 유출이다.
    경고에는 **설정 여부만** 담겨야 한다.
    """
    print("\n--- 6. 키 미설정 시 부팅 경고 (Sprint 246) ---")
    import logging
    from api.v1 import admin as admin_mod

    saved = (os.environ.pop("ADMIN_API_KEY", None),
             os.environ.pop("SUPER_ADMIN_API_KEY", None))

    class Grab(logging.Handler):
        def __init__(self):
            logging.Handler.__init__(self)
            self.records = []

        def emit(self, record):
            self.records.append(record)

    grab = Grab()
    lg = logging.getLogger(admin_mod.__name__)
    lg.addHandler(grab)
    prev_level = lg.level
    lg.setLevel(logging.WARNING)
    try:
        # (1) 두 키 모두 없음 -> 경고한다
        warned = admin_mod.warn_if_admin_keys_missing()
        check("★ 두 키가 모두 없으면 경고를 남긴다", warned, True)
        msgs = [r.getMessage() for r in grab.records if r.levelno >= logging.WARNING]
        check("★ 경고가 실제로 로그로 나간다(반환값만 바꾼 게 아니다)", len(msgs), 1)
        if msgs:
            check_true("경고에 원인이 적혀 있다(어떤 환경변수인지)",
                       "ADMIN_API_KEY" in msgs[0], msgs[0][:120])
            check_true("경고에 결과가 적혀 있다(무엇이 깨지는지)",
                       "500" in msgs[0], msgs[0][:120])

        # (2) ★ **한쪽만** 없어도 경고한다 (2026-08-25 BUGS #205)
        #
        #   예전 이 자리는 "키가 하나라도 있으면 조용하다" 를 고정하고 있었다.
        #   그 계약은 뒤집혔고, 이 검사는 **뒤집힌 것을 따라오지 못한 채 남아** 있었다.
        #   `warn_if_admin_keys_missing()` 의 docstring 이 이유를 실측으로 적어 둔다:
        #
        #       둘 다 없음      전부 500    -> 어차피 즉시 드러난다
        #       SUPER 만 없음   SUPER 전용 라우트가 **403**   <- 조용하다
        #       ADMIN 만 없음   ADMIN 등급 키가 **403**       <- 조용하다
        #
        #   403 은 "권한 부족"과 구별되지 않으므로 운영자는 설정 누락을 등급 문제로
        #   읽는다. **시끄러운 쪽이 아니라 조용한 쪽에 경고가 필요하다.**
        secret = "qa-boot-warn-not-a-real-key-000"
        os.environ["ADMIN_API_KEY"] = secret
        grab.records = []
        warned2 = admin_mod.warn_if_admin_keys_missing()
        check("★ SUPER 만 없어도 경고한다(403 이 조용히 묻히는 쪽)", warned2, True)
        msgs2 = [r.getMessage() for r in grab.records if r.levelno >= logging.WARNING]
        check("그때 경고가 정확히 한 줄 나간다", len(msgs2), 1)
        if msgs2:
            check_true("어느 키인지 적혀 있다(SUPER)",
                       "SUPER_ADMIN_API_KEY" in msgs2[0], msgs2[0][:120])
            check_true("무엇이 깨지는지 적혀 있다(403)",
                       "403" in msgs2[0], msgs2[0][:120])
            check_true("★ 경고에 키 **값**이 들어 있지 않다",
                       secret not in msgs2[0], msgs2[0][:120])

        # (3) 반대쪽도 같다 - ADMIN 만 없을 때
        del os.environ["ADMIN_API_KEY"]
        os.environ["SUPER_ADMIN_API_KEY"] = secret
        grab.records = []
        warned3 = admin_mod.warn_if_admin_keys_missing()
        check("★ ADMIN 만 없어도 경고한다", warned3, True)
        msgs3 = [r.getMessage() for r in grab.records if r.levelno >= logging.WARNING]
        check("그때도 경고는 한 줄이다", len(msgs3), 1)
        if msgs3:
            check_true("어느 키인지 적혀 있다(ADMIN)",
                       "ADMIN_API_KEY" in msgs3[0], msgs3[0][:120])
            check_true("★ 경고에 키 **값**이 들어 있지 않다",
                       secret not in msgs3[0], msgs3[0][:120])

        # (4) 대조군 - **둘 다 있을 때만** 조용하다. 이게 없으면 위 검사들은
        #     "항상 경고한다" 는 고장난 구현도 통과시킨다.
        os.environ["ADMIN_API_KEY"] = secret
        grab.records = []
        warned4 = admin_mod.warn_if_admin_keys_missing()
        check("★ 두 키가 모두 있으면 경고하지 않는다", warned4, False)
        check("그때 로그도 남기지 않는다(잡음 방지)", len(grab.records), 0)

        os.environ.pop("ADMIN_API_KEY", None)
        os.environ.pop("SUPER_ADMIN_API_KEY", None)
    finally:
        lg.removeHandler(grab)
        lg.setLevel(prev_level)
        for k, v in zip(("ADMIN_API_KEY", "SUPER_ADMIN_API_KEY"), saved):
            os.environ.pop(k, None)
            if v is not None:
                os.environ[k] = v

    # --- 키 값이 로그로 새지 않는가 ------------------------------------------
    #
    # ★ 이건 **동작으로는 검사할 수 없다.** 이 함수는 두 키가 **모두 빌 때만** 경고하니,
    #   경고가 나가는 순간에는 흘릴 값 자체가 존재하지 않는다. 처음엔 "로그에 키 값이
    #   없다"를 런타임으로 확인하려 했는데, 그 시점엔 두 환경변수가 비어 있어 **무엇을
    #   넣어도 통과하는 공허한 검사**였다(2026-08-21 mutation 으로 확인하고 걷어냈다).
    #
    #   그래서 소스를 AST 로 본다. 문자열 검색으로는 안 된다 - 경고 문구 자체가
    #   "ADMIN_API_KEY" 라는 **이름**을 정당하게 포함하기 때문이다. 이름이 아니라
    #   **값을 읽어 오는 호출**(`os.getenv`/`os.environ`)이 경고 인자에 있는지를 본다.
    #   미래의 편집이 "친절하게" 현재 설정값을 끼워 넣는 것을 막는다.
    import ast

    src_admin = io.open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                     "api", "v1", "admin.py"),
                        encoding="utf-8-sig").read()
    fn = None
    for node in ast.walk(ast.parse(src_admin)):
        if isinstance(node, ast.FunctionDef) and node.name == "warn_if_admin_keys_missing":
            fn = node
    check_true("검사가 공허하지 않다(함수를 찾았다)", fn is not None,
               "-> 이름이 바뀌었으면 이 검사도 고쳐라")

    warn_calls = []
    if fn is not None:
        for node in ast.walk(fn):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "warning"):
                warn_calls.append(node)
    # 경고 갈래는 셋이다(둘 다 없음 / SUPER 만 없음 / ADMIN 만 없음, BUGS #205).
    # 숫자를 고정하는 이유는 "몇 개인지"가 아니라 **하나라도 찾았는지**와
    # 갈래가 조용히 사라지지 않았는지를 함께 보기 위해서다.
    check("검사가 공허하지 않다(경고 호출을 찾았다)", len(warn_calls), 3)

    reads_value = []
    for call in warn_calls:
        for sub in ast.walk(call):
            if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute) \
                    and sub.func.attr == "getenv":
                reads_value.append("os.getenv")
            if isinstance(sub, ast.Attribute) and sub.attr == "environ":
                reads_value.append("os.environ")
    check_true("★ 경고 인자에서 키 **값**을 읽지 않는다", not reads_value,
               "-> %s 를 경고에 끼워 넣었다. 로그 유출이 곧 관리자 권한 유출이 된다"
               % sorted(set(reads_value)))

    # 부팅 경로가 실제로 이 함수를 부르는가 - 안 부르면 위 검사가 전부 무의미하다
    src = io.open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "api_server.py"), encoding="utf-8-sig").read()
    code = "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("#"))
    check_true("★ api_server.py 가 부팅 시 이 함수를 호출한다",
               "warn_if_admin_keys_missing()" in code,
               "-> 함수만 있고 아무도 안 부르면 경고는 영원히 안 나온다")


def run():
    print("=" * 62)
    print(" Admin Secret 계약 (Sprint 234)")
    print("=" * 62)
    test_no_keys_is_500_not_403()
    test_wrong_key_is_403_not_500()
    test_role_separation_is_real()
    test_missing_admin_secret_does_not_break_user_apis()
    test_admin_routes_all_share_the_same_guard()
    test_boot_warns_when_admin_keys_are_missing()

    print("\n" + "=" * 62)
    if failures:
        print("FAILED (%d): %s" % (len(failures), ", ".join(failures)))
        return 1
    print("ALL ADMIN SECRET CONTRACT TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(run())
