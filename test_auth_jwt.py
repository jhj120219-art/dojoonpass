"""
JWT 인증 체인 회귀 테스트 (2026-08-10 Sprint 46 신규, docs/BUGS.md #27)

Supabase가 ES256(비대칭 서명)으로 전환된 뒤 백엔드가 HS256만 검증해 로그인 사용자의
모든 인증 API가 401이 되던 문제를 고쳤다. 그 수정이 다시 깨지지 않도록 고정한다.

검증 전략
- Supabase의 **개인키는 가질 수 없으므로**, 테스트가 자체 EC P-256 키쌍을 만들고 그
  공개키를 JWKS 캐시에 주입한 뒤 개인키로 토큰을 서명한다. 그러면 실제 코드 경로
  (헤더 파싱 -> 알고리즘 화이트리스트 -> kid 조회 -> jose 검증)를 그대로 통과시킨다.
- 네트워크를 타지 않는다(캐시를 fresh로 세팅). 외부 상태에 의존하는 테스트를 만들지 않는다.
- **비밀값을 출력하지 않는다.** 토큰/시크릿 원문은 어떤 경우에도 print하지 않는다.

실행: python test_auth_jwt.py
"""
import io
import os
import re
import secrets
import sys
import time
from datetime import datetime, timedelta, timezone

# api.auth는 import 시점에 SUPABASE_JWT_SECRET을 읽는다. .env에 값이 없는 환경에서도
# HS256(레거시) 경로를 검증할 수 있도록, 없을 때만 이 프로세스 환경에 합성값을 주입한다.
# (test_api_regression.py와 동일한 기존 패턴. .env 파일은 건드리지 않는다.)
if not os.getenv("SUPABASE_JWT_SECRET"):
    os.environ["SUPABASE_JWT_SECRET"] = "qa-authtest-" + secrets.token_hex(16)

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from jose import jwk, jwt, JWTError

import api.auth as auth_mod
from api.auth import decode_supabase_jwt

PASS = 0
FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"[PASS] {name}")
    else:
        FAIL += 1
        print(f"[FAIL] {name} {detail}")


def expect_jwt_error(name, fn):
    """fn()이 JWTError를 던져야 한다(=검증 거부)."""
    try:
        fn()
    except JWTError:
        check(name, True)
        return
    except Exception as exc:
        check(name, False, f"-> JWTError가 아닌 {type(exc).__name__}")
        return
    check(name, False, "-> 예외 없이 통과함(거부되어야 함)")


# ---------------------------------------------------------------------------
# ES256 테스트용 키쌍 + JWKS 캐시 주입
# ---------------------------------------------------------------------------
TEST_KID = "test-kid-" + secrets.token_hex(4)
_priv = ec.generate_private_key(ec.SECP256R1())
_priv_pem = _priv.private_bytes(
    serialization.Encoding.PEM,
    serialization.PrivateFormat.PKCS8,
    serialization.NoEncryption(),
).decode()
_pub_pem = _priv.public_key().public_bytes(
    serialization.Encoding.PEM,
    serialization.PublicFormat.SubjectPublicKeyInfo,
).decode()

_pub_jwk = jwk.construct(_pub_pem, "ES256").to_dict()
# to_dict()의 값은 bytes일 수 있다 — JWKS(JSON) 형태와 같게 str로 맞춘다.
_pub_jwk = {k: (v.decode() if isinstance(v, bytes) else v) for k, v in _pub_jwk.items()}
_pub_jwk.update({"kid": TEST_KID, "alg": "ES256", "use": "sig"})

# 캐시를 fresh 상태로 만들어 테스트 중 외부 JWKS 호출이 일어나지 않게 한다.
auth_mod._jwks_keys = {TEST_KID: _pub_jwk}
auth_mod._jwks_fetched_at = time.monotonic()


def es256(payload, kid=TEST_KID):
    return jwt.encode(payload, _priv_pem, algorithm="ES256", headers={"kid": kid})


def hs256(payload):
    return jwt.encode(payload, auth_mod.SUPABASE_JWT_SECRET, algorithm="HS256")


USER = "auth-test-user"



print("=" * 70)
print(" JWT 인증 체인 (ES256/JWKS + HS256 레거시)")
print("=" * 70)

# --- 1. ES256 정상 경로 -----------------------------------------------------
payload = decode_supabase_jwt(es256({"sub": USER}))
check("ES256 정상 토큰 -> 검증 성공, sub 추출", payload.get("sub") == USER)

# --- 2. ES256 거부 경로 -----------------------------------------------------
expect_jwt_error(
    "ES256 만료 토큰 -> 거부",
    lambda: decode_supabase_jwt(
        es256({"sub": USER, "exp": datetime.now(timezone.utc) - timedelta(hours=1)})
    ),
)

_other = ec.generate_private_key(ec.SECP256R1()).private_bytes(
    serialization.Encoding.PEM,
    serialization.PrivateFormat.PKCS8,
    serialization.NoEncryption(),
).decode()
expect_jwt_error(
    "ES256 다른 개인키로 서명(위조) -> 거부",
    lambda: decode_supabase_jwt(
        jwt.encode({"sub": USER}, _other, algorithm="ES256", headers={"kid": TEST_KID})
    ),
)

expect_jwt_error(
    "JWKS에 없는 kid -> 거부",
    lambda: decode_supabase_jwt(es256({"sub": USER}, kid="unknown-kid")),
)

expect_jwt_error(
    "kid 없는 ES256 토큰 -> 거부",
    lambda: decode_supabase_jwt(jwt.encode({"sub": USER}, _priv_pem, algorithm="ES256")),
)

# --- 3. 알고리즘 화이트리스트 (알고리즘 혼동 공격 방어) ----------------------
# 공격자는 jose 라이브러리를 쓰지 않는다. jose는 alg="none" 토큰을 **만들지도** 못하므로
# (JWSError) 공격 토큰은 손으로 조립해야 실제 방어를 검증할 수 있다.
import base64
import hashlib
import hmac
import json as _json


def _b64u(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _seg(obj) -> str:
    return _b64u(_json.dumps(obj, separators=(",", ":")).encode())


def craft(header: dict, payload: dict, signature: bytes = b"") -> str:
    return f"{_seg(header)}.{_seg(payload)}.{_b64u(signature)}"


expect_jwt_error(
    'alg="none" 토큰(수제 조립) -> 거부',
    lambda: decode_supabase_jwt(craft({"alg": "none", "typ": "JWT"}, {"sub": USER})),
)

# ES256 공개키를 HMAC 비밀키로 써서 HS256으로 위조하는 고전적 알고리즘 혼동 공격.
# HS256은 SUPABASE_JWT_SECRET으로만 검증하므로 공개키를 알아도 통과할 수 없어야 한다.
def _alg_confusion_token():
    h, p = _seg({"alg": "HS256", "typ": "JWT"}), _seg({"sub": USER})
    sig = hmac.new(_pub_pem.encode(), f"{h}.{p}".encode(), hashlib.sha256).digest()
    return f"{h}.{p}.{_b64u(sig)}"


expect_jwt_error(
    "공개키를 HMAC 키로 쓴 HS256 위조(알고리즘 혼동) -> 거부",
    lambda: decode_supabase_jwt(_alg_confusion_token()),
)

expect_jwt_error(
    "알 수 없는 alg(예: XX999) -> 거부",
    lambda: decode_supabase_jwt(craft({"alg": "XX999", "typ": "JWT"}, {"sub": USER})),
)

expect_jwt_error("JWT 형식이 아닌 문자열 -> 거부", lambda: decode_supabase_jwt("not-a-jwt"))
expect_jwt_error("빈 문자열 -> 거부", lambda: decode_supabase_jwt(""))

# --- 4. HS256 레거시 경로 (전환기 호환) -------------------------------------
payload = decode_supabase_jwt(hs256({"sub": USER}))
check("HS256 레거시 토큰 -> 여전히 검증 성공", payload.get("sub") == USER)

expect_jwt_error(
    "HS256 잘못된 시크릿 -> 거부",
    lambda: decode_supabase_jwt(
        jwt.encode({"sub": USER}, "attacker-guessed-wrong-secret", algorithm="HS256")
    ),
)
expect_jwt_error(
    "HS256 만료 토큰 -> 거부",
    lambda: decode_supabase_jwt(
        jwt.encode(
            {"sub": USER, "exp": datetime.now(timezone.utc) - timedelta(hours=1)},
            auth_mod.SUPABASE_JWT_SECRET,
            algorithm="HS256",
        )
    ),
)

# --- 5. 엔드포인트 레벨: 인증 필수 / 선택적 인증 ----------------------------
from fastapi.testclient import TestClient
from api_server import app

client = TestClient(app)

r = client.get("/api/v1/favorites", headers={"Authorization": f"Bearer {es256({'sub': USER})}"})
check("인증 필수 API + ES256 토큰 -> 200", r.status_code == 200, f"-> {r.status_code}")

r = client.get("/api/v1/favorites", headers={"Authorization": f"Bearer {hs256({'sub': USER})}"})
check("인증 필수 API + HS256 토큰 -> 200", r.status_code == 200, f"-> {r.status_code}")

r = client.get("/api/v1/favorites")
check("인증 필수 API + 토큰 없음 -> 401/403", r.status_code in (401, 403), f"-> {r.status_code}")

r = client.get("/api/v1/favorites", headers={"Authorization": "Bearer garbage"})
check("인증 필수 API + 깨진 토큰 -> 401", r.status_code == 401, f"-> {r.status_code}")

r = client.get(
    "/api/v1/favorites",
    headers={"Authorization": f"Bearer {es256({'foo': 'bar'})}"},
)
check("인증 필수 API + sub 없는 ES256 토큰 -> 401", r.status_code == 401, f"-> {r.status_code}")

r = client.get(
    "/api/v1/favorites",
    headers={"Authorization": f"Bearer {es256({'sub': USER, 'exp': datetime.now(timezone.utc) - timedelta(hours=1)})}"},
)
check("인증 필수 API + 만료 ES256 토큰 -> 401", r.status_code == 401, f"-> {r.status_code}")

# 선택적 인증: 토큰이 없어도, 깨져도 검색은 200이어야 한다.
r = client.get("/api/v1/search?size=1")
check("선택적 인증 API + 비로그인 -> 200", r.status_code == 200, f"-> {r.status_code}")

r = client.get("/api/v1/search?size=1", headers={"Authorization": "Bearer garbage"})
check("선택적 인증 API + 깨진 토큰 -> 여전히 200(검색을 막지 않음)", r.status_code == 200, f"-> {r.status_code}")

r = client.get("/api/v1/search?size=1", headers={"Authorization": f"Bearer {es256({'sub': USER})}"})
check("선택적 인증 API + ES256 토큰 -> 200", r.status_code == 200, f"-> {r.status_code}")
if r.status_code == 200:
    items = r.json().get("items", [])
    check(
        "ES256 로그인 시 결과에 is_favorited 필드가 채워진다",
        all("is_favorited" in it for it in items),
    )

# ---------------------------------------------------------------------------
# --- 6. JWKS 조회/키 회전 (2026-08-13 Sprint 78 신설) -----------------------
#
# 커버리지로 찾은 **0% 경로**다. 위 §1~§5는 캐시를 미리 채워 두고 검증하므로
# `_fetch_jwks_locked()`와 `_get_jwk()`의 회전·속도제한 분기가 한 번도 실행되지 않았다
# (실측: api/auth.py 55-64, 78-83 미커버).
#
# 실제 운영에서 토큰이 지나는 길이 바로 이곳이다 — Supabase가 키를 회전하면 캐시에 없는
# kid가 오고, 그때 이 코드가 JWKS를 다시 받아야 로그인 사용자가 유지된다. 여기가 틀리면
# **전원 401**이 되거나, 반대로 외부 호출이 요청마다 나가 장애를 증폭시킨다.
#
# 네트워크는 쓰지 않는다 — `urllib.request.urlopen`을 대역으로 바꿔 응답만 흉내 낸다.
# 검증하는 계약 5가지:
#   (1) 캐시에 없는 kid가 오면 다시 받아 온다 (키 회전이 실제로 동작한다)
#   (2) 알 수 없는 kid가 쏟아져도 최소 간격 안에는 한 번만 받는다 (DoS 증폭 방지)
#   (3) 빈 응답으로 기존 캐시를 지우지 않는다 (일시 오류에 전원 로그아웃 방지)
#   (4) 조회 실패가 예외로 새어 나가지 않는다 (서버가 죽지 않는다)
#   (5) 실패해도 조회 시각을 갱신한다 (재시도 폭주 방지)
# ---------------------------------------------------------------------------
import contextlib  # noqa: E402
import io as _io  # noqa: E402
import json as _json  # noqa: E402
import urllib.request as _urlreq  # noqa: E402

_ROT_KID = "rotated-kid-" + secrets.token_hex(4)
_rot_priv = ec.generate_private_key(ec.SECP256R1())
_rot_priv_pem = _rot_priv.private_bytes(
    serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
    serialization.NoEncryption()).decode()
_rot_pub_jwk = jwk.construct(
    _rot_priv.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo).decode(), "ES256").to_dict()
_rot_pub_jwk = {k: (v.decode() if isinstance(v, bytes) else v) for k, v in _rot_pub_jwk.items()}
_rot_pub_jwk.update({"kid": _ROT_KID, "alg": "ES256", "use": "sig"})


class _FakeResponse:
    def __init__(self, payload):
        self._buf = _io.BytesIO(_json.dumps(payload).encode())

    def read(self, *a):
        return self._buf.read(*a)

    def __enter__(self):
        return self._buf

    def __exit__(self, *exc):
        return False


@contextlib.contextmanager
def _jwks_serving(payload=None, error=None, url_required=True):
    """JWKS 응답을 대역으로 바꾸고, 호출 횟수를 세어 돌려준다.

    모듈 전역(캐시/조회시각/URL)을 건드리므로 반드시 원래대로 되돌린다 —
    되돌리지 않으면 이 파일 뒤쪽 검사(§5의 엔드포인트 호출)가 오염된다.
    """
    calls = {"n": 0, "urls": []}
    orig_urlopen = _urlreq.urlopen
    orig_keys, orig_at = auth_mod._jwks_keys, auth_mod._jwks_fetched_at
    orig_url = auth_mod.SUPABASE_URL
    if url_required and not auth_mod.SUPABASE_URL:
        auth_mod.SUPABASE_URL = "https://qa-jwks.example.invalid"

    def fake_urlopen(url, *a, **k):
        calls["n"] += 1
        calls["urls"].append(url)
        if error is not None:
            raise error
        return _FakeResponse(payload if payload is not None else {"keys": []})

    _urlreq.urlopen = fake_urlopen
    try:
        yield calls
    finally:
        _urlreq.urlopen = orig_urlopen
        auth_mod._jwks_keys, auth_mod._jwks_fetched_at = orig_keys, orig_at
        auth_mod.SUPABASE_URL = orig_url


def _rot_token():
    return jwt.encode({"sub": USER}, _rot_priv_pem, algorithm="ES256",
                      headers={"kid": _ROT_KID})


# (1) 키 회전: 캐시에 없는 kid -> 다시 받아 와서 검증까지 성공해야 한다.
with _jwks_serving({"keys": [_rot_pub_jwk]}) as calls:
    auth_mod._jwks_keys = {TEST_KID: _pub_jwk}
    auth_mod._jwks_fetched_at = time.monotonic() - (auth_mod._JWKS_MIN_REFETCH_SECONDS + 1)
    rotated, rot_err = None, None
    try:
        rotated = decode_supabase_jwt(_rot_token())
    except Exception as exc:  # noqa: BLE001 - 실패를 크래시가 아니라 FAIL로 만든다
        rot_err = exc
    check("키 회전: 모르는 kid면 JWKS를 다시 받는다", calls["n"] == 1, f"-> 호출 {calls['n']}회")
    check("키 회전: 새 키로 서명된 토큰이 검증된다",
          rot_err is None and rotated and rotated.get("sub") == USER, f"-> {rot_err!r}")
    check("키 회전: JWKS 주소가 Supabase 규약 경로다",
          calls["urls"] and calls["urls"][0].endswith("/auth/v1/.well-known/jwks.json"),
          f"-> {calls['urls']}")

# (2) 속도 제한: 모르는 kid가 연속으로 와도 최소 간격 안에는 한 번만 받는다.
with _jwks_serving({"keys": [_rot_pub_jwk]}) as calls:
    auth_mod._jwks_keys = {TEST_KID: _pub_jwk}
    auth_mod._jwks_fetched_at = time.monotonic() - (auth_mod._JWKS_MIN_REFETCH_SECONDS + 1)
    for _ in range(5):
        auth_mod._get_jwk("unknown-kid-" + secrets.token_hex(2))
    check("속도 제한: 모르는 kid 5연속에도 외부 조회는 1회", calls["n"] == 1,
          f"-> 호출 {calls['n']}회 (요청마다 나가면 외부 장애를 증폭시킨다)")

# (3) 빈 응답이 기존 캐시를 지우지 않는다 (일시 오류에 전원 로그아웃 방지).
with _jwks_serving({"keys": []}) as calls:
    auth_mod._jwks_keys = {TEST_KID: _pub_jwk}
    auth_mod._jwks_fetched_at = time.monotonic() - (auth_mod._JWKS_MIN_REFETCH_SECONDS + 1)
    auth_mod._get_jwk("nope")
    check("빈 JWKS 응답이 기존 캐시를 날리지 않는다", auth_mod._jwks_keys.get(TEST_KID) is not None)
    kept = None
    try:
        kept = decode_supabase_jwt(es256({"sub": USER}))
    except Exception as exc:  # noqa: BLE001
        kept = exc
    check("빈 응답 뒤에도 기존 키 토큰은 검증된다",
          isinstance(kept, dict) and kept.get("sub") == USER, f"-> {kept!r}")

# (4)(5) 조회 실패: 예외가 새지 않고, 조회 시각은 갱신된다(재시도 폭주 방지).
with _jwks_serving(error=OSError("network down")) as calls:
    auth_mod._jwks_keys = {TEST_KID: _pub_jwk}
    stale_at = time.monotonic() - (auth_mod._JWKS_MIN_REFETCH_SECONDS + 1)
    auth_mod._jwks_fetched_at = stale_at
    raised = None
    try:
        got = auth_mod._get_jwk("nope")
    except Exception as exc:  # noqa: BLE001
        raised = exc
    check("JWKS 조회 실패가 예외로 새지 않는다", raised is None, f"-> {raised!r}")
    check("실패 시 그 kid는 None으로 돌려준다(인증 실패로만 이어진다)",
          raised is None and got is None)
    check("실패해도 조회 시각을 갱신한다(재시도 폭주 방지)",
          auth_mod._jwks_fetched_at > stale_at)
    after_fail = None
    try:
        after_fail = decode_supabase_jwt(es256({"sub": USER}))
    except Exception as exc:  # noqa: BLE001
        after_fail = exc
    check("실패 뒤에도 기존 캐시로 검증은 계속된다",
          isinstance(after_fail, dict) and after_fail.get("sub") == USER, f"-> {after_fail!r}")

# (6) 캐시가 신선하고 kid도 알고 있으면 외부 호출이 아예 없어야 한다.
with _jwks_serving({"keys": [_rot_pub_jwk]}) as calls:
    auth_mod._jwks_keys = {TEST_KID: _pub_jwk}
    auth_mod._jwks_fetched_at = time.monotonic()
    decode_supabase_jwt(es256({"sub": USER}))
    check("신선한 캐시 적중 시 외부 조회 0회", calls["n"] == 0, f"-> 호출 {calls['n']}회")

# (7) SUPABASE_URL이 없으면 조회를 시도하지 않는다(설정 미비 환경에서 네트워크 접근 금지).
with _jwks_serving({"keys": [_rot_pub_jwk]}, url_required=False) as calls:
    auth_mod.SUPABASE_URL = ""
    auth_mod._jwks_keys = {}
    auth_mod._jwks_fetched_at = 0.0
    check("URL 미설정이면 JWKS 조회를 시도하지 않는다",
          auth_mod._get_jwk("any") is None and calls["n"] == 0, f"-> 호출 {calls['n']}회")

# (8) 설정 미비 시 fail-closed (2026-08-13 Sprint 88)
#
# 커버리지가 지목한 두 분기다. 둘 다 **검증 수단이 없을 때 통과시키지 않는다**는
# 보안 규약인데 한 번도 실행된 적이 없었다.
#
#   HS256 토큰인데 SUPABASE_JWT_SECRET이 비어 있음  -> JWTError로 거부
#   대칭/비대칭 어느 쪽 수단도 없음                  -> 500 (설정 오류를 숨기지 않는다)
#
# 여기서 조용히 통과시키면 **서명 검증 없이 아무 토큰이나 받는 상태**가 된다.
_saved_secret, _saved_url = auth_mod.SUPABASE_JWT_SECRET, auth_mod.SUPABASE_URL
try:
    _hs_token = hs256({"sub": USER})

    auth_mod.SUPABASE_JWT_SECRET = ""
    expect_jwt_error("HS256 토큰인데 시크릿 미설정이면 거부",
                     lambda: auth_mod.decode_supabase_jwt(_hs_token))

    # 시크릿을 되돌리면 같은 토큰이 다시 통과한다(거부가 토큰 탓이 아님을 확인).
    auth_mod.SUPABASE_JWT_SECRET = _saved_secret
    check("시크릿을 되돌리면 같은 토큰이 통과한다",
          auth_mod.decode_supabase_jwt(_hs_token).get("sub") == USER)

    # get_current_user: 검증 수단이 하나도 없으면 500이다(401이 아니라).
    # 401로 만들면 "토큰이 잘못됐다"로 읽혀 서버 설정 문제가 사용자 탓으로 보인다.
    from fastapi import HTTPException
    from fastapi.security import HTTPAuthorizationCredentials

    auth_mod.SUPABASE_JWT_SECRET = ""
    auth_mod.SUPABASE_URL = ""
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=_hs_token)
    try:
        auth_mod.get_current_user(creds)
        check("검증 수단이 없으면 500", False, "-> 예외 없이 통과함")
    except HTTPException as exc:
        check("검증 수단이 없으면 500", exc.status_code == 500, f"-> {exc.status_code}")
    except Exception as exc:  # noqa: BLE001
        check("검증 수단이 없으면 500", False, f"-> {type(exc).__name__}")
finally:
    auth_mod.SUPABASE_JWT_SECRET, auth_mod.SUPABASE_URL = _saved_secret, _saved_url

check("정리 후 시크릿이 복원됐다", auth_mod.SUPABASE_JWT_SECRET == _saved_secret)


# ===========================================================================
# .env 로딩이 **작업 디렉터리에 의존하지 않는가** (2026-08-21 Sprint 245 신설)
#
# ## 왜 생겼나
#
# `api/auth.py` 는 예전에 `load_dotenv()` / `load_dotenv(".env.local")` 를 썼다.
# 둘 다 **cwd 기준**이라, 저장소 루트가 아닌 곳에서 서버를 띄우면 환경변수를 하나도
# 못 읽었다. 실측(2026-08-21, 같은 코드를 cwd 만 바꿔 임포트):
#
#     cwd = 저장소 루트   JWT_SECRET 88자 / SUPABASE_URL 40자  -> 정상
#     cwd = 다른 폴더     JWT_SECRET  0자 / SUPABASE_URL 빈값  -> 인증 API 전부 500
#
# 그 상태에서 `GET /api/v1/favorites` 는 401 이 아니라 **500 "JWT 검증 설정 미비"** 다.
# 로그인 사용자의 관심물건·최근본·검색조건·마이페이지·등기부가 전부 죽는다.
# 게다가 문구가 "설정 미비"라 시크릿을 의심하게 되는데 진짜 원인은 작업 디렉터리다.
#
# `.bat` 3개는 `cd /d %~dp0` 로 보호되지만, 문서가 안내하는
# `uvicorn api_server:app --reload` 와 서비스 등록(NSSM/작업 스케줄러)은 그렇지 않다.
# 이 저장소는 실제로 그 함정을 한 번 밟았다(Sprint 241).
#
# ## 검사 방법
#
# **별도 프로세스를 다른 cwd 에서 띄운다.** 같은 프로세스 안에서는 이미 로드된
# `os.environ` 이 남아 있어 cwd 를 바꿔도 재현되지 않는다 - 그러면 검사가 공허해진다.
# ===========================================================================
import subprocess as _sp
import tempfile as _tf
import shutil as _sh

_REPO = os.path.dirname(os.path.abspath(__file__))

_PROBE = (
    "import api.auth as a;"
    "print('SECRET=%d URL=%d' % (len(a.SUPABASE_JWT_SECRET), len(a.SUPABASE_URL)))"
)


def _probe_from(cwd):
    """`cwd` 에서 별도 프로세스로 api.auth 를 임포트하고 (secret길이, url길이) 를 얻는다."""
    env = dict(os.environ)
    env["PYTHONPATH"] = _REPO
    env["PYTHONIOENCODING"] = "utf-8"
    # 부모 프로세스가 이미 읽어 둔 값이 상속되면 검사가 공허해진다 - 지우고 띄운다.
    for k in ("SUPABASE_JWT_SECRET", "SUPABASE_URL", "SUPABASE_ANON_KEY",
              "NEXT_PUBLIC_SUPABASE_URL"):
        env.pop(k, None)
    r = _sp.run([sys.executable, "-c", _PROBE], cwd=cwd, env=env,
                capture_output=True, timeout=120)
    out = (r.stdout or b"").decode("utf-8", "replace").strip()
    m = re.search(r"SECRET=(\d+) URL=(\d+)", out)
    if not m:
        return None, (out + (r.stderr or b"").decode("utf-8", "replace"))[:200]
    return (int(m.group(1)), int(m.group(2))), out


print()
print("--- .env 로딩이 작업 디렉터리에 의존하지 않는가 (Sprint 245) ---")

# ★ 2026-08-26 — 공허함 판정을 **둘 중 하나라도 있으면**으로 바꿨다.
#
#   예전에는 `_root_vals[0] > 0`, 즉 **`SUPABASE_JWT_SECRET` 이 설정돼 있어야만** 이
#   검사가 성립했다. 그런데 그 변수는 **HS256(레거시) 전용이고 선택 사항**이다 —
#   Supabase 는 지금 ES256 을 발급하고, 그 경로는 `SUPABASE_URL` -> JWKS 로만 검증한다.
#   `.env` 에 그 변수가 없는 환경(=지금 이 머신)에서는 **재려던 성질과 무관한 이유로**
#   빨간불이 켜졌다. 실제로 성질 자체는 성립하고 있었다:
#
#       cwd=저장소 루트   SECRET=0 URL=40 (src=NEXT_PUBLIC_SUPABASE_URL)
#       cwd=임시 폴더     SECRET=0 URL=40 (src=NEXT_PUBLIC_SUPABASE_URL)
#
#   이 검사가 지켜야 하는 것은 "`.env` 를 **cwd 가 아니라 `__file__` 기준으로** 읽는가"다.
#   그것은 **해석된 값 아무거나 하나**로 확인할 수 있다. 그래서 게이트를 넓히되
#   **공허해지지는 않게** 한다 — 둘 다 0이면 여전히 실패한다(그때는 정말 잴 것이 없다).
#
#   그리고 **있는 값만** 비교한다. 0자인 항목을 "루트도 0 다른 폴더도 0 이니 통과"로
#   세면 그거야말로 공허한 통과다(BUGS #204 가 경계한 모양).
_root_vals, _root_raw = _probe_from(_REPO)
check("저장소 루트에서 설정을 하나라도 읽는다(검사가 공허하지 않다)",
      _root_vals is not None and (_root_vals[0] > 0 or _root_vals[1] > 0),
      f"-> {_root_raw}  (SUPABASE_JWT_SECRET 과 SUPABASE_URL 이 **둘 다** 비어 있으면"
      " cwd 비의존을 확인할 재료가 없다)")

if _root_vals and (_root_vals[0] > 0 or _root_vals[1] > 0):
    _tmp = _tf.mkdtemp(prefix="qa_cwd_")
    try:
        _other_vals, _other_raw = _probe_from(_tmp)
        check("다른 디렉터리에서도 임포트가 성공한다",
              _other_vals is not None, f"-> {_other_raw}")
        if _other_vals:
            # 루트에서 값이 있던 항목만 본다 — 애초에 0인 것을 "0==0" 으로 통과시키지 않는다.
            _compared = 0
            if _root_vals[0] > 0:
                _compared += 1
                check("★ 다른 디렉터리에서도 JWT 시크릿을 읽는다(cwd 비의존)",
                      _other_vals[0] == _root_vals[0],
                      f"-> 루트 {_root_vals[0]}자 vs 다른 폴더 {_other_vals[0]}자. "
                      "load_dotenv 가 cwd 기준이면 0자가 된다")
            if _root_vals[1] > 0:
                _compared += 1
                check("★ 다른 디렉터리에서도 SUPABASE_URL 을 읽는다(JWKS/ES256 경로)",
                      _other_vals[1] == _root_vals[1],
                      f"-> 루트 {_root_vals[1]}자 vs 다른 폴더 {_other_vals[1]}자. "
                      "load_dotenv 가 cwd 기준이면 0자가 된다")
            check("실제로 대조한 항목이 있다(0==0 통과가 아니다)", _compared > 0,
                  f"-> 대조 {_compared}건")
    finally:
        _sh.rmtree(_tmp, ignore_errors=True)

# 소스 수준 가드 - 편집 시점에 되돌리는 것을 잡는다(주석은 제외하고 코드만 본다)
for _f in ("api/auth.py", "api_server.py"):
    _src = io.open(os.path.join(_REPO, _f), encoding="utf-8-sig").read()
    _code = "\n".join(l for l in _src.splitlines() if not l.lstrip().startswith("#"))
    _bare = re.findall(r"load_dotenv\(\s*\)", _code)
    check(f"★ {_f} 가 인자 없는 load_dotenv() 를 쓰지 않는다(cwd 의존)",
          not _bare,
          "-> load_dotenv() 는 cwd 기준이다. __file__ 기준 절대경로를 넘겨라")
    _rel = re.findall(r"load_dotenv\(\s*['\"]\.env", _code)
    check(f"★ {_f} 가 상대경로 문자열로 .env 를 찾지 않는다",
          not _rel,
          "-> 상대경로도 cwd 기준이다")


# ---------------------------------------------------------------------------
# 설정이 비었을 때의 **실패 방식** (2026-08-21 Sprint 246 신설)
#
# ## 왜 필요한가
#
# Sprint 245 에서 `.env` 로딩의 cwd 의존을 고쳤다. 그때 확인한 것은 "제대로 읽는가"였다.
# 남은 절반은 **못 읽었을 때 어떻게 무너지는가**다. 배포 환경이 바뀌거나 시크릿이
# 아직 주입되지 않은 순간은 실제로 생기고, 그때의 동작이 다음 두 가지여야 한다:
#
#   (1) 시크릿과 무관한 **공개 API 는 계속 살아 있다.**
#       검색/상세/사진/요금제는 로그인이 필요 없다. 이것들이 500 이 되면
#       "설정 하나 빠졌다"가 **서비스 전면 장애**로 번진다.
#   (2) 보호 API 는 **거부**한다. 조용히 통과시키면 그게 인증 우회다.
#
# 그리고 **틀린 시크릿**은 무토큰보다 위험하다 - 값이 있으니 검증을 시도하는데,
# 여기서 실패를 삼키면 위조 토큰이 로그인으로 취급된다.
#
# ## 검사 방법
#
# 앱이 실제로 읽는 그 모듈 변수(`api.auth.SUPABASE_JWT_SECRET` / `SUPABASE_URL`)를
# 비우고/틀리게 바꾼다. 라우트는 요청 시점에 이 값을 보므로 **실제 설정 경로 그대로**다.
# 값 자체는 절대 출력하지 않는다 - 길이와 상태만 본다.
# ---------------------------------------------------------------------------
print()
print("--- 설정이 비었을 때의 실패 방식 (Sprint 246) ---")

_PUBLIC_PATHS = [
    "/",
    "/api/v1/search?size=1",
    "/api/v1/search/regions?sido=%EC%84%9C%EC%9A%B8",
    "/api/v1/stats",
    "/api/v1/plans",
]
_PROTECTED_PATHS = [
    "/api/v1/favorites",
    "/api/v1/recent-items",
    "/api/v1/search-presets",
]

# 공개 상세/사진은 DB 에 물건이 있어야 의미가 있다 - 있으면 붙인다(없으면 건너뛴다).
_probe_items = client.get("/api/v1/search?size=1")
_sample_id = None
if _probe_items.status_code == 200:
    _its = _probe_items.json().get("items", [])
    if _its:
        _sample_id = _its[0].get("id") or _its[0].get("item_id")
if _sample_id:
    _PUBLIC_PATHS.append(f"/api/v1/item/{_sample_id}")

_env_saved = (auth_mod.SUPABASE_JWT_SECRET, auth_mod.SUPABASE_URL)
check("검사가 공허하지 않다(정상 상태에서 시크릿이 실제로 있다)",
      len(_env_saved[0]) > 0, "-> 길이 0. 이 상태로는 아래 검사가 아무것도 구분하지 못한다")
check("검사가 공허하지 않다(공개 경로 표본을 확보했다)", len(_PUBLIC_PATHS) >= 5,
      f"-> {len(_PUBLIC_PATHS)}개")

# 진짜 시크릿으로 서명한 토큰을 **바꾸기 전에** 만들어 둔다(아래 (2)에서 쓴다).
_good_token = hs256({"sub": USER})

try:
    # --- (1) 시크릿이 통째로 없을 때 -------------------------------------
    auth_mod.SUPABASE_JWT_SECRET = ""
    auth_mod.SUPABASE_URL = ""

    _broken = []
    for _p in _PUBLIC_PATHS:
        _r = client.get(_p)
        if _r.status_code >= 500:
            _broken.append((_p, _r.status_code))
    check("★ 시크릿이 없어도 공개 API 가 500 이 되지 않는다",
          not _broken,
          f"-> {_broken}. 공개 경로가 인증 설정에 묶여 있다 - 설정 누락이 전면 장애가 된다")

    _passed_through = []
    for _p in _PROTECTED_PATHS:
        _r = client.get(_p)
        if _r.status_code < 400:
            _passed_through.append((_p, _r.status_code))
    check("★ 시크릿이 없으면 보호 API 는 통과시키지 않는다",
          not _passed_through,
          f"-> {_passed_through}. 설정이 없는데 인증이 성공했다 = 우회다")

    # 실패하더라도 **시크릿/내부 경로를 흘리지 않아야** 한다
    _leaks = []
    for _p in _PROTECTED_PATHS:
        _body = client.get(_p).text
        if _env_saved[0] and _env_saved[0] in _body:
            _leaks.append((_p, "secret"))
        if "Traceback (most recent call last)" in _body:
            _leaks.append((_p, "traceback"))
    check("★ 실패 응답이 시크릿이나 스택트레이스를 노출하지 않는다",
          not _leaks, f"-> {_leaks}")

    # --- (1b) ★ 시크릿만 비고 URL 은 살아 있을 때 = **빈 키 위조** ------------
    #
    #     이게 이 절에서 가장 위험한 경우다. HMAC-SHA256 은 **빈 키도 정상 키**라
    #     `jwt.decode(token, "", algorithms=["HS256"])` 가 그냥 **통과한다**
    #     (2026-08-21 실측: 빈 키로 서명한 sub=attacker 토큰이 빈 키 검증을 통과).
    #
    #     그래서 시크릿이 비면 "아무도 로그인 못 한다"가 아니라
    #     **"누구나 아무 사용자로 로그인된다"** 가 될 수 있다.
    #     `api/auth.py` 의 `if not SUPABASE_JWT_SECRET: raise JWTError(...)` 가 그걸 막는다.
    #
    #     `get_current_user` 의 "둘 다 없으면 500" 가드는 **이 경우를 막지 못한다** -
    #     `SUPABASE_URL` 이 살아 있으면(지금 저장소의 실제 상태다) 그 가드는 통과한다.
    #     즉 이 검사가 없으면 그 한 줄을 지워도 아무도 모른다(mutation 으로 확인했다).
    auth_mod.SUPABASE_JWT_SECRET = ""
    auth_mod.SUPABASE_URL = _env_saved[1] or "https://example.supabase.co"

    _empty_key_token = jwt.encode({"sub": "attacker"}, "", algorithm="HS256")
    _r = client.get("/api/v1/favorites",
                    headers={"Authorization": f"Bearer {_empty_key_token}"})
    check("★ 시크릿이 비었을 때 **빈 키로 서명한 위조 토큰**을 거부한다",
          _r.status_code in (401, 403),
          f"-> {_r.status_code}. 빈 키 HMAC 은 검증에 성공한다 - "
          "시크릿이 비면 누구나 아무 사용자로 로그인된다")

    _rejected_empty = False
    try:
        decode_supabase_jwt(_empty_key_token)
    except JWTError:
        _rejected_empty = True
    check("★ 검증 함수 자체가 빈 시크릿으로 HS256 을 검증하지 않는다",
          _rejected_empty, "-> 빈 키 검증을 시도했고 통과시켰다")

    # --- (2) 시크릿이 **틀린** 값일 때 ------------------------------------
    #     길이는 정상인데 내용이 다르다 = 배포에서 가장 흔한 잘못된 설정.
    #
    #     ★ 토큰은 **바꾸기 전에** 진짜 시크릿으로 미리 만들어 둔다.
    #       `hs256()` 은 호출 시점의 모듈 값으로 서명하므로, 바꾼 뒤에 만들면
    #       틀린 시크릿으로 서명하고 틀린 시크릿으로 검증해 **항상 통과한다**
    #       - 검사가 공허해진다(2026-08-21 실제로 이 함정을 밟고 잡았다).
    auth_mod.SUPABASE_JWT_SECRET = "z" * len(_env_saved[0])
    auth_mod.SUPABASE_URL = ""          # JWKS 경로도 막아 HS256 만 남긴다

    _r = client.get("/api/v1/favorites",
                    headers={"Authorization": f"Bearer {_good_token}"})
    check("★ 시크릿이 틀리면 정상 토큰도 거부한다(조용히 통과 금지)",
          _r.status_code in (401, 403), f"-> {_r.status_code}")

    _r = client.get("/api/v1/search?size=1",
                    headers={"Authorization": f"Bearer {_good_token}"})
    check("★ 시크릿이 틀려도 선택적 인증 API 는 200 이다(검색을 막지 않는다)",
          _r.status_code == 200, f"-> {_r.status_code}")

    # 선택적 인증이 그 토큰을 **로그인으로 취급하지 않는지**를 직접 본다.
    #   `is_favorited` 로는 판정할 수 없다 - 이 사용자는 관심물건이 없어서
    #   로그인이든 아니든 False 다(= 공허한 검사가 된다).
    #   대신 검증 함수 자체가 거부하는지를 본다.
    _rejected = False
    try:
        decode_supabase_jwt(_good_token)
    except JWTError:
        _rejected = True
    check("★ 시크릿이 틀리면 검증 함수가 예외로 거부한다(삼키지 않는다)",
          _rejected, "-> 서명 불일치를 통과시켰다")
finally:
    auth_mod.SUPABASE_JWT_SECRET, auth_mod.SUPABASE_URL = _env_saved

check("정리 후 설정이 복원됐다",
      auth_mod.SUPABASE_JWT_SECRET == _env_saved[0]
      and auth_mod.SUPABASE_URL == _env_saved[1])
_r = client.get("/api/v1/favorites",
                headers={"Authorization": f"Bearer {hs256({'sub': USER})}"})
check("복원 후 정상 토큰이 다시 통한다(검사가 뒤를 오염시키지 않았다)",
      _r.status_code == 200, f"-> {_r.status_code}")

print()
print("--- SUPABASE_URL 값에 경로가 섞여 있어도 JWKS 주소가 안 깨지는가 (Sprint 267) ---")
# 막으려는 고장: 프로젝트 URL 자리에 REST API 베이스 URL(".../rest/v1/")이 들어가면
# 예전 코드(.rstrip("/")만 적용)는 그 경로를 그대로 남겨 JWKS 주소가
# ".../rest/v1/auth/v1/.well-known/jwks.json"이 되고, 그 주소로는 키를 못 받는다 -
# ES256(주 인증 경로) 검증이 전부 실패한다. `_project_origin()`이 scheme+host만
# 남기도록 고쳤고, 여기서 그 정규화 자체를 고정한다.
#
# ★ 2026-08-24 정정 — 원래 이 주석은 "실측(2026-08-23): **이 환경의** .env가 ... 잘못
#   넣어 두고 있었다"라고 단정했다. 이 저장소의 현재 상태에서는 재현되지 않는다 -
#   .env 에 NEXT_PUBLIC_SUPABASE_URL 키 자체가 없고, .env.local 의 값은 경로가 없다
#   (2026-08-24 실측, api/auth.py:_project_origin docstring 에 수치 기록).
#   아래 네 개의 단언은 환경과 무관한 순수 함수 검사라 그대로 유효하다.
check("★ REST API 베이스 URL이 섞여도 origin만 남는다",
      auth_mod._project_origin("https://abcxyz.supabase.co/rest/v1/")
      == "https://abcxyz.supabase.co")
check("★ 경로 없는 정상 값은 그대로 유지된다",
      auth_mod._project_origin("https://abcxyz.supabase.co")
      == "https://abcxyz.supabase.co")
check("★ 끝 슬래시만 있는 값도 정리된다(기존 동작 유지)",
      auth_mod._project_origin("https://abcxyz.supabase.co/")
      == "https://abcxyz.supabase.co")
check("★ 빈 값은 빈 값 그대로다(JWKS 조회 스킵 경로 유지)",
      auth_mod._project_origin("") == "")

print("=" * 70)
print(f" 결과: {PASS} PASS / {FAIL} FAIL")
print("=" * 70)
sys.exit(1 if FAIL else 0)
