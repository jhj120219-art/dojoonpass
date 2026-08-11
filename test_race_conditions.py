"""
동시 요청(Race Condition) 회귀 테스트 — 실제 스레드로 검증한다.

배경: 등기부 무료한도 레이스(Sprint 9/10, docs/BUGS.md)와 초과결제 중복방지(Sprint 4,
docs/decision-log.md)는 전부 "5/10/20 스레드 동시 요청 테스트"로 실측 검증됐다고 문서에
기록돼 있지만, 그 테스트가 **자동화된 파일로 남아있지 않았다**(전체 test_*.py grep 결과
Thread/concurrent 사용 0건, 2026-08-09 확인) — 즉 그 방어가 아직도 정확히 동작하는지
재확인할 자동 회귀가 없었다. 이 파일이 그 공백을 메운다.

FastAPI TestClient(httpx 기반)를 여러 스레드에서 동시에 호출해 실제 DB 트랜잭션 경합을
재현한다. 테스트 전용 user_id(qa-race-<uuid>)만 사용하고 종료 시 그 행만 정리한다.

    python test_race_conditions.py
"""
import sys
import os
import uuid
import secrets
import threading
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ.setdefault("ADMIN_API_KEY", "qa-race-admin-key")
os.environ.setdefault("SUPER_ADMIN_API_KEY", "qa-race-super-admin-key")
if not os.getenv("SUPABASE_JWT_SECRET"):
    os.environ["SUPABASE_JWT_SECRET"] = "qa-race-" + secrets.token_hex(16)

from fastapi.testclient import TestClient
from jose import jwt

import api_server
from api.auth import SUPABASE_JWT_SECRET
from storage.database import get_connection

client = TestClient(api_server.app)
# 두 레이스 시나리오는 서로 다른 user_id를 쓴다 — 같은 사용자를 재사용하면 시나리오 1이
# 남긴 PAYMENT_REQUIRED 신청들이 시나리오 2의 "타깃 1건짜리 경쟁" 전제를 깨뜨린다
# (실제로 겪은 문제: 처음엔 같은 사용자를 썼다가 2건이 동시에 성공해 실패로 보였는데,
# 원인은 결제 레이스 방어 결함이 아니라 시나리오 1이 남긴 여분의 타깃이었다).
TEST_USER_LIMIT = "qa-race-limit-" + uuid.uuid4().hex[:10]
TEST_USER_PAYMENT = "qa-race-payment-" + uuid.uuid4().hex[:10]
TEST_USER_SUBSCRIPTION = "qa-race-sub-" + uuid.uuid4().hex[:10]
TEST_USER_ADMIN_TARGET = "qa-race-admintarget-" + uuid.uuid4().hex[:10]
failures = []


def check(name, actual, expected):
    ok = actual == expected
    print("[%s] %s: %r (expected %r)" % ("PASS" if ok else "FAIL", name, actual, expected))
    if not ok:
        failures.append(name)


def check_true(name, cond):
    check(name, bool(cond), True)


def auth_headers(user_id):
    token = jwt.encode({"sub": user_id}, SUPABASE_JWT_SECRET, algorithm="HS256")
    return {"Authorization": "Bearer " + token}


def pick_item_ids(n):
    conn = get_connection()
    try:
        rows = conn.execute("SELECT id FROM auction_item LIMIT ?", (n,)).fetchall()
        return [r["id"] for r in rows]
    finally:
        conn.close()


def test_registry_free_limit_race():
    """BASIC 플랜(월 5회 무료)에 대해 서로 다른 물건 24개를 정확히 동시에 신청한다.
    BEGIN IMMEDIATE로 직렬화되어 정확히 5건만 무료(PENDING)여야 하고, 나머지는
    PAYMENT_REQUIRED여야 한다 — 5보다 많거나 적게 무료 처리되면 레이스가 재발한 것이다.

    2026-08-11 Sprint 56 강화 — 이 테스트는 **레이스를 재현하지 못하는 레이스 테스트**였다.
    스레드 10개를 순서대로 start()만 했더니 생성/시작 오버헤드로 요청이 어긋나 겹치지
    않았고, `BEGIN IMMEDIATE`를 제거하는 변이가 그대로 통과했다.
    (1) Barrier로 모든 스레드의 진입 시점을 맞추고 (2) 경합 폭을 24로 올렸다.
    변이를 넣고 반복 실행해 검출률이 올라가는 것까지 확인했다 —
    레이스 테스트는 확률적이므로 "한 번 통과했다"로 판단하지 않는다.
    """
    print("\n--- 1. registry free-limit race (24 threads, BASIC = 5/month) ---")
    conn = get_connection()
    try:
        now = datetime.now().isoformat()
        expires = (datetime.now() + timedelta(days=30)).isoformat()
        conn.execute(
            "INSERT INTO subscriptions (user_id,plan,price,status,started_at,expires_at,created_at,updated_at)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (TEST_USER_LIMIT, "BASIC", 12900, "ACTIVE", now, expires, now, now),
        )
        conn.commit()
    finally:
        conn.close()

    item_ids = pick_item_ids(24)
    check("have 24 distinct items to race with", len(item_ids), 24)

    results = [None] * len(item_ids)

    # 2026-08-11 Sprint 56: 예전에는 스레드를 만들고 순서대로 start()만 했다. 생성/시작
    # 오버헤드 때문에 실제로는 요청이 어긋나 겹치지 않았고, `BEGIN IMMEDIATE`를 제거하는
    # 변이가 **그대로 통과했다**(레이스를 재현하지 못하는 레이스 테스트).
    # Barrier로 모든 스레드가 같은 순간에 HTTP 호출에 진입하도록 맞춘다.
    start_barrier = threading.Barrier(len(item_ids))

    def worker(idx, item_id):
        start_barrier.wait()
        r = client.post("/api/v1/registry-requests", json={"item_id": item_id},
                        headers=auth_headers(TEST_USER_LIMIT))
        results[idx] = r.json()

    threads = [threading.Thread(target=worker, args=(i, iid)) for i, iid in enumerate(item_ids)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    statuses = [r["data"]["status"] for r in results if r.get("success")]
    free_count = sum(1 for s in statuses if s == "PENDING")
    paid_count = sum(1 for s in statuses if s == "PAYMENT_REQUIRED")
    check("exactly 5 free (PENDING)", free_count, 5)
    check("나머지는 전부 PAYMENT_REQUIRED", paid_count, len(item_ids) - 5)
    check("no request failed outright", len(statuses), len(item_ids))

    # DB 레벨에서도 이번 달 무료 사용 건수가 정확히 5여야 한다(응답과 실제 원장 일치).
    conn = get_connection()
    try:
        actual_free_usage = conn.execute(
            "SELECT COUNT(*) FROM registry_usage WHERE user_id=? AND is_free=1", (TEST_USER_LIMIT,)
        ).fetchone()[0]
        check("registry_usage free rows == 5 (not 6+ from the race)", actual_free_usage, 5)
    finally:
        conn.close()


def test_overage_payment_race():
    """같은 PAYMENT_REQUIRED 등기부 신청 1건에 대해 결제 요청 8건을 동시에 보낸다.
    payments.py의 조건부 UPDATE(WHERE payment_id IS NULL AND status='PAYMENT_REQUIRED')가
    정확히 1건만 성공시키고 나머지는 PAY_ALREADY_PROCESSED로 거부해야 한다 — 2건 이상
    성공하면 사용자가 같은 신청에 대해 중복 결제될 수 있다는 뜻이다.

    별도 user_id(TEST_USER_PAYMENT)를 쓴다 — 시나리오 1과 같은 사용자를 쓰면 그쪽이 남긴
    PAYMENT_REQUIRED 신청들이 "타깃 1건짜리 경쟁"이라는 전제를 깨뜨려 오탐이 난다(실측:
    같은 사용자로 처음 시도했을 때 2건이 성공했는데, 원인은 결제 레이스 방어 결함이 아니라
    시나리오 1이 남긴 여분의 미결제 타깃이었다).
    """
    print("\n--- 2. overage payment race (8 threads, single PAYMENT_REQUIRED target) ---")
    item_id = pick_item_ids(11)[-1]
    conn = get_connection()
    try:
        now = datetime.now().isoformat()
        conn.execute(
            "INSERT INTO registry_requests (user_id,item_id,status,requested_at)"
            " VALUES (?,?,?,?)",
            (TEST_USER_PAYMENT, item_id, "PAYMENT_REQUIRED", now),
        )
        conn.commit()
        pending_targets = conn.execute(
            "SELECT COUNT(*) FROM registry_requests WHERE user_id=? AND status='PAYMENT_REQUIRED'"
            " AND payment_id IS NULL",
            (TEST_USER_PAYMENT,),
        ).fetchone()[0]
        check("exactly 1 unclaimed target before the race", pending_targets, 1)
    finally:
        conn.close()

    from api.v1.registry import OVERAGE_FEE

    n = 8
    results = [None] * n

    def worker(idx):
        r = client.post(
            "/api/v1/payments",
            json={"payment_type": "OVERAGE_USAGE", "amount": OVERAGE_FEE},
            headers=auth_headers(TEST_USER_PAYMENT),
        )
        results[idx] = r.json()

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    succeeded = [r for r in results if r.get("success")]
    already_processed = [r for r in results if r.get("error") == "PAY_ALREADY_PROCESSED"]
    no_target = [r for r in results if r.get("error") == "PAY_NO_TARGET_REQUEST"]

    check("exactly 1 payment succeeded", len(succeeded), 1)
    check("remaining 7 rejected (already processed or no target left)",
          len(already_processed) + len(no_target), n - 1)

    conn = get_connection()
    try:
        linked = conn.execute(
            "SELECT COUNT(*) FROM registry_requests WHERE user_id=? AND status='PENDING'"
            " AND payment_id IS NOT NULL",
            (TEST_USER_PAYMENT,),
        ).fetchone()[0]
        check("exactly 1 registry_request linked to a payment", linked, 1)
        paid_payments = conn.execute(
            "SELECT COUNT(*) FROM payments WHERE user_id=? AND payment_type='OVERAGE_USAGE'",
            (TEST_USER_PAYMENT,),
        ).fetchone()[0]
        # payments 행 자체는 provider.confirm_payment까지 항상 SUCCESS로 기록되므로 n개 전부
        # 생성될 수 있다(결제 자체는 Mock이라 항상 승인) — 레이스 방어의 핵심은 "그중 등기부
        # 신청에 실제로 연결된 것이 1건뿐"이라는 사실이지, payments 행 개수가 아니다.
        check("at least one payment row recorded", paid_payments >= 1, True)
    finally:
        conn.close()


def test_subscription_race():
    """같은 사용자가 같은 구독(PRO 연)을 정확히 동시에 10번 요청한다.

    2026-08-09 Sprint 38에서 발견: create_payment()가 SUBSCRIPTION 요청 시 기존 유효
    구독 확인(get_entitled_subscription) 후 신규 생성까지를 잠금 없는 "SELECT -> 판단 ->
    INSERT"로 처리해, 커밋되지 않은 동시 요청 여러 개가 전부 "구독 없음"을 보고 통과할 수
    있었다(최초 수정은 순차 중복만 막고 동시 레이스는 막지 못함 — 실측 재현: 동시 10회
    요청 -> subscriptions/payments 10개씩 생성, 1건당 198,000원씩 총 1,980,000원 중복 청구).
    registry.py의 등기부 중복신청 방지와 동일하게 BEGIN IMMEDIATE로 확인+생성을 원자화해
    해결했다 — 정확히 1건만 새로 생성되고 나머지는 그 1건을 그대로 반환해야 한다.
    """
    print("\n--- 3. subscription race (10 threads, same plan+cycle) ---")
    from api.v1.payments import resolve_plan_price, BILLING_YEARLY

    amount = resolve_plan_price("PRO", BILLING_YEARLY)
    n = 10
    results = [None] * n

    def worker(idx):
        r = client.post(
            "/api/v1/payments",
            json={"payment_type": "SUBSCRIPTION", "plan": "PRO",
                  "billing_cycle": BILLING_YEARLY, "amount": amount},
            headers=auth_headers(TEST_USER_SUBSCRIPTION),
        )
        results[idx] = r.json()

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    check("all 10 concurrent requests report success", sum(1 for r in results if r.get("success")), n)
    already_subscribed = sum(1 for r in results if r.get("data", {}).get("already_subscribed"))
    check("exactly 9 flagged as already_subscribed (1 winner + 9 losers)", already_subscribed, n - 1)
    returned_ids = set(
        r["data"]["subscription"]["id"] for r in results if r.get("data", {}).get("subscription")
    )
    check("all responses point to the same single subscription id", len(returned_ids), 1)

    conn = get_connection()
    try:
        sub_count = conn.execute(
            "SELECT COUNT(*) FROM subscriptions WHERE user_id=?", (TEST_USER_SUBSCRIPTION,)
        ).fetchone()[0]
        check("exactly 1 subscriptions row created (not 10)", sub_count, 1)
        pay_count = conn.execute(
            "SELECT COUNT(*) FROM payments WHERE user_id=? AND payment_type='SUBSCRIPTION'",
            (TEST_USER_SUBSCRIPTION,),
        ).fetchone()[0]
        check("exactly 1 payments row created (not 10 -- no duplicate charge)", pay_count, 1)
    finally:
        conn.close()


def test_admin_registry_status_race():
    """PROCESSING 상태인 등기부 신청 1건에 서로 다른 목표 상태(COMPLETED/FAILED)로 두 관리자
    PATCH를 정확히 동시에 보낸다.

    2026-08-09 Sprint 39 TOCTOU 감사에서 발견: admin.py:update_registry_request_status()가
    "현재 상태 SELECT -> 전이 허용 여부 판단 -> UPDATE ... WHERE id=?"만 하고 UPDATE에
    현재 상태 재확인 조건이 없어, 두 요청이 동시에 도착하면 둘 다 "지금 PROCESSING"을 보고
    통과해 나중에 커밋되는 쪽이 앞선 결과(doc_url/reason 포함)를 조용히 덮어쓸 수 있었다.
    WHERE에 status=current를 추가해 정확히 1건만 성공하고 나머지는 409로 거부되도록 고쳤다 —
    이 테스트는 그 수정이 유지되는지 검증한다.
    """
    print("\n--- 4. admin registry status transition race (COMPLETED vs FAILED, same target) ---")
    conn = get_connection()
    try:
        item_id = conn.execute("SELECT id FROM auction_item LIMIT 1").fetchone()["id"]
        now = datetime.now().isoformat()
        req_id = conn.execute(
            "INSERT INTO registry_requests (user_id,item_id,status,requested_at) VALUES (?,?,?,?)",
            (TEST_USER_ADMIN_TARGET, item_id, "PROCESSING", now),
        ).lastrowid
        conn.commit()
    finally:
        conn.close()

    admin_headers = {"X-Admin-Key": os.environ["ADMIN_API_KEY"]}
    # 2026-08-11 Sprint 56: Barrier가 없으면 두 요청이 겹치지 않아 진 쪽이 **항상**
    # SELECT를 나중에 하고, 그때는 이미 상태가 바뀌어 ALLOWED_TRANSITIONS에서 400으로
    # 걸린다. 즉 이 테스트가 검증하려던 **조건부 UPDATE(TOCTOU 가드)에는 도달조차 못 했고**,
    # 그 가드를 무력화하는 변이가 그대로 통과했다. 시작 시점을 맞춰 실제로 겹치게 한다.
    # 스레드 수를 6으로 늘려 봤지만 검출률이 오히려 3/4 -> 1/5로 **나빠졌다**(2026-08-11 실측).
    # Barrier 해제가 계단식이라 첫 스레드가 커밋을 마친 뒤에야 나머지가 SELECT에 도달한다.
    # 이 창(SELECT -> UPDATE, 수 마이크로초)은 실제 스레드로 안정 재현이 불가능하다.
    # 그래서 여기서는 2개로 두고, 가드 자체는 아래 `test_toctou_guard_is_structural()`이
    # **결정적으로** 고정한다. 확률적 테스트와 구조적 테스트를 함께 둔다.
    BODIES = [
        {"status": "COMPLETED", "doc_url": "https://example.com/qa-race.pdf"},
        {"status": "FAILED", "reason": "qa-race-fail"},
    ]
    results = [None] * len(BODIES)
    start_barrier = threading.Barrier(len(BODIES))

    def worker(idx, body):
        start_barrier.wait()
        r = client.patch(f"/api/v1/admin/registry-requests/{req_id}", json=body, headers=admin_headers)
        results[idx] = (r.status_code, r.json())

    threads = [threading.Thread(target=worker, args=(i, b)) for i, b in enumerate(BODIES)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # 두 스레드가 실제로 SELECT/판단을 동시에 통과했다면 진 쪽은 UPDATE의 조건부 WHERE에
    # 걸려 409를 받는다. 스케줄링이 덜 겹쳐 진 쪽이 SELECT를 나중에 하면, 그때는 이미 상태가
    # 바뀐 뒤라 ALLOWED_TRANSITIONS 자체에서 걸려 400을 받는다 — 둘 다 "이중 전이를 막았다"는
    # 점에서 올바른 결과이므로, 정확히 어느 코드로 막혔는지가 아니라 "정확히 1건만 성공했는가"
    # 와 "실패한 쪽은 성공이 아니었는가"만 확인한다.
    statuses = [code for code, _ in results]
    check("exactly one request succeeded (200)", statuses.count(200), 1)
    check("the other request did not also succeed",
          statuses.count(200) == 1 and any(c != 200 for c in statuses), True)
    check("the rejected request used a valid conflict code (400 or 409)",
          all(c in (200, 400, 409) for c in statuses), True)

    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT status, doc_url, reason FROM registry_requests WHERE id=?", (req_id,)
        ).fetchone()
        # 이긴 쪽이 COMPLETED든 FAILED든 상관없다 — 핵심은 상태와 그 상태에 딸린 필드
        # (doc_url/reason)가 서로 뒤섞이지 않고 정확히 한쪽 결과로만 일관되게 남는 것이다.
        if row["status"] == "COMPLETED":
            check("winner is COMPLETED -> doc_url set", row["doc_url"], "https://example.com/qa-race.pdf")
            check("winner is COMPLETED -> reason not set from the loser", row["reason"], None)
        else:
            check("winner is FAILED -> status", row["status"], "FAILED")
            check("winner is FAILED -> reason set", row["reason"], "qa-race-fail")
            check("winner is FAILED -> doc_url not set from the loser", row["doc_url"], None)
    finally:
        conn.close()



def test_toctou_guard_is_structural():
    """조건부 UPDATE(TOCTOU 가드)가 **모든 전이 분기에** 남아 있는가 — 결정적 검사.

    위 시나리오 4는 실제 스레드로 경합을 재현하지만, 창이 너무 좁아 가드를 없애는 변이를
    항상 잡지는 못한다(2026-08-11 실측: 2스레드 3/4, 6스레드 1/5). 확률에 기대는 검사만
    두면 가드가 사라져도 통과하는 날이 생긴다. 그래서 소스 레벨에서 함께 못 박는다.

    검사 대상: `update_registry_request_status()`의 UPDATE 세 갈래(COMPLETED/FAILED/그 외)가
    전부 `WHERE id=? AND status=?` 형태이고, rowcount==0이면 409로 거부하는가.
    """
    import re
    print("\n--- 5. TOCTOU 가드 구조 검사 (결정적) ---")
    src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "api", "v1", "admin.py"),
               encoding="utf-8-sig").read()
    i = src.index("def update_registry_request_status")
    body = src[i:i + 4000]

    updates = re.findall(r'"(UPDATE registry_requests SET [^"]*)"', body)
    check("UPDATE 분기가 3개다", len(updates), 3)
    missing = [u for u in updates if "WHERE id=? AND status=?" not in u]
    check("모든 UPDATE가 현재 상태를 다시 확인한다", missing, [])

    check_true("rowcount==0이면 거부한다", "cursor.rowcount == 0" in body)
    check_true("거부 응답이 409다", "status_code=409" in body)
    check_true("거부 시 롤백한다", "conn.rollback()" in body)



def cleanup():
    print("\n--- cleanup (test user rows only) ---")
    conn = get_connection()
    try:
        total = 0
        # audit_logs는 user_id가 아니라 target_id(registry_requests.id)로 연결되므로
        # 먼저 그 id 목록을 구해서 지운다(FK 자식 -> 부모 순서).
        target_ids = [
            r["id"] for r in conn.execute(
                "SELECT id FROM registry_requests WHERE user_id=?", (TEST_USER_ADMIN_TARGET,)
            ).fetchall()
        ]
        if target_ids:
            placeholders = ",".join("?" * len(target_ids))
            cur = conn.execute(
                "DELETE FROM audit_logs WHERE target_type='REGISTRY_REQUEST' AND target_id IN (%s)" % placeholders,
                target_ids,
            )
            total += cur.rowcount

        # FK가 런타임에 강제되므로 자식 -> 부모 순서로 지운다(test_api_regression.py의
        # cleanup()과 동일한 순서 원칙 — registry_credit_logs/payment_logs가 각각
        # registry_usage/payments를 참조하므로 먼저 지워야 한다).
        for table in ("registry_credit_logs", "registry_requests", "registry_usage",
                      "payment_logs", "payments", "subscriptions"):
            for user in (TEST_USER_LIMIT, TEST_USER_PAYMENT, TEST_USER_SUBSCRIPTION, TEST_USER_ADMIN_TARGET):
                cur = conn.execute("DELETE FROM %s WHERE user_id=?" % table, (user,))
                total += cur.rowcount
        conn.commit()
        print("removed %d test rows" % total)
        left = sum(
            conn.execute(
                "SELECT COUNT(*) FROM registry_requests WHERE user_id=?", (user,)
            ).fetchone()[0]
            for user in (TEST_USER_LIMIT, TEST_USER_PAYMENT, TEST_USER_SUBSCRIPTION, TEST_USER_ADMIN_TARGET)
        )
        check("no test rows left", left, 0)
    finally:
        conn.close()


def run():
    try:
        test_registry_free_limit_race()
        test_overage_payment_race()
        test_subscription_race()
        test_admin_registry_status_race()
        test_toctou_guard_is_structural()
    finally:
        cleanup()

    print("\n" + "=" * 55)
    if failures:
        print("FAILED (%d): %s" % (len(failures), ", ".join(failures)))
        return 1
    print("ALL TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(run())
