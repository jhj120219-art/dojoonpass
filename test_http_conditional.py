"""조건부 요청(304) 회귀 — 2026-08-17 Sprint 146 신설.

## 왜 이 파일이 생겼나 (실측)

검색 결과 카드의 썸네일이 **원본 사진을 그대로** 쓴다(서버 측 썸네일 생성은 Pillow가
`requirements.txt`에 없어 SKIP 상태). 실측 1페이지 전송량:

    9건(현재 검색 노출 전부)  0.91 MB   평균 104 KB / 최대 236 KB
    기본 page size 20 환산    약 2.03 MB

그런데 Starlette `FileResponse`는 `etag`/`last-modified`를 **붙여 주기만 하고 조건부
요청을 해석하지 않는다**(설치본 `starlette 1.3.1` 소스 확인 — `if-range`만 다룬다).
그래서 브라우저가 검증자를 되보내도 서버가 전체 본문을 다시 보냈다:

    GET /api/v1/item/502/documents/APPRAISAL                      200  2,528,908 B
    GET 같은 URL + If-None-Match: <그 etag>                       200  2,528,908 B   <- 304여야 한다
    GET 같은 URL + If-Modified-Since: <그 last-modified>          200  2,528,908 B

수정 후 재측정: 검색 1페이지 재방문이 **0.91 MB -> 0 MB**.

## ★ 이 테스트가 특히 지키는 것 — `stat_result`

`FileResponse(path, ...)`에 `stat_result`를 넘기지 않으면 Starlette는 **응답을 보낼
때에야** 파일을 stat해서 검증자를 만든다(`FileResponse.__call__`). 그러면 우리 조건부
검사가 헤더를 아직 못 봐서 **조용히 항상 200이 나간다** — 실제로 1차 구현에서 그렇게
됐고, 응답 코드만 보면 정상이라 눈치채기 어려웠다. 그래서 "304가 나온다"를 직접 고정한다.

    python test_http_conditional.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

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
    from fastapi.testclient import TestClient
    import api_server
    return TestClient(api_server.app)


def _pick_targets(client):
    """실 DB에서 200이 나오는 사진 1건 + 문서 1건을 고른다.

    하드코딩한 id를 쓰지 않는다 — 수집이 진행되면 id가 바뀌고, 그때 테스트가
    "기능이 깨졌다"가 아니라 "데이터가 없다"로 실패하면 신호가 흐려진다.
    """
    import sqlite3
    conn = sqlite3.connect("auction.db")
    conn.row_factory = sqlite3.Row
    try:
        img = conn.execute(
            "SELECT item_id, seq FROM auction_image ORDER BY item_id, seq LIMIT 1").fetchone()
        doc = conn.execute(
            "SELECT item_id, doc_type FROM doc_raw WHERE doc_type IN ('SPEC','APPRAISAL','STATUS')"
            " ORDER BY item_id LIMIT 1").fetchone()
    finally:
        conn.close()

    targets = []
    if img:
        targets.append(("image", "/api/v1/item/%d/images/%d" % (img["item_id"], img["seq"])))
    if doc:
        targets.append(("document",
                        "/api/v1/item/%d/documents/%s" % (doc["item_id"], doc["doc_type"])))
    return targets


# ---------------------------------------------------------------------------
# 1. 정상 — 검증자가 실제로 나가는가
# ---------------------------------------------------------------------------
def test_validators_are_present():
    print("\n--- 1. 검증자(etag/last-modified)가 응답에 있다 ---")
    client = _client()
    targets = _pick_targets(client)
    check_true("실 DB에 검사할 사진/문서가 있다", len(targets) >= 1, targets)
    for kind, url in targets:
        r = client.get(url)
        check("%s 최초 요청은 200" % kind, r.status_code, 200)
        check_true("%s etag가 있다" % kind, bool(r.headers.get("etag")), dict(r.headers))
        check_true("%s last-modified가 있다" % kind,
                   bool(r.headers.get("last-modified")), dict(r.headers))
        check_true("%s 본문이 비어 있지 않다" % kind, len(r.content) > 0)


# ---------------------------------------------------------------------------
# 2. ★ 조건부 요청이 304를 준다 (본문 0바이트)
# ---------------------------------------------------------------------------
def test_conditional_requests_return_304():
    print("\n--- 2. If-None-Match / If-Modified-Since -> 304 ---")
    client = _client()
    for kind, url in _pick_targets(client):
        first = client.get(url)
        etag = first.headers.get("etag")
        last_modified = first.headers.get("last-modified")

        r = client.get(url, headers={"If-None-Match": etag})
        check("%s If-None-Match -> 304" % kind, r.status_code, 304)
        check("%s 304 본문은 0바이트" % kind, len(r.content), 0)
        check("%s 304에 etag를 다시 실어 준다" % kind, r.headers.get("etag"), etag)

        r = client.get(url, headers={"If-Modified-Since": last_modified})
        check("%s If-Modified-Since -> 304" % kind, r.status_code, 304)
        check("%s 304 본문은 0바이트(IMS)" % kind, len(r.content), 0)


# ---------------------------------------------------------------------------
# 3. 경계값 / 잘못된 입력 — 거짓 304를 주지 않는다
# ---------------------------------------------------------------------------
def test_never_falsely_304():
    print("\n--- 3. 조건이 맞지 않으면 200 전체 본문 ---")
    client = _client()
    for kind, url in _pick_targets(client):
        full = len(client.get(url).content)

        for label, headers in (
            ("틀린 etag", {"If-None-Match": '"deadbeef"'}),
            ("빈 etag", {"If-None-Match": ""}),
            ("깨진 날짜", {"If-Modified-Since": "not-a-date"}),
            # 파일이 그 시각 이후에 바뀐 경우 = 조건 불충족
            ("과거 시각", {"If-Modified-Since": "Mon, 01 Jan 1990 00:00:00 GMT"}),
        ):
            r = client.get(url, headers=headers)
            check("%s / %s -> 200" % (kind, label), r.status_code, 200)
            check("%s / %s 전체 본문" % (kind, label), len(r.content), full)


# ---------------------------------------------------------------------------
# 4. 와일드카드 / weak etag / 목록
# ---------------------------------------------------------------------------
def test_etag_matching_rules():
    print("\n--- 4. `*` / W/ 접두사 / 콤마 목록 ---")
    client = _client()
    targets = _pick_targets(client)
    if not targets:
        return
    kind, url = targets[0]
    etag = client.get(url).headers.get("etag")

    check("`*`는 304", client.get(url, headers={"If-None-Match": "*"}).status_code, 304)
    check("W/ 접두사도 매칭(약한 비교)",
          client.get(url, headers={"If-None-Match": "W/%s" % etag}).status_code, 304)
    check("콤마 목록에 포함되면 304",
          client.get(url, headers={"If-None-Match": '"aaa", %s , "bbb"' % etag}).status_code, 304)
    check("목록에 없으면 200",
          client.get(url, headers={"If-None-Match": '"aaa", "bbb"'}).status_code, 200)


# ---------------------------------------------------------------------------
# 5. If-None-Match가 If-Modified-Since보다 우선 (RFC 9110 §13.1.3)
# ---------------------------------------------------------------------------
def test_if_none_match_wins():
    print("\n--- 5. If-None-Match 우선 ---")
    client = _client()
    targets = _pick_targets(client)
    if not targets:
        return
    kind, url = targets[0]
    first = client.get(url)
    last_modified = first.headers.get("last-modified")

    # etag가 어긋나면 IMS가 만족되더라도 200이어야 한다.
    r = client.get(url, headers={"If-None-Match": '"deadbeef"',
                                 "If-Modified-Since": last_modified})
    check("etag 불일치 + IMS 만족 -> 200", r.status_code, 200)
    check_true("전체 본문이 온다", len(r.content) > 0)


# ---------------------------------------------------------------------------
# 6. HEAD는 304를 주지 않는다 (의도된 예외)
#
# HEAD 응답에는 본문이 없어 304로 아낄 바이트가 0이다. 반면 프런트는 문서 존재 확인을
# `fetch(HEAD).then(res => res.ok ? 'ok' : 'notfound')`로 하고 `res.ok`는 200~299에서만
# 참이다. 이득이 0인 자리에 그 의존을 남기지 않는다.
# ---------------------------------------------------------------------------
def test_head_never_304():
    print("\n--- 6. HEAD는 항상 200 (304 아님) ---")
    client = _client()
    for kind, url in _pick_targets(client):
        etag = client.get(url).headers.get("etag")
        check("%s HEAD 최초 200" % kind, client.head(url).status_code, 200)
        check("%s HEAD + If-None-Match도 200" % kind,
              client.head(url, headers={"If-None-Match": etag}).status_code, 200)
        check("%s HEAD + `*`도 200" % kind,
              client.head(url, headers={"If-None-Match": "*"}).status_code, 200)
        # 존재하지 않는 것은 여전히 404여야 한다(HEAD 예외가 검사를 무르게 하지 않는다).
        check("%s HEAD 404는 그대로" % kind,
              client.head("/api/v1/item/999999/images/1").status_code, 404)


# ---------------------------------------------------------------------------
# 8. ★★ 파일이 바뀌면 옛 검증자가 무효가 되는가 (캐시의 존재 이유)
#
# 이 검사가 없으면 "304를 준다"만 고정되고 **틀린 304를 주지 않는다**는 더 중요한
# 성질이 비어 있다. 캐시가 실패하는 방식은 보통 "안 준다"가 아니라 "낡은 것을 준다"다.
#
# 운영 `documents/`를 건드리지 않는다 — `test_asset_pipeline.Env`가 쓰는 임시 DB +
# 임시 문서 루트를 그대로 재사용한다(스키마는 실제 부트스트랩 절차로 만들어진다).
# ---------------------------------------------------------------------------
def test_stale_validator_after_file_change():
    print("\n--- 8. 파일 변경/삭제 후 캐시 검증 ---")
    import contextlib
    import io
    import time

    import test_asset_pipeline as tap
    from fastapi.testclient import TestClient

    env = tap.Env()
    try:
        court, case_no, item_no = env.seed_item(item_id=1)
        img_dir = os.path.join(env.docs, court, case_no, item_no, "images")
        os.makedirs(img_dir)
        path = os.path.join(img_dir, "01.jpg")
        with open(path, "wb") as f:
            f.write(b"\xff\xd8\xff" + b"A" * 5000)

        rel = os.path.relpath(path, os.path.dirname(env.docs)).replace(os.sep, "/")
        conn = env.conn()
        try:
            conn.execute(
                "INSERT INTO auction_image (item_id,seq,kind,storage_path,file_hash,"
                "file_size,crawl_date,created_at) VALUES (1,1,'전경도',?,?,?,?,?)",
                (rel, "h", os.path.getsize(path), "2026-08-17", "2026-08-17T00:00:00"))
            conn.commit()
        finally:
            conn.close()

        import api_server
        with contextlib.redirect_stderr(io.StringIO()):
            client = TestClient(api_server.app)
        url = "/api/v1/item/1/images/1"

        first = client.get(url)
        check("최초 200", first.status_code, 200)
        etag_old = first.headers.get("etag")
        check("같은 etag -> 304", client.get(url, headers={"If-None-Match": etag_old}).status_code, 304)

        # 내용과 크기를 바꾼다. HTTP-date 해상도가 1초라 mtime이 확실히 넘어가게 둔다.
        time.sleep(1.1)
        with open(path, "wb") as f:
            f.write(b"\xff\xd8\xff" + b"B" * 9000)

        stale = client.get(url, headers={"If-None-Match": etag_old})
        check("★ 파일이 바뀌면 옛 etag는 200", stale.status_code, 200)
        check("★ 전체 본문이 온다", len(stale.content), 9003)
        etag_new = stale.headers.get("etag")
        check_true("etag가 실제로 바뀌었다", etag_old != etag_new, (etag_old, etag_new))
        check("새 etag -> 304", client.get(url, headers={"If-None-Match": etag_new}).status_code, 304)

        # 삭제된 파일을 캐시가 가려 주면 안 된다 — 404여야 한다.
        os.remove(path)
        check("★ 파일 삭제 후에는 404(304 아님)",
              client.get(url, headers={"If-None-Match": etag_new}).status_code, 404)
        check("삭제 + `*`도 404",
              client.get(url, headers={"If-None-Match": "*"}).status_code, 404)
    finally:
        env.close()


# ---------------------------------------------------------------------------
# 7. ★ stat_result를 넘기는지 소스로 고정
# ---------------------------------------------------------------------------
def test_stat_result_is_passed():
    """넘기지 않으면 검증자가 전송 시점에 만들어져 **조용히 항상 200**이 된다.

    §2가 이미 동작을 검사하지만, 실패했을 때 원인을 바로 짚어 주기 위해 남긴다
    (이 저장소가 반복해 겪은 "응답 코드는 정상인데 기능이 없다" 계열이다).
    """
    print("\n--- 7. FileResponse에 stat_result를 넘긴다 ---")
    root = os.path.dirname(os.path.abspath(__file__))
    for name in ("images.py", "documents.py"):
        src = open(os.path.join(root, "api", "v1", name), encoding="utf-8-sig").read()
        check_true("%s가 stat_result를 넘긴다" % name, "stat_result=" in src)
        check_true("%s가 not_modified를 쓴다" % name, "not_modified(" in src)


if __name__ == "__main__":
    test_validators_are_present()
    test_conditional_requests_return_304()
    test_never_falsely_304()
    test_etag_matching_rules()
    test_if_none_match_wins()
    test_head_never_304()
    test_stat_result_is_passed()
    test_stale_validator_after_file_change()

    print("\n" + "=" * 55)
    if failures:
        print("FAILED (%d): %s" % (len(failures), ", ".join(failures)))
        sys.exit(1)
    print("ALL HTTP CONDITIONAL TESTS PASSED")
