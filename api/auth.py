import json
import logging
import os
import threading
import time
import urllib.request
from typing import Any, Optional
from dotenv import load_dotenv
from fastapi import HTTPException, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError
from jose.exceptions import JOSEError

from api.constants import ErrorCode

logger = logging.getLogger(__name__)

load_dotenv()
# JWKS 주소를 만들려면 프로젝트 URL이 필요한데, 이 저장소에서 그 값은 `.env`가 아니라
# `.env.local`의 NEXT_PUBLIC_SUPABASE_URL에만 있다. 값을 **읽기만** 한다(파일 수정 없음).
load_dotenv(".env.local", override=False)

SUPABASE_JWT_SECRET = os.getenv("SUPABASE_JWT_SECRET", "")
SUPABASE_URL = (os.getenv("SUPABASE_URL") or os.getenv("NEXT_PUBLIC_SUPABASE_URL") or "").rstrip("/")
bearer_scheme = HTTPBearer()

# ---------------------------------------------------------------------------
# JWT 검증: ES256(JWKS) + HS256(레거시 공유 시크릿)
#
# 배경(docs/BUGS.md #27): Supabase 프로젝트가 **비대칭 서명(ES256)** 으로 전환됐는데 이 코드는
# `algorithms=["HS256"]` + 공유 시크릿으로만 검증하고 있었다. ES256 토큰은 그 방식으로는
# 원리상 검증되지 않아 로그인 사용자의 모든 인증 API가 401이 됐다(즐겨찾기/최근조회/
# 검색조건 저장/등기부/결제). Secret 교체로는 해결되지 않는 문제이며 검증 경로를 고쳐야 한다.
#
# **HS256을 계속 허용하는 이유**: 전환기에 남아있는 기존 토큰과, 합성 시크릿으로 HS256 토큰을
# 발급해 인증 로직을 검증하는 기존 회귀 스위트(`test_api_regression.py`)가 그대로 동작해야 한다.
#
# **알고리즘은 반드시 화이트리스트로 고정한다.** 토큰이 알려준 `alg`를 그대로 신뢰해
# `algorithms=[alg]`로 넘기면 `alg: "none"` 위조가 통과한다(기존 회귀 테스트가 이미 이 공격을
# 검사하고 있다). 아래 두 집합에 없는 alg는 전부 거부한다.
# ---------------------------------------------------------------------------
_ALLOWED_SYMMETRIC_ALGS = ("HS256",)
_ALLOWED_ASYMMETRIC_ALGS = ("ES256", "ES384", "ES512", "RS256", "RS384", "RS512")

_JWKS_TTL_SECONDS = 600          # 캐시 유효기간 — 요청마다 JWKS를 받지 않는다
_JWKS_MIN_REFETCH_SECONDS = 30   # 알 수 없는 kid가 쏟아져도 외부 호출이 폭주하지 않게 하는 하한
_jwks_lock = threading.Lock()
_jwks_keys: dict = {}
_jwks_fetched_at = 0.0


def _fetch_jwks_locked() -> None:
    """JWKS를 받아 kid -> JWK 맵으로 캐시한다. 호출자가 _jwks_lock을 잡고 있어야 한다."""
    global _jwks_keys, _jwks_fetched_at
    _jwks_fetched_at = time.monotonic()  # 실패해도 갱신 — 실패 시 재시도 폭주 방지
    if not SUPABASE_URL:
        return
    url = f"{SUPABASE_URL}/auth/v1/.well-known/jwks.json"
    with urllib.request.urlopen(url, timeout=5) as res:
        data = json.load(res)
    keys = {k["kid"]: k for k in data.get("keys", []) if k.get("kid")}
    # 빈 응답으로 기존 캐시를 날리지 않는다(일시적 오류에 기존 키를 잃으면 전원 로그아웃된다).
    if keys:
        _jwks_keys = keys


def _get_jwk(kid: str):
    """kid에 해당하는 공개키(JWK dict)를 돌려준다. 없으면 None.

    키 회전 대응: 캐시에 없는 kid가 오면 재조회한다(단 _JWKS_MIN_REFETCH_SECONDS 하한).
    """
    now = time.monotonic()
    with _jwks_lock:
        fresh = (now - _jwks_fetched_at) < _JWKS_TTL_SECONDS
        if kid in _jwks_keys and fresh:
            return _jwks_keys[kid]
        if (now - _jwks_fetched_at) >= _JWKS_MIN_REFETCH_SECONDS or not _jwks_keys:
            try:
                _fetch_jwks_locked()
            except Exception as exc:
                # 네트워크/파싱 실패는 인증 실패로만 이어지게 하고 서버를 죽이지 않는다.
                # 비밀값이 로그에 남지 않도록 예외 타입만 남긴다.
                logger.warning("JWKS 조회 실패(%s) — 기존 캐시로 검증 시도", type(exc).__name__)
        return _jwks_keys.get(kid)


def decode_supabase_jwt(token: str) -> dict:
    """Supabase access token을 검증하고 payload를 돌려준다.

    검증에 실패하면 **항상 JWTError**를 던진다. 호출부가 인증 필수(401)와 선택적 인증
    (비로그인으로 강등)을 각자 판단할 수 있어야 하기 때문이다 — 여기서 HTTPException을
    던지면 검색 같은 선택적 인증 API가 토큰 문제로 통째로 실패한다.
    """
    # jose는 상황에 따라 JWTError가 아니라 형제 예외(JWSError 등, 공통 조상은 JOSEError)를
    # 던진다. 호출부는 `except JWTError`만 잡으므로, 그대로 새어 나가면 **선택적 인증**
    # 라우트(검색/상세)가 토큰이 이상하다는 이유로 500이 된다 — 비로그인으로 강등돼야 하는데.
    # 검증 실패는 종류를 불문하고 JWTError 하나로 정규화한다.
    try:
        try:
            header = jwt.get_unverified_header(token)
        except Exception as exc:  # 형식이 아예 JWT가 아닌 경우 포함
            raise JWTError(f"토큰 헤더를 읽을 수 없습니다: {type(exc).__name__}") from exc

        alg = header.get("alg")

        if alg in _ALLOWED_SYMMETRIC_ALGS:
            if not SUPABASE_JWT_SECRET:
                raise JWTError("HS256 토큰이지만 SUPABASE_JWT_SECRET이 설정되지 않았습니다")
            return jwt.decode(
                token,
                SUPABASE_JWT_SECRET,
                algorithms=list(_ALLOWED_SYMMETRIC_ALGS),
                options={"verify_aud": False},
            )

        if alg in _ALLOWED_ASYMMETRIC_ALGS:
            kid = header.get("kid")
            if not kid:
                raise JWTError("kid가 없는 비대칭 서명 토큰입니다")
            key = _get_jwk(kid)
            if key is None:
                raise JWTError("JWKS에서 해당 kid의 공개키를 찾지 못했습니다")
            return jwt.decode(
                token,
                key,
                algorithms=[alg],
                options={"verify_aud": False},
            )

        # alg: "none" 등 화이트리스트 밖은 전부 거부
        raise JWTError(f"허용되지 않는 서명 알고리즘입니다: {alg!r}")
    except JWTError:
        raise
    except JOSEError as exc:
        raise JWTError(f"토큰 검증 실패: {type(exc).__name__}") from exc


def get_current_user(credentials: HTTPAuthorizationCredentials = Security(bearer_scheme)) -> str:
    token = credentials.credentials
    # 대칭/비대칭 어느 쪽도 검증할 수단이 없으면 설정 오류다(기존 "JWT Secret 미설정" 500 유지).
    if not SUPABASE_JWT_SECRET and not SUPABASE_URL:
        raise HTTPException(status_code=500, detail="JWT 검증 설정 미비")
    try:
        payload = decode_supabase_jwt(token)
    except JWTError as exc:
        # 실패 사유를 남긴다. 토큰/시크릿은 절대 로그에 넣지 않는다 — 사유 문자열만 남긴다.
        # (원인 없이 401만 떨어지면 ES256 전환 같은 사고를 며칠씩 못 찾는다. 실제로 그랬다.)
        logger.warning("JWT 검증 실패: %s", exc)
        raise HTTPException(status_code=401, detail="토큰 검증 실패")
    user_id: str = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="유효하지 않은 토큰")
    return user_id


# ---------------------------------------------------------------------------
# 공통 응답 형식 (CTO 승인 8번으로 표준화)
#
#   { "success": bool, "data": any, "error": str|null, "meta": dict|null, "message": str|null }
#
# ★ `message`는 **제거하지 않는다**. 프론트가 `result.message`를 읽고 있어(예:
#   `setRegistryMessage(result.message ?? '...')`) 없애면 Breaking Change다.
#   `error`(도메인 Error Code)와 `meta`(페이지네이션 등)는 **추가** 필드이므로
#   기존 클라이언트는 영향을 받지 않는다.
#
# 클라이언트는 문구가 아니라 `error` 코드로 분기해야 한다 — 한국어 메시지는 언제든 바뀐다.
# ---------------------------------------------------------------------------
def success(data: Any, message: Optional[str] = None, meta: Optional[dict] = None) -> dict:
    return {
        "success": True,
        "data": data,
        "error": None,
        "meta": meta,
        "message": message,
    }


def fail(message: str, error: Optional[str] = None, meta: Optional[dict] = None) -> dict:
    """실패 응답. `error`를 생략하면 미분류(INTERNAL_ERROR가 아니라 null)로 둔다 —
    코드가 붙지 않은 기존 호출부를 억지로 특정 코드로 몰아넣으면 오히려 오해를 부른다."""
    return {
        "success": False,
        "data": None,
        "error": str(error) if error else None,
        "meta": meta,
        "message": message,
    }


def error_response(code: ErrorCode, message: str, meta: Optional[dict] = None) -> dict:
    """Error Code를 반드시 붙이는 실패 응답. 신규 코드는 이쪽을 쓴다."""
    return fail(message, error=code, meta=meta)
