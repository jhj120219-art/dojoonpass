"""공개 엔드포인트가 **무엇을 내보내는지** 고정한다 (docs/BUGS.md #254 / 2026-08-28).

## 실측으로 찾은 것

`GET /api/v1/item/{item_id}` 는 **인증 없이** 읽을 수 있다
(`test_api_regression.PUBLIC_ENDPOINTS` 에 그렇게 등록돼 있다).

본체(`auction_item`)는 필드를 하나씩 적어 내보내는데, 곁딸린 세 테이블만
`dict(row)` 로 **행 전체**를 실었다.

    "case":           dict(case)
    "tenants":        [dict(t) for t in tenants]
    "rights_summary": dict(rights)

그래서 마이그레이션이 그 테이블에 컬럼을 하나 추가하면 **그날로 인증 없이 읽히는
API 에 실린다.** 아무도 그렇게 결정하지 않았고, 알려 줄 검사도 없었다.

그리고 그 세 테이블에는 **개인정보가 들어 있다**(2026-08-28 auction.db 실측).

    tenant_rights   tenant_name    240/519 행이 실명("김미화" 등)
                    occupied_area  475/519 행이 전체 주소
                    deposit / monthly_rent / move_in_date / fixed_date

감사 문서 두 곳은 그 반대로 적고 있었다 —

    docs/CURRENT_STATE.md §9229   "공개 8개에 개인정보·관리 기능 없음"
    docs/CHANGELOG.md     §4827   "공개 8개에 개인정보·관리 기능 없음"

## 이 파일이 하는 일

**응답을 바꾸지 않는다.** `api/v1/item.py` 의 화이트리스트는 지금 나가는 컬럼
그대로다. 여기서 고정하는 것은 두 가지다.

    1. 화이트리스트 == 실제 테이블 컬럼
       마이그레이션이 컬럼을 늘리면 이 검사가 **그 이름을 대며** 실패한다.
       목록에 적는 행위가 곧 "이것을 공개한다"는 결정이 된다.

    2. 개인정보가 공개 경로로 나간다는 **사실 자체**
       마스킹은 제품·법무 판단이라 여기서 정하지 않는다(임차인 성명은 대항력
       판단의 근거라 가리면 권리분석이 약해진다). 대신 "없다"고 적었던 문서가
       조용히 돌아오지 못하게 한다.

컬럼 순서는 보지 않는다 — migration 024 가 `auction_case` 의 순서를 바꾼다
(집합은 그대로). 순서로 판정하면 승인된 마이그레이션이 적용되는 날 이 검사가
엉뚱하게 붉어진다.

읽기 전용이다. auction.db 에 아무것도 쓰지 않는다.

    python test_public_endpoint_exposure.py
"""
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import storage.database as dbmod
from api.v1.item import _CASE_FIELDS, _RIGHTS_FIELDS, _TENANT_FIELDS

failures = []


def _safe(text):
    """콘솔 인코딩에 없는 문자를 지운다.

    이 검사는 **문서 원문을 되받아 찍는다.** 그 안에는 U+2014 EM DASH 가 들어 있고,
    cp949 콘솔(bash / cmd.exe / `run_daily.bat` 의 리다이렉트)에서는 그것을 찍다가
    UnicodeEncodeError 로 **프로세스가 죽는다** ― 검사가 실패한 것이 아니라 결과를
    출력하다 죽는 것이라 더 나쁘다(`test_console_encoding.py` 가 지키는 그 사고).
    """
    enc = getattr(sys.stdout, "encoding", None) or "utf-8"
    return str(text).encode(enc, "replace").decode(enc, "replace")


def _check_true(name, ok, detail=""):
    print(_safe("[%s] %s%s" % ("PASS" if ok else "FAIL", name,
                               "" if ok else "  -> %s" % (detail,))))
    if not ok:
        failures.append(name)


#: 응답 키 -> (테이블, 화이트리스트). `api/v1/item.py` 가 이 셋만 행 단위로 싣는다.
NESTED = (
    ("tenants", "tenant_rights", _TENANT_FIELDS),
    ("case", "auction_case", _CASE_FIELDS),
    ("rights_summary", "rights_summary", _RIGHTS_FIELDS),
)

#: 공개 경로로 나가는 **개인정보** 컬럼. 줄이려면 마스킹 구현이 함께 와야 한다.
PII_FIELDS = {
    "tenant_rights": ("tenant_name", "occupied_area", "deposit", "monthly_rent",
                      "move_in_date", "fixed_date"),
}


def test_whitelist_matches_the_actual_schema():
    """화이트리스트가 실제 컬럼과 **정확히 같은 집합**인가.

    적은 쪽으로 어긋나면 = 조용히 응답이 줄었다(프런트가 깨진다).
    많은 쪽으로 어긋나면 = 새 컬럼이 공개 API 에 실렸다.
    """
    print("\n--- 1. 화이트리스트 == 실제 테이블 컬럼 ---")
    conn = dbmod.get_connection()
    try:
        for key, table, fields in NESTED:
            cols = {r[1] for r in conn.execute("PRAGMA table_info(%s)" % table)}
            _check_true("%s: 테이블이 존재한다" % table, bool(cols))
            if not cols:
                continue
            missing = cols - set(fields)
            extra = set(fields) - cols
            _check_true(
                "%s: 새 컬럼이 공개 응답에 자동으로 실리지 않는다" % table,
                not missing,
                "%s 에 %s 가 생겼다. api/v1/item.py 의 목록에 적을지 **결정**하라. "
                "적으면 인증 없이 읽힌다." % (table, sorted(missing)),
            )
            _check_true(
                "%s: 사라진 컬럼을 응답이 약속하고 있지 않다" % table,
                not extra,
                "화이트리스트에만 있는 컬럼 %s" % sorted(extra),
            )
    finally:
        conn.close()


def test_item_detail_does_not_dump_whole_rows():
    """`dict(row)` 로 되돌아가면 1번 검사가 **무력해진다**.

    화이트리스트가 맞는지 아무리 봐도, 응답이 그것을 안 쓰면 의미가 없다.
    그래서 소스에서 그 형태 자체를 막는다.
    """
    print("\n--- 2. 곁딸린 행을 통째로 싣지 않는다 (소스 계약) ---")
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "api", "v1", "item.py")
    src = open(path, encoding="utf-8-sig").read()
    body = src[src.index("def get_item("):]
    for key, table, _ in NESTED:
        line = [ln for ln in body.splitlines() if '"%s":' % key in ln]
        _check_true("%s 응답 줄을 찾았다" % key, bool(line))
        if not line:
            continue
        _check_true("%s 를 _project() 로 만든다" % key,
                    "_project(" in line[0], line[0].strip())
        _check_true("%s 에 dict(row) 덤프가 없다" % key,
                    "dict(" not in line[0], line[0].strip())


def test_pii_on_a_public_route_is_recorded_not_forgotten():
    """개인정보가 **공개 경로로 나간다는 사실**을 고정한다.

    "공개 경로에 개인정보 없음" 이라고 적힌 문서 두 곳이 사실과 달랐다.
    사람이 다시 그렇게 적더라도, 이 검사가 실데이터로 반박한다.

    마스킹이 구현되면 이 검사가 실패한다 — 그때가 PII_FIELDS 와 문서를
    함께 정리할 시점이다. 조용히 어긋난 상태로 남지 않게 한다.
    """
    print("\n--- 3. 공개 경로의 개인정보 (실데이터) ---")
    for table, fields in PII_FIELDS.items():
        exposed = [f for f in fields if f in set(_TENANT_FIELDS)]
        _check_true("%s: 개인정보 컬럼이 여전히 공개 응답에 있다" % table,
                    len(exposed) == len(fields), exposed)

    conn = dbmod.get_connection()
    try:
        named = conn.execute(
            "SELECT COUNT(*) FROM tenant_rights WHERE tenant_name IS NOT NULL"
            " AND TRIM(tenant_name) <> ''").fetchone()[0]
    except sqlite3.OperationalError:
        named = None
    finally:
        conn.close()
    _check_true("실명이 실제로 저장돼 있다(가정이 아니라 실측)",
                named is None or named > 0,
                "tenant_name 이 있는 행 %s" % (named,))
    print("   tenant_name 보유 행: %s" % (named,))

    # 문서가 "없다"로 되돌아가지 못하게 한다.
    root = os.path.dirname(os.path.abspath(__file__))
    claim = "공개에 개인정보"
    for name in ("docs/CURRENT_STATE.md", "docs/CHANGELOG.md"):
        p = os.path.join(root, *name.split("/"))
        if not os.path.exists(p):
            continue
        text = open(p, encoding="utf-8", errors="replace").read()
        bad = [ln.strip() for ln in text.splitlines()
               if claim in ln and "없음" in ln and "#254" not in ln]
        _check_true("%s: '공개에 개인정보 없음' 주장이 정정돼 있다" % name,
                    not bad, bad[:2])


def test_source_files_are_not_indexable():
    """원천 문서/사진이 **검색엔진에 색인되지 않는가** (2026-08-30, BUGS #254).

    ## 전수 확인에서 나온 구멍

    JSON 응답의 임차인 정보는 가렸는데, **같은 물건의 PDF 는 인증 없이 그대로**
    나가고 있었다.

        GET /api/v1/item/53/documents/SPEC   200  application/pdf  402,328B
        본문에 임차인 실명 '김미화' '안지은' 이 그대로 있다
        그 PDF 첫 줄에 법원이 직접 "개인정보유출주의" 라고 적어 두었다

    실측: 공개 `spec.pdf` 371개 중 **약 92개(25%)** 에 임차인 실명이 있다(표본 40).

    ## 왜 인증으로 막지 않는가

    프런트가 이 주소를 `<iframe src>` / `<a href>` 로 쓴다 — 브라우저의 그 요청에는
    Authorization 헤더를 실을 수 없다. 토큰을 요구하면 뷰어와 다운로드가 깨진다.
    그리고 원천이 이미 공개다(법원 사이트가 로그인 없이 같은 문서를 준다).

    ## 그래서 **증폭**을 막는다

    원천이 공개인 것과 우리 도메인에서 **검색 가능해지는 것**은 다르다. 사람 이름을
    검색했을 때 우리 사이트가 뜨는 일을 막는다. 브라우저는 이 헤더를 무시하므로
    뷰어 동작은 그대로다.

    `robots.txt` 는 **받기 전에** 막고 헤더는 **받은 뒤에** 막는다 — 짝이다.
    """
    print("\n--- 4. 원천 자료 색인 차단 (BUGS #254) ---")
    import contextlib
    import io as _io

    conn = dbmod.get_connection()
    try:
        doc = conn.execute(
            "SELECT ai.id FROM auction_item ai JOIN doc_raw dr ON dr.item_id = ai.id"
            # ★ `doc_raw.doc_type` 은 **대문자**다(SPEC/STATUS/APPRAISAL).
            #   소문자로 물으면 0건이라 이 검사가 조용히 건너뛴다.
            " WHERE dr.doc_type='SPEC' LIMIT 1").fetchone()
        img = conn.execute("SELECT item_id, seq FROM auction_image LIMIT 1").fetchone()
    except sqlite3.OperationalError:
        doc = img = None
    finally:
        conn.close()

    from fastapi.testclient import TestClient
    import api_server
    with contextlib.redirect_stderr(_io.StringIO()):
        client = TestClient(api_server.app)

    # robots.txt 가 원천 경로를 막는가.
    r = client.get("/robots.txt")
    _check_true("robots.txt 가 있다", r.status_code == 200, r.status_code)
    body = r.text if r.status_code == 200 else ""
    for rule in ("/api/v1/item/*/documents/", "/api/v1/item/*/images/"):
        _check_true("robots.txt 가 %s 를 막는다" % rule,
                    ("Disallow: " + rule) in body, body[:120])
    # ★ 개인정보가 없는 공개 지표까지 막지는 않는다(과잉 차단 방지).
    _check_true("검색/통계는 막지 않는다",
                "Disallow: /api/v1/search" not in body, body[:160])

    want = "noindex"
    checked = 0

    if doc is not None:
        rr = client.get("/api/v1/item/%d/documents/SPEC" % doc["id"])
        if rr.status_code == 200:
            checked += 1
            _check_true("★ 문서 응답에 X-Robots-Tag 가 붙는다",
                        want in (rr.headers.get("x-robots-tag") or ""),
                        rr.headers.get("x-robots-tag"))
            # 계약이 깨지지 않았는지 - 여전히 PDF 를 준다.
            _check_true("문서는 그대로 나간다(막은 것은 색인뿐)",
                        rr.content[:4] == b"%PDF", rr.headers.get("content-type"))

    if img is not None:
        rr = client.get("/api/v1/item/%d/images/%d" % (img["item_id"], img["seq"]))
        if rr.status_code == 200:
            checked += 1
            _check_true("★ 사진 응답에 X-Robots-Tag 가 붙는다",
                        want in (rr.headers.get("x-robots-tag") or ""),
                        rr.headers.get("x-robots-tag"))

    _check_true("검사가 공허하지 않다(원천 응답을 실제로 받았다)", checked >= 1, checked)

    # 대조군 - 개인정보가 없는 응답까지 막지는 않는다.
    rr = client.get("/api/v1/search?page=1")
    if rr.status_code == 200:
        _check_true("검색 응답에는 색인 차단을 붙이지 않는다",
                    not (rr.headers.get("x-robots-tag") or ""),
                    rr.headers.get("x-robots-tag"))


def test_openapi_docs_can_be_closed_for_deployment():
    """OpenAPI 문서 UI 를 **끌 수 있는가** (2026-09-03).

    ## 왜 이 검사가 필요한가 (실측)

    인증 없이 `GET /openapi.json` 이 200 이고, 거기에 `/api/v1/admin/*` **16개**가
    요청/응답 스키마와 함께 실려 있다. `/docs` · `/redoc` 도 200 이다.

    지금은 서버가 `127.0.0.1` 로만 바인딩하므로 노출이 국지적이고, `/docs` 는
    `docs/CLAUDE.md` 가 개발 워크플로로 안내하는 자리다. 그래서 **기본값은 공개 그대로**
    두고 스위치만 만들었다(`CORS_ALLOW_ORIGINS` 가 "미설정이면 기존 `*`" 로 들어온 것과
    같은 방식). 이 검사가 지키는 것은 두 가지다.

        1. 기본값이 조용히 바뀌지 않는다      — 개발 워크플로가 깨지지 않는다
        2. 스위치가 실제로 닫는다             — 배포 때 켜 봤더니 안 닫히면 의미가 없다

    끄더라도 **API 자체는 그대로 돌아야 한다** — 그것까지 함께 확인한다.
    """
    print("\n--- OpenAPI 문서 UI 토글 (배포 시 닫을 수 있는가) ---")
    import contextlib
    import importlib
    import io as _io
    from fastapi.testclient import TestClient

    saved = os.environ.get("API_DOCS_ENABLED")
    DOC_PATHS = ("/docs", "/redoc", "/openapi.json")
    try:
        import api_server

        # (1) 미설정 = 기존대로 공개
        os.environ.pop("API_DOCS_ENABLED", None)
        with contextlib.redirect_stderr(_io.StringIO()):
            importlib.reload(api_server)
            client = TestClient(api_server.app)
        for p in DOC_PATHS:
            _check_true("기본값(미설정)에서 %s 가 열려 있다" % p,
                        client.get(p).status_code == 200, client.get(p).status_code)

        # 공허 방지 — 열려 있을 때 admin 경로가 실제로 실린다는 것을 확인한다.
        spec = client.get("/openapi.json")
        admin_paths = [p for p in (spec.json().get("paths", {}) if spec.status_code == 200 else {})
                       if "/admin/" in p]
        _check_true("열려 있을 때 admin 경로가 스펙에 실린다(검사가 공허하지 않다)",
                    len(admin_paths) >= 10, len(admin_paths))

        # (2) 끄면 실제로 닫힌다
        os.environ["API_DOCS_ENABLED"] = "0"
        with contextlib.redirect_stderr(_io.StringIO()):
            importlib.reload(api_server)
            client = TestClient(api_server.app)
        for p in DOC_PATHS:
            _check_true("API_DOCS_ENABLED=0 에서 %s 가 닫힌다" % p,
                        client.get(p).status_code == 404, client.get(p).status_code)

        # (3) 껐다고 API 가 죽지 않는다
        r = client.get("/api/v1/search?size=1")
        _check_true("문서를 꺼도 API 는 그대로 동작한다", r.status_code == 200, r.status_code)
    finally:
        if saved is None:
            os.environ.pop("API_DOCS_ENABLED", None)
        else:
            os.environ["API_DOCS_ENABLED"] = saved
        with contextlib.redirect_stderr(_io.StringIO()):
            importlib.reload(api_server)


def run():
    test_whitelist_matches_the_actual_schema()
    test_item_detail_does_not_dump_whole_rows()
    test_pii_on_a_public_route_is_recorded_not_forgotten()
    test_source_files_are_not_indexable()
    test_openapi_docs_can_be_closed_for_deployment()
    print("\n%s  (실패 %d)" % ("모두 통과" if not failures else "실패: %s" % failures,
                               len(failures)))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(run())
