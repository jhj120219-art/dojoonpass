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

        # ★ 2026-08-26 (BUGS #227 과 같은 부류) — 이 월 경계 판정은 `used_at` 을
        #   **문자열로** 비교한다(`used_at >= month_start`). ISO 8601 은 사전순 == 시간순이라
        #   맞는데, 그것은 **모든 쓰기가 `datetime.now().isoformat()` 형식일 때만** 참이다.
        #
        #   위험을 실제로 재 둔다: SQLite 의 `CURRENT_TIMESTAMP` 처럼 'T' 대신 **공백**을
        #   쓰면 어떻게 되는가.
        #
        #   ★ 처음에는 "오늘"로 넣어 보고 아무 일도 안 일어나 검사를 잘못 썼다고 알았다.
        #     구분자는 **날짜 부분이 같을 때만** 비교에 닿는다 — 즉 위험한 날은
        #     **매월 1일**뿐이다(그날 사용은 월초 자정과 날짜가 같다).
        #     좁지만 실재하고, 하필 조용하다: 그날 쓴 무료 열람이 한 건도 세어지지 않아
        #     한도가 그만큼 더 열린다.
        first_space = datetime.now().replace(day=1, hour=12, minute=0, second=0,
                                             microsecond=0).isoformat(sep=" ")
        conn.execute("INSERT INTO registry_usage (user_id,item_id,is_free,charged_amount,used_at)"
                     " VALUES (?,?,?,?,?)", ("t-fmt-user", item_id, 1, 0, first_space))
        check_true("★ 1일에 공백 구분으로 쓰면 이번 달 사용으로 세어지지 않는다(형식이 계약인 이유)",
                   get_free_count(conn, "t-fmt-user") == 0,
                   "-> %r vs 월초 %r" % (first_space, get_month_start()))
        # 같은 시각을 규정 형식('T')으로 쓰면 정상적으로 세어진다 — 차이가 구분자 하나임을 못박는다.
        conn.execute("INSERT INTO registry_usage (user_id,item_id,is_free,charged_amount,used_at)"
                     " VALUES (?,?,?,?,?)",
                     ("t-fmt-ok", item_id, 1, 0, first_space.replace(" ", "T")))
        check("같은 시각을 'T' 형식으로 쓰면 세어진다", get_free_count(conn, "t-fmt-ok"), 1)

        #   그래서 **쓰는 곳이 하나이고 그 형식인지**를 소스로 고정한다.
        reg_src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                    "api", "v1", "registry.py"), encoding="utf-8-sig").read()
        inserts = [ln for ln in reg_src.splitlines()
                   if "INSERT INTO registry_usage" in ln and not ln.strip().startswith("#")]
        check("registry_usage 를 쓰는 곳은 한 곳이다", len(inserts), 1)
        check_true("그 한 곳이 datetime.now().isoformat() 형식을 쓴다",
                   "now = datetime.now().isoformat()" in reg_src,
                   "-> 다른 형식으로 쓰기 시작하면 월 경계 판정이 조용히 틀린다")
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


# ---------------------------------------------------------------------------
# 두 곳의 `row_to_subscription()` 이 같은 기본 필드를 낸다 (2026-08-14 신설)
#
# 같은 이름의 직렬화 함수가 **두 라이브 API 파일에 각각** 정의돼 있다.
#
#     api/v1/payments.py:row_to_subscription()       기본 9필드
#     api/v1/subscriptions.py:row_to_subscription()  같은 9필드 + 파생 3필드
#
# 후자의 docstring 이 약속한다 —
#   "기존 payments.py:row_to_subscription과 필드가 동일하고, 상태 해석에 필요한
#    파생 필드만 추가한다(기존 필드는 하나도 바꾸지 않는다)"
#
# 그런데 **그 약속을 강제하는 것이 없다.** 한쪽에만 필드를 추가하거나 이름을 바꾸면
# 같은 구독이 **어느 엔드포인트로 받았느냐에 따라 다르게 보인다.**
# 프런트는 두 응답을 같은 타입으로 다루므로(`src/app/mypage` / `properties/[id]`),
# 그 차이는 화면에서 `undefined` 로 나타난다.
#
# 이 저장소는 같은 부류를 이미 한 번 겪었다 — `api/v1/admin.py` 의
# `_require_existing_registry_document()` 도 "다운로드 경로와 똑같이 맞춘다"고
# 적어 두고 실제로는 어긋나 있었다(Sprint 104). 약속은 검사로 고정해야 남는다.
# ---------------------------------------------------------------------------
def test_row_to_subscription_shapes_agree():
    print("\n--- row_to_subscription: 두 구현의 기본 필드 일치 ---")
    import api.v1.payments as pay_mod
    import api.v1.subscriptions as sub_mod

    # 실제 컬럼 이름으로 만든 가짜 행 하나로 두 함수를 모두 태운다.
    row = {
        "id": 1, "user_id": "qa-shape", "plan": "BASIC", "price": 12900,
        "status": "ACTIVE",
        "started_at": "2026-08-01T00:00:00",
        "expires_at": "2026-09-01T00:00:00",
        "created_at": "2026-08-01T00:00:00",
        "updated_at": "2026-08-01T00:00:00",
    }

    a = pay_mod.row_to_subscription(row)
    b = sub_mod.row_to_subscription(row)

    base = set(a)
    derived = set(b) - base
    check_true("payments 쪽이 필드를 낸다", len(base) > 0, sorted(base))
    check("subscriptions 는 payments 의 모든 필드를 포함한다", sorted(base - set(b)), [])
    # 값도 같아야 한다 — 이름만 같고 값이 달라지면 더 나쁘다.
    differing = sorted(k for k in base if a[k] != b[k])
    check("공통 필드의 값이 같다", differing, [])
    print("    공통 %d필드 / subscriptions 전용 파생 %d필드: %s"
          % (len(base), len(derived), sorted(derived)))

    # 파생 필드는 **subscriptions 쪽에만** 있어야 한다(payments 가 상태 해석을 흉내내기
    # 시작하면 두 곳에서 만료 판정이 갈린다 — resolve_expected_status 가 단일 기준이다).
    check_true("파생 필드가 실제로 추가돼 있다", len(derived) > 0, sorted(derived))
    for k in ("effective_status", "is_entitled", "grace_period_end"):
        check_true("subscriptions 가 %s 를 낸다" % k, k in b, sorted(b))
        check_true("payments 는 %s 를 내지 않는다(판정은 한 곳에서)" % k, k not in a, sorted(a))


def test_every_plan_prices_every_billing_cycle():
    """모든 `VALID_PLANS` x `VALID_BILLING_CYCLES` 조합에 가격이 있는가 (2026-08-24 Sprint 253).

    ## 왜 이 검사가 생겼나 — 커버리지 구멍에서 시작했다

    `api/v1/payments.py` 는 96% 커버리지인데 미실행 14줄이 전부 오류/롤백 분기였다.
    그중 350행이 눈에 걸렸다:

        expected_amount = resolve_plan_price(req.plan, billing_cycle)
        if expected_amount is None:
            return error_response(ErrorCode.PAY_INVALID_PLAN, "구독 플랜이 올바르지 않습니다")

    바로 위에서 `req.plan not in VALID_PLANS` 를 이미 걸렀는데 **또** 플랜 오류를 낸다.
    즉 "플랜 목록은 통과했지만 가격이 없는" 상태를 위한 방어다. 실제로 그런 상태가 될 수
    있는가를 확인했다:

        VALID_PLANS          = tuple(PLAN_CATALOG.keys())          <- 카탈로그에서 파생(단일 소스)
        VALID_BILLING_CYCLES = (MONTHLY, YEARLY)                   <- **독립 리터럴**

    앞쪽은 파생이라 어긋날 수 없다. 뒤쪽은 아니다 — 새 플랜을 추가하면서 `prices` 에
    `YEARLY` 를 빼먹으면, 플랜 검사는 통과하고 가격만 None 이 된다. 그때 사용자가 보는
    문구는 **"구독 플랜이 올바르지 않습니다"** 다. 가격표에 구멍이 난 것인데 사용자에게는
    플랜을 잘못 고른 것처럼 안내된다 — 이 저장소가 반복해서 잡아 온 "사실과 다른 안내"다.

    2026-08-24 실측: 4개 조합(BASIC/PRO x MONTHLY/YEARLY) 전부 가격이 있다.
    그래서 지금 350행은 **도달 불가**다. 그 상태를 못 박는다 — 도달 가능해지는 순간
    이 검사가 먼저 실패해서, 사용자가 잘못된 안내를 받기 전에 드러난다.
    """
    print("\n--- 플랜 x 결제주기 가격 완전성 (Sprint 253) ---")
    from api.v1.payments import (PLAN_CATALOG, VALID_PLANS, VALID_BILLING_CYCLES,
                                 resolve_plan_price)

    check_true("검사가 공허하지 않다(플랜/주기를 실제로 읽었다)",
               len(VALID_PLANS) >= 1 and len(VALID_BILLING_CYCLES) >= 1,
               (VALID_PLANS, VALID_BILLING_CYCLES))
    check("VALID_PLANS 는 카탈로그에서 파생된다(하드코딩 사본 아님)",
          sorted(VALID_PLANS), sorted(PLAN_CATALOG.keys()))

    gaps = []
    for plan in VALID_PLANS:
        for cycle in VALID_BILLING_CYCLES:
            price = resolve_plan_price(plan, cycle)
            if price is None or price <= 0:
                gaps.append("%s/%s=%r" % (plan, cycle, price))
    check("★ 가격이 없는 (플랜, 결제주기) 조합", sorted(gaps), [])
    if gaps:
        print("      -> 이 조합을 고른 사용자는 '구독 플랜이 올바르지 않습니다'를 본다."
              " 플랜이 아니라 **가격표**가 빈 것이다(payments.py:350)")
    print("    조합 %d개 전부 가격 있음" % (len(VALID_PLANS) * len(VALID_BILLING_CYCLES)))



# ---------------------------------------------------------------------------
# 가격표가 **조용히 틀린 금액을 만들 수 있는가** (2026-08-26, `docs/BUGS.md` #227)
# ---------------------------------------------------------------------------
def test_plan_catalog_rejects_silent_money_errors():
    """`PLAN_CATALOG` 는 프로그래머가 아닌 사람이 고치는 것을 전제로 한 표다.

    위 `PLAN_CATALOG` 주석이 그 의도를 직접 적고 있다 —
    *"향후 할인 이벤트를 붙일 때 이 카탈로그의 값만 바꾸면 되고 결제/검증 로직은
    손대지 않아도 된다."* 그렇다면 **그 표에 잘못 적힌 값이 조용히 금액을 바꾸면 안 된다.**

    ## 무엇이 틀려 있었나

    할인 기간 판정이 날짜를 **문자열로 비교**했다(`today < start`). `YYYY-MM-DD` 로
    영점을 채웠을 때만 맞는 방식이라, 월을 한 자리로 적으면 두 방향 모두 조용히 틀렸다.

        discount_end   "2026-9-1"  + 오늘 2026-10-05 -> 할인이 **끝나지 않는다**
                                                        (274,800 받을 것을 198,000 만 받는다)
        discount_start "2026-9-1"  + 오늘 2026-09-15 -> 할인이 **시작되지 않는다**

    오류도 로그도 없이 금액만 달라진다. 지금 카탈로그에는 기간이 걸린 항목이 없어
    드러나지 않았을 뿐, 이벤트를 하나 붙이는 순간 성립한다.

    ## 이 검사가 잠그는 것

    날짜 형식만 보지 않는다. 같은 표에 있는 다른 값들도 어긋나면 똑같이 조용히
    금액을 바꾸므로 함께 못박는다(할인가가 정상가보다 비싼 경우 등).
    """
    print("\n--- 4-b. 가격표의 조용한 금액 오류 (BUGS #227) ---")
    import ast as _ast
    import copy as _copy
    import io as _io
    import os as _os
    from api.v1.payments import validate_plan_catalog, _is_discount_active

    # (0) 전제 — 지금 쓰는 진짜 카탈로그는 통과해야 한다.
    #     이게 없으면 아래 "거부한다" 검사들이 전부 참이어도 아무 의미가 없다.
    try:
        validate_plan_catalog(PLAN_CATALOG)
        ok, why = True, ""
    except ValueError as exc:
        ok, why = False, str(exc)
    check_true("전제: 실제 PLAN_CATALOG 는 검증을 통과한다", ok, why)

    def rejects(label, mutate):
        """카탈로그 사본을 망가뜨려 검증이 **거부하는지** 본다(원본은 건드리지 않는다)."""
        cat = _copy.deepcopy(PLAN_CATALOG)
        mutate(cat)
        try:
            validate_plan_catalog(cat)
            check_true("거부한다: %s" % label, False, "-> 통과해 버렸다")
        except ValueError as exc:
            check_true("거부한다: %s" % label, True, str(exc)[:70])

    def price_of(cat, plan="BASIC", cycle=None):
        return cat[plan]["prices"][cycle or BILLING_MONTHLY]

    # (1) ★ 실제로 겪은 결함 — 월/일을 한 자리로 적은 날짜
    rejects("discount_end 의 월이 한 자리('2026-9-1')",
            lambda c: price_of(c).update({"discount_end": "2026-9-1"}))
    rejects("discount_start 의 월이 한 자리('2026-9-1')",
            lambda c: price_of(c).update({"discount_start": "2026-9-1"}))
    rejects("일이 한 자리('2026-09-1')",
            lambda c: price_of(c).update({"discount_end": "2026-09-1"}))
    rejects("슬래시 표기('2026/09/01')",
            lambda c: price_of(c).update({"discount_start": "2026/09/01"}))
    rejects("날짜가 아닌 값",
            lambda c: price_of(c).update({"discount_end": "곧 종료"}))
    # ★ 파이썬 3.11+ 의 `date.fromisoformat` 은 대시 없는 기본 형식도 받아들인다.
    #   그 값은 **날짜로는 유효한데 사전순 비교와 시간순 비교가 갈린다**
    #   ("2026-09-15" < "20260901" 이 참이다). 문서가 약속한 형식만 받게 못박는다.
    rejects("대시 없는 기본 형식('20260901')",
            lambda c: price_of(c).update({"discount_start": "20260901"}))
    rejects("날짜에 시각이 붙은 값('2026-09-01T00:00:00')",
            lambda c: price_of(c).update({"discount_end": "2026-09-01T00:00:00"}))
    rejects("날짜가 문자열이 아니다",
            lambda c: price_of(c).update({"discount_end": 20260901}))

    # (2) 뒤집힌 기간 — 할인이 영원히 적용되지 않는다(조용한 실패)
    rejects("시작일이 종료일보다 늦다",
            lambda c: price_of(c).update({"discount_start": "2026-10-01",
                                          "discount_end": "2026-09-01"}))

    # (3) 금액 자체가 어긋나는 경우
    rejects("sale_price 가 list_price 보다 비싸다(할인이라며 더 받는다)",
            lambda c: price_of(c).update({"sale_price": 99000}))
    rejects("sale_price 가 0 이하",
            lambda c: price_of(c).update({"sale_price": 0}))
    rejects("list_price 가 0 이하",
            lambda c: price_of(c).update({"list_price": 0}))
    rejects("discount_percent 가 100 이상(금액이 0 이하가 된다)",
            lambda c: price_of(c).update({"discount_percent": 100}))
    rejects("discount_percent 가 0 이하",
            lambda c: price_of(c).update({"discount_percent": 0}))

    # (4) 정상 값은 **거부하지 않는다** — 과잉 방어면 이벤트를 못 건다.
    for label, patch in [
        ("기간이 없는 상시 할인", {"sale_price": 9900}),
        ("정상 표기 기간", {"sale_price": 9900,
                        "discount_start": "2026-09-01", "discount_end": "2026-09-30"}),
        ("시작만 지정", {"sale_price": 9900, "discount_start": "2026-09-01"}),
        ("종료만 지정", {"sale_price": 9900, "discount_end": "2026-09-30"}),
        ("정률 할인", {"discount_percent": 20}),
    ]:
        cat = _copy.deepcopy(PLAN_CATALOG)
        entry = price_of(cat)
        entry.pop("sale_price", None)
        entry.update(patch)
        try:
            validate_plan_catalog(cat)
            check_true("정상 값은 통과한다: %s" % label, True)
        except ValueError as exc:
            check_true("정상 값은 통과한다: %s" % label, False, str(exc)[:70])

    # (5) 경계 — 시작일/종료일 **당일은 포함**한다(기존 규약을 그대로 유지한다)
    check("종료일 당일은 할인 적용",
          _is_discount_active({"discount_end": "2026-09-30"}, datetime(2026, 9, 30)), True)
    check("종료일 다음 날은 정상가",
          _is_discount_active({"discount_end": "2026-09-30"}, datetime(2026, 10, 1)), False)
    check("시작일 당일은 할인 적용",
          _is_discount_active({"discount_start": "2026-09-01"}, datetime(2026, 9, 1)), True)
    check("시작일 전날은 정상가",
          _is_discount_active({"discount_start": "2026-09-01"}, datetime(2026, 8, 31)), False)

    # (6) ★ 가드가 **실제로 불리는가** — 정의만 해 두면 아무것도 지키지 못한다.
    #     문자열 grep 이 아니라 구문 트리로 본다(주석에 이름이 나오는 것은 호출이 아니다).
    src = _io.open(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)),
                                 "api", "v1", "payments.py"), encoding="utf-8-sig").read()
    tree = _ast.parse(src)
    called_at_import = any(
        isinstance(node, _ast.Expr) and isinstance(node.value, _ast.Call)
        and getattr(node.value.func, "id", None) == "validate_plan_catalog"
        for node in tree.body        # 모듈 최상단에서 부르는 것만 센다
    )
    check_true("★ 모듈 최상단에서 validate_plan_catalog() 를 실제로 부른다",
               called_at_import,
               "-> 정의만 있고 호출이 없으면 잘못된 표가 그대로 배포된다")




# 구독 상태를 바꿔도 되는 유일한 자리. 이 목록을 늘리려면 그 파일이 전이 검증을
# 스스로 해야 한다(`assert_subscription_transition` + 조건부 UPDATE + rowcount 확인).
SUBSCRIPTION_STATUS_WRITERS = {"api/v1/subscriptions.py"}


def test_only_one_module_updates_subscription_status():
    """구독 상태 UPDATE 가 상태머신을 우회하지 않는가 (2026-09-01 신설).

    ## 왜 필요한가 - 지금 지키는 것이 관례뿐이다

    구독 상태 전이는 `subscriptions.py:change_status()` 하나가 담당한다. 그 함수는
    `assert_subscription_transition()` 으로 전이를 검증하고, **읽었던 상태를 WHERE 에
    다시 걸어**(조건부 UPDATE + rowcount) 경합을 막고, 만료된 구독을 되살릴 때
    새 `expires_at` 을 요구한다(`ReactivationRequiresNewExpiry`).

    실측(2026-09-01) 결과 지금은 아무도 우회하지 않는다 -
    `admin.py` 는 `change_status()` 를 부르고, `payments.py` 는 **INSERT 만** 한다
    (새 구독 생성은 이전 상태가 없으므로 전이 검증 대상이 아니다).

    그런데 그것을 지키는 검사가 없었다. 누가 다른 모듈에서

        UPDATE subscriptions SET status='ACTIVE' WHERE id=?

    를 한 줄 적으면 전이 검증도, 경합 가드도, 재활성화 시 만료일 요구도 **전부**
    건너뛴다. 그리고 그것은 돈을 받는 쪽 상태라서, 틀려도 예외가 아니라
    **잘못된 이용 권한**으로 나타난다.

    ★ INSERT 는 대상이 아니다 - 생성에는 이전 상태가 없다. 여기서 보는 것은
      **이미 있는 행의 status 를 바꾸는 UPDATE** 뿐이다.
    """
    import ast
    import re
    import subprocess as _sp

    print("\n--- 구독 상태 UPDATE 가 한 모듈에만 있는가 ---")
    root = os.path.dirname(os.path.abspath(__file__))
    try:
        out = _sp.run(["git", "ls-files", "*.py"], cwd=root,
                      capture_output=True, text=True, timeout=30)
    except (OSError, _sp.SubprocessError) as exc:
        print("   [SKIP] git 을 실행할 수 없다 (%s)" % type(exc).__name__)
        return
    if out.returncode != 0:
        print("   [SKIP] git 저장소가 아니다")
        return

    rels = [p for p in out.stdout.split()
            if p.endswith(".py") and "-DESKTOP-" not in p
            and not os.path.basename(p).startswith("test_")]
    check_true("검사가 공허하지 않다(제품 .py 를 찾았다) - %d개" % len(rels), len(rels) >= 40)

    # `UPDATE subscriptions ... SET ... status ...` 형태. 주석/독스트링은 제외한다.
    upd = re.compile(r"UPDATE\s+subscriptions\b[^;]*?\bSET\b[^;]*?\bstatus\s*=", re.I | re.S)
    offenders = []
    for rel in rels:
        if rel in SUBSCRIPTION_STATUS_WRITERS:
            continue
        try:
            src = open(os.path.join(root, rel.replace("/", os.sep)),
                       encoding="utf-8-sig").read()
        except OSError:
            continue
        # 문자열 상수만 본다 - 주석/설명문에 적힌 것은 결함이 아니다.
        # AST 로 뽑으면 중쿠표 중첩을 걱정할 필요가 없다
        # (정규식으로 리터럴을 직접 걱어내려다 한 번 틀렸다).
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Constant):
                continue
            if isinstance(node.value, str) and upd.search(node.value):
                offenders.append("%s:%d" % (rel, node.lineno))
                break
    check("★ subscriptions.status 를 직접 UPDATE 하는 다른 모듈", sorted(offenders), [])
    if offenders:
        print("      -> change_status() 를 쓰라. 직접 UPDATE 하면 전이 검증/경합 가드/"
              "재활성화 만료일 요구를 전부 건너뛴다")

    # 정본이 실제로 그 UPDATE 를 갖고 있는가(있어야 위 검사가 의미를 갖는다).
    owner = open(os.path.join(root, "api", "v1", "subscriptions.py"),
                 encoding="utf-8-sig").read()
    check_true("정본(subscriptions.py)이 status UPDATE 를 갖고 있다",
               bool(upd.search(owner)))
    check_true("정본이 전이 검증을 부른다",
               "assert_subscription_transition" in owner)

    # 자기 검증: 탐지기가 실제로 그 모양을 잡는가.
    check_true("자기 검증: 직접 UPDATE 문자열을 잡는다",
               bool(upd.search("UPDATE subscriptions SET status=?, updated_at=? WHERE id=?")))
    check_true("자기 검증: INSERT 는 잡지 않는다",
               not upd.search("INSERT INTO subscriptions (user_id, status) VALUES (?,?)"))


def run():
    test_row_to_subscription_shapes_agree()
    test_plan_prices()
    test_registry_limits()
    test_invalid_combinations()
    test_every_plan_prices_every_billing_cycle()
    test_discount_structure()
    test_plan_catalog_rejects_silent_money_errors()
    test_monthly_reset_and_plan_limit()
    test_auction_case_composite_key()
    test_auction_identity_keys()
    test_registry_credit_ledger()
    test_entitlement_judgments_agree()
    test_renew_state_matrix()
    test_renew_concurrent_guard()
    test_only_one_module_updates_subscription_status()

    print("\n" + "=" * 55)
    if failures:
        print("FAILED (%d): %s" % (len(failures), ", ".join(failures)))
        return 1
    print("ALL TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(run())
