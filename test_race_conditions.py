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
    # ★ 파일 복사가 아니라 **온라인 백업 스냅샷**이다 (2026-08-26).
    #   DocWorker(02:00~04:00)가 등록된 뒤로는 운영 DB 에 쓰는 프로세스가 실제로 있다.
    #   그 시간대에 shutil.copy2 로 사본을 뜨면 **찢어진 DB** 가 나와 검사가 제품과
    #   무관한 이유로 붉어진다(실측 재현: 워커와 스위트를 겹쳐 돌리자 2건 실패,
    #   단독으로는 둘 다 통과). 규칙은 storage/database.py 한 곳에 있다.
    _qa_dbmod.snapshot_live_db(_qa_scratch)
_qa_dbmod.DB_PATH = _qa_scratch

os.environ.setdefault("ADMIN_API_KEY", "qa-race-admin-key")
os.environ.setdefault("SUPER_ADMIN_API_KEY", "qa-race-super-admin-key")
if not os.getenv("SUPABASE_JWT_SECRET"):
    os.environ["SUPABASE_JWT_SECRET"] = "qa-race-" + secrets.token_hex(16)

from fastapi.testclient import TestClient
from jose import jwt

import api_server
from api.auth import SUPABASE_JWT_SECRET
from api.v1.payments import resolve_plan_price, BILLING_MONTHLY
from storage.database import get_connection
from api.constants import ErrorCode

client = TestClient(api_server.app)
# 두 레이스 시나리오는 서로 다른 user_id를 쓴다 — 같은 사용자를 재사용하면 시나리오 1이
# 남긴 PAYMENT_REQUIRED 신청들이 시나리오 2의 "타깃 1건짜리 경쟁" 전제를 깨뜨린다
# (실제로 겪은 문제: 처음엔 같은 사용자를 썼다가 2건이 동시에 성공해 실패로 보였는데,
# 원인은 결제 레이스 방어 결함이 아니라 시나리오 1이 남긴 여분의 타깃이었다).
TEST_USER_LIMIT = "qa-race-limit-" + uuid.uuid4().hex[:10]
TEST_USER_PAYMENT = "qa-race-payment-" + uuid.uuid4().hex[:10]
TEST_USER_SUBSCRIPTION = "qa-race-sub-" + uuid.uuid4().hex[:10]
TEST_USER_ADMIN_TARGET = "qa-race-admintarget-" + uuid.uuid4().hex[:10]
TEST_USER_REFUND = "qa-race-refund-" + uuid.uuid4().hex[:10]
TEST_USER_SUB_STATUS = "qa-race-substatus-" + uuid.uuid4().hex[:10]
TEST_USER_WEBHOOK_REPROCESS = "qa-race-whreprocess-" + uuid.uuid4().hex[:10]
TEST_USER_WEBHOOK_CAS = "qa-race-whcas-" + uuid.uuid4().hex[:10]
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
        # 2026-08-15 Sprint 129: 이전에는 payments 행이 provider.confirm_payment까지 항상
        # SUCCESS로 기록되어 n개 전부 생성될 수 있었다(BEGIN IMMEDIATE가 target_request UPDATE
        # 시점에만 걸려 있어, 레이스 패자도 provider 호출까지는 도달했다 — 지금은 MockProvider라
        # 부작용이 없지만 실제 PG라면 패자 쪽도 카드 승인까지 갈 수 있었다는 뜻). 락을
        # provider 호출보다 앞으로 당긴 뒤로는 패자가 target_request 재확인에서 즉시
        # PAY_NO_TARGET_REQUEST로 거부되어 provider까지 도달하지 않는다 — payments 행도
        # 정확히 1개만 생성돼야 한다.
        check("exactly 1 payment row recorded (provider never reached by losers)", paid_payments, 1)
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


def test_admin_refund_race():
    """같은 결제 1건에 부분 환불 요청 3개를 정확히 동시에 보낸다.

    `api/v1/payments.py:refund_payment()`는 `BEGIN IMMEDIATE`로 쓰기 락을 먼저 잡고
    (등기부 §1/구독 §3과 동일 패턴), 그 안에서 "이미 환불된 금액 조회 -> 환불 가능액
    계산 -> 조건부 UPDATE"를 수행한다. 락을 잡는 시점이 함수 진입 즉시라 다른 레이스
    시나리오(좁은 SELECT->UPDATE 창)보다 스레드로 안정 재현하기 쉽다 — 동시에 도착한
    요청들이 락 위에서 완전히 직렬화되므로 "먼저 커밋된 요청이 반영한 already_refunded를
    다음 요청이 반드시 보게" 된다.

    금액을 결제액의 절반보다 살짝 크게 잡아, 두 번째 요청까지는 성공하면 총 환불액이
    결제액을 넘는 상황을 만든다 — 방어가 없다면(각 스레드가 서로의 커밋을 보지 못하고
    "환불 가능액 100%"로 오판하면) 총 환불액이 결제액을 초과하는 **초과 환불**이 발생한다.
    """
    print("\n--- 5. admin refund race (3 threads, partial refunds > payment amount) ---")
    r = client.post(
        "/api/v1/payments",
        json={"payment_type": "SUBSCRIPTION", "plan": "BASIC",
              "amount": resolve_plan_price("BASIC", BILLING_MONTHLY), "billing_cycle": BILLING_MONTHLY},
        headers=auth_headers(TEST_USER_REFUND),
    )
    body = r.json()
    check_true("설정: 결제 생성 성공", body.get("success"))
    payment_id = body["data"]["payment"]["id"]
    amount = body["data"]["payment"]["amount"]
    partial = amount // 2 + 1000  # 2개만 성공해도 결제액을 넘는 크기

    n = 3
    super_admin_headers = {"X-Admin-Key": os.environ["SUPER_ADMIN_API_KEY"]}
    results = [None] * n
    start_barrier = threading.Barrier(n)

    def worker(idx):
        start_barrier.wait()
        r = client.post(
            f"/api/v1/admin/payments/{payment_id}/refund",
            json={"amount": partial, "reason": "qa-race-refund"},
            headers=super_admin_headers,
        )
        results[idx] = (r.status_code, r.json())

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    statuses = [code for code, _ in results]
    succeeded = [body for code, body in results if code == 200]
    check("최소 1건은 성공", len(succeeded) >= 1, True)
    check("모든 요청이 유효한 코드로만 응답(200 또는 400)",
          all(c in (200, 400) for c in statuses), True)
    # already_refunded=True로 200이 온 경우는 "초과 환불로 이미 막힌 뒤 재시도"가 아니라
    # "전액이 이미 환불된 결제에 대한 멱등 응답"이다 — partial < amount라 이번 시나리오에서는
    # 발생하지 않아야 한다(발생하면 로직이 예상과 다르게 동작했다는 신호).
    check("성공 응답 중 already_refunded는 없다(부분액이라 전액 도달 불가)",
          any(b.get("data", {}).get("already_refunded") for b in succeeded), False)

    conn = get_connection()
    try:
        row = conn.execute("SELECT amount FROM payments WHERE id=?", (payment_id,)).fetchone()
        total_refunded = conn.execute(
            "SELECT COALESCE(SUM(amount),0) FROM payment_logs"
            " WHERE payment_id=? AND event_type='CANCEL' AND status='SUCCESS'",
            (payment_id,),
        ).fetchone()[0]
        check("총 환불액이 결제액을 초과하지 않는다", total_refunded <= row["amount"], True)
        check("총 환불액이 성공한 요청 수 * partial과 정확히 일치한다(중복/유실 없음)",
              total_refunded, len(succeeded) * partial)
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
    print("\n--- 6. TOCTOU 가드 구조 검사 (결정적) ---")
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


def test_refund_guard_is_structural():
    """환불의 동시성 방어가 소스 레벨에 남아 있는가 — 결정적 검사.

    2026-08-11 실측: `test_admin_refund_race()`(시나리오 5)에서 `BEGIN IMMEDIATE`를 없애거나
    UPDATE의 `WHERE status=?` 조건을 없애는 변이를 각각 넣어 봤는데, 3스레드 재현으로는
    **둘 다 잡히지 않았다**(TestClient 스레드가 이 경로에서는 창을 벌리지 못한다 —
    `test_admin_registry_status_race()`가 이미 겪은 것과 같은 종류의 한계). 확률에 기대는
    검사만 두면 가드가 사라져도 통과하는 날이 생기므로, `test_toctou_guard_is_structural()`과
    같은 방법으로 소스 레벨에서 함께 못 박는다.
    """
    print("\n--- 7. refund 가드 구조 검사 (결정적) ---")
    src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "api", "v1", "payments.py"),
               encoding="utf-8-sig").read()
    i = src.index("def refund_payment")
    j = src.index("\ndef ", i + 1)
    body = src[i:j]

    check_true("함수 진입 직후 쓰기 락을 선점한다(BEGIN IMMEDIATE)",
               'conn.execute("BEGIN IMMEDIATE")' in body)
    check_true("UPDATE가 현재 상태를 다시 확인한다(WHERE id=? AND status=?)",
               "WHERE id=? AND status=?" in body)
    check_true("rowcount==0이면 거부한다", "cursor.rowcount == 0" in body)
    check_true("거부 시 롤백한다", "conn.rollback()" in body)
    check_true("거부 응답이 409다(다른 요청이 먼저 반영됨)",
               "409," in body or "409)" in body)


def test_admin_webhook_reprocess_race():
    """같은 Webhook 수신 1건에 재처리 요청 3개를 정확히 동시에 보낸다.

    2026-08-16 (Sprint 140, Transaction/Concurrency Audit) ― 환불/등기부/구독
    상태변경 레이스는 전부 실제 스레드로 재현하는 테스트가 있는데, Webhook
    재처리(`admin_reprocess_webhook` → `reprocess_webhook()`)는 아래
    `test_webhook_reprocess_guard_is_structural()`처럼 **소스 텍스트에
    "BEGIN IMMEDIATE"가 있는지만** 확인하는 정적 검사뿐이었다 — 실제 동시
    요청으로 락이 진짜 직렬화하는지 실행해 본 적이 없었다(전체 파일 grep으로
    확인: 이 엔드포인트를 대상으로 한 `threading` 기반 테스트 0건). 정적 검사는
    "그 문자열이 코드에 있다"만 보장하지, 순서가 뒤바뀌거나 락 범위가 좁아져도
    같은 문자열이 남아 있으면 통과한다 — 실제 결함을 잡는 것은 이 테스트다.

    RECEIVED 상태의 Webhook 수신 기록(PAID -> REFUNDED로 실제 상태를 바꾸는
    이벤트)을 하나 만들어 두고, 재처리 요청 3개를 동시에 보낸다. `BEGIN
    IMMEDIATE`가 실제로 직렬화하면 정확히 1건만 APPLIED고 나머지는
    `webhook_reprocess_block_reason()`이 "이미 처리됨"으로 막아 400을 받는다.
    """
    print("\n--- 10. admin webhook reprocess race (3 threads, single RECEIVED webhook) ---")
    r = client.post(
        "/api/v1/payments",
        json={"payment_type": "SUBSCRIPTION", "plan": "BASIC",
              "amount": resolve_plan_price("BASIC", BILLING_MONTHLY), "billing_cycle": BILLING_MONTHLY},
        headers=auth_headers(TEST_USER_WEBHOOK_REPROCESS),
    )
    body = r.json()
    check_true("설정: 결제 생성 성공", body.get("success"))
    payment_id = body["data"]["payment"]["id"]

    conn = get_connection()
    try:
        pg_txid = conn.execute(
            "SELECT pg_transaction_id FROM payments WHERE id=?", (payment_id,)
        ).fetchone()[0]
        now = datetime.now().isoformat()
        payload = '{"event_id": "qa-race-wh-1", "event_type": "PAYMENT_REFUNDED", ' \
                  '"pg_transaction_id": "%s"}' % pg_txid
        webhook_id = conn.execute(
            """
            INSERT INTO payment_webhooks
            (provider, event_type, event_id, pg_transaction_id, payment_id,
             signature_verified, processing_status, raw_payload, received_at)
            VALUES ('mock','PAYMENT_REFUNDED','qa-race-wh-1',?,?,1,'RECEIVED',?,?)
            """,
            (pg_txid, payment_id, payload, now),
        ).lastrowid
        conn.commit()
    finally:
        conn.close()

    n = 3
    super_admin_headers = {"X-Admin-Key": os.environ["SUPER_ADMIN_API_KEY"]}
    results = [None] * n
    start_barrier = threading.Barrier(n)

    def worker(idx):
        start_barrier.wait()
        resp = client.post(
            f"/api/v1/admin/payments/webhooks/{webhook_id}/reprocess",
            headers=super_admin_headers,
        )
        results[idx] = (resp.status_code, resp.json())

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    statuses = [code for code, _ in results]
    applied = [b for code, b in results if code == 200 and b.get("data", {}).get("result") == "APPLIED"]
    rejected = [code for code in statuses if code == 400]
    check("모든 요청이 유효한 코드로만 응답(200 또는 400)",
          all(c in (200, 400) for c in statuses), True)
    check("정확히 1건만 APPLIED된다(중복 적용 없음)", len(applied), 1)
    check("나머지 2건은 이미 처리됨으로 거부된다(400)", len(rejected), n - 1)

    conn = get_connection()
    try:
        pay_row = conn.execute("SELECT status FROM payments WHERE id=?", (payment_id,)).fetchone()
        wh_row = conn.execute(
            "SELECT processing_status FROM payment_webhooks WHERE id=?", (webhook_id,)
        ).fetchone()
        applied_logs = conn.execute(
            "SELECT COUNT(*) FROM payment_logs WHERE payment_id=? AND event_type='WEBHOOK' AND status='SUCCESS'",
            (payment_id,),
        ).fetchone()[0]
        check("결제 상태가 정확히 한 번만 REFUNDED로 바뀐다", pay_row["status"], "REFUNDED")
        check("Webhook 처리 상태는 PROCESSED로 정착된다(RECEIVED에 남지 않음)",
              wh_row["processing_status"], "PROCESSED")
        check("WEBHOOK 성공 로그가 정확히 1건뿐이다(중복 기록 없음)", applied_logs, 1)
    finally:
        conn.close()


def test_webhook_reprocess_guard_is_structural():
    """Webhook 재처리(`reprocess_webhook()`)와 그 안이 호출하는 상태 반영(`_apply_webhook_event()`)
    도 환불과 같은 `BEGIN IMMEDIATE` + 조건부 UPDATE 패턴을 쓰는가 — 결정적 검사.

    운영자가 같은 Webhook을 두 번 빠르게 재처리 클릭하는 시나리오를 막는다. 실시간 수신
    경로(`receive_payment_webhook`)와 재처리가 **같은** `_apply_webhook_event()`를 공유하므로
    가드 하나로 두 경로를 함께 지킨다.
    """
    print("\n--- 8. webhook 재처리 가드 구조 검사 (결정적) ---")
    src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "api", "v1", "payments.py"),
               encoding="utf-8-sig").read()

    i = src.index("def reprocess_webhook")
    j = src.index("\ndef ", i + 1)
    reprocess_body = src[i:j]
    check_true("reprocess_webhook 진입 직후 쓰기 락을 선점한다(BEGIN IMMEDIATE)",
               'conn.execute("BEGIN IMMEDIATE")' in reprocess_body)

    i2 = src.index("def _apply_webhook_event")
    j2 = src.index("\ndef ", i2 + 1)
    apply_body = src[i2:j2]
    check_true("_apply_webhook_event의 UPDATE가 현재 상태를 다시 확인한다(WHERE id=? AND status=?)",
               "WHERE id=? AND status=?" in apply_body)
    check_true("rowcount==0이면 적용하지 않고 건너뛴다(멱등)",
               "cursor.rowcount == 0" in apply_body)


def test_admin_subscription_status_race():
    """ACTIVE 구독 1건에 같은 목표 상태(CANCELLED)로 두 SUPER_ADMIN 요청을 정확히 동시에 보낸다.

    2026-08-12 발견: `api/v1/subscriptions.py:change_status()`(Admin PATCH
    /admin/subscriptions/{id}의 유일한 호출부)에는 이 감사에서 다룬 다른 모든 상태 전이
    경로(registry-requests #21, refund, webhook reprocess)와 달리 **동시성 가드가 전혀
    없었다.** 재현(5/5): 같은 구독에 PAUSED/CANCELLED로 동시 PATCH를 보내면 **둘 다 200
    성공**을 응답하고, 최종 DB 상태는 나중에 커밋되는 쪽으로 조용히 결정됐다 — 이긴 쪽만
    성공 응답을 받아야 하는데 진 쪽도 자신의 요청이 반영됐다고 믿게 된다(과금에 직접
    영향을 주는 SUPER_ADMIN 전용 엔드포인트라 영향이 작지 않다). `change_status()`에
    `BEGIN IMMEDIATE` + 조건부 UPDATE(WHERE id=? AND status=?) + rowcount 확인을 추가해
    해소했다.

    같은 목표(CANCELLED)를 두 번 겨냥한다 — CANCELLED는 종결 상태(전이 규칙상 나가는
    전이가 없다)라, 직렬화가 정상 동작하면 먼저 반영된 쪽만 200이고 나중 쪽은 "이미
    CANCELLED"라 전이 자체가 막혀 400을 받는다(수정 전에는 방어가 아예 없어 **둘 다
    200**을 받았다 — 이 테스트가 검출하려는 것이 바로 그 차이다).
    """
    print("\n--- 9. admin subscription status race (2 threads, same target CANCELLED) ---")
    conn = get_connection()
    try:
        ts = datetime.now().isoformat()
        sub_id = conn.execute(
            "INSERT INTO subscriptions (user_id,plan,price,status,started_at,expires_at,created_at,updated_at)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (TEST_USER_SUB_STATUS, "BASIC", 12900, "ACTIVE", ts,
             (datetime.now() + timedelta(days=30)).isoformat(), ts, ts),
        ).lastrowid
        conn.commit()
    finally:
        conn.close()

    super_admin_headers = {"X-Admin-Key": os.environ["SUPER_ADMIN_API_KEY"]}
    n = 2
    results = [None] * n
    start_barrier = threading.Barrier(n)

    def worker(idx):
        start_barrier.wait()
        r = client.patch(
            f"/api/v1/admin/subscriptions/{sub_id}",
            json={"status": "CANCELLED", "reason": "qa-race-sub-status"},
            headers=super_admin_headers,
        )
        results[idx] = (r.status_code, r.json())

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    statuses = [code for code, _ in results]
    check("exactly one request succeeded (200)", statuses.count(200), 1)
    check("the other request did not also succeed(둘 다 200이면 수정 전 결함이 재발한 것)",
          statuses.count(200) == 1 and any(c != 200 for c in statuses), True)
    check("the rejected request used a valid conflict/rule code (400 or 409)",
          all(c in (200, 400, 409) for c in statuses), True)

    conn = get_connection()
    try:
        row = conn.execute("SELECT status FROM subscriptions WHERE id=?", (sub_id,)).fetchone()
        check("최종 DB 상태가 CANCELLED다(둘 다 같은 목표라 혼선 여지 없음)", row["status"], "CANCELLED")
    finally:
        conn.close()


def test_subscription_status_guard_is_structural():
    """구독 상태 변경의 동시성 방어가 소스 레벨에 남아 있는가 — 결정적 검사.

    이유는 refund/webhook 재처리와 동일 — 3스레드/2스레드 재현이 이 종류의 좁은 창을
    안정적으로 잡지 못할 수 있다(이번 감사에서 반복 확인된 한계).
    """
    print("\n--- 10. 구독 상태 변경 가드 구조 검사 (결정적) ---")
    src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "api", "v1", "subscriptions.py"),
               encoding="utf-8-sig").read()
    i = src.index("def change_status")
    j = src.index("\ndef ", i + 1)
    body = src[i:j]

    check_true("함수 진입 직후 쓰기 락을 선점한다(BEGIN IMMEDIATE)",
               'conn.execute("BEGIN IMMEDIATE")' in body)
    # 2026-08-12 BUGS #58 이어 발견한 재활성화 결함(만료 시각 미갱신) 수정으로 ACTIVE 분기가
    # new_expires_at 유무에 따라 둘로 나뉘어 총 4개 UPDATE 분기가 됐다(CANCELLED/EXPIRED,
    # ACTIVE+new_expires_at, ACTIVE 그대로, 그 외/PAUSED 등) — 전부 조건부여야 한다.
    check_true("모든 UPDATE 분기가 현재 상태를 다시 확인한다(WHERE id=? AND status=?, 4곳)",
               body.count("WHERE id=? AND status=?") == 4)
    check_true("rowcount==0이면 거부한다", "cursor.rowcount == 0" in body)
    check_true("거부 시 롤백한다", "conn.rollback()" in body)


def test_registry_credit_adjust_race():
    """무료 횟수 조정이 동시에 들어와도 원장 합계가 정확한가 (2026-08-12 Sprint 67 신설).

    이 저장소의 다른 경합 지점(등기부 무료한도/결제/환불/구독 상태)은 전부
    "읽고 -> 판단하고 -> 쓴다" 구조라 `BEGIN IMMEDIATE`나 조건부 UPDATE로 막아야 했다.
    반면 `adjust_registry_credit`은 **append-only 원장**이다 — `add_credit()`은 현재 합계를
    읽지 않고 행 하나를 INSERT할 뿐이고, 상한 검사도 **1회 조정량**에만 걸린다(누적 아님).

    구조상 lost update가 생길 수 없다는 뜻인데, **그 사실이 검증된 적은 없었다.**
    누군가 나중에 "누적 상한"이나 "현재 잔액 확인 후 조정" 같은 읽기-판단을 넣으면
    조용히 경합이 생긴다 — 그때 이 검사가 잡는다.
    """
    print("\n--- 11. 등기부 무료횟수 조정 동시 요청 (append-only 원장) ---")
    user = "qa-race-credit-" + uuid.uuid4().hex[:10]
    sh = {"X-Admin-Key": os.environ["SUPER_ADMIN_API_KEY"]}

    N_GRANT, N_DEDUCT = 8, 4
    GRANT_AMT, DEDUCT_AMT = 3, 1
    results, errors = [], []
    lock = threading.Lock()

    def adjust(reason_type, amount):
        try:
            r = client.post("/api/v1/admin/registry-credits",
                            json={"user_id": user, "reason_type": reason_type,
                                  "amount": amount, "reason": "race"},
                            headers=sh)
            with lock:
                results.append((reason_type, r.status_code))
        except Exception as e:  # noqa: BLE001 - 예외 자체가 검사 대상이다
            with lock:
                errors.append(repr(e))

    threads = ([threading.Thread(target=adjust, args=("GRANT", GRANT_AMT)) for _ in range(N_GRANT)]
               + [threading.Thread(target=adjust, args=("DEDUCT", DEDUCT_AMT)) for _ in range(N_DEDUCT)])
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)

    check("동시 조정 중 예외 없음", errors, [])
    check("모든 요청이 200", sorted({c for _, c in results}), [200])
    check("요청 수만큼 처리됨", len(results), N_GRANT + N_DEDUCT)

    expected_adjustment = N_GRANT * GRANT_AMT - N_DEDUCT * DEDUCT_AMT
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT reason_type, amount FROM registry_credits WHERE user_id=?", (user,)).fetchall()
        ledger_sum = conn.execute(
            "SELECT COALESCE(SUM(amount),0) FROM registry_credits WHERE user_id=?",
            (user,)).fetchone()[0]
    finally:
        conn.close()

    # 원장에 요청 하나당 정확히 한 행 — 유실도 중복도 없어야 한다
    check("원장 행 수 = 요청 수 (유실/중복 없음)", len(rows), N_GRANT + N_DEDUCT)
    check("GRANT 행 수", sum(1 for r in rows if r["reason_type"] == "GRANT"), N_GRANT)
    check("DEDUCT 행 수", sum(1 for r in rows if r["reason_type"] == "DEDUCT"), N_DEDUCT)
    check("원장 합계가 정확하다 (lost update 없음)", ledger_sum, expected_adjustment)

    # API가 보고하는 값도 같은 합계여야 한다
    body = client.get("/api/v1/admin/registry-credits/%s" % user,
                      headers={"X-Admin-Key": os.environ["ADMIN_API_KEY"]}).json()["data"]
    check("API adjustment가 원장 합계와 일치", body["adjustment"], expected_adjustment)
    check("effective_limit = plan_limit + adjustment",
          body["effective_limit"], body["plan_limit"] + expected_adjustment)

    conn = get_connection()
    try:
        conn.execute("DELETE FROM audit_logs WHERE target_type='REGISTRY_CREDIT'"
                     " AND target_id IN (SELECT CAST(id AS TEXT) FROM registry_credits WHERE user_id=?)",
                     (user,))
        conn.execute("DELETE FROM registry_credit_logs WHERE user_id=?", (user,))
        conn.execute("DELETE FROM registry_credits WHERE user_id=?", (user,))
        conn.commit()
        left = conn.execute("SELECT COUNT(*) FROM registry_credits WHERE user_id=?",
                            (user,)).fetchone()[0]
    finally:
        conn.close()
    check("이 시나리오의 QA 데이터 정리됨", left, 0)


def test_search_preset_cap_race():
    """저장 개수 상한이 동시 요청에서도 지켜지는가 (2026-08-12 Sprint 67, BUGS #66).

    `create_preset()`은 COUNT로 상한을 판정한 뒤 INSERT한다 — 전형적인 "확인 후 쓰기"다.
    이 저장소는 등기부 무료한도·결제·환불·구독 상태 등 다른 경합 지점을 전부
    `BEGIN IMMEDIATE`나 조건부 UPDATE로 굳혔는데 **이 경로만 빠져 있었다.**

    실측 재현(수정 전): 99개 상태에서 12개 동시 요청 -> 2건 성공 -> 최종 101개.
    상한이 조용히 뚫린다.
    """
    print("\n--- 12. 검색조건 저장 상한 동시 요청 (BUGS #66) ---")
    from api.v1.search_presets import MAX_PRESETS_PER_USER

    user = "qa-race-preset-" + uuid.uuid4().hex[:10]
    h = auth_headers(user)

    # 상한 직전(99개)까지 채운다 — 남은 자리는 정확히 하나다.
    conn = get_connection()
    try:
        conn.executemany(
            "INSERT INTO search_presets (user_id,name,conditions,created_at) VALUES (?,?,?,?)",
            [(user, "seed-%d" % i, "{}", "2026-01-01") for i in range(MAX_PRESETS_PER_USER - 1)])
        conn.commit()
        seeded = conn.execute("SELECT COUNT(*) FROM search_presets WHERE user_id=?",
                              (user,)).fetchone()[0]
    finally:
        conn.close()
    check("상한 직전까지 채웠다", seeded, MAX_PRESETS_PER_USER - 1)

    n = 12
    barrier = threading.Barrier(n)
    results = [None] * n

    def worker(idx):
        barrier.wait()   # 동시 진입을 맞춘다(Sprint 56 교훈: start()만으로는 겹치지 않는다)
        r = client.post("/api/v1/search-presets",
                        json={"name": "race-%d" % idx, "conditions": {}}, headers=h)
        results[idx] = r.json()

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)

    succeeded = [r for r in results if r and r.get("success")]
    rejected = [r for r in results if r and not r.get("success")]

    conn = get_connection()
    try:
        final = conn.execute("SELECT COUNT(*) FROM search_presets WHERE user_id=?",
                             (user,)).fetchone()[0]
    finally:
        conn.close()

    # 핵심: 남은 자리는 하나뿐이므로 정확히 1건만 성공해야 하고, 총량이 상한을 넘으면 안 된다.
    check("정확히 1건만 성공", len(succeeded), 1)
    check("나머지는 전부 거부", len(rejected), n - 1)
    check("최종 개수가 상한을 넘지 않는다", final, MAX_PRESETS_PER_USER)
    check("거부 응답이 상한 초과 코드",
          sorted({r.get("error") for r in rejected}),
          [ErrorCode.SEARCH_PRESET_LIMIT_EXCEEDED.value])

    conn = get_connection()
    try:
        conn.execute("DELETE FROM search_presets WHERE user_id=?", (user,))
        conn.commit()
        left = conn.execute("SELECT COUNT(*) FROM search_presets WHERE user_id=?",
                            (user,)).fetchone()[0]
    finally:
        conn.close()
    check("이 시나리오의 QA 데이터 정리됨", left, 0)


def test_search_preset_cap_guard_is_structural():
    """상한 가드가 원자적 구조를 유지하는가 (결정적 검사).

    스레드 재현은 확률적이라 좁은 창을 놓칠 수 있다(Sprint 58/59에서 실제로 겪었다).
    소스에 가드가 남아 있는지 결정적으로 확인해 둔다.
    """
    print("\n--- 13. 검색조건 상한 가드 구조 검사 ---")
    src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "api", "v1", "search_presets.py"), encoding="utf-8-sig").read()
    body = src[src.index("def create_preset("):src.index("def get_presets(")]
    check_true("BEGIN IMMEDIATE로 확인+삽입을 원자화한다", "BEGIN IMMEDIATE" in body)
    check_true("상한 초과 시 ROLLBACK한다", "ROLLBACK" in body)
    check_true("성공 시 명시적으로 COMMIT한다", "COMMIT" in body)
    # COUNT가 트랜잭션 안에 있어야 의미가 있다 — 밖에 있으면 가드가 무력하다
    begin_i = body.index("BEGIN IMMEDIATE")
    count_i = body.index("SELECT COUNT(*) FROM search_presets")
    insert_i = body.index("INSERT INTO search_presets")
    check_true("COUNT와 INSERT가 모두 트랜잭션 안에 있다", begin_i < count_i < insert_i)


class _PaymentsInterleavingConn:
    """`UPDATE payments` 직전에 콜백을 딱 한 번 실행하는 커넥션 래퍼 (2026-08-24 Sprint 253).

    위 `_InterleavingConn` 과 같은 이유로 존재한다 — SELECT 와 조건부 UPDATE 사이의 창은
    수 마이크로초라 실제 스레드로는 안정 재현이 불가능하다. 그 창을 직접 벌린다.
    다른 점은 가로채는 문장뿐이다(`UPDATE REGISTRY_REQUESTS` -> `UPDATE PAYMENTS`).
    """

    def __init__(self, conn, on_update):
        self._conn = conn
        self._on_update = on_update
        self.fired = False

    def execute(self, sql, *a, **kw):
        if not self.fired and sql.lstrip().upper().startswith("UPDATE PAYMENTS"):
            self.fired = True
            self._on_update()
        return self._conn.execute(sql, *a, **kw)

    def __getattr__(self, name):
        return getattr(self._conn, name)


def test_webhook_apply_cas_is_deterministic():
    """`_apply_webhook_event()` 의 **조건부 UPDATE 실패 분기**를 결정적으로 실행한다
    (2026-08-24 Sprint 253 신설).

    ## 왜 필요했나 — 커버리지 0 인 돈 관련 분기였다

    합산 커버리지에서 `api/v1/payments.py` 는 96% 인데, 미실행 14줄이 **전부 오류/롤백
    분기**였다. 그중 하나가 이것이다:

        cursor = conn.execute("UPDATE payments SET status=? ... WHERE id=? AND status=?", ...)
        if cursor.rowcount == 0:
            return skip("다른 요청이 먼저 상태를 바꿨습니다")

    이 줄이 없으면 **늦게 도착한 PG 노티가 이미 환불된 결제를 다시 PAID 로 되돌린다.**
    바로 위 `test_webhook_reprocess_guard_is_structural()` 은 소스에
    `WHERE id=? AND status=?` 문자열이 남아 있는지만 본다 — 그 조건이 실제로
    **rowcount 0 을 만들고, 그때 상태를 보존하며 skip 으로 답하는지**는 확인하지 못한다.

    ## 어떻게 결정적으로 만드나

    `_apply_webhook_event()` 는 `SELECT * FROM payments` 로 현재 상태를 읽고,
    그 값을 조건에 넣어 UPDATE 한다. 래퍼가 **UPDATE 를 대행하기 바로 전에** 다른
    커넥션으로 상태를 바꿔 놓으면 조건부 UPDATE 는 rowcount=0 을 볼 수밖에 없다.
    확률이 개입하지 않는다.
    """
    import api.v1.payments as pay_mod

    print("\n--- 16. webhook 상태 반영 CAS 분기 결정적 검증 (Sprint 253) ---")

    # 설정: 결제 1건 + RECEIVED webhook 1건 (PAID -> REFUNDED 를 노리는 이벤트)
    r = client.post(
        "/api/v1/payments",
        json={"payment_type": "SUBSCRIPTION", "plan": "BASIC",
              "amount": resolve_plan_price("BASIC", BILLING_MONTHLY),
              "billing_cycle": BILLING_MONTHLY},
        headers=auth_headers(TEST_USER_WEBHOOK_CAS),
    )
    body = r.json()
    check_true("설정: 결제 생성 성공", body.get("success"))
    payment_id = body["data"]["payment"]["id"]

    conn = get_connection()
    try:
        pg_txid = conn.execute(
            "SELECT pg_transaction_id FROM payments WHERE id=?", (payment_id,)
        ).fetchone()[0]
        # 노티가 노리는 전이가 유효하도록 현재 상태를 PAID 로 둔다.
        conn.execute("UPDATE payments SET status='PAID' WHERE id=?", (payment_id,))
        now = datetime.now().isoformat()
        webhook_id = conn.execute(
            """
            INSERT INTO payment_webhooks
            (provider, event_type, event_id, pg_transaction_id, payment_id,
             signature_verified, processing_status, raw_payload, received_at)
            VALUES ('mock','PAYMENT_REFUNDED',?,?,?,1,'RECEIVED','{}',?)
            """,
            ("qa-cas-" + uuid.uuid4().hex[:8], pg_txid, payment_id, now),
        ).lastrowid
        conn.commit()
    finally:
        conn.close()

    # 끼어드는 쪽: UPDATE 직전에 다른 커넥션으로 상태를 먼저 바꾼다(환불이 먼저 확정된 상황).
    def interloper():
        c2 = get_connection()
        try:
            c2.execute("UPDATE payments SET status='REFUNDED' WHERE id=?", (payment_id,))
            c2.commit()
        finally:
            c2.close()

    class _Event:
        event_type = "PAYMENT_REFUNDED"
        status = "REFUNDED"
        pg_transaction_id = pg_txid
        amount = None
        raw = {}

    real = get_connection()
    wrapped = _PaymentsInterleavingConn(real, interloper)
    try:
        result = pay_mod._apply_webhook_event(wrapped, webhook_id, "mock", _Event())
        wrapped.commit()
    finally:
        real.close()

    check_true("래퍼가 UPDATE payments 를 실제로 가로챘다", wrapped.fired)
    # 값을 문자열로 베끼지 않는다 — 제품 상수를 그대로 쓴다(WEBHOOK_SKIPPED == "SKIPPED").
    check("★ CAS 실패 시 skip 으로 답한다", result.get("result"), pay_mod.WEBHOOK_SKIPPED)
    check("★ skip 사유가 '다른 요청이 먼저' 임을 밝힌다",
          "먼저" in (result.get("reason") or ""), True)

    # 상태가 끼어든 쪽의 값으로 **보존**되는가 (덮어쓰지 않았는가)
    conn = get_connection()
    try:
        final = conn.execute("SELECT status FROM payments WHERE id=?", (payment_id,)).fetchone()[0]
        wh = conn.execute(
            "SELECT processing_status FROM payment_webhooks WHERE id=?", (webhook_id,)
        ).fetchone()[0]
    finally:
        conn.close()
    check("★ 끼어든 쪽의 상태가 보존된다(덮어쓰지 않는다)", final, "REFUNDED")
    check("webhook 수신 기록이 종결 처리된다(RECEIVED 로 남지 않는다)",
          wh != "RECEIVED", True)


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

        # 환불 레이스 시나리오가 만든 결제도 같은 이유(target_id로 연결)로 먼저 id를 구해 지운다.
        refund_payment_ids = [
            r["id"] for r in conn.execute(
                "SELECT id FROM payments WHERE user_id=?", (TEST_USER_REFUND,)
            ).fetchall()
        ]
        if refund_payment_ids:
            placeholders = ",".join("?" * len(refund_payment_ids))
            cur = conn.execute(
                "DELETE FROM audit_logs WHERE target_type='PAYMENT' AND target_id IN (%s)" % placeholders,
                refund_payment_ids,
            )
            total += cur.rowcount

        # FK가 런타임에 강제되므로 자식 -> 부모 순서로 지운다(test_api_regression.py의
        # cleanup()과 동일한 순서 원칙 — registry_credit_logs/payment_logs가 각각
        # registry_usage/payments를 참조하므로 먼저 지워야 한다).
        # 구독 상태 레이스 시나리오가 만든 audit_logs도 target_id(subscriptions.id)로 연결된다.
        sub_status_ids = [
            r["id"] for r in conn.execute(
                "SELECT id FROM subscriptions WHERE user_id=?", (TEST_USER_SUB_STATUS,)
            ).fetchall()
        ]
        if sub_status_ids:
            placeholders = ",".join("?" * len(sub_status_ids))
            cur = conn.execute(
                "DELETE FROM audit_logs WHERE target_type='SUBSCRIPTION' AND target_id IN (%s)" % placeholders,
                [str(i) for i in sub_status_ids],
            )
            total += cur.rowcount

        # Webhook 재처리 레이스 시나리오가 만든 payment_webhooks/audit_logs도 payment_id로
        # 연결된다(payment_webhooks에는 user_id 컬럼 자체가 없다) ― payments를 지우기
        # 전에 먼저 정리해야 한다(자식 -> 부모 순서).
        wh_payment_ids = [
            r["id"] for r in conn.execute(
                "SELECT id FROM payments WHERE user_id=?", (TEST_USER_WEBHOOK_REPROCESS,)
            ).fetchall()
        ]
        if wh_payment_ids:
            placeholders = ",".join("?" * len(wh_payment_ids))
            cur = conn.execute(
                "DELETE FROM audit_logs WHERE target_type='PAYMENT' AND target_id IN (%s)" % placeholders,
                wh_payment_ids,
            )
            total += cur.rowcount
        # 재처리 요청이 거부(SKIPPED)될 때는 payment_id 없이 target_type='PAYMENT_WEBHOOK'
        # + target_id=webhook_id로 감사 로그가 남는다(`admin_reprocess_webhook()`의
        # `linked_payment_id` 분기 — `_apply_webhook_event()`의 `skip()`은 payment_id를
        # 돌려주지 않는다). 정상 동작에서는 이 분기가 애초에 실행되지 않지만(레이스 패자는
        # `webhook_reprocess_block_reason()`에서 400으로 막혀 record_audit() 도달 전에
        # 끝난다), 변이 검증처럼 그 방어를 일부러 깬 상태로 실행하면 이 모양의 행이 남는다
        # — 실측으로 걸린 잔해였다(2026-08-16). payment_id로는 못 찾으므로 event_id로
        # webhook_id를 다시 찾아 정리한다.
        wh_ids = [
            r["id"] for r in conn.execute(
                "SELECT id FROM payment_webhooks WHERE event_id='qa-race-wh-1'"
            ).fetchall()
        ]
        if wh_ids:
            placeholders = ",".join("?" * len(wh_ids))
            cur = conn.execute(
                "DELETE FROM audit_logs WHERE target_type='PAYMENT_WEBHOOK' AND target_id IN (%s)" % placeholders,
                [str(i) for i in wh_ids],
            )
            total += cur.rowcount
        if wh_payment_ids:
            placeholders = ",".join("?" * len(wh_payment_ids))
            cur = conn.execute(
                "DELETE FROM payment_webhooks WHERE payment_id IN (%s)" % placeholders,
                wh_payment_ids,
            )
            total += cur.rowcount

        # CAS 시나리오(Sprint 253)가 만든 webhook 도 payments 앞에 치운다 —
        # payment_webhooks 에는 user_id 컬럼이 없어 payment_id 로만 연결된다.
        # ★ 이 정리를 빼먹어 운영 DB 에 qa- 행 7개가 남은 적이 있다(2026-08-24).
        #   `test_api_regression.py` 의 "no stray qa-* rows" 가드가 그것을 잡았다 —
        #   새 TEST_USER_* 를 만들면 **반드시** 이 목록에도 넣어야 한다.
        cas_payment_ids = [
            r["id"] for r in conn.execute(
                "SELECT id FROM payments WHERE user_id=?", (TEST_USER_WEBHOOK_CAS,)
            ).fetchall()
        ]
        if cas_payment_ids:
            placeholders = ",".join("?" * len(cas_payment_ids))
            cur = conn.execute(
                "DELETE FROM payment_webhooks WHERE payment_id IN (%s)" % placeholders,
                cas_payment_ids,
            )
            total += cur.rowcount
            cur = conn.execute(
                "DELETE FROM audit_logs WHERE target_type='PAYMENT' AND target_id IN (%s)"
                % placeholders, [str(i) for i in cas_payment_ids],
            )
            total += cur.rowcount

        # subscriptions가 payments **앞**이어야 한다 ― `subscriptions.payment_id`가
        # 생기면서 구독이 결제의 자식이 됐다 (2026-08-13 Sprint 96, BUGS #94).
        for table in ("registry_credit_logs", "registry_requests", "registry_usage",
                      "payment_logs", "subscriptions", "payments"):
            for user in (TEST_USER_LIMIT, TEST_USER_PAYMENT, TEST_USER_SUBSCRIPTION,
                         TEST_USER_ADMIN_TARGET, TEST_USER_REFUND, TEST_USER_SUB_STATUS,
                         TEST_USER_WEBHOOK_REPROCESS, TEST_USER_WEBHOOK_CAS):
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
        left += conn.execute(
            "SELECT COUNT(*) FROM payments WHERE user_id=?", (TEST_USER_REFUND,)
        ).fetchone()[0]
        left += conn.execute(
            "SELECT COUNT(*) FROM subscriptions WHERE user_id=?", (TEST_USER_SUB_STATUS,)
        ).fetchone()[0]
        left += conn.execute(
            "SELECT COUNT(*) FROM payments WHERE user_id=?", (TEST_USER_WEBHOOK_REPROCESS,)
        ).fetchone()[0]
        left += conn.execute(
            "SELECT COUNT(*) FROM payment_webhooks WHERE event_id='qa-race-wh-1'"
        ).fetchone()[0]
        left += conn.execute(
            "SELECT COUNT(*) FROM payments WHERE user_id=?", (TEST_USER_WEBHOOK_CAS,)
        ).fetchone()[0]
        left += conn.execute(
            "SELECT COUNT(*) FROM subscriptions WHERE user_id=?", (TEST_USER_WEBHOOK_CAS,)
        ).fetchone()[0]
        left += conn.execute(
            "SELECT COUNT(*) FROM payment_webhooks WHERE event_id LIKE 'qa-cas-%'"
        ).fetchone()[0]
        if wh_ids:
            placeholders = ",".join("?" * len(wh_ids))
            left += conn.execute(
                "SELECT COUNT(*) FROM audit_logs WHERE target_type='PAYMENT_WEBHOOK'"
                " AND target_id IN (%s)" % placeholders,
                [str(i) for i in wh_ids],
            ).fetchone()[0]
        check("no test rows left", left, 0)
    finally:
        conn.close()


class _InterleavingConn:
    """`UPDATE registry_requests` 직전에 콜백을 딱 한 번 실행하는 커넥션 래퍼.

    SELECT와 조건부 UPDATE 사이의 창은 수 마이크로초라 실제 스레드로는 안정 재현이
    불가능하다는 것이 2026-08-11 실측 결론이었다(시나리오 4 주석: 2스레드 3/4, 6스레드 1/5).
    그래서 그 창을 **직접 벌린다** ― UPDATE를 대행하기 바로 전에 다른 커넥션으로 상태를
    바꿔 놓으면 조건부 UPDATE는 rowcount=0을 볼 수밖에 없다. 확률이 개입하지 않는다.

    구조 검사(`test_toctou_guard_is_structural()`)는 소스에 가드 문자열이 남아 있는지만
    보므로, 가드가 실제로 **409를 내고 롤백하며 앞선 결과를 보존하는지**는 확인하지 못한다.
    이 래퍼가 그 실행 경로를 결정적으로 밟는다.
    """

    def __init__(self, conn, on_update):
        self._conn = conn
        self._on_update = on_update
        self.fired = False

    def execute(self, sql, *a, **kw):
        if not self.fired and sql.lstrip().upper().startswith("UPDATE REGISTRY_REQUESTS"):
            self.fired = True
            self._on_update()
        return self._conn.execute(sql, *a, **kw)

    def __getattr__(self, name):
        return getattr(self._conn, name)


def _new_processing_request():
    conn = get_connection()
    try:
        item_id = conn.execute("SELECT id FROM auction_item LIMIT 1").fetchone()["id"]
        req_id = conn.execute(
            "INSERT INTO registry_requests (user_id,item_id,status,requested_at) VALUES (?,?,?,?)",
            (TEST_USER_ADMIN_TARGET, item_id, "PROCESSING", datetime.now().isoformat()),
        ).lastrowid
        conn.commit()
        return req_id
    finally:
        conn.close()


def test_admin_registry_conflict_is_deterministic():
    """409 분기를 **결정적으로** 실행시켜, 거부 응답과 데이터 보존을 함께 확인한다
    (2026-08-13 Sprint 85 신설).

    지금까지 이 분기의 근거는 (a) 확률적 스레드 재현과 (b) 소스 문자열 검사 두 개뿐이었다.
    둘 다 "409를 실제로 돌려주는가 / 앞선 관리자의 결과가 살아남는가"는 검증하지 못한다.
    끼어든 쪽이 COMPLETED(doc_url 포함)로 먼저 확정한 뒤, 진 쪽의 FAILED(reason 포함)가
    어떻게 처리되는지 본다 ― 조용히 덮어쓰면 운영자는 발급된 등기부를 잃는다.
    """
    import api.v1.admin as admin_mod

    print("\n--- 14. admin registry 409 분기 결정적 검증 (Sprint 85) ---")
    admin_headers = {"X-Admin-Key": os.environ["ADMIN_API_KEY"]}
    req_id = _new_processing_request()
    INTERLOPER_URL = "https://example.com/qa-interloper.pdf"

    def interloper():
        # 다른 관리자 요청이 먼저 반영된 상황. 이 시점의 admin 커넥션은 SELECT만 했고
        # sqlite3 모듈은 SELECT로 트랜잭션을 열지 않으므로 락 없이 끼어들 수 있다 ―
        # 이것이 TOCTOU 창의 실제 모습이다.
        c = get_connection()
        try:
            c.execute(
                "UPDATE registry_requests SET status=?, completed_at=?, doc_url=? WHERE id=?",
                ("COMPLETED", datetime.now().isoformat(), INTERLOPER_URL, req_id),
            )
            c.commit()
        finally:
            c.close()

    real_get_connection = admin_mod.get_connection
    box = {}

    def patched(*a, **kw):
        box["w"] = _InterleavingConn(real_get_connection(*a, **kw), interloper)
        return box["w"]

    admin_mod.get_connection = patched
    try:
        r = client.patch(
            "/api/v1/admin/registry-requests/%s" % req_id,
            json={"status": "FAILED", "reason": "qa-deterministic-loser"},
            headers=admin_headers,
        )
    finally:
        admin_mod.get_connection = real_get_connection

    check("끼어든 UPDATE가 실제로 실행됐다(창이 벌어졌다)", box.get("w").fired if box else None, True)
    check("진 쪽은 409로 거부된다", r.status_code, 409)
    check_true("거부 사유가 기대했던 현재 상태를 알려준다",
               "PROCESSING" in str(r.json().get("detail", "")))

    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT status, doc_url, reason FROM registry_requests WHERE id=?", (req_id,)
        ).fetchone()
    finally:
        conn.close()
    check("먼저 반영된 상태가 그대로 남는다", row["status"], "COMPLETED")
    check("먼저 발급된 doc_url이 덮이지 않는다", row["doc_url"], INTERLOPER_URL)
    check("진 쪽의 reason이 섞여 들어가지 않는다", row["reason"], None)

    # 대조군: 끼어들기가 없으면 **같은 요청이 성공한다**. 이게 없으면 위 409가 끼어들기
    # 때문인지 요청 자체가 잘못됐기 때문인지 구별되지 않는다(검사가 공허해진다).
    control_id = _new_processing_request()
    r2 = client.patch(
        "/api/v1/admin/registry-requests/%s" % control_id,
        json={"status": "FAILED", "reason": "qa-deterministic-control"},
        headers=admin_headers,
    )
    check("대조군(끼어들기 없음)은 같은 요청이 200", r2.status_code, 200)

    conn = get_connection()
    try:
        row2 = conn.execute(
            "SELECT status, reason FROM registry_requests WHERE id=?", (control_id,)
        ).fetchone()
    finally:
        conn.close()
    check("대조군은 요청대로 반영된다", (row2["status"], row2["reason"]),
          ("FAILED", "qa-deterministic-control"))


class _SubscriptionsInterleavingConn:
    """`UPDATE SUBSCRIPTIONS` 직전에 콜백을 딱 한 번 실행하는 커넥션 래퍼.

    위 두 래퍼와 같은 이유로 존재한다. 가로채는 문장만 다르다.
    """

    def __init__(self, conn, on_update):
        self._conn = conn
        self._on_update = on_update
        self.fired = False

    def execute(self, sql, *a, **kw):
        if not self.fired and sql.lstrip().upper().startswith("UPDATE SUBSCRIPTIONS"):
            self.fired = True
            self._on_update()
        return self._conn.execute(sql, *a, **kw)

    def __getattr__(self, name):
        return getattr(self._conn, name)


def _scratch_db():
    """이 검사 전용 DB 를 부트스트랩 3단계로 만든다.

    ★ 운영 DB 를 쓰지 않는다. 이 시나리오는 **두 커넥션이 각자 커밋**해야 성립하므로
      이 파일의 다른 검사처럼 qa- 행을 남겼다가 지우는 방식으로는 격리가 되지 않는다
      (커밋된 중간 상태가 잠시라도 운영 DB 에 보인다). 그리고 `sync_expired_status()` 는
      커넥션을 인자로 받으므로 전역 DB 를 건드리지 않고 그대로 태울 수 있다.
    """
    import contextlib
    import io as _io
    import tempfile
    import storage.database as dbmod
    import storage.migrate_v4_1 as mig
    import storage.migrations.run_migrations as runmig

    tmp = tempfile.mkdtemp(prefix="qa_race_sync_")
    path = os.path.join(tmp, "auction.db")
    prev_env = os.environ.get("AUCTION_DB_PATH")
    prev_path = dbmod.DB_PATH
    os.environ["AUCTION_DB_PATH"] = path
    dbmod.DB_PATH = path
    with contextlib.redirect_stdout(_io.StringIO()):
        dbmod.init_db()
        mig.migrate()
        runmig.run()

    def restore():
        import shutil
        dbmod.DB_PATH = prev_path
        if prev_env is None:
            os.environ.pop("AUCTION_DB_PATH", None)
        else:
            os.environ["AUCTION_DB_PATH"] = prev_env
        shutil.rmtree(tmp, ignore_errors=True)

    return dbmod, restore


def test_sync_expired_status_does_not_clobber_a_concurrent_change():
    """★ 자동 만료 동기화가 **그 사이 바뀐 상태를 덮어쓰지 않는다** (2026-08-24 Sprint 254).

    ## 무엇이 문제였나 (BUGS #180)

    `sync_expired_status()` 는 이 모듈에서 **유일하게 조건 없이** 쓰고 있었다:

        UPDATE subscriptions SET status=?, updated_at=? WHERE id=?      <- CAS 없음

    다른 writer(`change_status()`, `renew()`)는 전부 `AND status=?` 로 읽었던 값을 다시
    건다. 그리고 그 둘은 함수 진입 직후 `BEGIN IMMEDIATE` 로 쓰기 락을 먼저 잡는다 —
    실측해 보면 그 락이 SELECT~UPDATE 창을 실제로 닫는다(끼어든 쪽이 1.075초 대기 후에야
    쓴다). 그래서 그 둘의 `rowcount == 0` 분기는 현재 도달 불가능한 방어선이다.

    **이 함수만 다르다.** 읽기 경로(`GET /api/v1/subscriptions/me`, Admin 목록)에서
    락 없이 불리므로 창이 열려 있다. 그래서 여기만 실제로 덮어썼다.

    ## 왜 심각한가 — 금지된 전이가 DB 에 남는다

    바로 위 코드에 "전이 규칙을 우회하지 않는다 — 자동 전이도 같은 관문을 통과해야 한다"
    고 적혀 있고, 실제로 `assert_subscription_transition()` 을 부른다. 그런데 그 판정은
    **읽었던(낡은) 상태**로 한다. 해지가 끼어들면:

        판정: ACTIVE -> EXPIRED (허용)      실제로 덮는 대상: CANCELLED
        결과: CANCELLED -> EXPIRED 가 DB 에 남는다 -- 이 전이는 **금지**다
              (state_machines.py 에서 CANCELLED 는 최종 상태다)

    그리고 EXPIRED 는 최종이 아니라서(EXPIRED -> ACTIVE 허용) **해지된 구독이 재구독으로
    되살아난다.** 로그에도 `ACTIVE -> EXPIRED` 라는 사실이 아닌 문장이 남는다.

    ## 어떻게 결정적으로 재현하나

    래퍼가 UPDATE 를 대행하기 직전에, 다른 커넥션이 정식 경로(`change_status()`)로 해지를
    끝낸다. 확률이 개입하지 않는다.
    """
    import api.v1.subscriptions as subs_mod
    from api.v1.state_machines import can_transition_subscription

    print("\n--- 17. 자동 만료 동기화가 동시 변경을 덮지 않는다 (Sprint 254) ---")

    dbmod, restore = _scratch_db()
    try:
        user = "qa-race-sync-" + uuid.uuid4().hex[:10]
        past = (datetime.now() - timedelta(days=60)).isoformat()
        conn = dbmod.get_connection()
        try:
            sub_id = conn.execute(
                "INSERT INTO subscriptions (user_id, plan, price, status, started_at,"
                " expires_at, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
                (user, "BASIC", 12900, "ACTIVE", past, past, past, past),
            ).lastrowid
            conn.commit()
        finally:
            conn.close()

        # 검사가 공허하지 않다: 끼어들기가 없으면 이 행은 실제로 EXPIRED 로 동기화된다.
        conn = dbmod.get_connection()
        try:
            baseline_changed = subs_mod.sync_expired_status(conn, user, commit=True)
            baseline = conn.execute(
                "SELECT status FROM subscriptions WHERE id=?", (sub_id,)).fetchone()["status"]
        finally:
            conn.close()
        check("설정: 끼어들기가 없으면 자동 만료가 실제로 일어난다",
              (baseline_changed, baseline), (1, "EXPIRED"))

        # 다시 ACTIVE 로 돌려놓고 이번엔 창을 벌린다.
        conn = dbmod.get_connection()
        try:
            conn.execute("UPDATE subscriptions SET status='ACTIVE' WHERE id=?", (sub_id,))
            conn.commit()
        finally:
            conn.close()

        def interloper():
            """그 사이 사용자가 해지했다 — 정식 경로로."""
            c2 = dbmod.get_connection()
            try:
                subs_mod.change_status(c2, sub_id, subs_mod.SubscriptionStatus.CANCELLED,
                                       actor="qa-race")
                c2.commit()
            finally:
                c2.close()

        real = dbmod.get_connection()
        wrapped = _SubscriptionsInterleavingConn(real, interloper)
        try:
            changed = subs_mod.sync_expired_status(wrapped, user, commit=True)
        finally:
            real.close()

        conn = dbmod.get_connection()
        try:
            final = conn.execute(
                "SELECT status FROM subscriptions WHERE id=?", (sub_id,)).fetchone()["status"]
        finally:
            conn.close()

        check("래퍼가 UPDATE subscriptions 를 실제로 가로챘다", wrapped.fired, True)
        check("★ 그 사이 확정된 해지를 덮어쓰지 않는다", final, "CANCELLED")
        check("★ 덮지 않았으므로 '바꿨다'고 세지도 않는다", changed, 0)
        # 허용된 전이였다면 위 검사는 아무것도 증명하지 못한다(그냥 늦은 갱신일 뿐).
        check_true("★ 이 전이가 애초에 금지였음을 확인한다(검사가 공허하지 않다)",
                   not can_transition_subscription("CANCELLED", "EXPIRED"))

        # 그리고 다음 호출은 새 상태를 기준으로 판단한다 — 영구히 멈추지 않는다.
        conn = dbmod.get_connection()
        try:
            again = subs_mod.sync_expired_status(conn, user, commit=True)
            still = conn.execute(
                "SELECT status FROM subscriptions WHERE id=?", (sub_id,)).fetchone()["status"]
        finally:
            conn.close()
        check("★ 다음 호출도 해지를 건드리지 않는다(멱등)", (again, still), (0, "CANCELLED"))
    finally:
        restore()


def test_subscription_writers_all_use_cas():
    """구독 상태를 쓰는 **모든** 문장이 CAS 를 건다 — 새 writer 가 생겨도 걸린다.

    위 검사는 지금 있는 한 경로를 본다. 이 검사는 **다음에 추가될 경로**를 본다.
    `sync_expired_status()` 가 정확히 그렇게 빠져나갔다 — 나중에 붙은 함수였고,
    조건 없는 UPDATE 한 줄이 아무 검사에도 걸리지 않았다.
    """
    print("\n--- 18. 구독 writer 전수: 조건 없는 UPDATE 가 없다 (Sprint 254) ---")
    import re
    import api.v1.subscriptions as subs_mod

    src = open(subs_mod.__file__, encoding="utf-8").read()
    # ★ 먼저 **인접 문자열 리터럴을 잇는다.** 파이썬은 `"UPDATE ..." " WHERE ..."` 를
    #   한 문장으로 이어 붙이는데, 조각만 보면 뒤쪽 WHERE 절을 놓쳐 멀쩡한 CAS 를
    #   "조건 없음"으로 오판한다(이 검사를 쓰다가 실제로 `renew()` 를 오탐했다).
    joined = re.sub(r'"[ \t]*(?:\r?\n)?[ \t]*"', "", src)
    # 문자열 리터럴 안의 UPDATE 문만 본다(주석/설명문은 제외).
    stmts = re.findall(r'"(UPDATE subscriptions SET[^"]*)"', joined)
    print("    찾은 UPDATE 문: %d개" % len(stmts))
    check_true("검사가 공허하지 않다(UPDATE 문을 실제로 찾았다)", len(stmts) >= 4)
    naked = [q for q in stmts if "AND status=?" not in q]
    check("★ 조건 없이 구독 상태를 덮는 UPDATE 가 없다", naked, [])


def run():
    try:
        test_registry_free_limit_race()
        test_overage_payment_race()
        test_subscription_race()
        test_admin_registry_status_race()
        test_admin_refund_race()
        test_toctou_guard_is_structural()
        test_refund_guard_is_structural()
        test_admin_webhook_reprocess_race()
        test_webhook_apply_cas_is_deterministic()
        test_webhook_reprocess_guard_is_structural()
        test_admin_subscription_status_race()
        test_subscription_status_guard_is_structural()
        test_registry_credit_adjust_race()
        test_search_preset_cap_race()
        test_search_preset_cap_guard_is_structural()
        test_admin_registry_conflict_is_deterministic()
        test_sync_expired_status_does_not_clobber_a_concurrent_change()
        test_subscription_writers_all_use_cas()
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
