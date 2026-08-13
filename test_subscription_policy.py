"""
구독 정책 / 등기부 무료한도 / auction_case 복합키 회귀 테스트.

프로젝트에 pytest 설정이 없으므로 기존 test_*.py 관례(단독 실행 스크립트)를 그대로 따른다.
    python test_subscription_policy.py

DB에 쓰는 검사는 전부 롤백 트랜잭션 안에서만 수행하므로 실행해도 데이터가 남지 않는다.
콘솔 인코딩(cp949) 문제를 피하려고 출력은 ASCII만 사용한다(migrate_execute.py와 동일한 이유).
"""
import sys
import os
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from storage.database import get_connection
from api.v1.payments import (
    PLAN_CATALOG, VALID_PLANS, BILLING_MONTHLY, BILLING_YEARLY,
    BILLING_PERIOD_DAYS, resolve_plan_price, get_registry_monthly_limit,
)
from api.v1.registry import get_free_count, get_user_free_limit, get_month_start, DEFAULT_FREE_LIMIT

failures = []


def check(name, actual, expected):
    ok = actual == expected
    print("[%s] %s: %r (expected %r)" % ("PASS" if ok else "FAIL", name, actual, expected))
    if not ok:
        failures.append(name)


def check_true(name, cond, detail=""):
    """조건만 보는 검사. 기대값을 그대로 적기 어려운 비교(부등호 등)에 쓴다."""
    print("[%s] %s%s" % ("PASS" if cond else "FAIL", name, ("" if cond else " -- " + str(detail))))
    if not cond:
        failures.append(name)


# ---------------------------------------------------------------------------
# 1. 확정 구독 정책 (docs/decision-log.md "구독 정책 최종 확정")
# ---------------------------------------------------------------------------
def test_plan_prices():
    print("\n--- 1. plan prices (CTO confirmed) ---")
    check("BASIC monthly", resolve_plan_price("BASIC", BILLING_MONTHLY), 12900)
    check("BASIC yearly", resolve_plan_price("BASIC", BILLING_YEARLY), 154800)
    check("PRO monthly", resolve_plan_price("PRO", BILLING_MONTHLY), 22900)
    # PRO 연간은 정상가 274,800 -> 할인가 198,000
    check("PRO yearly (discounted)", resolve_plan_price("PRO", BILLING_YEARLY), 198000)
    check("PRO yearly list_price", PLAN_CATALOG["PRO"]["prices"][BILLING_YEARLY]["list_price"], 274800)
    check("valid plans", set(VALID_PLANS), {"BASIC", "PRO"})
    check("billing period monthly", BILLING_PERIOD_DAYS[BILLING_MONTHLY], 30)
    check("billing period yearly", BILLING_PERIOD_DAYS[BILLING_YEARLY], 365)


def test_registry_limits():
    print("\n--- 2. registry monthly limit per plan ---")
    check("BASIC limit", get_registry_monthly_limit("BASIC"), 5)
    check("PRO limit", get_registry_monthly_limit("PRO"), 10)
    check("unknown plan limit", get_registry_monthly_limit("BETA_EARLYBIRD"), 0)


def test_invalid_combinations():
    print("\n--- 3. invalid combinations are rejected ---")
    check("unknown plan", resolve_plan_price("BETA_EARLYBIRD", BILLING_MONTHLY), None)
    check("unknown cycle", resolve_plan_price("BASIC", "WEEKLY"), None)


# ---------------------------------------------------------------------------
# 2. 할인 구조 확장성 (list_price / sale_price / discount_percent / 기간)
#    카탈로그 값만 바꿔서 동작하는지 확인하고, 끝나면 원상복구한다.
# ---------------------------------------------------------------------------
def test_discount_structure():
    print("\n--- 4. discount structure (no hardcoding) ---")
    original = dict(PLAN_CATALOG["BASIC"]["prices"][BILLING_MONTHLY])
    try:
        # (a) 기간 한정 고정 할인
        PLAN_CATALOG["BASIC"]["prices"][BILLING_MONTHLY] = {
            "list_price": 12900, "sale_price": 9900,
            "discount_start": "2026-08-01", "discount_end": "2026-08-31",
        }
        check("within period", resolve_plan_price("BASIC", BILLING_MONTHLY, datetime(2026, 8, 15)), 9900)
        check("on end date (inclusive)", resolve_plan_price("BASIC", BILLING_MONTHLY, datetime(2026, 8, 31)), 9900)
        check("after period -> list price", resolve_plan_price("BASIC", BILLING_MONTHLY, datetime(2026, 9, 1)), 12900)
        check("before period -> list price", resolve_plan_price("BASIC", BILLING_MONTHLY, datetime(2026, 7, 31)), 12900)

        # (b) 정률 할인
        PLAN_CATALOG["BASIC"]["prices"][BILLING_MONTHLY] = {"list_price": 12900, "discount_percent": 20}
        check("percent discount 20%", resolve_plan_price("BASIC", BILLING_MONTHLY), 10320)

        # (c) 우선순위: sale_price가 discount_percent를 이긴다
        PLAN_CATALOG["BASIC"]["prices"][BILLING_MONTHLY] = {
            "list_price": 12900, "sale_price": 9900, "discount_percent": 50,
        }
        check("sale_price beats percent", resolve_plan_price("BASIC", BILLING_MONTHLY), 9900)
    finally:
        PLAN_CATALOG["BASIC"]["prices"][BILLING_MONTHLY] = original
    check("catalog restored", resolve_plan_price("BASIC", BILLING_MONTHLY), 12900)


# ---------------------------------------------------------------------------
# 3. 등기부 무료한도: 월 리셋 + 플랜별 차등 (실제 DB, 전부 롤백)
# ---------------------------------------------------------------------------
def test_monthly_reset_and_plan_limit():
    print("\n--- 5. registry free limit: monthly reset + per-plan (rolled back) ---")
    conn = get_connection()
    try:
        now = datetime.now().isoformat()
        expires = (datetime.now() + timedelta(days=30)).isoformat()
        item_id = conn.execute("SELECT id FROM auction_item LIMIT 1").fetchone()["id"]

        pro, basic, nosub = "t-pro-user", "t-basic-user", "t-nosub-user"
        for uid, plan, price in ((pro, "PRO", 22900), (basic, "BASIC", 12900)):
            conn.execute(
                "INSERT INTO subscriptions (user_id,plan,price,status,started_at,expires_at,created_at,updated_at)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (uid, plan, price, "ACTIVE", now, expires, now, now))

        check("PRO user limit", get_user_free_limit(conn, pro), 10)
        check("BASIC user limit", get_user_free_limit(conn, basic), 5)
        # 구독이 없으면 보수적 기본값으로 폴백(신청 자체는 has_active_subscription이 막는다)
        check("no-subscription fallback", get_user_free_limit(conn, nosub), DEFAULT_FREE_LIMIT)

        # 지난달 사용 3건 + 이번달 2건 -> 이번달 카운트는 2여야 한다(월 리셋)
        last_month = (datetime.now().replace(day=1) - timedelta(days=5)).isoformat()
        for _ in range(3):
            conn.execute("INSERT INTO registry_usage (user_id,item_id,is_free,charged_amount,used_at)"
                         " VALUES (?,?,?,?,?)", (pro, item_id, 1, 0, last_month))
        for _ in range(2):
            conn.execute("INSERT INTO registry_usage (user_id,item_id,is_free,charged_amount,used_at)"
                         " VALUES (?,?,?,?,?)", (pro, item_id, 1, 0, now))

        check("this month usage only", get_free_count(conn, pro), 2)
        lifetime = conn.execute(
            "SELECT COUNT(*) FROM registry_usage WHERE user_id=? AND is_free=1", (pro,)).fetchone()[0]
        check("lifetime total (old logic would use this)", lifetime, 5)
        check("month_start is 1st of month", get_month_start()[8:10], "01")
    finally:
        conn.rollback()
        conn.close()


# ---------------------------------------------------------------------------
# 4. auction_case 복합키 무결성 (Release Blocking 회귀 방지)
# ---------------------------------------------------------------------------
def test_auction_case_composite_key():
    print("\n--- 6. auction_case UNIQUE(court_code, case_no) integrity ---")
    conn = get_connection()
    try:
        schema = conn.execute(
            "SELECT sql FROM sqlite_master WHERE name='auction_case'").fetchone()[0]
        check("composite UNIQUE exists", "UNIQUE(court_code, case_no)" in schema, True)
        check("court_code not null", conn.execute(
            "SELECT COUNT(*) FROM auction_case WHERE court_code IS NULL").fetchone()[0], 0)
        check("no orphan case_id", conn.execute(
            "SELECT COUNT(*) FROM auction_item ai LEFT JOIN auction_case ac ON ai.case_id=ac.id"
            " WHERE ac.id IS NULL").fetchone()[0], 0)
        # 핵심: 물건이 연결된 사건의 법원이 물건 자신의 법원과 같아야 한다(원래 버그)
        check("no court mismatch", conn.execute(
            "SELECT COUNT(*) FROM auction_item ai JOIN auction_case ac ON ai.case_id=ac.id"
            " WHERE ac.court_code <> ai.court_name").fetchone()[0], 0)
    finally:
        conn.close()


def test_auction_identity_keys():
    """크롤러 파이프라인 전체의 식별키에 법원이 포함돼 있는지 (docs/BUGS.md #18 해결 고정).

    2026-08-06까지 auction/auction_item은 UNIQUE(case_no, item_no)로 **법원 구분이 없었다.**
    법원마다 사건번호를 독립 채번하므로, 서로 다른 법원이 같은 사건번호+물건번호를 쓰면
    매일 크롤링이 한쪽 법원의 물건을 통째로 덮어써 소실시켰다(사본 DB로 재현 확인).

    2026-08-07 Migration 012/013으로 해결했다:
      auction      -> UNIQUE(court_code, case_no, item_no)
      auction_item -> UNIQUE(case_id, item_no)   (case_id는 이미 법원이 특정된 값)

    이 테스트는 그 상태가 되돌아가지 않도록 고정한다.
    """
    print("\n--- 7. auction identity keys (docs/BUGS.md #18) ---")
    conn = get_connection()
    try:
        shared = conn.execute(
            "SELECT COUNT(*) FROM (SELECT case_no FROM auction"
            " GROUP BY case_no HAVING COUNT(DISTINCT court_code) > 1)"
        ).fetchone()[0]
        # 법원 간 사건번호 공유 자체는 정상이다(각 법원이 독립 채번하므로). 이제는 위험이
        # 아니라 단순 관측값이라 추이만 남긴다.
        print("       [INFO] 법원 간 공유 case_no: %d건 (2026-08-07 기준 3건, 이제 안전)" % shared)

        auction_sql = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='auction'").fetchone()[0]
        item_sql = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='auction_item'").fetchone()[0]
        check("auction keyed with court_code",
              "UNIQUE(court_code, case_no, item_no)" in auction_sql, True)
        check("auction no longer keyed without court",
              "UNIQUE(case_no, item_no)" in auction_sql, False)
        check("auction_item keyed by case_id", "UNIQUE(case_id, item_no)" in item_sql, True)
        check("auction_item no longer keyed by case_no only",
              "UNIQUE(case_no, item_no)" in item_sql, False)

        # 실제 데이터에도 중복이 없어야 한다.
        check("no duplicate (court,case_no,item_no) in auction", conn.execute(
            "SELECT COUNT(*) FROM (SELECT court_code, case_no, item_no FROM auction"
            " GROUP BY court_code, case_no, item_no HAVING COUNT(*) > 1)").fetchone()[0], 0)
        check("no duplicate (case_id,item_no) in auction_item", conn.execute(
            "SELECT COUNT(*) FROM (SELECT case_id, item_no FROM auction_item"
            " GROUP BY case_id, item_no HAVING COUNT(*) > 1)").fetchone()[0], 0)
    finally:
        conn.close()


def test_registry_credit_ledger():
    """등기부 무료횟수 조정 원장 (CTO 승인 6번) — 잔액 컬럼 없이 계산되는지.

    유효 한도 = 플랜 월 한도 + (이번 달 조정 합계). RESET 이후의 조정만 유효하다.
    DB를 건드리는 검사는 전부 롤백 안에서 수행한다.
    """
    print("\n--- 8. registry credit ledger ---")
    from api.v1.registry_credits import (
        add_credit, get_credit_adjustment, get_current_month,
        REASON_GRANT, REASON_DEDUCT, REASON_RESET, MAX_ADJUSTMENT,
    )
    from api.v1.registry import get_user_free_limit, get_plan_free_limit

    conn = get_connection()
    conn.isolation_level = None
    conn.execute("BEGIN")
    try:
        user = "qa-policy-credit-user"
        check("month format", len(get_current_month()), 7)
        check("no adjustment initially", get_credit_adjustment(conn, user), 0)

        base = get_plan_free_limit(conn, user)
        add_credit(conn, user, REASON_GRANT, 4, "test", "SUPER_ADMIN")
        check("GRANT adds", get_credit_adjustment(conn, user), 4)
        check("effective limit reflects grant", get_user_free_limit(conn, user), base + 4)

        add_credit(conn, user, REASON_DEDUCT, 2, "test", "SUPER_ADMIN")
        check("DEDUCT subtracts", get_credit_adjustment(conn, user), 2)

        add_credit(conn, user, REASON_RESET, 0, "test", "SUPER_ADMIN")
        check("RESET zeroes adjustment", get_credit_adjustment(conn, user), 0)

        add_credit(conn, user, REASON_GRANT, 1, "test", "SUPER_ADMIN")
        check("only post-RESET entries count", get_credit_adjustment(conn, user), 1)

        # 다른 달의 조정은 이번 달에 영향을 주지 않는다(월 리셋 정책과 동일 경계)
        check("other month isolated", get_credit_adjustment(conn, user, "1999-01"), 0)

        # 부호는 서버가 정한다 — 호출부가 음수를 넘겨 GRANT가 차감이 되는 일이 없어야 한다
        for bad in (0, -1, MAX_ADJUSTMENT + 1):
            try:
                add_credit(conn, user, REASON_GRANT, bad, None, "SUPER_ADMIN")
                check("invalid amount %s rejected" % bad, False, True)
            except ValueError:
                check("invalid amount %s rejected" % bad, True, True)
        try:
            add_credit(conn, user, "UNKNOWN", 1, None, "SUPER_ADMIN")
            check("unknown reason_type rejected", False, True)
        except ValueError:
            check("unknown reason_type rejected", True, True)
    finally:
        conn.execute("ROLLBACK")
        conn.isolation_level = ""
        conn.close()


# ---------------------------------------------------------------------------
# 9. 이용권 판정이 두 벌 존재한다 - 둘이 같은 답을 내는가 (2026-08-13 Sprint 72 신설)
#
# Dead Code 감사 중에 발견했다. "이 사용자가 지금 서비스를 쓸 수 있는가"를 판정하는 함수가
# 저장소에 두 개 있다.
#
#   api/v1/registry.py:get_entitled_subscription()
#       DB를 건드리지 않고 resolve_expected_status()로 "지금 있어야 할 상태"를 계산해 판정.
#       has_active_subscription() -> 등기부 신청 게이트가 이것을 쓴다(유일한 실사용 경로).
#
#   api/v1/subscriptions.py:get_active_subscription()
#       sync_expired_status()로 DB status를 먼저 갱신한 뒤 status IN (ACTIVE, GRACE_PERIOD)로 판정.
#       ★ 저장소 전체에서 **호출 0곳, 테스트 참조 0곳**이었다.
#
# 두 번째 함수의 docstring이 이미 "이용권 판정만 필요하면 get_entitled_subscription 쪽이 더
# 안전하다"고 적어 두었으므로 미배선 자체는 의도된 상태다. 문제는 **아무도 부르지 않고
# 아무도 검증하지 않는 판정 함수가 살아 있다**는 것이다. 나중에 누군가 이것을 쓰는 순간,
# 두 판정이 어긋나면 경로에 따라 유료 게이트의 답이 달라진다(무료한도/등기부 신청에 직결).
#
# 그래서 지금의 등가성을 회귀로 못박는다. 어느 쪽 규칙이 옳은지를 새로 정하지 않는다 -
# 지금 두 함수가 같은 답을 낸다는 사실만 고정한다.
#
# 판정 자체를 바꾸는 결정(유예 기간 길이 등)은 제품 정책이라 여기서 다루지 않는다.
# ---------------------------------------------------------------------------
def test_entitlement_judgments_agree():
    print("\n--- 9. entitlement: registry vs subscriptions must agree ---")
    from api.v1.registry import get_entitled_subscription
    from api.v1.subscriptions import get_active_subscription
    from api.v1.state_machines import GRACE_PERIOD_DAYS
    from api.constants import SubscriptionStatus

    now = datetime(2026, 6, 15, 12, 0, 0)
    user = "test-entitlement-agree-%d" % int(now.timestamp())

    def iso(days):
        return (now + timedelta(days=days)).isoformat()

    # (status, expires_at, 기대 이용권 여부, 라벨)
    grace = GRACE_PERIOD_DAYS
    cases = [
        (SubscriptionStatus.ACTIVE.value,       iso(10),            True,  "ACTIVE not yet expired"),
        (SubscriptionStatus.ACTIVE.value,       iso(-1),            True,  "ACTIVE expired within grace"),
        (SubscriptionStatus.ACTIVE.value,       iso(-(grace + 1)),  False, "ACTIVE expired past grace"),
        (SubscriptionStatus.ACTIVE.value,       None,               True,  "ACTIVE with no expiry"),
        (SubscriptionStatus.GRACE_PERIOD.value, iso(-1),            True,  "GRACE within grace"),
        (SubscriptionStatus.GRACE_PERIOD.value, iso(-(grace + 1)),  False, "GRACE past grace"),
        (SubscriptionStatus.PAUSED.value,       iso(10),            False, "PAUSED"),
        (SubscriptionStatus.CANCELLED.value,    iso(10),            False, "CANCELLED"),
        (SubscriptionStatus.EXPIRED.value,      iso(-1),            False, "EXPIRED"),
    ]

    conn = get_connection()
    try:
        for status, expires_at, expected, label in cases:
            # 각 사례를 독립 트랜잭션에서 만들고 끝나면 되돌린다 - DB에 남지 않는다.
            conn.execute("BEGIN")
            try:
                ts = now.isoformat()
                conn.execute(
                    "INSERT INTO subscriptions"
                    " (user_id,plan,price,status,started_at,expires_at,created_at,updated_at)"
                    " VALUES (?,?,?,?,?,?,?,?)",
                    (user, "BASIC", 12900, status, ts, expires_at, ts, ts),
                )

                # (1) 순수 계산 판정 - DB를 바꾸지 않으므로 먼저 본다.
                pure = get_entitled_subscription(conn, user, at=now)

                # (2) 동기화 후 판정 - status를 실제로 갱신하므로 나중에 본다.
                #     commit=False라 이 트랜잭션 롤백으로 전부 되돌아간다.
                synced = get_active_subscription(conn, user, at=now, commit=False)

                check("%s: pure entitled" % label, pure is not None, expected)
                check("%s: two judgments agree" % label,
                      (pure is not None), (synced is not None))
                if pure is not None and synced is not None:
                    check("%s: same row" % label, pure["id"], synced["id"])
            finally:
                conn.rollback()

        # 흔적이 남지 않았는지 확인한다(위 롤백이 실제로 동작했는가).
        left = conn.execute(
            "SELECT COUNT(*) FROM subscriptions WHERE user_id=?", (user,)).fetchone()[0]
        check("no rows left behind", left, 0)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 10. renew() 전 상태 매트릭스 (2026-08-13 Sprint 74 신설)
#
# `renew()`는 저장소 전체에서 **호출 0곳**이다(배선되지 않은 준비 코드). 그런데 검사는
# 딱 한 갈래뿐이었다 - test_api_regression.py §25의 "GRACE_PERIOD에서 갱신하면 ACTIVE"
# 하나. 돈을 받고 기간을 늘리는 함수인데 나머지 상태는 한 번도 확인된 적이 없다.
#
# 배선되지 않은 코드라서 지금 피해는 0이다. 문제는 배선되는 순간이다 - 아래 규칙 중
# 하나라도 어긋나면 **사용자가 산 기간을 잃거나, 해지한 구독이 되살아난다.**
#
# 여기서 고정하는 것(전부 현재 구현이 이미 가진 규칙이다. 새로 정하지 않았다):
#
#   1) 아직 만료 전이면 **기존 만료 시각에서** 이어 붙인다 (남은 기간을 잃지 않는다)
#   2) 이미 만료됐으면 **지금부터** 센다 (과거에서 더하면 갱신하자마자 또 만료된다)
#   3) CANCELLED는 갱신으로 되살아나지 않는다 (상태머신이 CANCELLED->ACTIVE를 막는다)
#   4) PAUSED / EXPIRED / GRACE_PERIOD는 갱신으로 ACTIVE가 된다
#   5) 없는 구독은 LookupError
#   6) expires_at이 깨져 있으면 지금부터 세되 **경고를 남긴다**(조용히 넘어가지 않는다)
#   7) 연속 갱신은 누적된다 (2회 갱신 = 2배 기간)
#
# 갱신 주기·가격 같은 제품 정책은 다루지 않는다. 현재 규칙의 회귀만 막는다.
# ---------------------------------------------------------------------------
def test_renew_state_matrix():
    print("\n--- 10. renew(): all states ---")
    import logging
    from api.v1.subscriptions import renew
    from api.constants import SubscriptionStatus

    now = datetime(2026, 6, 15, 12, 0, 0)
    user = "test-renew-matrix"
    PERIOD = 30

    conn = get_connection()
    try:
        def make(status, expires_at):
            ts = now.isoformat()
            return conn.execute(
                "INSERT INTO subscriptions"
                " (user_id,plan,price,status,started_at,expires_at,created_at,updated_at)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (user, "BASIC", 12900, status, ts, expires_at, ts, ts),
            ).lastrowid

        # --- (1) 아직 만료 전: 기존 만료 시각에서 이어 붙인다 ---
        conn.execute("BEGIN")
        try:
            remaining = (now + timedelta(days=10)).isoformat()
            sid = make(SubscriptionStatus.ACTIVE.value, remaining)
            res = renew(conn, sid, PERIOD, actor="TEST", at=now)
            expected = (now + timedelta(days=10 + PERIOD)).isoformat()
            check("ACTIVE not expired: extends from existing expiry",
                  res["after"]["expires_at"], expected)
            check("ACTIVE not expired: stays ACTIVE",
                  res["after"]["status"], SubscriptionStatus.ACTIVE.value)
            # 남은 10일을 잃지 않았는지 직접 확인한다(이 규칙이 깨지면 사용자가 손해다).
            check_true("ACTIVE not expired: does not lose remaining days",
                       res["after"]["expires_at"] > (now + timedelta(days=PERIOD)).isoformat())
        finally:
            conn.rollback()

        # --- (2) 이미 만료: 지금부터 센다 ---
        conn.execute("BEGIN")
        try:
            past = (now - timedelta(days=40)).isoformat()
            sid = make(SubscriptionStatus.ACTIVE.value, past)
            res = renew(conn, sid, PERIOD, actor="TEST", at=now)
            check("already expired: counts from now",
                  res["after"]["expires_at"], (now + timedelta(days=PERIOD)).isoformat())
            check_true("already expired: new expiry is in the future",
                       res["after"]["expires_at"] > now.isoformat())
        finally:
            conn.rollback()

        # --- (3) 상태별 허용/차단 ---
        for status, allowed in ((SubscriptionStatus.GRACE_PERIOD.value, True),
                                (SubscriptionStatus.PAUSED.value, True),
                                (SubscriptionStatus.EXPIRED.value, True),
                                (SubscriptionStatus.CANCELLED.value, False)):
            conn.execute("BEGIN")
            try:
                sid = make(status, (now - timedelta(days=1)).isoformat())
                raised = False
                after_status = None
                try:
                    res = renew(conn, sid, PERIOD, actor="TEST", at=now)
                    after_status = res["after"]["status"]
                except Exception:
                    raised = True
                check("renew from %s allowed" % status, not raised, allowed)
                if allowed:
                    check("renew from %s -> ACTIVE" % status,
                          after_status, SubscriptionStatus.ACTIVE.value)
                else:
                    # 차단됐다면 DB도 그대로여야 한다 - 막았는데 값이 바뀌면 의미가 없다.
                    row = conn.execute(
                        "SELECT status, expires_at FROM subscriptions WHERE id=?", (sid,)).fetchone()
                    check("blocked renew leaves status untouched", row["status"], status)
            finally:
                conn.rollback()

        # --- (4) 없는 구독 ---
        raised = False
        try:
            renew(conn, 999999999, PERIOD, actor="TEST", at=now)
        except LookupError:
            raised = True
        check("unknown subscription raises LookupError", raised, True)

        # --- (5) expires_at이 깨져 있으면 지금부터 세되 경고를 남긴다 ---
        conn.execute("BEGIN")
        try:
            sid = make(SubscriptionStatus.ACTIVE.value, "not-a-timestamp")
            records = []

            class _Capture(logging.Handler):
                def emit(self, record):
                    records.append(record.getMessage())

            lg = logging.getLogger("api.v1.subscriptions")
            handler = _Capture()
            lg.addHandler(handler)
            try:
                res = renew(conn, sid, PERIOD, actor="TEST", at=now)
            finally:
                lg.removeHandler(handler)

            check("corrupt expires_at: counts from now",
                  res["after"]["expires_at"], (now + timedelta(days=PERIOD)).isoformat())
            # 조용히 넘어가면 사용자가 잃은 기간을 아무도 모른다(Sprint 56이 남긴 규칙).
            check_true("corrupt expires_at: warns loudly",
                       any("expires_at" in m for m in records),
                       "경고 없이 폴백하면 잔여 기간 손실이 드러나지 않는다: %r" % records)
        finally:
            conn.rollback()

        # --- (6) 연속 갱신은 누적된다 ---
        conn.execute("BEGIN")
        try:
            sid = make(SubscriptionStatus.ACTIVE.value, (now + timedelta(days=1)).isoformat())
            renew(conn, sid, PERIOD, actor="TEST", at=now)
            res2 = renew(conn, sid, PERIOD, actor="TEST", at=now)
            check("consecutive renewals accumulate",
                  res2["after"]["expires_at"],
                  (now + timedelta(days=1 + PERIOD * 2)).isoformat())
        finally:
            conn.rollback()

        # 흔적이 남지 않았는지 확인한다.
        left = conn.execute(
            "SELECT COUNT(*) FROM subscriptions WHERE user_id=?", (user,)).fetchone()[0]
        check("no rows left behind", left, 0)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 11. renew() 동시 갱신 (2026-08-13 Sprint 78 신설)
#
# Sprint 74가 §10에서 renew()의 **전 상태 매트릭스**를 고정했지만 동시 갱신은 다루지
# 않았다. 그 경로가 결함이었다.
#
# renew()는 read -> compute -> write이고 write가 `WHERE id=?`뿐이었다. SELECT와 UPDATE
# 사이에 다른 갱신이 끼면 뒤엣것이 앞엣것의 연장을 통째로 덮어쓴다 — **결제 2건에
# 30일만 연장된다**(결정적으로 재현, journal_mode delete/wal 양쪽 동일).
#
#     기존 만료 +10일, 30일 갱신 2건
#       고치기 전: 30일 연장 (한 주기 소실, 예외도 경고도 없음)
#       고친 후  : 뒤엣것이 ConcurrentStatusChange로 거부 -> 재시도하면 60일 정확 누적
#
# 같은 모듈의 `change_status()`는 이미 이 가드를 갖고 있었다(2026-08-12). 돈을 받고
# 기간을 늘리는 쪽에만 없었다.
#
# 재현 방법은 스레드가 아니라 **결정적 끼워넣기**다. 이 저장소가 이미 확인한 대로
# (`test_race_conditions.py` §6/§7) 스레드 경합은 창이 좁아 가드 제거 변이를 항상 잡지
# 못한다. UPDATE 직전에 다른 커넥션의 갱신을 한 건 완주시키면 100% 재현된다.
# ---------------------------------------------------------------------------
class _InterleavingConn:
    """UPDATE subscriptions를 만나면 **그 직전에** 콜백을 한 번 실행한다.

    renew()의 SELECT와 UPDATE 사이를 결정적으로 벌리는 장치. 나머지 호출은 실제 커넥션에
    그대로 위임하므로 제품 코드는 자기가 감싸였다는 것을 모른다.
    """

    def __init__(self, real, on_first_update):
        self._real = real
        self._on_first_update = on_first_update
        self._fired = False

    def execute(self, sql, *args):
        if not self._fired and sql.strip().upper().startswith("UPDATE SUBSCRIPTIONS"):
            self._fired = True
            self._on_first_update()
        return self._real.execute(sql, *args)

    def __getattr__(self, name):
        return getattr(self._real, name)


def test_renew_concurrent_guard():
    print("\n--- 11. renew(): concurrent renewal guard ---")
    from api.v1.subscriptions import renew, ConcurrentStatusChange
    from api.constants import SubscriptionStatus

    now = datetime(2026, 6, 15, 12, 0, 0)
    base_expiry = now + timedelta(days=10)
    user = "test-renew-race"
    PERIOD = 30

    # 두 커넥션이 필요하므로 롤백 트랜잭션 하나에 담을 수 없다 —
    # 커밋된 상태가 서로 보여야 경합이 성립한다. 대신 finally에서 이 user의 행만 지운다.
    a = get_connection()
    b = get_connection()
    seed = get_connection()
    try:
        ts = now.isoformat()
        sid = seed.execute(
            "INSERT INTO subscriptions"
            " (user_id,plan,price,status,started_at,expires_at,created_at,updated_at)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (user, "BASIC", 12900, SubscriptionStatus.ACTIVE.value, ts,
             base_expiry.isoformat(), ts, ts),
        ).lastrowid
        seed.commit()

        b_ok = {}

        def b_renews():
            renew(b, sid, PERIOD, actor="B", at=now)
            b.commit()
            b_ok["done"] = True

        conflict = None
        try:
            renew(_InterleavingConn(a, b_renews), sid, PERIOD, actor="A", at=now)
            a.commit()
        except ConcurrentStatusChange as exc:
            conflict = exc
        except Exception as exc:  # noqa: BLE001 - 다른 예외가 나면 그 자체가 실패 정보다
            conflict = exc

        check_true("끼워넣은 갱신(B)은 정상 완주한다", b_ok.get("done") is True, b_ok)
        check_true("겹친 갱신(A)은 조용히 덮어쓰지 않고 거부된다",
                   isinstance(conflict, ConcurrentStatusChange),
                   "예외 없음(=덮어씀)" if conflict is None else repr(conflict))

        # ★ 거부된 뒤에는 **호출부가** 롤백해야 한다. `renew()`는 트랜잭션을 소유하지
        # 않으므로(호출부가 BEGIN한다) 여기서 rollback하면 호출부의 다른 작업까지 지운다.
        # 롤백하지 않으면 실패한 UPDATE가 열어 둔 쓰기 트랜잭션이 남아 다음 쓰기가
        # `database is locked`로 막힌다 — 이 테스트를 쓰다 실제로 그렇게 막혔고,
        # 그 사실이 곧 호출부 계약이다(재시도 전에 롤백).
        a.rollback()

        def expiry_of():
            return seed.execute(
                "SELECT expires_at FROM subscriptions WHERE id=?", (sid,)).fetchone()["expires_at"]

        # 거부 시점에는 B의 한 주기만 반영돼 있어야 한다(A가 덮어쓰지 않았다는 증거).
        check("거부 후에는 B의 연장만 남는다", expiry_of(),
              (base_expiry + timedelta(days=PERIOD)).isoformat())

        # ★ 거부로 끝나면 사용자는 여전히 한 주기를 못 받는다. 계약은 "거부 + 재시도"이므로
        # 재시도가 실제로 누적되는지까지 봐야 이 검사가 의미를 갖는다.
        renew(a, sid, PERIOD, actor="A-retry", at=now)
        a.commit()
        check("재시도하면 두 주기가 정확히 누적된다", expiry_of(),
              (base_expiry + timedelta(days=PERIOD * 2)).isoformat())

        # 상태 변경과의 경합도 같은 가드가 잡아야 한다 — 해지된 구독이 갱신으로 되살아나면
        # 안 된다(§10 (3)이 순차 경로에서 막은 것을 동시 경로에서도 확인한다).
        def b_cancels():
            from api.v1.subscriptions import change_status
            change_status(b, sid, SubscriptionStatus.CANCELLED.value, actor="B", at=now)
            b.commit()

        cancel_conflict = None
        try:
            renew(_InterleavingConn(a, b_cancels), sid, PERIOD, actor="A", at=now)
            a.commit()
        except Exception as exc:  # noqa: BLE001
            cancel_conflict = exc
        check_true("갱신 중 해지가 끼면 갱신이 거부된다",
                   isinstance(cancel_conflict, ConcurrentStatusChange),
                   "예외 없음(=해지된 구독이 갱신됨)" if cancel_conflict is None
                   else repr(cancel_conflict))
        row = seed.execute(
            "SELECT status FROM subscriptions WHERE id=?", (sid,)).fetchone()
        check("해지 상태가 갱신으로 되살아나지 않는다", row["status"],
              SubscriptionStatus.CANCELLED.value)
        a.rollback()   # 위와 같은 이유 — 거부된 트랜잭션을 닫는다

        # 무기한 구독(expires_at IS NULL)도 갱신될 수 있어야 한다 —
        # WHERE에 `= ?`를 쓰면 `NULL = NULL`이 참이 아니라서 **항상** 충돌로 오판된다.
        nid = seed.execute(
            "INSERT INTO subscriptions"
            " (user_id,plan,price,status,started_at,expires_at,created_at,updated_at)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (user, "BASIC", 12900, SubscriptionStatus.ACTIVE.value, ts, None, ts, ts),
        ).lastrowid
        seed.commit()
        null_error = None
        try:
            renew(a, nid, PERIOD, actor="A", at=now)
            a.commit()
        except Exception as exc:  # noqa: BLE001
            null_error = exc
        check_true("expires_at이 NULL인 구독도 갱신된다(NULL 비교 함정)",
                   null_error is None, repr(null_error))
        null_row = seed.execute(
            "SELECT expires_at FROM subscriptions WHERE id=?", (nid,)).fetchone()
        check("NULL 만료는 지금부터 센다", null_row["expires_at"],
              (now + timedelta(days=PERIOD)).isoformat())
    finally:
        for c in (a, b):
            try:
                c.rollback()
            except Exception:  # noqa: BLE001
                pass
            c.close()
        seed.execute("DELETE FROM subscriptions WHERE user_id=?", (user,))
        seed.commit()
        left = seed.execute(
            "SELECT COUNT(*) FROM subscriptions WHERE user_id=?", (user,)).fetchone()[0]
        check("no rows left behind (race test)", left, 0)
        seed.close()


def run():
    test_plan_prices()
    test_registry_limits()
    test_invalid_combinations()
    test_discount_structure()
    test_monthly_reset_and_plan_limit()
    test_auction_case_composite_key()
    test_auction_identity_keys()
    test_registry_credit_ledger()
    test_entitlement_judgments_agree()
    test_renew_state_matrix()
    test_renew_concurrent_guard()

    print("\n" + "=" * 55)
    if failures:
        print("FAILED (%d): %s" % (len(failures), ", ".join(failures)))
        return 1
    print("ALL TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(run())
