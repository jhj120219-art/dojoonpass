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




# ---------------------------------------------------------------------------
# 8. ★ JWKS 가 응답하지 않을 때 바깥 호출이 폭주하지 않는가 (2026-08-25 신설, BUGS #191)
#
# 왜 필요한가 — `_get_jwk()` 의 재조회 조건에 `or not _jwks_keys` 가 붙어 있었다.
# 캐시가 비어 있는 동안(콜드 스타트 / 긴 장애 뒤) **하한이 통째로 무효**가 되어
# 들어오는 요청마다 5초짜리 바깥 호출이 하나씩 나갔고, 그 호출이 `_jwks_lock` 을
# 잡은 채 일어나므로 요청들이 직렬화됐다.
#
#     수정 전 실측(스레드 8개, 응답 없는 JWKS, 타임아웃 1초로 축소):
#         바깥 호출 8회 / 전체 8.00초 / 마지막 요청 8.00초
#     실제 timeout=5 로 환산하면 동시 8요청에 마지막 요청이 40초.
#
# 즉 **JWKS 한 곳이 느려지는 것이 API 전체 정지로 번진다.** 결과(401)는 어차피 같으므로
# 빨리 401 을 주고 서버가 살아 있는 편이 낫다.
#
# 이 검사는 네트워크를 타지 않는다 — `urlopen` 을 응답하지 않는 가짜로 갈아끼운다.
# ---------------------------------------------------------------------------
def test_jwks_outage_does_not_storm():
    print("\n--- 8. JWKS 무응답 중 바깥 호출 폭주 방지 (BUGS #191) ---")
    import logging as _logging
    import threading
    import time

    import api.auth as auth_mod

    HANG = 0.3          # 타임아웃을 축소해 재현만 본다(실제 코드는 5초)
    THREADS = 8
    calls = {"n": 0}
    saved_urlopen = auth_mod.urllib.request.urlopen
    saved_keys, saved_at = auth_mod._jwks_keys, auth_mod._jwks_fetched_at
    saved_url = auth_mod.SUPABASE_URL

    class _Hang:
        def __enter__(self):
            calls["n"] += 1
            time.sleep(HANG)
            raise TimeoutError("The read operation timed out")

        def __exit__(self, *a):
            return False

    class _Ok:
        def __enter__(self):
            calls["n"] += 1
            return io.StringIO(json.dumps({"keys": [{"kid": "live-kid", "kty": "EC"}]}))

        def __exit__(self, *a):
            return False

    _logging.disable(_logging.WARNING)      # 실패 경고가 판정문을 덮지 않게
    try:
        # --- (1) 무응답 JWKS + 동시 요청 -----------------------------------
        auth_mod.urllib.request.urlopen = lambda url, timeout=None: _Hang()
        auth_mod.SUPABASE_URL = "https://qa-jwks.example.invalid"
        auth_mod._jwks_keys, auth_mod._jwks_fetched_at = {}, 0.0
        calls["n"] = 0

        latencies = []

        def worker(i):
            t0 = time.time()
            auth_mod._get_jwk("kid-%d" % i)
            latencies.append(time.time() - t0)

        started = time.time()
        threads = [threading.Thread(target=worker, args=(i,)) for i in range(THREADS)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        wall = time.time() - started

        print("    동시 %d요청 / 바깥 호출 %d회 / 전체 %.2fs / 최장 %.2fs"
              % (THREADS, calls["n"], wall, max(latencies)))
        check("★ 바깥 JWKS 호출이 1회로 눌린다(요청마다 나가지 않는다)", calls["n"], 1)
        check_true("★ 전체 소요가 타임아웃 1회분 안쪽이다(직렬화되지 않는다)",
                   wall < HANG * (THREADS / 2.0),
                   "-> %.2fs. 요청마다 %.1fs 씩 쌓이면 %.1fs 가 된다" % (wall, HANG, HANG * THREADS))
        check_true("검사가 공허하지 않다(스레드가 실제로 다 돌았다)",
                   len(latencies) == THREADS, len(latencies))

        # --- (2) 그래도 콜드 스타트에서 첫 조회는 한다 ----------------------
        #     하한을 시간 비교만으로 두면 부팅 직후(monotonic 이 작은 환경)에
        #     첫 조회를 통째로 건너뛸 수 있다. 그 회귀를 여기서 막는다.
        auth_mod.urllib.request.urlopen = lambda url, timeout=None: _Ok()
        auth_mod._jwks_keys, auth_mod._jwks_fetched_at = {}, 0.0
        calls["n"] = 0
        got = auth_mod._get_jwk("live-kid")
        check_true("★ 콜드 스타트 + 정상 네트워크면 첫 조회가 그대로 된다", got is not None, got)
        check("그때 바깥 호출은 정확히 1회", calls["n"], 1)

        # --- (3) 최근에 시도했으면 다시 나가지 않는다(하한이 실제로 유효) ----
        auth_mod._jwks_keys, auth_mod._jwks_fetched_at = {}, time.monotonic()
        calls["n"] = 0
        auth_mod._get_jwk("live-kid")
        check("★ 방금 시도했으면 재조회하지 않는다(하한 유효)", calls["n"], 0)

        # --- (4) 캐시가 살아 있는 평시 동작은 그대로다 ----------------------
        auth_mod._jwks_keys = {"warm-kid": {"kid": "warm-kid", "kty": "EC"}}
        auth_mod._jwks_fetched_at = time.monotonic()
        calls["n"] = 0
        warm = auth_mod._get_jwk("warm-kid")
        check_true("캐시 적중은 바깥 호출 없이 그대로 돌려준다",
                   warm is not None and calls["n"] == 0, (warm, calls["n"]))
    finally:
        _logging.disable(_logging.NOTSET)
        auth_mod.urllib.request.urlopen = saved_urlopen
        auth_mod._jwks_keys, auth_mod._jwks_fetched_at = saved_keys, saved_at
        auth_mod.SUPABASE_URL = saved_url


def test_no_unbounded_refetch_escape_in_source():
    """소스에 `or not _jwks_keys` 가 되돌아오면 잡는다.

    행위 검사(위 8번)가 주 방어선이지만, 타이밍에 의존하는 검사는 느린 CI 에서
    흔들릴 수 있다. 구조로 한 겹 더 못 박는다 — 이 저장소가 이미 쓰는 방식이다.
    """
    print("\n--- 8-b. 재조회 하한에 예외 조항이 없다 (구조) ---")
    src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "api", "auth.py"),
               encoding="utf-8-sig").read()
    body = src[src.index("def _get_jwk("):]
    body = body[:body.index("def decode_supabase_jwt(")]
    code = "\n".join(l for l in body.splitlines() if not l.strip().startswith("#"))
    check_true("★ `or not _jwks_keys` 예외 조항이 없다",
               "or not _jwks_keys" not in code,
               "-> 캐시가 빌 때 하한이 무효가 된다(BUGS #191)")
    check_true("하한 상수를 실제로 쓴다", "_JWKS_MIN_REFETCH_SECONDS" in code, code[:200])
    check_true("'한 번도 조회한 적 없음'은 따로 본다", "never_fetched" in code, code[:200])


# ---------------------------------------------------------------------------
# 9. 인증 설정이 **한쪽만** 사라졌을 때 부팅에서 알아채는가 (2026-08-25, BUGS #205)
#
# 왜 필요한가 — `get_current_user()` 는 **둘 다** 없을 때만 500 을 낸다. 그 경우는
# 500 이라 즉시 드러난다. 위험한 것은 한쪽만 사라진 경우다. 실측(로컬 스텁 JWKS +
# 진짜 ES256 키):
#
#     둘 다 있음            ES256 200 / HS256 200
#     SUPABASE_URL 없음     ES256 **401** / HS256 200   <- 로그인 사용자 전원 401
#     JWT_SECRET 없음       ES256 200 / HS256 **401**
#     둘 다 없음            전부 500
#
# ES256 이 현행 서명이다(BUGS #27). `SUPABASE_URL` 하나가 비면 로그인한 사람 전부가
# 막히는데, 그때 남는 로그는 요청마다 나오는 "JWKS에서 해당 kid의 공개키를 찾지
# 못했습니다" 뿐이라 **키 회전 사고처럼 읽힌다.** 401 은 "토큰이 틀렸다"와 구별되지
# 않는다 — `api/v1/admin.py` 의 403 이 "권한 부족"과 구별되지 않는 것과 같은 모양이다.
# ---------------------------------------------------------------------------
def test_boot_warns_when_auth_config_is_partially_missing():
    print("\n--- 9. 인증 설정 부분 소실 시 부팅 경고 (BUGS #205) ---")
    import logging as _logging
    import api.auth as auth_mod

    class Grab(_logging.Handler):
        def __init__(self):
            _logging.Handler.__init__(self)
            self.msgs = []

        def emit(self, record):
            if record.levelno >= _logging.WARNING:
                self.msgs.append(record.getMessage())

    grab = Grab()
    lg = _logging.getLogger(auth_mod.__name__)
    lg.addHandler(grab)
    prev_level, prev_prop = lg.level, lg.propagate
    lg.setLevel(_logging.WARNING)
    saved = (auth_mod.SUPABASE_JWT_SECRET, auth_mod.SUPABASE_URL)

    # 실제 값과 구별되는 합성값 — 이 값이 로그에 나오면 누출이다
    SECRET = "qa-authcfg-not-a-real-secret-000"
    URL = "https://qa-authcfg.example.invalid"

    def scene(secret, url):
        auth_mod.SUPABASE_JWT_SECRET, auth_mod.SUPABASE_URL = secret, url
        grab.msgs = []
        warned = auth_mod.warn_if_auth_config_missing()
        return warned, list(grab.msgs)

    try:
        # (1) 둘 다 있으면 조용하다 — 잡음 방지는 여기서만 성립한다
        warned, msgs = scene(SECRET, URL)
        check("★ 둘 다 있으면 경고하지 않는다", warned, False)
        check("그때 로그도 남기지 않는다(잡음 방지)", len(msgs), 0)

        # (2) SUPABASE_URL 만 사라짐 — 가장 위험한 경우(로그인 전원 401)
        warned, msgs = scene(SECRET, "")
        check("★ SUPABASE_URL 만 없어도 경고한다", warned, True)
        check("경고가 실제로 로그로 나간다(반환값만 바꾼 게 아니다)", len(msgs), 1)
        if msgs:
            check_true("어느 설정이 없는지 지목한다", "SUPABASE_URL" in msgs[0], msgs[0][:150])
            check_true("무엇이 깨지는지 적혀 있다(401)", "401" in msgs[0], msgs[0][:150])
            check_true("★ 그때 살아 있는 시크릿 **값**이 로그에 안 들어간다",
                       SECRET not in msgs[0], "-> 경고에 시크릿이 섞였다")

        # (3) JWT_SECRET 만 사라짐 — 레거시 토큰만 막혀 증상이 일부에게만 보인다
        warned, msgs = scene("", URL)
        check("★ SUPABASE_JWT_SECRET 만 없어도 경고한다", warned, True)
        check("경고가 실제로 로그로 나간다", len(msgs), 1)
        if msgs:
            check_true("어느 설정이 없는지 지목한다",
                       "SUPABASE_JWT_SECRET" in msgs[0], msgs[0][:150])
            check_true("★ 그때 살아 있는 URL **값**이 로그에 안 들어간다",
                       URL not in msgs[0], "-> 경고에 설정값이 섞였다")

        # (4) 둘 다 사라짐 — 500 이라 어차피 드러나지만 부팅에서도 말해 준다
        warned, msgs = scene("", "")
        check("★ 둘 다 없으면 경고한다", warned, True)
        check("경고가 실제로 로그로 나간다", len(msgs), 1)
        if msgs:
            check_true("무엇이 깨지는지 적혀 있다(500)", "500" in msgs[0], msgs[0][:150])
    finally:
        auth_mod.SUPABASE_JWT_SECRET, auth_mod.SUPABASE_URL = saved
        lg.removeHandler(grab)
        lg.setLevel(prev_level)
        lg.propagate = prev_prop

    # --- 값이 로그로 새지 않는가 (구조) --------------------------------------
    #
    #   행위로도 위에서 봤지만(합성값이 메시지에 없다), 소스로 한 겹 더 못 박는다.
    #   문자열 검색으로는 안 된다 — 경고 문구가 "SUPABASE_URL" 이라는 **이름**을
    #   정당하게 포함하기 때문이다. 이름이 아니라 **값을 담은 이름을 경고 인자로
    #   넘기는지**를 AST 로 본다. 미래의 편집이 "친절하게" 현재 설정값을 끼워 넣는
    #   것을 막는다(`test_admin_secret_contract.py` 가 쓰는 방식과 같다).
    import ast

    src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "api", "auth.py"),
               encoding="utf-8-sig").read()
    fn = None
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.FunctionDef) and node.name == "warn_if_auth_config_missing":
            fn = node
    check_true("검사가 공허하지 않다(함수를 찾았다)", fn is not None,
               "-> 이름이 바뀌었으면 이 검사도 고쳐라")

    warn_calls = []
    if fn is not None:
        for node in ast.walk(fn):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "warning"):
                warn_calls.append(node)
    # 경고 호출 3개 — 둘 다 없음 / URL 만 없음 / SECRET 만 없음
    check("검사가 공허하지 않다(경고 호출을 찾았다)", len(warn_calls), 3)

    SECRET_NAMES = {"SUPABASE_JWT_SECRET", "SUPABASE_URL"}
    leaked = []
    for call in warn_calls:
        for sub in ast.walk(call):
            if isinstance(sub, ast.Name) and sub.id in SECRET_NAMES:
                leaked.append(sub.id)
            if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute) \
                    and sub.func.attr == "getenv":
                leaked.append("os.getenv")
    check_true("★ 경고 인자에서 설정 **값**을 읽지 않는다", not leaked,
               "-> %s 를 경고에 끼워 넣었다. 로그 유출이 곧 인증 우회가 된다"
               % sorted(set(leaked)))

    # --- 폴백에 걸려 있는 상태를 부팅 로그에 드러내는가 (2026-08-25, BUGS #205 후속) ---
    #
    #   실측: `.env` 의 SUPABASE_URL 은 **비어 있고**, ES256(현행 서명) 검증은 전적으로
    #   `.env.local` 의 NEXT_PUBLIC_SUPABASE_URL 에 걸려 있다. 두 파일 다 gitignore 라
    #   배포 대상에 따로 넣어야 하는데, 백엔드만 올리는 사람은 `.env` 만 챙기는 것이
    #   자연스럽다. 그러면 URL 이 비고 **로그인 사용자 전원이 401** 이 된다.
    #
    #   그 장애 자체는 위 (2) 가 잡는다. 여기서는 **아직 멀쩡하지만 폴백에 걸려 있는**
    #   상태를 본다 - 경고가 아니라 INFO 다(장애가 아니므로 경고로 만들면 잡음이 된다).
    class GrabAll(_logging.Handler):
        def __init__(self):
            _logging.Handler.__init__(self)
            self.msgs = []

        def emit(self, record):
            self.msgs.append((record.levelno, record.getMessage()))

    ga = GrabAll()
    lg.addHandler(ga)
    prev2 = lg.level
    lg.setLevel(_logging.INFO)
    saved2 = (auth_mod.SUPABASE_JWT_SECRET, auth_mod.SUPABASE_URL, auth_mod._SUPABASE_URL_SOURCE)
    try:
        check_true("검사가 공허하지 않다(출처 상수가 있다)",
                   hasattr(auth_mod, "_SUPABASE_URL_SOURCE"),
                   "-> 이름이 바뀌었으면 이 검사도 고쳐라")
        check_true("출처는 두 이름 중 하나이거나 비어 있다",
                   auth_mod._SUPABASE_URL_SOURCE in
                   ("SUPABASE_URL", "NEXT_PUBLIC_SUPABASE_URL", ""),
                   auth_mod._SUPABASE_URL_SOURCE)
        # 출처가 실제 해석 결과와 어긋나지 않는가 - 상수만 손대는 편집을 막는다
        check_true("URL 이 있으면 출처도 비어 있지 않다",
                   bool(auth_mod.SUPABASE_URL) == bool(auth_mod._SUPABASE_URL_SOURCE),
                   (bool(auth_mod.SUPABASE_URL), auth_mod._SUPABASE_URL_SOURCE))
        # ★ **실제 환경과 대조한다.** 위 검사만으로는 "출처를 늘 SUPABASE_URL 이라고
        #   보고하는" 편집이 통과한다(2026-08-25 mutation 이 실제로 뚫었다).
        #   보고된 이름에는 **값이 있어야 한다** - 그것이 출처라는 말의 뜻이다.
        _expected = ("SUPABASE_URL" if os.getenv("SUPABASE_URL")
                     else "NEXT_PUBLIC_SUPABASE_URL" if os.getenv("NEXT_PUBLIC_SUPABASE_URL")
                     else "")
        check("★ 보고한 출처가 실제로 값을 가진 이름이다",
              auth_mod._SUPABASE_URL_SOURCE, _expected)
        # 이 머신은 `.env` 의 SUPABASE_URL 이 비어 있어 폴백이 곧 정답이다. 그래서
        # "항상 폴백이라고 보고하는" 편집은 여기서 구별되지 않는다(mutation 으로 확인).
        # **환경을 바꾼 하위 프로세스**로 반대쪽 분기를 실제로 밟아 본다.
        import subprocess as _sp
        _env = dict(os.environ)
        _env["SUPABASE_URL"] = "https://qa-source-probe.example.invalid"
        _env["PYTHONIOENCODING"] = "utf-8"
        _probe = _sp.run(
            [sys.executable, "-c",
             "import os,sys;sys.path.insert(0,os.getcwd());"
             "import api.auth as a;print(a._SUPABASE_URL_SOURCE)"],
            cwd=os.path.dirname(os.path.abspath(__file__)),
            env=_env, capture_output=True, timeout=120)
        _got = (_probe.stdout or b"").decode("utf-8", "replace").strip().splitlines()
        check("★ SUPABASE_URL 이 있는 환경에서는 그쪽을 출처로 보고한다",
              _got[-1] if _got else "(출력 없음)", "SUPABASE_URL")

        # 셋째 분기 - **둘 다 없으면 출처도 없어야 한다.** 이걸 빼면 "언제나 폴백에서
        # 왔다"고 보고하는 편집이 통과한다(2026-08-25 mutation 이 실제로 뚫었다).
        # 그 상태는 위 (2) 의 경고와 어긋나 로그가 서로 다른 말을 하게 된다.
        _env2 = dict(os.environ)
        _env2.pop("SUPABASE_URL", None)
        _env2.pop("NEXT_PUBLIC_SUPABASE_URL", None)
        _env2["PYTHONIOENCODING"] = "utf-8"
        _probe2 = _sp.run(
            [sys.executable, "-c",
             "import os,sys;sys.path.insert(0,os.getcwd());"
             "import dotenv;dotenv.load_dotenv=lambda *a,**k:False;"   # .env 를 못 읽게 막는다
             "import api.auth as a;print(repr(a._SUPABASE_URL_SOURCE))"],
            cwd=os.path.dirname(os.path.abspath(__file__)),
            env=_env2, capture_output=True, timeout=120)
        _got2 = (_probe2.stdout or b"").decode("utf-8", "replace").strip().splitlines()
        check("★ 둘 다 없는 환경에서는 출처도 비어 있다",
              _got2[-1] if _got2 else "(출력 없음)", "''")

        auth_mod.SUPABASE_JWT_SECRET, auth_mod.SUPABASE_URL = SECRET, URL

        # (5) 폴백에서 왔으면 INFO 로 남긴다 - 경고는 아니다
        auth_mod._SUPABASE_URL_SOURCE = "NEXT_PUBLIC_SUPABASE_URL"
        ga.msgs = []
        warned = auth_mod.warn_if_auth_config_missing()
        check("폴백이어도 경고는 아니다(장애가 아니다)", warned, False)
        infos = [m for lvl, m in ga.msgs if lvl == _logging.INFO]
        warns = [m for lvl, m in ga.msgs if lvl >= _logging.WARNING]
        check("★ 폴백에서 왔다는 사실을 INFO 로 남긴다", len(infos), 1)
        check("그것을 경고로 올리지는 않는다(잡음 방지)", len(warns), 0)
        if infos:
            check_true("어느 이름에서 왔는지 적는다",
                       "NEXT_PUBLIC_SUPABASE_URL" in infos[0], infos[0][:150])
            check_true("★ 그 안내에도 URL **값**이 들어가지 않는다",
                       URL not in infos[0], "-> 안내에 설정값이 섞였다")

        # (6) 정규 이름에서 왔으면 아무 말도 안 한다
        auth_mod._SUPABASE_URL_SOURCE = "SUPABASE_URL"
        ga.msgs = []
        auth_mod.warn_if_auth_config_missing()
        check("★ SUPABASE_URL 에서 왔으면 조용하다", len(ga.msgs), 0)
    finally:
        (auth_mod.SUPABASE_JWT_SECRET, auth_mod.SUPABASE_URL,
         auth_mod._SUPABASE_URL_SOURCE) = saved2
        lg.removeHandler(ga)
        lg.setLevel(prev2)

    # 부팅 경로가 실제로 이 함수를 **호출**하는가 - 안 부르면 위 검사가 전부 무의미하다.
    #
    #   문자열 검색으로는 부족하다(2026-08-25, BUGS #205 의 mutation 이 뚫었다):
    #   주석 줄만 걸러 내는 방식은 `pass  # warn_if_auth_config_missing()` 같은 **꼬리 주석**을
    #   호출로 오인한다. 실제로 배선을 지우는 mutation 이 통과했다.
    #   그래서 AST 로 **모듈 최상위의 호출문**을 찾는다.
    import ast as _ast

    _boot = _ast.parse(open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                            "api_server.py"),
                               encoding="utf-8-sig").read())
    _called = any(isinstance(n, _ast.Expr) and isinstance(n.value, _ast.Call)
                  and isinstance(n.value.func, _ast.Name)
                  and n.value.func.id == "warn_if_auth_config_missing"
                  for n in _boot.body)
    check_true("★ api_server.py 가 부팅 시 이 함수를 호출한다", _called,
               "-> 함수만 있고 아무도 안 부르면 경고는 영원히 안 나온다")

if __name__ == "__main__":
    test_normalized_to_jwt_error()
    test_optional_auth_routes_degrade()
    test_required_auth_returns_401()
    test_no_internal_leak_in_response()
    test_log_has_type_only()
    test_valid_token_still_works()
    test_broad_normalization_present_in_source()
    test_jwks_outage_does_not_storm()
    test_no_unbounded_refetch_escape_in_source()
    test_boot_warns_when_auth_config_is_partially_missing()

    print("\n" + "=" * 60)
    if failures:
        print("FAILED (%d): %s" % (len(failures), ", ".join(failures)))
        sys.exit(1)
    print("ALL JWKS ROBUSTNESS TESTS PASSED")
