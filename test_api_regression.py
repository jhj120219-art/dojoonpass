"""
전 도메인 API 회귀 테스트 (실제 HTTP 레벨).

FastAPI TestClient로 api_server.app을 직접 호출하므로 라우팅/의존성/인증/직렬화까지
실제 요청과 동일한 경로를 탄다. 커버 도메인:
    Auth / Search / Detail / Favorite / Recent / SearchPreset /
    Registry / Payment / Subscription / Admin / Documents / Stats

    python test_api_regression.py

주의:
- 테스트 전용 user_id(qa-reg-<uuid>)로만 데이터를 만들고, 끝나면 그 user_id의 행만 정리한다.
  실제 사용자 데이터는 조회만 하고 절대 건드리지 않는다.
- ADMIN_API_KEY / SUPABASE_JWT_SECRET은 이 프로세스 환경에만 주입한다(.env 파일은 수정하지
  않는다). 두 값 모두 이 테스트가 검증하는 것은 "인가/서명 로직이 올바른가"이지 실제 운영
  Supabase 프로젝트의 진짜 비밀값이 맞는가가 아니므로, 테스트 프로세스 안에서만 유효한
  합성 값으로 충분하다(2026-08-08 — 이 환경의 .env에는 SUPABASE_JWT_SECRET이라는 이름
  자체가 없어서 추가함, JWT_SECRET이라는 다른 이름만 존재. docs/BETA_RELEASE_CHECKLIST.md
  P0-4 참고. 실제 운영 배포에서는 여전히 .env에 정확한 이름으로 진짜 값을 넣어야 한다).
- 출력은 ASCII만 사용한다(Windows cp949 콘솔에서 UnicodeEncodeError 방지).
"""
import sys
import os
import json
import uuid
import secrets
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Admin 인증 테스트를 위해 프로세스 환경에만 키를 주입한다(.env 무수정).
# api/v1/admin.py는 요청 시점에 os.getenv를 읽으므로 import 전에 설정해야 한다.
TEST_ADMIN_KEY = "qa-regression-admin-key"
TEST_SUPER_ADMIN_KEY = "qa-regression-super-admin-key"
os.environ["ADMIN_API_KEY"] = TEST_ADMIN_KEY
os.environ["SUPER_ADMIN_API_KEY"] = TEST_SUPER_ADMIN_KEY

# api/auth.py는 모듈 최상단에서 SUPABASE_JWT_SECRET = os.getenv(...)로 한 번만 읽으므로
# import 전에 설정해야 한다. .env에 이미 값이 있으면(정확한 이름으로) 그 값을 그대로
# 쓰고, 없을 때만(이 환경처럼) 이 프로세스에서만 유효한 무작위 값으로 대체한다 — 그래야
# 실제 운영 값이 설정된 뒤에도 이 스크립트가 조용히 그 값을 덮어쓰지 않는다.
if not os.getenv("SUPABASE_JWT_SECRET"):
    os.environ["SUPABASE_JWT_SECRET"] = "qa-regression-" + secrets.token_hex(16)

from fastapi.testclient import TestClient
from jose import jwt

import api_server
from api.auth import SUPABASE_JWT_SECRET
from storage.database import get_connection
from api.v1.registry import OVERAGE_FEE
from api.v1.payments import resolve_plan_price, BILLING_MONTHLY, BILLING_YEARLY

client = TestClient(api_server.app)

TEST_USER = "qa-reg-" + uuid.uuid4().hex[:12]
failures = []

# 공통 응답 형식 (CTO 승인 8번). `message`는 프론트가 읽고 있어 하위호환으로 유지하고,
# `error`(도메인 Error Code)와 `meta`(페이지네이션 등)가 추가됐다.
ENVELOPE_KEYS = {"success", "data", "error", "meta", "message"}


def _safe_out(text):
    """콘솔 인코딩으로 표현할 수 없는 문자를 안전하게 치환한다.

    2026-08-11 Sprint 53 — 변이 테스트 중에 발견한 **하네스 결함**을 고친 것이다.
    이 파일 상단 규칙("출력은 ASCII만 사용한다")은 테스트가 직접 쓰는 문자열에만 적용되는데,
    실패 시 출력하는 `detail`에는 **제품 코드가 만든 문자열**이 그대로 실린다. 거기에 em-dash(—)
    같은 문자가 있으면 Windows cp949 콘솔에서 `UnicodeEncodeError`가 나고, 그 순간
    **실패가 깔끔한 FAIL이 아니라 스위트 중단으로 바뀐다** — 남은 검사도 실행되지 않는다.
    실제로 "서명 미검증 재처리 허용" 변이를 넣었을 때 FAIL 0건 + 크래시로 나타나
    회귀의 성격을 오판하기 쉬운 상태였다.

    개별 문자열을 ASCII로 다듬는 대신 출력 함수 한 곳에서 막는다 — 앞으로 어떤 제품 문자열이
    들어와도 같은 사고가 재발하지 않는다.
    """
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    return str(text).encode(encoding, errors="replace").decode(encoding, errors="replace")


def check(name, actual, expected):
    ok = actual == expected
    print(_safe_out("[%s] %s: %r (expected %r)" % ("PASS" if ok else "FAIL", name, actual, expected)))
    if not ok:
        failures.append(name)


def check_true(name, cond, detail=""):
    ok = bool(cond)
    print(_safe_out("[%s] %s%s" % ("PASS" if ok else "FAIL", name, ("" if ok else " -> " + str(detail)))))
    if not ok:
        failures.append(name)


def auth_headers(user_id=TEST_USER):
    """Supabase가 발급하는 것과 같은 형식(HS256, sub=user_id)의 테스트 토큰."""
    token = jwt.encode({"sub": user_id}, SUPABASE_JWT_SECRET, algorithm="HS256")
    return {"Authorization": "Bearer " + token}


def pick_item_ids(n=2):
    conn = get_connection()
    try:
        rows = conn.execute("SELECT id FROM auction_item LIMIT ?", (n,)).fetchall()
        return [r["id"] for r in rows]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 1. Health / Stats (인증 불필요)
# ---------------------------------------------------------------------------
def test_health_and_stats():
    print("\n--- 1. health / stats ---")
    r = client.get("/")
    check("health status", r.status_code, 200)
    check("health envelope", r.json()["success"], True)

    r = client.get("/api/v1/stats")
    check("stats status", r.status_code, 200)
    check_true("stats total > 0", r.json()["data"]["total"] > 0)

    r = client.get("/api/v1/document-stats")
    check("document-stats status", r.status_code, 200)
    check_true("document-stats has total_items", "total_items" in r.json())

    # 2026-08-12 Sprint 66: 위 두 줄은 "200이고 키가 하나 있다"까지만 봤다. 이 엔드포인트는
    # 숫자 8개를 돌려주는데 **그중 어느 것도 값이 맞는지 확인한 적이 없었다** — 집계 쿼리가
    # doc_type을 잘못 세거나 status 필터를 빠뜨려도 검사는 그대로 통과한다.
    # 각 숫자를 **자기 출처 테이블과 직접 대조**한다.
    stats = r.json()
    conn = get_connection()
    try:
        db_total = conn.execute("SELECT COUNT(*) FROM auction_item").fetchone()[0]
        pairs = {(row[0], row[1]): row[2] for row in conn.execute(
            "SELECT doc_type, status, COUNT(*) FROM document_status"
            " WHERE doc_type IN ('SPEC','STATUS','APPRAISAL') AND status IN ('READY','FAILED')"
            " GROUP BY doc_type, status")}
        db_failures = conn.execute("SELECT COUNT(*) FROM document_collect_failures").fetchone()[0]
    finally:
        conn.close()

    check("document-stats total_items = auction_item 건수", stats["total_items"], db_total)
    for key, doc_type, status in (
        ("spec_success", "SPEC", "READY"), ("status_success", "STATUS", "READY"),
        ("appraisal_success", "APPRAISAL", "READY"), ("spec_failed", "SPEC", "FAILED"),
        ("status_failed", "STATUS", "FAILED"), ("appraisal_failed", "APPRAISAL", "FAILED"),
    ):
        check("document-stats %s = document_status(%s,%s)" % (key, doc_type, status),
              stats[key], pairs.get((doc_type, status), 0))
    # total_failures는 document_status가 아니라 **다른 테이블**에서 온다.
    # 우연히 합계와 같아질 수 있으므로 자기 출처로 확인해야 의미가 있다.
    check("document-stats total_failures = document_collect_failures 건수",
          stats["total_failures"], db_failures)

    # ★ 위 한 줄만으로는 부족하다 — 현재 DB에서 document_collect_failures(3)와
    #   document_status FAILED(3)가 **우연히 같아서**, 출처 테이블을 바꿔치기하는 변이가
    #   그대로 살아남는다(2026-08-12 Sprint 66에 변이 테스트로 실제 확인).
    #   한쪽에만 행을 하나 더해 두 값을 어긋나게 만든 뒤, 엔드포인트가 **어느 쪽을 세는지**
    #   확인한다. 넣은 행은 곧바로 되돌린다.
    conn = get_connection()
    probe_id = None
    try:
        probe_item = pick_item_ids(1)[0]
        probe_id = conn.execute(
            "INSERT INTO document_collect_failures (item_id, doc_type, error_message, created_at)"
            " VALUES (?,?,?,?)",
            (probe_item, "SPEC", "qa-doc-stats-probe", datetime.now().isoformat())).lastrowid
        conn.commit()
    finally:
        conn.close()
    try:
        bumped = client.get("/api/v1/document-stats").json()
        check("total_failures가 document_collect_failures를 따라 증가한다",
              bumped["total_failures"], db_failures + 1)
        # 같은 요청에서 document_status 기반 숫자는 **변하지 않아야** 한다(출처가 다르므로)
        check("같은 변경이 spec_failed에는 영향을 주지 않는다",
              bumped["spec_failed"], stats["spec_failed"])
    finally:
        conn = get_connection()
        try:
            conn.execute("DELETE FROM document_collect_failures WHERE id=?", (probe_id,))
            conn.commit()
            left = conn.execute("SELECT COUNT(*) FROM document_collect_failures").fetchone()[0]
        finally:
            conn.close()
        check("probe 행이 정리됐다", left, db_failures)
    check_true("집계 대상이 실제로 존재한다(공허한 0 비교가 아님)",
               db_total > 0 and sum(pairs.values()) > 0, (db_total, pairs))


# ---------------------------------------------------------------------------
# 2. Search (비로그인 접근 가능 + 필터/정렬/페이지네이션)
# ---------------------------------------------------------------------------
def test_search():
    print("\n--- 2. search ---")
    r = client.get("/api/v1/search")
    check("search anonymous status", r.status_code, 200)
    body = r.json()
    for key in ("total", "page", "size", "total_pages", "items"):
        check_true("search response has " + key, key in body)
    check("search default size", body["size"], 20)
    check_true("is_favorited false for anonymous",
               all(i["is_favorited"] is False for i in body["items"]))

    # 정렬 화이트리스트 8개 전수(2026-08-10 Sprint 43 강화) — 기존에는 sort_by=auction_date
    # 하나만 200인지 확인해, api/v1/search.py:SORT_COLUMNS의 나머지 7개(특히 crawl_date —
    # 프론트 TypeScript 타입(src/app/search/types.ts)에 빠져 있던 것을 이번에 발견한 바로 그
    # 필드) 중 하나가 화이트리스트에서 빠지거나 오타가 나도 잡아내지 못했다. 8개 전부 200으로
    # 허용되고, 실제로 그 필드 기준으로 정렬된 결과를 돌려주는지(status만이 아니라 body 내용)
    # 까지 확인한다.
    SORT_WHITELIST = ("auction_date", "appraisal_price", "minimum_bid_price",
                       "bid_rate", "fail_count", "crawl_date", "case_no", "full_address")
    for field in SORT_WHITELIST:
        sr = client.get("/api/v1/search?sort_by=%s&sort_order=asc&size=50" % field)
        check("sort_by=%s allowed" % field, sr.status_code, 200)
        values = [i[field] for i in sr.json()["items"] if i.get(field) is not None]
        check_true("sort_by=%s actually sorted ascending" % field, values == sorted(values),
                   (field, values[:5]))
    check("sort_by rejected", client.get("/api/v1/search?sort_by=; DROP TABLE--").status_code, 400)
    check("sort_order rejected", client.get("/api/v1/search?sort_order=sideways").status_code, 400)

    # 페이지네이션 경계
    check("size over limit rejected", client.get("/api/v1/search?size=101").status_code, 422)
    check("page zero rejected", client.get("/api/v1/search?page=0").status_code, 422)

    # D7 기본 필터: include_closed=true면 종결물건 포함이라 건수가 같거나 늘어난다
    base = client.get("/api/v1/search").json()["total"]
    closed = client.get("/api/v1/search?include_closed=true").json()["total"]
    check_true("include_closed >= default", closed >= base, "%d < %d" % (closed, base))

    # SQL Injection 시도가 파라미터 바인딩으로 무해하게 처리되는지
    r = client.get("/api/v1/search?sido=' OR 1=1--")
    check("injection attempt safe", r.status_code, 200)
    check("injection returns no rows", r.json()["total"], 0)

    # regions
    r = client.get("/api/v1/search/regions?sido=서울")
    check("regions status", r.status_code, 200)
    check_true("regions returns list", isinstance(r.json()["sigungu"], list))


# ---------------------------------------------------------------------------
# 2-B. 물건종류 어휘 별칭 (docs/BUGS.md #33, 2026-08-11 Sprint 51 신규)
# ---------------------------------------------------------------------------
def test_property_type_aliases():
    """
    검색 UI(PropertyTypeTree)의 물건종류 어휘와 크롤러가 저장하는 법원 원문 어휘가 달라
    69개 중 62개가 항상 0건이던 문제(#33)의 회귀 테스트.

    핵심 불변식은 **가산성(additive)** 이다 — 별칭은 매칭을 넓히기만 하고 좁히지 않는다.
    그래서 "0건이던 게 살아났는가"뿐 아니라 "원래 되던 게 그대로인가"를 함께 고정한다.
    고정 건수를 단언하지 않고 **관계**로만 단언해 데이터가 늘어도 유효하다.
    """
    print("\n--- 2-B. property_type 어휘 별칭 (#33) ---")

    def total(pt=None, **kw):
        params = {"size": "1", "include_closed": "true"}
        if pt is not None:
            params["property_type"] = pt
        params.update(kw)
        qs = "&".join("%s=%s" % (k, v) for k, v in params.items())
        return client.get("/api/v1/search?" + qs).json()["total"]

    everything = total()
    check_true("baseline: 전체 물건이 존재한다", everything > 0, everything)

    # (1) 별칭이 붙은 UI 어휘가 실제로 결과를 돌려준다.
    #
    # **기대값을 코드에서 끌어오지 않는다.** 처음 작성했을 때는
    # `for ui_label, db_tokens in PROPERTY_TYPE_ALIASES.items():`로 돌렸는데,
    # 변이 테스트에서 **별칭 표를 통째로 비우면 루프가 0회 실행되어 아무것도 단언하지 않고
    # 전부 통과**하는 것을 발견했다(검증 대상 자체를 기대값의 출처로 삼은 자기참조 결함).
    # 그래서 여기 목록은 테스트가 직접 들고 있고, 구현 표는 아래에서 "이 목록을 덮는가"로만 본다.
    REQUIRED_ALIASES = [
        ("다세대주택", "다세대"),
        ("오피스텔(주거)", "오피스텔"),
        ("오피스텔(상업)", "오피스텔"),
        ("근린생활시설", "근린시설"),
        ("근린상가", "상가"),
        ("자동차관련", "자동차"),
        ("기타중기", "중기"),
    ]
    for ui_label, db_token in REQUIRED_ALIASES:
        token_total = total(db_token)
        if token_total == 0:
            # 이 카테고리 데이터가 아직 없으면 건수 비교는 의미가 없다.
            # 다만 별칭 매핑 자체가 사라진 것은 아닌지 아래 (1-b)에서 별도로 고정한다.
            continue
        alias_total = total(ui_label)
        check_true("별칭 '%s' -> '%s' 결과가 나온다" % (ui_label, db_token),
                   alias_total > 0, (ui_label, alias_total))
        # 별칭은 원본 토큰이 잡는 행을 전부 포함해야 한다(부분집합이 아니라 상위집합).
        check_true("별칭 '%s' 건수 >= 원본 토큰 '%s' 건수" % (ui_label, db_token),
                   alias_total >= token_total, (alias_total, token_total))

    # (1-b) 데이터가 비어 있는 카테고리까지 포함해 **매핑 표 자체**를 고정한다.
    #       데이터가 다 빠져도 별칭이 조용히 사라지는 것을 막는다.
    from api.v1.search import PROPERTY_TYPE_ALIASES, _property_type_patterns
    for ui_label, db_token in REQUIRED_ALIASES:
        check_true("별칭 표에 '%s' -> '%s'가 있다" % (ui_label, db_token),
                   db_token in PROPERTY_TYPE_ALIASES.get(ui_label, []),
                   (ui_label, PROPERTY_TYPE_ALIASES.get(ui_label)))
        # 확장 결과에는 **원본이 항상 먼저** 포함돼야 한다(가산성의 코드 레벨 보장).
        patterns = _property_type_patterns([ui_label])
        check("확장의 첫 패턴은 원본 '%s'" % ui_label, patterns[0], ui_label)
        check_true("확장에 '%s'가 포함된다" % db_token, db_token in patterns, patterns)

    # (2) 가산성: 별칭이 **없는** 어휘의 결과는 별칭 도입과 무관하게 그대로여야 한다.
    #     원본 토큰으로 직접 조회한 값과 자기 자신을 넣은 값이 같아야 한다(확장이 원본을 삼키지 않음).
    for plain in ("아파트", "연립주택", "임야", "대지", "단독주택", "다가구주택", "기타"):
        check_true("별칭 없는 '%s'는 그대로 동작" % plain, total(plain) > 0, plain)

    # (3) 존재하지 않는 카테고리는 계속 0건이어야 한다 — 별칭이 과도하게 넓어지지 않았는지.
    #     특히 개별 차종은 DB에 구분이 없어 의도적으로 매핑하지 않았다(제품 의미 훼손 방지).
    for absent in ("승용차", "화물차", "덤프트럭", "선박", "광업권", "기숙사"):
        check("과확장 없음: '%s'는 0건" % absent, total(absent), 0)

    # (4) 필터를 걸면 전체보다 작거나 같아야 한다(어떤 어휘도 전체를 초과할 수 없다).
    for label in ("다세대주택", "근린생활시설", "오피스텔(주거)", "근린상가"):
        check_true("'%s' <= 전체" % label, total(label) <= everything, label)

    # (5) 다중 선택(콤마 join)은 합집합이다 — 별칭 확장 후에도 유지되어야 한다.
    a, b = total("임야"), total("다세대주택")
    if a and b:
        both = total("임야,다세대주택")
        check_true("다중 선택은 합집합", max(a, b) <= both <= a + b, (a, b, both))

    # (6) 별칭 확장이 SQL 파라미터 바인딩을 깨지 않는다(주입 방어 유지).
    r = client.get("/api/v1/search?property_type=' OR 1=1--")
    check("별칭 확장 후에도 주입 무해", r.status_code, 200)
    check("주입 결과 0건", r.json()["total"], 0)

    # (7) 토큰 개수 상한 — 클라이언트 입력으로 500을 만들 수 없어야 한다.
    #     실측(Sprint 51): 상한 도입 전에는 2,000개를 보내면 SQLite 표현식 한계로 **500**이 났다.
    #     UI 트리 전체가 69개이므로 상한 100은 정상 사용에 여유가 있다.
    from api.v1.search import MAX_PROPERTY_TYPES
    check_true("상한이 UI 트리 최대(69개)보다 크다", MAX_PROPERTY_TYPES > 69, MAX_PROPERTY_TYPES)
    at_limit = ",".join("가나다%d" % i for i in range(MAX_PROPERTY_TYPES))
    over_limit = ",".join("가나다%d" % i for i in range(MAX_PROPERTY_TYPES + 1))
    check("상한 이내는 허용", client.get("/api/v1/search?property_type=" + at_limit).status_code, 200)
    check("상한 초과는 400", client.get("/api/v1/search?property_type=" + over_limit).status_code, 400)
    # 과거에 500이 나던 크기에서도 500이 아니라 400이어야 한다.
    huge = ",".join("가나다%d" % i for i in range(2000))
    check("대량 입력에도 서버 오류(5xx) 없음", client.get("/api/v1/search?property_type=" + huge).status_code, 400)


# ---------------------------------------------------------------------------
# 3. Detail / Documents
# ---------------------------------------------------------------------------
def test_detail_and_documents():
    print("\n--- 3. detail / documents ---")
    item_id = pick_item_ids(1)[0]

    r = client.get("/api/v1/item/%d" % item_id)
    check("detail status", r.status_code, 200)
    d = r.json()
    for key in ("id", "case_no", "court_name", "documents", "tenants", "rights_summary", "case", "is_favorited"):
        check_true("detail has " + key, key in d)

    # Migration 회귀: 연결된 사건의 법원이 물건의 법원과 같아야 한다
    if d.get("case"):
        check("detail case court matches", d["case"].get("court_code"), d["court_name"])

    check("detail not found", client.get("/api/v1/item/99999999").status_code, 404)

    # 문서: 지원하지 않는 타입은 400, 지원 타입은 200/404(파일 유무에 따라)
    check("document bad type", client.get("/api/v1/item/%d/documents/INVALID" % item_id).status_code, 400)
    get_status = client.get("/api/v1/item/%d/documents/SPEC" % item_id).status_code
    check_true("document known type", get_status in (200, 404))

    # HEAD 프로브 — properties/[id]/page.tsx가 문서 뷰어를 열기 전에 실제로 호출하는
    # 엔드포인트다(docCheckKey). GET/HEAD를 별도 라우트로 분리한 이유(OpenAPI Duplicate
    # Operation ID 회피, docs/CHANGELOG.md Sprint 26)가 유지되는지, 응답 상태코드가 GET과
    # 항상 같은지 여기서 처음으로 자동 검증한다(이전까지 이 라우트는 테스트 0건이었다).
    head_status = client.head("/api/v1/item/%d/documents/SPEC" % item_id).status_code
    check("HEAD status matches GET status", head_status, get_status)
    check("HEAD on bad doc type -> 400",
          client.head("/api/v1/item/%d/documents/INVALID" % item_id).status_code, 400)
    check("HEAD on nonexistent item -> 404",
          client.head("/api/v1/item/99999999/documents/SPEC").status_code, 404)

    # 실제 성공 경로 — 위 "document known type" 검사는 200/404 둘 다 통과로 처리해
    # 어느 쪽이 맞는지, 200일 때 실제로 올바른 파일이 내려오는지는 확인한 적이 없었다
    # (docs/CHANGELOG.md Sprint 35에서 registry 다운로드에 대해 지적한 것과 같은 축의 공백).
    # 크롤러가 이미 수집해 둔 실제 파일이 있으면 그 내용을 검증하고, 없으면 이 테스트가
    # 임시로 만들어 성공 경로를 강제로 왕복시킨 뒤 정확히 그 파일만 지운다.
    from api.v1.documents import get_doc_dir, DOC_TYPE_FILES
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT court_name, case_no, item_no FROM auction_item WHERE id=?", (item_id,)
        ).fetchone()
    finally:
        conn.close()
    filename, media_type = DOC_TYPE_FILES["SPEC"]
    doc_dir = get_doc_dir(row["court_name"], row["case_no"], row["item_no"])
    doc_path = os.path.join(doc_dir, filename)
    created_file = created_dirs = False
    if get_status == 200:
        # 크롤러가 실제로 수집해 둔 파일 — 존재 여부가 아니라 내용까지 확인한다.
        check_true("existing SPEC file is non-empty", os.path.getsize(doc_path) > 0)
    else:
        if not os.path.isdir(doc_dir):
            os.makedirs(doc_dir)
            created_dirs = True
        with open(doc_path, "wb") as f:
            f.write(b"%PDF-1.4 qa-regression-doc-content")
        created_file = True
        forced = client.get("/api/v1/item/%d/documents/SPEC" % item_id)
        check("forced real document download status 200", forced.status_code, 200)
        check("forced real document body matches file", forced.content, b"%PDF-1.4 qa-regression-doc-content")
        forced_head = client.head("/api/v1/item/%d/documents/SPEC" % item_id)
        check("forced real document HEAD also 200", forced_head.status_code, 200)
    if created_file:
        os.remove(doc_path)
    if created_dirs:
        # get_doc_dir()가 만든 court_name/case_no/item_no 3단계 디렉터리를 역순으로 정리한다.
        d = doc_dir
        for _ in range(3):
            try:
                os.rmdir(d)
            except OSError:
                break
            d = os.path.dirname(d)


# ---------------------------------------------------------------------------
# 4. Authentication (인증 필요 라우트 게이트)
# ---------------------------------------------------------------------------
def test_authentication():
    print("\n--- 4. authentication ---")
    # HTTPBearer(auto_error=True)가 Authorization 헤더 자체가 없으면 401을 낸다.
    # (403이 아니라 401이 맞다 — 인증 정보가 없는 것이지 권한이 없는 게 아니므로)
    protected = ["/api/v1/favorites", "/api/v1/recent-items",
                 "/api/v1/search-presets", "/api/v1/registry-requests", "/api/v1/payments"]
    for path in protected:
        check("no token -> 401 " + path, client.get(path).status_code, 401)

    bad = {"Authorization": "Bearer not-a-real-token"}
    check("invalid token -> 401", client.get("/api/v1/favorites", headers=bad).status_code, 401)

    # sub 없는 토큰도 거부되어야 한다
    no_sub = jwt.encode({"foo": "bar"}, SUPABASE_JWT_SECRET, algorithm="HS256")
    check("token without sub -> 401",
          client.get("/api/v1/favorites", headers={"Authorization": "Bearer " + no_sub}).status_code, 401)

    check("valid token -> 200", client.get("/api/v1/favorites", headers=auth_headers()).status_code, 200)

    # 만료 토큰 — python-jose는 exp 클레임이 있으면 기본적으로 검증한다(옵션으로 끄지 않는 한).
    # SUPABASE_JWT_SECRET을 정확히 알아도 만료된 토큰으로는 접근할 수 없어야 한다.
    from datetime import timezone as _tz
    expired = jwt.encode(
        {"sub": TEST_USER, "exp": datetime.now(_tz.utc) - timedelta(hours=1)},
        SUPABASE_JWT_SECRET, algorithm="HS256",
    )
    check("expired token -> 401",
          client.get("/api/v1/favorites", headers={"Authorization": "Bearer " + expired}).status_code, 401)

    # 서명은 형식만 맞고(구조적으로 유효한 HS256 JWT) 실제 비밀키가 다른 토큰 — 위조 시도의
    # 가장 현실적인 형태. "not-a-real-token"(구조 자체가 깨진 문자열)과는 다른 공격면이다.
    wrong_secret = jwt.encode({"sub": TEST_USER}, "attacker-guessed-wrong-secret", algorithm="HS256")
    check("wrong-secret token -> 401",
          client.get("/api/v1/favorites", headers={"Authorization": "Bearer " + wrong_secret}).status_code, 401)

    # alg 혼동 공격: 헤더의 alg를 none으로 바꿔 서명 검증 자체를 우회하려는 고전적 시도.
    # api/auth.py가 jwt.decode(..., algorithms=["HS256"])로 알고리즘을 명시 고정해두었으므로
    # 서버가 이를 거부해야 한다(알고리즘 화이트리스트가 실제로 강제되는지의 회귀 방어).
    try:
        none_alg_token = jwt.encode({"sub": TEST_USER}, "", algorithm="none")
        check("alg=none token -> 401",
              client.get("/api/v1/favorites",
                        headers={"Authorization": "Bearer " + none_alg_token}).status_code, 401)
    except Exception:
        # 라이브러리가 alg=none 인코딩 자체를 막는 버전이면(그 자체로 안전), 서버 왕복 없이도
        # "그 공격 벡터가 애초에 성립하지 않는다"는 것으로 통과 처리한다.
        check_true("alg=none encoding rejected by jose itself (equally safe)", True)


# ---------------------------------------------------------------------------
# 5. Favorite (등록/중복/조회/삭제 + 소유권 격리)
# ---------------------------------------------------------------------------
def test_favorites():
    print("\n--- 5. favorites ---")
    item_id = pick_item_ids(1)[0]
    h = auth_headers()

    r = client.post("/api/v1/favorites", json={"item_id": item_id}, headers=h)
    check("add favorite", r.json()["success"], True)

    r = client.post("/api/v1/favorites", json={"item_id": item_id}, headers=h)
    check("duplicate favorite rejected", r.json()["success"], False)
    # 프론트(FavoriteButton / 상세페이지)가 "이미 원하는 상태"와 "진짜 실패"를 구분하는 근거다.
    # 코드가 바뀌면 하트 아이콘과 에러 메시지가 서로 모순되는 화면이 된다.
    from api.constants import ErrorCode as _EC
    check("duplicate favorite error code", r.json()["error"], _EC.FAVORITE_ALREADY_EXISTS.value)

    r = client.get("/api/v1/favorites", headers=h)
    check_true("favorite listed", any(i["id"] == item_id for i in r.json()["data"]))
    # N+1 제거(JOIN) 후에도 응답 필드가 유지되는지
    check_true("favorite has favorited_at", "favorited_at" in r.json()["data"][0])

    # 검색에서 is_favorited가 true로 반영되는지(로그인 상태)
    r = client.get("/api/v1/search?size=100", headers=h)
    found = [i for i in r.json()["items"] if i["id"] == item_id]
    if found:
        check("search reflects favorite", found[0]["is_favorited"], True)

    # 다른 유저는 이 즐겨찾기를 보면 안 된다
    other_user = "qa-reg-other-" + uuid.uuid4().hex[:6]
    other = client.get("/api/v1/favorites", headers=auth_headers(other_user))
    check("other user isolated", other.json()["data"], [])

    # 남의 즐겨찾기를 지우려는 시도는 실패해야 하고, **실제로 지워지지도 않아야 한다**.
    # success=False만 확인하면 "지워놓고 에러를 반환하는" 구현도 통과한다 —
    # 거부 여부와 부수효과 없음을 함께 단언한다(2026-08-12 Sprint 61).
    other_del = client.delete("/api/v1/favorites/%d" % item_id, headers=auth_headers(other_user))
    check("other user cannot delete my favorite", other_del.json()["success"], False)
    check_true("my favorite survives other user's delete attempt",
               any(i["id"] == item_id for i in client.get("/api/v1/favorites", headers=h).json()["data"]))

    # 개인화 데이터는 요청자 기준이어야 한다 — 같은 물건이라도 다른 로그인 사용자에게는
    # is_favorited=false여야 한다(소유자 true만 검증하면 "전역 true" 구현도 통과한다).
    conn = get_connection()
    try:
        fav_case_no = conn.execute(
            "SELECT case_no FROM auction_item WHERE id=?", (item_id,)).fetchone()["case_no"]
    finally:
        conn.close()
    fav_url = "/api/v1/search?size=100&include_closed=true&case_no=" + fav_case_no
    owner_rows = [i for i in client.get(fav_url, headers=h).json()["items"] if i["id"] == item_id]
    other_rows = [i for i in client.get(fav_url, headers=auth_headers(other_user)).json()["items"]
                  if i["id"] == item_id]
    anon_rows = [i for i in client.get(fav_url).json()["items"] if i["id"] == item_id]
    check("search personalization: owner sees favorited", [r["is_favorited"] for r in owner_rows], [True])
    check("search personalization: other user sees not-favorited",
          [r["is_favorited"] for r in other_rows], [False])
    check("search personalization: anonymous sees not-favorited",
          [r["is_favorited"] for r in anon_rows], [False])

    check("nonexistent item -> 404",
          client.post("/api/v1/favorites", json={"item_id": 99999999}, headers=h).status_code, 404)

    r = client.delete("/api/v1/favorites/%d" % item_id, headers=h)
    check("delete favorite", r.json()["success"], True)
    r = client.delete("/api/v1/favorites/%d" % item_id, headers=h)
    check("delete again -> fail", r.json()["success"], False)
    check("delete again error code", r.json()["error"], _EC.FAVORITE_NOT_FOUND.value)


# ---------------------------------------------------------------------------
# 6. Recent items (상세 조회 시 자동 기록)
# ---------------------------------------------------------------------------
def test_recent_items():
    print("\n--- 6. recent items ---")
    item_id = pick_item_ids(1)[0]
    h = auth_headers()

    client.get("/api/v1/item/%d" % item_id, headers=h)
    r = client.get("/api/v1/recent-items", headers=h)
    check_true("recent recorded", any(i["id"] == item_id for i in r.json()["data"]))

    # 재조회해도 중복 행이 생기지 않고 viewed_at만 갱신되어야 한다
    client.get("/api/v1/item/%d" % item_id, headers=h)
    rows = [i for i in client.get("/api/v1/recent-items", headers=h).json()["data"] if i["id"] == item_id]
    check("no duplicate recent row", len(rows), 1)

    # --- 2026-08-12 Sprint 61: 아래 3개는 그동안 검사가 0건이던 영역이다 ---
    # (1) 최근 조회는 개인화 데이터다 — 다른 사용자에게 새어나가면 안 된다.
    other_user = "qa-reg-recent-other-" + uuid.uuid4().hex[:6]
    other_recent = client.get("/api/v1/recent-items", headers=auth_headers(other_user)).json()["data"]
    check("recent items isolated from other user", other_recent, [])

    # (2) 정렬: viewed_at DESC.
    #
    # 주의 — 여기서 HTTP로 연속 조회해 정렬을 검증하려 하면 안 된다. Windows의
    # datetime.now() 분해능(~1~16ms)보다 요청이 빨라 viewed_at이 **같은 값으로 묶이고**,
    # 그러면 정렬이 tie-break(ri.id)로 결정돼 ORDER BY를 ASC로 뒤집어도 검사가 통과한다
    # (2026-08-12 Sprint 61에 변이 테스트로 실제 확인 — 실데이터에는 동률 0건이라
    # 운영 문제가 아니라 테스트 설계 문제였다).
    # 그래서 viewed_at을 **명시적으로 다른 값**으로 심고 순서를 단언한다.
    ids = pick_item_ids(25)
    conn = get_connection()
    try:
        conn.execute("DELETE FROM recent_items WHERE user_id=?", (TEST_USER,))
        base = datetime.now() - timedelta(days=1)
        for offset, iid in enumerate(ids[:3]):
            conn.execute(
                "INSERT INTO recent_items (user_id, item_id, viewed_at) VALUES (?,?,?)",
                (TEST_USER, iid, (base + timedelta(minutes=offset)).isoformat()))
        conn.commit()
    finally:
        conn.close()
    data = client.get("/api/v1/recent-items", headers=h).json()["data"]
    check("recent items sorted by viewed_at DESC",
          [x["id"] for x in data], [ids[2], ids[1], ids[0]])

    # 다시 조회하면 viewed_at이 갱신되어 맨 앞으로 온다(ON CONFLICT DO UPDATE).
    # 위에서 심은 값이 전부 하루 전이라 지금 시각과 충돌할 수 없다 — 결정적이다.
    client.get("/api/v1/item/%d" % ids[0], headers=h)
    data = client.get("/api/v1/recent-items", headers=h).json()["data"]
    check("re-viewed item moves to front", data[0]["id"], ids[0])
    check("re-view does not duplicate the row", len([x for x in data if x["id"] == ids[0]]), 1)
    check("re-view does not drop the other rows", len(data), 3)

    # (3) 응답은 LIMIT 20으로 잘린다 — 상한이 사라지면 사용자가 볼수록 응답이 무한정 커진다.
    for i in ids:
        client.get("/api/v1/item/%d" % i, headers=h)
    capped = client.get("/api/v1/recent-items", headers=h).json()["data"]
    check("recent items response capped at 20", len(capped), 20)
    check("capped response has no duplicate items", len({x["id"] for x in capped}), 20)


# ---------------------------------------------------------------------------
# 7. Search presets
# ---------------------------------------------------------------------------
def test_search_presets():
    print("\n--- 7. search presets ---")
    h = auth_headers()
    conditions = {"sido": "서울", "min_fail_count": "1"}

    r = client.post("/api/v1/search-presets", json={"name": "QA preset", "conditions": conditions}, headers=h)
    check("create preset", r.json()["success"], True)
    preset_id = r.json()["data"]["id"]

    r = client.get("/api/v1/search-presets", headers=h)
    mine = [p for p in r.json()["data"] if p["id"] == preset_id]
    check("preset listed", len(mine), 1)
    check("conditions round-trip", mine[0]["conditions"], conditions)

    # 다른 유저가 남의 preset을 지울 수 없어야 한다
    preset_other = "qa-reg-other-" + uuid.uuid4().hex[:6]
    other = client.delete("/api/v1/search-presets/%d" % preset_id,
                          headers=auth_headers(preset_other))
    check("other user cannot delete", other.json()["success"], False)
    # 거부만 확인하면 부족하다 — 실제로 남아 있는지, 그리고 남의 목록에 새어나가지
    # 않는지까지 단언한다(2026-08-12 Sprint 61).
    check_true("preset survives other user's delete attempt",
               any(p["id"] == preset_id
                   for p in client.get("/api/v1/search-presets", headers=h).json()["data"]))
    check("other user's preset list does not leak mine",
          [p for p in client.get("/api/v1/search-presets",
                                 headers=auth_headers(preset_other)).json()["data"]
           if p["id"] == preset_id], [])

    check("delete own preset", client.delete("/api/v1/search-presets/%d" % preset_id, headers=h).json()["success"], True)

    # --- 서버측 입력 검증 (프론트 maxLength에 의존하지 않고 API 직접 호출도 막는다) ---
    from api.v1.search_presets import (
        MAX_PRESET_NAME_LENGTH, MAX_PRESET_CONDITIONS_LENGTH, MAX_PRESETS_PER_USER,
    )

    r = client.post("/api/v1/search-presets", json={"name": "   ", "conditions": {}}, headers=h)
    check("blank preset name rejected", r.json()["success"], False)

    r = client.post("/api/v1/search-presets",
                    json={"name": "x" * (MAX_PRESET_NAME_LENGTH + 1), "conditions": {}}, headers=h)
    check("too long preset name rejected", r.json()["success"], False)

    r = client.post("/api/v1/search-presets",
                    json={"name": "big", "conditions": {"sido": "x" * (MAX_PRESET_CONDITIONS_LENGTH + 10)}},
                    headers=h)
    check("oversized conditions rejected", r.json()["success"], False)

    # 이름은 서버에서도 trim된다(프론트 trim에 의존하지 않는다)
    r = client.post("/api/v1/search-presets", json={"name": "  trimmed  ", "conditions": {}}, headers=h)
    check("preset name trimmed by server", r.json()["data"]["name"], "trimmed")
    client.delete("/api/v1/search-presets/%d" % r.json()["data"]["id"], headers=h)

    # 사용자당 저장 개수 상한 — 한도까지 채운 뒤 한 건 더 시도하면 거부되어야 한다.
    conn = get_connection()
    try:
        now = datetime.now().isoformat()
        conn.executemany(
            "INSERT INTO search_presets (user_id, name, conditions, created_at) VALUES (?,?,?,?)",
            [(TEST_USER, "bulk-%d" % i, "{}", now) for i in range(MAX_PRESETS_PER_USER)],
        )
        conn.commit()
    finally:
        conn.close()
    r = client.post("/api/v1/search-presets", json={"name": "over cap", "conditions": {}}, headers=h)
    check("preset count cap enforced", r.json()["success"], False)


# ---------------------------------------------------------------------------
# 8. Payment / Subscription (확정 정책 + 금액 검증)
# ---------------------------------------------------------------------------
def test_payment_and_subscription():
    print("\n--- 8. payment / subscription ---")
    h = auth_headers()

    # 금액 위조는 서버가 거부해야 한다
    r = client.post("/api/v1/payments",
                    json={"payment_type": "SUBSCRIPTION", "plan": "BASIC", "amount": 100}, headers=h)
    check("tampered amount rejected", r.json()["success"], False)

    # 폐기된 옛 플랜명도 거부
    r = client.post("/api/v1/payments",
                    json={"payment_type": "SUBSCRIPTION", "plan": "BETA_EARLYBIRD", "amount": 9900}, headers=h)
    check("legacy plan rejected", r.json()["success"], False)

    r = client.post("/api/v1/payments",
                    json={"payment_type": "SUBSCRIPTION", "plan": "BASIC",
                          "amount": 12900, "billing_cycle": "WEEKLY"}, headers=h)
    check("invalid billing cycle rejected", r.json()["success"], False)

    check("unknown payment type rejected",
          client.post("/api/v1/payments", json={"payment_type": "GIFT", "amount": 1}, headers=h).json()["success"], False)

    # 월 결제(BASIC) 기간 검증은 별도 사용자로 한다 — 하위 테스트(9번 Registry 등)가 이
    # TEST_USER의 PRO 한도(10회)를 전제하므로, TEST_USER는 아래에서 곧바로 PRO 연 구독
    # 하나만 만든다(중복 구독 방지 수정으로 BASIC->PRO를 같은 사용자에 연이어 만들 수 없다).
    monthly_user = TEST_USER + "-monthly"
    hm = auth_headers(monthly_user)
    r = client.post("/api/v1/payments",
                    json={"payment_type": "SUBSCRIPTION", "plan": "BASIC",
                          "amount": resolve_plan_price("BASIC", BILLING_MONTHLY),
                          "billing_cycle": BILLING_MONTHLY}, headers=hm)
    body = r.json()
    check("monthly subscription payment success", body["success"], True)
    check("monthly payment status SUCCESS", body["data"]["payment"]["status"], "SUCCESS")
    check("monthly subscription plan", body["data"]["subscription"]["plan"], "BASIC")
    check("monthly subscription price", body["data"]["subscription"]["price"], 12900)
    check("pg_provider null (mock)", body["data"]["payment"]["pg_provider"], None)
    sub = body["data"]["subscription"]
    days = (datetime.fromisoformat(sub["expires_at"]) - datetime.fromisoformat(sub["started_at"])).days
    check("monthly period ~30d", days, 30)

    # 연 결제(PRO) — 할인가 198,000원이 적용되어야 한다. TEST_USER는 여기서 처음이자
    # 유일하게 구독한다(하위 테스트가 PRO 한도 10회를 전제).
    r = client.post("/api/v1/payments",
                    json={"payment_type": "SUBSCRIPTION", "plan": "PRO",
                          "amount": resolve_plan_price("PRO", BILLING_YEARLY),
                          "billing_cycle": BILLING_YEARLY}, headers=h)
    check("yearly PRO success", r.json()["success"], True)
    check("yearly discounted price", r.json()["data"]["subscription"]["price"], 198000)
    check("fresh subscription has no already_subscribed flag", r.json()["data"].get("already_subscribed"), None)
    sub = r.json()["data"]["subscription"]
    pro_sub_id = sub["id"]
    days = (datetime.fromisoformat(sub["expires_at"]) - datetime.fromisoformat(sub["started_at"])).days
    check("yearly period ~365d", days, 365)

    # 정상가로 결제 시도하면 거부(할인가만 허용)
    r = client.post("/api/v1/payments",
                    json={"payment_type": "SUBSCRIPTION", "plan": "PRO",
                          "amount": 274800, "billing_cycle": BILLING_YEARLY}, headers=h)
    check("list price rejected when discounted", r.json()["success"], False)

    # 중복 구독 방지(멱등성) — 이미 유효한 구독(PRO)이 있는 상태에서 재구독을 시도해도 새
    # subscriptions/payments 행을 만들지 않고 기존 구독을 그대로 돌려줘야 한다(2026-08-09
    # 발견: Sprint 37 Registry 중복신청 결함(#19)과 동일 패턴 — POST /api/v1/payments
    # (SUBSCRIPTION)는 이미 유효한 구독이 있어도 매번 새 subscriptions/payments 행을 만들어
    # 중복 결제를 허용했다. 프론트(properties/[id]/page.tsx)는 이미 유효한 구독이 있으면
    # 구독 UI 자체를 렌더링하지 않으므로("이미 구독 중이면 재구독 불가"가 기존에 이미 전제된
    # 불변식) 승인 없이 수정 가능한 버그로 판단해 즉시 고침. 같은 플랜뿐 아니라 다른 플랜
    # (BASIC) 재구독 시도도 막혀야 한다 — 이미 entitled한 사용자가 도달할 수 있는 유일한
    # 경로는 중복 클릭/재시도뿐이고 프론트에 "플랜 변경" UI 자체가 없다. docs/CHANGELOG.md 참고.
    conn = get_connection()
    try:
        before_sub_count = conn.execute(
            "SELECT COUNT(*) FROM subscriptions WHERE user_id=?", (TEST_USER,)).fetchone()[0]
        before_pay_count = conn.execute(
            "SELECT COUNT(*) FROM payments WHERE user_id=?", (TEST_USER,)).fetchone()[0]
    finally:
        conn.close()
    dup = client.post("/api/v1/payments",
                      json={"payment_type": "SUBSCRIPTION", "plan": "BASIC",
                            "amount": resolve_plan_price("BASIC", BILLING_MONTHLY),
                            "billing_cycle": BILLING_MONTHLY}, headers=h)
    dup_body = dup.json()
    check("duplicate subscribe still returns success", dup_body["success"], True)
    check("duplicate subscribe returns existing (PRO) subscription, not the requested plan",
          dup_body["data"]["subscription"]["plan"], "PRO")
    check("duplicate subscribe returns same subscription id", dup_body["data"]["subscription"]["id"], pro_sub_id)
    check_true("duplicate subscribe flagged", dup_body["data"].get("already_subscribed"))
    check("duplicate subscribe creates no payment", dup_body["data"]["payment"], None)
    conn = get_connection()
    try:
        after_sub_count = conn.execute(
            "SELECT COUNT(*) FROM subscriptions WHERE user_id=?", (TEST_USER,)).fetchone()[0]
        after_pay_count = conn.execute(
            "SELECT COUNT(*) FROM payments WHERE user_id=?", (TEST_USER,)).fetchone()[0]
    finally:
        conn.close()
    check("duplicate subscribe adds no subscriptions row", after_sub_count, before_sub_count)
    check("duplicate subscribe adds no payments row", after_pay_count, before_pay_count)

    # 구독 결제 실패 시 부수효과 없음 + 실패 후 재시도(2026-08-09 Sprint 38) — MockProvider는
    # 항상 SUCCESS라 실패를 자연 재현할 수 없으므로 provider를 일시적으로 실패하도록 교체한다.
    # 실패한 시도는 subscription을 만들지 않아야 하고(entitlement 없음), 이어지는 재시도는
    # 정상 provider로 새 구독을 만들 수 있어야 한다. 전용 사용자를 쓴다(TEST_USER는 이미
    # entitled라 이 경로 자체에 도달하지 못하고 already_subscribed로 막힌다).
    import api.v1.payments as payments_module
    from api.v1.payment_providers import PaymentProvider, ChargeResult, OrderResult

    class _FailingSubProvider(PaymentProvider):
        def create_order(self, payment_type, amount, metadata):
            return OrderResult(order_id="qa-fail-sub-order-" + uuid.uuid4().hex[:8], pg_provider=None)

        def confirm_payment(self, order_id, pg_transaction_id, amount):
            return ChargeResult(status="FAILED", pg_provider=None, pg_transaction_id="qa-fail-sub-txn")

        def verify_payment(self, pg_transaction_id):
            return ChargeResult(status="FAILED", pg_provider=None, pg_transaction_id=pg_transaction_id)

    fail_user = TEST_USER + "-subfail"
    hf = auth_headers(fail_user)
    _orig_provider = payments_module.get_payment_provider
    payments_module.get_payment_provider = lambda: _FailingSubProvider()
    try:
        fail_r = client.post("/api/v1/payments",
                             json={"payment_type": "SUBSCRIPTION", "plan": "BASIC",
                                   "amount": resolve_plan_price("BASIC", BILLING_MONTHLY),
                                   "billing_cycle": BILLING_MONTHLY}, headers=hf)
        fail_body = fail_r.json()
        check("failed subscription payment reports failure", fail_body["success"], False)
        check("failed subscription payment error code", fail_body.get("error"), "PAY_FAILED")
    finally:
        payments_module.get_payment_provider = _orig_provider

    conn = get_connection()
    try:
        sub_count = conn.execute(
            "SELECT COUNT(*) FROM subscriptions WHERE user_id=?", (fail_user,)).fetchone()[0]
        check("no subscription created on failed payment", sub_count, 0)
    finally:
        conn.close()

    retry = client.post("/api/v1/payments",
                        json={"payment_type": "SUBSCRIPTION", "plan": "BASIC",
                              "amount": resolve_plan_price("BASIC", BILLING_MONTHLY),
                              "billing_cycle": BILLING_MONTHLY}, headers=hf)
    retry_body = retry.json()
    check("retry after failed payment succeeds", retry_body["success"], True)
    check("retry creates a subscription", retry_body["data"]["subscription"]["plan"], "BASIC")

    # 결제 내역 조회 + 소유권 격리
    r = client.get("/api/v1/payments", headers=h)
    check_true("payment history", len(r.json()["data"]) >= 1)
    pid = r.json()["data"][0]["id"]
    check("own payment detail", client.get("/api/v1/payments/%d" % pid, headers=h).status_code, 200)
    other = client.get("/api/v1/payments/%d" % pid,
                       headers=auth_headers("qa-reg-other-" + uuid.uuid4().hex[:6]))
    check("other user payment 404", other.status_code, 404)


# ---------------------------------------------------------------------------
# 9. Registry (구독 게이트 + 무료한도 + 초과결제 연결)
# ---------------------------------------------------------------------------
def test_registry():
    print("\n--- 9. registry ---")
    item_ids = pick_item_ids(2)
    h = auth_headers()

    # 8번에서 PRO 구독이 생성됐으므로 한도는 10회
    r = client.post("/api/v1/registry-requests", json={"item_id": item_ids[0]}, headers=h)
    body = r.json()
    check("registry request success", body["success"], True)
    check("first request is free", body["data"]["is_free"], True)
    check("status PENDING", body["data"]["status"], "PENDING")
    check("PRO remaining 9", body["data"]["free_remaining"], 9)

    # 중복 신청 방지(멱등성) — 같은 물건에 다시 신청해도 새 행을 만들거나 무료횟수를
    # 추가로 소모하지 않고 기존 신청을 그대로 돌려줘야 한다(2026-08-09 발견: 이 검사가
    # 없던 시절엔 반복 호출마다 별도 행이 생기고 매번 무료횟수가 소모됐다 — 재현 확인 후
    # 승인 없이 수정 가능한 버그로 판단해 즉시 고침. `docs/CHANGELOG.md` Sprint 37 참고).
    dup = client.post("/api/v1/registry-requests", json={"item_id": item_ids[0]}, headers=h)
    dup_body = dup.json()
    check("duplicate request returns same id", dup_body["data"]["id"], body["data"]["id"])
    check_true("duplicate request flagged", dup_body["data"].get("already_requested"))
    check("duplicate request does not consume another free credit",
          dup_body["data"]["free_remaining"], 9)
    conn = get_connection()
    try:
        dup_count = conn.execute(
            "SELECT COUNT(*) FROM registry_requests WHERE user_id=? AND item_id=?",
            (TEST_USER, item_ids[0]),
        ).fetchone()[0]
        check("still exactly one registry_requests row for this item", dup_count, 1)
        usage_count = conn.execute(
            "SELECT COUNT(*) FROM registry_usage WHERE user_id=? AND item_id=? AND is_free=1",
            (TEST_USER, item_ids[0]),
        ).fetchone()[0]
        check("still exactly one free usage row for this item", usage_count, 1)
    finally:
        conn.close()

    # 종결 상태(COMPLETED/FAILED)는 재신청을 막지 않아야 한다 — 발급 실패 후 재시도,
    # 재발급 요청 같은 정당한 흐름을 이 중복 방지 로직이 오히려 막으면 안 된다.
    # 이 서브 검사는 실제로 무료횟수를 하나 더 소모시키므로(재시도도 정당한 신규 신청이라
    # 당연함), 뒤이은 9번(초과결제 흐름)의 "이미 1건 사용" 전제가 깨지지 않도록 검증
    # 후 원래 상태(신청 1건, 무료 1건 소모)로 정확히 되돌린다.
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE registry_requests SET status='FAILED', reason='qa-regression-test' WHERE id=?",
            (body["data"]["id"],),
        )
        conn.commit()
    finally:
        conn.close()
    retry = client.post("/api/v1/registry-requests", json={"item_id": item_ids[0]}, headers=h)
    retry_body = retry.json()
    check_true("retry after FAILED is allowed (new request, not blocked)",
               retry_body["data"]["id"] != body["data"]["id"])
    check_true("retry after FAILED not flagged as duplicate",
               not retry_body["data"].get("already_requested"))

    conn = get_connection()
    try:
        retry_usage_id = conn.execute(
            "SELECT usage_id FROM registry_requests WHERE id=?", (retry_body["data"]["id"],)
        ).fetchone()["usage_id"]
        # FK가 런타임에 강제되므로 자식(registry_requests, registry_credit_logs) ->
        # 부모(registry_usage) 순서로 지운다 — log_credit_event()가 USAGE 사유로
        # registry_credit_logs.related_usage_id도 함께 남기므로 그것도 지워야 한다.
        conn.execute("DELETE FROM registry_requests WHERE id=?", (retry_body["data"]["id"],))
        if retry_usage_id is not None:
            conn.execute("DELETE FROM registry_credit_logs WHERE related_usage_id=?", (retry_usage_id,))
            conn.execute("DELETE FROM registry_usage WHERE id=?", (retry_usage_id,))
        conn.execute(
            "UPDATE registry_requests SET status='PENDING', reason=NULL WHERE id=?",
            (body["data"]["id"],),
        )
        conn.commit()
        restored_usage = conn.execute(
            "SELECT COUNT(*) FROM registry_usage WHERE user_id=? AND item_id=? AND is_free=1",
            (TEST_USER, item_ids[0]),
        ).fetchone()[0]
        check("free usage count restored to 1 after retry sub-test", restored_usage, 1)
    finally:
        conn.close()

    check("nonexistent item -> 404",
          client.post("/api/v1/registry-requests", json={"item_id": 99999999}, headers=h).status_code, 404)

    r = client.get("/api/v1/registry-requests", headers=h)
    check_true("registry listed", len(r.json()["data"]) >= 1)
    req_id = r.json()["data"][0]["id"]
    check_true("reason field exposed", "reason" in r.json()["data"][0])

    # 소유권 격리
    other_h = auth_headers("qa-reg-other-" + uuid.uuid4().hex[:6])
    check("other user cannot read request",
          client.get("/api/v1/registry-requests/%d" % req_id, headers=other_h).status_code, 404)
    check("other user cannot download",
          client.get("/api/v1/registry-requests/%d/download" % req_id, headers=other_h).status_code, 404)

    # 미완료 상태 다운로드는 거짓 성공 없이 실패 메시지를 반환.
    # ★ success=False만 보면 안 된다 (2026-08-11 Sprint 56): 상태 검사를 통째로 없애는
    #   변이를 넣었더니 doc_url이 NULL이라 다른 오류(REGISTRY_DOCUMENT_NOT_FOUND)로 떨어져
    #   테스트가 그대로 통과했다. **어느 가드가 막았는지**까지 고정해야 가드 제거가 검출된다.
    r = client.get("/api/v1/registry-requests/%d/download" % req_id, headers=h)
    body = r.json()
    check("incomplete download not a file", body["success"], False)
    check("incomplete download blocked by status gate", body.get("error"), "REGISTRY_NOT_COMPLETED")
    check_true("error message names the actual status",
               "PENDING" in str(body.get("message", "")) or "PROCESSING" in str(body.get("message", "")),
               body.get("message"))

    # 실제 성공 다운로드 — 지금까지 이 파일은 "COMPLETED인데 파일이 없는" 방어 경로만
    # 검증했고(위 admin 섹션의 doc_url이 항상 존재하지 않는 더미 파일이었다), 베타 사용자
    # 여정의 마지막 단계인 "실제로 파일이 내려오는" 성공 경로는 테스트 0건이었다.
    import os as _os
    from api.v1.registry import REGISTRY_DOCUMENT_ROOT
    _os.makedirs(REGISTRY_DOCUMENT_ROOT, exist_ok=True)
    real_filename = "qa-regression-real-file.pdf"
    real_path = _os.path.join(REGISTRY_DOCUMENT_ROOT, real_filename)
    file_bytes = b"%PDF-1.4 qa-regression-test-content"
    with open(real_path, "wb") as f:
        f.write(file_bytes)
    try:
        conn = get_connection()
        try:
            conn.execute(
                "UPDATE registry_requests SET status='COMPLETED', doc_url=?, completed_at=? WHERE id=?",
                (real_filename, datetime.now().isoformat(), req_id),
            )
            conn.commit()
        finally:
            conn.close()

        dl = client.get("/api/v1/registry-requests/%d/download" % req_id, headers=h)
        check("real download status 200", dl.status_code, 200)
        check("real download body matches file", dl.content, file_bytes)
        check_true("content-disposition exposes filename",
                   real_filename in dl.headers.get("content-disposition", ""))

        # 경로 탐색 방어 — commonpath 검사가 실제로 막는지 지금까지 검증된 적이 없었다.
        # doc_url은 DB 값이라 클라이언트가 직접 조작할 수 없지만, 방어 로직 자체가
        # 여전히 정확히 동작하는지는 별도로 확인할 가치가 있다(회귀 시 무음 실패 위험).
        conn = get_connection()
        try:
            conn.execute(
                "UPDATE registry_requests SET status='COMPLETED', doc_url=? WHERE id=?",
                ("../../../../etc/passwd", req_id),
            )
            conn.commit()
        finally:
            conn.close()
        traversal = client.get("/api/v1/registry-requests/%d/download" % req_id, headers=h)
        check("path traversal blocked -> 404", traversal.status_code, 404)
    finally:
        _os.remove(real_path)
        conn = get_connection()
        try:
            conn.execute(
                "UPDATE registry_requests SET status='PENDING', doc_url=NULL, completed_at=NULL WHERE id=?",
                (req_id,),
            )
            conn.commit()
        finally:
            conn.close()

    # 구독 없는 유저는 신청 자체가 막힌다
    r = client.post("/api/v1/registry-requests", json={"item_id": item_ids[0]}, headers=other_h)
    check("no subscription blocked", r.json()["message"], "구독이 필요합니다")

    # 결제 대상이 없는데 초과결제를 시도하면 거부(짝 없는 payment 방지)
    r = client.post("/api/v1/payments",
                    json={"payment_type": "OVERAGE_USAGE", "amount": OVERAGE_FEE}, headers=h)
    check("overage without target rejected", r.json()["success"], False)

    r = client.post("/api/v1/payments",
                    json={"payment_type": "OVERAGE_USAGE", "amount": 1}, headers=h)
    check("overage wrong amount rejected", r.json()["success"], False)


# ---------------------------------------------------------------------------
# 10. Registry 무료한도 초과 -> PAYMENT_REQUIRED -> 초과결제 연결
# ---------------------------------------------------------------------------
def test_registry_overage_flow():
    print("\n--- 10. registry overage flow ---")
    h = auth_headers()
    ids = pick_item_ids(12)

    # PRO 한도(10) 소진: 앞서 1건 사용했으므로 9건 더 신청
    statuses = []
    for i in ids[1:11]:
        statuses.append(client.post("/api/v1/registry-requests", json={"item_id": i}, headers=h).json()["data"]["status"])
    check("10th request still PENDING", statuses[8], "PENDING")

    # 11번째는 한도 초과 -> PAYMENT_REQUIRED
    over = client.post("/api/v1/registry-requests", json={"item_id": ids[11]}, headers=h).json()["data"]
    check("over limit -> PAYMENT_REQUIRED", over["status"], "PAYMENT_REQUIRED")
    check("over limit not free", over["is_free"], False)
    check("charged amount", over["charged_amount"], OVERAGE_FEE)

    # 결제 실패 시 부수효과 없음 + 실패 후 재시도(2026-08-09 Sprint 38) — MockProvider는 항상
    # SUCCESS라 실패를 자연 재현할 수 없으므로 provider를 일시적으로 실패하도록 교체한다.
    # 실패한 시도는 등기부 신청을 PENDING으로 전환하지 않고(payment_id 그대로 NULL) 그대로
    # 재시도 가능한 상태로 남아야 한다.
    import api.v1.payments as payments_module
    from api.v1.payment_providers import PaymentProvider, ChargeResult, OrderResult

    class _FailingProvider(PaymentProvider):
        def create_order(self, payment_type, amount, metadata):
            return OrderResult(order_id="qa-fail-order-" + uuid.uuid4().hex[:8], pg_provider=None)

        def confirm_payment(self, order_id, pg_transaction_id, amount):
            return ChargeResult(status="FAILED", pg_provider=None, pg_transaction_id="qa-fail-txn")

        def verify_payment(self, pg_transaction_id):
            return ChargeResult(status="FAILED", pg_provider=None, pg_transaction_id=pg_transaction_id)

    _orig_provider = payments_module.get_payment_provider
    payments_module.get_payment_provider = lambda: _FailingProvider()
    try:
        fail_r = client.post("/api/v1/payments",
                             json={"payment_type": "OVERAGE_USAGE", "amount": OVERAGE_FEE}, headers=h)
        fail_body = fail_r.json()
        check("failed overage payment reports failure", fail_body["success"], False)
        check("failed overage payment error code", fail_body.get("error"), "PAY_FAILED")
    finally:
        payments_module.get_payment_provider = _orig_provider

    conn = get_connection()
    try:
        still_unclaimed = conn.execute(
            "SELECT status, payment_id FROM registry_requests WHERE id=?", (over["id"],)
        ).fetchone()
        check("target request still PAYMENT_REQUIRED after failed payment", still_unclaimed["status"], "PAYMENT_REQUIRED")
        check("target request still unlinked after failed payment", still_unclaimed["payment_id"], None)
    finally:
        conn.close()

    # --- 미결제 신청을 관리자가 완료 처리할 수 없다 (2026-08-11 Sprint 56 신설) -------
    # 이것이 초과 과금의 **실질적 우회 경로**다. PAYMENT_REQUIRED는 "돈을 아직 안 냈다"는
    # 뜻이고, COMPLETED가 되면 다운로드 게이트(status==COMPLETED)가 열려 등기부를 공짜로
    # 받게 된다. `ALLOWED_TRANSITIONS`에 PAYMENT_REQUIRED 키가 아예 없어 막혀 있지만,
    # 그 사실을 고정하는 회귀가 없었다 — 키를 하나 추가하는 것만으로 조용히 뚫린다.
    ah_guard = {"X-Admin-Key": TEST_ADMIN_KEY}
    for target in ("COMPLETED", "PROCESSING", "FAILED"):
        body = {"status": target}
        if target == "COMPLETED":
            body["doc_url"] = "qa-should-not-be-created.pdf"
        if target == "FAILED":
            body["reason"] = "qa"
        rr = client.patch("/api/v1/admin/registry-requests/%d" % over["id"], json=body, headers=ah_guard)
        check("PAYMENT_REQUIRED -> %s 는 거부" % target, rr.status_code, 400)

    conn = get_connection()
    try:
        after = conn.execute(
            "SELECT status, doc_url, completed_at FROM registry_requests WHERE id=?", (over["id"],)
        ).fetchone()
        check("거부된 전이 후에도 상태 불변", after["status"], "PAYMENT_REQUIRED")
        check("거부된 전이가 doc_url을 남기지 않는다", after["doc_url"], None)
        check("거부된 전이가 completed_at을 남기지 않는다", after["completed_at"], None)
    finally:
        conn.close()

    # 그 상태로 다운로드도 당연히 막혀야 한다(가드가 두 겹인지 확인).
    # 여기서도 **어느 가드가 막았는지**를 고정한다 — success=False만 보면 상태 검사를
    # 없애도 doc_url NULL 때문에 다른 오류로 떨어져 통과해 버린다.
    dl = client.get("/api/v1/registry-requests/%d/download" % over["id"], headers=h).json()
    check("미결제 신청은 다운로드 불가", dl["success"], False)
    check("미결제 다운로드는 상태 게이트가 막는다", dl.get("error"), "REGISTRY_NOT_COMPLETED")
    check_true("오류 메시지가 PAYMENT_REQUIRED임을 밝힌다",
               "PAYMENT_REQUIRED" in str(dl.get("message", "")), dl.get("message"))

    # 초과분 결제(실패 후 재시도, 정상 provider) -> 해당 신청이 PENDING으로 자동 전환
    r = client.post("/api/v1/payments",
                    json={"payment_type": "OVERAGE_USAGE", "amount": OVERAGE_FEE}, headers=h)
    check("overage payment success", r.json()["success"], True)
    linked = r.json()["data"]["registry_request"]
    check("linked request PENDING", linked["status"], "PENDING")
    check_true("payment_id linked", linked["payment_id"] is not None)


# ---------------------------------------------------------------------------
# 11. Admin (X-Admin-Key 인증 + 상태 전이 규칙)
# ---------------------------------------------------------------------------
def test_admin():
    print("\n--- 11. admin ---")
    check("no admin key -> 403", client.get("/api/v1/admin/registry-requests").status_code, 403)
    check("wrong admin key -> 403",
          client.get("/api/v1/admin/registry-requests", headers={"X-Admin-Key": "wrong"}).status_code, 403)

    ah = {"X-Admin-Key": TEST_ADMIN_KEY}
    r = client.get("/api/v1/admin/registry-requests", headers=ah)
    check("admin list status", r.status_code, 200)
    check_true("admin list has items", "items" in r.json()["data"])

    check("admin invalid status filter",
          client.get("/api/v1/admin/registry-requests?status=BOGUS", headers=ah).status_code, 400)

    # 내 테스트 유저의 PENDING 건으로 상태 전이 규칙 검증
    r = client.get("/api/v1/admin/registry-requests?status=PENDING&user_id=%s" % TEST_USER, headers=ah)
    items = r.json()["data"]["items"]
    check_true("admin can filter by user", len(items) >= 1)
    rid = items[0]["id"]

    # PENDING -> COMPLETED 직행은 금지
    check("PENDING->COMPLETED rejected",
          client.patch("/api/v1/admin/registry-requests/%d" % rid,
                       json={"status": "COMPLETED", "doc_url": "x.pdf"}, headers=ah).status_code, 400)
    # FAILED에는 reason 필수
    check("FAILED without reason rejected",
          client.patch("/api/v1/admin/registry-requests/%d" % rid,
                       json={"status": "FAILED"}, headers=ah).status_code, 400)

    # PENDING -> PROCESSING (허용)
    r = client.patch("/api/v1/admin/registry-requests/%d" % rid, json={"status": "PROCESSING"}, headers=ah)
    check("PENDING->PROCESSING ok", r.json()["data"]["status"], "PROCESSING")

    # COMPLETED에는 doc_url 필수
    check("COMPLETED without doc_url rejected",
          client.patch("/api/v1/admin/registry-requests/%d" % rid,
                       json={"status": "COMPLETED"}, headers=ah).status_code, 400)

    # PROCESSING -> COMPLETED (doc_url 포함)
    r = client.patch("/api/v1/admin/registry-requests/%d" % rid,
                     json={"status": "COMPLETED", "doc_url": "qa-regression-not-a-real-file.pdf"}, headers=ah)
    check("PROCESSING->COMPLETED ok", r.json()["data"]["status"], "COMPLETED")
    check_true("completed_at recorded", r.json()["data"]["completed_at"] is not None)

    # 종결 상태에서 추가 전이 금지
    check("COMPLETED->FAILED rejected",
          client.patch("/api/v1/admin/registry-requests/%d" % rid,
                       json={"status": "FAILED", "reason": "x"}, headers=ah).status_code, 400)

    check("admin 404 for unknown id",
          client.patch("/api/v1/admin/registry-requests/99999999",
                       json={"status": "PROCESSING"}, headers=ah).status_code, 404)

    # COMPLETED이지만 실제 파일이 없으면 거짓 성공을 반환하지 않아야 한다
    r = client.get("/api/v1/registry-requests/%d/download" % rid, headers=auth_headers())
    check_true("missing file not a false success",
               r.status_code == 404 or r.json().get("success") is False)


# ---------------------------------------------------------------------------
# 12. Payment Provider 레지스트리 (PG사 = KG이니시스 확정 기준)
#     실제 PG API는 호출하지 않는다 — 어떤 Provider가 선택되는지와, 미구현 Provider가
#     "조용히 성공"하지 않고 반드시 실패하는지만 확인한다.
# ---------------------------------------------------------------------------
def test_payment_providers():
    print("\n--- 12. payment providers ---")
    import api.v1.payment_providers as pp

    saved = os.environ.get("PAYMENT_PROVIDER")
    try:
        os.environ.pop("PAYMENT_PROVIDER", None)
        check("unset -> MockProvider", type(pp.get_payment_provider()).__name__, "MockProvider")

        os.environ["PAYMENT_PROVIDER"] = "kginicis"
        provider = pp.get_payment_provider()
        check("kginicis -> KGInicisProvider", type(provider).__name__, "KGInicisProvider")

        # Interface v2 6개 메서드 전부 미구현이어야 한다(자리 구현). 하나라도 조용히
        # 값을 돌려주면 실연동 전에 결제가 성공한 것처럼 보일 수 있어 회귀로 잡는다.
        calls = [
            ("charge", lambda p: p.charge("SUBSCRIPTION", 12900, None)),
            ("create_order", lambda p: p.create_order("SUBSCRIPTION", 12900, None)),
            ("confirm_payment", lambda p: p.confirm_payment("o", "t", 12900)),
            ("cancel_payment", lambda p: p.cancel_payment("t")),
            ("verify_payment", lambda p: p.verify_payment("t")),
            ("handle_webhook", lambda p: p.handle_webhook({})),
        ]
        for name, call in calls:
            try:
                call(provider)
                check_true("kginicis %s not implemented" % name, False, "실패하지 않고 값을 반환함")
            except NotImplementedError:
                check_true("kginicis %s not implemented" % name, True)

        # 폐기 예정 후보도 여전히 선택은 되지만(하위호환) 호출 시 실패해야 한다
        for legacy in ("toss", "portone"):
            os.environ["PAYMENT_PROVIDER"] = legacy
            p = pp.get_payment_provider()
            try:
                p.charge("SUBSCRIPTION", 12900, None)
                check_true("%s deprecated still fails" % legacy, False, "실패하지 않음")
            except NotImplementedError:
                check_true("%s deprecated still fails" % legacy, True)

        os.environ["PAYMENT_PROVIDER"] = "nope"
        try:
            pp.get_payment_provider()
            check_true("unknown provider rejected", False, "예외가 발생하지 않음")
        except ValueError:
            check_true("unknown provider rejected", True)
    finally:
        if saved is None:
            os.environ.pop("PAYMENT_PROVIDER", None)
        else:
            os.environ["PAYMENT_PROVIDER"] = saved

    # MockProvider가 여전히 기본 경로임을 확인(실제 결제 흐름은 8~10번에서 검증됨)
    check("restored default is mock", type(pp.get_payment_provider()).__name__, "MockProvider")


# ---------------------------------------------------------------------------
# 13. 정렬 결정성 — created_at/requested_at 동률에도 순서가 흔들리지 않아야 한다.
#     offset 페이지네이션에서 같은 행이 두 페이지에 나오거나 빠지는 것을 막는다.
# ---------------------------------------------------------------------------
def test_deterministic_ordering():
    print("\n--- 13. deterministic ordering ---")
    h = auth_headers()
    item_id = pick_item_ids(1)[0]
    same_ts = "2026-01-02T03:04:05.000000"

    conn = get_connection()
    try:
        # 완전히 같은 타임스탬프를 가진 행 3개를 직접 넣는다(Windows 시계 분해능상 실제로 발생 가능).
        conn.executemany(
            "INSERT INTO registry_requests (user_id, item_id, status, requested_at) VALUES (?,?,?,?)",
            [(TEST_USER, item_id, "PENDING", same_ts) for _ in range(3)],
        )
        conn.executemany(
            "INSERT INTO search_presets (user_id, name, conditions, created_at) VALUES (?,?,?,?)",
            [(TEST_USER, "tie-%d" % i, "{}", same_ts) for i in range(3)],
        )
        conn.commit()
    finally:
        conn.close()

    def ids_of(path):
        return [row["id"] for row in client.get(path, headers=h).json()["data"]]

    check_true("registry list order stable across calls",
               ids_of("/api/v1/registry-requests") == ids_of("/api/v1/registry-requests"))
    check_true("preset list order stable across calls",
               ids_of("/api/v1/search-presets") == ids_of("/api/v1/search-presets"))

    # 동률 구간은 id 내림차순으로 전순서가 잡혀 있어야 한다
    tie_ids = [r["id"] for r in client.get("/api/v1/registry-requests", headers=h).json()["data"]
               if r["requested_at"] == same_ts]
    check_true("tie group sorted by id desc", tie_ids == sorted(tie_ids, reverse=True), tie_ids)


# ---------------------------------------------------------------------------
# 14. 구독 플랜 해석 — 같은 시각에 만들어진 두 구독 중 나중 것이 이겨야 한다.
#     (플랜 업그레이드 직후 등기부 한도가 옛 플랜으로 계산되던 버그의 회귀 방지)
# ---------------------------------------------------------------------------
def test_subscription_plan_tiebreak():
    print("\n--- 14. subscription plan tie-break ---")
    from api.v1.registry import get_user_free_limit

    user = TEST_USER + "-tie"
    same_ts = "2026-01-02T03:04:05.000000"
    expires = (datetime.now() + timedelta(days=365)).isoformat()
    now = datetime.now().isoformat()

    conn = get_connection()
    try:
        # BASIC(5회) 먼저, PRO(10회) 나중 — started_at 문자열은 완전히 동일하다.
        for plan in ("BASIC", "PRO"):
            conn.execute(
                "INSERT INTO subscriptions (user_id, plan, price, status, started_at, expires_at, created_at, updated_at)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (user, plan, 1, "ACTIVE", same_ts, expires, now, now),
            )
        conn.commit()
        check("upgraded plan wins on tie", get_user_free_limit(conn, user), 10)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 15. Plan API — 서버가 가격/플랜의 단일 Source of Truth인지 (CTO 승인 2번)
#     프론트는 더 이상 가격을 갖지 않는다. 따라서 (1) 응답이 PLAN_CATALOG와 일치하고
#     (2) 프론트에 가격 하드코딩이 되살아나지 않았는지 둘 다 확인한다.
# ---------------------------------------------------------------------------
DETAIL_PAGE_SOURCE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "src", "app", "properties", "[id]", "page.tsx"
)


def test_plans_api():
    print("\n--- 15. plans api (single source of truth) ---")
    from api.v1.payments import PLAN_CATALOG
    from api.v1.registry import OVERAGE_FEE

    r = client.get("/api/v1/plans")
    check("plans status", r.status_code, 200)
    body = r.json()
    check("plans envelope", set(body), ENVELOPE_KEYS)
    data = body["data"]
    check("plans count", len(data["plans"]), len(PLAN_CATALOG))
    check("overage_fee matches server constant", data["overage_fee"], OVERAGE_FEE)
    check("billing cycles", sorted(data["billing_cycles"]), sorted([BILLING_MONTHLY, BILLING_YEARLY]))

    for entry in data["plans"]:
        plan = entry["plan"]
        server = PLAN_CATALOG[plan]
        check("%s label" % plan, entry["label"], server["label"])
        check("%s registry limit" % plan,
              entry["registry_monthly_limit"], server["registry_monthly_limit"])
        for cycle in (BILLING_MONTHLY, BILLING_YEARLY):
            price = entry["prices"][cycle]
            check("%s/%s list_price" % (plan, cycle),
                  price["list_price"], server["prices"][cycle]["list_price"])
            # 표시 금액과 실제 청구 금액이 같은 함수에서 나오는지 — 어긋나면 결제가 거절된다
            check("%s/%s charged price" % (plan, cycle),
                  price["price"], resolve_plan_price(plan, cycle))
            check("%s/%s discounted flag" % (plan, cycle),
                  price["discounted"], price["price"] < price["list_price"])

    # 응답 금액 그대로 결제하면 반드시 통과해야 한다(프론트가 하는 것과 동일한 경로)
    pro_yearly = [p for p in data["plans"] if p["plan"] == "PRO"][0]["prices"][BILLING_YEARLY]
    r = client.post("/api/v1/payments",
                    json={"payment_type": "SUBSCRIPTION", "plan": "PRO",
                          "amount": pro_yearly["price"], "billing_cycle": BILLING_YEARLY},
                    headers=auth_headers())
    check("catalog price is accepted by payment", r.json()["success"], True)

    # 프론트에 가격 하드코딩이 되살아나지 않았는지 — 되살아나면 다시 드리프트가 생긴다
    if os.path.exists(DETAIL_PAGE_SOURCE):
        with open(DETAIL_PAGE_SOURCE, encoding="utf-8") as f:
            source = f.read()
        for literal in ("12900", "22900", "154800", "274800", "198000"):
            check_true("no hardcoded price %s in detail page" % literal,
                       literal not in source, "프론트에 가격이 다시 하드코딩됨")
        check_true("no PLAN_OPTIONS const", "const PLAN_OPTIONS" not in source)


# ---------------------------------------------------------------------------
# 16. API 표면(surface) 고정 — 라우트가 조용히 사라지거나 늘어나는 것을 잡는다.
#     프론트가 의존하는 엔드포인트가 리팩터링 중에 사라지면 배포 후에야 드러난다.
# ---------------------------------------------------------------------------
EXPECTED_ENDPOINTS = {
    ("GET", "/"),
    ("GET", "/api/v1/stats"),
    ("GET", "/api/v1/document-stats"),
    ("GET", "/api/v1/search"),
    ("GET", "/api/v1/search/regions"),
    ("GET", "/api/v1/item/{item_id}"),
    ("GET", "/api/v1/item/{item_id}/documents/{doc_type}"),
    ("GET", "/api/v1/favorites"),
    ("POST", "/api/v1/favorites"),
    ("DELETE", "/api/v1/favorites/{item_id}"),
    ("GET", "/api/v1/recent-items"),
    ("GET", "/api/v1/search-presets"),
    ("POST", "/api/v1/search-presets"),
    ("DELETE", "/api/v1/search-presets/{preset_id}"),
    ("GET", "/api/v1/registry-requests"),
    ("POST", "/api/v1/registry-requests"),
    ("GET", "/api/v1/registry-requests/{request_id}"),
    ("GET", "/api/v1/registry-requests/{request_id}/download"),
    ("GET", "/api/v1/payments"),
    ("POST", "/api/v1/payments"),
    ("GET", "/api/v1/payments/{payment_id}"),
    ("GET", "/api/v1/admin/registry-requests"),
    ("PATCH", "/api/v1/admin/registry-requests/{request_id}"),
    ("GET", "/api/v1/plans"),
    ("GET", "/api/v1/payments/{payment_id}/logs"),
    ("GET", "/api/v1/admin/registry-credits/{user_id}"),
    ("POST", "/api/v1/admin/registry-credits"),
    ("GET", "/api/v1/admin/registry/requests"),
    ("GET", "/api/v1/admin/registry/credit-logs/{user_id}"),
    ("GET", "/api/v1/admin/users"),
    ("GET", "/api/v1/admin/payments"),
    ("GET", "/api/v1/admin/payments/{payment_id}/logs"),
    ("GET", "/api/v1/admin/subscriptions"),
    ("PATCH", "/api/v1/admin/subscriptions/{subscription_id}"),
    ("GET", "/api/v1/admin/audit-logs"),
    # 2026-08-11 Sprint 52 신설 — 결제 도메인 내부 완성(환불 / Webhook 수신).
    # 실제 PG 호출은 없다(MockProvider). 두 경로 모두 이 파일 §29에서 검증한다.
    ("POST", "/api/v1/admin/payments/{payment_id}/refund"),
    ("POST", "/api/v1/payments/webhook/{provider_name}"),
    # 사용자가 자기 구독을 볼 수 있는 유일한 경로. 마이페이지 스펙과 무관하게 필요하다.
    ("GET", "/api/v1/subscriptions/me"),
    # 2026-08-11 Sprint 53 — Webhook 운영 도구(조회/상세/재처리). 실제 PG 호출 없음.
    ("GET", "/api/v1/admin/payments/webhooks"),
    ("GET", "/api/v1/admin/payments/webhooks/{webhook_id}"),
    ("POST", "/api/v1/admin/payments/webhooks/{webhook_id}/reprocess"),
}


def test_api_surface():
    print("\n--- 16. api surface ---")
    import warnings

    # OpenAPI 생성 시 경고가 나오면 안 된다. 예전에는 documents.py의 GET/HEAD 겸용 라우트가
    # 같은 operationId를 만들어 매번 "Duplicate Operation ID" 경고가 났다(클라이언트 생성도 깨짐).
    api_server.app.openapi_schema = None  # 캐시된 스키마를 비우고 새로 생성
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        spec = api_server.app.openapi()
    dup = [str(w.message) for w in caught if "Duplicate Operation ID" in str(w.message)]
    check_true("no duplicate operationId", not dup, dup)

    actual = {
        (method.upper(), path)
        for path, ops in spec["paths"].items()
        for method in ops
    }
    missing = sorted(EXPECTED_ENDPOINTS - actual)
    added = sorted(actual - EXPECTED_ENDPOINTS)
    check_true("no endpoint removed", not missing, missing)
    check_true("no undeclared endpoint added", not added, added)

    # 프론트가 문서 뷰어를 열기 전에 쓰는 HEAD 프로브는 스키마에 없어도 동작해야 한다.
    item_id = pick_item_ids(1)[0]
    path = "/api/v1/item/%d/documents/SPEC" % item_id
    check("HEAD probe matches GET status",
          client.request("HEAD", path).status_code, client.get(path).status_code)
    check("HEAD rejects unknown doc_type",
          client.request("HEAD", "/api/v1/item/%d/documents/BOGUS" % item_id).status_code, 400)


# ---------------------------------------------------------------------------
# 17. 공통 응답 envelope — 인증 필요 라우트는 {success, data, message} 형태를 유지해야 한다.
#     (docs/backend.md "절대 변경하면 안 되는 것"에 명시된 계약)
# ---------------------------------------------------------------------------
def test_response_envelope():
    print("\n--- 17. response envelope ---")
    h = auth_headers()
    for path in ("/api/v1/favorites", "/api/v1/recent-items", "/api/v1/search-presets",
                 "/api/v1/registry-requests", "/api/v1/payments"):
        body = client.get(path, headers=h).json()
        check_true("envelope keys %s" % path, set(body) == ENVELOPE_KEYS, sorted(body))
        check_true("envelope success is bool %s" % path, isinstance(body["success"], bool))
        # 성공 응답에는 error가 없어야 한다
        check_true("success has no error %s" % path, body["error"] is None, body["error"])
        # 기존 클라이언트가 읽는 message 필드는 계속 존재해야 한다(Breaking Change 방지)
        check_true("message key preserved %s" % path, "message" in body)

    # 실패 응답에는 도메인 Error Code가 붙어야 한다
    from api.constants import ErrorCode
    body = client.post("/api/v1/payments",
                       json={"payment_type": "GIFT", "amount": 1}, headers=h).json()
    check("fail carries error code", body["error"], ErrorCode.PAY_INVALID_TYPE.value)
    check("fail success is False", body["success"], False)
    check_true("fail keeps message", isinstance(body["message"], str))

    # 반대로 비인증 공개 라우트(search/item)는 envelope를 쓰지 않는다 — 기존 계약 유지
    body = client.get("/api/v1/search").json()
    check_true("search keeps flat shape", "items" in body and "success" not in body, sorted(body)[:4])


# ---------------------------------------------------------------------------
# 18. CORS 설정 — 기본값은 전체 허용, 환경변수 지정 시 그 목록만 허용
# ---------------------------------------------------------------------------
def test_cors_configuration():
    print("\n--- 18. cors ---")
    import importlib

    saved = os.environ.get("CORS_ALLOW_ORIGINS")
    try:
        os.environ.pop("CORS_ALLOW_ORIGINS", None)
        mod = importlib.reload(api_server)
        check("default allows all origins", mod.CORS_ALLOW_ORIGINS, ["*"])

        os.environ["CORS_ALLOW_ORIGINS"] = "https://a.example, https://b.example"
        mod = importlib.reload(api_server)
        check("configured origins parsed", mod.CORS_ALLOW_ORIGINS,
              ["https://a.example", "https://b.example"])
    finally:
        if saved is None:
            os.environ.pop("CORS_ALLOW_ORIGINS", None)
        else:
            os.environ["CORS_ALLOW_ORIGINS"] = saved
        importlib.reload(api_server)


# ---------------------------------------------------------------------------
# 19. Admin 권한 2단계 (CTO 승인 4번) — SUPER_ADMIN / ADMIN
# ---------------------------------------------------------------------------
def test_admin_roles():
    print("\n--- 19. admin roles ---")
    from api.v1.admin import resolve_admin_role, ROLE_ADMIN, ROLE_SUPER_ADMIN

    check("admin key -> ADMIN", resolve_admin_role(TEST_ADMIN_KEY), ROLE_ADMIN)
    check("super key -> SUPER_ADMIN", resolve_admin_role(TEST_SUPER_ADMIN_KEY), ROLE_SUPER_ADMIN)
    check("unknown key -> None", resolve_admin_role("nope"), None)
    check("empty key -> None", resolve_admin_role(""), None)

    ah = {"X-Admin-Key": TEST_ADMIN_KEY}
    sh = {"X-Admin-Key": TEST_SUPER_ADMIN_KEY}

    # ADMIN 등급으로 가능한 일(기존 운영)은 그대로여야 한다 — 하위호환
    check("ADMIN can list requests",
          client.get("/api/v1/admin/registry-requests", headers=ah).status_code, 200)
    check("SUPER_ADMIN can list requests",
          client.get("/api/v1/admin/registry-requests", headers=sh).status_code, 200)

    # 과금에 영향을 주는 조작은 SUPER_ADMIN 전용
    body = {"user_id": TEST_USER, "reason_type": "GRANT", "amount": 1}
    check("ADMIN cannot adjust credit",
          client.post("/api/v1/admin/registry-credits", json=body, headers=ah).status_code, 403)
    check("SUPER_ADMIN can adjust credit",
          client.post("/api/v1/admin/registry-credits", json=body, headers=sh).status_code, 200)
    check("wrong key cannot adjust credit",
          client.post("/api/v1/admin/registry-credits", json=body,
                      headers={"X-Admin-Key": "nope"}).status_code, 403)


# ---------------------------------------------------------------------------
# 20. 등기부 무료횟수 조정 (CTO 승인 6번)
#     잔액 컬럼이 아니라 조정 원장이므로, 유효 한도 = 플랜 한도 + 이번 달 조정 합계다.
# ---------------------------------------------------------------------------
def test_registry_credits():
    print("\n--- 20. registry credits ---")
    from api.v1.registry_credits import MAX_ADJUSTMENT

    sh = {"X-Admin-Key": TEST_SUPER_ADMIN_KEY}
    ah = {"X-Admin-Key": TEST_ADMIN_KEY}
    user = TEST_USER + "-credit"

    r = client.get("/api/v1/admin/registry-credits/%s" % user, headers=ah)
    check("credit status readable by ADMIN", r.status_code, 200)
    base = r.json()["data"]["plan_limit"]
    check("no adjustment initially", r.json()["data"]["adjustment"], 0)
    check("effective == plan limit", r.json()["data"]["effective_limit"], base)

    r = client.post("/api/v1/admin/registry-credits",
                    json={"user_id": user, "reason_type": "GRANT", "amount": 3,
                          "reason": "CS compensation"}, headers=sh)
    check("GRANT +3 adjustment", r.json()["data"]["adjustment"], 3)
    check("GRANT raises effective limit", r.json()["data"]["effective_limit"], base + 3)

    r = client.post("/api/v1/admin/registry-credits",
                    json={"user_id": user, "reason_type": "DEDUCT", "amount": 1}, headers=sh)
    check("DEDUCT -1 adjustment", r.json()["data"]["adjustment"], 2)

    r = client.post("/api/v1/admin/registry-credits",
                    json={"user_id": user, "reason_type": "RESET"}, headers=sh)
    check("RESET clears adjustment", r.json()["data"]["adjustment"], 0)
    check("RESET restores plan limit", r.json()["data"]["effective_limit"], base)

    # RESET 이후의 조정만 유효해야 한다(이전 조정이 되살아나면 안 된다)
    r = client.post("/api/v1/admin/registry-credits",
                    json={"user_id": user, "reason_type": "GRANT", "amount": 2}, headers=sh)
    check("post-RESET adjustment counts only new", r.json()["data"]["adjustment"], 2)

    # 입력 검증
    check("oversized adjustment rejected",
          client.post("/api/v1/admin/registry-credits",
                      json={"user_id": user, "reason_type": "GRANT",
                            "amount": MAX_ADJUSTMENT + 1}, headers=sh).status_code, 400)
    check("zero amount rejected",
          client.post("/api/v1/admin/registry-credits",
                      json={"user_id": user, "reason_type": "GRANT", "amount": 0},
                      headers=sh).status_code, 400)
    check("unknown reason_type rejected",
          client.post("/api/v1/admin/registry-credits",
                      json={"user_id": user, "reason_type": "HACK", "amount": 1},
                      headers=sh).status_code, 400)
    check("blank user_id rejected",
          client.post("/api/v1/admin/registry-credits",
                      json={"user_id": "  ", "reason_type": "GRANT", "amount": 1},
                      headers=sh).status_code, 400)

    # 차감이 과해도 한도는 음수가 되지 않는다
    client.post("/api/v1/admin/registry-credits",
                json={"user_id": user, "reason_type": "DEDUCT", "amount": 99}, headers=sh)
    r = client.get("/api/v1/admin/registry-credits/%s" % user, headers=ah)
    check("effective limit floors at 0", r.json()["data"]["effective_limit"], 0)
    check("remaining never negative", r.json()["data"]["remaining"], 0)
    # 성공한 조정 5건(GRANT/DEDUCT/RESET/GRANT/DEDUCT)만 원장에 남는다.
    # 거부된 요청(한도 초과·0·잘못된 유형·빈 user_id)은 기록되지 않아야 한다.
    history = r.json()["data"]["history"]
    check("only accepted adjustments recorded", len(history), 5)
    check("history newest first", [h["reason_type"] for h in history],
          ["DEDUCT", "GRANT", "RESET", "DEDUCT", "GRANT"])
    check_true("actor recorded on every entry",
               all(h["created_by"] == "SUPER_ADMIN" for h in history),
               [h["created_by"] for h in history])

    # -----------------------------------------------------------------------
    # 20-B. 조정과 **실제 사용**이 뒤섞였을 때의 산술 (2026-08-12 Sprint 64 신규)
    #
    # 위 검사들은 관리자 조정만 따로 본다 — 실제 등기부 사용과 섞인 적이 없었다.
    # 이 원장은 잔액 컬럼이 아니라 조정 누계이므로, 사용이 끼어들면
    #   effective_limit = plan_limit + adjustment
    #   remaining       = effective_limit - used
    # 두 항등식이 계속 성립해야 한다. 특히 **이미 사용한 뒤의 DEDUCT**가 `used`를
    # 건드리면(혹은 remaining을 두 번 깎으면) 사용자는 쓰지도 않은 횟수를 잃는다.
    # -----------------------------------------------------------------------
    mix_user = TEST_USER + "-creditmix"
    conn = get_connection()
    try:
        now = datetime.now().isoformat()
        conn.execute(
            "INSERT INTO subscriptions (user_id,plan,price,status,started_at,expires_at,created_at,updated_at)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (mix_user, "BASIC", 12900, "ACTIVE", now,
             (datetime.now() + timedelta(days=30)).isoformat(), now, now))
        conn.commit()
    finally:
        conn.close()

    def credit_state():
        d = client.get("/api/v1/admin/registry-credits/%s" % mix_user, headers=ah).json()["data"]
        return d

    def check_identities(label, d):
        check("%s: effective = plan + adjustment" % label,
              d["effective_limit"], d["plan_limit"] + d["adjustment"])
        check("%s: remaining = effective - used" % label,
              d["remaining"], max(0, d["effective_limit"] - d["used"]))

    base_state = credit_state()
    plan_limit = base_state["plan_limit"]
    check_identities("초기", base_state)
    check("초기 사용 0", base_state["used"], 0)

    # GRANT +3 -> 한도만 늘고 사용량은 그대로
    client.post("/api/v1/admin/registry-credits",
                json={"user_id": mix_user, "reason_type": "GRANT", "amount": 3,
                      "reason": "qa mix"}, headers=sh)
    d = credit_state()
    check_identities("GRANT 후", d)
    check("GRANT는 한도만 늘린다", d["effective_limit"], plan_limit + 3)
    check("GRANT가 사용량을 건드리지 않는다", d["used"], 0)

    # 실제 등기부 2건 신청(무료 소모) -> used만 증가
    mix_items = pick_item_ids(2)
    for iid in mix_items:
        rr = client.post("/api/v1/registry-requests", json={"item_id": iid},
                         headers=auth_headers(mix_user))
        check_true("무료 신청 성공", rr.json()["success"], rr.json())
    d = credit_state()
    check_identities("사용 2건 후", d)
    check("사용 2건이 used에 반영", d["used"], 2)
    check("사용은 adjustment를 바꾸지 않는다", d["adjustment"], 3)
    check("remaining이 정확히 2 줄어든다", d["remaining"], plan_limit + 3 - 2)

    # 사용 이후의 DEDUCT -1 -> 한도만 줄고, 이미 쓴 횟수는 그대로여야 한다
    client.post("/api/v1/admin/registry-credits",
                json={"user_id": mix_user, "reason_type": "DEDUCT", "amount": 1,
                      "reason": "qa mix"}, headers=sh)
    d = credit_state()
    check_identities("사용 후 DEDUCT", d)
    check("DEDUCT는 used를 건드리지 않는다", d["used"], 2)
    check("DEDUCT가 한도를 1 줄인다", d["effective_limit"], plan_limit + 2)
    check("remaining도 1만 줄어든다", d["remaining"], plan_limit + 2 - 2)

    # 원장에는 조정 2건 + 사용 2건이 각각 남는다(사용이 조정 원장을 오염시키지 않는다)
    clogs = client.get("/api/v1/admin/registry/credit-logs/%s" % mix_user,
                       headers=ah).json()["data"]
    kinds = sorted(l["reason_type"] for l in clogs)
    check("원장에 조정 2건 + 사용 2건", kinds, ["DEDUCT", "GRANT", "USAGE", "USAGE"])
    check("조정 원장(history)에는 조정 2건만",
          sorted(h["reason_type"] for h in credit_state()["history"]), ["DEDUCT", "GRANT"])
    # 사용 로그의 delta는 1회당 -1이어야 한다(두 번 깎으면 사용자가 횟수를 잃는다)
    check("사용 로그 delta는 -1", sorted(l["delta"] for l in clogs if l["reason_type"] == "USAGE"),
          [-1, -1])


# ---------------------------------------------------------------------------
# 21. 결제 로그 / Webhook 구조 (CTO 승인 5번) — 실제 PG API는 호출하지 않는다
# ---------------------------------------------------------------------------
def test_payment_logs():
    print("\n--- 21. payment logs / webhooks ---")
    from api.v1.payment_logs import (
        mask_sensitive, record_webhook, mark_webhook_processed,
        WEBHOOK_PROCESSED, REDACTED,
    )

    # 전용 사용자로 구독한다 — TEST_USER는 8번에서 이미 PRO를 구독해 entitled 상태라,
    # 공유 TEST_USER로 다시 구독을 시도하면(중복 구독 방지, 2026-08-09) 새 payment가
    # 생기지 않아 이 테스트가 검증하려는 "새 결제의 로그 3단계"를 만들 수 없다.
    logs_user = TEST_USER + "-logs"
    h = auth_headers(logs_user)
    r = client.post("/api/v1/payments",
                    json={"payment_type": "SUBSCRIPTION", "plan": "BASIC",
                          "amount": resolve_plan_price("BASIC", BILLING_MONTHLY),
                          "billing_cycle": BILLING_MONTHLY}, headers=h)
    payment_id = r.json()["data"]["payment"]["id"]

    r = client.get("/api/v1/payments/%d/logs" % payment_id, headers=h)
    check("payment logs status", r.status_code, 200)
    logs = r.json()["data"]
    check("three lifecycle stages logged", len(logs), 3)
    check("stages in order", [log["event_type"] for log in logs],
          ["CREATE_ORDER", "CONFIRM", "VERIFY"])
    check_true("logs linked to payment", all(log["payment_id"] == payment_id for log in logs))
    check_true("provider recorded", all(log["provider"] == "mock" for log in logs))

    # 소유권 격리 — 남의 결제 로그는 볼 수 없다
    other = client.get("/api/v1/payments/%d/logs" % payment_id,
                       headers=auth_headers("qa-reg-other-" + uuid.uuid4().hex[:6]))
    check("other user cannot read logs", other.status_code, 404)

    # Admin 전용 결제 로그 조회 — GET /admin/payments/{id}/logs는 사용자용 §21과 별개
    # 라우트(require_admin, 소유권 검사 없이 아무 payment_id나 조회 가능)인데 지금까지
    # 테스트 0건이었다. 결제 분쟁 대응 시 운영자가 실제로 쓰는 경로이므로 커버한다.
    ah = {"X-Admin-Key": TEST_ADMIN_KEY}
    admin_view = client.get("/api/v1/admin/payments/%d/logs" % payment_id, headers=ah)
    check("admin can view any payment's logs", admin_view.status_code, 200)
    check("admin view has same log count", len(admin_view.json()["data"]), 3)
    check("admin payment logs requires admin key",
          client.get("/api/v1/admin/payments/%d/logs" % payment_id).status_code, 403)
    check("admin payment logs 404 for unknown payment",
          client.get("/api/v1/admin/payments/999999999/logs", headers=ah).status_code, 404)

    # 민감정보 마스킹 — 로그는 폭넓게 열람되므로 카드번호 등이 남으면 안 된다
    masked = mask_sensitive({"card_no": "4111111111111111", "amount": 1000,
                             "nested": {"cvc": "123", "ok": "keep"}})
    check("card_no masked", masked["card_no"], REDACTED)
    check("nested cvc masked", masked["nested"]["cvc"], REDACTED)
    check("non-sensitive kept", masked["nested"]["ok"], "keep")
    check("amount kept", masked["amount"], 1000)

    # Webhook 멱등성 — 같은 event_id 재수신은 새 행을 만들지 않는다
    conn = get_connection()
    try:
        event_id = "qa-wh-" + uuid.uuid4().hex[:10]
        first_id, dup1 = record_webhook(conn, "mock", {"status": "PAID"},
                                        event_type="PAYMENT_CONFIRMED", event_id=event_id)
        second_id, dup2 = record_webhook(conn, "mock", {"status": "PAID"},
                                         event_type="PAYMENT_CONFIRMED", event_id=event_id)
        conn.commit()
        check("first webhook is new", dup1, False)
        check("duplicate webhook detected", dup2, True)
        check("duplicate returns same row", second_id, first_id)

        mark_webhook_processed(conn, first_id, WEBHOOK_PROCESSED)
        conn.commit()
        row = conn.execute("SELECT * FROM payment_webhooks WHERE id=?", (first_id,)).fetchone()
        check("webhook marked processed", row["processing_status"], WEBHOOK_PROCESSED)
        check_true("processed_at set", row["processed_at"] is not None)
        check("signature unverified by default", row["signature_verified"], 0)

        conn.execute("DELETE FROM payment_webhooks WHERE id=?", (first_id,))
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 22. 크롤러 식별키 (docs/BUGS.md #18) — 법원이 다르면 별도 물건으로 남아야 한다
# ---------------------------------------------------------------------------
def test_auction_identity_keys():
    print("\n--- 22. auction identity keys ---")
    conn = get_connection()
    try:
        auction_sql = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='auction'").fetchone()[0]
        item_sql = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='auction_item'").fetchone()[0]
        check_true("auction keyed by court",
                   "UNIQUE(court_code, case_no, item_no)" in auction_sql, auction_sql[-120:])
        check_true("auction_item keyed by case_id",
                   "UNIQUE(case_id, item_no)" in item_sql, item_sql[-120:])
        check_true("auction no longer keyed without court",
                   "UNIQUE(case_no, item_no)" not in auction_sql)

        # 두 법원이 같은 사건번호+물건번호를 써도 각자의 행으로 남아야 한다(롤백으로 검증)
        conn.isolation_level = None
        conn.execute("BEGIN")
        try:
            base = conn.execute("SELECT * FROM auction LIMIT 1").fetchone()
            other = conn.execute(
                "SELECT court_code, court_name FROM auction WHERE court_code != ? LIMIT 1",
                (base["court_code"],)).fetchone()
            cols = [k for k in base.keys() if k != "id"]
            vals = [other["court_code"] if k == "court_code"
                    else other["court_name"] if k == "court_name"
                    else base[k] for k in cols]
            conn.execute("INSERT INTO auction (%s) VALUES (%s)"
                         % (",".join(cols), ",".join("?" * len(cols))), vals)
            n = conn.execute("SELECT COUNT(*) FROM auction WHERE case_no=? AND item_no IS ?",
                             (base["case_no"], base["item_no"])).fetchone()[0]
            check("both courts coexist", n, 2)
        finally:
            conn.execute("ROLLBACK")
            conn.isolation_level = ""
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 23. FK 런타임 강제 (CTO 승인 1번)
# ---------------------------------------------------------------------------
def test_foreign_key_enforcement():
    print("\n--- 23. foreign key enforcement ---")
    import sqlite3

    conn = get_connection()
    try:
        check("FK pragma ON by default", conn.execute("PRAGMA foreign_keys").fetchone()[0], 1)
        # 존재하지 않는 item_id로 즐겨찾기를 넣으면 DB가 막아야 한다
        try:
            conn.execute(
                "INSERT INTO favorites (user_id, item_id, created_at) VALUES (?,?,?)",
                (TEST_USER + "-fk", 99999999, "2026-01-01"),
            )
            check_true("orphan insert blocked", False, "FK 위반이 통과됨")
        except sqlite3.IntegrityError:
            check_true("orphan insert blocked", True)
        finally:
            conn.rollback()
    finally:
        conn.close()

    # 마이그레이션 전용 커넥션은 FK를 끈다(테이블 재작성 패턴이 중간에 고아를 만들기 때문)
    mig = get_connection(enforce_foreign_keys=False)
    try:
        check("migration connection has FK off",
              mig.execute("PRAGMA foreign_keys").fetchone()[0], 0)
    finally:
        mig.close()


# ---------------------------------------------------------------------------
# 24. Payment State Machine (CTO 승인 2번)
# ---------------------------------------------------------------------------
def test_payment_state_machine():
    print("\n--- 24. payment state machine ---")
    from api.constants import PaymentStatus, is_paid
    from api.v1.state_machines import (
        can_transition_payment, assert_payment_transition,
        is_terminal_payment, InvalidTransition,
    )

    # 정상 흐름
    for cur, nxt in (("CREATED", "READY"), ("READY", "REQUESTED"),
                     ("REQUESTED", "PAID"), ("PAID", "PARTIAL_REFUND"),
                     ("PARTIAL_REFUND", "REFUNDED"), ("PAID", "REFUNDED")):
        check("allow %s->%s" % (cur, nxt), can_transition_payment(cur, nxt), True)

    # 금지 전이 — 건너뛰기, 되돌리기, 종결 상태에서의 이동
    for cur, nxt in (("CREATED", "PAID"), ("REFUNDED", "PAID"),
                     ("FAILED", "PAID"), ("PAID", "READY"),
                     ("CANCELLED", "REQUESTED"), ("EXPIRED", "PAID")):
        check("block %s->%s" % (cur, nxt), can_transition_payment(cur, nxt), False)

    # 레거시 SUCCESS도 PAID와 동일하게 환불 가능해야 한다(기존 데이터 호환)
    check("legacy SUCCESS refundable", can_transition_payment("SUCCESS", "REFUNDED"), True)
    check("is_paid(SUCCESS)", is_paid(PaymentStatus.SUCCESS), True)
    check("is_paid(PAID)", is_paid(PaymentStatus.PAID), True)
    check("is_paid(FAILED)", is_paid(PaymentStatus.FAILED), False)
    # 부분 환불은 아직 돈이 남아있으므로 결제된 것으로 본다
    check("is_paid(PARTIAL_REFUND)", is_paid(PaymentStatus.PARTIAL_REFUND), True)

    for st in ("FAILED", "EXPIRED", "CANCELLED", "REFUNDED"):
        check("terminal %s" % st, is_terminal_payment(st), True)
    check("PAID not terminal", is_terminal_payment("PAID"), False)

    # 알 수 없는 상태는 거부
    try:
        assert_payment_transition("PAID", "TELEPORTED")
        check_true("unknown target rejected", False, "예외 없음")
    except InvalidTransition:
        check_true("unknown target rejected", True)


# ---------------------------------------------------------------------------
# 25. Subscription Lifecycle (CTO 승인 3번)
# ---------------------------------------------------------------------------
def test_subscription_lifecycle():
    print("\n--- 25. subscription lifecycle ---")
    from api.constants import SubscriptionStatus
    from api.v1.state_machines import (
        can_transition_subscription, resolve_expected_status, is_entitled,
        GRACE_PERIOD_DAYS,
    )
    from api.v1.subscriptions import sync_expired_status, change_status, renew

    for cur, nxt in (("ACTIVE", "GRACE_PERIOD"), ("GRACE_PERIOD", "ACTIVE"),
                     ("GRACE_PERIOD", "EXPIRED"), ("ACTIVE", "PAUSED"),
                     ("PAUSED", "ACTIVE"), ("EXPIRED", "ACTIVE"),
                     ("ACTIVE", "CANCELLED")):
        check("allow %s->%s" % (cur, nxt), can_transition_subscription(cur, nxt), True)
    for cur, nxt in (("CANCELLED", "ACTIVE"), ("PAUSED", "GRACE_PERIOD"),
                     ("EXPIRED", "GRACE_PERIOD")):
        check("block %s->%s" % (cur, nxt), can_transition_subscription(cur, nxt), False)

    now = datetime(2026, 8, 7, 12, 0, 0)
    future = (now + timedelta(days=10)).isoformat()
    just_expired = (now - timedelta(days=1)).isoformat()
    long_expired = (now - timedelta(days=GRACE_PERIOD_DAYS + 5)).isoformat()

    check("active stays active",
          resolve_expected_status("ACTIVE", future, now), SubscriptionStatus.ACTIVE)
    check("recently expired -> grace",
          resolve_expected_status("ACTIVE", just_expired, now), SubscriptionStatus.GRACE_PERIOD)
    check("long expired -> expired",
          resolve_expected_status("ACTIVE", long_expired, now), SubscriptionStatus.EXPIRED)
    # 사용자 의사로 정해진 상태는 시간과 무관하게 유지된다
    check("paused unaffected by time",
          resolve_expected_status("PAUSED", long_expired, now), SubscriptionStatus.PAUSED)
    check("cancelled unaffected by time",
          resolve_expected_status("CANCELLED", long_expired, now), SubscriptionStatus.CANCELLED)

    # 유예 기간에도 서비스는 이용 가능해야 한다(카드 갱신 중인 정상 사용자 보호).
    # ★ 유예의 기한은 expires_at이 아니라 expires_at + GRACE_PERIOD_DAYS다 —
    #   만료 시각으로 판정하면 유예 정책이 한 번도 작동하지 않는다(실제로 그 버그가 있었다).
    check("grace is entitled", is_entitled("GRACE_PERIOD", future, now), True)
    check("expired not entitled", is_entitled("EXPIRED", future, now), False)
    check("active just past expiry is entitled (grace)",
          is_entitled("ACTIVE", just_expired, now), True)
    check("active long past expiry not entitled",
          is_entitled("ACTIVE", long_expired, now), False)
    check("grace past its own deadline not entitled",
          is_entitled("GRACE_PERIOD", long_expired, now), False)
    check("paused never entitled", is_entitled("PAUSED", future, now), False)
    check("cancelled never entitled", is_entitled("CANCELLED", future, now), False)
    check("no expiry means unlimited", is_entitled("ACTIVE", None, now), True)

    # 이용권 게이트(registry.py)가 Lifecycle과 같은 기준을 쓰는지 —
    # 상태머신만 정의하고 게이트가 status='ACTIVE'만 보던 문제의 회귀 방어
    from api.v1.registry import has_active_subscription, get_plan_free_limit
    conn = get_connection()
    conn.isolation_level = None
    conn.execute("BEGIN")
    try:
        ts = datetime.now().isoformat()

        def mk(uid, status, days):
            conn.execute(
                "INSERT INTO subscriptions (user_id,plan,price,status,started_at,expires_at,created_at,updated_at)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (uid, "PRO", 1, status, ts,
                 (datetime.now() + timedelta(days=days)).isoformat(), ts, ts))

        base = TEST_USER + "-gate-"
        mk(base + "active", "ACTIVE", 10)
        # 아직 sync가 돌지 않아 DB에는 ACTIVE로 남아있는 유예 상태
        mk(base + "grace", "ACTIVE", -1)
        # ★ sync가 이미 돌아 DB에 GRACE_PERIOD로 **저장된** 상태.
        #   이 케이스가 없으면 조회 조건에서 GRACE_PERIOD를 빼먹어도 테스트가 통과한다
        #   (변이 감사에서 실제로 이 공백이 발견됐다).
        mk(base + "synced-grace", "GRACE_PERIOD", -1)
        mk(base + "expired", "ACTIVE", -(GRACE_PERIOD_DAYS + 5))
        mk(base + "synced-expired", "GRACE_PERIOD", -(GRACE_PERIOD_DAYS + 5))
        mk(base + "paused", "PAUSED", 10)
        mk(base + "cancelled", "CANCELLED", 10)

        for suffix, expected in (("active", True), ("grace", True), ("synced-grace", True),
                                 ("expired", False), ("synced-expired", False),
                                 ("paused", False), ("cancelled", False), ("none", False)):
            check("gate %s" % suffix,
                  has_active_subscription(conn, base + suffix), expected)
        # 저장된 GRACE_PERIOD에서도 플랜 한도가 유지되어야 한다
        check("synced grace keeps plan limit",
              get_plan_free_limit(conn, base + "synced-grace"), 10)
        # 유예 중에도 플랜 한도가 유지되어야 한다(기본값으로 떨어지면 안 됨)
        check("grace keeps plan limit", get_plan_free_limit(conn, base + "grace"), 10)
        check("expired falls back to default", get_plan_free_limit(conn, base + "expired"), 5)
    finally:
        conn.execute("ROLLBACK")
        conn.isolation_level = ""
        conn.close()

    # DB 레벨 lifecycle.
    # 롤백으로 감싸지 않는다 — 아래에서 sync_expired_status(commit=True)를 쓰기 때문이다
    # (읽기 경로와 같은 조건으로 검증하려는 의도). 대신 테스트 전용 user_id를 쓰고
    # cleanup()이 그 행만 지운다.
    conn = get_connection()
    try:
        user = TEST_USER + "-sub"
        ts = datetime.now().isoformat()
        sub_id = conn.execute(
            "INSERT INTO subscriptions (user_id,plan,price,status,started_at,expires_at,created_at,updated_at)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (user, "BASIC", 12900, "ACTIVE", ts,
             (datetime.now() - timedelta(days=1)).isoformat(), ts, ts),
        ).lastrowid

        # 만료 시각이 지났으니 동기화하면 GRACE_PERIOD가 되어야 한다
        sync_expired_status(conn, user, commit=True)

        # commit 인자는 키워드 전용이고 기본값이 없다 — 호출부가 반드시 명시해야 한다.
        # 쓰기 트랜잭션 안에서 실수로 커밋되는 것을 구조적으로 막기 위한 설계다.
        try:
            sync_expired_status(conn, user)
            check_true("commit must be explicit", False, "기본값이 허용됨")
        except TypeError:
            check_true("commit must be explicit", True)
        row = conn.execute("SELECT status FROM subscriptions WHERE id=?", (sub_id,)).fetchone()
        check("auto transition to grace", row["status"], SubscriptionStatus.GRACE_PERIOD.value)

        # 갱신하면 ACTIVE로 돌아오고 만료가 미래로 밀린다
        result = renew(conn, sub_id, 30, actor="TEST")
        check("renew restores active", result["after"]["status"], SubscriptionStatus.ACTIVE.value)
        check_true("renew pushes expiry",
                   result["after"]["expires_at"] > datetime.now().isoformat())

        # 해지는 최종 상태 — 되돌릴 수 없다
        change_status(conn, sub_id, "CANCELLED", actor="TEST")
        row = conn.execute("SELECT status FROM subscriptions WHERE id=?", (sub_id,)).fetchone()
        check("cancel applied", row["status"], SubscriptionStatus.CANCELLED.value)
        from api.v1.state_machines import InvalidTransition
        try:
            change_status(conn, sub_id, "ACTIVE", actor="TEST")
            check_true("cancelled cannot reactivate", False, "전이가 허용됨")
        except InvalidTransition:
            check_true("cancelled cannot reactivate", True)
    finally:
        conn.commit()
        conn.close()


# ---------------------------------------------------------------------------
# 26. audit_logs / registry_credit_logs (CTO 승인 4·5번)
# ---------------------------------------------------------------------------
def test_audit_and_credit_logs():
    print("\n--- 26. audit / credit logs ---")
    sh = {"X-Admin-Key": TEST_SUPER_ADMIN_KEY}
    ah = {"X-Admin-Key": TEST_ADMIN_KEY}
    user = TEST_USER + "-audit"

    r = client.post("/api/v1/admin/registry-credits",
                    json={"user_id": user, "reason_type": "GRANT", "amount": 2,
                          "reason": "audit test"}, headers=sh)
    check("credit adjust ok", r.status_code, 200)

    # 감사 로그가 남았는지
    r = client.get("/api/v1/admin/audit-logs?action=REGISTRY_CREDIT_ADJUST", headers=ah)
    check("audit logs status", r.status_code, 200)
    logs = r.json()["data"]
    check_true("audit log recorded", len(logs) >= 1)
    entry = logs[0]
    for key in ("admin_id", "action", "target_type", "target_id", "before", "after", "created_at"):
        check_true("audit log has %s" % key, key in entry)
    check("audit actor is SUPER_ADMIN", entry["admin_id"], "SUPER_ADMIN")
    check_true("audit meta has total", "total" in (r.json()["meta"] or {}))

    # credit 변동 추적 로그
    r = client.get("/api/v1/admin/registry/credit-logs/%s" % user, headers=ah)
    check("credit logs status", r.status_code, 200)
    clogs = r.json()["data"]
    check_true("credit log recorded", len(clogs) >= 1)
    check("credit log delta", clogs[0]["delta"], 2)
    check("credit log actor", clogs[0]["actor"], "SUPER_ADMIN")
    check_true("credit log balance_after", clogs[0]["balance_after"] is not None)

    # 사용(USAGE)도 추적 로그에 남아야 한다(승인 4번의 기록 대상에 "사용"이 포함된다).
    # 단 한도 계산에는 반영되지 않아야 한다 — registry_usage가 이미 세고 있어 이중 차감이 된다.
    usage_user = TEST_USER + "-usage"
    uh = auth_headers(usage_user)
    conn = get_connection()
    try:
        ts = datetime.now().isoformat()
        conn.execute(
            "INSERT INTO subscriptions (user_id,plan,price,status,started_at,expires_at,created_at,updated_at)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (usage_user, "BASIC", 12900, "ACTIVE", ts,
             (datetime.now() + timedelta(days=30)).isoformat(), ts, ts),
        )
        conn.commit()
    finally:
        conn.close()

    before = client.get("/api/v1/admin/registry-credits/%s" % usage_user,
                        headers=ah).json()["data"]
    r = client.post("/api/v1/registry-requests",
                    json={"item_id": pick_item_ids(1)[0]}, headers=uh)
    check("free registry request ok", r.json()["data"]["is_free"], True)

    logs = client.get("/api/v1/admin/registry/credit-logs/%s" % usage_user,
                      headers=ah).json()["data"]
    usage_logs = [g for g in logs if g["reason_type"] == "USAGE"]
    check("usage logged", len(usage_logs), 1)
    check("usage delta is -1", usage_logs[0]["delta"], -1)
    check("usage actor is USER", usage_logs[0]["actor"], "USER")
    check_true("usage links to registry_usage", usage_logs[0]["related_usage_id"] is not None)
    check("usage balance_after reflects consumption",
          usage_logs[0]["balance_after"], before["effective_limit"] - 1)

    after = client.get("/api/v1/admin/registry-credits/%s" % usage_user,
                       headers=ah).json()["data"]
    # 사용은 조정 합계를 건드리지 않는다(이중 차감 방지)
    check("usage does not change adjustment", after["adjustment"], before["adjustment"])
    check("usage does not change effective limit",
          after["effective_limit"], before["effective_limit"])
    check("usage counted once", after["used"], before["used"] + 1)

    # 상태 전이도 감사 로그에 남는지
    item_id = pick_item_ids(1)[0]
    conn = get_connection()
    try:
        rid = conn.execute(
            "INSERT INTO registry_requests (user_id,item_id,status,requested_at)"
            " VALUES (?,?,?,?)",
            (TEST_USER, item_id, "PENDING", datetime.now().isoformat()),
        ).lastrowid
        conn.commit()
    finally:
        conn.close()
    client.patch("/api/v1/admin/registry-requests/%d" % rid,
                 json={"status": "PROCESSING"}, headers=ah)
    r = client.get("/api/v1/admin/audit-logs?target_type=REGISTRY_REQUEST&target_id=%d" % rid,
                   headers=ah)
    entries = r.json()["data"]
    check("status change audited", len(entries), 1)
    check_true("audit before recorded", "PENDING" in (entries[0]["before"] or ""))
    check_true("audit after recorded", "PROCESSING" in (entries[0]["after"] or ""))


# ---------------------------------------------------------------------------
# 27. Admin REST 구조 (CTO 승인 7번) — 기존 경로는 그대로 살아있어야 한다
# ---------------------------------------------------------------------------
def test_admin_rest_structure():
    print("\n--- 27. admin rest structure ---")
    ah = {"X-Admin-Key": TEST_ADMIN_KEY}
    sh = {"X-Admin-Key": TEST_SUPER_ADMIN_KEY}

    # 기존 경로 유지 확인(Breaking Change 방지) + 새 경로가 같은 결과를 주는지
    legacy = client.get("/api/v1/admin/registry-requests", headers=ah)
    modern = client.get("/api/v1/admin/registry/requests", headers=ah)
    check("legacy path still works", legacy.status_code, 200)
    check("new path works", modern.status_code, 200)
    check("both paths identical", legacy.json()["data"]["total"], modern.json()["data"]["total"])
    # total만 같으면 "둘 다 빈 결과"여도 통과한다 — 실제 행과 필터 동작까지 대조한다
    # (2026-08-12 Sprint 64: 신규 경로는 위임 함수라 조용히 갈라져도 total은 같을 수 있다).
    lj, mj = legacy.json()["data"], modern.json()["data"]
    check("both paths return the same rows",
          [i["id"] for i in mj["items"]], [i["id"] for i in lj["items"]])
    check("both paths agree on page/size", (mj["page"], mj["size"]), (lj["page"], lj["size"]))
    for params in ("?status=PENDING", "?page=2&size=1", "?status=BOGUS"):
        a = client.get("/api/v1/admin/registry-requests" + params, headers=ah)
        b = client.get("/api/v1/admin/registry/requests" + params, headers=ah)
        check("alias matches legacy for %s (status)" % params, b.status_code, a.status_code)
        if a.status_code == 200:
            # 전체 body를 그대로 비교하되(강도 유지), 출력에는 결과만 남긴다 —
            # 응답 본문을 통째로 찍으면 회귀 로그가 수천 자로 뒤덮여 실제 실패를 못 찾는다.
            check_true("alias matches legacy for %s (body)" % params,
                       b.json()["data"] == a.json()["data"],
                       "legacy=%d rows / alias=%d rows"
                       % (len(a.json()["data"]["items"]), len(b.json()["data"]["items"])))

    # /admin/users: 집계값이 정확한지 + 페이지네이션이 안쪽 LIMIT로 잘려도 결과가 같은지
    conn = get_connection()
    try:
        iid = pick_item_ids(1)[0]
        ts = datetime.now().isoformat()
        for i in range(3):
            uid = "%s-users-%d" % (TEST_USER, i)
            conn.execute("INSERT INTO favorites (user_id,item_id,created_at) VALUES (?,?,?)",
                         (uid, iid, ts))
            for _ in range(i):
                conn.execute(
                    "INSERT INTO payments (user_id,payment_type,amount,status,created_at,updated_at)"
                    " VALUES (?,?,?,?,?,?)", (uid, "SUBSCRIPTION", 1, "SUCCESS", ts, ts))
        conn.commit()
    finally:
        conn.close()

    r = client.get("/api/v1/admin/users?q=%s-users&size=10" % TEST_USER, headers=ah)
    rows = {x["user_id"]: x for x in r.json()["data"]}
    check("user aggregation count", r.json()["meta"]["total"], 3)
    for i in range(3):
        uid = "%s-users-%d" % (TEST_USER, i)
        check("user %d payment_count" % i, rows[uid]["payment_count"], i)
        check("user %d favorite_count" % i, rows[uid]["favorite_count"], 1)
    # 페이지를 잘라도 집계가 흐트러지지 않아야 한다(안쪽 LIMIT 최적화 회귀 방어)
    p2 = client.get("/api/v1/admin/users?q=%s-users&size=1&page=2" % TEST_USER, headers=ah)
    check("paged user count", len(p2.json()["data"]), 1)
    check("paged user is second", p2.json()["data"][0]["user_id"], "%s-users-1" % TEST_USER)
    check("paged user aggregation intact", p2.json()["data"][0]["payment_count"], 1)

    for path in ("/api/v1/admin/users", "/api/v1/admin/payments",
                 "/api/v1/admin/subscriptions", "/api/v1/admin/audit-logs"):
        r = client.get(path, headers=ah)
        check("%s status" % path, r.status_code, 200)
        check_true("%s has meta.total" % path, "total" in (r.json()["meta"] or {}))
        check_true("%s data is list" % path, isinstance(r.json()["data"], list))
        # 권한 게이트가 걸려 있는지
        check("%s requires admin" % path, client.get(path).status_code, 403)

    # 구독 상태 변경은 SUPER_ADMIN 전용 + 전이 규칙 적용
    conn = get_connection()
    try:
        ts = datetime.now().isoformat()
        sub_id = conn.execute(
            "INSERT INTO subscriptions (user_id,plan,price,status,started_at,expires_at,created_at,updated_at)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (TEST_USER, "BASIC", 12900, "ACTIVE", ts,
             (datetime.now() + timedelta(days=30)).isoformat(), ts, ts),
        ).lastrowid
        conn.commit()
    finally:
        conn.close()

    check("ADMIN cannot change subscription",
          client.patch("/api/v1/admin/subscriptions/%d" % sub_id,
                       json={"status": "PAUSED"}, headers=ah).status_code, 403)
    r = client.patch("/api/v1/admin/subscriptions/%d" % sub_id,
                     json={"status": "PAUSED", "reason": "test"}, headers=sh)
    check("SUPER_ADMIN can pause", r.status_code, 200)
    check("subscription paused", r.json()["data"]["status"], "PAUSED")
    # 규칙에 없는 전이는 400
    check("invalid transition rejected",
          client.patch("/api/v1/admin/subscriptions/%d" % sub_id,
                       json={"status": "GRACE_PERIOD"}, headers=sh).status_code, 400)
    check("unknown subscription 404",
          client.patch("/api/v1/admin/subscriptions/99999999",
                       json={"status": "PAUSED"}, headers=sh).status_code, 404)

    # ACTIVE -> CANCELLED / ACTIVE -> EXPIRED — 둘 다 CANCELLED/EXPIRED 종결 분기를 타며
    # 즉시 만료 시각을 지금으로 당긴다. 각각 별도 구독으로 실제 엔드포인트를 통해 확인한다
    # (2026-08-12, BUGS #58 동시성 수정 이후 이 분기가 실제로 여전히 정상 동작하는지 고정).
    for target_status in ("CANCELLED", "EXPIRED"):
        conn = get_connection()
        try:
            ts = datetime.now().isoformat()
            fresh_sub_id = conn.execute(
                "INSERT INTO subscriptions (user_id,plan,price,status,started_at,expires_at,created_at,updated_at)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (TEST_USER, "BASIC", 12900, "ACTIVE", ts,
                 (datetime.now() + timedelta(days=30)).isoformat(), ts, ts),
            ).lastrowid
            conn.commit()
        finally:
            conn.close()
        r_end = client.patch("/api/v1/admin/subscriptions/%d" % fresh_sub_id,
                             json={"status": target_status, "reason": "test"}, headers=sh)
        check("ACTIVE -> %s 성공" % target_status, r_end.status_code, 200)
        check("응답 status가 %s" % target_status, r_end.json()["data"]["status"], target_status)
        conn = get_connection()
        try:
            row_end = conn.execute("SELECT status, expires_at FROM subscriptions WHERE id=?",
                                   (fresh_sub_id,)).fetchone()
            check("%s DB 상태 반영" % target_status, row_end["status"], target_status)
            check_true("%s 만료 시각이 과거로 당겨짐" % target_status,
                       row_end["expires_at"] <= datetime.now().isoformat())
        finally:
            conn.close()

    # --- 만료된 구독 재활성화 (2026-08-12, docs/BUGS.md #59) ---
    # expires_at 없이 ACTIVE로 되돌리면 응답은 200(status=ACTIVE)이었지만 만료 시각을
    # 갱신하지 않아 같은 응답의 effective_status가 이미 EXPIRED였고, 다음 조회에서 DB
    # 상태도 조용히 EXPIRED로 되돌아갔다 — "성공했다고 응답했지만 아무 일도 없었던" 결함.
    conn = get_connection()
    try:
        ts = datetime.now().isoformat()
        expired_sub_id = conn.execute(
            "INSERT INTO subscriptions (user_id,plan,price,status,started_at,expires_at,created_at,updated_at)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (TEST_USER, "BASIC", 12900, "EXPIRED", ts,
             (datetime.now() - timedelta(days=5)).isoformat(), ts, ts),
        ).lastrowid
        conn.commit()
    finally:
        conn.close()

    r = client.patch("/api/v1/admin/subscriptions/%d" % expired_sub_id,
                     json={"status": "ACTIVE"}, headers=sh)
    check("expires_at 없이 만료 구독 재활성화는 400(조용한 실패 대신 명시적 거부)",
          r.status_code, 400)
    conn = get_connection()
    try:
        row = conn.execute("SELECT status FROM subscriptions WHERE id=?",
                           (expired_sub_id,)).fetchone()
        check("거부 후 DB 상태는 EXPIRED 그대로", row["status"], "EXPIRED")
    finally:
        conn.close()

    check("expires_at 형식이 잘못되면 400",
          client.patch("/api/v1/admin/subscriptions/%d" % expired_sub_id,
                       json={"status": "ACTIVE", "expires_at": "not-a-date"},
                       headers=sh).status_code, 400)

    new_expiry = (datetime.now() + timedelta(days=30)).isoformat()
    r2 = client.patch("/api/v1/admin/subscriptions/%d" % expired_sub_id,
                      json={"status": "ACTIVE", "expires_at": new_expiry, "reason": "cs"},
                      headers=sh)
    check("expires_at을 함께 주면 재활성화 성공", r2.status_code, 200)
    check("응답 status가 ACTIVE", r2.json()["data"]["status"], "ACTIVE")
    check("응답 effective_status도 ACTIVE(모순 없음)",
          r2.json()["data"]["effective_status"], "ACTIVE")
    check_true("응답 is_entitled True", r2.json()["data"]["is_entitled"])
    conn = get_connection()
    try:
        row2 = conn.execute("SELECT status, expires_at FROM subscriptions WHERE id=?",
                            (expired_sub_id,)).fetchone()
        check("DB 상태가 실제로 ACTIVE로 반영됨", row2["status"], "ACTIVE")
        check("DB expires_at이 새 값으로 반영됨", row2["expires_at"], new_expiry)
    finally:
        conn.close()

    # PAUSED -> ACTIVE(재개)는 expires_at이 아직 남아있으므로 없이도 정상 동작해야 한다
    # (이번 수정이 재개 경로까지 깨뜨리지 않았는지 확인).
    conn = get_connection()
    try:
        ts = datetime.now().isoformat()
        paused_sub_id = conn.execute(
            "INSERT INTO subscriptions (user_id,plan,price,status,started_at,expires_at,created_at,updated_at)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (TEST_USER, "BASIC", 12900, "PAUSED", ts,
             (datetime.now() + timedelta(days=20)).isoformat(), ts, ts),
        ).lastrowid
        conn.commit()
    finally:
        conn.close()
    r3 = client.patch("/api/v1/admin/subscriptions/%d" % paused_sub_id,
                      json={"status": "ACTIVE"}, headers=sh)
    check("PAUSED -> ACTIVE 재개는 expires_at 없이도 200", r3.status_code, 200)
    check("재개 응답도 effective_status ACTIVE", r3.json()["data"]["effective_status"], "ACTIVE")


# ---------------------------------------------------------------------------
# 28. Soft Delete 컬럼 (CTO 승인 6번)
#     이번 범위는 "컬럼 추가"까지다 — 기존 DELETE 동작은 그대로 유지된다.
# ---------------------------------------------------------------------------
def test_soft_delete_columns():
    print("\n--- 28. soft delete columns ---")
    conn = get_connection()
    try:
        for table in ("favorites", "search_presets"):
            cols = [r[1] for r in conn.execute("PRAGMA table_info(%s)" % table)]
            check_true("%s has deleted_at" % table, "deleted_at" in cols, cols)
            check_true("%s has deleted_by" % table, "deleted_by" in cols, cols)
    finally:
        conn.close()

    # 기존 삭제 동작이 바뀌지 않았는지(하드 딜리트 유지 — 전환은 별도 판단)
    item_id = pick_item_ids(1)[0]
    h = auth_headers()
    client.post("/api/v1/favorites", json={"item_id": item_id}, headers=h)
    check("delete favorite still works",
          client.delete("/api/v1/favorites/%d" % item_id, headers=h).json()["success"], True)
    check_true("favorite gone from list",
               all(i["id"] != item_id
                   for i in client.get("/api/v1/favorites", headers=h).json()["data"]))

    # -----------------------------------------------------------------------
    # 28-B. `deleted_at`은 **아직 어떤 조회도 보지 않는다** (2026-08-12 Sprint 71 신규)
    #
    # 컬럼은 소프트 삭제 전환을 위해 미리 만들어 뒀지만(Migration 016), 실제로 그 값을
    # 쓰는 코드는 저장소 전체에 0곳이고 조회 쿼리에도 `deleted_at IS NULL` 조건이 없다.
    # 즉 지금은 하드 삭제만이 유일한 삭제 경로이며 **그것이 의도된 현재 동작**이다.
    #
    # 위험은 나중이다 — 누군가 "컬럼이 있으니 값만 채우면 되겠지" 하고 `deleted_at`을
    # 쓰기 시작하면, 행은 **사라지지 않고 그대로 조회된다**(검색 결과의 하트까지 켜진 채로).
    # Migration 016 주석도 정확히 이 위험을 적어 뒀다("컬럼만 늘리면 모든 조회에
    # deleted_at IS NULL을 붙여야 한다").
    #
    # 그래서 **현재 동작을 그대로 못 박는다.** 소프트 삭제를 배선하는 순간 이 검사가 실패해,
    # 아래 열거된 조회들을 함께 고쳐야 한다는 사실을 강제로 알려 준다.
    # 전환 여부 자체는 제품 판단이라 여기서 정하지 않는다.
    # -----------------------------------------------------------------------
    soft_user = TEST_USER + "-softdel"
    sh_hdr = auth_headers(soft_user)
    client.post("/api/v1/favorites", json={"item_id": item_id}, headers=sh_hdr)
    preset = client.post("/api/v1/search-presets",
                         json={"name": "soft-delete probe", "conditions": {}},
                         headers=sh_hdr).json()
    check("사전 조건: 즐겨찾기 1건", len(client.get("/api/v1/favorites", headers=sh_hdr).json()["data"]), 1)
    check("사전 조건: 검색조건 1건",
          len(client.get("/api/v1/search-presets", headers=sh_hdr).json()["data"]), 1)

    conn = get_connection()
    try:
        now = datetime.now().isoformat()
        for table in ("favorites", "search_presets"):
            conn.execute("UPDATE %s SET deleted_at=?, deleted_by=? WHERE user_id=?" % table,
                         (now, soft_user, soft_user))
        conn.commit()
    finally:
        conn.close()

    favs = client.get("/api/v1/favorites", headers=sh_hdr).json()["data"]
    presets = client.get("/api/v1/search-presets", headers=sh_hdr).json()["data"]
    check("[현재 동작] deleted_at을 채워도 즐겨찾기 조회에서 사라지지 않는다", len(favs), 1)
    check("[현재 동작] deleted_at을 채워도 검색조건 조회에서 사라지지 않는다", len(presets), 1)

    # 검색 결과의 개인화(하트)도 같은 테이블을 읽으므로 함께 켜진 채로 남는다
    conn = get_connection()
    try:
        soft_case_no = conn.execute("SELECT case_no FROM auction_item WHERE id=?",
                                    (item_id,)).fetchone()["case_no"]
    finally:
        conn.close()
    hearts = [i["is_favorited"] for i in client.get(
        "/api/v1/search?size=100&include_closed=true&case_no=" + soft_case_no,
        headers=sh_hdr).json()["items"] if i["id"] == item_id]
    check("[현재 동작] 검색 결과의 하트도 켜진 채로 남는다", hearts, [True])

    # 소프트 삭제를 배선할 때 **함께 고쳐야 하는 조회 지점**을 소스로 고정해 둔다.
    # (지금은 어느 곳에도 조건이 없어야 정상 — 하나라도 생기면 전환이 시작된 것이다)
    fav_src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "api", "v1", "favorites.py"), encoding="utf-8-sig").read()
    pre_src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "api", "v1", "search_presets.py"), encoding="utf-8-sig").read()
    sea_src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "api", "v1", "search.py"), encoding="utf-8-sig").read()
    check("favorites.py에 deleted_at 조건이 아직 없다", "deleted_at" in fav_src, False)
    check("search_presets.py에 deleted_at 조건이 아직 없다", "deleted_at" in pre_src, False)
    check("search.py(하트 조회)에 deleted_at 조건이 아직 없다", "deleted_at" in sea_src, False)

    conn = get_connection()
    try:
        for table in ("favorites", "search_presets"):
            conn.execute("DELETE FROM %s WHERE user_id=?" % table, (soft_user,))
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 29. 환불 (2026-08-11 Sprint 52 신설) — SUPER_ADMIN 전용, MockProvider 기반
#
# Sprint 27~28에 준비만 되고 한 번도 실행되지 않던 경로를 검증한다:
# 상태머신(PAID -> PARTIAL_REFUND/REFUNDED), cancel_payment(), EVENT_CANCEL 로그,
# PAY_NOT_FOUND / PAY_INVALID_TRANSITION.
# ---------------------------------------------------------------------------
def _make_paid_payment(user_id):
    """환불 대상 결제를 하나 만들고 (payment_id, amount)를 돌려준다."""
    r = client.post("/api/v1/payments",
                    json={"payment_type": "SUBSCRIPTION", "plan": "BASIC",
                          "amount": resolve_plan_price("BASIC", BILLING_MONTHLY),
                          "billing_cycle": BILLING_MONTHLY},
                    headers=auth_headers(user_id))
    body = r.json()
    assert body.get("success"), body
    payment = body["data"]["payment"]
    return payment["id"], payment["amount"]


def test_refund():
    print("\n--- 29. refund (SUPER_ADMIN) ---")
    sh = {"X-Admin-Key": TEST_SUPER_ADMIN_KEY}
    ah = {"X-Admin-Key": TEST_ADMIN_KEY}

    # --- 권한 경계 ---
    user = TEST_USER + "-refund-authz"
    pid, amount = _make_paid_payment(user)
    check("환불은 인증 없이 불가",
          client.post("/api/v1/admin/payments/%d/refund" % pid,
                      json={"reason": "x"}).status_code, 403)
    check("환불은 ADMIN 등급으로 불가(SUPER_ADMIN 전용)",
          client.post("/api/v1/admin/payments/%d/refund" % pid,
                      json={"reason": "x"}, headers=ah).status_code, 403)
    check("reason 없으면 400",
          client.post("/api/v1/admin/payments/%d/refund" % pid,
                      json={"reason": "   "}, headers=sh).status_code, 400)
    check("없는 결제는 404",
          client.post("/api/v1/admin/payments/99999999/refund",
                      json={"reason": "x"}, headers=sh).status_code, 404)

    # --- 전액 환불 ---
    user = TEST_USER + "-refund-full"
    pid, amount = _make_paid_payment(user)
    r = client.post("/api/v1/admin/payments/%d/refund" % pid,
                    json={"reason": "고객 요청"}, headers=sh)
    check("전액 환불 200", r.status_code, 200)
    data = r.json()["data"]
    check("환불 금액 = 결제 금액", data["refunded_amount"], amount)
    check("누적 환불 = 결제 금액", data["total_refunded"], amount)
    check("잔여 환불 가능액 0", data["refundable_remaining"], 0)
    check("상태가 REFUNDED", data["payment"]["status"], "REFUNDED")
    check_true("구독은 자동 해지하지 않는다(정책 미결정)", data["subscription_untouched"])

    # 멱등: 이미 전액 환불된 결제에 다시 요청해도 오류가 아니고 중복 차감도 없다
    r2 = client.post("/api/v1/admin/payments/%d/refund" % pid,
                     json={"reason": "중복 요청"}, headers=sh)
    check("재환불 요청도 200(멱등)", r2.status_code, 200)
    check_true("already_refunded 플래그", r2.json()["data"]["already_refunded"])
    check("재요청은 추가 환불 0원", r2.json()["data"]["refunded_amount"], 0)
    check("누적 환불액이 늘지 않음", r2.json()["data"]["total_refunded"], amount)

    # --- 부분 환불 (누적) ---
    user = TEST_USER + "-refund-partial"
    pid, amount = _make_paid_payment(user)
    part = amount // 3
    r = client.post("/api/v1/admin/payments/%d/refund" % pid,
                    json={"amount": part, "reason": "부분1"}, headers=sh)
    check("부분 환불 200", r.status_code, 200)
    check("상태가 PARTIAL_REFUND", r.json()["data"]["payment"]["status"], "PARTIAL_REFUND")
    check("잔여 = 총액 - 부분", r.json()["data"]["refundable_remaining"], amount - part)

    r = client.post("/api/v1/admin/payments/%d/refund" % pid,
                    json={"amount": part, "reason": "부분2"}, headers=sh)
    check("부분 환불 반복 가능", r.json()["data"]["payment"]["status"], "PARTIAL_REFUND")
    check("누적 환불액 합산", r.json()["data"]["total_refunded"], part * 2)

    # 잔여를 초과하는 환불은 거부
    check("잔여 초과 환불은 400",
          client.post("/api/v1/admin/payments/%d/refund" % pid,
                      json={"amount": amount, "reason": "초과"}, headers=sh).status_code, 400)
    check("0원 환불은 400",
          client.post("/api/v1/admin/payments/%d/refund" % pid,
                      json={"amount": 0, "reason": "0원"}, headers=sh).status_code, 400)
    check("음수 환불은 400",
          client.post("/api/v1/admin/payments/%d/refund" % pid,
                      json={"amount": -100, "reason": "음수"}, headers=sh).status_code, 400)

    # 잔여 전액을 마저 환불하면 REFUNDED로 종결
    r = client.post("/api/v1/admin/payments/%d/refund" % pid,
                    json={"reason": "잔액 정리"}, headers=sh)
    check("잔여 환불 시 REFUNDED로 종결", r.json()["data"]["payment"]["status"], "REFUNDED")
    check("누적 = 결제 총액", r.json()["data"]["total_refunded"], amount)

    # --- 상태머신 관문: 종결 상태는 환불 불가 ---
    user = TEST_USER + "-refund-terminal"
    pid, amount = _make_paid_payment(user)
    conn = get_connection()
    try:
        conn.execute("UPDATE payments SET status='FAILED' WHERE id=?", (pid,))
        conn.commit()
    finally:
        conn.close()
    r = client.post("/api/v1/admin/payments/%d/refund" % pid,
                    json={"reason": "실패 결제 환불 시도"}, headers=sh)
    check("FAILED 결제는 환불 불가(400)", r.status_code, 400)

    # --- 원장(payment_logs)이 환불 궤적을 남기는가 ---
    user = TEST_USER + "-refund-log"
    pid, amount = _make_paid_payment(user)
    client.post("/api/v1/admin/payments/%d/refund" % pid,
                json={"amount": 100, "reason": "로그확인"}, headers=sh)
    logs = client.get("/api/v1/admin/payments/%d/logs" % pid, headers=ah).json()["data"]
    cancels = [l for l in logs if l["event_type"] == "CANCEL"]
    check("CANCEL 이벤트가 기록됨", len(cancels), 1)
    check("CANCEL 로그 금액", cancels[0]["amount"], 100)
    check("CANCEL 로그 상태", cancels[0]["status"], "SUCCESS")

    # --- 감사 로그(audit_logs) ---
    # target_id는 **문자열**로 저장된다 — AuditTargetType.USER의 대상이 Supabase user_id
    # (UUID 문자열)라 컬럼이 TEXT다. 정수 payment_id도 문자열로 들어간다.
    # (이 계약을 모르고 int로 비교했다가 실제로 한 번 헛나갔다 — 그래서 명시적으로 고정한다.)
    audit = client.get("/api/v1/admin/audit-logs?target_type=PAYMENT", headers=ah).json()["data"]
    mine = [a for a in audit if str(a["target_id"]) == str(pid)]
    check_true("환불이 감사 로그에 남는다", len(mine) >= 1, [a["target_id"] for a in audit[:5]])
    if mine:
        check("감사 action", mine[0]["action"], "PAYMENT_STATUS_CHANGE")
        check_true("target_id는 문자열로 저장된다", isinstance(mine[0]["target_id"], str),
                   type(mine[0]["target_id"]).__name__)
        check_true("환불 전후 상태가 남는다",
                   '"status"' in (mine[0]["before"] or "") and '"status"' in (mine[0]["after"] or ""),
                   (mine[0]["before"], mine[0]["after"]))
        check_true("환불 금액이 감사에 남는다", "refunded_amount" in (mine[0]["after"] or ""),
                   mine[0]["after"])


# ---------------------------------------------------------------------------
# 31. 사용자용 구독 조회 (2026-08-11 Sprint 52 신설)
#
# 결제한 사용자가 자기 구독을 볼 방법이 없던 공백을 메운 경로. 소유권 격리가 핵심이다.
# ---------------------------------------------------------------------------
def test_my_subscriptions():
    print("\n--- 31. GET /subscriptions/me ---")
    check("인증 없으면 401/403",
          client.get("/api/v1/subscriptions/me").status_code in (401, 403), True)

    user_a = TEST_USER + "-mysub-a"
    user_b = TEST_USER + "-mysub-b"

    # 구독이 없는 사용자는 빈 리스트(오류가 아니다)
    r = client.get("/api/v1/subscriptions/me", headers=auth_headers(user_b))
    check("구독 없으면 200", r.status_code, 200)
    check("빈 리스트", r.json()["data"], [])
    check_true("envelope 형식", set(r.json().keys()) == ENVELOPE_KEYS, sorted(r.json()))

    # A가 구독을 만든다
    price = resolve_plan_price("PRO", BILLING_YEARLY)
    pay = client.post("/api/v1/payments",
                      json={"payment_type": "SUBSCRIPTION", "plan": "PRO",
                            "amount": price, "billing_cycle": BILLING_YEARLY},
                      headers=auth_headers(user_a)).json()
    check_true("구독 결제 성공", pay["success"], pay)

    r = client.get("/api/v1/subscriptions/me", headers=auth_headers(user_a))
    data = r.json()["data"]
    check("A는 자기 구독 1건", len(data), 1)
    sub = data[0]
    check("plan", sub["plan"], "PRO")
    check("price", sub["price"], price)
    check("status", sub["status"], "ACTIVE")
    check_true("지금 이용 가능", sub["is_entitled"], sub)
    check("effective_status", sub["effective_status"], "ACTIVE")
    check_true("만료일이 있다", bool(sub["expires_at"]), sub)
    check_true("유예 종료 시각 파생", bool(sub["grace_period_end"]), sub)
    check("소유자 일치", sub["user_id"], user_a)

    # 소유권 격리 — B는 A의 구독을 볼 수 없다
    rb = client.get("/api/v1/subscriptions/me", headers=auth_headers(user_b)).json()["data"]
    check("B에게 A의 구독이 보이지 않는다", len(rb), 0)

    # lazy sync — 만료 시각을 과거로 밀면 조회만으로 상태가 따라와야 한다
    conn = get_connection()
    try:
        past = (datetime.now() - timedelta(days=10)).isoformat()
        conn.execute("UPDATE subscriptions SET expires_at=? WHERE id=?", (past, sub["id"]))
        conn.commit()
    finally:
        conn.close()
    r2 = client.get("/api/v1/subscriptions/me", headers=auth_headers(user_a)).json()["data"][0]
    check("만료 경과 후 상태가 EXPIRED", r2["effective_status"], "EXPIRED")
    check_true("만료 후에는 이용 불가", not r2["is_entitled"], r2)
    conn = get_connection()
    try:
        stored = conn.execute("SELECT status FROM subscriptions WHERE id=?", (sub["id"],)).fetchone()[0]
    finally:
        conn.close()
    check("lazy sync가 DB 상태도 맞춘다", stored, "EXPIRED")

    # -----------------------------------------------------------------------
    # 31-B. Admin의 변경이 사용자 상태에 그대로 반영되는가 (2026-08-12 Sprint 64 신규)
    #
    # 그동안 Admin 변경(§27)과 사용자 조회(§31)가 **서로 만난 적이 없었다** — 각자 자기
    # 쪽만 확인했다. 그런데 이 둘이 어긋나면 "관리자 화면에서는 해지했는데 사용자는 계속
    # 이용 가능"이라는, 과금에 직접 영향을 주는 모순이 조용히 성립한다.
    # 한 구독을 **세 관점**(사용자 조회 / Admin 목록 / 이용권 게이트)에서 동시에 본다.
    # -----------------------------------------------------------------------
    from api.v1.registry import has_active_subscription
    from api.constants import ErrorCode

    ah = {"X-Admin-Key": TEST_ADMIN_KEY}
    sh = {"X-Admin-Key": TEST_SUPER_ADMIN_KEY}
    user_c = TEST_USER + "-mysub-c"

    def three_views(sub_id, user_id):
        """사용자 조회 / Admin 목록 / 이용권 게이트를 한 번에 본다."""
        mine = [s for s in client.get("/api/v1/subscriptions/me",
                                      headers=auth_headers(user_id)).json()["data"]
                if s["id"] == sub_id]
        adm = [s for s in client.get("/api/v1/admin/subscriptions?user_id=%s" % user_id,
                                     headers=ah).json()["data"] if s["id"] == sub_id]
        conn = get_connection()
        try:
            gate = has_active_subscription(conn, user_id)
            db_status = conn.execute("SELECT status FROM subscriptions WHERE id=?",
                                     (sub_id,)).fetchone()[0]
        finally:
            conn.close()
        return (mine[0] if mine else None), (adm[0] if adm else None), gate, db_status

    pay_c = client.post("/api/v1/payments",
                        json={"payment_type": "SUBSCRIPTION", "plan": "PRO",
                              "amount": price, "billing_cycle": BILLING_YEARLY},
                        headers=auth_headers(user_c)).json()
    check_true("C 구독 결제 성공", pay_c["success"], pay_c)
    sub_c = client.get("/api/v1/subscriptions/me", headers=auth_headers(user_c)).json()["data"][0]["id"]

    me_v, adm_v, gate, db_status = three_views(sub_c, user_c)
    check("[ACTIVE] 사용자/Admin status 일치", (me_v["status"], adm_v["status"]), ("ACTIVE", "ACTIVE"))
    check("[ACTIVE] effective_status 일치", me_v["effective_status"], adm_v["effective_status"])
    check("[ACTIVE] 이용권 게이트가 사용자 표시와 일치", gate, me_v["is_entitled"])
    check("[ACTIVE] 게이트 True", gate, True)

    # Admin이 일시정지 -> 사용자는 즉시 이용 불가여야 한다
    rp = client.patch("/api/v1/admin/subscriptions/%d" % sub_c,
                      json={"status": "PAUSED", "reason": "qa"}, headers=sh)
    check("Admin PAUSED 성공", rp.status_code, 200)
    me_v, adm_v, gate, db_status = three_views(sub_c, user_c)
    check("[PAUSED] 사용자 조회에 반영", me_v["status"], "PAUSED")
    check("[PAUSED] Admin 목록에 반영", adm_v["status"], "PAUSED")
    check("[PAUSED] DB에도 반영", db_status, "PAUSED")
    check("[PAUSED] effective_status 일치", me_v["effective_status"], adm_v["effective_status"])
    check("[PAUSED] 사용자는 이용 불가", me_v["is_entitled"], False)
    check("[PAUSED] 이용권 게이트도 차단", gate, False)

    # 재개하면 이용권이 되살아나야 한다 (되돌릴 수 없으면 CS가 복구를 못 한다)
    rr = client.patch("/api/v1/admin/subscriptions/%d" % sub_c,
                      json={"status": "ACTIVE", "reason": "qa resume"}, headers=sh)
    check("Admin 재개 성공", rr.status_code, 200)
    me_v, adm_v, gate, db_status = three_views(sub_c, user_c)
    check("[재개] 사용자 조회 ACTIVE", me_v["status"], "ACTIVE")
    check("[재개] 이용권 회복", me_v["is_entitled"], True)
    check("[재개] 게이트도 회복", gate, True)

    # Admin이 해지 -> 사용자는 이용 불가 + 등기부 신청이 구독 요구로 막혀야 한다.
    # (해지했는데 계속 무료로 쓸 수 있으면 그대로 매출 누수다)
    rc = client.patch("/api/v1/admin/subscriptions/%d" % sub_c,
                      json={"status": "CANCELLED", "reason": "qa cancel"}, headers=sh)
    check("Admin 해지 성공", rc.status_code, 200)
    me_v, adm_v, gate, db_status = three_views(sub_c, user_c)
    check("[해지] 사용자 조회 CANCELLED", me_v["status"], "CANCELLED")
    check("[해지] Admin 목록 CANCELLED", adm_v["status"], "CANCELLED")
    check("[해지] DB CANCELLED", db_status, "CANCELLED")
    check("[해지] effective_status 일치", me_v["effective_status"], adm_v["effective_status"])
    check("[해지] 사용자 이용 불가", me_v["is_entitled"], False)
    check("[해지] 이용권 게이트 차단", gate, False)

    reg = client.post("/api/v1/registry-requests",
                      json={"item_id": pick_item_ids(1)[0]}, headers=auth_headers(user_c))
    check("[해지] 등기부 신청이 구독 요구로 막힌다",
          reg.json()["error"], ErrorCode.REGISTRY_SUBSCRIPTION_REQUIRED.value)
    check_true("[해지] 신청 행이 생기지 않는다", reg.json()["data"] is None, reg.json())


# ---------------------------------------------------------------------------
# 30. Webhook 수신 (2026-08-11 Sprint 52 신설)
#
# **인증 없는 공개 경로**라 서명 검증이 유일한 방어선이다. 그래서 이 섹션의 첫 번째 관심사는
# "정상 동작"이 아니라 **"검증 없이 상태를 바꿀 수 없는가"** 다.
# ---------------------------------------------------------------------------
WEBHOOK_SECRET = "qa-regression-webhook-secret"


def _sign(body_bytes):
    import hashlib as _h, hmac as _hm
    return _hm.new(WEBHOOK_SECRET.encode(), body_bytes, _h.sha256).hexdigest()


def _post_webhook(payload, provider="mock", signed=True, secret=None):
    body = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if signed:
        sig = _sign(body) if secret is None else __import__("hmac").new(
            secret.encode(), body, __import__("hashlib").sha256).hexdigest()
        headers["X-Webhook-Signature"] = sig
    return client.post("/api/v1/payments/webhook/%s" % provider, content=body, headers=headers)


def test_payment_webhook():
    print("\n--- 30. payment webhook ---")
    saved = os.environ.get("PAYMENT_WEBHOOK_SECRET")

    # --- 시크릿 미설정이면 어떤 요청도 통과하지 못한다(fail-closed) ---
    os.environ.pop("PAYMENT_WEBHOOK_SECRET", None)
    user = TEST_USER + "-wh-closed"
    pid, _ = _make_paid_payment(user)
    conn = get_connection()
    try:
        txid = conn.execute("SELECT pg_transaction_id FROM payments WHERE id=?", (pid,)).fetchone()[0]
    finally:
        conn.close()
    r = _post_webhook({"event_id": "qa-wh-closed-1", "event_type": "PAYMENT_CANCELLED",
                       "pg_transaction_id": txid})
    check("시크릿 미설정이면 401(fail-closed)", r.status_code, 401)

    os.environ["PAYMENT_WEBHOOK_SECRET"] = WEBHOOK_SECRET
    try:
        # --- 서명 없는/틀린 요청은 상태를 바꾸지 못한다 ---
        user = TEST_USER + "-wh-authz"
        pid, _ = _make_paid_payment(user)
        conn = get_connection()
        try:
            txid = conn.execute("SELECT pg_transaction_id FROM payments WHERE id=?", (pid,)).fetchone()[0]
        finally:
            conn.close()

        check("서명 없으면 401",
              _post_webhook({"event_id": "qa-wh-nosig", "event_type": "PAYMENT_CANCELLED",
                             "pg_transaction_id": txid}, signed=False).status_code, 401)
        check("서명이 틀리면 401",
              _post_webhook({"event_id": "qa-wh-badsig", "event_type": "PAYMENT_CANCELLED",
                             "pg_transaction_id": txid}, secret="wrong-secret").status_code, 401)

        def status_of(payment_id):
            c = get_connection()
            try:
                return c.execute("SELECT status FROM payments WHERE id=?", (payment_id,)).fetchone()[0]
            finally:
                c.close()

        check("위조 요청은 결제 상태를 바꾸지 못했다", status_of(pid), "SUCCESS")

        # ★ 검증 실패는 **저장하지 않는다**(2026-08-11 Sprint 53 변경).
        # 인증 없는 공개 경로라 익명 요청 하나당 행 하나가 무제한으로 늘어나는
        # 저장소 증폭 통로였다(실측: 서명 없는 요청 5회 -> 행 5개). 탐지에 필요한 정보는
        # 경고 로그로 남긴다 — 로그는 회전되지만 DB는 계속 쌓이기 때문이다.
        conn = get_connection()
        try:
            stored = conn.execute(
                "SELECT COUNT(*) FROM payment_webhooks"
                " WHERE event_id IN ('qa-wh-nosig','qa-wh-badsig')").fetchone()[0]
        finally:
            conn.close()
        check("검증 실패 요청은 DB에 저장되지 않는다", stored, 0)

        # 저장소 증폭 방어: 익명 요청을 반복해도 행이 늘지 않아야 한다.
        conn = get_connection()
        try:
            n_before = conn.execute("SELECT COUNT(*) FROM payment_webhooks").fetchone()[0]
        finally:
            conn.close()
        for i in range(5):
            _post_webhook({"event_id": "qa-wh-flood-%d" % i}, signed=False)
        conn = get_connection()
        try:
            n_after = conn.execute("SELECT COUNT(*) FROM payment_webhooks").fetchone()[0]
        finally:
            conn.close()
        check("익명 요청 5회가 행을 만들지 않는다", n_after - n_before, 0)

        check("알 수 없는 provider는 404",
              _post_webhook({"event_id": "qa-wh-prov"}, provider="nope").status_code, 404)

        # --- 정상 적용 ---
        user = TEST_USER + "-wh-apply"
        pid, _ = _make_paid_payment(user)
        conn = get_connection()
        try:
            txid = conn.execute("SELECT pg_transaction_id FROM payments WHERE id=?", (pid,)).fetchone()[0]
        finally:
            conn.close()
        r = _post_webhook({"event_id": "qa-wh-apply-1", "event_type": "PAYMENT_REFUNDED",
                           "pg_transaction_id": txid})
        check("정상 서명 200", r.status_code, 200)
        body = r.json()["data"]
        check("적용됨", body["result"], "APPLIED")
        check("전이 to", body["to"], "REFUNDED")
        check("결제 상태 반영", status_of(pid), "REFUNDED")

        # --- 멱등: 같은 event_id 재전송 ---
        r = _post_webhook({"event_id": "qa-wh-apply-1", "event_type": "PAYMENT_REFUNDED",
                           "pg_transaction_id": txid})
        check("중복 event_id도 200", r.status_code, 200)
        check_true("중복으로 표시", r.json()["data"]["duplicate"])
        check("중복은 적용하지 않음", r.json()["data"]["result"], "SKIPPED")
        conn = get_connection()
        try:
            rows = conn.execute(
                "SELECT COUNT(*) FROM payment_webhooks WHERE event_id='qa-wh-apply-1'").fetchone()[0]
            applied = conn.execute(
                "SELECT COUNT(*) FROM payment_logs WHERE payment_id=? AND event_type='WEBHOOK'",
                (pid,)).fetchone()[0]
        finally:
            conn.close()
        check("중복 수신은 행을 새로 만들지 않는다", rows, 1)
        check("중복 수신은 WEBHOOK 로그를 두 번 남기지 않는다", applied, 1)

        # --- 상태머신이 막는 전이는 반영하지 않는다 ---
        r = _post_webhook({"event_id": "qa-wh-invalid", "event_type": "PAYMENT_CONFIRMED",
                           "pg_transaction_id": txid})
        check("REFUNDED -> PAID 전이는 적용되지 않음", r.json()["data"]["result"], "SKIPPED")
        check("상태는 그대로 REFUNDED", status_of(pid), "REFUNDED")

        # --- 알 수 없는 event_type / 모르는 거래 ---
        check("알 수 없는 event_type은 무시",
              _post_webhook({"event_id": "qa-wh-unknown", "event_type": "SOMETHING_ELSE",
                             "pg_transaction_id": txid}).json()["data"]["result"], "SKIPPED")
        check("모르는 거래는 무시",
              _post_webhook({"event_id": "qa-wh-notx", "event_type": "PAYMENT_CANCELLED",
                             "pg_transaction_id": "NOPE-does-not-exist"}).json()["data"]["result"],
              "SKIPPED")

        # --- 깨진 payload ---
        bad = b"{not json"
        check("깨진 payload는 400",
              client.post("/api/v1/payments/webhook/mock", content=bad,
                          headers={"X-Webhook-Signature": _sign(bad),
                                   "Content-Type": "application/json"}).status_code, 400)

        # --- 서명 검증이 payload 변조를 잡는가(서명 후 본문 변경) ---
        original = json.dumps({"event_id": "qa-wh-tamper", "event_type": "PAYMENT_CANCELLED",
                               "pg_transaction_id": txid}).encode()
        tampered = json.dumps({"event_id": "qa-wh-tamper", "event_type": "PAYMENT_CONFIRMED",
                               "pg_transaction_id": txid}).encode()
        check("본문 변조 시 401",
              client.post("/api/v1/payments/webhook/mock", content=tampered,
                          headers={"X-Webhook-Signature": _sign(original),
                                   "Content-Type": "application/json"}).status_code, 401)
    finally:
        if saved is None:
            os.environ.pop("PAYMENT_WEBHOOK_SECRET", None)
        else:
            os.environ["PAYMENT_WEBHOOK_SECRET"] = saved
        # 이 섹션이 만든 webhook 행 정리
        conn = get_connection()
        try:
            conn.execute("DELETE FROM payment_webhooks WHERE event_id LIKE 'qa-wh-%'")
            conn.commit()
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# 32. Webhook 운영 도구 (2026-08-11 Sprint 53) — 조회 / 상세 / 재처리
#
# 핵심 관심사는 **재처리가 보안 경계를 뚫지 않는가**다. 서명이 검증되지 않은 수신을
# 운영자 손으로 적용할 수 있으면 Sprint 52의 서명 검증이 통째로 무의미해진다.
# ---------------------------------------------------------------------------
def test_webhook_ops():
    print("\n--- 32. webhook ops (list / detail / reprocess) ---")
    ah = {"X-Admin-Key": TEST_ADMIN_KEY}
    sh = {"X-Admin-Key": TEST_SUPER_ADMIN_KEY}
    saved = os.environ.get("PAYMENT_WEBHOOK_SECRET")
    os.environ["PAYMENT_WEBHOOK_SECRET"] = WEBHOOK_SECRET

    def status_of(pid):
        c = get_connection()
        try:
            return c.execute("SELECT status FROM payments WHERE id=?", (pid,)).fetchone()[0]
        finally:
            c.close()

    def webhook_row(wid):
        return client.get("/api/v1/admin/payments/webhooks/%d" % wid, headers=ah).json()["data"]

    try:
        # --- 권한 경계 ---
        check("Webhook 목록은 인증 필요",
              client.get("/api/v1/admin/payments/webhooks").status_code, 403)
        check("Webhook 목록은 ADMIN으로 조회 가능",
              client.get("/api/v1/admin/payments/webhooks", headers=ah).status_code, 200)
        check("재처리는 ADMIN 등급으로 불가(SUPER_ADMIN 전용)",
              client.post("/api/v1/admin/payments/webhooks/1/reprocess", headers=ah).status_code, 403)
        check("없는 Webhook 상세는 404",
              client.get("/api/v1/admin/payments/webhooks/99999999", headers=ah).status_code, 404)
        check("없는 Webhook 재처리는 404",
              client.post("/api/v1/admin/payments/webhooks/99999999/reprocess", headers=sh).status_code, 404)
        check("허용되지 않는 processing_status 필터는 400",
              client.get("/api/v1/admin/payments/webhooks?processing_status=NOPE",
                         headers=ah).status_code, 400)

        # --- 실제 재처리 시나리오: PG 노티가 payments row보다 먼저 도착 ---
        # (수신 시점에는 거래를 못 찾아 IGNORED, 나중에 재처리하면 성공해야 한다)
        user = TEST_USER + "-whops"
        future_tx = "MOCK-whops-" + uuid.uuid4().hex[:10]
        # event_type은 **상태머신이 허용하는 전이**여야 한다 — 결제는 SUCCESS로 생성되고
        # SUCCESS에서 갈 수 있는 곳은 PARTIAL_REFUND/REFUNDED뿐이다(PAYMENT_CANCELLED를 쓰면
        # 재처리해도 상태머신이 막아 SKIPPED가 된다 — 첫 작성에서 실제로 그렇게 헛나갔다).
        r = _post_webhook({"event_id": "qa-wh-ops-early", "event_type": "PAYMENT_REFUNDED",
                           "pg_transaction_id": future_tx})
        check("이른 노티는 200으로 접수", r.status_code, 200)
        check("적용되지 않음(거래 없음)", r.json()["data"]["result"], "SKIPPED")
        wid = r.json()["data"]["webhook_id"]
        row = webhook_row(wid)
        check("상태 IGNORED", row["processing_status"], "IGNORED")
        check_true("실패 사유가 보인다", bool(row["error_message"]), row)
        check_true("재처리 가능으로 표시", row["reprocessable"], row)
        check("차단 사유 없음", row["reprocess_blocked_reason"], None)

        # 뒤늦게 결제가 생긴 상황을 만든다(같은 pg_transaction_id)
        pid, _ = _make_paid_payment(user)
        conn = get_connection()
        try:
            conn.execute("UPDATE payments SET pg_transaction_id=? WHERE id=?", (future_tx, pid))
            conn.commit()
        finally:
            conn.close()

        rr = client.post("/api/v1/admin/payments/webhooks/%d/reprocess" % wid, headers=sh)
        check("재처리 200", rr.status_code, 200)
        data = rr.json()["data"]
        check("이번엔 적용됨", data["result"], "APPLIED")
        check_true("재처리로 실행됐음을 명시", data["reprocessed"], data)
        check("이전 상태를 알려준다", data["previous_status"], "IGNORED")
        check("결제 상태가 반영됨", status_of(pid), "REFUNDED")

        # --- 중복 재처리 방지 ---
        row = webhook_row(wid)
        check("재처리 후 PROCESSED", row["processing_status"], "PROCESSED")
        check_true("더 이상 재처리 대상이 아니다", not row["reprocessable"], row)
        again = client.post("/api/v1/admin/payments/webhooks/%d/reprocess" % wid, headers=sh)
        check("두 번째 재처리는 400", again.status_code, 400)
        check("결제 상태는 그대로", status_of(pid), "REFUNDED")

        # --- 보안 경계: 서명 미검증 수신은 절대 재처리 불가 ---
        bad = _post_webhook({"event_id": "qa-wh-ops-unsigned", "event_type": "PAYMENT_CONFIRMED",
                             "pg_transaction_id": future_tx}, signed=False)
        check("서명 없는 수신은 401", bad.status_code, 401)
        conn = get_connection()
        try:
            stored = conn.execute(
                "SELECT COUNT(*) FROM payment_webhooks WHERE event_id='qa-wh-ops-unsigned'"
            ).fetchone()[0]
        finally:
            conn.close()
        # 2026-08-11 Sprint 53: 미검증 요청은 **행 자체를 만들지 않는다**(저장소 증폭 차단).
        check("미검증 요청은 수신 기록을 만들지 않는다", stored, 0)

        # ★ 그래도 서명 가드는 살아 있어야 한다 — **방어를 한 겹에만 의존하지 않기 위해서다.**
        # 지금은 미검증 행이 애초에 생기지 않지만, 나중에 다른 경로가(예: 배치 임포트, 마이그레이션)
        # 미검증 행을 만들 수 있다. 그때 재처리로 적용되면 서명 검증이 통째로 무의미해진다.
        # 그런 행을 직접 만들어 **상태와 무관하게 미검증이면 막히는가**를 격리 검증한다.
        # (재처리 가능한 상태 IGNORED로 두어, FAILED 가드가 아니라 서명 가드가 막는지 확인한다)
        conn = get_connection()
        try:
            legacy_id = conn.execute(
                "INSERT INTO payment_webhooks (provider, event_type, event_id, pg_transaction_id,"
                " signature_verified, processing_status, raw_payload, received_at)"
                " VALUES ('mock','PAYMENT_CONFIRMED','qa-wh-ops-legacy-unverified',?,0,'IGNORED',?,?)",
                (future_tx, json.dumps({"event_type": "PAYMENT_CONFIRMED",
                                        "pg_transaction_id": future_tx}),
                 datetime.now().isoformat()),
            ).lastrowid
            conn.commit()
        finally:
            conn.close()
        row = webhook_row(legacy_id)
        check("가드 격리: 상태는 재처리 가능 범위", row["processing_status"], "IGNORED")
        check_true("가드 격리: 그래도 미검증이라 재처리 불가", not row["reprocessable"], row)
        check_true("가드 격리: 차단 사유가 서명 때문임을 명시",
                   "서명" in (row["reprocess_blocked_reason"] or ""),
                   row["reprocess_blocked_reason"])
        check("가드 격리: 재처리 시도 400",
              client.post("/api/v1/admin/payments/webhooks/%d/reprocess" % legacy_id,
                          headers=sh).status_code, 400)
        check("가드 격리: 결제 상태 불변", status_of(pid), "REFUNDED")

        # --- 목록 필터 ---
        lst = client.get("/api/v1/admin/payments/webhooks?processing_status=PROCESSED",
                         headers=ah).json()
        check_true("PROCESSED 필터가 동작", all(i["processing_status"] == "PROCESSED"
                                            for i in lst["data"]), lst["data"][:2])
        check_true("meta.total 제공", "total" in lst["meta"], lst["meta"])
        unv = client.get("/api/v1/admin/payments/webhooks?signature_verified=false",
                         headers=ah).json()["data"]
        check_true("미검증 필터가 동작", all(not i["signature_verified"] for i in unv), unv[:2])
        check_true("미검증은 전부 재처리 불가", all(not i["reprocessable"] for i in unv), unv[:2])
        ro = client.get("/api/v1/admin/payments/webhooks?reprocessable_only=true",
                        headers=ah).json()
        check_true("reprocessable_only는 가능한 것만", all(i["reprocessable"] for i in ro["data"]),
                   ro["data"][:2])
        check_true("필터 사실을 meta에 명시", ro["meta"]["reprocessable_only"] is True, ro["meta"])

        # --- 감사 로그 ---
        audit = client.get("/api/v1/admin/audit-logs?target_type=PAYMENT", headers=ah).json()["data"]
        mine = [a for a in audit if str(a["target_id"]) == str(pid)]
        check_true("재처리가 감사 로그에 남는다", len(mine) >= 1, [a["target_id"] for a in audit[:5]])
    finally:
        if saved is None:
            os.environ.pop("PAYMENT_WEBHOOK_SECRET", None)
        else:
            os.environ["PAYMENT_WEBHOOK_SECRET"] = saved
        conn = get_connection()
        try:
            # ★ 순서가 중요하다: 감사 행을 **먼저** 지운다.
            # PAYMENT_WEBHOOK 감사의 target_id는 payment_webhooks.id인데, webhook 행을 먼저
            # 지우면 아래 cleanup()이 그 id를 더 이상 알 수 없어 감사 행만 남는다
            # (실제로 dangling 1건으로 검출됐다 — Sprint 53).
            ids = [str(r[0]) for r in conn.execute(
                "SELECT id FROM payment_webhooks WHERE event_id LIKE 'qa-wh-%'")]
            if ids:
                placeholders = ",".join("?" * len(ids))
                conn.execute(
                    "DELETE FROM audit_logs WHERE target_type='PAYMENT_WEBHOOK'"
                    " AND target_id IN (%s)" % placeholders, ids)
            conn.execute("DELETE FROM payment_webhooks WHERE event_id LIKE 'qa-wh-%'")
            conn.commit()
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# 33. 인증 경계 전수 (2026-08-11 Sprint 53 신규)
#
# §4(authentication)는 **하드코딩된 5개 경로**만 검사했다. 그래서 새 엔드포인트를 추가해도
# 인증 경계 검증이 자동으로 따라오지 않았다 — 실제로 Sprint 52~53에 6개가 늘었지만
# §4의 목록은 그대로였다.
#
# 여기서는 OpenAPI 스펙에서 **모든 엔드포인트를 열거**해 익명 접근을 검사한다.
# 분류되지 않은 새 엔드포인트가 나타나면 테스트가 실패하므로, 추가할 때 공개/사용자/관리자
# 중 무엇인지 **반드시 의식적으로 선언**하게 된다(EXPECTED_ENDPOINTS와 같은 규율).
# ---------------------------------------------------------------------------
# 인증 없이 접근 가능한 것으로 **의도된** 경로.
# `/payments/webhook/{provider}`는 사용자 인증이 없지만 서명 검증이 대신하므로 여기 둔다
# (익명 요청은 401이어야 한다 — 아래에서 따로 확인).
PUBLIC_ENDPOINTS = {
    "/",
    "/api/v1/stats",
    "/api/v1/document-stats",
    "/api/v1/search",
    "/api/v1/search/regions",
    "/api/v1/item/{item_id}",
    "/api/v1/item/{item_id}/documents/{doc_type}",
    "/api/v1/plans",
}
# 사용자 인증은 없지만 다른 수단(서명)으로 보호되는 경로.
SIGNATURE_PROTECTED_ENDPOINTS = {"/api/v1/payments/webhook/{provider_name}"}

_PATH_SAMPLE = {
    "{item_id}": "1", "{payment_id}": "1", "{preset_id}": "1", "{request_id}": "1",
    "{doc_type}": "SPEC", "{user_id}": "qa-authz-probe", "{subscription_id}": "1",
    "{webhook_id}": "1", "{provider_name}": "mock",
}


def test_authz_coverage():
    print("\n--- 33. 인증 경계 전수 (OpenAPI 기반) ---")
    api_server.app.openapi_schema = None
    spec = api_server.app.openapi()

    unclassified, leaks = [], []
    checked = {"public": 0, "user": 0, "admin": 0, "signature": 0}

    for path, ops in sorted(spec["paths"].items()):
        probe = path
        for token, sample in _PATH_SAMPLE.items():
            probe = probe.replace(token, sample)
        for method in ops:
            if path in PUBLIC_ENDPOINTS:
                kind = "public"
            elif path in SIGNATURE_PROTECTED_ENDPOINTS:
                kind = "signature"
            elif "/admin/" in path:
                kind = "admin"
            elif path.startswith("/api/v1/"):
                kind = "user"
            else:
                unclassified.append((method.upper(), path))
                continue
            checked[kind] += 1

            body = {} if method in ("post", "patch", "put") else None
            code = client.request(method.upper(), probe, json=body).status_code

            if kind == "public":
                # 공개 경로는 인증 때문에 막히면 안 된다(파라미터 부족으로 인한 422/404는 무방).
                if code in (401, 403):
                    leaks.append(("public blocked", method.upper(), path, code))
            else:
                # 나머지는 전부 익명 거부여야 한다.
                # 401/403이 아니면 **인증 없이 도달 가능**하다는 뜻이다.
                if code not in (401, 403):
                    leaks.append(("anon reachable", method.upper(), path, code))

    check_true("분류되지 않은 신규 엔드포인트 없음", not unclassified, unclassified)
    check_true("익명 접근이 가능한 보호 엔드포인트 없음", not leaks, leaks)
    check_true("검사 대상이 실제로 존재한다",
               checked["user"] >= 10 and checked["admin"] >= 10, checked)
    print("   분류: %s" % checked)

    # 인증이 **body 검증보다 먼저** 동작하는지 — 그래야 스키마 정보가 익명에게 새지 않는다.
    # (POST에 빈 body를 보냈을 때 422가 아니라 401이어야 한다)
    check("POST 익명 요청은 body 검증 전에 401",
          client.post("/api/v1/payments", json={}).status_code, 401)
    check("Admin POST 익명 요청은 body 검증 전에 403",
          client.post("/api/v1/admin/registry-credits", json={}).status_code, 403)

    # 서명 보호 경로는 익명이면 401이어야 한다(공개처럼 열려 있으면 안 된다).
    # event_id는 cleanup 패턴(qa-wh-)을 따라야 한다 — 처음엔 'qa-authz'로 썼다가 정리되지
    # 않고 남아, 다음 실행에서 **중복 경로**를 타 200이 나왔다(그 덕에 아래 oracle 결함을 발견).
    check("Webhook은 서명 없이 401",
          client.post("/api/v1/payments/webhook/mock",
                      json={"event_id": "qa-wh-authz"}).status_code, 401)
    # ★ 같은 event_id로 한 번 더 — **중복이어도** 서명이 없으면 401이어야 한다.
    # 예전에는 중복 검사가 서명 검사보다 먼저라 이 경우 200이 나왔고, 익명 공격자가
    # "이 event_id가 존재하는가"를 응답 코드로 알아낼 수 있었다(oracle).
    # 지금은 검증 전에 저장 자체를 하지 않으므로 중복 판정에 도달하지도 않는다.
    check("중복 event_id여도 서명 없으면 401(존재 여부 oracle 차단)",
          client.post("/api/v1/payments/webhook/mock",
                      json={"event_id": "qa-wh-authz"}).status_code, 401)
    conn = get_connection()
    try:
        leaked = conn.execute(
            "SELECT COUNT(*) FROM payment_webhooks WHERE event_id='qa-wh-authz'").fetchone()[0]
    finally:
        conn.close()
    check("미검증 요청은 행을 남기지 않는다(저장소 증폭 차단)", leaked, 0)

    # 사용자 간 격리 — 남의 결제/로그는 404로 존재조차 알리지 않는다.
    owner, other = TEST_USER + "-authz-a", TEST_USER + "-authz-b"
    pid, _ = _make_paid_payment(owner)
    check("남의 결제 조회는 404",
          client.get("/api/v1/payments/%d" % pid, headers=auth_headers(other)).status_code, 404)
    check("남의 결제 로그 조회는 404",
          client.get("/api/v1/payments/%d/logs" % pid, headers=auth_headers(other)).status_code, 404)
    check("본인은 조회 가능",
          client.get("/api/v1/payments/%d" % pid, headers=auth_headers(owner)).status_code, 200)


# ---------------------------------------------------------------------------
# cleanup: 이 테스트가 만든 행만 정리한다(실제 사용자 데이터는 건드리지 않음)
# ---------------------------------------------------------------------------
def cleanup():
    print("\n--- cleanup (test user rows only) ---")
    conn = get_connection()
    try:
        like = "qa-reg-%"
        total = 0

        # audit_logs / payment_webhooks는 user_id 컬럼이 없어 위 루프로는 지워지지 않는다.
        # 그래서 실행할 때마다 QA 행이 쌓여 왔다(2026-08-11 Sprint 52에 785행 누적 발견 —
        # 운영자가 감사 로그를 조회할 때 테스트 흔적이 섞여 보이는 상태였다).
        # 지울 대상 id를 **부모 행을 지우기 전에** 미리 뽑아 정확히 그 행만 제거한다.
        audit_targets = {
            "PAYMENT": [str(r[0]) for r in conn.execute(
                "SELECT id FROM payments WHERE user_id LIKE ?", (like,))],
            "REGISTRY_REQUEST": [str(r[0]) for r in conn.execute(
                "SELECT id FROM registry_requests WHERE user_id LIKE ?", (like,))],
            "SUBSCRIPTION": [str(r[0]) for r in conn.execute(
                "SELECT id FROM subscriptions WHERE user_id LIKE ?", (like,))],
            # REGISTRY_CREDIT 감사의 target_id는 registry_credits.id다(user_id가 아니다 —
            # admin.py:377이 credit_id를 넘긴다). 이 표를 빠뜨려서 509행이 쌓여 있었다.
            "REGISTRY_CREDIT": [str(r[0]) for r in conn.execute(
                "SELECT id FROM registry_credits WHERE user_id LIKE ?", (like,))],
            # 결제에 연결되지 못한 Webhook 재처리 감사(2026-08-11 Sprint 53).
            # target_id가 payment_webhooks.id다.
            "PAYMENT_WEBHOOK": [str(r[0]) for r in conn.execute(
                "SELECT id FROM payment_webhooks WHERE event_id LIKE 'qa-wh-%'")],
        }
        qa_tx_ids = [r[0] for r in conn.execute(
            "SELECT pg_transaction_id FROM payments WHERE user_id LIKE ? AND pg_transaction_id IS NOT NULL",
            (like,))]

        # FK가 런타임에 강제되므로 자식 -> 부모 순서로 지운다.
        for table in ("registry_credit_logs", "registry_requests", "registry_usage",
                      "payment_logs", "payments", "subscriptions", "favorites",
                      "recent_items", "search_presets", "registry_credits"):
            cur = conn.execute("DELETE FROM %s WHERE user_id LIKE ?" % table, (like,))
            total += cur.rowcount

        for target_type, ids in audit_targets.items():
            if not ids:
                continue
            placeholders = ",".join("?" * len(ids))
            cur = conn.execute(
                "DELETE FROM audit_logs WHERE target_type=? AND target_id IN (%s)" % placeholders,
                [target_type] + ids)
            total += cur.rowcount
        # REGISTRY_CREDIT 감사는 target_id가 user_id 문자열이다(정수 id가 아님).
        total += conn.execute(
            "DELETE FROM audit_logs WHERE target_id LIKE ?", (like,)).rowcount
        if qa_tx_ids:
            placeholders = ",".join("?" * len(qa_tx_ids))
            total += conn.execute(
                "DELETE FROM payment_webhooks WHERE pg_transaction_id IN (%s)" % placeholders,
                qa_tx_ids).rowcount
        total += conn.execute(
            "DELETE FROM payment_webhooks WHERE event_id LIKE 'qa-wh-%'").rowcount

        conn.commit()
        print("removed %d test rows" % total)
        left = conn.execute("SELECT COUNT(*) FROM registry_requests WHERE user_id LIKE ?", (like,)).fetchone()[0]
        check("no test rows left", left, 0)

        # 이 정리 루틴은 `qa-reg-%`(자동 회귀가 만드는 유일한 접두사)만 지운다. 그런데
        # 과거 **수동 QA**가 `qa-download-001`/`qa-race-001`처럼 다른 `qa-` 접두사를 썼고,
        # 그 행들은 어떤 정리에도 걸리지 않아 운영 DB에 그대로 남아 있었다
        # (2026-08-12 Sprint 61에 `recent_items` 10행 발견·제거 — 전부 2026-08-05자).
        # 접두사를 넓혀 확인만 한다(삭제는 하지 않는다 — 남의 데이터일 수 있으므로).
        stray = []
        for table in ("registry_requests", "registry_usage", "payments", "subscriptions",
                      "favorites", "recent_items", "search_presets", "registry_credits"):
            n = conn.execute(
                "SELECT COUNT(*) FROM %s WHERE user_id LIKE 'qa-%%' AND user_id NOT LIKE ?" % table,
                (like,)).fetchone()[0]
            if n:
                stray.append("%s=%d" % (table, n))
        check("no stray qa-* rows outside qa-reg-* (manual QA residue)", stray, [])
        # 이번 실행이 만든 감사 흔적도 남지 않아야 한다.
        # ★ 부모 행을 이미 지웠으므로 "현재 존재하는 qa 결제"로 되묻는 서브쿼리는 항상 0을
        #   돌려준다(공허하게 참). 삭제 **전에 캡처해 둔 id**로 확인해야 실제 검출력이 있다.
        audit_left = 0
        for target_type, ids in audit_targets.items():
            if not ids:
                continue
            placeholders = ",".join("?" * len(ids))
            audit_left += conn.execute(
                "SELECT COUNT(*) FROM audit_logs WHERE target_type=? AND target_id IN (%s)"
                % placeholders, [target_type] + ids).fetchone()[0]
        check("no test audit rows left", audit_left, 0)
        # 대상이 사라진 감사 행(dangling)이 남아 있으면 정리 규칙에 구멍이 있다는 뜻이다.
        dangling = conn.execute("""
            SELECT COUNT(*) FROM audit_logs a WHERE
              (a.target_type='PAYMENT'          AND NOT EXISTS (SELECT 1 FROM payments t          WHERE CAST(t.id AS TEXT)=a.target_id))
           OR (a.target_type='REGISTRY_REQUEST' AND NOT EXISTS (SELECT 1 FROM registry_requests t WHERE CAST(t.id AS TEXT)=a.target_id))
           OR (a.target_type='SUBSCRIPTION'     AND NOT EXISTS (SELECT 1 FROM subscriptions t     WHERE CAST(t.id AS TEXT)=a.target_id))
           OR (a.target_type='REGISTRY_CREDIT'  AND NOT EXISTS (SELECT 1 FROM registry_credits t  WHERE CAST(t.id AS TEXT)=a.target_id))
           OR (a.target_type='PAYMENT_WEBHOOK'  AND NOT EXISTS (SELECT 1 FROM payment_webhooks t  WHERE CAST(t.id AS TEXT)=a.target_id))
        """).fetchone()[0]
        check("no dangling audit rows left", dangling, 0)
        check("no test webhook rows left",
              conn.execute("SELECT COUNT(*) FROM payment_webhooks WHERE event_id LIKE 'qa-wh-%'").fetchone()[0], 0)
    finally:
        conn.close()


def run():
    try:
        test_health_and_stats()
        test_search()
        test_property_type_aliases()
        test_detail_and_documents()
        test_authentication()
        test_favorites()
        test_recent_items()
        test_search_presets()
        test_payment_and_subscription()
        test_registry()
        test_registry_overage_flow()
        test_admin()
        test_payment_providers()
        test_deterministic_ordering()
        test_subscription_plan_tiebreak()
        test_plans_api()
        test_api_surface()
        test_response_envelope()
        test_cors_configuration()
        test_admin_roles()
        test_registry_credits()
        test_payment_logs()
        test_auction_identity_keys()
        test_foreign_key_enforcement()
        test_payment_state_machine()
        test_subscription_lifecycle()
        test_audit_and_credit_logs()
        test_admin_rest_structure()
        test_soft_delete_columns()
        test_refund()
        test_payment_webhook()
        test_my_subscriptions()
        test_webhook_ops()
        test_authz_coverage()
    finally:
        cleanup()

    print("\n" + "=" * 60)
    if failures:
        print("FAILED (%d): %s" % (len(failures), ", ".join(failures)))
        return 1
    print("ALL API REGRESSION TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(run())
