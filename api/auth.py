import os
from typing import Any, Optional
from dotenv import load_dotenv
from fastapi import HTTPException, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError

from api.constants import ErrorCode

load_dotenv()

SUPABASE_JWT_SECRET = os.getenv("SUPABASE_JWT_SECRET", "")
bearer_scheme = HTTPBearer()

def get_current_user(credentials: HTTPAuthorizationCredentials = Security(bearer_scheme)) -> str:
    token = credentials.credentials
    if not SUPABASE_JWT_SECRET:
        raise HTTPException(status_code=500, detail="JWT Secret 미설정")
    try:
        payload = jwt.decode(
            token,
            SUPABASE_JWT_SECRET,
            algorithms=["HS256"],
            options={"verify_aud": False}
        )
        user_id: str = payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="유효하지 않은 토큰")
        return user_id
    except JWTError:
        raise HTTPException(status_code=401, detail="토큰 검증 실패")


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
