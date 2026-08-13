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
import os
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

print("=" * 70)
print(f" 결과: {PASS} PASS / {FAIL} FAIL")
print("=" * 70)
sys.exit(1 if FAIL else 0)
