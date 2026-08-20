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


def run():
    print("=" * 62)
    print(" Admin Secret 계약 (Sprint 234)")
    print("=" * 62)
    test_no_keys_is_500_not_403()
    test_wrong_key_is_403_not_500()
    test_role_separation_is_real()
    test_missing_admin_secret_does_not_break_user_apis()
    test_admin_routes_all_share_the_same_guard()

    print("\n" + "=" * 62)
    if failures:
        print("FAILED (%d): %s" % (len(failures), ", ".join(failures)))
        return 1
    print("ALL ADMIN SECRET CONTRACT TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(run())
