"""Beta 사용자 여정 Release Gate (2026-08-12 Sprint 68 신설).

기존 회귀는 **도메인별**로는 촘촘하지만(검색, 상세, 즐겨찾기, 등기부 …), 실제 사용자가
겪는 **하나의 연속된 흐름**으로 묶여 검증된 적이 없었다. 각 도메인이 통과해도 그 사이를
잇는 지점(로그인 redirect 복귀, 상세 진입이 최근조회에 남는지, 즐겨찾기가 검색 결과에
반영되는지)이 깨지면 사용자는 서비스를 쓸 수 없다.

이 파일은 그 이음매를 Release Gate로 고정한다.

    /  ->  검색  ->  정렬  ->  페이지 이동  ->  물건 선택
       ->  로그인 게이트 + 복귀 URL 보존  ->  상세  ->  문서 조회
       ->  등기부 신청  ->  관심물건  ->  최근조회  ->  검색조건 저장

각 단계에서 **HTTP status만 보지 않는다** — 응답 본문과 DB 상태를 함께 확인한다.

프런트 게이트(redirect) 단계는 dev 서버가 필요하다. 서버가 없으면 그 단계를 **명시적으로
SKIPPED로 보고**하고 나머지를 계속한다(조용히 통과시키지 않는다 —
`docs/TEST_PLAN.md`에 기록된 "cancelled를 초록으로 오인하는" 함정을 반복하지 않기 위해서다).

    python test_beta_journey.py
"""
import os
import sys
import uuid
import secrets
import urllib.error
import urllib.request
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ.setdefault("ADMIN_API_KEY", "qa-journey-admin-key")
os.environ.setdefault("SUPER_ADMIN_API_KEY", "qa-journey-super-key")
if not os.getenv("SUPABASE_JWT_SECRET"):
    os.environ["SUPABASE_JWT_SECRET"] = "qa-journey-" + secrets.token_hex(16)

from fastapi.testclient import TestClient
from jose import jwt

import api_server
from api.auth import SUPABASE_JWT_SECRET
from api.constants import ErrorCode
from storage.database import get_connection

client = TestClient(api_server.app)
USER = "qa-journey-" + uuid.uuid4().hex[:10]
FRONTEND = os.getenv("BASE_URL", "http://localhost:3000").rstrip("/")

failures = []
skipped = []


def check(name, actual, expected):
    ok = actual == expected
    print("[%s] %s: %r (expected %r)" % ("PASS" if ok else "FAIL", name, actual, expected))
    if not ok:
        failures.append(name)


def check_true(name, cond, detail=""):
    print("[%s] %s%s" % ("PASS" if cond else "FAIL", name, ("" if cond else " -- " + str(detail))))
    if not cond:
        failures.append(name)


def headers():
    token = jwt.encode({"sub": USER, "exp": datetime.now() + timedelta(hours=1)},
                       SUPABASE_JWT_SECRET, algorithm="HS256")
    return {"Authorization": "Bearer " + token}


def db_one(sql, params=()):
    conn = get_connection()
    try:
        row = conn.execute(sql, params).fetchone()
        return row[0] if row else None
    finally:
        conn.close()


def frontend_get(path):
    """dev 서버 응답. 서버가 없으면 None (호출부가 SKIPPED 처리)."""
    req = urllib.request.Request(FRONTEND + path, method="GET")
    try:
        opener = urllib.request.build_opener(NoRedirect)
        return opener.open(req, timeout=10)
    except urllib.error.HTTPError as e:
        return e
    except Exception:
        return None


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, hdrs, newurl):
        return None


def pick_target():
    """문서 3종이 READY이고 기일이 남은 물건 — 여정 전 단계를 실제로 밟을 수 있어야 한다."""
    conn = get_connection()
    try:
        row = conn.execute(
            """SELECT ai.id, ai.case_no, ai.court_name,
                      SUM(CASE WHEN ds.status='READY' THEN 1 ELSE 0 END) AS rdy
               FROM auction_item ai JOIN document_status ds ON ds.item_id = ai.id
               GROUP BY ai.id HAVING rdy = 3
               ORDER BY ai.auction_date DESC LIMIT 1"""
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


# ---------------------------------------------------------------------------
def step_1_search_as_anonymous():
    print("\n--- 1. 비로그인 검색 (첫 화면) ---")
    r = client.get("/api/v1/search?size=10&include_closed=true")
    check("검색 200", r.status_code, 200)
    body = r.json()
    check_true("결과가 존재한다", body["total"] > 0, body.get("total"))
    check_true("items가 리스트", isinstance(body["items"], list))
    check("응답 최상위 계약", sorted(body.keys()),
          ["items", "page", "size", "total", "total_pages"])
    # 비로그인은 개인화가 붙지 않아야 한다
    check("비로그인은 전부 is_favorited=false",
          sorted({i["is_favorited"] for i in body["items"]}), [False])
    return body


def step_2_sort_changes_order():
    print("\n--- 2. 정렬이 실제 결과 순서를 바꾼다 ---")
    q = "/api/v1/search?size=10&include_closed=true&sort_by=appraisal_price&sort_order=%s"
    asc = [i["id"] for i in client.get(q % "asc").json()["items"]]
    desc = [i["id"] for i in client.get(q % "desc").json()["items"]]
    check_true("asc/desc 결과가 다르다", asc != desc, (asc[:3], desc[:3]))
    prices = [i["appraisal_price"] for i in client.get(q % "asc").json()["items"]
              if i["appraisal_price"] is not None]
    check_true("asc는 실제로 오름차순", prices == sorted(prices), prices[:5])


def step_3_pagination():
    print("\n--- 3. 페이지 이동 ---")
    p1 = client.get("/api/v1/search?size=5&include_closed=true&page=1").json()
    p2 = client.get("/api/v1/search?size=5&include_closed=true&page=2").json()
    ids1 = [i["id"] for i in p1["items"]]
    ids2 = [i["id"] for i in p2["items"]]
    check("1페이지 5건", len(ids1), 5)
    check("2페이지 5건", len(ids2), 5)
    check("두 페이지가 겹치지 않는다", len(set(ids1) & set(ids2)), 0)
    check("total이 동일하다", p1["total"], p2["total"])


def step_4_login_gate_preserves_return_url(item_id):
    """상세는 로그인 필수 — 복귀 URL(쿼리 포함)이 보존되어야 한다."""
    print("\n--- 4. 로그인 게이트 + 복귀 URL 보존 (프런트) ---")
    path = "/properties/%d?ids=%d&i=0" % (item_id, item_id)
    res = frontend_get(path)
    if res is None:
        print("[SKIPPED] dev 서버(%s) 미기동 ― 프런트 게이트 단계를 건너뛴다" % FRONTEND)
        skipped.append("프런트 로그인 게이트 (dev 서버 없음)")
        return
    code = getattr(res, "status", None) or res.getcode()
    check("비로그인 상세는 307로 막힌다", code, 307)
    loc = res.headers.get("Location", "")
    check_true("로그인으로 보낸다", "/login" in loc, loc)
    # 원래 가려던 경로 + 쿼리스트링이 전부 살아 있어야 목록 컨텍스트를 잃지 않는다
    check_true("복귀 URL에 상세 경로가 보존된다", ("%%2Fproperties%%2F%d" % item_id) in loc
               or ("/properties/%d" % item_id) in loc, loc)
    check_true("복귀 URL에 쿼리(ids/i)가 보존된다", "ids" in loc and "i%3D0" in loc or "i=0" in loc,
               loc)


def step_5_detail_records_recent(item_id):
    print("\n--- 5. 로그인 후 상세 조회 -> 최근조회 기록 ---")
    before = db_one("SELECT COUNT(*) FROM recent_items WHERE user_id=?", (USER,))
    check("조회 전 최근기록 0", before, 0)

    r = client.get("/api/v1/item/%d" % item_id, headers=headers())
    check("상세 200", r.status_code, 200)
    d = r.json()
    check("요청한 물건이 맞다", d["id"], item_id)
    for k in ("case_no", "court_name", "full_address", "appraisal_price", "documents", "tenants"):
        check_true("상세에 %s가 있다" % k, k in d, sorted(d.keys()))

    after = db_one("SELECT COUNT(*) FROM recent_items WHERE user_id=? AND item_id=?",
                   (USER, item_id))
    check("상세 조회가 최근조회에 기록된다(DB)", after, 1)

    listed = client.get("/api/v1/recent-items", headers=headers()).json()["data"]
    check("최근조회 목록에 나온다", [x["id"] for x in listed], [item_id])
    return d


def step_6_documents(item_id, detail):
    print("\n--- 6. 문서 조회 ---")
    ready = {x["doc_type"] for x in detail["documents"] if x["status"] == "READY"}
    check("문서 3종이 READY", sorted(ready), ["APPRAISAL", "SPEC", "STATUS"])
    for dt in ("SPEC", "STATUS", "APPRAISAL"):
        r = client.get("/api/v1/item/%d/documents/%s" % (item_id, dt))
        check("%s 문서 200" % dt, r.status_code, 200)
        check_true("%s 문서에 실제 내용이 있다" % dt, len(r.content) > 0, len(r.content))
    # 존재하지 않는 문서 종류는 400
    check("알 수 없는 문서 종류는 400",
          client.get("/api/v1/item/%d/documents/BOGUS" % item_id).status_code, 400)


def step_7_registry_requires_subscription(item_id):
    print("\n--- 7. 등기부 신청: 구독 없으면 막힌다 ---")
    r = client.post("/api/v1/registry-requests", json={"item_id": item_id}, headers=headers())
    body = r.json()
    check("구독 없이 신청하면 실패", body["success"], False)
    check("구독 필요 에러코드", body["error"], ErrorCode.REGISTRY_SUBSCRIPTION_REQUIRED.value)
    check("신청 행이 생기지 않는다",
          db_one("SELECT COUNT(*) FROM registry_requests WHERE user_id=?", (USER,)), 0)


def step_8_subscribe_then_registry(item_id):
    print("\n--- 8. 구독 -> 등기부 무료 신청 ---")
    from api.v1.payments import resolve_plan_price, BILLING_MONTHLY

    price = resolve_plan_price("BASIC", BILLING_MONTHLY)
    pay = client.post("/api/v1/payments",
                      json={"payment_type": "SUBSCRIPTION", "plan": "BASIC",
                            "amount": price, "billing_cycle": BILLING_MONTHLY},
                      headers=headers()).json()
    check("구독 결제 성공", pay["success"], True)
    check("구독이 DB에 생성된다",
          db_one("SELECT COUNT(*) FROM subscriptions WHERE user_id=? AND status='ACTIVE'",
                 (USER,)), 1)

    me = client.get("/api/v1/subscriptions/me", headers=headers()).json()["data"]
    check("사용자 화면에 구독 1건", len(me), 1)
    check("지금 이용 가능", me[0]["is_entitled"], True)

    r = client.post("/api/v1/registry-requests", json={"item_id": item_id}, headers=headers())
    body = r.json()
    check("구독 후 신청 성공", body["success"], True)
    check("무료 신청은 PENDING", body["data"]["status"], "PENDING")
    check("신청이 DB에 남는다",
          db_one("SELECT COUNT(*) FROM registry_requests WHERE user_id=?", (USER,)), 1)
    check("무료 사용이 원장에 기록된다",
          db_one("SELECT COUNT(*) FROM registry_usage WHERE user_id=? AND is_free=1", (USER,)), 1)

    # 같은 물건 재신청은 중복 생성하지 않는다(진행 중 신청 재사용)
    dup = client.post("/api/v1/registry-requests", json={"item_id": item_id},
                      headers=headers()).json()
    check("같은 물건 재신청은 기존 건 반환", dup["data"]["already_requested"], True)
    check("신청 행이 늘지 않는다",
          db_one("SELECT COUNT(*) FROM registry_requests WHERE user_id=?", (USER,)), 1)
    check("무료 횟수가 추가 소모되지 않는다",
          db_one("SELECT COUNT(*) FROM registry_usage WHERE user_id=?", (USER,)), 1)


def step_9_favorite_reflects_in_search(item_id, case_no):
    print("\n--- 9. 관심물건 -> 검색 결과에 반영 ---")
    r = client.post("/api/v1/favorites", json={"item_id": item_id}, headers=headers())
    check("관심물건 등록", r.json()["success"], True)
    check("DB에 기록",
          db_one("SELECT COUNT(*) FROM favorites WHERE user_id=? AND item_id=?",
                 (USER, item_id)), 1)

    url = "/api/v1/search?size=100&include_closed=true&case_no=" + case_no
    mine = [i for i in client.get(url, headers=headers()).json()["items"] if i["id"] == item_id]
    check("로그인 검색에서 하트가 켜진다", [i["is_favorited"] for i in mine], [True])
    anon = [i for i in client.get(url).json()["items"] if i["id"] == item_id]
    check("비로그인에게는 꺼져 있다", [i["is_favorited"] for i in anon], [False])

    listed = client.get("/api/v1/favorites", headers=headers()).json()["data"]
    check("관심물건 목록에 나온다", [x["id"] for x in listed], [item_id])


def step_10_save_search_preset():
    print("\n--- 10. 검색조건 저장 ---")
    conditions = {"sido": "서울특별시", "min_fail_count": "1"}
    r = client.post("/api/v1/search-presets",
                    json={"name": "여정 테스트 조건", "conditions": conditions}, headers=headers())
    check("검색조건 저장 성공", r.json()["success"], True)
    pid = r.json()["data"]["id"]
    listed = client.get("/api/v1/search-presets", headers=headers()).json()["data"]
    mine = [p for p in listed if p["id"] == pid]
    check("저장 목록에 나온다", len(mine), 1)
    check("조건이 그대로 복원된다", mine[0]["conditions"], conditions)
    check("DB에도 남는다",
          db_one("SELECT COUNT(*) FROM search_presets WHERE user_id=?", (USER,)), 1)


def step_11_auth_boundary(item_id):
    """여정 전체에서 인증이 필요한 곳은 비로그인으로 뚫리지 않아야 한다."""
    print("\n--- 11. 인증 경계 (여정에서 쓰는 엔드포인트) ---")
    for method, path in (("GET", "/api/v1/favorites"),
                         ("POST", "/api/v1/favorites"),
                         ("GET", "/api/v1/recent-items"),
                         ("GET", "/api/v1/search-presets"),
                         ("GET", "/api/v1/registry-requests"),
                         ("POST", "/api/v1/registry-requests"),
                         ("GET", "/api/v1/subscriptions/me"),
                         ("GET", "/api/v1/payments")):
        kw = {"json": {"item_id": item_id}} if method == "POST" else {}
        r = client.request(method, path, **kw)
        check_true("%s %s 는 비로그인 차단" % (method, path.replace("/api/v1", "")),
                   r.status_code in (401, 403), r.status_code)


def cleanup():
    print("\n--- cleanup (여정 사용자 행만) ---")
    conn = get_connection()
    try:
        # 감사/결제 로그는 user_id가 없으므로 부모 id를 먼저 확보한다(FK 자식 -> 부모 순서).
        pay_ids = [str(r[0]) for r in conn.execute(
            "SELECT id FROM payments WHERE user_id=?", (USER,))]
        total = 0
        # subscriptions가 payments **앞**이어야 한다 ― `subscriptions.payment_id`가
        # 생기면서 구독이 결제의 자식이 됐다 (2026-08-13 Sprint 96, BUGS #94).
        for t in ("registry_credit_logs", "registry_requests", "registry_usage",
                  "payment_logs", "subscriptions", "payments", "favorites",
                  "recent_items", "search_presets", "registry_credits"):
            total += conn.execute("DELETE FROM %s WHERE user_id=?" % t, (USER,)).rowcount
        if pay_ids:
            ph = ",".join("?" * len(pay_ids))
            total += conn.execute(
                "DELETE FROM audit_logs WHERE target_type='PAYMENT' AND target_id IN (%s)" % ph,
                pay_ids).rowcount
        conn.commit()
        print("removed %d rows" % total)
        left = sum(conn.execute("SELECT COUNT(*) FROM %s WHERE user_id=?" % t,
                                (USER,)).fetchone()[0]
                   for t in ("registry_requests", "payments", "subscriptions", "favorites",
                             "recent_items", "search_presets", "registry_usage"))
        check("여정 QA 데이터 잔여 0", left, 0)
    finally:
        conn.close()


def run():
    target = pick_target()
    if not target:
        print("[SKIPPED] 문서 3종이 READY인 물건이 없어 여정을 재현할 수 없다")
        return 0
    print("여정 대상: id=%s %s (%s)" % (target["id"], target["case_no"], target["court_name"]))
    item_id, case_no = target["id"], target["case_no"]

    try:
        step_1_search_as_anonymous()
        step_2_sort_changes_order()
        step_3_pagination()
        step_4_login_gate_preserves_return_url(item_id)
        detail = step_5_detail_records_recent(item_id)
        step_6_documents(item_id, detail)
        step_7_registry_requires_subscription(item_id)
        step_8_subscribe_then_registry(item_id)
        step_9_favorite_reflects_in_search(item_id, case_no)
        step_10_save_search_preset()
        step_11_auth_boundary(item_id)
    finally:
        cleanup()

    print("\n" + "=" * 60)
    if skipped:
        print("SKIPPED 단계 %d개 (조용히 통과시키지 않고 명시한다):" % len(skipped))
        for s in skipped:
            print("   - " + s)
    if failures:
        print("FAILED (%d): %s" % (len(failures), ", ".join(failures)))
        return 1
    print("BETA JOURNEY GATE PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(run())
