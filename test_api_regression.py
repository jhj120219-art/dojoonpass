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
TEST_SUPER_ADMIN_KEY = "qa-regression-super-admin-key"
os.environ["ADMIN_API_KEY"] = TEST_ADMIN_KEY
os.environ["SUPER_ADMIN_API_KEY"] = TEST_SUPER_ADMIN_KEY

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
    other = client.get("/api/v1/favorites", headers=auth_headers("qa-reg-other-" + uuid.uuid4().hex[:6]))
    check("other user isolated", other.json()["data"], [])

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


# ---------------------------------------------------------------------------
# 21. 결제 로그 / Webhook 구조 (CTO 승인 5번) — 실제 PG API는 호출하지 않는다
# ---------------------------------------------------------------------------
def test_payment_logs():
    print("\n--- 21. payment logs / webhooks ---")
    from api.v1.payment_logs import (
        mask_sensitive, record_webhook, mark_webhook_processed,
        WEBHOOK_PROCESSED, REDACTED,
    )

    h = auth_headers()
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


# ---------------------------------------------------------------------------
# cleanup: 이 테스트가 만든 행만 정리한다(실제 사용자 데이터는 건드리지 않음)
# ---------------------------------------------------------------------------
def cleanup():
    print("\n--- cleanup (test user rows only) ---")
    conn = get_connection()
    try:
        like = "qa-reg-%"
        total = 0
        # FK가 런타임에 강제되므로 자식 -> 부모 순서로 지운다.
        for table in ("registry_credit_logs", "registry_requests", "registry_usage",
                      "payment_logs", "payments", "subscriptions", "favorites",
                      "recent_items", "search_presets", "registry_credits"):
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
