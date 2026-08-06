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
- ADMIN_API_KEY는 이 프로세스 환경에만 주입한다(.env 파일은 수정하지 않는다).
- 출력은 ASCII만 사용한다(Windows cp949 콘솔에서 UnicodeEncodeError 방지).
"""
import sys
import os
import uuid
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Admin 인증 테스트를 위해 프로세스 환경에만 키를 주입한다(.env 무수정).
# api/v1/admin.py는 요청 시점에 os.getenv를 읽으므로 import 전에 설정해야 한다.
TEST_ADMIN_KEY = "qa-regression-admin-key"
os.environ["ADMIN_API_KEY"] = TEST_ADMIN_KEY

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


def check(name, actual, expected):
    ok = actual == expected
    print("[%s] %s: %r (expected %r)" % ("PASS" if ok else "FAIL", name, actual, expected))
    if not ok:
        failures.append(name)


def check_true(name, cond, detail=""):
    ok = bool(cond)
    print("[%s] %s%s" % ("PASS" if ok else "FAIL", name, ("" if ok else " -> " + str(detail))))
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

    # 정렬 화이트리스트: 허용값은 200, 미허용값은 400으로 거부
    check("sort_by allowed", client.get("/api/v1/search?sort_by=auction_date").status_code, 200)
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
    check_true("document known type",
               client.get("/api/v1/item/%d/documents/SPEC" % item_id).status_code in (200, 404))


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
    other = client.get("/api/v1/favorites", headers=auth_headers("qa-reg-other-" + uuid.uuid4().hex[:6]))
    check("other user isolated", other.json()["data"], [])

    check("nonexistent item -> 404",
          client.post("/api/v1/favorites", json={"item_id": 99999999}, headers=h).status_code, 404)

    r = client.delete("/api/v1/favorites/%d" % item_id, headers=h)
    check("delete favorite", r.json()["success"], True)
    r = client.delete("/api/v1/favorites/%d" % item_id, headers=h)
    check("delete again -> fail", r.json()["success"], False)


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
    other = client.delete("/api/v1/search-presets/%d" % preset_id,
                          headers=auth_headers("qa-reg-other-" + uuid.uuid4().hex[:6]))
    check("other user cannot delete", other.json()["success"], False)

    check("delete own preset", client.delete("/api/v1/search-presets/%d" % preset_id, headers=h).json()["success"], True)


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

    # 정상 구독(BASIC 월) — 확정가 12,900원
    r = client.post("/api/v1/payments",
                    json={"payment_type": "SUBSCRIPTION", "plan": "BASIC",
                          "amount": resolve_plan_price("BASIC", BILLING_MONTHLY),
                          "billing_cycle": BILLING_MONTHLY}, headers=h)
    body = r.json()
    check("subscription payment success", body["success"], True)
    check("payment status SUCCESS", body["data"]["payment"]["status"], "SUCCESS")
    check("subscription created", body["data"]["subscription"]["plan"], "BASIC")
    check("subscription price", body["data"]["subscription"]["price"], 12900)
    check("pg_provider null (mock)", body["data"]["payment"]["pg_provider"], None)

    # 구독 기간이 결제주기(월=30일)를 따르는지
    sub = body["data"]["subscription"]
    days = (datetime.fromisoformat(sub["expires_at"]) - datetime.fromisoformat(sub["started_at"])).days
    check("monthly period ~30d", days, 30)

    # 연 결제(PRO) — 할인가 198,000원이 적용되어야 한다
    r = client.post("/api/v1/payments",
                    json={"payment_type": "SUBSCRIPTION", "plan": "PRO",
                          "amount": resolve_plan_price("PRO", BILLING_YEARLY),
                          "billing_cycle": BILLING_YEARLY}, headers=h)
    check("yearly PRO success", r.json()["success"], True)
    check("yearly discounted price", r.json()["data"]["subscription"]["price"], 198000)
    sub = r.json()["data"]["subscription"]
    days = (datetime.fromisoformat(sub["expires_at"]) - datetime.fromisoformat(sub["started_at"])).days
    check("yearly period ~365d", days, 365)

    # 정상가로 결제 시도하면 거부(할인가만 허용)
    r = client.post("/api/v1/payments",
                    json={"payment_type": "SUBSCRIPTION", "plan": "PRO",
                          "amount": 274800, "billing_cycle": BILLING_YEARLY}, headers=h)
    check("list price rejected when discounted", r.json()["success"], False)

    # 결제 내역 조회 + 소유권 격리
    r = client.get("/api/v1/payments", headers=h)
    check_true("payment history", len(r.json()["data"]) >= 2)
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

    # 미완료 상태 다운로드는 거짓 성공 없이 실패 메시지를 반환
    r = client.get("/api/v1/registry-requests/%d/download" % req_id, headers=h)
    check("incomplete download not a file", r.json()["success"], False)

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

    # 초과분 결제 -> 해당 신청이 PENDING으로 자동 전환
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
# cleanup: 이 테스트가 만든 행만 정리한다(실제 사용자 데이터는 건드리지 않음)
# ---------------------------------------------------------------------------
def cleanup():
    print("\n--- cleanup (test user rows only) ---")
    conn = get_connection()
    try:
        like = "qa-reg-%"
        total = 0
        for table in ("registry_requests", "registry_usage", "payments",
                      "subscriptions", "favorites", "recent_items", "search_presets"):
            cur = conn.execute("DELETE FROM %s WHERE user_id LIKE ?" % table, (like,))
            total += cur.rowcount
        conn.commit()
        print("removed %d test rows" % total)
        left = conn.execute("SELECT COUNT(*) FROM registry_requests WHERE user_id LIKE ?", (like,)).fetchone()[0]
        check("no test rows left", left, 0)
    finally:
        conn.close()


def run():
    try:
        test_health_and_stats()
        test_search()
        test_detail_and_documents()
        test_authentication()
        test_favorites()
        test_recent_items()
        test_search_presets()
        test_payment_and_subscription()
        test_registry()
        test_registry_overage_flow()
        test_admin()
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
