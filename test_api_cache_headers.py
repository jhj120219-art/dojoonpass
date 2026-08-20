# -*- coding: utf-8 -*-
"""응답 캐시 헤더 계약 (2026-08-20 Sprint 237 신설).

## 무엇을 잠그나

    사용자별 JSON   `Cache-Control: no-store`   공용 PC 에 남지 않는다
    공개 JSON       그대로 (정책 없음)           신선도 계약을 바꾸지 않는다
    파일(문서/사진)  ETag/Last-Modified 유지      조건부 요청 304 절약이 살아 있다

## 왜

Sprint 237 실측: JSON 응답 9종 전부 `Cache-Control` 이 **없었다.** 헤더가 없으면
브라우저는 휴리스틱 캐싱에 맡겨진다 - 공용 PC 에서 앞사람의 관심물건 응답이
디스크에 남을 수 있다.

★ 그렇다고 전부 `no-store` 로 덮으면 **문서/사진의 304 절약(실측 395KB/235KB)이
  사라진다.** 그래서 "검증자(ETag/Last-Modified)가 붙은 응답은 건드리지 않는다"는
  조건이 핵심이고, 이 파일이 지키는 것도 바로 그 경계다.

    python test_api_cache_headers.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

failures = []
CHECKS = [0]


def check(name, actual, expected):
    CHECKS[0] += 1
    ok = actual == expected
    print("[%s] %s: %r (expected %r)" % ("PASS" if ok else "FAIL", name, actual, expected))
    if not ok:
        failures.append(name)


def check_true(name, cond, detail=""):
    CHECKS[0] += 1
    print("[%s] %s%s" % ("PASS" if cond else "FAIL", name, "" if cond else " -- " + str(detail)))
    if not cond:
        failures.append(name)


def run():
    print("=" * 64)
    print(" 응답 캐시 헤더 계약 (Sprint 237)")
    print("=" * 64)

    from fastapi.testclient import TestClient
    import api_server

    client = TestClient(api_server.app)

    # 인증이 필요한 라우트를 OpenAPI 에서 찾는다(하드코딩하지 않는다)
    spec = client.get("/openapi.json").json()
    authed = []
    for path, ops in spec.get("paths", {}).items():
        for method, op in ops.items():
            if method != "get":
                continue
            if op.get("security") and "{" not in path:
                authed.append(path)
    print("    인증이 걸린 GET 라우트 %d개" % len(authed))
    check_true("검사가 공허하지 않다(인증 라우트를 찾았다)", len(authed) >= 2, authed)

    # --- 1. 사용자별 JSON 은 no-store ---------------------------------------
    print("\n--- 1. 사용자별 JSON 은 캐시되지 않는다 ---")
    HDR = {"Authorization": "Bearer qa-not-a-real-token"}
    checked = 0
    for path in authed:
        r = client.get(path, headers=HDR)
        cc = r.headers.get("cache-control")
        has_validator = "etag" in r.headers or "last-modified" in r.headers
        if has_validator:
            continue
        checked += 1
        if cc != "no-store":
            check("★ %s 가 no-store 다" % path, cc, "no-store")
    if checked and not [f for f in failures if "no-store" in f]:
        print("[PASS] ★ 검증자 없는 인증 응답 %d개 전부 no-store" % checked)
        CHECKS[0] += 1
    check_true("검사가 공허하지 않다(실제로 확인한 응답이 있다)", checked >= 2, checked)

    # --- 2. 공개 JSON 은 건드리지 않는다 -------------------------------------
    print("\n--- 2. 공개 JSON 의 신선도 계약은 그대로 ---")
    r = client.get("/api/v1/search?size=5&include_closed=true")
    check("공개 검색은 200", r.status_code, 200)
    check("★ 공개 JSON 에 no-store 를 씌우지 않는다",
          r.headers.get("cache-control"), None)

    # --- 3. 인증 헤더가 없으면 아무것도 바뀌지 않는다 --------------------------
    print("\n--- 3. 인증 헤더가 없으면 규칙이 적용되지 않는다 ---")
    r2 = client.get("/api/v1/stats")
    check("통계는 200", r2.status_code, 200)
    check("인증 없는 응답에는 no-store 가 없다",
          r2.headers.get("cache-control"), None)

    # --- 4. ★ 파일 응답의 검증자와 304 를 죽이지 않았는가 ---------------------
    print("\n--- 4. 파일 응답의 304 절약이 살아 있다 ---")
    import sqlite3
    db = os.path.join(os.getcwd(), "auction.db")
    target = None
    if os.path.exists(db):
        conn = sqlite3.connect("file:%s?mode=ro" % db.replace("\\", "/"), uri=True)
        try:
            row = conn.execute(
                "SELECT item_id, seq FROM auction_image ORDER BY item_id LIMIT 1").fetchone()
            if row:
                target = "/api/v1/item/%d/images/%s" % (row[0], row[1])
        finally:
            conn.close()
    if not target:
        print("[SKIP] auction_image 가 비어 있다 - 파일 경로를 확인할 수 없다")
    else:
        r3 = client.get(target, headers=HDR)
        etag = r3.headers.get("etag")
        check("사진 응답 200", r3.status_code, 200)
        check_true("★ 인증 요청에도 ETag 가 남아 있다", bool(etag), r3.headers.get("etag"))
        check("★ 파일 응답에는 no-store 를 씌우지 않는다",
              r3.headers.get("cache-control"), None)
        if etag:
            r4 = client.get(target, headers=dict(HDR, **{"If-None-Match": etag}))
            check("★ 조건부 요청이 여전히 304 를 돌려준다", r4.status_code, 304)
            check_true("304 는 본문이 없다(절약이 실제로 일어난다)",
                       len(r4.content) == 0, len(r4.content))

    print("\n" + "=" * 64)
    if failures:
        print("FAILED (%d/%d): %s" % (len(failures), CHECKS[0], ", ".join(failures)))
        return 1
    print("ALL CACHE HEADER TESTS PASSED (%d checks)" % CHECKS[0])
    return 0


if __name__ == "__main__":
    sys.exit(run())
