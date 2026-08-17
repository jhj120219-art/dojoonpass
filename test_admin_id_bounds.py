"""Admin 경로의 id 범위 경계 — 2026-08-17 Sprint 153 신설.

## 왜 이 파일이 생겼나

전 라우트를 적대적 입력으로 훑다가 `api/v1/admin.py` 에서 500 이 나왔다.

```
GET /api/v1/admin/payments/9223372036854775808/logs
   -> OverflowError: Python int too large to convert to SQLite INTEGER
   -> 500 Internal Server Error          (정상 범위 id 는 404 를 준다)
```

파이썬 int 는 임의 정밀도라 `2**63` 이 그대로 쿼리까지 내려가고 sqlite3 이 터진다.
Sprint 144 가 `/api/v1/search`·`item`·`documents`·`images` 에서 없앤 것과 **같은 계열**인데,
`admin.py` 만 그 정리에서 빠져 있었다.

    실측: api/v1/admin.py 의 is_sqlite_int 사용 0건
          api/v1/{item,documents,images,search}.py 는 전부 사용 중

## 6개 핸들러 전부에서 재현됐다 (수정 전)

| 핸들러 | 필요 등급 | 2^63 | 정상 id |
|---|---|---|---|
| `GET /admin/payments/{id}/logs` | ADMIN | **500** | 404 |
| `GET /admin/payments/webhooks/{id}` | ADMIN | **500** | 404 |
| `POST /admin/payments/webhooks/{id}/reprocess` | SUPER_ADMIN | **500** | 404 |
| `POST /admin/payments/{id}/refund` | SUPER_ADMIN | **500** | 404 |
| `PATCH /admin/subscriptions/{id}` | SUPER_ADMIN | **500** | 404 |
| `PATCH /admin/registry-requests/{id}` | ADMIN | **500** | 404 |

앞의 둘만 ADMIN 등급에서 바로 드러났고, 나머지 넷은 **SUPER_ADMIN 권한 검사에 가려
있었다** — 권한이 있는 운영자에게는 그대로 500 이다. 그래서 등급을 올려 가며 확인했다.
마지막 하나는 status 검증에 가려 있어 `status=FAILED` 로 통과시킨 뒤에야 드러났다.

## 심각도 — 인증이 필요하므로 무인증 공격은 아니다

전부 Admin 키가 있어야 도달한다. 다만 운영자가 잘못된 id 로 조회했을 때
**"찾을 수 없다"가 아니라 원인 없는 500** 을 받는다는 것이 문제다. 이 저장소가
반복해 지켜 온 "실패했으면 왜인지 남긴다" 원칙에 어긋나고, 운영 도구에서
500 은 장애로 오인된다.

## 왜 404 인가

범위 밖 정수는 **어떤 행도 될 수 없으므로** "찾을 수 없다"가 정확한 답이다.
400("잘못된 형식")이 아니다 — 형식은 올바른 정수다. `api/v1/item.py` 등이 이미
같은 판단을 하고 있어 응답 규약도 일치한다.

## 실제 credential 을 쓰지 않는다

`ADMIN_API_KEY`/`SUPER_ADMIN_API_KEY` 에 **합성 값**을 넣는다(프로세스 안에서만).
운영 키를 읽지도 출력하지도 않는다. 존재하지 않는 id 만 다루므로 운영 DB 에
쓰기가 일어나지 않는다(전부 조회 단계에서 404 로 끝난다).

    python test_admin_id_bounds.py
"""
import contextlib
import io
import os
import re
import secrets
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 합성 키. 실제 운영 키는 읽지 않는다.
_KEY = "qa-admin-bounds-" + secrets.token_hex(16)
os.environ["ADMIN_API_KEY"] = _KEY
os.environ["SUPER_ADMIN_API_KEY"] = _KEY
if not os.getenv("SUPABASE_JWT_SECRET"):
    os.environ["SUPABASE_JWT_SECRET"] = "qa-bounds-" + secrets.token_hex(16)

HEADERS = {"X-Admin-Key": _KEY}

# SQLite INTEGER 경계 밖. 파이썬 int 는 임의 정밀도라 여기까지 그대로 내려간다.
OUT_OF_RANGE = [
    ("2^63 (최대+1)", str(2 ** 63)),
    ("-2^63-1 (최소-1)", str(-2 ** 63 - 1)),
    ("2^200", str(2 ** 200)),
]
# 범위 **안**이지만 존재하지 않는 id — 가드가 의미를 바꾸지 않았음을 보이는 대조군.
IN_RANGE_MISSING = "999999999"

# (메서드, 경로 템플릿, 본문, 기대 detail)
HANDLERS = [
    ("GET", "/api/v1/admin/payments/{}/logs", None, "결제 내역을 찾을 수 없습니다"),
    ("GET", "/api/v1/admin/payments/webhooks/{}", None, "Webhook 수신 기록을 찾을 수 없습니다"),
    ("POST", "/api/v1/admin/payments/webhooks/{}/reprocess", {}, "Webhook 수신 기록을 찾을 수 없습니다"),
    ("POST", "/api/v1/admin/payments/{}/refund", {"reason": "qa"}, "결제 내역을 찾을 수 없습니다"),
    ("PATCH", "/api/v1/admin/subscriptions/{}", {"status": "CANCELLED"}, "구독을 찾을 수 없습니다"),
    ("PATCH", "/api/v1/admin/registry-requests/{}", {"status": "FAILED", "reason": "qa"},
     "신청을 찾을 수 없습니다"),
]

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


def _client():
    import api_server
    from fastapi.testclient import TestClient
    with contextlib.redirect_stderr(io.StringIO()):
        return TestClient(api_server.app, raise_server_exceptions=False)


def _call(client, meth, url, body):
    with contextlib.redirect_stderr(io.StringIO()):
        if body is None:
            return client.get(url, headers=HEADERS)
        return client.request(meth, url, headers=HEADERS, json=body)


# ---------------------------------------------------------------------------
# 1. ★★ 범위 밖 id 는 500이 아니라 404
# ---------------------------------------------------------------------------
def test_out_of_range_is_404_not_500():
    print("\n--- 1. 범위 밖 id -> 404 (500 아님) ---")
    client = _client()
    for meth, tmpl, body, detail in HANDLERS:
        for label, value in OUT_OF_RANGE:
            r = _call(client, meth, tmpl.format(value), body)
            name = "★ %s %s [%s]" % (meth, tmpl.format("{id}").replace("/api/v1/admin", ""), label)
            check(name, r.status_code, 404)
            if r.status_code == 404:
                check_true(name + " 메시지", r.json().get("detail") == detail, r.json())


# ---------------------------------------------------------------------------
# 2. 대조군 — 범위 안이면 동작이 그대로다 (가드가 의미를 바꾸지 않았다)
# ---------------------------------------------------------------------------
def test_in_range_behaviour_unchanged():
    print("\n--- 2. 범위 안 미존재 id 는 원래대로 404 ---")
    client = _client()
    for meth, tmpl, body, detail in HANDLERS:
        r = _call(client, meth, tmpl.format(IN_RANGE_MISSING), body)
        label = "%s %s" % (meth, tmpl.format("{id}").replace("/api/v1/admin", ""))
        check(label, r.status_code, 404)
        if r.status_code == 404:
            check_true(label + " 메시지 동일", r.json().get("detail") == detail, r.json())

    # 경계값 자체(2^63-1)는 **범위 안**이므로 가드에 걸리면 안 된다 — off-by-one 방지.
    boundary = str(2 ** 63 - 1)
    r = _call(client, "GET", "/api/v1/admin/payments/%s/logs" % boundary, None)
    check("★ 경계값 2^63-1 은 통과해 조회까지 간다", r.status_code, 404)


# ---------------------------------------------------------------------------
# 3. 응답에 내부 정보가 새지 않는다
# ---------------------------------------------------------------------------
def test_no_internal_leak():
    print("\n--- 3. 500 대신 오는 404 에 내부 정보가 없다 ---")
    client = _client()
    r = _call(client, "GET", "/api/v1/admin/payments/%d/logs" % (2 ** 63), None)
    body = r.text
    for bad in ("OverflowError", "Traceback", "sqlite3", "site-packages", "admin.py"):
        check_true("응답에 %r 이 없다" % bad, bad not in body, body[:150])
    check_true("응답에 Admin 키가 없다", _KEY not in body)


# ---------------------------------------------------------------------------
# 4. ★ 전수 스캔 — int 경로변수를 받는 **모든** 핸들러가 가드를 부른다
#
# 목록으로 대상을 지정하는 검사는 목록에서 빠진 새 핸들러를 영원히 못 본다.
# `docs/BUGS.md` 가 같은 교훈을 적어 두었다("목록이 아니라 전수 스캔으로 짜야 한다").
# 그래서 소스를 훑어 int 경로변수를 받는 핸들러를 **직접 찾아내고**, 그 각각이
# `_require_sqlite_id` 를 부르는지 확인한다.
# ---------------------------------------------------------------------------
def test_every_int_path_handler_is_guarded():
    print("\n--- 4. int 경로변수 핸들러 전수 검사 ---")
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "api", "v1", "admin.py")
    src = open(path, encoding="utf-8-sig").read()
    lines = src.splitlines()

    check_true("is_sqlite_int 를 import 한다", "is_sqlite_int" in src)
    check_true("_require_sqlite_id 헬퍼가 있다", "def _require_sqlite_id(" in src)

    found = []
    for i, line in enumerate(lines):
        m = re.match(r'\s*@router\.(get|post|patch|delete|put)\("([^"]+)"', line)
        if not m or "{" not in m.group(2):
            continue
        # 이 데코레이터부터 다음 데코레이터(또는 파일 끝)까지가 핸들러 본문이다.
        end = len(lines)
        for j in range(i + 1, len(lines)):
            if re.match(r'\s*@router\.', lines[j]):
                end = j
                break
        block = "\n".join(lines[i:end])
        # 시그니처에서 int 경로변수를 찾는다.
        sig = block[:block.index("):") + 2] if "):" in block else block
        if not re.search(r'\w+\s*:\s*int\b', sig):
            continue
        found.append((m.group(2), "_require_sqlite_id" in block))

    check_true("int 경로변수 핸들러를 찾았다", len(found) > 0, found)
    print("      발견한 핸들러 %d개:" % len(found))
    for p, guarded in found:
        print("        %-46s 가드=%s" % (p[:46], "있음" if guarded else "★없음"))
    unguarded = [p for p, g in found if not g]
    check("★ 가드 없는 핸들러", unguarded, [])


if __name__ == "__main__":
    test_out_of_range_is_404_not_500()
    test_in_range_behaviour_unchanged()
    test_no_internal_leak()
    test_every_int_path_handler_is_guarded()

    print("\n" + "=" * 60)
    if failures:
        print("FAILED (%d): %s" % (len(failures), ", ".join(failures)))
        sys.exit(1)
    print("ALL ADMIN ID BOUNDS TESTS PASSED")
