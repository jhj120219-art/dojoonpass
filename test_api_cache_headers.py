# -*- coding: utf-8 -*-
"""응답 캐시 헤더 계약 (2026-08-20 Sprint 237 신설 / 2026-08-24 Sprint 254 확장).

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
        except sqlite3.OperationalError as e:
            if "no such table: auction_image" not in str(e):
                raise
            print("[SKIP] auction_image 테이블이 없다(migration 020 미적용) - 사진 304 검사를 건너뛴다:", e)
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

        # --- 5. 조건부 요청의 **나머지 절반** (2026-08-24 Sprint 254 신설) -------
        #
        # 위 4번은 강한 `If-None-Match` 하나만 본다. 합산 커버리지로 재보니
        # `api/http_cache.py` 의 12줄이 **어떤 테스트도 실행하지 않는 상태**였다:
        #
        #     65      약한 ETag(`W/`) 접두사 벗기기
        #     73-79   `_http_date_to_timestamp()` 전체
        #     121-125 `If-Modified-Since` 분기 전체
        #
        # 실제로 두드려 보니 13가지 경우가 전부 RFC 9110 대로 동작했다 — 즉 지금은
        # **결함이 아니라 미검증**이다. 그래서 고칠 것은 없고 잠글 것만 있다.
        # 잠그지 않으면 다음 리팩터링이 조용히 깨뜨린다. 그리고 이 경로가 깨지는
        # 방향은 두 가지인데 **둘 다 사용자에게 보인다**:
        #
        #     304 를 못 주면   문서/사진을 매번 다시 받는다(실측 395KB/235KB 낭비)
        #     304 를 잘못 주면 바뀐 문서를 **옛것으로 보여준다** — 이쪽이 더 나쁘다
        #
        # 브라우저는 압축/프록시를 거치면 `W/` 를 붙여 보내고, ETag 가 없는 캐시는
        # `If-Modified-Since` 만 보낸다. 둘 다 실제로 오는 요청이다.
        print("\n--- 5. 조건부 요청: 약한 ETag / If-Modified-Since (Sprint 254) ---")
        import email.utils

        last_modified = r3.headers.get("last-modified")
        check_true("★ 파일 응답이 Last-Modified 를 준다(IMS 협상의 전제)",
                   bool(last_modified), r3.headers.get("last-modified"))

        if etag and last_modified:
            def cond(headers):
                return client.get(target, headers=dict(HDR, **headers)).status_code

            # (1) 약한 비교 — RFC 9110 §13.1.2 는 If-None-Match 에 약한 비교를 쓰라고 한다.
            check("★ 약한 ETag(W/) 도 304 다", cond({"If-None-Match": "W/" + etag}), 304)
            check("★ 소문자 w/ 도 같다", cond({"If-None-Match": "w/" + etag}), 304)
            check("★ 목록 중 하나만 맞아도 304 다",
                  cond({"If-None-Match": '"nope", W/' + etag + ', "other"'}), 304)
            check("★ `*` 는 표현이 있기만 하면 304 다", cond({"If-None-Match": "*"}), 304)
            check("★ 맞지 않는 ETag 는 200 이다(공허하지 않은 대조군)",
                  cond({"If-None-Match": '"definitely-not-it"'}), 200)

            file_ts = email.utils.parsedate_to_datetime(last_modified).timestamp()

            # (2) If-Modified-Since — ETag 를 못 쓰는 캐시가 쓰는 경로.
            check("★ 파일과 같은 시각이면 304 다",
                  cond({"If-Modified-Since": last_modified}), 304)
            check("★ 클라이언트 쪽이 더 최신이면 304 다",
                  cond({"If-Modified-Since":
                        email.utils.formatdate(file_ts + 60, usegmt=True)}), 304)
            check("★ 파일이 더 최신이면 200 이다(바뀐 문서를 옛것으로 보여주지 않는다)",
                  cond({"If-Modified-Since":
                        email.utils.formatdate(file_ts - 60, usegmt=True)}), 200)

            # (3) 날짜를 못 읽으면 **조건을 무시하고 200** — 잘못 304 를 주는 것보다 안전하다.
            check("★ 깨진 날짜는 조건을 무시하고 200 이다",
                  cond({"If-Modified-Since": "not-a-date"}), 200)
            check("★ 빈 값도 마찬가지다", cond({"If-Modified-Since": ""}), 200)

            # (4) 우선순위 — RFC 9110 §13.1.3: If-None-Match 가 있으면 IMS 는 **보지 않는다.**
            #     이 규칙이 없으면 ETag 로 "바뀌었다"고 판정한 요청을 날짜가 뒤집는다.
            check("★ If-None-Match 가 있으면 If-Modified-Since 는 무시한다",
                  cond({"If-None-Match": '"nope"', "If-Modified-Since": last_modified}), 200)

            # (5) ★ HEAD 에는 304 를 주지 않는다 (의도된 예외).
            #
            #     프런트는 문서 뷰어를 열기 전에 HEAD 로 존재를 확인한다
            #     (`src/app/properties/[id]/page.tsx` 의 `headOk()`). 그 판정은
            #     `res.ok` 이고 그것은 200~299 에서만 참이다. HEAD 응답에는 애초에
            #     본문이 없으니 304 로 아낄 바이트가 **0** 인데, 304 를 주면
            #     "문서 없음" 으로 잘못 읽힐 위험만 생긴다.
            #     얻는 것이 없으면 위험도 만들지 않는다 - 그 규칙을 여기서 잠근다.
            head = client.head(target, headers=dict(HDR, **{"If-None-Match": etag}))
            check("★ HEAD 에는 304 를 주지 않는다(존재 확인이 '없음'으로 뒤집힌다)",
                  head.status_code, 200)
            check_true("★ 그래서 res.ok 가 참이다(프런트의 판정 기준)",
                       200 <= head.status_code < 300, head.status_code)
            check_true("HEAD 에도 검증자는 그대로 붙는다",
                       bool(head.headers.get("etag")), dict(head.headers))

            # (6) 304 응답도 검증자를 다시 실어야 한다 — RFC 9110 §15.4.5.
            #     안 실으면 캐시가 다음 요청에서 조건을 걸 수 없어 304 절약이 1회로 끝난다.
            r5 = client.get(target, headers=dict(HDR, **{"If-None-Match": etag}))
            check("★ 304 가 ETag 를 다시 실어 준다", r5.headers.get("etag"), etag)
            check("★ 304 가 Last-Modified 를 다시 실어 준다",
                  r5.headers.get("last-modified"), last_modified)

    print("\n" + "=" * 64)
    if failures:
        print("FAILED (%d/%d): %s" % (len(failures), CHECKS[0], ", ".join(failures)))
        return 1
    print("ALL CACHE HEADER TESTS PASSED (%d checks)" % CHECKS[0])
    return 0


if __name__ == "__main__":
    sys.exit(run())
