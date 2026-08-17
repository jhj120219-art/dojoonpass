"""손상된 JWKS 공개키가 인증 경로를 500으로 만들지 않는가 — 2026-08-17 Sprint 152 신설.

## 왜 이 파일이 생겼나

`api/auth.py:decode_supabase_jwt()`의 docstring은 이렇게 약속한다:

    검증에 실패하면 **항상 JWTError**를 던진다. 호출부가 인증 필수(401)와 선택적 인증
    (비로그인으로 강등)을 각자 판단할 수 있어야 하기 때문이다 — 여기서 HTTPException을
    던지면 검색 같은 선택적 인증 API가 토큰 문제로 통째로 실패한다.

그 약속을 지키는 장치가 `except JOSEError -> JWTError` 정규화였다. 그런데 **jose가
JOSE 계열이 아닌 예외도 던진다**. 커버리지에서 그 줄(134-135)이 0회 실행인 것을 보고
직접 도달시켜 보다가 발견했다.

    JWKS 캐시에 구조가 깨진 공개키 -> jwt.decode() -> ValueError
      ("invalid literal for int() with base 16: ''")
    ValueError 는 JOSEError 가 아니다 -> 정규화를 그냥 통과 -> 호출부로 전파

**수정 전 실측** (TestClient, 손상 JWK 를 캐시에 주입):

    GET /api/v1/search    (선택적 인증)   500      <- 비로그인으로 강등돼야 한다
    GET /api/v1/item/1    (선택적 인증)   500      <- 〃
    GET /api/v1/favorites (인증 필수)     500      <- 401 이어야 한다

**수정 후 실측**: 각각 200 / 200 / 401.

## 왜 심각한가 — `kid`는 요청자가 고른다

공격자가 JWKS 내용을 바꿀 수는 없다. 그러나 토큰 헤더의 `kid`로 **어느 키를 쓸지
지목**한다. 그러므로 실제 JWKS 에 jose 가 못 읽는 키가 하나라도 섞이면(키 회전 중
미지원 `kty`, 부분 손상 응답 등) 그 kid 를 지목하는 것만으로 **인증 없이 500** 을
만들 수 있다. Sprint 144 가 `/api/v1/search` 에서 없앤 "인증 없이 만드는 500"과
같은 계열이다.

키가 멀쩡한 평시에는 재현되지 않는다. 그래서 더더욱 검사로 고정해 둬야 한다 —
문제가 드러나는 시점이 하필 **키 회전 중**, 즉 가장 손대기 어려운 때이기 때문이다.

## 실제 credential 을 쓰지 않는다

JWKS 는 네트워크로 받지 않고 `api.auth._jwks_keys` 캐시에 **합성 손상 키**를 직접
심는다. HS256 시크릿도 합성값이다(`test_auth_jwt.py` 와 같은 방식). 운영 DB 는
읽기만 한다(`/search`, `/item` 은 조회 전용이고 `/favorites` 는 401 로 DB 앞에서 끊긴다).

    python test_auth_jwks_robustness.py
"""
import base64
import contextlib
import io
import json
import logging
import os
import secrets
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

if not os.getenv("SUPABASE_JWT_SECRET"):
    os.environ["SUPABASE_JWT_SECRET"] = "qa-jwks-" + secrets.token_hex(16)

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


def _b64(obj):
    return base64.urlsafe_b64encode(json.dumps(obj).encode()).rstrip(b"=").decode()


def _es256_token(kid="broken-kid", sub="u1"):
    """서명은 의미 없다 — 키 파싱 단계에서 터지는 것이 이 파일의 관심사다."""
    return _b64({"alg": "ES256", "kid": kid}) + "." + _b64({"sub": sub}) + ".c2ln"


# 실제로 서로 다른 예외를 만드는 손상 형태들. ValueError 하나만 막는 수정으로는
# 부족하다는 것을 보이려고 타입이 다른 것들을 섞었다(None 값은 TypeError 를 낸다).
BROKEN_JWKS = [
    ("16진수가 아닌 x", {"kty": "EC", "crv": "P-256", "x": "!!!", "y": "???"}),
    ("x가 빈 문자열", {"kty": "EC", "crv": "P-256", "x": "", "y": ""}),
    ("지원하지 않는 kty", {"kty": "UNKNOWN", "crv": "P-256", "x": "AA", "y": "AA"}),
    ("필수 필드 누락", {"kty": "EC"}),
    ("값이 None", {"kty": "EC", "crv": None, "x": None, "y": None}),
]


@contextlib.contextmanager
def broken_key(jwk, kid="broken-kid"):
    """JWKS 캐시에 손상 키를 심는다. 네트워크를 타지 않도록 fetched_at 을 미래로 둔다."""
    import api.auth as auth_mod
    saved_keys, saved_at = auth_mod._jwks_keys, auth_mod._jwks_fetched_at
    auth_mod._jwks_keys = {kid: jwk}
    auth_mod._jwks_fetched_at = 1e18
    try:
        yield
    finally:
        auth_mod._jwks_keys, auth_mod._jwks_fetched_at = saved_keys, saved_at


def _client():
    import api_server
    from fastapi.testclient import TestClient
    with contextlib.redirect_stderr(io.StringIO()):
        # raise_server_exceptions=False 라야 500 을 **응답으로** 관찰할 수 있다.
        # True 면 예외가 테스트로 다시 던져져 500 인지 크래시인지 구분이 안 된다.
        return TestClient(api_server.app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# 1. ★ 손상 키는 종류를 불문하고 JWTError 로 정규화된다
# ---------------------------------------------------------------------------
def test_normalized_to_jwt_error():
    print("\n--- 1. 손상 JWK -> JWTError 정규화 ---")
    from jose.exceptions import JWTError
    import api.auth as auth_mod

    for label, jwk in BROKEN_JWKS:
        with broken_key(jwk):
            with contextlib.redirect_stderr(io.StringIO()):
                try:
                    auth_mod.decode_supabase_jwt(_es256_token())
                    got = "예외 없음"
                except JWTError:
                    got = "JWTError"
                except Exception as exc:  # noqa: BLE001 - 계약 검증이 목적
                    got = type(exc).__name__
        check("★ %s -> JWTError" % label, got, "JWTError")


# ---------------------------------------------------------------------------
# 2. ★★ 선택적 인증 라우트는 500이 아니라 비로그인으로 강등된다
# ---------------------------------------------------------------------------
def test_optional_auth_routes_degrade():
    print("\n--- 2. 선택적 인증 라우트는 200 (비로그인 강등) ---")
    client = _client()
    headers = {"Authorization": "Bearer " + _es256_token()}

    for label, jwk in BROKEN_JWKS:
        with broken_key(jwk):
            with contextlib.redirect_stderr(io.StringIO()):
                r_search = client.get("/api/v1/search", headers=headers)
                r_item = client.get("/api/v1/item/1", headers=headers)
        check("★ %s: /search" % label, r_search.status_code, 200)
        check("★ %s: /item/1" % label, r_item.status_code, 200)
        # 강등이므로 개인화 필드는 비로그인과 같아야 한다.
        if r_item.status_code == 200:
            check_true("%s: is_favorited 가 False(비로그인)" % label,
                       r_item.json().get("is_favorited") is False, r_item.json().get("is_favorited"))


# ---------------------------------------------------------------------------
# 3. ★ 인증 필수 라우트는 401 (500 아님)
# ---------------------------------------------------------------------------
def test_required_auth_returns_401():
    print("\n--- 3. 인증 필수 라우트는 401 ---")
    client = _client()
    headers = {"Authorization": "Bearer " + _es256_token()}
    for label, jwk in BROKEN_JWKS:
        with broken_key(jwk):
            with contextlib.redirect_stderr(io.StringIO()):
                r = client.get("/api/v1/favorites", headers=headers)
        check("★ %s: /favorites" % label, r.status_code, 401)


# ---------------------------------------------------------------------------
# 4. 응답에 내부 정보가 새지 않는다
# ---------------------------------------------------------------------------
def test_no_internal_leak_in_response():
    print("\n--- 4. 응답에 traceback/내부 경로가 없다 ---")
    client = _client()
    headers = {"Authorization": "Bearer " + _es256_token()}
    with broken_key(BROKEN_JWKS[0][1]):
        with contextlib.redirect_stderr(io.StringIO()):
            r = client.get("/api/v1/favorites", headers=headers)
    body = r.text
    for bad in ("Traceback", "File \"", "site-packages", "api\\auth.py", "api/auth.py"):
        check_true("응답에 %r 이 없다" % bad, bad not in body, body[:160])
    # 비밀값이 응답에 실리지 않는다.
    secret = os.environ["SUPABASE_JWT_SECRET"]
    check_true("응답에 JWT 시크릿이 없다", secret not in body)


# ---------------------------------------------------------------------------
# 5. 로그에 비밀값이 남지 않는다 (예외 타입만 남긴다)
# ---------------------------------------------------------------------------
def test_log_has_type_only():
    print("\n--- 5. 로그에는 예외 타입만 남는다 ---")
    import api.auth as auth_mod

    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    logger = logging.getLogger("api.auth")
    logger.addHandler(handler)
    try:
        with broken_key(BROKEN_JWKS[0][1]):
            with contextlib.suppress(Exception):
                auth_mod.decode_supabase_jwt(_es256_token())
    finally:
        logger.removeHandler(handler)

    logged = stream.getvalue()
    check_true("경고가 남는다(조용히 삼키지 않는다)", "JOSE" in logged or "예외" in logged, logged[:160])
    check_true("로그에 예외 타입이 있다", "ValueError" in logged, logged[:160])
    secret = os.environ["SUPABASE_JWT_SECRET"]
    check_true("로그에 JWT 시크릿이 없다", secret not in logged)
    check_true("로그에 공개키 값이 없다", "!!!" not in logged, logged[:160])


# ---------------------------------------------------------------------------
# 6. 정상 경로 회귀 — 넓게 잡는 수정이 멀쩡한 토큰까지 막지는 않는다
# ---------------------------------------------------------------------------
def test_valid_token_still_works():
    print("\n--- 6. 정상 HS256 토큰은 그대로 동작한다 ---")
    from jose import jwt
    import api.auth as auth_mod

    token = jwt.encode({"sub": "jwks-probe-user"}, auth_mod.SUPABASE_JWT_SECRET, algorithm="HS256")
    payload = auth_mod.decode_supabase_jwt(token)
    check("sub 가 그대로 나온다", payload.get("sub"), "jwks-probe-user")

    # 기존의 거부 계약도 유지되는지 확인한다(넓은 except 가 alg 화이트리스트를 무력화하지 않는다).
    from jose.exceptions import JWTError
    forged = _b64({"alg": "none"}) + "." + _b64({"sub": "attacker"}) + "."
    try:
        auth_mod.decode_supabase_jwt(forged)
        got = "통과함(위험)"
    except JWTError:
        got = "JWTError"
    except Exception as exc:  # noqa: BLE001
        got = type(exc).__name__
    check("alg:none 은 여전히 거부된다", got, "JWTError")


# ---------------------------------------------------------------------------
# 7. 배선 고정 — 넓은 정규화가 사라지면 2/3번이 조용히 무의미해진다
# ---------------------------------------------------------------------------
def test_broad_normalization_present_in_source():
    print("\n--- 7. 소스에 JOSE 계열 밖 정규화가 있다 ---")
    src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "api", "auth.py"),
               encoding="utf-8-sig").read()
    body = src[src.index("def decode_supabase_jwt("):]
    body = body[:body.index("def get_current_user(")]
    check_true("★ JOSEError 정규화가 있다", "except JOSEError" in body)
    check_true("★ 그 밖의 예외 정규화도 있다", "except Exception" in body.split("except JOSEError")[-1],
               body[-260:])
    # 정규화 결과가 JWTError 여야 의미가 있다.
    tail = body.split("except JOSEError")[-1]
    check_true("★ 넓은 except 도 JWTError 로 바꾼다", "JWTError(" in tail, tail[:200])


if __name__ == "__main__":
    test_normalized_to_jwt_error()
    test_optional_auth_routes_degrade()
    test_required_auth_returns_401()
    test_no_internal_leak_in_response()
    test_log_has_type_only()
    test_valid_token_still_works()
    test_broad_normalization_present_in_source()

    print("\n" + "=" * 60)
    if failures:
        print("FAILED (%d): %s" % (len(failures), ", ".join(failures)))
        sys.exit(1)
    print("ALL JWKS ROBUSTNESS TESTS PASSED")
