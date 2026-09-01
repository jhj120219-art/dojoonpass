"""
등기부 무료 횟수 조정 원장(api/v1/registry_credits.py) 순수 로직 회귀 테스트.

api/v1/registry_credits.py는 api.constants만 import하고 api.auth(jose 의존)를 타지 않으므로,
python-jose가 없는 이 환경(2026-08-08 기준)에서도 실행 가능하다 — test_api_regression.py/
test_subscription_policy.py가 이 환경에서 막혀 있는 만큼, 그 두 파일이 이미 계획하고 있던
"등기부 credit 원장" 검증(RESET 이후 합산 규칙, 조정 한도)을 이 파일이 대신 커버한다.

DB는 임시 in-memory SQLite에 이 모듈이 실제로 사용하는 컬럼만으로 최소 테이블을 만들어 쓴다
(운영 DB의 실제 마이그레이션 스키마를 대체하지 않는다 — 순수 로직 검증용 fixture일 뿐이며,
운영 auction.db는 이 테스트가 열지도, 쓰지도 않는다).

    python test_registry_credits.py

콘솔 인코딩(cp949) 문제를 피하려고 출력은 ASCII만 사용한다.
"""
import sys
import os
import sqlite3

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from api.v1.registry_credits import (
    add_credit, get_credit_adjustment, log_credit_event, get_credit_logs,
    get_current_month, REASON_GRANT, REASON_DEDUCT, REASON_RESET, MAX_ADJUSTMENT,
)

failures = []


def check(name, actual, expected):
    ok = actual == expected
    print("[%s] %s: %r (expected %r)" % ("PASS" if ok else "FAIL", name, actual, expected))
    if not ok:
        failures.append(name)


def check_raises(name, fn, exc_type=ValueError):
    try:
        fn()
        check(name, False, True)
    except exc_type:
        check(name, True, True)


def make_conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE registry_credits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            reason_type TEXT NOT NULL,
            amount INTEGER NOT NULL,
            reason TEXT,
            effective_month TEXT NOT NULL,
            created_by TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE registry_credit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            reason_type TEXT NOT NULL,
            delta INTEGER NOT NULL,
            balance_after INTEGER,
            reason TEXT,
            effective_month TEXT NOT NULL,
            actor TEXT NOT NULL,
            related_credit_id INTEGER,
            related_usage_id INTEGER,
            created_at TEXT NOT NULL
        )
    """)
    return conn


def test_grant_and_deduct_sum():
    print("\n--- 1. GRANT/DEDUCT sign normalization and sum ---")
    conn = make_conn()
    # 고정하면 해가 바뀔 때 검사가 조용히 무력해진다. add_credit() 은 at 을 안 주면
    #   **지금 달**로 쓰는데 여기만 "2026-08" 로 읽어
    #   2026-09-01 KST 로 넘어가는 순간 실패했다.
    #   0 을 기대하는 RESET 검사는 틀린 달에서도 0 이라 **거짓 통과**했다.
    month = get_current_month()
    add_credit(conn, "u1", REASON_GRANT, 3, "cs", "ADMIN")
    check("after GRANT 3", get_credit_adjustment(conn, "u1", month), 3)
    add_credit(conn, "u1", REASON_DEDUCT, 1, "cs", "ADMIN")
    check("after DEDUCT 1", get_credit_adjustment(conn, "u1", month), 2)
    add_credit(conn, "u1", REASON_GRANT, 5, "cs", "ADMIN")
    check("after GRANT 5 more", get_credit_adjustment(conn, "u1", month), 7)

    # amount는 항상 양수로 받고 부호는 reason_type이 정한다 — DB에 실제로 음수/양수가
    # 맞게 저장됐는지 확인한다.
    rows = conn.execute(
        "SELECT reason_type, amount FROM registry_credits WHERE user_id='u1' ORDER BY id"
    ).fetchall()
    check("stored amounts have correct signs",
          [(r["reason_type"], r["amount"]) for r in rows],
          [(REASON_GRANT, 3), (REASON_DEDUCT, -1), (REASON_GRANT, 5)])


def test_reset_cuts_off_prior_adjustments():
    print("\n--- 2. RESET cuts off prior adjustments ---")
    conn = make_conn()
    # 고정하면 해가 바뀔 때 검사가 조용히 무력해진다. add_credit() 은 at 을 안 주면
    #   **지금 달**로 쓰는데 여기만 "2026-08" 로 읽어
    #   2026-09-01 KST 로 넘어가는 순간 실패했다.
    #   0 을 기대하는 RESET 검사는 틀린 달에서도 0 이라 **거짓 통과**했다.
    month = get_current_month()
    add_credit(conn, "u2", REASON_GRANT, 10, None, "ADMIN")
    check("before RESET", get_credit_adjustment(conn, "u2", month), 10)

    add_credit(conn, "u2", REASON_RESET, 0, "CS correction", "SUPER_ADMIN")
    check("immediately after RESET", get_credit_adjustment(conn, "u2", month), 0)

    add_credit(conn, "u2", REASON_GRANT, 2, None, "ADMIN")
    check("GRANT after RESET only counts new amount", get_credit_adjustment(conn, "u2", month), 2)

    # 두 번째 RESET도 그 이전 조정을 다시 무효화해야 한다
    add_credit(conn, "u2", REASON_DEDUCT, 1, None, "ADMIN")
    add_credit(conn, "u2", REASON_RESET, 0, None, "SUPER_ADMIN")
    check("second RESET clears again", get_credit_adjustment(conn, "u2", month), 0)


def test_month_isolation():
    print("\n--- 3. month isolation (adjustments do not leak across months) ---")
    conn = make_conn()
    add_credit(conn, "u3", REASON_GRANT, 4, None, "ADMIN", at=__import__("datetime").datetime(2026, 7, 15))
    add_credit(conn, "u3", REASON_GRANT, 9, None, "ADMIN", at=__import__("datetime").datetime(2026, 8, 5))
    check("2026-07 adjustment", get_credit_adjustment(conn, "u3", "2026-07"), 4)
    check("2026-08 adjustment", get_credit_adjustment(conn, "u3", "2026-08"), 9)
    check("no adjustment recorded for user with none", get_credit_adjustment(conn, "u3", "2026-09"), 0)


def test_validation():
    print("\n--- 4. input validation ---")
    conn = make_conn()
    check_raises("amount=0 rejected", lambda: add_credit(conn, "u4", REASON_GRANT, 0, None, "ADMIN"))
    check_raises("negative amount rejected", lambda: add_credit(conn, "u4", REASON_GRANT, -5, None, "ADMIN"))
    check_raises("amount over MAX_ADJUSTMENT rejected",
                 lambda: add_credit(conn, "u4", REASON_GRANT, MAX_ADJUSTMENT + 1, None, "ADMIN"))
    check_raises("unknown reason_type rejected",
                 lambda: add_credit(conn, "u4", "NOT_A_REASON", 1, None, "ADMIN"))
    # 정확히 한도값은 통과해야 한다(경계값)
    add_credit(conn, "u4", REASON_GRANT, MAX_ADJUSTMENT, None, "ADMIN")
    check("amount == MAX_ADJUSTMENT accepted",
          get_credit_adjustment(conn, "u4", get_current_month()), MAX_ADJUSTMENT)
    # RESET은 amount를 검증하지 않고 항상 0으로 기록되어야 한다(양수 강제 규칙과 무관)
    add_credit(conn, "u4", REASON_RESET, 0, None, "ADMIN")
    check("RESET always nets to 0 regardless of prior amount",
          get_credit_adjustment(conn, "u4", get_current_month()), 0)


def test_credit_log_written_alongside_ledger():
    print("\n--- 5. registry_credit_logs is written alongside the ledger ---")
    conn = make_conn()
    credit_id = add_credit(conn, "u5", REASON_GRANT, 6, "event", "ADMIN")
    logs = get_credit_logs(conn, "u5")
    check("one log written per add_credit call", len(logs), 1)
    check("log delta matches signed amount", logs[0]["delta"], 6)
    check("log references the credit id", logs[0]["related_credit_id"], credit_id)
    check("log balance_after reflects running total", logs[0]["balance_after"], 6)

    # USAGE 사유는 add_credit이 아니라 registry.py가 log_credit_event를 직접 호출해 남긴다
    # (한도 계산에는 반영되지 않고 추적 로그에만 남는다 — api/v1/registry.py 참고)
    log_credit_event(conn, "u5", "USAGE", -1, reason="registry request", actor="USER",
                      related_usage_id=42, balance_after=5)
    logs = get_credit_logs(conn, "u5")
    check("USAGE log added without touching ledger sum", len(logs), 2)
    check("ledger sum unaffected by USAGE log",
          get_credit_adjustment(conn, "u5", get_current_month()), 6)




def test_ledger_reason_gate_cannot_double_count():
    """원장에 **쓸 수 있는** 사유가 전부 "합계에 넣어도 되는" 사유인가 (2026-09-01 신설).

    ## 왜 필요한가 - 지금 합계는 사유로 거르지 않는다

    `get_credit_adjustment()` 는 그 달의 `registry_credits` 행을 **전부** 더한다
    (RESET 이후 자르기만 할 뿐 `reason_type` 조건이 없다). 지금 그것이 안전한 이유는
    `add_credit()` 이 `VALID_REASON_TYPES` 3종만 받아들여, 다른 사유는 애초에 그
    테이블에 들어갈 수 없기 때문이다. 즉 **안전이 게이트 하나에 걸려 있다.**

    누가 `VALID_REASON_TYPES` 에 `USAGE` 를 더하면 그 순간

        add_credit(..., "USAGE", -1)  ->  registry_credits 에 행이 생기고
        get_credit_adjustment()       ->  거르지 않으므로 그 -1 을 합산한다
        registry_usage                ->  같은 사용을 이미 세고 있다
        결과                          ->  **이중 차감** (사용자가 손해를 본다)

    `016_create_audit_and_credit_logs.sql` 과 `docs/CHANGELOG.md` 가 바로 이 이중 차감을
    경고하면서 근거로 `api/constants.py:ADJUSTMENT_REASONS` 를 인용한다. 그런데 실측하니
    (2026-09-01) 그 상수는 **코드에서 아무도 읽지 않는다** - 추적/미추적 전 파일형식을
    훑어 참조가 정의 한 줄과 두 문서뿐이었다. 즉 두 문서가 인용하는 근거가 실제로는
    아무것도 강제하지 않고 있었다.

    기존 `test_credit_log_written_alongside_ledger()` 는 USAGE 를 `log_credit_event()` 로
    직접 남겨 합계가 안 변하는 것을 본다. 그것은 **로그 경로**의 검증이라,
    `VALID_REASON_TYPES` 가 넓어지는 위 시나리오는 잡지 못한다(그 테스트는 add_credit 을
    부르지 않는다). 그래서 게이트 자체를 여기서 못박는다.

    ★ 동작은 바꾸지 않는다. 합계에 `reason_type` 필터를 넣는 것은 과금 로직 변경이라
      승인 영역이다. 여기서는 **지금 성립하는 불변식**만 고정한다.
    """
    print("\n[6] ledger reason gate")
    from api.constants import ADJUSTMENT_REASONS, RegistryCreditReason
    from api.v1.registry_credits import VALID_REASON_TYPES

    writable = {str(r) for r in VALID_REASON_TYPES}
    countable = {str(r) for r in ADJUSTMENT_REASONS}

    check("gate is not empty", len(writable) >= 3, True)
    check("countable set is not empty", len(countable) >= 3, True)

    # 핵심 불변식: 원장에 쓸 수 있는 사유는 전부 합계에 넣어도 되는 사유여야 한다.
    check("every writable reason is countable",
          sorted(writable - countable), [])

    # USAGE 는 절대 원장에 들어가면 안 된다(registry_usage 가 이미 센다).
    check("USAGE is not writable to the ledger",
          RegistryCreditReason.USAGE.value in writable, False)
    check("USAGE is not in the countable set",
          RegistryCreditReason.USAGE.value in countable, False)

    # 합계가 아직 사유로 거르지 않는다는 사실도 함께 고정한다 - 이 전제가 바뀌면
    # 위 불변식의 의미도 달라지므로 그때 이 검사를 다시 읽어야 한다.
    import inspect
    from api.v1.registry_credits import get_credit_adjustment as _gca
    body = inspect.getsource(_gca)
    check("sum still does not filter by reason_type (premise)",
          "reason_type=?" in body and body.count("reason_type") == 1, True)

    # 자기 검증: 비교가 공허하지 않은가.
    check("selftest: a bogus reason would be caught",
          sorted(({"QA_BOGUS"} | writable) - countable), ["QA_BOGUS"])


def run():
    test_grant_and_deduct_sum()
    test_reset_cuts_off_prior_adjustments()
    test_month_isolation()
    test_validation()
    test_credit_log_written_alongside_ledger()
    test_ledger_reason_gate_cannot_double_count()

    print("\n" + "=" * 55)
    if failures:
        print("FAILED (%d): %s" % (len(failures), ", ".join(failures)))
        return 1
    print("ALL TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(run())
