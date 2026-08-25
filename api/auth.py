import json
import logging
import os
import threading
import time
import urllib.parse
import urllib.request
from typing import Any, Optional
from dotenv import load_dotenv
from fastapi import HTTPException, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError
from jose.exceptions import JOSEError

from api.constants import ErrorCode

logger = logging.getLogger(__name__)

# ★ `.env` 경로를 **현재 작업 디렉터리가 아니라 이 파일 기준**으로 잡는다
#   (2026-08-21 Sprint 245).
#
#   예전에는 `load_dotenv()` / `load_dotenv(".env.local")` 였다. 둘 다 **cwd 기준**이라
#   저장소 루트가 아닌 곳에서 서버를 띄우면 **환경변수를 하나도 못 읽는다.**
#
#   실측(2026-08-21, 같은 코드를 cwd 만 바꿔 임포트):
#       cwd = 저장소 루트   JWT_SECRET 88자 / SUPABASE_URL 40자   -> 정상
#       cwd = 다른 폴더     JWT_SECRET  0자 / SUPABASE_URL  빈값  -> get_current_user() 가
#                           "JWT 검증 설정 미비" **500** 을 던진다
#
#   그러면 로그인 사용자의 관심물건·최근본·검색조건·마이페이지·등기부가 전부 500 이 된다.
#   게다가 오류 문구가 "설정 미비"라 **시크릿이 없는 줄 알고 .env 를 뒤지게 된다** -
#   실제 원인은 작업 디렉터리다. 진단이 오래 걸리는 종류의 고장이다.
#
#   .bat 3개는 `cd /d %~dp0` 로 스스로를 보호하지만, 문서가 안내하는
#   `uvicorn api_server:app --reload` 는 운영자가 있는 아무 디렉터리에서 실행되고,
#   서비스 등록(NSSM/작업 스케줄러)도 작업 디렉터리를 따로 준다. 이 저장소는 실제로
#   그 함정을 한 번 밟았다(Sprint 241, fixture API 를 다른 cwd 에서 띄워 인증 전부 실패).
#
#   파일 기준 절대경로로 바꾸면 **어디서 띄워도 같은 값을 읽는다.** cwd 가 이미
#   저장소 루트인 경우 동작은 완전히 동일하다.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(_REPO_ROOT, ".env"))
# JWKS 주소를 만들려면 프로젝트 URL이 필요한데, 이 저장소에서 그 값은 `.env`가 아니라
# `.env.local`의 NEXT_PUBLIC_SUPABASE_URL에만 있다. 값을 **읽기만** 한다(파일 수정 없음).
load_dotenv(os.path.join(_REPO_ROOT, ".env.local"), override=False)

def _project_origin(url: str) -> str:
    """Supabase 프로젝트 URL에서 scheme+host만 남긴다 (2026-08-23 Sprint 267).

    막으려는 고장: 프로젝트 URL 자리에 REST API 베이스 URL
    (`https://<ref>.supabase.co/rest/v1/`)을 붙여 넣으면, `.rstrip("/")`만 하던 예전
    코드는 `/rest/v1` 경로를 그대로 남긴다. 그러면 JWKS 주소가
    `.../rest/v1/auth/v1/.well-known/jwks.json`이 되고 그 주소는 200을 주지 않는다
    (`.../auth/v1/.well-known/jwks.json`만 유효) - ES256(주 인증 경로) 검증이 전부
    실패한다. origin만 남기면 이런 오타에도 견딘다.

    ★ 2026-08-24 정정 — 이 docstring은 원래 "실측: **이 환경의** `.env`에
      `NEXT_PUBLIC_SUPABASE_URL=.../rest/v1/`이 들어 있었다"라고 단정했다.
      **이 저장소의 현재 상태에서는 재현되지 않는다.** 2026-08-24 실측:

          .env         SUPABASE_URL(빈값) / SUPABASE_ANON_KEY(빈값) / SUPABASE_JWT_SECRET(88자)
                       -> NEXT_PUBLIC_SUPABASE_URL 키 자체가 없다
          .env.local   NEXT_PUBLIC_SUPABASE_URL 40자, urlsplit().path == ''  (경로 없음)
          해석 결과    SUPABASE_URL 40자, path '' -> JWKS 경로 '/auth/v1/.well-known/jwks.json'

      즉 지금 이 정규화는 **오타를 고치고 있는 것이 아니라 방어만 하고 있다.**
      정규화 자체는 그대로 둘 가치가 있으므로 코드는 유지한다 — 고친 것은 사실 주장뿐이다.
      (값은 길이/경로 유무만 확인했고 어디에도 출력하지 않았다.)
    """
    parsed = urllib.parse.urlsplit(url)
    if not parsed.scheme or not parsed.netloc:
        return url.rstrip("/")
    return f"{parsed.scheme}://{parsed.netloc}"


SUPABASE_JWT_SECRET = os.getenv("SUPABASE_JWT_SECRET", "")
SUPABASE_URL = _project_origin(os.getenv("SUPABASE_URL") or os.getenv("NEXT_PUBLIC_SUPABASE_URL") or "")

# 위 URL 이 **어느 이름에서 왔는지**를 기억한다 (2026-08-25, BUGS #205 후속 실측).
#
#   지금 이 저장소의 실제 상태가 그렇다:
#
#       .env        SUPABASE_URL              **비어 있다**
#       .env.local  NEXT_PUBLIC_SUPABASE_URL  SET      <- ES256 검증이 여기에 걸려 있다
#
#   즉 백엔드의 **현행 토큰 검증 경로(ES256/JWKS)가 프런트 전용 파일 이름에 의존한다.**
#   `.env` 와 `.env.local` 은 둘 다 gitignore 이므로 배포 대상에 따로 넣어야 하는데,
#   백엔드만 올리는 사람은 `.env` 만 챙기는 것이 자연스럽다. 그러면 URL 이 비고,
#   **로그인 사용자 전원이 401** 이 된다(BUGS #205 의 바로 그 시나리오다).
#
#   그 상황 자체는 `warn_if_auth_config_missing()` 이 부팅에서 잡는다. 여기서는 한 걸음
#   앞을 본다 - **아직 멀쩡하지만 폴백에 걸려 있는 상태**를 부팅 로그에 드러내,
#   장애가 났을 때 "어느 파일이 빠졌나"를 되짚을 수 있게 한다. 값은 남기지 않는다.
_SUPABASE_URL_SOURCE = ("SUPABASE_URL" if os.getenv("SUPABASE_URL")
                        else "NEXT_PUBLIC_SUPABASE_URL" if os.getenv("NEXT_PUBLIC_SUPABASE_URL")
                        else "")

bearer_scheme = HTTPBearer()

def warn_if_auth_config_missing() -> bool:
    """Supabase 인증 설정이 **하나라도** 없으면 부팅 시점에 경고한다. 남겼으면 True.

    ## 왜 필요한가 - 한쪽만 사라지면 로그인 사용자 전원이 401 이 된다

    `get_current_user()` 는 **둘 다** 없을 때만 500 "JWT 검증 설정 미비" 를 낸다.
    그 경우는 500 이라 즉시 드러난다. 문제는 **한쪽만** 사라진 경우다 - 실측하면
    이렇다(2026-08-25, 로컬 스텁 JWKS + 진짜 ES256 키로 재현. BUGS #205).

        둘 다 있음            ES256 200 / HS256 200      (정상)
        SUPABASE_URL 없음     ES256 **401** / HS256 200  <- 로그인 사용자 전원 401
        JWT_SECRET 없음       ES256 200 / HS256 **401**  <- 레거시 토큰 전원 401
        둘 다 없음            전부 500

    **ES256 이 현행 서명이다**(BUGS #27 에서 Supabase 가 비대칭으로 전환했다).
    그러니 `SUPABASE_URL` 하나가 비는 것만으로 로그인한 사람 전부가 막힌다.
    그런데 그때 남는 로그는 요청마다 나오는

        JWT 검증 실패: JWKS에서 해당 kid의 공개키를 찾지 못했습니다

    뿐이다 - **키 회전 중 사고처럼 읽힌다.** 설정이 빠졌다는 말은 어디에도 없다.
    401 은 "토큰이 틀렸다"와 구별되지 않는다. `_require_role()` 의 403 이 "권한
    부족"과 구별되지 않는 것과 같은 모양이고(BUGS #205), 같은 방식으로 고친다.

    이 파일 위쪽 주석이 기록하듯 **설정이 실제로 사라진 적이 있다**(cwd 가 저장소
    루트가 아니면 `.env` 를 못 읽어 둘 다 빈값이 됐다). 그때는 500 이라 드러났다.
    한쪽만 사라지는 날에는 드러나지 않는다.

    ## 값은 절대 남기지 않는다

    시크릿이 로그에 들어가면 로그 유출이 곧 인증 우회다. `_get_jwk()` 와
    `get_current_user()` 의 기존 규칙(토큰·키·비밀값을 로그에 넣지 않는다)을 그대로
    따라 **설정 여부만** 남긴다.
    """
    has_secret = bool(SUPABASE_JWT_SECRET)
    has_url = bool(SUPABASE_URL)
    if has_secret and has_url:
        # 멀쩡하지만 **폴백에 걸려 있는** 경우는 남겨 둔다 - 경고는 아니다(장애가 아니다).
        # 배포에서 `.env` 만 챙기면 이 폴백이 사라져 로그인 전원 401 이 되므로,
        # 사고가 났을 때 "어느 파일이 빠졌나"를 되짚을 단서를 부팅 로그에 남긴다.
        if _SUPABASE_URL_SOURCE == "NEXT_PUBLIC_SUPABASE_URL":
            logger.info(
                "JWKS 조회 URL 을 SUPABASE_URL 이 아니라 NEXT_PUBLIC_SUPABASE_URL 에서 "
                "가져왔다(.env 의 SUPABASE_URL 이 비어 있다). 백엔드만 배포하면서 그 "
                "파일을 빠뜨리면 ES256 검증이 끊긴다 - BUGS #205."
            )
        return False

    if not has_secret and not has_url:
        logger.warning(
            "SUPABASE_JWT_SECRET / SUPABASE_URL 이 모두 미설정이다 - "
            "인증이 필요한 모든 API 가 500(JWT 검증 설정 미비)으로 응답한다. "
            "cwd 가 저장소 루트인지, .env 가 읽히는지 확인하라."
        )
        return True

    if not has_url:
        logger.warning(
            "SUPABASE_URL 이 미설정이다(NEXT_PUBLIC_SUPABASE_URL 도 없다) - JWKS 를 "
            "받을 곳이 없어 ES256 토큰을 검증하지 못한다. ES256 이 현행 서명이므로 "
            "로그인 사용자 전원이 401 이 된다. 401 은 '토큰이 틀렸다'와 구별되지 "
            "않으니 설정 누락이 조용히 묻힌다. .env 설정을 확인하라."
        )
    else:
        logger.warning(
            "SUPABASE_JWT_SECRET 이 미설정이다 - HS256(레거시) 토큰을 검증하지 "
            "못해 그 토큰을 쓰는 요청이 전부 401 이 된다. ES256 경로는 살아 있어 "
            "증상이 일부에게만 나타난다. .env 설정을 확인하라."
        )
    return True

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
        # ★ 2026-08-25 (BUGS #191) — 예전에는 이 조건에 `or not _jwks_keys` 가 붙어
        #   있었다. 캐시가 비어 있는 동안 **하한이 통째로 무효**가 되어, JWKS 가
        #   응답하지 않는 상태에서는 들어오는 요청마다 5초짜리 바깥 호출이 하나씩
        #   나갔다. 게다가 그 호출이 `_jwks_lock` 을 **잡은 채** 일어나므로 요청들이
        #   직렬화된다 — 재현(스레드 8개, 응답 없는 JWKS): 바깥 호출 8회 / 마지막
        #   요청이 8×타임아웃을 대기. 실제 timeout=5 면 동시 8요청에 40초다.
        #   JWKS 한 곳이 느려지는 것이 **API 전체 정지**로 번진다.
        #
        #   `_JWKS_MIN_REFETCH_SECONDS` 의 원래 취지가 바로 그 폭주 방지였는데
        #   (위 상수 주석) 그 예외 조항이 정확히 캐시가 빈 순간 취지를 무효화했다.
        #   `_fetch_jwks_locked()` 가 **시도 전에** `_jwks_fetched_at` 을 갱신하므로
        #   시간 조건만으로 실패 후 재시도까지 올바르게 눌린다. 남는 것은
        #   "한 번도 시도한 적 없다"뿐이라 그것만 따로 본다 — 0.0 을 시간 비교로
        #   대신하면 부팅 직후(monotonic 이 작은 환경)에 첫 조회를 건너뛸 수 있다.
        #
        #   바뀌는 것: JWKS 장애 중 401 이 **빠르게** 난다(예전에는 5초씩 매달린 뒤
        #   같은 401). 결과는 같고 서버가 살아 있다. 캐시가 살아 있을 때의 동작은
        #   전혀 바뀌지 않는다(아래 `fresh` 분기가 그대로 먼저 걸린다).
        never_fetched = _jwks_fetched_at == 0.0
        if never_fetched or (now - _jwks_fetched_at) >= _JWKS_MIN_REFETCH_SECONDS:
            try:
                _fetch_jwks_locked()
            except Exception as exc:
                # 네트워크/파싱 실패는 인증 실패로만 이어지게 하고 서버를 죽이지 않는다.
                # 비밀값이 로그에 남지 않도록 예외 타입만 남긴다.
                logger.warning("JWKS 조회 실패(%s) ― 기존 캐시로 검증 시도", type(exc).__name__)
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
    except Exception as exc:
        # ★ 2026-08-17 Sprint 152: JOSE 계열**이 아닌** 예외도 새어 나왔다.
        #
        #   위 `except JOSEError`는 jose가 던지는 예외가 전부 JOSEError 자손이라는 전제인데,
        #   **키 파싱 단계는 그렇지 않다.** JWKS 캐시에 구조가 깨진 공개키가 들어 있으면
        #   `jwt.decode()`가 순수 `ValueError`를 던진다(실측: `invalid literal for int()
        #   with base 16: ''`). ValueError는 JOSEError가 아니라 그대로 통과해 버렸다.
        #
        #   그 결과가 이 함수의 docstring이 막겠다고 적어 둔 바로 그 실패다 — 실측:
        #
        #       GET /api/v1/search    (선택적 인증)  500   <- 비로그인으로 강등돼야 한다
        #       GET /api/v1/item/1    (선택적 인증)  500   <- 〃
        #       GET /api/v1/favorites (인증 필수)    500   <- 401이어야 한다
        #
        #   토큰의 `kid`는 **요청자가 고른다.** 따라서 실제 JWKS에 jose가 못 읽는 키가
        #   하나라도 섞이면(키 회전 중 미지원 kty 등) 그 kid를 지목하는 것만으로 인증 없이
        #   500을 만들 수 있다. Sprint 144에서 없앤 "인증 없이 만드는 500"과 같은 계열이다.
        #
        #   그래서 "검증 실패는 종류를 불문하고 JWTError 하나로 정규화한다"는 이 함수의
        #   계약을 **예외 계층에 기대지 않고** 지킨다. 같은 함수 안 헤더 파싱(위 101행)이
        #   이미 `except Exception`으로 같은 일을 하고 있어 방식도 일관된다.
        #
        #   삼키기만 하면 진짜 버그가 조용한 인증 실패로 묻히므로 **타입만** 남긴다
        #   (토큰·키·비밀값은 로그에 넣지 않는다 — `_get_jwk`의 기존 규칙과 동일).
        logger.warning("토큰 검증 중 JOSE 계열 밖 예외(%s) ― 인증 실패로 처리", type(exc).__name__)
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
