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
import sqlite3
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ★ 운영 `auction.db` 를 건드리지 않는다 (2026-08-25). 이 파일은 `get_connection()` 으로
#   합성 행을 심고 지우는데, 예전에는 그 대상이 **운영 DB 자체**였다. 끝에 지우므로
#   행수는 원복돼 아무도 몰랐지만, `sqlite_sequence` 는 영구히 전진했고(1회 실측:
#   search_presets +210 / payment_logs +112 / registry_requests +53 ...) 중간에 죽으면
#   지우는 코드에 도달하지 못해 합성 행이 운영 테이블에 그대로 남았다.
#
#   `test_admin_failure_injection.py` 와 같은 방식으로 임시 사본에 대고 돌린다.
#   `get_connection()` 은 `sqlite3.connect(DB_PATH)` 로 **호출 시점에** 모듈 전역을
#   읽으므로, 이 재지정 한 줄이 API 라우터까지 함께 돌린다(제품 코드 중 `DB_PATH` 를
#   직접 import 하는 곳은 없다 - 2026-08-25 전수 확인). 문서 파일은 사본을 만들지
#   않고 저장소 루트 기준으로 그대로 읽힌다(읽기만 한다).
#
#   감시는 `run_python_tests.py` 가 한다 - 파일마다 운영 DB 지문을 재서 바뀌면
#   그 파일을 지목하고 게이트를 붉게 만든다. 경위는 docs/BUGS.md #186.
import atexit as _qa_atexit
import shutil as _qa_shutil
import tempfile as _qa_tempfile
import storage.database as _qa_dbmod
_qa_tmp = _qa_tempfile.mkdtemp(prefix="dojoonpass-qa-")
_qa_atexit.register(_qa_shutil.rmtree, _qa_tmp, True)
_qa_scratch = os.path.join(_qa_tmp, "auction.db")
if os.path.exists(_qa_dbmod.DB_PATH):
    _qa_shutil.copy2(_qa_dbmod.DB_PATH, _qa_scratch)
_qa_dbmod.DB_PATH = _qa_scratch

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

    # 2026-08-16 Sprint 141 신설 — document_queue 적체 규모. 운영자가 API/Admin
    # 어디서도 이 큐 크기를 볼 수 없어서 doc_worker.py 스케줄 미등록이 최소 5주간
    # (2026-07-08 최초 대기 건 기준) 발견되지 않았다(docs/SPRINT141_SCHEDULER_STATUS_CORRECTION.md).
    # 세 값 전부 자기 출처(document_queue.status)와 직접 대조한다.
    conn = get_connection()
    try:
        queue_pairs = {row[0]: row[1] for row in conn.execute(
            "SELECT status, COUNT(*) FROM document_queue GROUP BY status")}
    finally:
        conn.close()
    # ★ 상태 이름을 여기에 베껴 적지 않는다 (2026-08-18 Sprint 190).
    #   Sprint 189가 큐 어휘를 늘리자(refresh / in_progress_refresh) 이 검사가
    #   **틀렸는데도 통과하는 상태**가 됐다 — 아직 그 값을 가진 행이 실 DB에 없어서다.
    #   `queue_in_progress`는 이제 두 진행 상태의 합인데, 여기서는 `in_progress`
    #   하나만 세고 있었다. 첫 재수집이 도는 날 조용히 어긋난다.
    #   BUGS #119("하드코딩 목록은 결함 없음과 아직 그 값이 안 나타났을 뿐을
    #   구분하지 못한다")와 정확히 같은 부류라, 단일 소스에서 가져온다.
    from storage.database import (
        QUEUE_STATUS_PENDING, QUEUE_STATUS_REFRESH, QUEUE_IN_PROGRESS_STATUSES,
    )

    check("document-stats queue_pending = document_queue(status=pending) 건수",
          stats["queue_pending"], queue_pairs.get(QUEUE_STATUS_PENDING, 0))
    check("document-stats queue_refresh = document_queue(status=refresh) 건수",
          stats["queue_refresh"], queue_pairs.get(QUEUE_STATUS_REFRESH, 0))
    check("document-stats queue_in_progress = 진행 상태 두 갈래의 합",
          stats["queue_in_progress"],
          sum(queue_pairs.get(v, 0) for v in QUEUE_IN_PROGRESS_STATUSES))
    check("document-stats queue_failed = document_queue(status=failed) 건수",
          stats["queue_failed"], queue_pairs.get("failed", 0))

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

    # ── D7 경계: **오늘이 매각기일인 물건은 보여야 한다** (2026-08-13 Sprint 79) ──
    #
    # 위 검사는 "include_closed를 켜면 건수가 같거나 는다"만 본다. 그래서 기본 필터가
    # `auction_date >= today`에서 `> today`로 바뀌어도 **그대로 통과한다.**
    #
    # 그 한 글자가 바뀌면 **매각 당일 아침에 그 물건이 검색에서 사라진다.** 사용자가 가장
    # 절실하게 찾는 시점에 사라지는 셈이라, 경계를 데이터로 못박아 둔다.
    # (실측 2026-08-13 기준 오늘이 기일인 물건이 0건이라 기존 데이터로는 확인할 수 없다 —
    #  그래서 어제/오늘/내일 픽스처를 직접 만든다.)
    d7_case = "QA-D7-%d" % int(datetime.now().timestamp())
    conn = get_connection()
    made_ids = []
    try:
        try:
            case_id = conn.execute(
                "INSERT INTO auction_case (court_code, case_no) VALUES (?,?)",
                ("서울중앙지방법원", d7_case)).lastrowid
            for label, offset in (("yesterday", -1), ("today", 0), ("tomorrow", 1)):
                d = (datetime.now() + timedelta(days=offset)).strftime("%Y-%m-%d")
                made_ids.append(conn.execute(
                    "INSERT INTO auction_item"
                    " (case_id, case_no, item_no, court_name, auction_date, full_address,"
                    "  appraisal_price, minimum_bid_price)"
                    " VALUES (?,?,?,?,?,?,?,?)",
                    (case_id, d7_case, label, "서울중앙지방법원", d,
                     "서울특별시 강남구 역삼동 1", 100000000, 70000000)).lastrowid)
            conn.commit()

            def d7_dates(qs):
                r = client.get("/api/v1/search?size=50&case_no=%s&%s" % (d7_case, qs))
                return sorted(i["auction_date"] for i in r.json()["items"])

            today_str = datetime.now().strftime("%Y-%m-%d")
            tomorrow_str = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
            yesterday_str = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

            default_dates = d7_dates("")
            check("D7 기본: 오늘과 내일만 보인다", default_dates, [today_str, tomorrow_str])
            check_true("D7 기본: 오늘이 기일인 물건이 포함된다", today_str in default_dates,
                       default_dates)
            check_true("D7 기본: 어제 기일인 물건은 빠진다", yesterday_str not in default_dates,
                       default_dates)

            all_dates = d7_dates("include_closed=true")
            check("include_closed=true면 셋 다 보인다", all_dates,
                  [yesterday_str, today_str, tomorrow_str])

            # auction_date_from을 명시하면 D7 기본값을 적용하지 않는다(기존 계약).
            explicit = d7_dates("auction_date_from=%s" % yesterday_str)
            check("auction_date_from 명시는 기본 필터를 대체한다", explicit,
                  [yesterday_str, today_str, tomorrow_str])
        finally:
            if made_ids:
                conn.execute("DELETE FROM auction_item WHERE id IN (%s)"
                             % ",".join("?" * len(made_ids)), made_ids)
            conn.execute("DELETE FROM auction_case WHERE case_no=?", (d7_case,))
            conn.commit()
    finally:
        conn.close()

    # 픽스처가 남지 않았는지 확인한다(남으면 다음 실행의 건수 검사를 오염시킨다).
    leftover = client.get("/api/v1/search?include_closed=true&case_no=%s" % d7_case).json()["total"]
    check("D7 픽스처가 정리됐다", leftover, 0)

    # SQL Injection 시도가 파라미터 바인딩으로 무해하게 처리되는지
    r = client.get("/api/v1/search?sido=' OR 1=1--")
    check("injection attempt safe", r.status_code, 200)
    check("injection returns no rows", r.json()["total"], 0)

    # 나머지 문자열 파라미터도 같은지 (2026-08-14 신설).
    #
    # 위 `sido` 한 줄만으로는 부족하다. WHERE 조각을 만드는 파라미터는 여럿이고,
    # 뚫리는 곳은 **검사하지 않은 쪽**이다. 페이로드가 값으로 취급되면 결과가 0건이어야 한다
    # (기준 total 과 같아지면 조건이 "항상 참"이 됐다는 뜻이다).
    #
    # 조립 구조 자체는 `test_schema_hygiene.py` 의 SQL 텍스트 보간 검사가 지킨다.
    # 여기서는 **실제 요청**으로 확인한다 ― 두 검사가 같은 것을 다른 방법으로 본다.
    base_total = client.get("/api/v1/search?size=1").json()["total"]
    for field in ("sigungu", "dong", "case_no", "court_name", "status", "address_detail"):
        for payload in ("' OR '1'='1", "'; DROP TABLE auction_item; --", "%' OR 1=1 --"):
            rr = client.get("/api/v1/search", params={field: payload, "size": 1})
            check_true("injection %s 는 200" % field, rr.status_code == 200,
                       "HTTP %s / %s" % (rr.status_code, payload))
            if rr.status_code == 200:
                check_true("injection %s 는 값으로 취급" % field, rr.json()["total"] == 0,
                           "total=%s (기준 %s) payload=%r"
                           % (rr.json()["total"], base_total, payload))

    # 정렬은 값 바인딩이 불가능해 화이트리스트가 유일한 방어다 ― 밖이면 거부해야 한다.
    # (조용히 기본값으로 넘어가면 "정렬이 먹지 않는다"는 버그로만 보이고 방어는 안 보인다.)
    for bad in ("id; DROP TABLE auction_item", "auction_date; --", "(SELECT 1)"):
        check("sort_by 화이트리스트 밖 거부",
              client.get("/api/v1/search", params={"sort_by": bad}).status_code, 400)
    for bad in ("asc; DROP TABLE x", "DESC--"):
        check("sort_order 화이트리스트 밖 거부",
              client.get("/api/v1/search", params={"sort_order": bad}).status_code, 400)

    # 테이블이 살아 있는가 ― 위 시도 중 하나라도 성립했으면 여기서 드러난다.
    check_true("인젝션 시도 후에도 auction_item 이 살아 있다",
               client.get("/api/v1/search?size=1").status_code == 200)

    # regions
    r = client.get("/api/v1/search/regions?sido=서울")
    check("regions status", r.status_code, 200)
    check_true("regions returns list", isinstance(r.json()["sigungu"], list))


# ---------------------------------------------------------------------------
# 2-B. 물건종류 어휘 별칭 (docs/BUGS.md #33, 2026-08-11 Sprint 51 신규)
# ---------------------------------------------------------------------------
# 2-C. address_detail 의도 분기 (2026-08-13 Sprint 90 신규)
#
# `address_detail`은 검색 화면의 **주소 상세** 입력이다. 사용자가 무엇을 적었는지를
# `intent.analyzer`가 해석하고, `api/v1/search.py:build_address_condition()`이 그에 맞는
# SQL 조건을 만든다. 그런데 이 파라미터는 **API 레벨 검사가 0건**이었다
# (커버리지가 LOT_NUMBER 분기와 MIXED의 sido 가지를 미커버로 지목했다).
#
# 의도별로 조건이 완전히 다르다.
#
#     "서울"                -> SIDO          sido = ?
#     "강남구"               -> SIGUNGU       sigungu LIKE ?
#     "역삼동"               -> DONG          dong LIKE ?
#     "609-10"             -> LOT_NUMBER    lot_number = ?        <- 미커버였다
#     "서울 강남구 역삼동"      -> FULL_ADDRESS  세 조건 AND
#     "서울 아파트"           -> MIXED         sido + 잔여어         <- sido 가지가 미커버였다
#
# 200만 보고 통과시키지 않는다. **반환된 행이 실제로 그 조건에 맞는지**까지 본다
# (Sprint 49가 정렬/페이지에서 세운 원칙과 같다 - 조건이 통째로 무시돼도 200은 나온다).
#
# 기대 건수는 단언하지 않는다. DB에서 실제 물건 하나를 뽑아 그 값으로 검색하므로
# 데이터가 바뀌어도 유효하다.
# ---------------------------------------------------------------------------
def test_address_detail_intents():
    print("\n--- 2-C. address_detail 의도 분기 (Sprint 90) ---")
    conn = get_connection()
    try:
        sample = conn.execute(
            "SELECT id, sido, sigungu, dong, lot_number FROM auction_item"
            " WHERE sido != '' AND sigungu != '' AND dong != '' AND lot_number != ''"
            " LIMIT 1"
        ).fetchone()
    finally:
        conn.close()
    if not sample:
        print("[SKIP] 주소 4요소가 모두 있는 물건이 없다")
        return

    sido, sigungu = sample["sido"], sample["sigungu"]
    dong, lot = sample["dong"], sample["lot_number"]

    def search(detail, **extra):
        params = {"size": 100, "include_closed": "true", "address_detail": detail}
        params.update(extra)
        r = client.get("/api/v1/search", params=params)
        check("address_detail=%r 는 200" % detail, r.status_code, 200)
        return r.json()

    # (1) SIDO — 반환된 모든 행의 sido가 정확히 일치해야 한다(LIKE가 아니라 =).
    body = search(sido)
    check_true("SIDO: 결과가 있다", body["total"] > 0, body["total"])
    off = [i["sido"] for i in body["items"] if i["sido"] != sido]
    check("SIDO: 다른 시도가 섞이지 않는다", off, [])

    # (2) SIGUNGU — LIKE라 부분 일치를 허용하지만 그 값을 포함해야 한다.
    body = search(sigungu)
    check_true("SIGUNGU: 결과가 있다", body["total"] > 0, body["total"])
    off = [i["sigungu"] for i in body["items"] if sigungu not in (i["sigungu"] or "")]
    check("SIGUNGU: 조건과 무관한 시군구가 없다", off, [])

    # (3) DONG
    body = search(dong)
    check_true("DONG: 결과가 있다", body["total"] > 0, body["total"])
    off = [i["dong"] for i in body["items"] if dong not in (i["dong"] or "")]
    check("DONG: 조건과 무관한 동이 없다", off, [])

    # (4) ★ LOT_NUMBER — 지번은 **정확히 일치**해야 한다(LIKE가 아니다).
    #
    # 검사가 실제로 구분력을 가지려면 **다른 지번의 부분문자열인 지번**을 써야 한다.
    # 처음엔 임의의 지번을 썼는데, 그 값이 다른 어떤 지번에도 포함되지 않아
    # `=`를 LIKE로 바꾸는 변이가 **그대로 통과했다**(결과가 같았다).
    # 이제 상위 문자열이 존재하는 지번을 DB에서 직접 골라, LIKE가 되면
    # "19"가 "342-19"·"619-2"까지 끌어오는 것이 드러나게 한다.
    conn = get_connection()
    try:
        distinguishing = conn.execute(
            "SELECT a.id, a.lot_number FROM auction_item a"
            " WHERE a.lot_number != '' AND EXISTS ("
            "   SELECT 1 FROM auction_item b"
            "   WHERE b.lot_number != a.lot_number"
            "     AND b.lot_number LIKE '%' || a.lot_number || '%')"
            " LIMIT 1"
        ).fetchone()
    finally:
        conn.close()
    # 지번을 바꾸면 "그 물건이 결과에 있는가"의 기준 id도 함께 바꿔야 한다.
    lot_sample_id = sample["id"]
    if distinguishing:
        lot = distinguishing["lot_number"]
        lot_sample_id = distinguishing["id"]
    else:
        print("[NOTE] 부분문자열 관계인 지번이 없어 LIKE/= 구분력이 약하다")

    body = search(lot)
    check_true("LOT_NUMBER: 결과가 있다", body["total"] > 0, body["total"])
    # 검색 응답 항목에는 lot_number가 없다(row_to_item이 내려주지 않는다).
    # 반환된 id를 DB로 되짚어 확인한다 — 직렬화가 아니라 **SQL 필터 자체**를 보는 셈이라
    # 오히려 더 강한 검사다.
    ids = [i["id"] for i in body["items"]]
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT id, lot_number FROM auction_item WHERE id IN (%s)"
            % ",".join("?" * len(ids)), ids).fetchall() if ids else []
    finally:
        conn.close()
    off = [(r["id"], r["lot_number"]) for r in rows if r["lot_number"] != lot]
    check("LOT_NUMBER: 지번이 정확히 일치한다", off, [])
    check_true("LOT_NUMBER: 그 지번의 물건이 결과에 있다",
               any(i["id"] == lot_sample_id for i in body["items"]),
               [i["id"] for i in body["items"]][:5])

    # (5) FULL_ADDRESS — 세 조건이 AND로 걸린다.
    body = search("%s %s %s" % (sido, sigungu, dong))
    check_true("FULL_ADDRESS: 결과가 있다", body["total"] > 0, body["total"])
    bad = [i["id"] for i in body["items"]
           if i["sido"] != sido or sigungu not in (i["sigungu"] or "")
           or dong not in (i["dong"] or "")]
    check("FULL_ADDRESS: 세 조건이 모두 적용된다", bad, [])
    # 좁은 조건이 넓은 조건보다 결과가 많을 수는 없다.
    sido_total = search(sido)["total"]
    check_true("FULL_ADDRESS는 SIDO보다 넓지 않다", body["total"] <= sido_total,
               "%d > %d" % (body["total"], sido_total))

    # (6) ★ MIXED — 지역어 + 잔여어. sido 가지가 실제로 걸리는지 본다.
    mixed = search("%s 아파트" % sido)
    off = [i["sido"] for i in mixed["items"] if i["sido"] != sido]
    check("MIXED: sido 조건이 적용된다", off, [])
    check_true("MIXED는 SIDO보다 넓지 않다", mixed["total"] <= sido_total,
               "%d > %d" % (mixed["total"], sido_total))

    # MIXED는 세 요소가 각각 독립적으로 붙는다. sido만 검증하면 나머지 두 가지가
    # 통째로 빠져도 드러나지 않는다 — "시군구 + 동" 조합으로 나머지 가지도 확인한다.
    mixed2 = search("%s %s" % (sigungu, dong))
    bad2 = [i["id"] for i in mixed2["items"]
            if sigungu not in (i["sigungu"] or "") or dong not in (i["dong"] or "")]
    check("MIXED: 시군구와 동 조건이 함께 적용된다", bad2, [])
    check_true("MIXED(시군구+동)는 시군구 단독보다 넓지 않다",
               mixed2["total"] <= search(sigungu)["total"],
               "%d > %d" % (mixed2["total"], search(sigungu)["total"]))

    # (6-B) 검색도 선택적 인증이다 — 토큰이 잘못돼도 200이고 비로그인으로 처리된다.
    #
    # item.py와 같은 분기인데(Sprint 88), 검색 쪽은 **BUGS #27이 살았던 자리**다:
    # ES256 전환 후 HS256만 검증하던 시절 로그인 사용자의 하트가 전부 빈 하트로 내려갔다.
    # 그때는 예외가 아니라 **조용한 오답**이었으므로, 200만 보지 말고 is_favorited까지 본다.
    bad_tok = {"Authorization": "Bearer not-a-jwt"}
    leaked = None
    r_badtok = None
    try:
        r_badtok = client.get("/api/v1/search",
                              params={"size": 5, "include_closed": "true"}, headers=bad_tok)
    except Exception as exc:
        leaked = exc
    check_true("검색: 잘못된 토큰에 예외가 새어 나오지 않는다", leaked is None,
               "선택적 인증의 except JWTError가 사라졌는가? 검색이 통째로 500이 된다: %r"
               % (leaked,))
    if r_badtok is not None:
        check("검색: 잘못된 토큰이어도 200", r_badtok.status_code, 200)
        hearts = {i["is_favorited"] for i in r_badtok.json()["items"]}
        check("검색: 잘못된 토큰이면 하트가 켜지지 않는다", hearts - {False}, set())

    # (7) 해석할 수 없는 입력은 결과를 0으로 만들되 오류가 아니다.
    unknown = search("존재하지않는지역명입니다")
    check("UNKNOWN 입력도 200이고 오류가 아니다", unknown["total"], 0)

    # (8) 빈 문자열은 조건을 걸지 않는다(전체와 같아야 한다).
    all_total = client.get("/api/v1/search",
                           params={"size": 1, "include_closed": "true"}).json()["total"]
    check("빈 address_detail은 조건을 걸지 않는다", search("")["total"], all_total)


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
    #
    # 2026-08-13 Sprint 85: 상태코드를 직접 꺼내지 않고 감싼다. TestClient는 서버 예외를
    # 그대로 올리므로, 엔드포인트가 500이 되는 결함이 생기면 이 줄에서 **스위트 전체가
    # 크래시**했다(변이 테스트로 확인: doc_type 검사를 없앤 변이가 FAIL 0건 + 크래시로
    # 끝나 집계에서 사라졌다). 예외를 None으로 바꿔 기대값과 어긋나게 만든다.
    def doc_status(item, doc_type, method="GET"):
        try:
            return client.request(method, "/api/v1/item/%s/documents/%s" % (item, doc_type)).status_code
        except Exception as exc:  # noqa: BLE001
            print("      (서버 예외: %r)" % (exc,))
            return None

    check("document bad type", doc_status(item_id, "INVALID"), 400)
    get_status = doc_status(item_id, "SPEC")
    check_true("document known type", get_status in (200, 404), get_status)

    # HEAD 프로브 — properties/[id]/page.tsx가 문서 뷰어를 열기 전에 실제로 호출하는
    # 엔드포인트다(docCheckKey). GET/HEAD를 별도 라우트로 분리한 이유(OpenAPI Duplicate
    # Operation ID 회피, docs/CHANGELOG.md Sprint 26)가 유지되는지, 응답 상태코드가 GET과
    # 항상 같은지 여기서 처음으로 자동 검증한다(이전까지 이 라우트는 테스트 0건이었다).
    head_status = doc_status(item_id, "SPEC", method="HEAD")
    check("HEAD status matches GET status", head_status, get_status)
    check("HEAD on bad doc type -> 400", doc_status(item_id, "INVALID", method="HEAD"), 400)
    check("HEAD on nonexistent item -> 404", doc_status(99999999, "SPEC", method="HEAD"), 404)

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

    # --- 2026-08-13 Sprint 88: 토큰이 잘못돼도 상세는 비로그인으로 보인다 ---
    #
    # 커버리지가 지목했다: `api/v1/item.py`의 `except JWTError: user_id = None`(52-54행)이
    # 미커버였다. 상세 조회는 **선택적 인증**이다 — 토큰이 있으면 최근조회를 기록하고,
    # 없거나 잘못됐으면 비로그인으로 그냥 보여준다.
    #
    # 이 분기가 없으면 **토큰이 만료된 사용자가 물건 상세를 열 때 오류를 본다.**
    # 세션 만료는 정상적인 일상이고, 그때 화면이 깨지면 안 된다.
    # (401도 아니다 — 비로그인도 볼 수 있는 화면인데 401을 주면 로그인 강요가 된다)
    detail_id = pick_item_ids(1)[0]
    for label, token in (("깨진 토큰", "not-a-jwt"),
                         ("빈 문자열", ""),
                         ("서명이 틀린 토큰",
                          auth_headers("qa-reg-x")["Authorization"][7:] + "tampered")):
        # except JWTError가 사라지면 예외가 그대로 올라와 **스위트가 크래시**한다.
        # 그 형태로 끝나면 원인이 안 보이므로 붙잡아 깔끔한 FAIL로 바꾼다.
        r_bad = None
        leaked = None
        try:
            r_bad = client.get("/api/v1/item/%d" % detail_id,
                               headers={"Authorization": "Bearer " + token})
        except Exception as exc:
            leaked = exc
        check_true("%s에 예외가 새어 나오지 않는다" % label, leaked is None,
                   "선택적 인증의 except JWTError가 사라졌는가? "
                   "세션 만료만으로 상세 화면이 깨진다: %r" % (leaked,))
        if r_bad is None:
            continue
        check("%s이어도 상세는 200" % label, r_bad.status_code, 200)
        check("%s이어도 본문은 정상" % label, r_bad.json()["id"], detail_id)

    # 토큰이 없을 때와 같은 결과여야 한다(잘못된 토큰 = 비로그인 취급).
    anon = client.get("/api/v1/item/%d" % detail_id).json()
    broken = client.get("/api/v1/item/%d" % detail_id,
                        headers={"Authorization": "Bearer not-a-jwt"}).json()
    # 전체 dict를 check()로 비교하면 실패 시 본문 두 개가 통째로 찍혀 읽을 수 없다.
    # 같은지 여부는 그대로 단언하되, **다른 키만** 골라 보여준다.
    diff_keys = sorted(k for k in set(anon) | set(broken) if anon.get(k) != broken.get(k))
    check_true("잘못된 토큰의 응답이 비로그인과 같다", not diff_keys,
               "다른 키: %s" % diff_keys)
    # 개인화 필드가 켜지지 않았는지 직접 확인한다(위 비교가 통과해도 명시적으로 못박는다).
    check("잘못된 토큰에 is_favorited가 켜지지 않는다", broken.get("is_favorited"), False)

    # 그리고 잘못된 토큰으로는 최근조회가 기록되지 않아야 한다 —
    # 기록됐다면 그 user_id는 검증되지 않은 값이다.
    conn = get_connection()
    try:
        before_rows = conn.execute("SELECT COUNT(*) FROM recent_items").fetchone()[0]
    finally:
        conn.close()
    client.get("/api/v1/item/%d" % detail_id,
               headers={"Authorization": "Bearer not-a-jwt"})
    conn = get_connection()
    try:
        after_rows = conn.execute("SELECT COUNT(*) FROM recent_items").fetchone()[0]
    finally:
        conn.close()
    check("잘못된 토큰은 최근조회를 남기지 않는다", after_rows, before_rows)

    # --- 2026-08-13 Sprint 80: 기록 실패가 상세 조회를 막으면 안 된다 ---
    #
    # `api/v1/item.py`는 record_view()를 try/except로 감싸고 실패해도 계속 진행한다.
    #
    #     try:
    #         record_view(conn, user_id, item_id)
    #     except Exception:
    #         logger.warning("최근조회 기록 실패 ...", exc_info=True)
    #
    # 의도는 분명하다 — **부가 기능(최근조회)의 실패가 본 기능(물건 상세)을 무너뜨리면
    # 안 된다.** 그런데 그 계약이 검증된 적이 없었다. except를 지우거나 raise로 바꾸면
    # DB 잠금 한 번에 **상세 화면 전체가 500**이 되는데, 기존 검사는 전부 정상 경로만 탄다.
    #
    # 반대쪽도 함께 고정한다 — 조용히 삼키기만 하고 아무 흔적도 안 남기면 원인 추적이
    # 불가능해진다. 그래서 경고 로그가 실제로 남는지까지 본다.
    import logging as _logging
    import api.v1.item as item_mod

    fail_item_id = pick_item_ids(1)[0]
    fail_user = "qa-reg-recordview-" + uuid.uuid4().hex[:6]
    original_record_view = item_mod.record_view
    captured = []

    class _Capture(_logging.Handler):
        def emit(self, record):
            captured.append(record.getMessage())

    def _boom(conn, user_id, item_id):
        # 실제로 일어날 법한 실패를 흉내 낸다 — DB 잠금이 대표적이다.
        # (이 파일은 sqlite3을 import하지 않으므로 지역 import로 정확한 예외 타입을 쓴다)
        import sqlite3 as _sqlite3
        raise _sqlite3.OperationalError("database is locked (주입된 실패)")

    handler = _Capture()
    item_logger = _logging.getLogger("api.v1.item")
    item_logger.addHandler(handler)
    item_mod.record_view = _boom
    r_fail = None
    propagated = None
    try:
        # 예외가 그대로 새어 나오면 TestClient가 **그것을 다시 던진다** — 500 응답이 아니라
        # 스위트가 통째로 죽는다. 그 형태로 끝나면 원인이 안 보이므로 여기서 붙잡아
        # 깔끔한 FAIL로 바꾼다. 가드는 실패할 때 무엇이 잘못됐는지 말해야 한다.
        try:
            r_fail = client.get("/api/v1/item/%d" % fail_item_id, headers=auth_headers(fail_user))
        except Exception as exc:
            propagated = exc
    finally:
        item_mod.record_view = original_record_view
        item_logger.removeHandler(handler)

    check_true("기록 실패가 상세 조회 밖으로 새어 나오지 않는다", propagated is None,
               "record_view의 예외가 그대로 전파됐다(try/except가 사라졌는가?): %r" % (propagated,))
    if r_fail is not None:
        check("최근조회 기록이 실패해도 상세는 200", r_fail.status_code, 200)
        # item 상세는 envelope를 쓰지 않는다(search/item 예외 — docs/CLAUDE.md).
        check("실패해도 상세 본문은 정상", r_fail.json()["id"], fail_item_id)
    check_true("기록 실패가 경고 로그로 남는다",
               any("최근조회" in m for m in captured),
               "조용히 삼키면 원인 추적이 불가능하다: %r" % captured)

    conn = get_connection()
    try:
        left = conn.execute("SELECT COUNT(*) FROM recent_items WHERE user_id=?",
                            (fail_user,)).fetchone()[0]
    finally:
        conn.close()
    check("실패했으므로 최근조회 행은 생기지 않는다", left, 0)

    # 주입을 되돌린 뒤에는 다시 정상 기록되어야 한다(패치가 남지 않았는지 확인).
    client.get("/api/v1/item/%d" % fail_item_id, headers=auth_headers(fail_user))
    conn = get_connection()
    try:
        after = conn.execute("SELECT COUNT(*) FROM recent_items WHERE user_id=?",
                             (fail_user,)).fetchone()[0]
        conn.execute("DELETE FROM recent_items WHERE user_id=?", (fail_user,))
        conn.commit()
    finally:
        conn.close()
    check("주입 해제 후에는 정상 기록된다", after, 1)

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

    # (4) 저장 자체도 20건으로 잘린다 (2026-08-22 신설) — (3)은 화면 응답(SELECT LIMIT)만
    # 본다. 그런데 예전에는 `record_view()`가 정리 없이 INSERT만 해서, 화면은 항상 20건만
    # 보여줘도 `recent_items` 테이블 자체는 사용자가 서로 다른 물건을 볼 때마다 한 행씩
    # **무한정** 쌓였다(28행 = 위에서 심은 3 + 여기서 새로 본 25). 화면 뒤에서 저장공간이
    # 계속 느는 것은 기능 결함은 아니지만 방치하면 커진다 - 저장 쪽도 같은 상한으로 잠근다.
    conn = get_connection()
    try:
        raw_count = conn.execute(
            "SELECT COUNT(*) FROM recent_items WHERE user_id=?", (TEST_USER,)).fetchone()[0]
    finally:
        conn.close()
    check("recent_items 원본 테이블도 20건으로 정리된다(무한정 누적 안 함)", raw_count, 20)


def test_favorites_and_recent_items_survive_orphaned_auction_item():
    """`auction_item` 행이 없어져도 favorites/recent_items 조회가 조용히 항목을 지우지
    않고, 대신 로그로 남긴다 (2026-08-23 Sprint 267).

    admin.py:320이 이미 registry_requests에 대해 이 문제를 고쳤다 — INNER JOIN이던
    시절 `auction_item` 행이 사라진 신청이 관리자 목록에서 **아무 신호 없이** 사라졌다
    (011~013처럼 FK를 끄고 재작성하는 마이그레이션 중 대상 행이 빠지면 이 상태가 됨).
    같은 `auction_item.id` 참조 패턴을 쓰는 favorites/recent_items는 그 수정에서
    빠져 있었다 — 이 검사가 없으면 그 공백이 재발해도 아무도 모른다.
    """
    print("\n--- 6-b. favorites/recent_items가 삭제된 auction_item에도 안전하다 (Sprint 267) ---")
    import logging as _logging

    class _Capture(_logging.Handler):
        def emit(self, record):
            captured.append(record.getMessage())

    captured = []

    fav_user = "qa-reg-orphanfav-" + uuid.uuid4().hex[:6]
    ri_user = "qa-reg-orphanri-" + uuid.uuid4().hex[:6]
    ghost_id = 900000000  # 실제 auction_item에 존재하지 않는 id (FK 없이 직접 심는다)

    conn = get_connection()
    try:
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute(
            "INSERT INTO favorites (user_id, item_id, created_at) VALUES (?, ?, datetime('now','localtime'))",
            (fav_user, ghost_id))
        conn.execute(
            "INSERT INTO recent_items (user_id, item_id, viewed_at) VALUES (?, ?, datetime('now','localtime'))",
            (ri_user, ghost_id))
        conn.commit()
    finally:
        conn.close()

    fav_handler, ri_handler = _Capture(), _Capture()
    fav_logger = _logging.getLogger("api.v1.favorites")
    ri_logger = _logging.getLogger("api.v1.recent_items")
    fav_logger.addHandler(fav_handler)
    ri_logger.addHandler(ri_handler)
    try:
        r_fav = client.get("/api/v1/favorites", headers=auth_headers(fav_user))
        r_ri = client.get("/api/v1/recent-items", headers=auth_headers(ri_user))
    finally:
        fav_logger.removeHandler(fav_handler)
        ri_logger.removeHandler(ri_handler)

    check("고아 favorite이 있어도 목록 조회는 200", r_fav.status_code, 200)
    check("고아 recent_item이 있어도 목록 조회는 200", r_ri.status_code, 200)
    check_true("고아 favorite은 목록에 안 보인다(깨진 카드 노출 안 함)",
               all(i["id"] != ghost_id for i in r_fav.json()["data"]))
    check_true("고아 recent_item은 목록에 안 보인다(깨진 카드 노출 안 함)",
               all(i["id"] != ghost_id for i in r_ri.json()["data"]))
    check_true("★ favorites 고아가 조용히 사라지지 않고 로그에 남는다",
               any(fav_user in m for m in captured),
               "조용히 삼키면 원인 추적이 불가능하다: %r" % captured)
    check_true("★ recent_items 고아가 조용히 사라지지 않고 로그에 남는다",
               any(ri_user in m for m in captured),
               "조용히 삼키면 원인 추적이 불가능하다: %r" % captured)

    conn = get_connection()
    try:
        conn.execute("DELETE FROM favorites WHERE user_id=?", (fav_user,))
        conn.execute("DELETE FROM recent_items WHERE user_id=?", (ri_user,))
        conn.commit()
    finally:
        conn.close()


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

    # ── 손상된 conditions 한 행이 목록 전체를 죽이면 안 된다 ──────────────────
    #   (2026-08-13 Sprint 96, BUGS #95)
    #
    # 고치기 전 실측: 정상 3건 + 손상 1건 -> **GET 전체가 500**. 멀쩡한 검색조건까지
    # 통째로 사라졌다. 그리고 사용자는 **스스로 빠져나올 수 없었다** ― 지우려면
    # preset_id가 필요한데, id를 알 수 있는 유일한 경로가 죽은 그 목록이다.
    #
    # 손상 행은 정상 API로는 만들 수 없다(POST는 항상 유효한 JSON을 쓴다). 그래서
    # DB에 직접 넣는다 ― 레거시 행·수동 복구·부분 쓰기로 생길 수 있는 상태이고,
    # Sprint 95에서 "COMPLETED인데 파일 없음"을 레거시 상태 방어로 남긴 것과 같은 판단이다.
    conn = get_connection()
    try:
        broken_user = TEST_USER + "-broken-preset"
        bh = auth_headers(broken_user)
        now = datetime.now().isoformat()
        conn.execute(
            "INSERT INTO search_presets (user_id, name, conditions, created_at) VALUES (?,?,?,?)",
            (broken_user, "정상", json.dumps({"sido": "서울"}), now))
        conn.execute(
            "INSERT INTO search_presets (user_id, name, conditions, created_at) VALUES (?,?,?,?)",
            (broken_user, "손상", "{not valid json", now))
        # 객체가 아닌 유효 JSON도 같은 취급이어야 한다(리스트/문자열 -> conditions[key]가 깨진다)
        conn.execute(
            "INSERT INTO search_presets (user_id, name, conditions, created_at) VALUES (?,?,?,?)",
            (broken_user, "객체아님", "[1, 2, 3]", now))
        conn.commit()

        # TestClient는 서버 예외를 그대로 다시 던지므로, 가드가 사라지면 이 호출이
        # **테스트를 크래시**시킨다(FAIL 0건에 exit=1). 그러면 무엇이 깨졌는지 알 수 없다.
        # 잡아서 진단으로 바꾼다 ― 이 저장소에서 반복해 겪은 형태다.
        try:
            r = client.get("/api/v1/search-presets", headers=bh)
            status = r.status_code
        except Exception as exc:
            r, status = None, "예외: %r" % (exc,)
        check("손상 행이 있어도 목록은 200 (BUGS #95)", status, 200)
        got = {p["name"]: p["conditions"] for p in r.json()["data"]} if r is not None else {}
        check("멀쩡한 검색조건이 살아남는다", got.get("정상"), {"sido": "서울"})
        check("손상 행은 빈 조건으로 대체된다", got.get("손상"), {})
        check("객체가 아닌 JSON도 빈 조건으로", got.get("객체아님"), {})
        # ★ 핵심: 목록에 보여야 지울 수 있다. 숨기면 영원히 남고 한도만 잡아먹는다.
        broken_id = next((p["id"] for p in (r.json()["data"] if r is not None else [])
                          if p["name"] == "손상"), None)
        check("손상 행을 사용자가 지울 수 있다",
              client.delete("/api/v1/search-presets/%d" % broken_id, headers=bh).status_code
              if broken_id is not None else "목록에서 찾을 수 없다", 200)
    finally:
        conn.execute("DELETE FROM search_presets WHERE user_id=?", (TEST_USER + "-broken-preset",))
        conn.commit()
        conn.close()

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

    # ── 결제 <-> 구독을 잇는 열쇠 (2026-08-13 Sprint 96, BUGS #94) ────────────
    #
    # 구독 결제를 전액 환불해도 구독은 ACTIVE로 남는다 ― 돈은 돌려주고 서비스는 계속
    # 준다(#93 "돈 받고 물건 안 준다"의 거울상). 고치려 해도 **대상을 특정할 수
    # 없었다**: `subscriptions`에 `payment_id`가 없고 `payments`에도 구독 id가 없어서,
    # 두 행을 맞출 방법이 `(user_id, 금액, 시각)` 어림짐작뿐이었다.
    # (`registry_requests`는 진작부터 `payment_id`를 갖고 있다 ― 여기만 끊겨 있었다.)
    #
    # ★ 환불 시 구독을 **어떻게** 할지는 정책 결정 대기라 여기서 정하지 않는다.
    #   그래서 이 검사는 "환불하면 해지된다"를 요구하지 않는다 ― 지금 동작을 정상으로
    #   굳히지도 않는다(Sprint 95에서 겪은 함정: 결함을 굳힌 검사가 수정을 가로막았다).
    #   고정하는 것은 **어떤 정책을 고르든 반드시 있어야 하는 식별자**뿐이다.
    conn = get_connection()
    try:
        linked = conn.execute(
            "SELECT payment_id FROM subscriptions WHERE id=?", (sub["id"],)
        ).fetchone()["payment_id"]
    finally:
        conn.close()
    check("구독이 자신을 산 결제를 가리킨다(BUGS #94)", linked, body["data"]["payment"]["id"])

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

    # Provider 성공 + 그 이후 DB 처리 실패(2026-08-16, Sprint 132) — 위는 "provider가
    # 거절"만 재현했다. 반대 방향(provider는 승인했는데 그 뒤 우리 코드가 죽는 경우)은
    # 아직 아무 테스트도 만든 적이 없었다 — Sprint 129가 고친 "provider 호출보다 락이
    # 먼저"는 레이스 패자가 provider까지 도달하는 것을 막았을 뿐, provider가 정상 승인한
    # **뒤에** DB 쪽에서 예외가 나는 경우는 별개 경로다(BEGIN IMMEDIATE 안에서
    # create_subscription()이 죽는 경우). MockProvider는 실패를 만들지 않으므로
    # create_subscription() 자체를 강제로 예외를 던지도록 바꿔 재현한다.
    #
    # 기대: 같은 트랜잭션이므로 payments/payment_logs까지 전부 롤백되어 고아가 남지
    # 않아야 하고(승인만 되고 기록은 없는 반쪽 상태 금지), 이어지는 재시도는 정상
    # 성공해야 한다.
    db_fail_user = TEST_USER + "-dbfail"
    hdb = auth_headers(db_fail_user)
    _orig_create_sub = payments_module.create_subscription

    def _boom(*_a, **_kw):
        raise RuntimeError("qa-injected-post-provider-db-failure")

    payments_module.create_subscription = _boom
    try:
        try:
            boom_r = client.post("/api/v1/payments",
                                 json={"payment_type": "SUBSCRIPTION", "plan": "BASIC",
                                       "amount": resolve_plan_price("BASIC", BILLING_MONTHLY),
                                       "billing_cycle": BILLING_MONTHLY}, headers=hdb)
            check("provider 성공 후 DB 예외는 500", boom_r.status_code, 500)
        except RuntimeError as e:
            # TestClient는 기본적으로 서버 예외를 그대로 올린다(raise_server_exceptions=True) —
            # FastAPI가 500으로 바꿔 주는 것은 실제 uvicorn 하에서만이다. 여기서는 "예외가
            # 그대로 escape했다"는 사실 자체가 "커밋되지 않았다"는 확신을 준다(핸들러가
            # 끝까지 실행돼 return에 도달하지 못했다는 뜻이므로).
            check_true("provider 성공 후 DB 예외가 그대로 전파된다(요청이 조용히 성공하지 않았다)",
                      "qa-injected-post-provider-db-failure" in str(e))
    finally:
        payments_module.create_subscription = _orig_create_sub

    conn = get_connection()
    try:
        orphan_sub = conn.execute(
            "SELECT COUNT(*) FROM subscriptions WHERE user_id=?", (db_fail_user,)).fetchone()[0]
        orphan_pay = conn.execute(
            "SELECT COUNT(*) FROM payments WHERE user_id=?", (db_fail_user,)).fetchone()[0]
        orphan_log = conn.execute(
            "SELECT COUNT(*) FROM payment_logs WHERE user_id=?", (db_fail_user,)).fetchone()[0]
    finally:
        conn.close()
    check("DB 예외 시 subscription 고아 없음(롤백됨)", orphan_sub, 0)
    check("DB 예외 시 payment 고아 없음(provider 승인 기록도 함께 롤백됨)", orphan_pay, 0)
    check("DB 예외 시 payment_logs 고아 없음", orphan_log, 0)

    # provider가 원상복구된 뒤 재시도는 정상 성공해야 한다 — 앞선 예외가 커넥션/상태를
    # 오염시켜 다음 요청까지 막지 않는지 확인한다.
    retry2 = client.post("/api/v1/payments",
                         json={"payment_type": "SUBSCRIPTION", "plan": "BASIC",
                               "amount": resolve_plan_price("BASIC", BILLING_MONTHLY),
                               "billing_cycle": BILLING_MONTHLY}, headers=hdb)
    retry2_body = retry2.json()
    check("DB 예외 후 재시도는 정상 성공", retry2_body["success"], True)
    check("DB 예외 후 재시도가 구독을 만든다", retry2_body["data"]["subscription"]["plan"], "BASIC")

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

    # ── 본인 신청 상세 조회의 응답 계약 (2026-08-13 Sprint 93) ──────────────────
    #
    # 커버리지가 지목했다: `get_registry_request()`의 `return success(...)`가 미커버였다.
    # **404(타인 접근)만 검증되고 200(본인 조회)은 한 번도 실행된 적이 없었다.**
    #
    # 즉 이 엔드포인트가 실제로 무엇을 돌려주는지 아무도 확인하지 않았다. 응답에서 키가
    # 하나 빠지거나 이름이 바뀌어도 검사는 전부 통과한다 — 프런트가 읽는 값인데도 그렇다.
    own = client.get("/api/v1/registry-requests/%d" % req_id, headers=h)
    check("본인 신청 상세는 200", own.status_code, 200)
    own_data = own.json()["data"]
    check("상세가 요청한 신청을 돌려준다", own_data["id"], req_id)
    # 필드 집합을 고정한다 — 늘어나는 것은 허용(추가 필드는 하위호환), 사라지면 실패한다.
    for key in ("id", "item_id", "case_no", "full_address",
                "status", "reason", "requested_at", "completed_at"):
        check_true("상세 응답에 %s가 있다" % key, key in own_data, sorted(own_data))
    # 목록과 상세가 같은 신청에 대해 같은 상태를 말해야 한다(두 경로가 갈라지면 안 된다).
    listed = client.get("/api/v1/registry-requests", headers=h).json()["data"]
    mine = [x for x in listed if x["id"] == req_id]
    check_true("목록에도 같은 신청이 있다", len(mine) == 1, [x["id"] for x in listed][:5])
    if mine:
        check("목록과 상세의 상태가 일치한다", mine[0]["status"], own_data["status"])
    check("other user cannot download",
          client.get("/api/v1/registry-requests/%d/download" % req_id, headers=other_h).status_code, 404)

    # ── 다운로드의 인증 경계 (2026-08-13 Sprint 93) ────────────────────────────
    #
    # §8의 보호 라우트 검사는 **기본 경로만** 훑는다(`/api/v1/registry-requests`).
    # 다운로드는 그 하위 경로라 목록에 걸리지 않아, "토큰 없이 파일을 받을 수 있는가"가
    # 검증된 적이 없었다. 파일을 내려주는 엔드포인트라 가장 먼저 막혀야 하는 자리다.
    dl_path = "/api/v1/registry-requests/%d/download" % req_id
    check("토큰 없이 다운로드하면 401", client.get(dl_path).status_code, 401)
    check("잘못된 토큰으로 다운로드하면 401",
          client.get(dl_path, headers={"Authorization": "Bearer not-a-real-token"}).status_code,
          401)
    # 스킴이 없는 Authorization 헤더도 401이다(403이 아니다) — HTTPBearer가 스킴 불일치를
    # 인증 실패로 다룬다. 세 경우(없음/잘못된 토큰/스킴 없음)가 **같은 401**로 수렴하는 것이
    # 맞다: 어느 쪽이든 "인증되지 않았다"이고, 구분해서 알려주면 탐색 단서가 된다.
    check("Bearer 스킴이 없는 헤더도 401",
          client.get(dl_path, headers={"Authorization": "raw-token"}).status_code, 401)
    # 없는 신청은 소유자 토큰이어도 404다(존재 여부를 노출하지 않는다).
    check("없는 신청 다운로드는 404",
          client.get("/api/v1/registry-requests/999999999/download", headers=h).status_code, 404)
    check("음수 request_id도 404",
          client.get("/api/v1/registry-requests/-1/download", headers=h).status_code, 404)

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

        # COMPLETED인데 doc_url이 비어 있는 방어 경로 (2026-08-13 Sprint 92).
        #
        # 코드 주석이 "정상 경로로는 발생하지 않지만 방어적으로 처리한다"고 적어 둔 분기이고,
        # 실제로 커버리지 0이었다. admin.py가 COMPLETED 전이에 doc_url을 필수로 받으므로
        # API를 통해서는 만들 수 없지만, **직접 DB를 만진 복구 작업이나 과거 데이터**로는
        # 생길 수 있다. 그때 500이나 경로 오류가 아니라 **읽을 수 있는 실패**여야 한다.
        conn = get_connection()
        try:
            conn.execute(
                "UPDATE registry_requests SET status='COMPLETED', doc_url=NULL WHERE id=?",
                (req_id,))
            conn.commit()
        finally:
            conn.close()
        # 가드가 없으면 os.path.join(root, None)이 TypeError를 내고 그대로 새어 나온다
        # (500조차 아니라 예외 전파). 그 형태로 끝나면 원인이 안 보이므로 붙잡아
        # 깔끔한 FAIL로 바꾼다 — 이 가드가 막는 것이 정확히 그 사고다.
        no_doc = None
        leaked_dl = None
        try:
            no_doc = client.get("/api/v1/registry-requests/%d/download" % req_id, headers=h)
        except Exception as exc:
            leaked_dl = exc
        check_true("doc_url이 비어도 예외가 새어 나오지 않는다", leaked_dl is None,
                   "doc_url 가드가 사라졌는가? os.path.join(root, None)이 터진다: %r"
                   % (leaked_dl,))
        if no_doc is not None:
            check("doc_url이 비면 200 + 실패 응답(500이 아니다)", no_doc.status_code, 200)
            check("doc_url이 비면 REGISTRY_DOCUMENT_NOT_FOUND",
                  no_doc.json().get("error"), "REGISTRY_DOCUMENT_NOT_FOUND")
            # 상태 게이트가 아니라 **문서 가드**가 막았는지까지 본다 —
            # 위 "어느 가드가 막았는지 고정해야 제거가 검출된다"는 교훈과 같은 이유다.
            check_true("상태 게이트가 아니라 문서 가드가 막았다",
                       no_doc.json().get("error") != "REGISTRY_NOT_COMPLETED",
                       no_doc.json())
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

    # ── 물건 행이 사라진 신청도 관리자에게 보여야 한다 (2026-08-13 Sprint 97) ──
    #
    # 관리자 목록은 `auction_item`을 JOIN해 사건번호/주소를 붙인다. 이것이 INNER JOIN이면
    # **물건 행이 없는 신청은 목록에서 통째로 사라지고 total도 함께 줄어든다** ―
    # 빠졌다는 신호조차 남지 않는다. 반면 사용자 쪽 목록(`registry.py:161`)은 JOIN을
    # 하지 않아 **그 신청을 계속 보여준다.**
    #
    #     사용자 화면   "처리 중"
    #     관리자 화면   존재하지 않음   -> 돈 낸 신청이 영영 처리되지 않는다
    #
    # 정상 API로는 만들 수 없는 상태다(FK가 막는다). 011~013처럼 테이블을 재작성하는
    # 마이그레이션이 FK를 끄고 도는 동안 생길 수 있어, 그 상태를 직접 재현한다.
    # 실 DB에 흔적을 남기지 않도록 물건과 사건을 이 검사가 직접 만들고 지운다.
    conn = get_connection()
    orphan_user = TEST_USER + "-orphan-item"
    orphan_case = "9999타경콕찰97"
    try:
        now = datetime.now().isoformat()
        case_id = conn.execute(
            "INSERT INTO auction_case (case_no, court_code, court_name, created_at) VALUES (?,?,?,?)",
            (orphan_case, "QA법원", "QA법원", now)).lastrowid
        item_id = conn.execute(
            "INSERT INTO auction_item (case_id, case_no, item_no, full_address, created_at) "
            "VALUES (?,?,?,?,?)",
            (case_id, orphan_case, "1", "서울특별시 강남구 QA로 1", now)).lastrowid
        req_id = conn.execute(
            "INSERT INTO registry_requests (user_id,item_id,status,requested_at) VALUES (?,?,?,?)",
            (orphan_user, item_id, "PENDING", now)).lastrowid
        conn.commit()

        r = client.get("/api/v1/admin/registry-requests?user_id=%s" % orphan_user, headers=ah)
        check("물건이 있을 때 관리자 목록에 보인다", r.json()["data"]["total"], 1)

        # 물건 행만 지운다 — FK를 끈 커넥션이라야 가능하다(마이그레이션이 도는 방식).
        mig = get_connection(enforce_foreign_keys=False)
        try:
            mig.execute("DELETE FROM auction_item WHERE id=?", (item_id,))
            mig.commit()
        finally:
            mig.close()

        r = client.get("/api/v1/admin/registry-requests?user_id=%s" % orphan_user, headers=ah)
        check("물건이 사라져도 관리자 목록에 남는다", r.json()["data"]["total"], 1)
        got = r.json()["data"]["items"]
        check("신청 id가 그대로다", [x["id"] for x in got], [req_id])
        # 사건번호/주소는 붙일 곳이 없으니 None ― 값을 지어내지 않는다.
        # ★ 목록이 비면 got[0]이 IndexError로 **테스트를 크래시**시킨다. 그러면 위의
        #   FAIL 두 줄까지 묻히고 정리(finally)만 남는다. 회귀는 크래시가 아니라
        #   읽을 수 있는 실패여야 한다 ― 빈 dict로 대신해 검사로 드러낸다.
        #   빈 dict를 그냥 쓰면 `.get()`이 None을 돌려줘 **기대값 None과 우연히 같아진다**
        #   ― 목록이 사라졌는데 검사가 통과하는 최악의 형태다. 없을 때는 다른 값이 나오게 한다.
        first = got[0] if got else {}
        check("사라진 물건의 사건번호는 None", first.get("case_no", "목록에 행이 없다"), None)
        check("사라진 물건의 주소는 None", first.get("full_address", "목록에 행이 없다"), None)
        # ★ 보이기만 해서는 부족하다. 관리자가 **처리할 수 있어야** 한다.
        #   전이 뒤 상세를 다시 읽는 쿼리도 같은 JOIN을 쓴다 ― INNER JOIN이면 그 SELECT가
        #   빈 결과를 주고 응답 조립에서 터진다. TestClient가 그 예외를 되던지므로
        #   감싸지 않으면 여기서 테스트가 크래시한다(앞선 FAIL들이 묻힌다).
        try:
            patched = client.patch("/api/v1/admin/registry-requests/%d" % req_id,
                                   json={"status": "PROCESSING"}, headers=ah).status_code
        except Exception as exc:
            patched = "예외: %r" % (exc,)
        check("사라진 물건의 신청도 상태를 바꿀 수 있다", patched, 200)
    finally:
        # ★ `conn`을 먼저 정리한다. 위 try 본문이 실패하면(예: INSERT가 제약 위반으로
        # 죽으면) `conn`이 커밋도 롤백도 안 된 트랜잭션을 쥔 채로 남는다 - 그 상태에서
        # 아래 `mig`(별도 커넥션)가 같은 파일에 쓰려고 하면 "database is locked"로
        # 죽어 진짜 원인(위 IntegrityError 등)이 그 아래 예외에 가려진다. 정리 커넥션을
        # 열기 전에 `conn`의 잠금부터 확실히 풀어야 cleanup 자체가 신뢰할 수 있다.
        conn.rollback()
        conn.close()
        mig = get_connection(enforce_foreign_keys=False)
        try:
            # PATCH가 감사 로그를 남긴다 — 신청 행을 지우기 전에 그 id로 함께 지운다
            # (남기면 `no dangling audit rows left` 가드가 다음 실행에서 잡는다).
            for (rid_,) in mig.execute(
                    "SELECT id FROM registry_requests WHERE user_id=?", (orphan_user,)).fetchall():
                mig.execute("DELETE FROM audit_logs WHERE target_type='REGISTRY_REQUEST' "
                            "AND target_id=?", (str(rid_),))
            mig.execute("DELETE FROM registry_requests WHERE user_id=?", (orphan_user,))
            mig.execute("DELETE FROM auction_item WHERE case_id IN "
                        "(SELECT id FROM auction_case WHERE case_no=?)", (orphan_case,))
            mig.execute("DELETE FROM auction_case WHERE case_no=?", (orphan_case,))
            mig.commit()
        finally:
            mig.close()
    left = client.get("/api/v1/admin/registry-requests?user_id=%s" % orphan_user,
                      headers=ah).json()["data"]["total"]
    check("고아 픽스처가 정리됐다", left, 0)

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

    # ── COMPLETED 전이는 **실제 파일이 있어야** 성립한다 (2026-08-13 Sprint 95, BUGS #93) ──
    #
    # 예전에는 doc_url이 비어 있지 않기만 하면 통과했다. 그래서 운영자가 파일명을 오타내도
    # 전이가 성공했고, 사용자 화면에는 "발급 완료"가 뜨는데 다운로드는 404였다(실측 재현).
    # 크롤러 쪽 BUGS #50/#65와 같은 부류인데, **이쪽은 자가 복구가 없다** —
    # 운영자가 알아채기 전까지 그 사용자는 계속 404를 받는다.
    #
    # 이 검사가 없던 시절 이 블록은 `doc_url="qa-regression-not-a-real-file.pdf"`로
    # **성공을 기대**하고 있었다. 즉 테스트가 결함을 정상으로 굳혀 두고 있었다.
    check("없는 파일로 COMPLETED 전이는 400",
          client.patch("/api/v1/admin/registry-requests/%d" % rid,
                       json={"status": "COMPLETED",
                             "doc_url": "qa-regression-not-a-real-file.pdf"},
                       headers=ah).status_code, 400)
    check("경로 탐색 doc_url도 400(쓰기 시점 차단)",
          client.patch("/api/v1/admin/registry-requests/%d" % rid,
                       json={"status": "COMPLETED", "doc_url": "../../../etc/passwd"},
                       headers=ah).status_code, 400)
    # ★ **실재하는** 바깥 파일로도 막혀야 한다.
    #
    # 위 `../../../etc/passwd`는 이 환경에 없는 파일이라 "파일 없음" 검사에도 걸린다.
    # 즉 그것만으로는 **경로 탐색 검사가 살아 있는지 알 수 없다**(변이 시험에서 실제로
    # 통과했다). `registry_documents/`의 부모는 저장소 루트이고 거기에는 `auction.db`가
    # 실재한다 — 경로 검사가 없으면 운영자가 그것을 연결할 수 있고, 그러면 사용자가
    # **DB 파일 전체를 내려받는다.**
    check("실재하는 바깥 파일(../auction.db)도 400",
          client.patch("/api/v1/admin/registry-requests/%d" % rid,
                       json={"status": "COMPLETED", "doc_url": "../auction.db"},
                       headers=ah).status_code, 400)
    # ★ **비교조차 할 수 없는 경로**도 막혀야 한다 (2026-08-13 Sprint 99, 커버리지가 지목).
    #
    #   포함 검사는 `os.path.commonpath([root, path]) == root`인데, 이 함수는 두 경로가
    #   **다른 드라이브에 있으면 답을 내는 대신 ValueError를 던진다.**
    #
    #       commonpath(["C:\\...\\registry_documents", "D:\\x.pdf"])
    #           -> ValueError: Paths don't have the same drive
    #
    #   `doc_url`이 절대 경로면 `os.path.join(root, doc_url)`이 root를 통째로 버리므로
    #   그런 경로가 실제로 들어온다(UNC `//server/share/...`도 같다).
    #
    #   그 예외를 잡지 않으면 500이 되고, 잡되 `inside = True`로 처리하면 **드라이브만
    #   바꾸면 어떤 파일이든 연결되는 우회로**가 된다. 지금은 `inside = False`로
    #   fail-closed다 ― 그 선택을 여기서 고정한다. 이 분기는 지금까지 한 번도 실행된 적이
    #   없었다(커버리지 미도달).
    #   ★ 400이라는 것만 봐서는 **어느 가드가 막았는지 알 수 없다.** 이 경로들은 존재하지도
    #     않으므로 뒤따르는 "파일 없음" 검사에도 걸린다 ― `../../../etc/passwd`에서 이미
    #     한 번 속았던 그 자리다. 다른 드라이브에 실재하는 파일을 만들어 구분하는 방법은
    #     저장소 밖에 파일을 쓰는 일이라 하지 않는다. 대신 **응답 메시지**로 가른다:
    #     두 가드는 서로 다른 문장을 돌려준다.
    for outside in ("D:/x.pdf", "//server/share/x.pdf", "Z:/nope.pdf"):
        r_out = client.patch("/api/v1/admin/registry-requests/%d" % rid,
                             json={"status": "COMPLETED", "doc_url": outside}, headers=ah)
        check("비교 불가 경로도 400: %s" % outside, r_out.status_code, 400)
        check_true("막은 것은 경로 검사다(파일 없음이 아니라): %s" % outside,
                   "디렉터리 밖" in str(r_out.json().get("detail", "")),
                   r_out.json())
    # 거부됐으면 상태가 그대로여야 한다 — 막았는데 값이 바뀌면 의미가 없다.
    # 목록의 첫 항목이 아니라 **그 신청**을 직접 본다 — TEST_USER에게는 다른 신청도 있다.
    _items = client.get("/api/v1/admin/registry-requests?user_id=%s&size=200" % TEST_USER,
                        headers=ah).json()["data"]["items"]
    _mine = [x for x in _items if x["id"] == rid]
    check_true("그 신청을 목록에서 찾을 수 있다", len(_mine) == 1, [x["id"] for x in _items][:5])
    check("거부된 COMPLETED 전이 후에도 PROCESSING", _mine[0]["status"], "PROCESSING")

    # PROCESSING -> COMPLETED (실제 파일을 두고 연결한다 — 문서가 안내하는 운영 순서)
    from api.v1.registry import REGISTRY_DOCUMENT_ROOT as _REG_ROOT
    os.makedirs(_REG_ROOT, exist_ok=True)
    real_doc_name = "qa-regression-%s.pdf" % uuid.uuid4().hex[:8]
    real_doc_path = os.path.join(_REG_ROOT, real_doc_name)
    with open(real_doc_path, "wb") as _fh:
        _fh.write(b"%PDF-1.4 qa registry fixture")
    # 아래 검사 중 하나라도 실패하면 파일이 registry_documents/에 남는다(실제로 남았다).
    # 남은 픽스처는 다음 실행의 "파일 없음" 전제를 오염시키므로 try/finally로 반드시 지운다.
    try:
        r = client.patch("/api/v1/admin/registry-requests/%d" % rid,
                         json={"status": "COMPLETED", "doc_url": real_doc_name}, headers=ah)
        check("PROCESSING->COMPLETED ok", r.json()["data"]["status"], "COMPLETED")
        check_true("completed_at recorded", r.json()["data"]["completed_at"] is not None)

        # 종결 상태에서 추가 전이 금지
        check("COMPLETED->FAILED rejected",
              client.patch("/api/v1/admin/registry-requests/%d" % rid,
                           json={"status": "FAILED", "reason": "x"}, headers=ah).status_code, 400)

        check("admin 404 for unknown id",
              client.patch("/api/v1/admin/registry-requests/99999999",
                           json={"status": "PROCESSING"}, headers=ah).status_code, 404)

        # 정상 경로: 실제 파일이 연결됐으니 사용자는 받을 수 있어야 한다.
        ok_dl = client.get("/api/v1/registry-requests/%d/download" % rid, headers=auth_headers())
        check("연결된 문서는 실제로 받아진다", ok_dl.status_code, 200)

        # 레거시 상태 방어: **API로는 더 이상 만들 수 없지만**(위 400 검사) 과거 데이터나
        # 수동 복구로 "COMPLETED인데 파일 없음"이 남아 있을 수 있다. 그때도 거짓 성공을
        # 돌려주면 안 된다 — 읽기 쪽 방어는 그대로 살아 있어야 한다.
        os.remove(real_doc_path)
        r = client.get("/api/v1/registry-requests/%d/download" % rid, headers=auth_headers())
        check_true("파일이 사라지면 거짓 성공을 주지 않는다",
                   r.status_code == 404 or r.json().get("success") is False,
                   (r.status_code, r.text[:60]))

    finally:
        if os.path.exists(real_doc_path):
            os.remove(real_doc_path)


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
            except NotImplementedError as exc:
                check_true("kginicis %s not implemented" % name, True)
                # 2026-08-13 Sprint 78 (BUGS #80): 예외가 **나는 것**만으로는 부족하다.
                # 예전에는 인자 없는 `raise NotImplementedError`라 str(e)가 빈 문자열이었고,
                # 그 값이 payment_logs.error_message와 사용자 응답에 그대로 실려
                # "왜 실패했는지"가 통째로 사라졌다. 사유가 실제로 담기는지까지 본다.
                message = str(exc)
                check_true("kginicis %s 실패 사유가 비어 있지 않다" % name, bool(message.strip()),
                           "빈 메시지는 로그와 응답에서 원인을 지운다")
                # provider를 식별할 수 있어야 한다. `charge`만은 자체 메시지를 갖고 있어
                # ("KG이니시스 실연동 미구현 (계약/API Key 발급 대기)") 클래스명 대신 브랜드명이
                # 들어간다 — 둘 중 하나면 운영자가 어느 PG인지 안다.
                check_true("kginicis %s 사유로 provider를 식별할 수 있다" % name,
                           "KGInicis" in message or "KG이니시스" in message, message)

        # 기본 구현의 계약: **어느 provider의 어느 단계**인지 담는다(BUGS #80).
        # 하위 클래스가 자체 메시지로 덮어쓸 수 있으므로, 기본 구현 자체를 직접 확인한다.
        class _BareProvider(pp.PaymentProvider):
            pass

        bare = _BareProvider()
        for name, call in calls:
            try:
                call(bare)
                check_true("기본 구현 %s는 실패한다" % name, False, "값을 반환함")
            except NotImplementedError as exc:
                msg = str(exc)
                check_true("기본 구현 %s 사유에 클래스와 단계가 담긴다" % name,
                           "_BareProvider" in msg and name in msg, msg)

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

    # ── verify_webhook_signature: provider별 fail-closed (2026-08-13 Sprint 76) ──
    #
    # 위 6개 생명주기 메서드는 검증돼 있었지만 **7번째이자 유일한 보안 메서드**는
    # provider별로 확인된 적이 없었다.
    #
    # `POST /payments/webhook/{provider_name}`은 **사용자 인증이 없는 공개 경로**다.
    # provider를 URL 이름으로 고르고 그 provider의 `verify_webhook_signature()` 하나로
    # 신뢰 여부를 정한다. 어느 provider든 이 메서드가 True로 기울면 **누구나 "결제 완료"를
    # 위조**할 수 있다. 그래서 기본 구현이 `return False`(fail-closed)인데,
    # 그 기본값이 실제로 유지되는지는 아무도 확인하지 않고 있었다.
    #
    # 특히 KGInicisProvider는 실연동 전 자리 구현이라 이 메서드를 **오버라이드하지 않는다**.
    # 누군가 기본 구현을 True로 바꾸거나, 새 provider를 추가하면서 이 메서드를 잊고
    # 기본값을 낙관적으로 만들면 방어가 통째로 사라진다.
    forged_headers = {"X-Webhook-Signature": "a" * 64, "Content-Type": "application/json"}
    forged_body = b'{"event":"PAID","pg_transaction_id":"forged"}'

    saved_secret = os.environ.get("PAYMENT_WEBHOOK_SECRET")
    try:
        # (1) 시크릿이 아예 없으면 어떤 provider도 통과시키면 안 된다.
        os.environ.pop("PAYMENT_WEBHOOK_SECRET", None)
        for name in pp._PROVIDERS:
            provider = pp.get_payment_provider_by_name(name)
            check("%s: 시크릿 없으면 서명 검증 실패" % name,
                  provider.verify_webhook_signature(forged_body, forged_headers), False)

        # (2) 시크릿이 있어도, 서명을 구현하지 않은 provider는 여전히 거절해야 한다.
        os.environ["PAYMENT_WEBHOOK_SECRET"] = "sprint76-probe-secret"
        for name in pp._PROVIDERS:
            provider = pp.get_payment_provider_by_name(name)
            implements = type(provider).verify_webhook_signature is not \
                pp.PaymentProvider.verify_webhook_signature
            got = provider.verify_webhook_signature(forged_body, forged_headers)
            if implements:
                # 구현한 provider(mock)는 **틀린 서명**을 거절해야 한다.
                check("%s: 위조 서명 거절" % name, got, False)
            else:
                # 미구현 provider는 기본 fail-closed를 그대로 물려받아야 한다.
                check("%s: 미구현이므로 항상 거절(fail-closed)" % name, got, False)

        # (3) 기본 구현 자체가 False여야 한다 - 이 한 줄이 모든 미구현 provider의 방어선이다.
        check("PaymentProvider 기본 구현은 False",
              pp.PaymentProvider().verify_webhook_signature(forged_body, forged_headers), False)

        # (4) 올바른 서명은 통과해야 한다(방어가 정상 경로까지 막으면 안 된다).
        import hmac as _hmac, hashlib as _hashlib
        good = _hmac.new(b"sprint76-probe-secret", forged_body, _hashlib.sha256).hexdigest()
        mock = pp.get_payment_provider_by_name("mock")
        check("mock: 올바른 서명은 통과",
              mock.verify_webhook_signature(forged_body, {"X-Webhook-Signature": good}), True)
        # 헤더 이름 대소문자는 가리지 않는다(HTTP 표준).
        check("mock: 헤더 이름 대소문자 무관",
              mock.verify_webhook_signature(forged_body, {"x-webhook-signature": good}), True)
        # 서명이 없으면 거절.
        check("mock: 서명 헤더 없으면 거절",
              mock.verify_webhook_signature(forged_body, {}), False)
        # 바디가 1바이트만 달라도 거절(원문 전체에 대한 서명임을 확인).
        check("mock: 바디가 바뀌면 거절",
              mock.verify_webhook_signature(forged_body + b" ", {"X-Webhook-Signature": good}),
              False)

        # (5) 엔드포인트 수준: 서명을 구현하지 않은 provider로 들어온 Webhook은 401이어야 한다.
        r_forged = client.post("/api/v1/payments/webhook/kginicis",
                               content=forged_body, headers=forged_headers)
        check("kginicis webhook은 401(미검증 거절)", r_forged.status_code, 401)
    finally:
        if saved_secret is None:
            os.environ.pop("PAYMENT_WEBHOOK_SECRET", None)
        else:
            os.environ["PAYMENT_WEBHOOK_SECRET"] = saved_secret


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
# 13-B. /api/v1/search의 정렬 결정성 (2026-08-15 Sprint 122)
#
# 위 §13이 다루는 목록(registry-requests/search-presets)은 Sprint 26이 이미 id
# tie-break를 붙인 것들이다. 그런데 **가장 많이 쓰이는 목록인 /api/v1/search 자체는
# 그 정리에서 빠져 있었다** ― 기본 정렬(auction_date, fail_count)도 커스텀 정렬
# (예: minimum_bid_price)도 동률에서 id로 전순서를 잡지 않았다. 실 DB 실측:
# auction_date+fail_count 동률 최대 27건, minimum_bid_price 동률 최대 8건 ―
# 흔한 페이지 크기(20)를 가볍게 넘어서는 규모라 동률이 페이지 경계에 걸치기 쉽다.
# ---------------------------------------------------------------------------
def test_search_ordering_is_deterministic():
    print("\n--- 13-B. /api/v1/search 정렬 결정성 (동률 tie-break) ---")
    tag = "QA-TIEBREAK-%d" % int(datetime.now().timestamp())
    conn = get_connection()
    made_ids = []
    try:
        try:
            case_id = conn.execute(
                "INSERT INTO auction_case (court_code, case_no) VALUES (?,?)",
                ("서울중앙지방법원", tag)).lastrowid
            # 5개 물건이 auction_date/fail_count/minimum_bid_price 전부 동률이다 ―
            # 기본 정렬과 커스텀 정렬(minimum_bid_price) 양쪽 다 이 한 세트로 검증한다.
            same_date = (datetime.now() + timedelta(days=3)).strftime("%Y-%m-%d")
            for i in range(5):
                made_ids.append(conn.execute(
                    "INSERT INTO auction_item"
                    " (case_id, case_no, item_no, court_name, auction_date, fail_count,"
                    "  full_address, appraisal_price, minimum_bid_price)"
                    " VALUES (?,?,?,?,?,?,?,?,?)",
                    (case_id, tag, str(i), "서울중앙지방법원", same_date, 2,
                     "서울특별시 강남구 역삼동 1", 100000000, 70000000)).lastrowid)
            conn.commit()

            def page_ids(qs, size):
                seen, page = [], 1
                while True:
                    r = client.get("/api/v1/search?case_no=%s&size=%d&page=%d&%s"
                                   % (tag, size, page, qs))
                    items = r.json()["items"]
                    if not items:
                        break
                    seen.extend(i["id"] for i in items)
                    page += 1
                    if page > 10:  # 안전판 ― 무한 루프 방지
                        break
                return seen

            for label, qs in (("기본 정렬", "include_closed=true"),
                               ("커스텀 정렬(minimum_bid_price)",
                                "include_closed=true&sort_by=minimum_bid_price&sort_order=asc")):
                collected = page_ids(qs, size=2)  # 5건을 2/2/1로 쪼갠다 ― 동률이 경계에 걸린다
                check("%s: 페이지를 다 모으면 중복/누락 없이 5건" % label,
                      sorted(collected), sorted(made_ids))
                check("%s: 페이지 사이 중복 없음" % label,
                      len(collected) - len(set(collected)), 0)
                collected_again = page_ids(qs, size=2)
                check("%s: 반복 호출에도 순서가 흔들리지 않는다" % label,
                      collected_again, collected)
        finally:
            if made_ids:
                conn.execute("DELETE FROM auction_item WHERE id IN (%s)"
                             % ",".join("?" * len(made_ids)), made_ids)
            conn.execute("DELETE FROM auction_case WHERE case_no=?", (tag,))
            conn.commit()
    finally:
        conn.close()

    leftover = client.get("/api/v1/search?include_closed=true&case_no=%s" % tag).json()["total"]
    check("QA 픽스처가 정리됐다", leftover, 0)


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
        with open(DETAIL_PAGE_SOURCE, encoding="utf-8-sig") as f:
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
    # 2026-08-17 Sprint 144: 물건 사진 서빙. 문서 뷰어와 같은 계열(공개 GET + 존재확인 HEAD)이다.
    ("GET", "/api/v1/item/{item_id}/images/{seq}"),
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

    # doc_type은 대소문자를 가리지 않는다 (2026-08-17 Sprint 148, BUGS #108).
    # 이 저장소는 같은 개념을 두 벌 어휘로 저장한다 — document_status는 대문자,
    # document_queue는 소문자다. 큐 쪽 값으로 URL을 만들면 400이 났고, 그 400이
    # 오타로 넣은 값과 구별되지 않아 원인을 찾기 어려웠다.
    #
    # 알 수 없는 종류는 **여전히 400**이어야 한다 — 넓힌 것은 대소문자뿐이다.
    lower = client.get("/api/v1/item/%d/documents/spec" % item_id)
    upper = client.get(path)
    check("소문자 doc_type이 대문자와 같은 상태를 준다", lower.status_code, upper.status_code)
    if upper.status_code == 200:
        check("소문자 doc_type이 같은 본문을 준다", len(lower.content), len(upper.content))
    check("섞인 대소문자도 같다",
          client.get("/api/v1/item/%d/documents/sPeC" % item_id).status_code, upper.status_code)
    check("모르는 종류는 그대로 400",
          client.get("/api/v1/item/%d/documents/bogus" % item_id).status_code, 400)
    check("HEAD도 같은 규칙",
          client.request("HEAD", "/api/v1/item/%d/documents/spec" % item_id).status_code,
          client.request("HEAD", path).status_code)


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

    # ------------------------------------------------------------------
    # ★ 전수 검사 — 위 5개는 **손으로 적은 목록**이라 새 엔드포인트를 영원히 못 본다
    #   (2026-08-17 Sprint 165 신설).
    #
    #   실측: 이 목록은 5개인데 실제로 envelope 를 쓰는 GET 엔드포인트는 **14개**였다.
    #   admin 7개 전부와 `/api/v1/plans`, `/api/v1/subscriptions/me` 가 검사 밖에 있었다.
    #   같은 "목록 기반이라 빠뜨린다" 실패를 Sprint 161 이 경로 규칙 검사에서 이미
    #   겪었다(세 번 반복됐다). 그래서 여기도 OpenAPI 에서 라우트를 뽑아 전부 두드린다.
    #
    #   제외는 **포함 목록이 아니라 예외 목록**이다 — 새 엔드포인트는 기본적으로 검사
    #   대상이 되고(fail-safe), 빼려면 이유를 여기에 적어야 한다.
    # ------------------------------------------------------------------
    RAW_BY_DESIGN = {
        # api/v1/search.py:436 — "인증 불필요 라우트라 envelope 를 쓰지 않는다"
        "/api/v1/search": "인증 불필요 라우트(소스에 근거 주석 있음)",
        "/api/v1/search/regions": "위와 같은 모듈·같은 근거",
        # api_server.py:92 — 레거시 3키 {success, data, message}. 헬스체크용.
        "/": "레거시 3키 헬스체크 응답",
        "/api/v1/stats": "레거시 3키 운영 통계 응답",
        # api/v1/doc_stats.py — 순수 dict. 소스에 명시적 근거 주석은 없다(확인함).
        "/api/v1/document-stats": "운영 진단용 raw dict(소스에 근거 주석 없음)",
    }

    spec = api_server.app.openapi()
    admin_h = {"X-Admin-Key": TEST_ADMIN_KEY}
    checked = 0
    offenders = []
    for path, ops in sorted(spec.get("paths", {}).items()):
        if "get" not in ops or "{" in path:
            continue
        if path in RAW_BY_DESIGN:
            continue
        hdr = admin_h if "/admin/" in path else h
        resp = client.get(path, headers=hdr)
        if resp.status_code >= 400:
            # 이 검사의 관심사는 **성공 응답의 형태**다. 권한/검증 실패는 여기서 보지 않는다.
            continue
        try:
            got = resp.json()
        except Exception:  # noqa: BLE001
            offenders.append("%s: JSON 아님" % path)
            continue
        checked += 1
        if not isinstance(got, dict) or set(got) != ENVELOPE_KEYS:
            offenders.append("%s: %s" % (path, sorted(got) if isinstance(got, dict) else type(got).__name__))

    check_true("전수 검사 대상이 실제로 모였다(0이면 검사가 비어 있다)", checked >= 10, checked)
    check_true("★ 모든 GET 엔드포인트가 envelope 계약을 지킨다 "
               "(raw 로 두려면 RAW_BY_DESIGN 에 이유와 함께 등록할 것)",
               not offenders, offenders)
    check_true("fail keeps message", isinstance(body["message"], str))

    # 반대로 비인증 공개 라우트(search/item)는 envelope를 쓰지 않는다 — 기존 계약 유지
    body = client.get("/api/v1/search").json()
    check_true("search keeps flat shape", "items" in body and "success" not in body, sorted(body)[:4])

    # ── 위 5개는 손으로 적은 목록이다. 전수로 넓힌다 (2026-08-14) ──────────────
    #
    # 인증이 필요한 GET 은 **21개**인데 위에서 검사하던 것은 5개뿐이었다.
    # 빠져 있던 16개에는 관리자 목록 11개와 `/subscriptions/me` 가 전부 들어간다.
    # 지금은 전부 봉투를 지키지만(2026-08-14 실측), 새 관리자 엔드포인트가
    # 리스트를 그대로 돌려주면 프런트의 `result.data` 읽기가 깨진다 —
    # 그리고 그 사실을 알려 줄 검사가 없었다.
    #
    # 라우트를 손으로 고르지 않고 앱에서 유도한다(Sprint 108과 같은 방식).
    # 이 FastAPI 버전은 `include_router` 결과를 평탄화하지 않으므로 감싼 것을 풀어서 센다.
    #
    # ★ 판정 대상은 **HTTP 200 응답만**이다. 이 저장소에는 실패 응답이 두 형태 있고
    #   둘 다 의도된 상태다 — `error_response()` 는 200 + 봉투, `HTTPException` 은
    #   4xx + `detail`. 없는 id 를 넣어 404가 나온 것을 봉투 위반으로 세면 안 된다.
    routes = set()
    for r in api_server.app.routes:
        if type(r).__name__ == "_IncludedRouter":
            pre = r.include_context.prefix or ""
            subs = [(pre + s.path, s) for s in r.original_router.routes]
        else:
            subs = [(getattr(r, "path", ""), r)]
        for full, s in subs:
            for m in (getattr(s, "methods", None) or set()):
                if m == "GET":
                    routes.add(full)

    admin_h = {"X-Admin-Key": TEST_SUPER_ADMIN_KEY}
    checked, violations = 0, []
    for path in sorted(routes):
        if path in ("/", "/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"):
            continue
        probe = path
        for token, sample in _PATH_SAMPLE.items():
            probe = probe.replace(token, sample)
        if client.get(probe).status_code not in (401, 403):
            continue          # 공개 라우트 — 봉투 계약 대상이 아니다
        hdr = admin_h if "/admin/" in path else h
        resp = client.get(probe, headers=hdr)
        if resp.status_code != 200:
            continue          # HTTPException 경로(detail 모양) — 위 주석 참고
        checked += 1
        try:
            body = resp.json()
        except ValueError:
            violations.append("%s: JSON 아님" % path)
            continue
        if not isinstance(body, dict) or set(body) != ENVELOPE_KEYS:
            violations.append("%s: %s" % (path, sorted(body) if isinstance(body, dict)
                                          else type(body).__name__))

    print("   인증 필요 GET 중 200 응답 %d개 대조" % checked)
    check_true("봉투 계약 대상이 충분히 있다(검사가 공허하지 않다)", checked >= 12, checked)
    check("봉투 모양을 벗어난 인증 GET 없음", violations, [])


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
# 18-B. 보안 응답 헤더 (2026-08-15 Sprint 127)
#
# `X-Content-Type-Options`/`Referrer-Policy`는 모든 응답(성공/실패/파일)에 실려야 한다.
#
# ★ `X-Frame-Options`는 **일부러 넣지 않았다** - 이 백엔드 자체가
# `properties/[id]/page.tsx`의 문서 뷰어 iframe이 담는 대상이다(`<iframe src="{API}/api/v1/
# item/{id}/documents/{doc_type}">`). 프런트(3000)/백엔드(8000)는 다른 origin이라
# `SAMEORIGIN`조차 이 뷰어를 깬다. 프런트(`next.config.ts`)에는 있고 여기는 없는 것이
# 실수가 아니라 의도라는 것을, 실린 것과 안 실린 것 둘 다 검사로 고정해 다음 세션이
# "빠뜨렸나 보다" 하고 무심코 채워 넣지 않게 한다.
# ---------------------------------------------------------------------------
def test_backend_security_headers():
    print("\n--- 18-B. 백엔드 보안 응답 헤더 ---")
    endpoints = [
        ("성공 응답(JSON)", lambda: client.get("/api/v1/search?page=1&size=1")),
        ("실패 응답(404)", lambda: client.get("/api/v1/item/999999999")),
        ("인증 실패(401)", lambda: client.get("/api/v1/favorites")),
    ]
    for label, call in endpoints:
        r = call()
        check("%s: X-Content-Type-Options" % label,
              r.headers.get("x-content-type-options"), "nosniff")
        check("%s: Referrer-Policy" % label,
              r.headers.get("referrer-policy"), "strict-origin-when-cross-origin")
        check_true("%s: X-Frame-Options가 없다(백엔드는 iframe 대상이라 의도적으로 제외)"
                   % label, "x-frame-options" not in r.headers,
                   dict(r.headers))

    # 실제 문서 파일 응답(FileResponse 경로, 위 JSONResponse 경로와 미들웨어 통과가 다를 수 있다)
    row = get_connection().execute(
        "SELECT item_id, doc_type FROM document_status WHERE status='READY' LIMIT 1").fetchone()
    if row:
        r = client.get("/api/v1/item/%s/documents/%s" % (row["item_id"], row["doc_type"]))
        check("파일 응답: X-Content-Type-Options", r.headers.get("x-content-type-options"), "nosniff")
        check_true("파일 응답: X-Frame-Options가 없다", "x-frame-options" not in r.headers, dict(r.headers))
    else:
        print("   [SKIP] READY 문서가 없어 파일 응답 경로는 못 대조했다")


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

    # ── 리스트 안쪽까지 마스킹되는가 (2026-08-13 Sprint 89) ────────────────────
    #
    # 커버리지가 지목했다: `mask_sensitive()`의 **리스트 분기**(70행)가 미커버였다.
    # 위 검사는 dict 중첩만 본다.
    #
    # PG Webhook payload는 배열을 흔히 포함한다(`{"items":[{...}]}`, 승인 내역 목록 등).
    # 리스트 재귀가 끊기면 **배열 안의 카드번호가 평문 그대로** `payment_webhooks.raw_payload`에
    # 저장되고, 그 로그는 운영자가 폭넓게 열람한다. dict만 막고 리스트를 놓치면
    # 마스킹이 있다는 사실 자체가 오히려 위험하다(안전하다고 믿게 되므로).
    in_list = mask_sensitive({"items": [{"card_no": "4111111111111111", "name": "홍길동"}]})
    check("리스트 안 dict의 민감 키도 마스킹", in_list["items"][0]["card_no"], REDACTED)
    check("리스트 안 비민감 값은 보존", in_list["items"][0]["name"], "홍길동")

    top_list = mask_sensitive([{"cvc": "123"}, {"ok": "x"}])
    check("최상위가 리스트여도 마스킹", top_list[0]["cvc"], REDACTED)
    check("최상위 리스트의 비민감 값 보존", top_list[1]["ok"], "x")

    nested_list = mask_sensitive({"a": [[{"password": "p"}]]})
    check("중첩 리스트도 끝까지 내려간다", nested_list["a"][0][0]["password"], REDACTED)

    # ── 감사 로그(audit_logs)도 같은 기준으로 마스킹하는가 (2026-08-14 신설) ────
    #
    # `payment_logs._dump()` 와 `audit._dump()` 는 **이름이 같고 하는 일도 같은데**
    # 마스킹은 결제 로그 쪽만 하고 있었다. 감사 로그 payload 는 지금 손으로 고른
    # 스칼라 dict 뿐이라 사고가 없었지만(호출부 5곳 전수 확인), `audit.py` 의 docstring
    # 자체가 "전체 행을 통째로 넣으면 민감정보가 섞여 들어갈 여지가 커진다"고 경고한다 —
    # 그건 **관례**일 뿐 강제되지 않았다.
    #
    # `audit_logs` 도 운영자가 폭넓게 열람하는 기록이다. 같은 성질의 기록에 서로 다른
    # 기준이 적용되는 상태를 없앤다. 지금 payload 에는 민감 키가 없으므로 무영향이고,
    # 앞으로 누가 행을 통째로 넘겼을 때만 효과가 있다.
    import json as _json
    from api.v1.audit import _dump as audit_dump

    dumped = audit_dump({"status": "PAID", "card_no": "4111111111111111",
                         "nested": {"access_token": "eyJ", "ok": "keep"}})
    parsed = _json.loads(dumped)
    check("감사 로그도 card_no를 마스킹한다", parsed["card_no"], REDACTED)
    check("감사 로그도 중첩 토큰을 마스킹한다", parsed["nested"]["access_token"], REDACTED)
    check("감사 로그의 비민감 값은 보존", parsed["nested"]["ok"], "keep")
    check("감사 로그의 일반 필드도 보존", parsed["status"], "PAID")

    # 현재 실제로 쓰이는 payload 모양에는 **영향이 없어야 한다**(no-op).
    for sample in ({"status": "PENDING", "reason": None, "doc_url": "a.pdf"},
                   {"status": "ACTIVE", "expires_at": "2026-09-01T00:00:00"}):
        check("현재 감사 payload는 그대로 직렬화된다 %s" % sorted(sample),
              _json.loads(audit_dump(sample)), sample)

    # datetime 이 섞여도 감사 기록을 잃지 않아야 한다(default=str 유지).
    from datetime import datetime as _dt
    check_true("datetime이 섞여도 직렬화가 죽지 않는다",
               "2026" in audit_dump({"when": _dt(2026, 8, 14)}))

    # 키 표기 변형 — PG마다 표기가 다르다(card-no / CARD_NO).
    check("하이픈 키도 마스킹", mask_sensitive({"card-no": "1111"})["card-no"], REDACTED)
    check("대문자 키도 마스킹", mask_sensitive({"CARD_NO": "1111"})["CARD_NO"], REDACTED)

    # 스칼라는 그대로 통과한다(문자열을 dict처럼 다루지 않는다).
    check("스칼라는 그대로", mask_sensitive("그냥 문자열"), "그냥 문자열")

    # ★ 원본을 바꾸지 않는다 — docstring이 약속한 것이고, 바꾸면 호출부가 PG로 되돌려보내는
    #   payload까지 오염된다(마스킹된 값으로 재처리하면 서명이 깨진다).
    original = {"card_no": "4111", "items": [{"cvc": "999"}]}
    mask_sensitive(original)
    check("원본 dict가 변형되지 않는다", original["card_no"], "4111")
    check("원본 리스트 안쪽도 변형되지 않는다", original["items"][0]["cvc"], "999")

    # _dump: audit._dump과 같은 세 갈래(None / 문자열 / 그 외)
    from api.v1.payment_logs import _dump as _pl_dump
    check("_dump(None)은 None", _pl_dump(None), None)
    check("_dump(str)은 그대로(이중 인코딩 없음)", _pl_dump("이미 문자열"), "이미 문자열")
    check_true("_dump(dict)은 마스킹된 JSON",
               REDACTED in _pl_dump({"card_no": "4111"}), _pl_dump({"card_no": "4111"}))
    check_true("_dump(dict)은 한글을 이스케이프하지 않는다",
               "한글" in _pl_dump({"한글": "값"}), _pl_dump({"한글": "값"}))

    # ── 알 수 없는 enum 값은 조용히 저장되지 않는다 ────────────────────────────
    #
    # `log_payment_event` / `mark_webhook_processed`의 ValueError 분기(103·105·194행)도
    # 미커버였다. 이 값들은 나중에 재처리 가능 여부를 판정하는 근거가 되므로,
    # 모르는 값이 DB에 들어가면 `webhook_reprocess_block_reason()`이 오판한다.
    from api.v1.payment_logs import log_payment_event as _log_event
    conn_v = get_connection()
    try:
        # ★ status 케이스의 event_type은 **반드시 유효한 값**이어야 한다.
        #   처음엔 "PAYMENT_CONFIRMED"를 썼는데 그것이 VALID_EVENT_TYPES에 없어서
        #   앞선 event_type 가드에서 걸렸다 — 검사는 통과했지만 **의도한 분기를 타지
        #   않았다**(커버리지가 그 줄을 미커버로 남겨 드러났다).
        #   "ValueError가 났다"만 보면 이런 가짜 통과를 구분할 수 없다.
        for label, kwargs in (
            ("알 수 없는 event_type",
             dict(event_type="NOT_A_TYPE", status="SUCCESS")),
            ("알 수 없는 log status",
             dict(event_type="CONFIRM", status="NOT_A_STATUS")),
        ):
            raised = False
            try:
                _log_event(conn_v, payment_id=None, provider="mock", **kwargs)
            except ValueError:
                raised = True
            check("%s는 ValueError" % label, raised, True)

        raised = False
        try:
            mark_webhook_processed(conn_v, 1, "NOT_A_WEBHOOK_STATUS")
        except ValueError:
            raised = True
        check("알 수 없는 webhook 상태는 ValueError", raised, True)
    finally:
        conn_v.rollback()
        conn_v.close()

    # ── 재처리 차단 사유: 나머지 두 갈래 (235·237행) ──────────────────────────
    from api.v1.payment_logs import (
        webhook_reprocess_block_reason as _block_reason, WEBHOOK_FAILED,
    )

    def fake_row(status, verified=1):
        return {"signature_verified": verified, "processing_status": status}

    failed_reason = _block_reason(fake_row(WEBHOOK_FAILED))
    check_true("FAILED는 재처리를 막는다", failed_reason is not None, failed_reason)
    check_true("FAILED 사유가 재전송을 안내한다", "재전송" in (failed_reason or ""), failed_reason)

    unknown_reason = _block_reason(fake_row("SOME_FUTURE_STATUS"))
    check_true("모르는 상태도 막는다(기본 허용이 아니다)",
               unknown_reason is not None, unknown_reason)
    check_true("모르는 상태 사유에 그 값이 적힌다",
               "SOME_FUTURE_STATUS" in (unknown_reason or ""), unknown_reason)

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
# 31-B. Admin 목록 필터와 키 미설정 가드 (2026-08-13 Sprint 91 신규)
#
# 커버리지가 지목했다. `api/v1/admin.py`의 미커버 26행 중 상당수가
# **한 번도 걸어보지 않은 목록 필터**였다.
#
#     /admin/registry-requests?item_id= / ?case_no=
#     /admin/payments?user_id= / ?payment_type=
#     /admin/payments/webhooks?payment_id=
#
# Sprint 74가 "잘못된 필터 **값**"을 다뤘다면, 이번은 **필터가 실제로 걸리는가**다.
# 둘은 다른 문제다 - 값 검증을 통과해도 조건이 SQL에 안 붙으면 **전체가 그대로 나온다**.
# 200이고 목록도 그럴듯해서 운영자는 필터가 먹었다고 믿는다.
#
# 그리고 `_require_role()`의 첫 가드(104행)도 미커버였다 - 두 키가 모두 없으면 500이다.
# 여기서 통과시키면 **키 없이 관리자 API가 열린다.**
# ---------------------------------------------------------------------------
def test_admin_list_filters():
    print("\n--- 31-B. Admin 목록 필터 / 키 미설정 가드 (Sprint 91) ---")
    ah = {"X-Admin-Key": TEST_ADMIN_KEY}

    # (1) ★ 두 키가 모두 없으면 Admin API 자체가 500이다(fail-closed).
    #     401/403이 아니라 500인 것도 의도다 - 키를 안 준 것이 아니라 **서버가 설정되지
    #     않은 것**이므로, 사용자 탓처럼 보이는 응답을 주면 원인을 못 찾는다.
    saved_admin = os.environ.get("ADMIN_API_KEY")
    saved_super = os.environ.get("SUPER_ADMIN_API_KEY")
    try:
        os.environ.pop("ADMIN_API_KEY", None)
        os.environ.pop("SUPER_ADMIN_API_KEY", None)
        r_nokey = client.get("/api/v1/admin/users", headers=ah)
        check("관리자 키가 모두 없으면 500", r_nokey.status_code, 500)
        # 키 값이 응답에 새면 안 된다.
        check_true("500 응답에 키 값이 실리지 않는다",
                   TEST_ADMIN_KEY not in r_nokey.text, r_nokey.text[:80])
    finally:
        if saved_admin is not None:
            os.environ["ADMIN_API_KEY"] = saved_admin
        if saved_super is not None:
            os.environ["SUPER_ADMIN_API_KEY"] = saved_super
    check("키를 되돌리면 다시 200",
          client.get("/api/v1/admin/users", headers=ah).status_code, 200)

    # (2) 필터 픽스처 - 두 사용자 x 두 결제유형으로 구분 가능한 데이터를 만든다.
    #     한 종류만 있으면 "필터가 무시돼도 결과가 같아" 검사가 구분력을 잃는다.
    tag = uuid.uuid4().hex[:8]
    user_a = "qa-reg-flt-a-" + tag
    user_b = "qa-reg-flt-b-" + tag
    conn = get_connection()
    made = []
    try:
        ts = datetime.now().isoformat()
        for uid, ptype in ((user_a, "SUBSCRIPTION"), (user_a, "OVERAGE_USAGE"),
                           (user_b, "SUBSCRIPTION")):
            made.append(conn.execute(
                "INSERT INTO payments (user_id, payment_type, amount, status,"
                " created_at, updated_at) VALUES (?,?,?,?,?,?)",
                (uid, ptype, 12900, "PAID", ts, ts)).lastrowid)
        conn.commit()

        def ids(qs):
            r = client.get("/api/v1/admin/payments?size=200&" + qs, headers=ah)
            check("%s 는 200" % qs, r.status_code, 200)
            return {i["id"] for i in r.json()["data"]}

        # user_id 필터: A의 것만 나와야 한다.
        a_ids = ids("user_id=" + user_a)
        check("user_id 필터: A의 결제 2건", a_ids & set(made), {made[0], made[1]})
        check_true("user_id 필터: B의 결제가 섞이지 않는다", made[2] not in a_ids, sorted(a_ids)[:5])

        # payment_type 필터: 같은 사용자 안에서도 갈라져야 한다.
        overage = ids("user_id=%s&payment_type=OVERAGE_USAGE" % user_a)
        check("payment_type 필터: 초과결제 1건만", overage & set(made), {made[1]})
        check_true("payment_type 필터: 구독 결제가 섞이지 않는다",
                   made[0] not in overage, sorted(overage)[:5])

        # 두 필터를 함께 걸면 교집합이다(하나만 먹으면 이 검사가 실패한다).
        none_expected = ids("user_id=%s&payment_type=OVERAGE_USAGE" % user_b)
        check("두 필터의 교집합이 비어 있다", none_expected & set(made), set())

        # (3) webhook payment_id 필터
        wh_ids = []
        for pid in (made[0], made[1]):
            wh_ids.append(conn.execute(
                "INSERT INTO payment_webhooks (provider, event_type, event_id,"
                " payment_id, signature_verified, processing_status, raw_payload, received_at)"
                " VALUES (?,?,?,?,?,?,?,?)",
                ("mock", "PAYMENT_CONFIRMED", "qa-wh-flt-%s-%d" % (tag, pid),
                 pid, 1, "RECEIVED", "{}", ts)).lastrowid)
        conn.commit()

        r = client.get("/api/v1/admin/payments/webhooks?size=200&payment_id=%d" % made[0],
                       headers=ah)
        check("webhook payment_id 필터는 200", r.status_code, 200)
        got = {w["id"] for w in r.json()["data"]}
        check("webhook payment_id 필터: 해당 건만", got & set(wh_ids), {wh_ids[0]})
        check_true("webhook payment_id 필터: 다른 결제의 webhook이 섞이지 않는다",
                   wh_ids[1] not in got, sorted(got)[:5])
    finally:
        conn.execute("DELETE FROM payment_webhooks WHERE event_id LIKE ?",
                     ("qa-wh-flt-%s-%%" % tag,))
        conn.execute("DELETE FROM payments WHERE user_id IN (?,?)", (user_a, user_b))
        conn.commit()
        conn.close()

    # 픽스처가 남지 않았는지 확인한다.
    left = client.get("/api/v1/admin/payments?size=1&user_id=" + user_a,
                      headers=ah).json()["meta"]["total"]
    check("필터 픽스처가 정리됐다", left, 0)

    # (4) registry-requests의 item_id / case_no 필터도 미커버였다.
    #     case_no는 LIKE(부분 일치)이고 item_id는 정확 일치다 — 둘의 성격이 다르다.
    reg_user = "qa-reg-flt-r-" + tag
    conn = get_connection()
    reg_ids = []
    try:
        two = conn.execute(
            "SELECT id, case_no FROM auction_item WHERE case_no != '' LIMIT 2").fetchall()
        if len(two) < 2:
            print("[SKIP] 서로 다른 물건 2건이 없어 registry 필터 검사를 생략한다")
        else:
            ts = datetime.now().isoformat()
            for it in two:
                reg_ids.append(conn.execute(
                    "INSERT INTO registry_requests (user_id, item_id, status, requested_at)"
                    " VALUES (?,?,?,?)", (reg_user, it["id"], "PENDING", ts)).lastrowid)
            conn.commit()

            def reg_ids_for(qs):
                r = client.get("/api/v1/admin/registry-requests?size=200&" + qs, headers=ah)
                check("registry %s 는 200" % qs, r.status_code, 200)
                # 이 엔드포인트만 data가 리스트가 아니라 {total,page,size,items} dict다
                # (다른 admin 목록은 data=list + meta.total). 기존 계약이라 그대로 따른다.
                return {x["id"] for x in r.json()["data"]["items"]}

            only_first = reg_ids_for("user_id=%s&item_id=%d" % (reg_user, two[0]["id"]))
            check("item_id 필터: 해당 물건의 신청만", only_first & set(reg_ids), {reg_ids[0]})
            check_true("item_id 필터: 다른 물건의 신청이 섞이지 않는다",
                       reg_ids[1] not in only_first, sorted(only_first)[:5])

            # case_no는 부분 일치 — 전체 사건번호로 걸면 그 건이 나와야 한다.
            by_case = reg_ids_for("user_id=%s&case_no=%s" % (reg_user, two[0]["case_no"]))
            check_true("case_no 필터: 해당 사건의 신청이 나온다",
                       reg_ids[0] in by_case, sorted(by_case)[:5])

            # 존재하지 않는 사건번호는 빈 결과(오류가 아니라).
            check("case_no 필터: 없는 사건은 빈 결과",
                  reg_ids_for("user_id=%s&case_no=NOPE-%s" % (reg_user, tag)) & set(reg_ids),
                  set())

            # (5) 상태 변경의 허용값 가드 — 목록 필터와 달리 **본문** 검증이다.
            r_bad = client.patch("/api/v1/admin/registry-requests/%d" % reg_ids[0],
                                 json={"status": "NOT_A_STATUS"},
                                 headers={"X-Admin-Key": TEST_SUPER_ADMIN_KEY})
            check("허용되지 않는 상태 값은 400", r_bad.status_code, 400)
            check_true("400 메시지가 그 값을 알려준다",
                       "NOT_A_STATUS" in r_bad.text, r_bad.text[:80])
            # 거부됐으면 DB도 그대로여야 한다.
            still = conn.execute("SELECT status FROM registry_requests WHERE id=?",
                                 (reg_ids[0],)).fetchone()["status"]
            check("거부된 상태 변경은 DB를 바꾸지 않는다", still, "PENDING")

            # 관리자가 직접 바꿀 수 없는 값(실재하는 상태지만 자동 전이 전용)도 막힌다.
            # PAYMENT_REQUIRED는 결제 성공 시 payments.py가 자동으로 PENDING으로 옮긴다.
            for forbidden in ("PENDING", "PAYMENT_REQUIRED"):
                r_forbid = client.patch("/api/v1/admin/registry-requests/%d" % reg_ids[0],
                                        json={"status": forbidden},
                                        headers={"X-Admin-Key": TEST_SUPER_ADMIN_KEY})
                check("관리자가 직접 바꿀 수 없는 값(%s)은 400" % forbidden,
                      r_forbid.status_code, 400)
                after = conn.execute("SELECT status FROM registry_requests WHERE id=?",
                                     (reg_ids[0],)).fetchone()["status"]
                check("%s 시도 후에도 상태 불변" % forbidden, after, "PENDING")

            # ── 상태값 가드가 전이 검사와 어떻게 다른가 (2026-08-13 Sprint 91) ──────
            #
            # 변이 시험에서 알게 된 것: `if req.status not in ("PROCESSING","COMPLETED",
            # "FAILED")` 가드를 제거해도 **위 검사들이 전부 통과했다.** ALLOWED_TRANSITIONS가
            #
            #     PENDING    -> {FAILED, PROCESSING}
            #     PROCESSING -> {COMPLETED, FAILED}
            #
            # 뿐이라, 그 가드가 막는 값은 하류 전이 검사도 전부 막기 때문이다.
            #
            # 두 검사가 갈라지는 지점은 **순서**다. 가드는 DB 조회 **이전**에 돌고
            # 전이 검사는 조회 **이후**에 돈다. 그래서 없는 신청 + 잘못된 상태값이면
            #
            #     가드 있음 -> 400 (상태값이 잘못됐다)
            #     가드 없음 -> 404 (신청이 없다)
            #
            # 가 된다. 운영자가 상태값을 오타냈을 때 "신청이 없다"고 답하면 엉뚱한 곳을
            # 찾게 되므로, 이 순서가 곧 진단 품질이다.
            r_order = client.patch("/api/v1/admin/registry-requests/999999999",
                                   json={"status": "NOT_A_STATUS"},
                                   headers={"X-Admin-Key": TEST_SUPER_ADMIN_KEY})
            check("없는 신청이어도 상태값 오류가 먼저다(404가 아니라 400)",
                  r_order.status_code, 400)
            check_true("그 400이 상태값을 지목한다",
                       "NOT_A_STATUS" in r_order.text, r_order.text[:80])
    finally:
        if reg_ids:
            conn.execute("DELETE FROM registry_requests WHERE user_id=?", (reg_user,))
            conn.commit()
        conn.close()


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

    # ── _dump()의 두 분기와 admin_id 필터 (2026-08-13 Sprint 87) ──────────────
    #
    # 커버리지가 지목했다: `api/v1/audit.py`의 `_dump()`가 **None으로도 문자열로도
    # 호출된 적이 없었고**, `get_audit_logs(admin_id=...)` 필터도 미검증이었다.
    # 지금까지는 dict만 들어와 json.dumps 경로만 돌았다.
    #
    # 세 가지 모두 조용히 틀릴 수 있는 자리다.
    #
    #   _dump(None) 이 "null" 문자열을 돌려주면  생성 이벤트의 before가 **값이 있는 것처럼**
    #                                          보인다(NULL과 문자열 "null"은 다르다)
    #   _dump(str) 이 다시 json.dumps하면        문자열이 이중 인코딩돼 화면에 따옴표가 남는다
    #   admin_id 필터가 빗나가면                 "이 관리자가 무엇을 했는가"를 못 찾는다
    #
    # 감사 로그는 사후 추적의 유일한 근거라 표기 하나가 틀리면 판단이 틀어진다.
    from api.v1.audit import _dump, record_audit, get_audit_logs

    check("_dump(None)은 None (문자열 'null'이 아니다)", _dump(None), None)
    check("_dump(str)은 그대로 통과(이중 인코딩 없음)", _dump("이미 문자열"), "이미 문자열")
    check("_dump(dict)은 JSON 문자열", _dump({"a": 1}), '{"a": 1}')
    check_true("_dump(dict)은 한글을 이스케이프하지 않는다",
               "서울" in _dump({"court": "서울"}), _dump({"court": "서울"}))

    # DB 레벨: before=None으로 기록하면 컬럼이 NULL이어야 한다(문자열 "null"이 아니라).
    conn = get_connection()
    try:
        actor = "qa-reg-audit-actor-" + uuid.uuid4().hex[:6]
        target = "qa-audit-target-" + uuid.uuid4().hex[:6]
        record_audit(conn, admin_id=actor, action="SOFT_DELETE",
                     target_type="USER", target_id=target,
                     before=None, after="문자열 그대로")
        conn.commit()
        row = conn.execute(
            "SELECT before, after FROM audit_logs WHERE target_id=?", (target,)).fetchone()
        check("before=None은 컬럼 NULL", row["before"], None)
        check("after=문자열은 그대로 저장", row["after"], "문자열 그대로")

        # admin_id 필터가 실제로 걸리는가 — 다른 행위자의 기록이 섞이면 안 된다.
        total, items = get_audit_logs(conn, admin_id=actor, limit=50, offset=0)
        check("admin_id 필터가 그 행위자만 돌려준다", total, 1)
        check_true("돌려준 행이 그 행위자다",
                   items and items[0]["admin_id"] == actor, items)
        # 존재하지 않는 행위자는 빈 결과(에러가 아니라).
        empty_total, empty_items = get_audit_logs(
            conn, admin_id="qa-nobody-" + uuid.uuid4().hex[:6], limit=50, offset=0)
        check("없는 행위자는 빈 결과", (empty_total, empty_items), (0, []))
    finally:
        conn.execute("DELETE FROM audit_logs WHERE target_id=?", (target,))
        conn.commit()
        conn.close()

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

    # ── 목록 필터의 잘못된 값 (2026-08-13 Sprint 74) ──────────────────────────
    # Admin 16개 엔드포인트를 경계 상태로 전수 스윕하다 발견했다. 잘못된 필터 값을
    # 다루는 방식이 **세 갈래로 갈려 있었다.**
    #
    #     registry-requests?status=오타            400  허용값 안내
    #     payments/webhooks?processing_status=오타  400  허용값 안내
    #     payments?status=오타                     200  빈 목록   <- 오타를 결과 없음으로 오인
    #     subscriptions?status=오타                200  빈 목록   <-
    #     audit-logs?target_type=오타              200  빈 목록   <-
    #
    # 운영자가 필터를 잘못 적으면 "이 상태인 건이 한 건도 없다"로 읽힌다. 조회 결과를
    # 근거로 판단하는 자리라 조용한 오답이 그대로 운영 판단이 된다.
    # (프런트에서 BUGS #31이 "빈 결과"와 "페이지 범위 초과"를 갈라 놓은 것과 같은 부류)
    #
    # 새 정책이 아니라 이 파일이 이미 검증하고 있던 두 엔드포인트의 방식에 나머지를 맞춘 것이다.
    for path, param in (
        ("/api/v1/admin/payments", "status"),
        ("/api/v1/admin/payments", "payment_type"),
        ("/api/v1/admin/subscriptions", "status"),
        ("/api/v1/admin/audit-logs", "target_type"),
        ("/api/v1/admin/audit-logs", "action"),
        ("/api/v1/admin/registry-requests", "status"),
        ("/api/v1/admin/payments/webhooks", "processing_status"),
    ):
        bad = client.get("%s?%s=NOT_A_REAL_VALUE" % (path, param), headers=ah)
        check("%s?%s 오타는 400" % (path, param), bad.status_code, 400)
        detail = str(bad.json().get("detail", ""))
        check_true("%s?%s 400 메시지가 허용값을 알려준다" % (path, param),
                   "허용값" in detail or "허용되지 않는" in detail,
                   "메시지=%r ― 무엇이 잘못됐는지 알 수 없으면 400의 의미가 없다" % detail[:80])

    # 빈 값/미지정은 필터를 걸지 않는 것이므로 그대로 통과해야 한다(기존 동작 유지).
    for path, param in (("/api/v1/admin/payments", "status"),
                        ("/api/v1/admin/subscriptions", "status"),
                        ("/api/v1/admin/audit-logs", "target_type")):
        check("%s?%s= (빈 값)은 200" % (path, param),
              client.get("%s?%s=" % (path, param), headers=ah).status_code, 200)

    # 허용값은 Enum에서 도출돼야 한다 — 손으로 적어 두면 Enum이 늘 때 조용히 어긋난다.
    from api.v1 import admin as admin_mod
    from api.constants import PaymentStatus, SubscriptionStatus, AuditTargetType
    check("payments status 허용값이 Enum과 일치",
          set(admin_mod.VALID_PAYMENT_STATUSES), {s.value for s in PaymentStatus})
    check("subscriptions status 허용값이 Enum과 일치",
          set(admin_mod.VALID_SUBSCRIPTION_STATUSES), {s.value for s in SubscriptionStatus})
    check("audit target_type 허용값이 Enum과 일치",
          set(admin_mod.VALID_AUDIT_TARGET_TYPES), {t.value for t in AuditTargetType})

    # 정상 값은 여전히 통과해야 한다(검증이 정상 경로까지 막으면 안 된다).
    check("정상 status 값은 통과",
          client.get("/api/v1/admin/payments?status=PAID", headers=ah).status_code, 200)
    check("정상 구독 status 값은 통과",
          client.get("/api/v1/admin/subscriptions?status=ACTIVE", headers=ah).status_code, 200)

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

    # ── 감사 로그의 원자성: **실패한 조작은 흔적을 남기지 않는다** (2026-08-13 Sprint 75) ──
    #
    # `api/v1/audit.py:record_audit()`의 계약은 "commit은 호출부 책임이다 — 업무 트랜잭션과
    # 함께 커밋되어야 하므로"다. 지금까지의 검사는 **성공했을 때 로그가 남는가**만 봤다.
    # 계약의 나머지 절반(실패하면 남지 않는가)은 검증된 적이 없었다.
    #
    # 이 방향이 더 위험하다. 실패한 조작이 감사 로그에만 남으면 **하지도 않은 특권 조작이
    # 기록으로 존재**하게 되고, 반대로 성공한 조작이 안 남으면 추적이 끊긴다. 감사 로그는
    # "누가 무엇을 바꿨는가"를 사후에 판단하는 유일한 근거라 어느 쪽도 허용되지 않는다.
    #
    # ★ 2026-08-14 정정 — 위 문단은 원래 이렇게 적혀 있었다:
    #
    #     "admin.py의 5개 호출부는 전부 record_audit(...) 다음에 같은 커넥션으로
    #      conn.commit()을 부르고, 실패 경로에서는 conn.rollback()으로 되돌린다
    #      (정적 확인 완료)"
    #
    #   **5개 중 2개가 사실이 아니었다.** `update_registry_request_status` 와
    #   `adjust_registry_credit` 는 본 작업을 먼저 커밋한 뒤에 record_audit 을 불렀다.
    #   즉 감사 기록이 실패하면 **기록 없는 특권 조작이 영구히 남는** 상태였다.
    #   실측 재현(record_audit 에 예외 주입, 수정 전):
    #
    #       registry_credits +1 / registry_credit_logs +1 / audit_logs +0
    #
    #   "정적 확인 완료"라고 적힌 주장이 틀렸던 것이라, 아래에 **구조 검사**를 넣어
    #   같은 착오가 반복되지 않게 한다(주석이 아니라 코드가 확인하게 만든다).
    #   수정 후에는 셋 다 0이 된다.
    def audit_commit_order_violations():
        """record_audit 앞에서 본 작업을 커밋하는 admin 엔드포인트를 찾는다."""
        import ast as _ast
        import re as _re

        path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "api", "v1", "admin.py")
        with open(path, encoding="utf-8-sig") as _fh:
            src = _fh.read()
        lines = src.splitlines()
        bad = []
        for node in _ast.walk(_ast.parse(src, filename=path)):
            if not isinstance(node, (_ast.FunctionDef, _ast.AsyncFunctionDef)):
                continue
            body = [l.split("#")[0]
                    for l in lines[node.lineno - 1:(node.end_lineno or node.lineno)]]
            audits = [i for i, l in enumerate(body) if "record_audit(" in l]
            if not audits:
                continue
            commits = [i for i, l in enumerate(body)
                       if _re.search(r"\bconn\.commit\(\)", l)]
            if any(i < audits[0] for i in commits):
                bad.append(node.name)
        return sorted(bad)

    check("본 작업을 감사보다 먼저 커밋하는 admin 엔드포인트 없음",
          audit_commit_order_violations(), [])

    # 여기서는 그 결과를 **실제 응답과 DB로** 확인한다.
    def audit_count(target_type, target_id):
        c = get_connection()
        try:
            return c.execute(
                "SELECT COUNT(*) FROM audit_logs WHERE target_type=? AND target_id=?",
                (target_type, str(target_id))).fetchone()[0]
        finally:
            c.close()

    before_cnt = audit_count("SUBSCRIPTION", sub_id)
    # 규칙에 없는 전이(PAUSED -> GRACE_PERIOD)는 400이어야 하고, 감사 로그도 남으면 안 된다.
    rejected = client.patch("/api/v1/admin/subscriptions/%d" % sub_id,
                            json={"status": "GRACE_PERIOD", "reason": "should not be audited"},
                            headers=sh)
    check("거부된 전이는 400", rejected.status_code, 400)
    check("거부된 전이는 감사 로그를 남기지 않는다",
          audit_count("SUBSCRIPTION", sub_id), before_cnt)

    # 없는 대상에 대한 조작도 마찬가지다.
    ghost_before = audit_count("SUBSCRIPTION", 99999999)
    client.patch("/api/v1/admin/subscriptions/99999999",
                 json={"status": "PAUSED", "reason": "ghost"}, headers=sh)
    check("없는 구독 조작은 감사 로그를 남기지 않는다",
          audit_count("SUBSCRIPTION", 99999999), ghost_before)

    # 권한 부족(ADMIN이 SUPER_ADMIN 작업 시도)도 흔적을 남기면 안 된다 —
    # 시도 자체는 admin.py가 WARNING 로그로 남기지만 audit_logs는 "실제로 바뀐 것"만 담는다.
    forbidden_before = audit_count("SUBSCRIPTION", sub_id)
    check("권한 부족은 403",
          client.patch("/api/v1/admin/subscriptions/%d" % sub_id,
                       json={"status": "CANCELLED"}, headers=ah).status_code, 403)
    check("권한 부족 시도는 감사 로그를 남기지 않는다",
          audit_count("SUBSCRIPTION", sub_id), forbidden_before)

    # 반대 방향도 함께 고정한다 — 성공한 조작은 반드시 남아야 한다(둘이 짝이어야 계약이 성립).
    ok_before = audit_count("SUBSCRIPTION", sub_id)
    check("정상 전이는 200",
          client.patch("/api/v1/admin/subscriptions/%d" % sub_id,
                       json={"status": "ACTIVE", "reason": "resume"}, headers=sh).status_code, 200)
    check("성공한 조작은 감사 로그를 남긴다",
          audit_count("SUBSCRIPTION", sub_id), ok_before + 1)

    # 호출부 구조 자체도 고정한다 — record_audit 뒤에 commit이 오지 않으면
    # "업무는 커밋됐는데 감사만 빠지는" 상태가 생긴다(정적으로만 잡을 수 있는 형태다).
    admin_src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                  "api", "v1", "admin.py"), encoding="utf-8-sig").read()
    unpaired = []
    for idx in range(len(admin_src)):
        pos = admin_src.find("record_audit(", idx)
        if pos == -1:
            break
        idx = pos + 1
        tail = admin_src[pos:pos + 1500]
        commit_at = tail.find("conn.commit()")
        return_at = tail.find("return ")
        if commit_at == -1 or (return_at != -1 and return_at < commit_at):
            unpaired.append(admin_src[:pos].count("\n") + 1)
    check("record_audit 뒤에는 반드시 commit이 온다(줄번호)", unpaired, [])

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
    #
    # ★ 목록을 손으로 적지 않는다 (2026-08-14 정정).
    #
    #   원래 여기에는 favorites.py / search_presets.py / search.py **3개**가 박혀 있었다.
    #   그런데 소프트 삭제 대상 테이블을 읽는 파일은 실제로 **5개**다 —
    #   `item.py`(물건 상세의 하트)와 `admin.py`(사용자 목록 UNION, favorite_count)가
    #   빠져 있었다. 이 목록의 용도가 "배선할 때 함께 고칠 곳"인데 **목록 자체가 불완전**하면,
    #   그것을 믿고 전환한 사람은 상세 화면의 하트와 관리자 통계에서 지운 즐겨찾기를 계속 본다.
    #
    #   손으로 적은 목록은 코드가 늘면 어긋난다(Sprint 106의 "정적 확인 완료" 주석과 같은
    #   실패 모양이다). 그래서 **코드에서 유도한다** — 그 테이블을 읽는 파일을 찾아서 검사한다.
    #   새 라우터가 favorites를 읽기 시작하면 목록에 자동으로 들어온다.
    import io
    import re
    import tokenize

    api_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "api")
    # 테이블명이 그냥 등장하는 것으로는 부족하다 — `api/constants.py` 처럼 **설명 문자열**에
    # 파일명이 적혀 있는 경우가 걸린다(실제로 걸렸다). 질의로 쓰는 것만 고른다.
    soft_sql = re.compile(r"\b(?:FROM|INTO|UPDATE|JOIN)\s+(?:favorites|search_presets)\b",
                          re.IGNORECASE)
    readers, wired = [], []
    for dirpath, dirnames, filenames in os.walk(api_dir):
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        for fn in sorted(filenames):
            if not fn.endswith(".py"):
                continue
            full = os.path.join(dirpath, fn)
            with open(full, "rb") as fh:
                src = fh.read().decode("utf-8-sig")
            # 주석/문자열을 걷어낸 **코드만** 본다 — 설명 주석에 컬럼명이 나왔다고
            # "배선됐다"고 오판하지 않기 위해서다(앞선 스프린트에서 3번 겪은 실패 모양).
            code = []
            try:
                for tok in tokenize.generate_tokens(io.StringIO(src).readline):
                    if tok.type not in (tokenize.COMMENT,):
                        code.append(tok.string)
            except (tokenize.TokenError, IndentationError):
                code = [src]
            code = " ".join(code)
            rel = os.path.relpath(full, os.path.dirname(api_dir)).replace("\\", "/")
            if soft_sql.search(code):
                readers.append(rel)
                if "deleted_at" in code:
                    wired.append(rel)

    check_true("소프트 삭제 테이블을 읽는 파일을 실제로 찾았다", len(readers) >= 5, readers)
    print("   대상 파일 %d개: %s" % (len(readers), ", ".join(readers)))
    check("아직 어느 조회에도 deleted_at 조건이 없다", wired, [])

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

    # --- 실연동 전 provider로 환불 시도: DB만 REFUNDED가 되면 안 된다 (Sprint 78) ---
    #
    # 커버리지로 찾은 미검증 경로다(`api/v1/payments.py` 539-549). 이 분기의 주석이 위험을
    # 정확히 적어 두었다 — "PG에서 실제로 환불되지 않았는데 DB만 REFUNDED가 되는 것이 최악의
    # 결과다." KG이니시스 Provider는 계약 전이라 전 메서드가 NotImplementedError이고,
    # `PAYMENT_PROVIDER`를 바꾸는 순간(운영자의 .env 한 줄) 이 경로가 실제로 열린다.
    #
    # **실제 PG를 부르지 않는다** — kginicis Provider는 호출 즉시 NotImplementedError를
    # 던지도록 되어 있어(자리만 잡아둔 상태) 외부 통신이 발생하지 않는다.
    # 환경변수는 이 프로세스에서만 바꾸고 반드시 되돌린다.
    user = TEST_USER + "-refund-unimpl"
    pid, amount = _make_paid_payment(user)
    # 시도 **전** 상태를 기록해 둔다. 어떤 값이 "결제 완료"인지는 provider가 정하므로
    # (Mock은 레거시 SUCCESS, 실연동은 PAID — api/constants.py:is_paid가 둘 다 인정한다)
    # 특정 값을 기대하지 않고 **변하지 않았다**만 본다.
    conn = get_connection()
    try:
        status_before = conn.execute(
            "SELECT status FROM payments WHERE id=?", (pid,)).fetchone()["status"]
    finally:
        conn.close()

    saved_provider = os.environ.get("PAYMENT_PROVIDER")
    os.environ["PAYMENT_PROVIDER"] = "kginicis"
    try:
        r = client.post("/api/v1/admin/payments/%d/refund" % pid,
                        json={"reason": "미구현 provider 환불 시도"}, headers=sh)
        check("실연동 전 provider 환불은 실패로 끝난다", r.status_code, 400)
        # Admin은 실패를 envelope가 아니라 HTTPException(detail)로 돌려준다
        # (api/v1/admin.py 상단 주석의 기존 결정). envelope의 error를 기대하면 안 된다.
        detail_msg = r.json().get("detail", "")
        check_true("실패 사유가 응답에 담긴다", "환불 처리에 실패" in str(detail_msg), r.json())
        check_true("어느 provider의 어느 단계인지까지 담긴다",
                   "KGInicisProvider" in str(detail_msg) and "cancel_payment" in str(detail_msg),
                   detail_msg)
    finally:
        if saved_provider is None:
            os.environ.pop("PAYMENT_PROVIDER", None)
        else:
            os.environ["PAYMENT_PROVIDER"] = saved_provider

    # ★ 돈 안전 불변식: 상태가 바뀌지 않았어야 한다.
    conn = get_connection()
    try:
        row = conn.execute("SELECT status FROM payments WHERE id=?", (pid,)).fetchone()
    finally:
        conn.close()
    check("PG 환불 실패 시 결제 상태 불변(REFUNDED로 바뀌지 않는다)",
          row["status"], status_before)
    check_true("종결 상태로 넘어가지 않았다", row["status"] not in ("REFUNDED", "PARTIAL_REFUND"),
               row["status"])

    # ── refund_payment()의 소유권 인자 (2026-08-13 Sprint 94) ──────────────────
    #
    # Sprint 72가 **잠재 IDOR 함정**으로 기록한 자리다. `refund_payment(user_id=None)`은
    # 기본값이 "소유권을 확인하지 않음"이고, 지금 유일한 호출부가 super-admin이라
    # 현재 IDOR는 없다. 그래서 **소유권 분기 자체가 한 번도 실행된 적이 없었다**
    # (커버리지 497-498 미커버).
    #
    # 위험은 나중이다. 누군가 사용자용 환불 경로를 만들면서 `user_id=`를 빠뜨리면
    # **아무나 남의 결제를 환불할 수 있다.** 기본값이 안전하지 않은 쪽이라 더 그렇다.
    # 그 분기가 실제로 동작하는지 지금 못박아 두면, 배선하는 사람이 믿고 쓸 수 있다.
    from api.v1.payments import refund_payment, RefundError

    owner = TEST_USER + "-refund-owner"
    owned_pid, owned_amount = _make_paid_payment(owner)
    conn = get_connection()
    try:
        # (1) 남의 결제를 user_id로 환불하려 하면 "찾을 수 없음"이다
        #     (권한 오류가 아니라 404 — 존재 자체를 노출하지 않는다).
        denied = None
        try:
            refund_payment(conn, owned_pid, None, "타인 환불 시도",
                           actor="USER", user_id="qa-reg-not-the-owner")
        except RefundError as exc:
            denied = exc
        check_true("타인 user_id로는 환불되지 않는다", denied is not None,
                   "소유권 필터가 걸리지 않았다 - 남의 결제를 환불할 수 있다")
        if denied is not None:
            check("거부는 404(존재를 노출하지 않는다)", denied.http_status, 404)
        conn.rollback()

        # 상태가 바뀌지 않았어야 한다.
        after_denied = conn.execute(
            "SELECT status FROM payments WHERE id=?", (owned_pid,)).fetchone()["status"]
        check_true("거부된 시도는 상태를 바꾸지 않는다",
                   after_denied not in ("REFUNDED", "PARTIAL_REFUND"), after_denied)

        # (2) 본인 user_id면 정상 환불된다 — 필터가 정상 경로까지 막으면 안 된다.
        result = refund_payment(conn, owned_pid, None, "본인 환불",
                                actor="USER", user_id=owner)
        check("본인 user_id면 환불된다", result.payment_row["id"], owned_pid)
        check("잔여 전액이 환불된다", result.refunded_amount, owned_amount)
        conn.rollback()

        # (3) user_id를 주지 않으면 소유권을 보지 않는다(현재 Admin 경로의 동작).
        result2 = refund_payment(conn, owned_pid, None, "관리자 환불",
                                 actor="ADMIN")
        check("user_id 없이도 환불된다(Admin 경로)", result2.payment_row["id"], owned_pid)
        conn.rollback()
    finally:
        conn.close()

    detail = client.get("/api/v1/admin/payments/%d/logs" % pid, headers=ah).json()["data"]
    cancels = [l for l in detail if l["event_type"] == "CANCEL"]
    check("실패한 환불도 원장에 남는다(시도를 추적할 수 있다)", len(cancels), 1)
    check("그 기록은 FAILED 상태다", cancels[0]["status"], "FAILED")
    check_true("실패 사유가 기록된다", bool(cancels[0].get("error_message")), cancels[0])
    # 누적 환불액은 성공한 CANCEL만 세야 한다 — 실패 기록이 잔액을 깎으면
    # 나중에 진짜 환불을 할 때 "환불 가능 금액 초과"로 막힌다.
    again = client.post("/api/v1/admin/payments/%d/refund" % pid,
                        json={"reason": "mock으로 되돌린 뒤 정상 환불"}, headers=sh)
    check("provider를 되돌리면 전액 환불이 가능하다", again.status_code, 200)
    check("실패 기록이 누적 환불액을 오염시키지 않았다",
          again.json()["data"]["refunded_amount"], amount)

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

        # --- 저장된 payload가 손상된 경우 (2026-08-13 Sprint 94) ------------------
        #
        # 커버리지가 지목했다: `reprocess_webhook()`의 payload 파싱 실패 분기가 미커버였다.
        #
        # `raw_payload`는 수신 당시 그대로 저장한 텍스트다. 디스크 문제나 과거 데이터,
        # 수동 복구 과정에서 잘리거나 JSON이 아닌 값이 들어갈 수 있다. 그때 운영자가
        # 재처리 버튼을 누르면 **500이 아니라 읽을 수 있는 400**이어야 한다.
        # (500이면 운영자는 서버 장애로 오해하고 엉뚱한 곳을 본다)
        conn = get_connection()
        broken_ids = []
        try:
            ts = datetime.now().isoformat()
            for label, payload in (("잘린 JSON", '{"event_id": "x", "amo'),
                                   ("JSON이 아님", "not json at all"),
                                   ("객체가 아닌 JSON", '[1, 2, 3]')):
                broken_ids.append((label, conn.execute(
                    "INSERT INTO payment_webhooks (provider, event_type, event_id,"
                    " pg_transaction_id, signature_verified, processing_status,"
                    " raw_payload, received_at) VALUES (?,?,?,?,?,?,?,?)",
                    ("mock", "PAYMENT_CONFIRMED",
                     "qa-wh-broken-%s-%d" % (uuid.uuid4().hex[:6], len(broken_ids)),
                     future_tx, 1, "RECEIVED", payload, ts)).lastrowid))
            conn.commit()
        finally:
            conn.close()

        for label, bid in broken_ids:
            r_broken = None
            leaked_rp = None
            try:
                r_broken = client.post(
                    "/api/v1/admin/payments/webhooks/%d/reprocess" % bid, headers=sh)
            except Exception as exc:
                leaked_rp = exc
            check_true("%s: 예외가 새어 나오지 않는다" % label, leaked_rp is None,
                       "payload 파싱 가드가 사라졌는가? json.loads가 그대로 터진다: %r"
                       % (leaked_rp,))
            if r_broken is not None:
                check("%s: 500이 아니라 400" % label, r_broken.status_code, 400)
                check_true("%s: 사유가 payload를 지목한다" % label,
                           "payload" in r_broken.text, r_broken.text[:80])

        conn = get_connection()
        try:
            conn.execute("DELETE FROM payment_webhooks WHERE event_id LIKE 'qa-wh-broken-%'")
            conn.commit()
        finally:
            conn.close()

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

        # --- provider 필터 (2026-08-13 Sprint 78 신규) ---
        # Sprint 74가 "잘못된 필터 값은 400으로 거부한다"로 규약을 통일했는데, 이 함수의
        # `provider`만 빠져 있었다 — 바로 위 `processing_status`는 검증되고 `provider`는
        # 그대로 SQL로 들어가 오타에 200 + 빈 목록을 돌려줬다(실측).
        #
        # 검사가 무력해지지 않도록 **이 시점에 provider='mock' 행이 실재하는 상태**에서 본다.
        # 빈 테이블에서 검사하면 "필터가 동작한다"와 "아무것도 없다"를 구분할 수 없다.
        mock_list = client.get("/api/v1/admin/payments/webhooks?provider=mock", headers=ah).json()
        check_true("provider=mock 이 실제 행을 돌려준다(검사의 구분력 확보)",
                   len(mock_list["data"]) > 0, mock_list["meta"])
        check_true("provider 필터가 동작", all(i["provider"] == "mock" for i in mock_list["data"]),
                   [i["provider"] for i in mock_list["data"][:3]])

        check("오타 provider는 400으로 거부",
              client.get("/api/v1/admin/payments/webhooks?provider=BOGUS",
                         headers=ah).status_code, 400)

        # 유효하지만 해당 행이 없는 값은 **200 + 빈 목록**이어야 한다 —
        # "오타"와 "그 PG의 노티가 없다"가 이 두 응답으로 갈린다(고치기 전에는 둘 다 200이었다).
        valid_empty = client.get("/api/v1/admin/payments/webhooks?provider=kginicis", headers=ah)
        check("유효한 provider는 200", valid_empty.status_code, 200)
        check("유효하지만 없는 provider는 빈 목록", valid_empty.json()["data"], [])

        # 수신 경로는 provider 이름을 `.strip().lower()`로 정규화해 저장한다. 조회가 그
        # 정규화를 하지 않으면 "시스템이 받아주는 이름인데 조회에서는 거부"되는 비대칭이 생긴다.
        upper = client.get("/api/v1/admin/payments/webhooks?provider=MOCK", headers=ah)
        check("대문자 provider도 수신 경로와 같게 정규화", upper.status_code, 200)
        check_true("정규화 결과가 소문자 조회와 동일",
                   len(upper.json()["data"]) == len(mock_list["data"]),
                   (len(upper.json()["data"]), len(mock_list["data"])))

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
    # 물건 사진은 법원이 공개하는 경매 정보이고, 상세 화면(`/api/v1/item/{item_id}`)이
    # 이미 공개인데 그 화면에 그려질 사진만 인증을 요구하면 화면이 깨진다.
    # 문서 뷰어와 같은 판단이다.
    "/api/v1/item/{item_id}/images/{seq}",
    "/api/v1/plans",
}
# 사용자 인증은 없지만 다른 수단(서명)으로 보호되는 경로.
SIGNATURE_PROTECTED_ENDPOINTS = {"/api/v1/payments/webhook/{provider_name}"}

_PATH_SAMPLE = {
    "{item_id}": "1", "{payment_id}": "1", "{preset_id}": "1", "{request_id}": "1",
    "{doc_type}": "SPEC", "{user_id}": "qa-authz-probe", "{subscription_id}": "1",
    "{webhook_id}": "1", "{provider_name}": "mock", "{seq}": "1",
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

    # ★ 이 검사가 **조용히 좁아지지** 않게 한다 (2026-08-14 신설).
    #
    # 위 전수는 `app.openapi()` 로 라우트를 열거한다. 그런데 `include_in_schema=False` 인
    # 라우트는 스펙에 **아예 나오지 않는다.** 즉 누가 보호 엔드포인트에 그 인자를 붙이면
    # 이 검사는 실패하지 않고 **그 엔드포인트를 그냥 안 보게 된다.**
    #
    # 하필 그 인자를 붙이는 동기가 "내부용이라 문서에 안 띄우고 싶다"인 경우가 많다 ―
    # 즉 **가장 민감한 것부터** 검사 밖으로 빠질 수 있다. 검사가 줄어드는데 초록불이면
    # 줄어든 사실을 알 방법이 없다.
    #
    # 2026-08-14 실측: 구조상 42개 / 스펙 41개, 차이는 **문서 뷰어용 HEAD 하나**뿐이고
    # 그 HEAD는 공개 경로이며 GET과 인가 결과가 같다(둘 다 404). 그 상태를 고정한다.
    #
    # (이 FastAPI 버전은 `include_router` 결과를 `app.routes` 에 평탄화하지 않고
    #  `_IncludedRouter` 로 감싼다 ― 그냥 훑으면 라우트가 2개만 보여서 "전부 공개"라는
    #  거짓 정상 판정이 나온다. 그래서 감싼 것을 풀어서 센다.)
    structural = set()
    for r in api_server.app.routes:
        if type(r).__name__ == "_IncludedRouter":
            sub_prefix = r.include_context.prefix or ""
            subs = [(sub_prefix + s.path, s) for s in r.original_router.routes]
        else:
            subs = [(getattr(r, "path", ""), r)]
        for full_path, s in subs:
            for m in (getattr(s, "methods", None) or set()):
                structural.add((m.upper(), full_path))
    docs_paths = {"/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"}
    structural = {(m, p) for m, p in structural
                  if p not in docs_paths and m != "OPTIONS"}
    spec_pairs = {(m.upper(), p) for p, ops in spec["paths"].items() for m in ops}
    # 스펙 밖에 있어도 되는 것: 프런트가 **존재만 확인**하는 HEAD 둘.
    # 둘 다 같은 이유로 스펙에서 뺐다 — GET과 operationId가 겹치면 /openapi.json 생성이
    # 깨진다(각 라우터의 include_in_schema=False 주석 참고).
    ALLOWED_UNSPECED = {
        ("HEAD", "/api/v1/item/{item_id}/documents/{doc_type}"),
        ("HEAD", "/api/v1/item/{item_id}/images/{seq}"),
    }
    unspeced = structural - spec_pairs - ALLOWED_UNSPECED
    check_true("스펙에 없어 전수에서 빠지는 라우트 없음", not unspeced,
               "이 라우트들은 위 인가 전수를 통과한 적이 없다: %s" % sorted(unspeced))
    # 허용한 HEAD 가 사라지면 목록도 같이 줄여야 한다(죽은 예외가 남으면 검사가 헐거워진다).
    check_true("허용한 스펙 밖 라우트가 실재한다",
               ALLOWED_UNSPECED <= structural,
               "코드에서 사라진 예외: %s" % sorted(ALLOWED_UNSPECED - structural))
    # HEAD 는 GET 과 같은 인가를 받아야 한다 ― 다르면 HEAD 가 우회로가 된다.
    for _, hp in sorted(ALLOWED_UNSPECED):
        probe = hp
        for token, sample in _PATH_SAMPLE.items():
            probe = probe.replace(token, sample)
        g = client.get(probe).status_code
        h = client.request("HEAD", probe).status_code
        check_true("HEAD 와 GET 의 인가 결과가 같다 (%s)" % hp,
                   (g in (401, 403)) == (h in (401, 403)),
                   "GET %s / HEAD %s" % (g, h))

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
# 34. 문서 서빙의 방어 분기 (2026-08-13 Sprint 85 신설)
#
# 커버리지가 지목한 두 줄이다 ― `api/v1/documents.py` 48행(경로를 만들 수 없는 행은 404)과
# 58행(계산된 경로가 DOCUMENT_ROOT를 벗어나면 차단). 둘 다 **방어 코드인데 검사가 없었다.**
# 방어 코드에 검사가 없으면 리팩터링 때 조용히 사라지고, 사라진 사실은 사고로만 드러난다.
#
# 실제 DB에 조작된 행을 넣지 않는다 ― `court_name`에 `..`를 담은 행을 운영 테이블에 만드는
# 것 자체가 위험하고, 정리에 실패하면 흔적이 남는다. 대신 커넥션만 메모리 DB로 갈아끼운다
# (`test_race_conditions.py` §14가 쓴 방법과 같은 계열).
# ---------------------------------------------------------------------------
def test_document_serving_guards():
    import shutil as _shutil
    import sqlite3 as _sqlite3
    import tempfile as _tempfile
    import api.v1.documents as docs_mod

    print("\n--- 34. 문서 서빙 방어 분기 (Sprint 85) ---")

    def fetch(url, method="GET"):
        """서버가 예외를 던지면 TestClient는 그것을 그대로 올린다 ― 그대로 두면 결함이
        FAIL이 아니라 **크래시**로 나타나 집계에서 사라진다. 상태코드 자리에 None을 돌려
        어떤 기대값과도 맞지 않게 만든다."""
        try:
            r = client.request(method, url)
            return r.status_code, r.content
        except Exception as exc:  # noqa: BLE001
            return None, ("예외: %r" % (exc,)).encode("utf-8")

    # 경로 탈출이 **실제로 파일을 새게 만드는** 조건을 만든다. os.path.join은 두 번째
    # 인자가 절대경로면 앞을 버리므로, court_name에 절대경로가 들어오면 DOCUMENT_ROOT를
    # 즉시 벗어난다. 여기에 진짜 파일을 두고, 가드가 없으면 그 내용이 응답에 실리는지 본다
    # (파일이 없는 탈출 경로만 검사하면 "존재하지 않아서 404"와 구별되지 않는다).
    leak_dir = _tempfile.mkdtemp(prefix="qa_leak_")
    os.makedirs(os.path.join(leak_dir, "1"), exist_ok=True)
    with open(os.path.join(leak_dir, "1", "spec.pdf"), "wb") as fh:
        fh.write(b"%PDF-1.4 QA-SECRET-SHOULD-NOT-LEAK")

    mem = _sqlite3.connect(":memory:", check_same_thread=False)
    mem.row_factory = _sqlite3.Row
    mem.execute("CREATE TABLE auction_item (id INTEGER PRIMARY KEY, court_name TEXT,"
                " case_no TEXT, item_no TEXT)")
    mem.executemany(
        "INSERT INTO auction_item (id, court_name, case_no, item_no) VALUES (?,?,?,?)",
        [
            # 1) 경로를 만들 수 없는 행: court_name이 NULL. 예전에는 os.path.join이
            #    TypeError로 터져 500이었다(48행 주석).
            (9001, None, "2026타경1", "1"),
            (9002, "서울중앙지방법원", None, "1"),
            # 2) 경로 탈출 시도: 값 자체에 상위 디렉터리 이동이 들어 있다. 크롤 데이터가
            #    오염되거나 누가 직접 DB를 건드린 경우에 해당한다.
            (9003, "..", "..", "1"),
            (9004, "서울중앙지방법원", "../../../../windows", "1"),
            # 3) 정상 형태지만 파일이 없는 행 ― 404가 나야 하고, 그 이유는 탈출이 아니다.
            (9005, "존재하지않는법원", "2026타경9999", "1"),
            # 4) 절대경로 주입 ― 실제로 존재하는 파일을 가리킨다(가드가 없으면 유출된다).
            (9006, leak_dir, ".", "1"),
        ],
    )
    mem.commit()

    class _NoCloseConn:
        """엔드포인트는 finally에서 conn.close()를 부른다 ― 메모리 DB가 그때 사라지면
        다음 호출이 빈 DB를 보게 된다. close만 무시하고 나머지는 그대로 위임한다."""

        def __init__(self, conn):
            self._conn = conn

        def close(self):
            pass

        def __getattr__(self, name):
            return getattr(self._conn, name)

    real_get_connection = docs_mod.get_connection
    docs_mod.get_connection = lambda *a, **kw: _NoCloseConn(mem)
    try:
        # 잘못된 doc_type은 DB를 보기도 전에 400 ― 순서까지 고정한다(존재하지 않는 물건이어도
        # 400이어야 한다. 404가 나오면 DB를 먼저 보고 있다는 뜻이다).
        status, _ = fetch("/api/v1/item/9999999/documents/REGISTRY")
        check("지원하지 않는 문서 종류는 400", status, 400)

        status, _ = fetch("/api/v1/item/424242/documents/SPEC")
        check("없는 물건은 404", status, 404)

        for item_id, label in ((9001, "court_name이 NULL"), (9002, "case_no가 NULL")):
            status, body = fetch("/api/v1/item/%d/documents/SPEC" % item_id)
            # None이면 서버가 예외로 죽었다는 뜻이다 ― 그것도 이 검사가 잡아야 하는 결과다.
            check("%s인 행은 404(500도 예외도 아니다)" % label, status, 404)

        for item_id, label in ((9003, "법원명/사건번호가 '..'"),
                               (9004, "사건번호에 상위 경로 이동"),
                               (9006, "court_name에 절대경로 주입(실파일 존재)")):
            status, body = fetch("/api/v1/item/%d/documents/SPEC" % item_id)
            check("%s: 404로 차단" % label, status, 404)
            # 파일 내용이 새어 나오지 않았는지 ― 본문에 PDF 시그니처가 없어야 한다.
            check_true("%s: 응답에 파일 내용이 없다" % label,
                       b"%PDF" not in body and b"QA-SECRET" not in body, body[:60])

        status, _ = fetch("/api/v1/item/9005/documents/STATUS")
        check("정상 형태 + 파일 없음도 404", status, 404)

        # HEAD도 같은 방어를 지나야 한다(프론트가 뷰어를 열기 전에 HEAD로 확인한다).
        status, _ = fetch("/api/v1/item/9006/documents/SPEC", method="HEAD")
        check("HEAD도 경로 탈출을 차단한다", status, 404)
        status, _ = fetch("/api/v1/item/9001/documents/SPEC", method="HEAD")
        check("HEAD도 경로를 만들 수 없으면 404", status, 404)
    finally:
        docs_mod.get_connection = real_get_connection
        mem.close()
        _shutil.rmtree(leak_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# 35. 관심물건 등록 실패를 "이미 등록됨"으로 오해하지 않는다 (2026-08-13 Sprint 85 신설)
#
# `api/v1/favorites.py` 57-59행(중복 위반이 **아닌** 예외는 감추지 않고 올린다)이 미커버였다.
# 이 분기는 과거의 실제 결함을 고친 자리다 ― 예전에는 `except Exception`으로 전부 잡아
# DB 잠금/디스크 오류까지 "이미 관심물건으로 등록되어 있습니다"로 안내했다. 그러면 사용자는
# 등록됐다고 믿고 넘어가고, 운영자는 오류를 볼 수 없다.
# ---------------------------------------------------------------------------
def test_favorite_insert_failure_is_not_masked():
    import api.v1.favorites as fav_mod

    print("\n--- 35. 관심물건 등록 실패 격리 (Sprint 85) ---")
    user = "qa-reg-favfail-" + uuid.uuid4().hex[:8]
    item_id = pick_item_ids(1)[0]

    real_get_connection = fav_mod.get_connection

    class _FailingInsert:
        """INSERT만 IntegrityError가 **아닌** 오류로 실패시킨다(디스크/잠금 오류를 흉내)."""

        def __init__(self, conn):
            self._conn = conn
            self.rolled_back = False

        def execute(self, sql, *a, **kw):
            if sql.lstrip().upper().startswith("INSERT INTO FAVORITES"):
                raise sqlite3.OperationalError("database is locked (qa-injected)")
            return self._conn.execute(sql, *a, **kw)

        def rollback(self):
            self.rolled_back = True
            return self._conn.rollback()

        def __getattr__(self, name):
            return getattr(self._conn, name)

    box = {}

    def patched(*a, **kw):
        box["conn"] = _FailingInsert(real_get_connection(*a, **kw))
        return box["conn"]

    fav_mod.get_connection = patched
    try:
        raised = None
        try:
            r = client.post("/api/v1/favorites", json={"item_id": item_id},
                            headers=auth_headers(user))
            status = r.status_code
            body = r.text
        except Exception as exc:  # TestClient는 서버 예외를 그대로 올린다
            raised = exc
            status = None
            body = ""
    finally:
        fav_mod.get_connection = real_get_connection

    # 어떤 형태로든 **성공으로 보이지 않아야** 하고, "이미 등록됨"으로 오해되지도 않아야 한다.
    check_true("성공(200 + success)으로 응답하지 않는다", status != 200 or '"success": true' not in body,
               (status, body[:120]))
    check_true("'이미 등록' 안내로 감추지 않는다", "이미 관심물건" not in body, body[:120])
    check_true("오류가 드러난다(예외 전파 또는 5xx)",
               raised is not None or (status is not None and status >= 500), (raised, status))
    check_true("실패 시 롤백한다", box.get("conn") is not None and box["conn"].rolled_back,
               "rollback이 호출되지 않았다")

    # 실제로 등록되지 않았는지 DB로 확인한다(응답만 보고 판단하지 않는다).
    conn = get_connection()
    try:
        left = conn.execute("SELECT COUNT(*) FROM favorites WHERE user_id=?", (user,)).fetchone()[0]
    finally:
        conn.close()
    check("실패한 등록은 남지 않는다", left, 0)

    # 대조군: 같은 요청이 정상 경로에서는 성공한다(위 실패가 주입 때문임을 보인다).
    r = client.post("/api/v1/favorites", json={"item_id": item_id}, headers=auth_headers(user))
    check("대조군: 정상 경로에서는 200", r.status_code, 200)
    client.delete("/api/v1/favorites/%d" % item_id, headers=auth_headers(user))


# ---------------------------------------------------------------------------
# 36. 결제·Webhook의 남은 실패 분기 (2026-08-13 Sprint 85 신설)
#
# 커버리지가 `api/v1/payments.py`에 남긴 미커버 중 **Mock Provider로 도달 가능한** 실패
# 분기들이다(실연동은 계속 SKIP). 돈이 걸린 경로라 우선순위를 가장 높게 뒀다.
#
#   514행  환불 가능 잔액 0 -> 두 번째 환불 거절     (이중 환불 방어)
#   557행  조건부 UPDATE rowcount=0 -> 409          (동시 환불 방어의 **실행** 경로)
#   629행  Webhook payload 해석 불가 -> 400
#   682행  pg_transaction_id 없음 -> skip
#   693행  같은 상태 재통지 -> 멱등 skip
#   761행  재처리: 알 수 없는 provider -> 400
#   767행  재처리: 저장된 payload 해석 불가 -> 400
# ---------------------------------------------------------------------------
def test_payment_failure_branches():
    print("\n--- 36. 결제/Webhook 남은 실패 분기 (Sprint 85) ---")
    # 환불과 Webhook 재처리는 둘 다 SUPER_ADMIN 전용이다(§29/§31이 그 경계를 고정했다).
    super_headers = {"X-Admin-Key": TEST_SUPER_ADMIN_KEY}
    saved_secret = os.environ.get("PAYMENT_WEBHOOK_SECRET")
    os.environ["PAYMENT_WEBHOOK_SECRET"] = WEBHOOK_SECRET

    # -- (1) 전액 환불 뒤 같은 요청이 또 오면 **멱등 성공**이다 (오류가 아니다) ----
    #
    # 처음에 이 검사를 "두 번째 환불은 거절된다"로 썼는데 200이 왔다. 제품이 아니라 **검사의
    # 가정이 틀렸다** ― `refund_payment()`는 이미 REFUNDED인 결제에 다시 요청이 오면
    # `already_refunded=True`, 환불액 0으로 돌려준다(등기부 `already_requested`, 구독
    # `already_subscribed`와 같은 규약이다).
    #
    # 그래서 여기서 지켜야 할 것은 "거절"이 아니라 **원장이 두 번 계상되지 않는 것**이다.
    # 멱등 성공이 원장에 환불을 한 번 더 적으면 총 환불액이 결제액의 2배가 되고, 그 뒤로는
    # 정산이 영구히 어긋난다. 돈 관련 멱등에서 진짜 위험은 그쪽이다.
    user = TEST_USER + "-refund-twice"
    pid, amount = _make_paid_payment(user)
    r1 = client.post("/api/v1/admin/payments/%d/refund" % pid,
                     json={"reason": "qa-full-refund"}, headers=super_headers)
    check("전액 환불은 성공한다", r1.status_code, 200)
    d1 = r1.json()["data"]
    check("첫 환불액은 결제액 전액", d1["refunded_amount"], amount)
    check("첫 환불 후 잔여는 0", d1["refundable_remaining"], 0)
    check("첫 환불은 멱등 응답이 아니다", d1["already_refunded"], False)

    r2 = client.post("/api/v1/admin/payments/%d/refund" % pid,
                     json={"reason": "qa-second-refund"}, headers=super_headers)
    check("같은 환불 재요청은 멱등 성공", r2.status_code, 200)
    d2 = r2.json()["data"]
    check("멱등 응답임을 표시한다", d2["already_refunded"], True)
    check("두 번째 요청의 환불액은 0", d2["refunded_amount"], 0)
    check("누적 환불액이 결제액을 넘지 않는다", d2["total_refunded"], amount)

    conn = get_connection()
    try:
        ledger = conn.execute(
            "SELECT COALESCE(SUM(amount),0) FROM payment_logs"
            " WHERE payment_id=? AND event_type='CANCEL' AND status='SUCCESS'",
            (pid,)).fetchone()[0]
        rows = conn.execute(
            "SELECT COUNT(*) FROM payment_logs"
            " WHERE payment_id=? AND event_type='CANCEL' AND status='SUCCESS'",
            (pid,)).fetchone()[0]
        audits = conn.execute(
            "SELECT COUNT(*) FROM audit_logs WHERE target_type='PAYMENT' AND target_id=?",
            (str(pid),)).fetchone()[0]
    finally:
        conn.close()
    check("원장의 환불 합계가 결제액 그대로다(2배가 아니다)", ledger, amount)
    check("원장에 환불 성공 기록은 한 건뿐이다", rows, 1)
    # 멱등 응답은 감사 로그도 남기지 않는다(admin.py가 already_refunded를 보고 건너뛴다).
    check("멱등 재요청은 감사 로그를 늘리지 않는다", audits, 1)

    # -- (2) 동시 환불 방어의 **1차 방어선**을 직접 확인한다 (BEGIN IMMEDIATE) -----
    #
    # 처음 의도는 admin 409 분기(payments.py 557행)를 §14처럼 결정적으로 태우는 것이었다.
    # 그런데 커넥션을 감싸 `UPDATE payments` 직전에 다른 커넥션으로 끼어들려 하니 **끼어든
    # 쪽이 쓰기를 하지 못했다**. 이유가 곧 답이다 - `refund_payment()`는 함수 진입 직후
    # `BEGIN IMMEDIATE`로 쓰기 락을 선점한다. 그래서 같은 프로세스/같은 DB에서는 조회와
    # UPDATE 사이에 다른 쓰기가 끼어들 수 없고, 557행의 rowcount 검사는 **락 뒤의 이중
    # 방어**다(도달시키려면 락을 우회해야 하는데, 그건 제품 동작이 아니다).
    #
    # 그래서 검사의 방향을 바꿨다: 못 태우는 분기를 억지로 태우는 대신, **1차 방어선이
    # 실제로 직렬화하는지**를 확인한다. 이것도 지금까지 소스 문자열 검사밖에 없었다
    # (test_race_conditions.py §7). 끼어든 쓰기가 "database is locked"로 막히는 것이
    # BEGIN IMMEDIATE가 살아 있다는 실행 증거다.
    import api.v1.admin as admin_mod
    import storage.database as dbmod

    user2 = TEST_USER + "-refund-lock"
    pid2, amount2 = _make_paid_payment(user2)
    attempt = {}

    def interloper():
        # 타임아웃을 짧게 잡는다(기본 5초를 기다릴 이유가 없다).
        c = sqlite3.connect(dbmod.DB_PATH, timeout=0.3)
        try:
            c.execute("UPDATE payments SET status='REFUNDED' WHERE id=?", (pid2,))
            c.commit()
            attempt["result"] = "wrote"
        except sqlite3.OperationalError as exc:
            attempt["result"] = "blocked"
            attempt["error"] = str(exc)
        finally:
            c.close()

    class _Interleave:
        """`UPDATE payments SET status` 직전에 다른 커넥션의 쓰기를 시도한다.

        속성 **대입**도 감싼 커넥션으로 넘겨야 한다 - `refund_payment()`가
        `conn.isolation_level = None`을 설정하는데, 래퍼에만 붙으면 실제 커넥션의 트랜잭션
        모드가 바뀌지 않아 BEGIN IMMEDIATE가 의도대로 동작하지 않는다(그러면 검사가
        제품이 아니라 래퍼를 시험하게 된다).
        """

        def __init__(self, conn):
            object.__setattr__(self, "_conn", conn)
            object.__setattr__(self, "fired", False)

        def execute(self, sql, *a, **kw):
            if not self.fired and sql.lstrip().upper().startswith("UPDATE PAYMENTS SET STATUS"):
                object.__setattr__(self, "fired", True)
                interloper()
            return self._conn.execute(sql, *a, **kw)

        def __getattr__(self, name):
            return getattr(self._conn, name)

        def __setattr__(self, name, value):
            setattr(self._conn, name, value)

    real_get_connection = admin_mod.get_connection
    box = {}

    def patched(*a, **kw):
        box["w"] = _Interleave(real_get_connection(*a, **kw))
        return box["w"]

    admin_mod.get_connection = patched
    try:
        r = client.post("/api/v1/admin/payments/%d/refund" % pid2,
                        json={"reason": "qa-lock-probe"}, headers=super_headers)
    finally:
        admin_mod.get_connection = real_get_connection

    check("끼어들기 시도가 실제로 실행됐다", box.get("w").fired if box.get("w") else None, True)
    check("끼어든 쓰기는 락에 막힌다(BEGIN IMMEDIATE가 살아 있다)",
          attempt.get("result"), "blocked")
    check_true("막힌 이유가 잠금이다", "locked" in attempt.get("error", ""), attempt)
    check("락을 잡은 쪽의 환불은 정상 완료된다", r.status_code, 200)

    conn = get_connection()
    try:
        st = conn.execute("SELECT status FROM payments WHERE id=?", (pid2,)).fetchone()["status"]
        entries = conn.execute(
            "SELECT COUNT(*) FROM payment_logs WHERE payment_id=? AND event_type='CANCEL'"
            " AND status='SUCCESS'", (pid2,)).fetchone()[0]
    finally:
        conn.close()
    check("최종 상태는 환불이다", st, "REFUNDED")
    check("원장에 환불 기록은 정확히 한 건이다", entries, 1)

    # ── (3) Webhook payload 해석 불가 ────────────────────────────────────────
    bad_body = b"{this is not json"
    r = client.post("/api/v1/payments/webhook/mock", content=bad_body,
                    headers={"Content-Type": "application/json",
                             "X-Webhook-Signature": _sign(bad_body)})
    check("해석 불가 payload는 400", r.status_code, 400)

    list_body = json.dumps([1, 2, 3]).encode("utf-8")
    r = client.post("/api/v1/payments/webhook/mock", content=list_body,
                    headers={"Content-Type": "application/json",
                             "X-Webhook-Signature": _sign(list_body)})
    check("객체가 아닌 payload도 400", r.status_code, 400)

    conn = get_connection()
    try:
        stored = conn.execute(
            "SELECT COUNT(*) FROM payment_webhooks WHERE raw_payload LIKE '%this is not json%'"
        ).fetchone()[0]
    finally:
        conn.close()
    check("해석 불가 요청은 행을 만들지 않는다", stored, 0)

    # -- (4) 무시되는 노티 두 종류 / (5) 같은 상태 재통지의 멱등 ----------------
    #
    # 여기서 한 번 헛돌았다. 처음에 `event_type="payment.paid"`로 보냈는데 통과했지만,
    # 그것은 **무시 이유가 달랐기 때문**이다 - Mock의 매핑표(WEBHOOK_EVENT_STATUS)에 없는
    # 이름이라 status가 빈 문자열이 되어 더 앞의 분기에서 걸렸다. 검사하려던 분기
    # (pg_transaction_id 없음 / 같은 상태)에는 **도달조차 못 했다.** 커버리지로 그 사실이
    # 드러났다(해당 줄이 그대로 미커버였다). 실제 event_type을 쓰도록 고친다.
    user3 = TEST_USER + "-wh-branches"
    pid3, _ = _make_paid_payment(user3)

    # (4-a) 매핑표에 없는 event_type - 상태를 바꾸지 않는다(Sprint 52에서 고친 결함:
    #       예전엔 event_type과 무관하게 항상 SUCCESS로 바꿨다).
    r = _post_webhook({"event_id": "qa-wh-unknown-" + uuid.uuid4().hex[:8],
                       "event_type": "payment.paid",
                       "pg_transaction_id": "qa-nonexistent-tx"})
    check("모르는 event_type은 200(무시)", r.status_code, 200)
    check_true("무시 사유가 응답에 담긴다", "reason" in json.dumps(r.json()), r.text[:160])

    # (4-b) 아는 event_type인데 pg_transaction_id가 없다 - 어느 결제인지 특정할 수 없다.
    r = _post_webhook({"event_id": "qa-wh-notx-" + uuid.uuid4().hex[:8],
                       "event_type": "PAYMENT_CONFIRMED"})
    check("pg_transaction_id 없는 노티는 200(무시)", r.status_code, 200)
    check_true("사유가 pg_transaction_id 부재를 알린다",
               "pg_transaction_id" in json.dumps(r.json(), ensure_ascii=False), r.text[:200])

    # (5) 이미 REFUNDED인 결제에 PAYMENT_REFUNDED가 다시 온다(PG 재전송의 정상 결과).
    #     같은 상태이므로 멱등하게 성공 처리하고 **원장을 늘리지 않아야** 한다 - 여기서
    #     환불 기록이 하나 더 생기면 총 환불액이 결제액을 넘는다.
    conn = get_connection()
    try:
        row = conn.execute("SELECT status, pg_transaction_id FROM payments WHERE id=?",
                           (pid,)).fetchone()
        before_entries = conn.execute(
            "SELECT COUNT(*) FROM payment_logs WHERE payment_id=? AND event_type='CANCEL'"
            " AND status='SUCCESS'", (pid,)).fetchone()[0]
    finally:
        conn.close()
    check("대상 결제는 이미 REFUNDED다(검사 전제)", row["status"], "REFUNDED")

    if row["pg_transaction_id"]:
        r = _post_webhook({"event_id": "qa-wh-same-" + uuid.uuid4().hex[:8],
                           "event_type": "PAYMENT_REFUNDED",
                           "pg_transaction_id": row["pg_transaction_id"]})
        check("같은 상태 재통지는 200", r.status_code, 200)
        body = json.dumps(r.json(), ensure_ascii=False)
        check_true("멱등 처리임을 사유로 알린다", "이미 동일한 상태" in body, body[:200])
        conn = get_connection()
        try:
            after = conn.execute("SELECT status FROM payments WHERE id=?", (pid,)).fetchone()["status"]
            after_entries = conn.execute(
                "SELECT COUNT(*) FROM payment_logs WHERE payment_id=? AND event_type='CANCEL'"
                " AND status='SUCCESS'", (pid,)).fetchone()[0]
        finally:
            conn.close()
        check("같은 상태 재통지가 상태를 바꾸지 않는다", after, "REFUNDED")
        check("같은 상태 재통지가 원장을 늘리지 않는다", after_entries, before_entries)
    else:
        check_true("pg_transaction_id가 없어 같은상태 재통지 검사를 생략", False,
                   "Mock 결제에 pg_transaction_id가 없다 - 전제가 바뀌었으면 검사를 고쳐야 한다")

    # ── (6)(7) 재처리: 알 수 없는 provider / 저장된 payload 해석 불가 ────────
    conn = get_connection()
    try:
        now = datetime.now().isoformat()
        bad_provider_id = conn.execute(
            "INSERT INTO payment_webhooks (provider, event_id, event_type, raw_payload,"
            " signature_verified, processing_status, received_at)"
            " VALUES (?,?,?,?,?,?,?)",
            ("qa-unknown-pg", "qa-wh-badpg-" + uuid.uuid4().hex[:8], "payment.paid",
             '{"event_type": "payment.paid"}', 1, "RECEIVED", now),
        ).lastrowid
        bad_payload_id = conn.execute(
            "INSERT INTO payment_webhooks (provider, event_id, event_type, raw_payload,"
            " signature_verified, processing_status, received_at)"
            " VALUES (?,?,?,?,?,?,?)",
            ("mock", "qa-wh-badbody-" + uuid.uuid4().hex[:8], "payment.paid",
             "{not json at all", 1, "RECEIVED", now),
        ).lastrowid
        conn.commit()
    finally:
        conn.close()

    r = client.post("/api/v1/admin/payments/webhooks/%d/reprocess" % bad_provider_id, headers=super_headers)
    check("알 수 없는 provider 재처리는 400", r.status_code, 400)
    # 재처리 가능 상태는 RECEIVED/IGNORED뿐이다(payment_logs.py:REPROCESSABLE_STATUSES).
    # 처음에 PENDING으로 행을 만들어 "재처리를 지원하지 않는 상태"에 먼저 걸렸다 ― 제품이
    # 아니라 픽스처의 상태값이 틀렸다.
    check_true("사유에 provider를 알려준다", "provider" in r.text, r.text[:160])

    r = client.post("/api/v1/admin/payments/webhooks/%d/reprocess" % bad_payload_id, headers=super_headers)
    check("저장된 payload 해석 불가 재처리는 400", r.status_code, 400)
    check_true("사유가 payload 문제임을 알린다", "payload" in r.text, r.text[:160])

    if saved_secret is None:
        os.environ.pop("PAYMENT_WEBHOOK_SECRET", None)
    else:
        os.environ["PAYMENT_WEBHOOK_SECRET"] = saved_secret


# ---------------------------------------------------------------------------
# 37. 결제 생성이 중간에 실패하면 결제 행도 남지 않는다 (2026-08-13 Sprint 85 신설)
#
# `api/v1/payments.py` 420-422행(`except Exception: rollback; raise`)이 미커버였다.
# 이 트랜잭션은 **결제 기록 -> 구독 생성 -> 등기부 신청 연결**을 한 묶음으로 처리한다.
# 중간에서 실패했는데 앞 단계가 남으면 **돈은 받았는데 이용권이 없는** 상태가 된다 —
# 사용자에게 가장 나쁜 형태의 절반 반영이다.
#
# 구독 INSERT만 실패시켜 그 격리를 확인한다. 실패 자체가 목적이 아니라 **결제 행이
# 남지 않는 것**이 목적이다.
# ---------------------------------------------------------------------------
def test_payment_creation_rolls_back_completely():
    import api.v1.payments as pay_mod

    print("\n--- 37. 결제 생성 실패의 완전 롤백 (Sprint 85) ---")
    user = TEST_USER + "-create-rollback"
    real_get_connection = pay_mod.get_connection

    class _FailSubscriptionInsert:
        def __init__(self, conn):
            object.__setattr__(self, "_conn", conn)
            object.__setattr__(self, "rolled_back", False)

        def execute(self, sql, *a, **kw):
            if sql.lstrip().upper().startswith("INSERT INTO SUBSCRIPTIONS"):
                raise sqlite3.OperationalError("disk I/O error (qa-injected)")
            return self._conn.execute(sql, *a, **kw)

        def rollback(self):
            object.__setattr__(self, "rolled_back", True)
            return self._conn.rollback()

        def __getattr__(self, name):
            return getattr(self._conn, name)

        def __setattr__(self, name, value):
            setattr(self._conn, name, value)

    box = {}

    def patched(*a, **kw):
        box["conn"] = _FailSubscriptionInsert(real_get_connection(*a, **kw))
        return box["conn"]

    pay_mod.get_connection = patched
    try:
        raised = None
        status = None
        body = ""
        try:
            r = client.post("/api/v1/payments",
                            json={"payment_type": "SUBSCRIPTION", "plan": "BASIC",
                                  "amount": resolve_plan_price("BASIC", BILLING_MONTHLY),
                                  "billing_cycle": BILLING_MONTHLY},
                            headers=auth_headers(user))
            status, body = r.status_code, r.text
        except Exception as exc:  # noqa: BLE001 - TestClient는 서버 예외를 그대로 올린다
            raised = exc
    finally:
        pay_mod.get_connection = real_get_connection

    check_true("실패가 성공으로 보이지 않는다", status != 200, (status, body[:120]))
    check_true("오류가 드러난다(예외 전파 또는 5xx)",
               raised is not None or (status is not None and status >= 500), (raised, status))
    # 명시적 롤백까지 확인하는 이유: 커밋 없이 close()하면 sqlite가 암묵적으로 되돌리므로
    # **데이터는 두 겹으로 안전하다**(실제로 rollback을 지운 변이에서도 결제 행은 남지 않았다).
    # 그러나 커넥션을 재사용하는 구조로 바뀌는 순간 암묵적 롤백은 사라진다 — 명시적 롤백이
    # 그 변화에 견디는 쪽이므로, 그것도 함께 못 박는다.
    check_true("실패 시 롤백한다", box.get("conn") is not None and box["conn"].rolled_back,
               "rollback이 호출되지 않았다")

    conn = get_connection()
    try:
        payments_left = conn.execute(
            "SELECT COUNT(*) FROM payments WHERE user_id=?", (user,)).fetchone()[0]
        subs_left = conn.execute(
            "SELECT COUNT(*) FROM subscriptions WHERE user_id=?", (user,)).fetchone()[0]
        logs_left = conn.execute(
            "SELECT COUNT(*) FROM payment_logs WHERE user_id=?", (user,)).fetchone()[0]
    finally:
        conn.close()
    # 핵심: 결제 행이 남으면 "돈은 받았는데 구독이 없는" 상태다.
    check("실패한 결제 행이 남지 않는다", payments_left, 0)
    check("구독도 만들어지지 않는다", subs_left, 0)
    check("원장에도 성공 기록이 남지 않는다", logs_left, 0)

    # 대조군: 주입을 풀면 같은 요청이 결제와 구독을 함께 만든다(위 실패가 주입 때문임을 보인다).
    r = client.post("/api/v1/payments",
                    json={"payment_type": "SUBSCRIPTION", "plan": "BASIC",
                          "amount": resolve_plan_price("BASIC", BILLING_MONTHLY),
                          "billing_cycle": BILLING_MONTHLY},
                    headers=auth_headers(user))
    check("대조군: 정상 경로는 200", r.status_code, 200)
    conn = get_connection()
    try:
        pair = (conn.execute("SELECT COUNT(*) FROM payments WHERE user_id=?", (user,)).fetchone()[0],
                conn.execute("SELECT COUNT(*) FROM subscriptions WHERE user_id=?", (user,)).fetchone()[0])
    finally:
        conn.close()
    check("대조군: 결제와 구독이 함께 생긴다", pair, (1, 1))


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
        #
        # ★ subscriptions가 payments **앞**에 있어야 한다 (2026-08-13 Sprint 96).
        #   `subscriptions.payment_id`가 생기면서 구독이 결제의 자식이 됐다(BUGS #94).
        #   순서를 되돌리면 이 정리가 FOREIGN KEY constraint failed로 죽는다 ―
        #   실제로 그렇게 죽는 것을 보고 고친 순서다.
        for table in ("registry_credit_logs", "registry_requests", "registry_usage",
                      "payment_logs", "subscriptions", "payments", "favorites",
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


# ---------------------------------------------------------------------------
# 무료 등기부 크레딧: 부분 실패 시 차감이 되돌아오는가 (2026-08-14 신설)
#
# `create_registry_request()`의 무료 경로는 **한 트랜잭션에서 세 번 쓴다.**
#
#     1) registry_usage        INSERT   <- 무료 1회를 "썼다"고 기록 (한도 계산의 근거)
#     2) registry_credit_logs  INSERT   <- 변동 추적 원장
#     3) registry_requests     INSERT   <- 사용자가 보는 신청
#
# 3번이 실패했는데 1번이 남으면 **사용자는 무료 횟수를 잃고 신청은 없다.** 화면에는
# "남은 횟수 9회"라고만 줄어들 뿐, 왜 줄었는지 볼 방법이 없다 — 가장 알아채기 어려운
# 손실이다(돈으로 환산되는 자원이다).
#
# 코드는 `except Exception: conn.rollback(); raise`로 되돌리게 돼 있다. 그런데 그 경로가
# **한 번도 실행된 적이 없었다** — 정적으로만 확인돼 있었다. 여기서 실제로 태운다.
#
# `test_payment_creation_rolls_back_completely()`(결제)와 같은 방식이고, 등기부는 그
# 검사가 없었다.
# ---------------------------------------------------------------------------
def test_registry_free_credit_rolls_back_on_partial_failure():
    print("\n--- 41. 무료 등기부 크레딧 부분 실패 롤백 (2026-08-14) ---")
    import api.v1.registry as reg_mod

    user = "qa-reg-rollback-" + uuid.uuid4().hex[:8]
    h = auth_headers(user)
    item_id = pick_item_ids(1)[0]

    # 무료 경로를 타려면 구독이 있어야 한다(무료 한도가 플랜에서 나온다).
    sub = client.post("/api/v1/payments",
                      json={"payment_type": "SUBSCRIPTION", "plan": "PRO",
                            "amount": resolve_plan_price("PRO", BILLING_MONTHLY),
                            "billing_cycle": BILLING_MONTHLY}, headers=h)
    check("전제: 구독 생성 성공", sub.json().get("success"), True)

    def free_remaining():
        r = client.get("/api/v1/registry-requests", headers=h)
        return r.json()

    def counts():
        c = get_connection()
        try:
            return (
                c.execute("SELECT COUNT(*) FROM registry_usage WHERE user_id=?",
                          (user,)).fetchone()[0],
                c.execute("SELECT COUNT(*) FROM registry_credit_logs WHERE user_id=?",
                          (user,)).fetchone()[0],
                c.execute("SELECT COUNT(*) FROM registry_requests WHERE user_id=?",
                          (user,)).fetchone()[0],
            )
        finally:
            c.close()

    before = counts()
    check("전제: 시작 시 아무 흔적이 없다", before, (0, 0, 0))

    real_get_connection = reg_mod.get_connection

    class _FailLastInsert:
        """`registry_requests` INSERT만 실패시킨다 — 앞의 두 쓰기는 이미 끝난 상태다."""

        def __init__(self, conn):
            self._conn = conn
            self.rolled_back = False

        def execute(self, sql, *a, **kw):
            if "INSERT INTO REGISTRY_REQUESTS" in " ".join(sql.split()).upper():
                raise sqlite3.OperationalError("disk I/O error (qa-injected)")
            return self._conn.execute(sql, *a, **kw)

        def rollback(self):
            self.rolled_back = True
            return self._conn.rollback()

        def __getattr__(self, name):
            return getattr(self._conn, name)

    box = {}

    def patched(*a, **kw):
        box["conn"] = _FailLastInsert(real_get_connection(*a, **kw))
        return box["conn"]

    reg_mod.get_connection = patched
    try:
        raised = None
        status, body = None, ""
        try:
            r = client.post("/api/v1/registry-requests", json={"item_id": item_id}, headers=h)
            status, body = r.status_code, r.text
        except Exception as exc:  # TestClient는 서버 예외를 그대로 올린다
            raised = exc
    finally:
        reg_mod.get_connection = real_get_connection

    check_true("성공(200 + success)으로 응답하지 않는다",
               status != 200 or '"success": true' not in body, (status, body[:120]))
    check_true("오류가 드러난다(예외 전파 또는 5xx)",
               raised is not None or (status is not None and status >= 500), (raised, status))
    check_true("실패 시 롤백한다", box.get("conn") is not None and box["conn"].rolled_back,
               "rollback이 호출되지 않았다")

    # ★ 핵심: 응답이 아니라 **DB**로 확인한다. 세 테이블 전부 시작 상태여야 한다.
    after = counts()
    check("registry_usage에 차감 흔적이 남지 않는다", after[0], 0)
    check("registry_credit_logs에 흔적이 남지 않는다", after[1], 0)
    check("registry_requests도 만들어지지 않는다", after[2], 0)
    check("세 테이블 모두 시작 상태로 돌아온다", after, before)

    # 그리고 사용자가 실제로 무료 횟수를 잃지 않았는지 — 다시 신청하면 정상 성공해야 한다.
    ok = client.post("/api/v1/registry-requests", json={"item_id": item_id}, headers=h)
    ok_body = ok.json()
    check("롤백 후 정상 신청이 성공한다", ok_body.get("success"), True)
    check_true("무료 횟수를 잃지 않았다(첫 신청이 여전히 무료)",
               ok_body.get("data", {}).get("is_free") is True, ok_body.get("data"))

    # 정리 — 이 테스트가 만든 행만 지운다(자식 -> 부모 순서).
    conn = get_connection()
    try:
        conn.execute("DELETE FROM registry_credit_logs WHERE user_id=?", (user,))
        conn.execute("DELETE FROM registry_requests WHERE user_id=?", (user,))
        conn.execute("DELETE FROM registry_usage WHERE user_id=?", (user,))
        conn.execute("DELETE FROM payment_logs WHERE user_id=?", (user,))
        conn.execute("DELETE FROM subscriptions WHERE user_id=?", (user,))
        conn.execute("DELETE FROM payments WHERE user_id=?", (user,))
        conn.commit()
    finally:
        conn.close()


def run():
    try:
        test_health_and_stats()
        test_search()
        test_address_detail_intents()
        test_property_type_aliases()
        test_detail_and_documents()
        test_authentication()
        test_favorites()
        test_recent_items()
        test_favorites_and_recent_items_survive_orphaned_auction_item()
        test_search_presets()
        test_payment_and_subscription()
        test_registry()
        test_registry_overage_flow()
        test_admin()
        test_payment_providers()
        test_deterministic_ordering()
        test_search_ordering_is_deterministic()
        test_subscription_plan_tiebreak()
        test_plans_api()
        test_api_surface()
        test_response_envelope()
        test_cors_configuration()
        test_backend_security_headers()
        test_admin_roles()
        test_registry_credits()
        test_payment_logs()
        test_auction_identity_keys()
        test_foreign_key_enforcement()
        test_payment_state_machine()
        test_subscription_lifecycle()
        test_admin_list_filters()
        test_audit_and_credit_logs()
        test_admin_rest_structure()
        test_soft_delete_columns()
        test_refund()
        test_payment_webhook()
        test_my_subscriptions()
        test_webhook_ops()
        test_authz_coverage()
        test_document_serving_guards()
        test_favorite_insert_failure_is_not_masked()
        test_payment_failure_branches()
        test_payment_creation_rolls_back_completely()
        test_registry_free_credit_rolls_back_on_partial_failure()
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
