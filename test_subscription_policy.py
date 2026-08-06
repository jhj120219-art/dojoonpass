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


def run():
    test_plan_prices()
    test_registry_limits()
    test_invalid_combinations()
    test_discount_structure()
    test_monthly_reset_and_plan_limit()
    test_auction_case_composite_key()

    print("\n" + "=" * 55)
    if failures:
        print("FAILED (%d): %s" % (len(failures), ", ".join(failures)))
        return 1
    print("ALL TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(run())
