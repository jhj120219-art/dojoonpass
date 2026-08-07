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


def run():
    test_plan_prices()
    test_registry_limits()
    test_invalid_combinations()
    test_discount_structure()
    test_monthly_reset_and_plan_limit()
    test_auction_case_composite_key()
    test_auction_identity_keys()
    test_registry_credit_ledger()

    print("\n" + "=" * 55)
    if failures:
        print("FAILED (%d): %s" % (len(failures), ", ".join(failures)))
        return 1
    print("ALL TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(run())
