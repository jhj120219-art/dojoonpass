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

print("=" * 70)
print(f" 결과: {PASS} PASS / {FAIL} FAIL")
print("=" * 70)
sys.exit(1 if FAIL else 0)
