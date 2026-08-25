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


# ---------------------------------------------------------------------------
# JWKS 조회는 **세 갈래**로 판정한다 (2026-08-25 정정, BUGS #188)
#
# 예전에는 두 갈래였다 — `status == 200` 이면 정상, 아니면 실패. 그래서 한 번의
# 네트워크 타임아웃이 곧바로 "★ ES256(주 경로) 실패 - 로그인 사용자 인증이 사실상
# 막혀 있다"로 찍혔다. 2026-08-25 에 실제로 그렇게 나왔고, **몇 초 뒤 같은 주소로
# 다시 보내니 0.17초 만에 HTTP 200 + ES256 공개키 1개**가 왔다. 설정은 멀쩡했다.
#
# 이 감사기의 docstring 은 "추측하지 않는다"고 적어 두었는데, 정작 판정에서
# **"모른다"를 "고장났다"로 읽고 있었다.** 두 상태는 조치가 정반대다:
#
#     주소가 틀렸다  -> .env 를 고쳐야 한다 (사람이 개입할 일)
#     이번에 못 닿았다 -> 아무것도 고칠 것이 없다 (다시 재면 된다)
#
# 그래서 네트워크 계열 실패는 재시도하고, 끝내 못 닿으면 **실패가 아니라 "확인 불가"**
# 로 남긴다. 반대로 HTTP 오류/JWKS 아님은 재시도하지 않는다 - 그것은 이번 문제가
# 아니라 주소 문제라 몇 번을 보내도 같다.
# ---------------------------------------------------------------------------
JWKS_ATTEMPT_TIMEOUTS = (5, 8, 12)


def _classify_jwks_exception(exc):
    """예외 하나를 'FAILED'(주소가 틀렸다는 확정 증거) / 'UNKNOWN'(이번에 못 닿았다)
    로 나눈다. 네트워크 없이 검증할 수 있도록 따로 뺐다."""
    if isinstance(exc, urllib.error.HTTPError):
        return "FAILED"
    # URLError / timeout / DNS / TLS / 연결거부 - 전부 "이번에 못 닿았다"이지
    # "설정이 틀렸다"가 아니다. OSError 가 이들 대부분의 상위 타입이다.
    if isinstance(exc, (urllib.error.URLError, TimeoutError, OSError)):
        return "UNKNOWN"
    return "UNKNOWN"


def _default_jwks_fetch(url, timeout):
    """(status, parsed_json) 을 돌려준다. 실패는 예외로 올린다."""
    import json
    with urllib.request.urlopen(url, timeout=timeout) as res:
        return res.status, json.load(res)


def _check_jwks_reachable(supabase_url, fetch=None, timeouts=None):
    """JWKS 엔드포인트를 실제로 재고 (verdict, status, detail) 을 돌려준다.

    verdict 는 'OK' / 'FAILED' / 'UNKNOWN' 셋 중 하나다.
    `fetch`/`timeouts` 는 selftest 가 네트워크 없이 이 판정을 검증하려고 둔 자리다.
    """
    if not supabase_url:
        # 이건 네트워크 문제가 아니라 설정 문제다 - 확정 실패가 맞다.
        return "FAILED", None, "SUPABASE_URL 이 비어 있어 JWKS 주소를 만들 수 없다"

    url = supabase_url + "/auth/v1/.well-known/jwks.json"
    fetch = fetch or _default_jwks_fetch
    timeouts = timeouts or JWKS_ATTEMPT_TIMEOUTS

    tries = []
    for i, timeout in enumerate(timeouts, 1):
        try:
            status, data = fetch(url, timeout)
        except Exception as exc:                      # noqa: BLE001 - 분류해서 다시 쓴다
            tries.append("%d회차(%ds) %s: %s" % (i, timeout, type(exc).__name__, exc))
            if _classify_jwks_exception(exc) == "FAILED":
                code = getattr(exc, "code", None)
                return "FAILED", code, "HTTP %s - 이 주소는 JWKS 를 주지 않는다" % code
            continue

        keys = (data or {}).get("keys") or []
        if status == 200 and keys:
            return "OK", status, "%d개 공개키 (%d회차에 성공)" % (len(keys), i)
        # 200 인데 키가 없으면 주소가 JWKS 가 아니다 - 재시도해도 같다.
        return "FAILED", status, "HTTP %s 인데 공개키가 0개다 - JWKS 응답이 아니다" % status

    return "UNKNOWN", None, ("%d번 시도했지만 응답을 받지 못했다. 네트워크가 이번에 안 된 것이지 "
                             "설정이 틀렸다는 증거가 아니다 | %s" % (len(timeouts), " / ".join(tries)))

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
    print("    실제 GET %s/auth/v1/.well-known/jwks.json" % auth_mod.SUPABASE_URL)
    verdict, status, detail = _check_jwks_reachable(auth_mod.SUPABASE_URL)
    print("    -> [%s] %s (%s)" % (verdict, status, detail))

    print()
    print("=" * 70)
    if verdict == "OK" and secret_len:
        print(" 종합: HS256 / ES256 둘 다 정상 - 로그인 사용자 인증이 실제로 동작한다")
    elif verdict == "OK":
        print(" 종합: ES256(주 경로)만 정상 - HS256 레거시 토큰만 거부된다(대개 무해함)")
    elif verdict == "UNKNOWN":
        # ★ 여기서 "실패"라고 적지 않는다 - 그것이 이 도구가 저지른 오판이었다.
        print(" 종합: ES256 주 경로를 **확인하지 못했다** (네트워크가 이번에 안 됐다)")
        print("       설정이 틀렸다는 뜻이 아니다. 고칠 것이 있는지 알려면 다시 재라:")
        print("           python audit_auth_health.py")
        if not secret_len:
            print("       (다만 SUPABASE_JWT_SECRET 이 없는 것은 네트워크와 무관한 확정 문제다)")
    elif secret_len:
        print(" 종합: ★ ES256(주 경로) 실패 - 로그인 사용자 인증이 사실상 막혀 있다")
    else:
        print(" 종합: ★★ HS256/ES256 둘 다 실패 - 로그인 사용자 인증이 전부 막혀 있다")
    print("=" * 70)

    # 종료코드 계약: 0 = 정상 / 1 = 확정 실패(주소가 틀렸다) / 2 = 확인 불가.
    # 2 를 따로 두는 이유는 1 과 조치가 정반대이기 때문이다 - 1 은 사람이 .env 를
    # 고쳐야 하고, 2 는 고칠 것이 없다. 같은 코드로 묶으면 이 도구를 자동화에
    # 물렸을 때 네트워크 딸꾹질마다 "인증 장애" 알림이 간다.
    return {"OK": 0, "FAILED": 1, "UNKNOWN": 2}[verdict]


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

    def check(name, actual, expected):
        ok = actual == expected
        print("  [%s] %s: %r (기대 %r)" % ("PASS" if ok else "FAIL", name, actual, expected))
        if not ok:
            fails.append(name)

    # -----------------------------------------------------------------------
    # JWKS 세 갈래 판정 (2026-08-25 신설, BUGS #188)
    #
    # 왜 여기서 검증하나 — 이 판정이 틀렸을 때 나오는 것은 "조용한 오작동"이 아니라
    # **틀린 P0 경보**다("로그인 인증이 사실상 막혀 있다"). 실제로 한 번 그렇게 나왔고
    # 몇 초 뒤 같은 주소가 200 을 돌려줬다. 네트워크 없이 재현할 수 있도록 `fetch` 를
    # 주입해서 검사한다 — 회귀 스위트가 외부 서비스를 두드리면 안 되기 때문이다.
    # -----------------------------------------------------------------------
    print("--- selftest: JWKS 세 갈래 판정 ---")

    URL = "https://x.supabase.co"
    T = (1, 1, 1)          # selftest 는 실제로 자지 않는다(가짜 fetch 라 즉시 돌아온다)

    def ok_fetch(url, timeout):
        return 200, {"keys": [{"kid": "k1", "alg": "ES256"}]}

    def http404(url, timeout):
        raise urllib.error.HTTPError(url, 404, "Not Found", None, None)

    def always_timeout(url, timeout):
        raise TimeoutError("The read operation timed out")

    calls = {"n": 0}

    def flaky(url, timeout):
        """앞의 두 번은 타임아웃, 세 번째에 성공 — 실제로 겪은 모양 그대로."""
        calls["n"] += 1
        if calls["n"] < 3:
            raise TimeoutError("The read operation timed out")
        return 200, {"keys": [{"kid": "k1"}]}

    def empty_keys(url, timeout):
        return 200, {"keys": []}

    def _v(fetch):
        return _check_jwks_reachable(URL, fetch=fetch, timeouts=T)[0]

    check("정상 응답은 OK", _v(ok_fetch), "OK")
    check("HTTP 404 는 확정 실패(주소가 틀렸다)", _v(http404), "FAILED")
    check("200 인데 공개키 0개도 확정 실패", _v(empty_keys), "FAILED")
    check("★ 계속 타임아웃이면 FAILED 가 아니라 UNKNOWN", _v(always_timeout), "UNKNOWN")
    check("★ 앞 두 번 타임아웃 뒤 성공하면 OK (재시도가 실제로 있다)", _v(flaky), "OK")
    check("   그때 정말 3번 불렀다", calls["n"], 3)
    check("SUPABASE_URL 이 비면 확정 실패(네트워크 문제가 아니다)",
          _check_jwks_reachable("", fetch=ok_fetch, timeouts=T)[0], "FAILED")

    # HTTP 오류는 재시도하지 않는다 — 몇 번을 보내도 주소는 그대로다.
    http_calls = {"n": 0}

    def counting_404(url, timeout):
        http_calls["n"] += 1
        raise urllib.error.HTTPError(url, 404, "Not Found", None, None)

    _check_jwks_reachable(URL, fetch=counting_404, timeouts=T)
    check("★ HTTP 오류는 재시도하지 않는다(1번만 부른다)", http_calls["n"], 1)

    check("타임아웃 예외 분류", _classify_jwks_exception(TimeoutError()), "UNKNOWN")
    check("연결 거부 분류", _classify_jwks_exception(ConnectionRefusedError()), "UNKNOWN")
    check("URLError 분류", _classify_jwks_exception(urllib.error.URLError("dns")), "UNKNOWN")
    check("HTTPError 분류",
          _classify_jwks_exception(urllib.error.HTTPError(URL, 500, "x", None, None)), "FAILED")

    # 기본값 자체도 검사한다 - 위 검사들은 timeouts 를 직접 주입하므로
    # 상수를 1회로 줄여도 전부 통과해 버린다(2026-08-25 mutation 으로 확인한 구멍).
    check("★ 기본 재시도 횟수가 2 이상이다", len(JWKS_ATTEMPT_TIMEOUTS) >= 2, True)
    check("   재시도마다 타임아웃을 늘린다",
          list(JWKS_ATTEMPT_TIMEOUTS) == sorted(set(JWKS_ATTEMPT_TIMEOUTS)), True)

    if fails:
        print("selftest 실패 %d건: %s" % (len(fails), fails))
        return 1
    print("selftest 전체 통과")
    return 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    sys.exit(main())
