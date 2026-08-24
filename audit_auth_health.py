# -*- coding: utf-8 -*-
"""
인증 설정이 **실제로 동작하는지** 재는 읽기 전용 감사기 (2026-08-23 Sprint 267).

왜 만들었나
---------------------------------------------------------------------------
막으려는 함정: `NEXT_PUBLIC_SUPABASE_URL`에 REST API 베이스 URL(".../rest/v1/")이
프로젝트 URL 자리에 들어가는 경우다. 코드(`api/auth.py`)는
`SUPABASE_URL`이 "있기는 하니" 조용히 그 값으로 JWKS 주소를 만들고, 그 주소로는 키가
오지 않는다 - `_get_jwk()`가 그 실패를 `except Exception`으로 삼키고 경고 로그만 남기므로
서버는 죽지 않는다. 겉보기엔 "정상 기동"이지만 **로그인 사용자 인증(ES256)이 전부
거부되는 상태**였다. `.env`는 gitignore 대상이라 세션/컴퓨터마다 값이 다르고, 이런
조용한 실패는 실제로 로그인 API를 두드려 보지 않으면 드러나지 않는다.

이 감사기는 세 가지를 실제로 실행해서 잰다(추측하지 않는다).

    [1] SUPABASE_JWT_SECRET 이 실제로 있는가 (HS256 레거시 경로)
    [2] SUPABASE_URL 이 실제로 유효한 JWKS 주소를 만드는가 (ES256 주 경로)
    [3] 그 주소로 실제 네트워크 요청을 보내면 진짜 공개키가 오는가

무엇을 하지 않는가
---------------------------------------------------------------------------
아무것도 바꾸지 않는다. `.env`를 쓰지 않고, 토큰을 발급하지도 않는다. JWKS 엔드포인트에
대한 읽기 전용 GET 요청 하나만 실제로 보낸다(공개 엔드포인트 - 인증 불필요, 값 변경 없음).

    python audit_auth_health.py
    python audit_auth_health.py --selftest   # _project_origin() 정규화 로직 자체를 검증

★ 2026-08-24 정정 — 위 "왜 만들었나"는 원래 "이 세션에서 실제로 밟은 함정: `.env`의
  NEXT_PUBLIC_SUPABASE_URL 에 .../rest/v1/ 이 들어 있었다"라고 단정했다.
  **이 저장소의 현재 상태에서는 재현되지 않는다** — 2026-08-24 실측:

      .env         키 3개, 전부 NEXT_PUBLIC_* 아님 (SUPABASE_URL/ANON_KEY 는 빈 값,
                   SUPABASE_JWT_SECRET 88자)
      .env.local   NEXT_PUBLIC_SUPABASE_URL 40자, urlsplit().path == ''  (경로 없음)
      해석 결과    api.auth.SUPABASE_URL 의 path '' -> JWKS 경로가 정상으로 만들어진다

  그래도 이 감사기는 그대로 가치가 있다 — `.env` 는 gitignore 대상이라 컴퓨터마다
  값이 다르고, 이런 조용한 실패는 실제로 재 보지 않으면 드러나지 않는다.
  (값은 길이/경로 유무만 확인했고 어디에도 출력하지 않았다. [3]번 검사는 외부 서비스로
   실제 네트워크 요청을 보내므로, 승인 없이 도는 자동 검증에서는 실행하지 않는다.)
"""
import os
import sys
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def _check_jwks_reachable(supabase_url: str):
    """실제로 JWKS 엔드포인트에 GET 을 보낸다. (status, kid_count 또는 오류) 를 돌려준다."""
    if not supabase_url:
        return None, "SUPABASE_URL 이 비어 있어 JWKS 주소를 만들 수 없다"
    url = supabase_url + "/auth/v1/.well-known/jwks.json"
    try:
        with urllib.request.urlopen(url, timeout=5) as res:
            import json
            data = json.load(res)
        keys = data.get("keys", [])
        return res.status, "%d개 공개키" % len(keys)
    except urllib.error.HTTPError as exc:
        return exc.code, "HTTP %d - 이 주소는 JWKS 를 주지 않는다" % exc.code
    except Exception as exc:
        return None, "%s: %s" % (type(exc).__name__, exc)


def main():
    import api.auth as auth_mod

    print("=" * 70)
    print(" 인증 설정 상태 (읽기 전용)")
    print("=" * 70)

    secret_len = len(auth_mod.SUPABASE_JWT_SECRET or "")
    print("[1] HS256 레거시 경로")
    print("    SUPABASE_JWT_SECRET 길이: %d" % secret_len)
    if secret_len:
        print("    -> HS256 토큰 검증 가능")
    else:
        print("    -> ★ 없음. HS256(레거시) 토큰은 전부 거부된다")
        print("       (.env 에 SUPABASE_JWT_SECRET=<값> 필요 - 승인 영역이라 이 도구는 고치지 않는다)")

    print()
    print("[2] ES256 주 경로 (JWKS)")
    print("    SUPABASE_URL 해석값: %r" % auth_mod.SUPABASE_URL)
    status, detail = _check_jwks_reachable(auth_mod.SUPABASE_URL)
    print("    실제 GET %s/auth/v1/.well-known/jwks.json" % auth_mod.SUPABASE_URL)
    print("    -> %s (%s)" % (status, detail))

    ok = status == 200
    print()
    print("=" * 70)
    if secret_len and ok:
        print(" 종합: HS256 / ES256 둘 다 정상 - 로그인 사용자 인증이 실제로 동작한다")
    elif ok:
        print(" 종합: ES256(주 경로)만 정상 - HS256 레거시 토큰만 거부된다(대개 무해함)")
    elif secret_len:
        print(" 종합: ★ ES256(주 경로) 실패 - 로그인 사용자 인증이 사실상 막혀 있다")
    else:
        print(" 종합: ★★ HS256/ES256 둘 다 실패 - 로그인 사용자 인증이 전부 막혀 있다")
    print("=" * 70)
    return 0 if ok else 1


# ---------------------------------------------------------------------------
# selftest - _project_origin() 정규화 로직 자체가 실제로 우는지 확인한다.
# 실제 .env/네트워크에 의존하지 않는다.
# ---------------------------------------------------------------------------
def selftest():
    import api.auth as auth_mod

    print("--- selftest: _project_origin() 정규화 ---")
    cases = [
        ("https://abcxyz.supabase.co/rest/v1/", "https://abcxyz.supabase.co"),
        ("https://abcxyz.supabase.co", "https://abcxyz.supabase.co"),
        ("https://abcxyz.supabase.co/", "https://abcxyz.supabase.co"),
        ("", ""),
    ]
    fails = []
    for raw, expected in cases:
        got = auth_mod._project_origin(raw)
        ok = got == expected
        print("  [%s] %r -> %r (기대 %r)" % ("PASS" if ok else "FAIL", raw, got, expected))
        if not ok:
            fails.append(raw)
    if fails:
        print("selftest 실패 %d건: %s" % (len(fails), fails))
        return 1
    print("selftest 전체 통과")
    return 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    sys.exit(main())
