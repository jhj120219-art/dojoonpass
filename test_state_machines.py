"""
Payment/Subscription 상태 전이 규칙(api/v1/state_machines.py) 순수 로직 회귀 테스트.

이 모듈은 DB 커넥션도, jose(JWT)도 필요 없는 순수 함수만 다룬다(sync_expired_status처럼
conn을 요구하는 함수는 이 파일의 범위 밖) — api.auth -> jose 의존성 체인을 타지 않으므로
python-jose가 설치되지 않은 환경에서도(2026-08-08 기준 이 저장소 환경) 그대로 실행된다.
`test_api_regression.py`/`test_subscription_policy.py`는 둘 다 api.auth를 import해서 이 환경에서
실행 불가능한데, 그 두 파일이 커버하지 못하는 "전이 규칙 자체의 순수 로직"이 이 파일의 범위다.

프로젝트에 pytest 설정이 없으므로 기존 test_*.py 관례(단독 실행 스크립트)를 그대로 따른다.
    python test_state_machines.py

콘솔 인코딩(cp949) 문제를 피하려고 출력은 ASCII만 사용한다(migrate_execute.py와 동일한 이유).
"""
import sys
import os
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from api.constants import (PaymentStatus, SubscriptionStatus, is_paid,
                           TERMINAL_PAYMENT_STATUSES)
from api.v1.state_machines import (
    can_transition_payment, assert_payment_transition, is_terminal_payment,
    can_transition_subscription, assert_subscription_transition,
    is_entitled, resolve_expected_status, grace_period_end,
    InvalidTransition, GRACE_PERIOD_DAYS,
    PAYMENT_TRANSITIONS, SUBSCRIPTION_TRANSITIONS,
)

failures = []


def check(name, actual, expected):
    ok = actual == expected
    print("[%s] %s: %r (expected %r)" % ("PASS" if ok else "FAIL", name, actual, expected))
    if not ok:
        failures.append(name)


def check_true(name, cond):
    check(name, bool(cond), True)


def check_raises(name, fn, exc_type=InvalidTransition):
    try:
        fn()
        check(name, False, True)
    except exc_type:
        check(name, True, True)


# ---------------------------------------------------------------------------
# 1. Payment 전이 규칙 (docs/STATE_MACHINES.md 1절)
# ---------------------------------------------------------------------------
def test_payment_transitions_allowed():
    print("\n--- 1. payment transitions: allowed ---")
    P = PaymentStatus
    allowed = [
        (P.CREATED, P.READY), (P.CREATED, P.FAILED), (P.CREATED, P.CANCELLED),
        (P.READY, P.REQUESTED), (P.READY, P.FAILED), (P.READY, P.EXPIRED), (P.READY, P.CANCELLED),
        (P.REQUESTED, P.PAID), (P.REQUESTED, P.SUCCESS), (P.REQUESTED, P.FAILED),
        (P.REQUESTED, P.EXPIRED), (P.REQUESTED, P.CANCELLED),
        (P.PAID, P.PARTIAL_REFUND), (P.PAID, P.REFUNDED),
        (P.SUCCESS, P.PARTIAL_REFUND), (P.SUCCESS, P.REFUNDED),
        (P.PARTIAL_REFUND, P.PARTIAL_REFUND), (P.PARTIAL_REFUND, P.REFUNDED),
    ]
    for cur, tgt in allowed:
        check("allow %s -> %s" % (cur, tgt), can_transition_payment(cur, tgt), True)
        assert_payment_transition(cur, tgt)  # 예외 없이 통과해야 한다
    check("all allowed transitions did not raise", True, True)


def test_payment_transitions_forbidden():
    print("\n--- 2. payment transitions: forbidden ---")
    P = PaymentStatus
    forbidden = [
        (P.CREATED, P.PAID),          # 승인 단계 건너뛰기 금지
        (P.CREATED, P.REQUESTED),     # READY 건너뛰기 금지
        (P.READY, P.PAID),            # REQUESTED 건너뛰기 금지
        (P.PAID, P.CREATED),          # 역행 금지
        (P.PAID, P.FAILED),           # 승인 후 FAILED로 되돌리기 금지
        (P.REFUNDED, P.PAID),         # 종결 상태에서 나가는 전이 없음
        (P.FAILED, P.READY),          # 종결 상태에서 나가는 전이 없음
        (P.EXPIRED, P.PAID),          # 종결 상태에서 나가는 전이 없음
        (P.CANCELLED, P.PAID),        # 종결 상태에서 나가는 전이 없음
    ]
    for cur, tgt in forbidden:
        check("forbid %s -> %s" % (cur, tgt), can_transition_payment(cur, tgt), False)
        check_raises("assert raises for %s -> %s" % (cur, tgt),
                     lambda c=cur, t=tgt: assert_payment_transition(c, t))
    # 존재하지 않는 상태값으로의 전이도 거부되어야 한다
    check_raises("reject unknown target status",
                 lambda: assert_payment_transition(PaymentStatus.CREATED, "NOT_A_REAL_STATUS"))


def test_payment_terminal_and_is_paid():
    print("\n--- 3. is_terminal_payment / is_paid ---")
    for s in (PaymentStatus.FAILED, PaymentStatus.EXPIRED, PaymentStatus.CANCELLED, PaymentStatus.REFUNDED):
        check_true("terminal: %s" % s, is_terminal_payment(s))
    for s in (PaymentStatus.CREATED, PaymentStatus.READY, PaymentStatus.REQUESTED,
              PaymentStatus.PAID, PaymentStatus.SUCCESS, PaymentStatus.PARTIAL_REFUND):
        check("not terminal: %s" % s, is_terminal_payment(s), False)

    # is_paid: 레거시 SUCCESS와 신규 PAID를 모두 성공으로 인정 (docs/STATE_MACHINES.md 참고)
    for s in (PaymentStatus.PAID, PaymentStatus.SUCCESS, PaymentStatus.PARTIAL_REFUND):
        check_true("is_paid(%s)" % s, is_paid(s))
    for s in (PaymentStatus.CREATED, PaymentStatus.READY, PaymentStatus.REQUESTED,
              PaymentStatus.FAILED, PaymentStatus.EXPIRED, PaymentStatus.CANCELLED,
              PaymentStatus.REFUNDED):
        check("not is_paid(%s)" % s, is_paid(s), False)

    # ── ★ 종결 집합이 **전이표에서 유도된 값과 같은가** (2026-09-01) ──────────
    #
    #   위 검사들은 "지금 무엇이 종결인가"를 손으로 나열해 고정한다. 그런데
    #   `TERMINAL_PAYMENT_STATUSES` 는 손으로 유지하는 집합이고, 진짜 근거는
    #   `PAYMENT_TRANSITIONS` 다 — **나가는 전이가 없는 상태가 곧 종결**이다.
    #   그 둘이 갈라져도 지금은 아무도 모른다:
    #
    #     [1] 누가 CANCELLED 에 나가는 전이를 추가하면(더 이상 종결이 아니다)
    #         `is_terminal_payment("CANCELLED")` 는 여전히 True 를 돌려준다.
    #         -> 합법이 된 전이를 종결 가드가 계속 막는다.
    #         위 §2 의 금지 전이 목록은 `(CANCELLED, PAID)` 한 쌍만 보므로
    #         `CANCELLED -> READY` 같은 것은 걸리지 않는다.
    #     [2] 새 상태를 넣고 전이를 안 달면(=종결인데) 집합에 넣는 것을 잊으면
    #         `is_terminal_payment` 가 False 를 돌려준다.
    #         -> 막다른 상태를 "아직 진행 중"으로 취급한다.
    #
    #   `PAID_STATUSES` / `ENTITLED_SUBSCRIPTION_STATUSES` 는 **유도할 수 없다** —
    #   "이 상태는 돈을 받은 것인가 / 이용할 수 있는 것인가"는 전이 구조가 아니라
    #   제품 판단이다. 그래서 여기서는 종결만 유도로 묶는다.
    derived_terminal = {s for s in (e.value for e in PaymentStatus)
                        if not PAYMENT_TRANSITIONS.get(s)}
    declared_terminal = {str(s) for s in TERMINAL_PAYMENT_STATUSES}
    check_true("검사가 공허하지 않다(전이표를 실제로 읽었다)",
               len(PAYMENT_TRANSITIONS) >= 5)
    check("★ 종결로 유도됐는데 선언에 없다", sorted(derived_terminal - declared_terminal), [])
    check("★ 선언은 종결인데 나가는 전이가 있다", sorted(declared_terminal - derived_terminal), [])

    # 새 상태가 전이표에 아예 빠지는 것도 막는다 — 빠지면 `.get(s)` 가 빈 집합이라
    # **자동으로 종결처럼 보인다.** 위 대조만으로는 그것이 의도인지 누락인지 알 수 없다.
    missing = sorted(s for s in (e.value for e in PaymentStatus)
                     if s not in PAYMENT_TRANSITIONS)
    check("★ 전이표에 항목이 없는 결제 상태", missing, [])

    sub_missing = sorted(s for s in (e.value for e in SubscriptionStatus)
                         if s not in SUBSCRIPTION_TRANSITIONS)
    check("★ 전이표에 항목이 없는 구독 상태", sub_missing, [])


# ---------------------------------------------------------------------------
# 2. Subscription 전이 규칙 (docs/STATE_MACHINES.md 2절)
# ---------------------------------------------------------------------------
def test_subscription_transitions_allowed():
    print("\n--- 4. subscription transitions: allowed ---")
    S = SubscriptionStatus
    allowed = [
        (S.ACTIVE, S.GRACE_PERIOD), (S.ACTIVE, S.PAUSED),
        (S.ACTIVE, S.EXPIRED), (S.ACTIVE, S.CANCELLED),
        (S.GRACE_PERIOD, S.ACTIVE), (S.GRACE_PERIOD, S.EXPIRED), (S.GRACE_PERIOD, S.CANCELLED),
        (S.PAUSED, S.ACTIVE), (S.PAUSED, S.EXPIRED), (S.PAUSED, S.CANCELLED),
        (S.EXPIRED, S.ACTIVE), (S.EXPIRED, S.CANCELLED),
    ]
    for cur, tgt in allowed:
        check("allow %s -> %s" % (cur, tgt), can_transition_subscription(cur, tgt), True)
        assert_subscription_transition(cur, tgt)
    check("all allowed transitions did not raise", True, True)


def test_subscription_transitions_forbidden():
    print("\n--- 5. subscription transitions: forbidden ---")
    S = SubscriptionStatus
    forbidden = [
        (S.ACTIVE, S.ACTIVE),           # 자기 자신으로의 "전이"는 정의되지 않음
        (S.CANCELLED, S.ACTIVE),        # 해지는 최종 상태 — 되돌릴 수 없음
        (S.CANCELLED, S.GRACE_PERIOD),
        (S.CANCELLED, S.PAUSED),
        (S.CANCELLED, S.EXPIRED),
        (S.GRACE_PERIOD, S.PAUSED),     # 유예 중 바로 일시정지는 허용 목록에 없음
    ]
    for cur, tgt in forbidden:
        check("forbid %s -> %s" % (cur, tgt), can_transition_subscription(cur, tgt), False)
        check_raises("assert raises for %s -> %s" % (cur, tgt),
                     lambda c=cur, t=tgt: assert_subscription_transition(c, t))

    # ── 아는 상태가 아니면 거부한다 (2026-08-13 Sprint 99, 커버리지가 지목) ──
    #
    # `assert_subscription_transition()`에는 관문이 **둘** 있다.
    #
    #     if target not in {s.value for s in SubscriptionStatus}:  # (A) 아는 상태인가
    #     if not can_transition_subscription(current, target):     # (B) 허용된 전이인가
    #
    # 위 목록은 전부 (B)에서 걸리므로 **(A)는 한 번도 실행된 적이 없었다.** 둘은 막는
    # 것이 다르다 ― (B)는 "아는 상태끼리 잘못된 순서", (A)는 **오타나 새 상태값처럼
    # 우리가 모르는 문자열**이다.
    #
    # (A)가 없으면 그런 값은 `SUBSCRIPTION_TRANSITIONS.get(current, set())`에서
    # 조용히 False가 되어 결국 같은 예외가 나긴 한다. 그래서 지금은 동작이 같다.
    # 그럼에도 검사를 두는 이유: 전이표에 `"*"` 같은 와일드카드나 기본 허용이 한 줄
    # 들어오는 순간 (A)만이 유일한 방어가 된다. 그 줄은 **모르는 상태를 열어 주는
    # 형태로** 들어오기 마련이다.
    for unknown in ("ACTIVE_", "활성", "active", "", "DELETED"):
        check("모르는 상태값은 거부한다: %r" % (unknown,),
              can_transition_subscription(S.ACTIVE, unknown), False)
        check_raises("모르는 상태값에 예외: %r" % (unknown,),
                     lambda t=unknown: assert_subscription_transition(S.ACTIVE.value, t))


# ---------------------------------------------------------------------------
# 3. 유예 기간(GRACE_PERIOD) 계산 — docs/BUGS.md #16과 같은 축의 회귀
#    (과거 결함: GRACE_PERIOD인데도 expires_at > now를 요구해 유예 정책이 작동하지 않았음)
# ---------------------------------------------------------------------------
def test_resolve_expected_status():
    print("\n--- 6. resolve_expected_status (grace period math) ---")
    now = datetime(2026, 8, 8, 12, 0, 0)

    # 만료 전 -> 그대로 ACTIVE
    future = (now + timedelta(days=1)).isoformat()
    check("ACTIVE, expires in future -> ACTIVE",
          resolve_expected_status(SubscriptionStatus.ACTIVE, future, now), SubscriptionStatus.ACTIVE)

    # 만료 직후(유예 기간 안, 0일 < 경과 < 3일) -> GRACE_PERIOD
    just_expired = (now - timedelta(hours=1)).isoformat()
    check("ACTIVE, expired 1h ago -> GRACE_PERIOD",
          resolve_expected_status(SubscriptionStatus.ACTIVE, just_expired, now), SubscriptionStatus.GRACE_PERIOD)

    # 유예 기간 경계 바로 안쪽 (3일 - 1초)
    edge_inside = (now - (timedelta(days=GRACE_PERIOD_DAYS) - timedelta(seconds=1))).isoformat()
    check("ACTIVE, expired just under %d days -> GRACE_PERIOD" % GRACE_PERIOD_DAYS,
          resolve_expected_status(SubscriptionStatus.ACTIVE, edge_inside, now), SubscriptionStatus.GRACE_PERIOD)

    # 유예 기간 정확히 경계 (3일 지남) -> EXPIRED (now < expires+3d가 거짓)
    edge_outside = (now - timedelta(days=GRACE_PERIOD_DAYS)).isoformat()
    check("ACTIVE, expired exactly %d days ago -> EXPIRED" % GRACE_PERIOD_DAYS,
          resolve_expected_status(SubscriptionStatus.ACTIVE, edge_outside, now), SubscriptionStatus.EXPIRED)

    # 유예 기간 지남 -> EXPIRED
    long_expired = (now - timedelta(days=GRACE_PERIOD_DAYS + 1)).isoformat()
    check("ACTIVE, expired %d+1 days ago -> EXPIRED" % GRACE_PERIOD_DAYS,
          resolve_expected_status(SubscriptionStatus.ACTIVE, long_expired, now), SubscriptionStatus.EXPIRED)

    # expires_at이 정확히 now와 같음 -> "이미 지남"으로 취급되어야 한다(now < expires가 False)
    check("ACTIVE, expires_at == now -> GRACE_PERIOD (not ACTIVE)",
          resolve_expected_status(SubscriptionStatus.ACTIVE, now.isoformat(), now), SubscriptionStatus.GRACE_PERIOD)

    # expires_at 없음 -> 무기한으로 보고 상태 유지
    check("ACTIVE, no expires_at -> ACTIVE (unlimited)",
          resolve_expected_status(SubscriptionStatus.ACTIVE, None, now), SubscriptionStatus.ACTIVE)

    # 형식이 깨진 expires_at -> 파싱 실패를 만료로 해석하지 않고 상태를 유지해야 한다
    check("ACTIVE, malformed expires_at -> ACTIVE (parse failure keeps status)",
          resolve_expected_status(SubscriptionStatus.ACTIVE, "not-a-date", now), SubscriptionStatus.ACTIVE)

    # PAUSED/CANCELLED/EXPIRED는 시간과 무관하게 유지 (사용자 의사로 정해진 상태)
    for s in (SubscriptionStatus.PAUSED, SubscriptionStatus.CANCELLED, SubscriptionStatus.EXPIRED):
        check("%s stays %s regardless of expired expires_at" % (s, s),
              resolve_expected_status(s, long_expired, now), s)
        check("%s stays %s even with future expires_at" % (s, s),
              resolve_expected_status(s, future, now), s)


def test_is_entitled():
    print("\n--- 7. is_entitled ---")
    now = datetime(2026, 8, 8, 12, 0, 0)
    future = (now + timedelta(days=1)).isoformat()
    just_expired = (now - timedelta(hours=1)).isoformat()
    long_expired = (now - timedelta(days=GRACE_PERIOD_DAYS + 1)).isoformat()

    # 판정은 resolve_expected_status에 위임되므로, 여기서는 "effective status"를 넣어 확인한다
    # (registry.py:get_entitled_subscription()이 실제로 호출하는 방식과 동일한 2단계 호출)
    eff = resolve_expected_status(SubscriptionStatus.ACTIVE, future, now)
    check_true("ACTIVE within period -> entitled", is_entitled(eff, future, now))

    eff = resolve_expected_status(SubscriptionStatus.ACTIVE, just_expired, now)
    check("grace period effective status is GRACE_PERIOD", eff, SubscriptionStatus.GRACE_PERIOD)
    check_true("GRACE_PERIOD (just expired) -> still entitled", is_entitled(eff, just_expired, now))

    eff = resolve_expected_status(SubscriptionStatus.ACTIVE, long_expired, now)
    check("long expired effective status is EXPIRED", eff, SubscriptionStatus.EXPIRED)
    check("EXPIRED -> not entitled", is_entitled(eff, long_expired, now), False)

    check("PAUSED -> not entitled", is_entitled(SubscriptionStatus.PAUSED, future, now), False)
    check("CANCELLED -> not entitled", is_entitled(SubscriptionStatus.CANCELLED, future, now), False)


def test_grace_period_end():
    print("\n--- 8. grace_period_end ---")
    expires = datetime(2026, 8, 8, 12, 0, 0)
    expected = (expires + timedelta(days=GRACE_PERIOD_DAYS)).isoformat()
    check("grace_period_end adds %d days" % GRACE_PERIOD_DAYS,
          grace_period_end(expires.isoformat()), expected)
    check("grace_period_end(malformed) -> None", grace_period_end("garbage"), None)




# ---------------------------------------------------------------------------
# 8. 만료 시각이 깨졌을 때 — 안전하게 실패하되 **조용하지 않게** (2026-08-11 Sprint 56)
#
#    `_parse()`가 None을 돌려 만료 판정을 보류하는 것 자체는 옳다. 파싱 실패를 '만료'로
#    해석하면 정상 구독자가 끊긴다. 문제는 그 폴백이 **로그 한 줄 없이** 일어났다는 것이다.
#    깨진 expires_at을 가진 구독은 `effective_status()`가 영원히 만료로 넘기지 않으므로
#    **무기한 유효한 구독**이 되는데, 그 사실을 알 방법이 없었다.
#    안전한 방향으로 실패하는 것과 실패를 숨기는 것은 다르다.
# ---------------------------------------------------------------------------
def test_corrupt_expiry_is_safe_and_logged():
    import logging
    from datetime import datetime, timedelta

    print("\n--- 8. 깨진 만료 시각 처리 ---")
    now = datetime.now()

    class Capture(logging.Handler):
        def __init__(self):
            super().__init__()
            self.records = []

        def emit(self, record):
            self.records.append(record)

    sm_logger = logging.getLogger("api.v1.state_machines")
    cap = Capture()
    sm_logger.addHandler(cap)
    prev_level = sm_logger.level
    sm_logger.setLevel(logging.WARNING)
    try:
        # 진짜로 해석 불가능한 값만 고른다.
        # `''`는 "만료 시각 없음"(부재)이지 부패가 아니고, `'20260811'`은 Python 3.11+의
        # fromisoformat이 정상 파싱한다(기본 ISO 형식). 둘을 부패로 취급하면 테스트가
        # 실제 동작이 아니라 내 짐작을 검사하게 된다 — 실제로 그렇게 틀렸었다.
        for bad in ("not-a-date", "2026-13-45", "2026-08-11T99:99", "1754899200"):
            cap.records.clear()
            got = resolve_expected_status(SubscriptionStatus.ACTIVE, bad, now)
            # 안전한 방향: 만료로 넘기지 않는다
            check("expires_at=%r 이면 만료시키지 않는다" % bad, got, SubscriptionStatus.ACTIVE)
            # 그리고 반드시 드러난다
            check_true("expires_at=%r 파싱 실패가 로그에 남는다" % bad,
                       any(r.levelno >= logging.WARNING for r in cap.records))

        # 만료 시각 자체가 없는 것은 부패가 아니다 — 경고 없이 상태를 유지해야 한다.
        # (과잉 경고는 진짜 경고를 묻는다)
        for absent in (None, ""):
            cap.records.clear()
            check("expires_at=%r 는 상태 유지" % absent,
                  resolve_expected_status(SubscriptionStatus.ACTIVE, absent, now),
                  SubscriptionStatus.ACTIVE)
            check("expires_at=%r 에는 경고를 남기지 않는다" % absent,
                  [r for r in cap.records if r.levelno >= logging.WARNING], [])

        # 날짜만 있는 값은 자정으로 해석된다 — 부패가 아니므로 경고 없이 정상 처리한다.
        cap.records.clear()
        check("날짜만 있는 값은 자정 기준으로 정상 처리",
              resolve_expected_status(SubscriptionStatus.ACTIVE,
                                      (now + timedelta(days=2)).strftime("%Y-%m-%d"), now),
              SubscriptionStatus.ACTIVE)
        check("날짜만 있는 값에 경고 없음",
              [r for r in cap.records if r.levelno >= logging.WARNING], [])

        # grace_period_end도 같은 경로를 쓴다
        cap.records.clear()
        check("깨진 값이면 유예 종료 시각도 없음", grace_period_end("not-a-date"), None)
        check_true("유예 종료 계산에서도 로그가 남는다",
                   any(r.levelno >= logging.WARNING for r in cap.records))

        # 정상 값에서는 경고가 나오면 안 된다 (과잉 경고는 진짜 경고를 묻는다)
        cap.records.clear()
        ok = (now + timedelta(days=10)).isoformat()
        check("정상 만료값은 ACTIVE 유지",
              resolve_expected_status(SubscriptionStatus.ACTIVE, ok, now), SubscriptionStatus.ACTIVE)
        check("정상 값에는 경고를 남기지 않는다",
              [r for r in cap.records if r.levelno >= logging.WARNING], [])
    finally:
        sm_logger.removeHandler(cap)
        sm_logger.setLevel(prev_level)


def test_status_vocabulary_is_not_hardcoded_in_sql():
    """결제/구독/등기부 상태값이 **SQL 문자열에 박혀 있지 않은가** (2026-08-31 신설).

    ## 왜 필요한가

    이 값들은 전부 `WHERE status='...'` 로 비교된다. 오타는 예외가 아니라 **0행 매치**다 --
    조건이 아무 행도 고르지 못하면 "대상이 없다"로 조용히 끝난다. 결제 경로에서는
    그것이 곧 "초과결제 대상 신청을 못 찾음" 또는 "이미 처리됨" 오판이 된다.

    2026-08-31 실측으로 세 자리를 찾았다.

        api/v1/payments.py  SELECT ... WHERE user_id=? AND status='PAYMENT_REQUIRED'
        api/v1/payments.py  UPDATE ... SET status='PENDING' WHERE ... status='PAYMENT_REQUIRED'
        api/v1/doc_stats.py WHERE doc_type IN ('SPEC',...) AND status IN ('READY','FAILED')

    같은 파일들이 다른 자리에서는 이미 상수를 쓰고 있어(`PaymentStatus` / `QUEUE_STATUS_*`)
    **한 파일 안에서 규칙이 둘**이었다. 큐 상태에 대해 같은 정리를 한 것과 같은 취지다
    (`test_queue_safety_invariants.py`).

    ## 무엇을 보나

    어휘는 `api/constants.py` 의 열거형에서 **파생**한다 -- 목록을 여기 베끼면 한쪽만
    갱신되는 날이 오고, 그때 이 검사는 옛 목록을 지키게 된다.
    docstring 은 제외한다(설명문에 값을 적는 것은 정상이다).
    """
    print("\n--- 상태값이 SQL 리터럴로 박혀 있지 않은가 ---")
    import ast
    import io as _io
    import re
    import subprocess as _sp_scan
    from api.constants import (
        PaymentStatus, SubscriptionStatus, RegistryRequestStatus,
        DocumentStatus, DocumentType,
    )

    vocab = set()
    for enum in (PaymentStatus, SubscriptionStatus, RegistryRequestStatus,
                 DocumentStatus, DocumentType):
        vocab |= {e.value for e in enum}
    check_true("어휘를 열거형에서 뽑았다(검사가 공허하지 않다)", len(vocab) >= 20)

    # ★ 2026-09-04: **모양이 아니라 자리로** 본다.
    #
    #   예전 정규식은 `status='X'` / `status IN ('X',...)` 두 모양만 봤다. 그래서
    #   같은 값이 다른 모양으로 박힌 것을 전부 놓쳤다 — 실측으로 확인한 것들:
    #
    #       INSERT ... VALUES (?, ?, 'READY', ?)     collect_documents.py
    #       WHERE source='STATUS'                    load_rights_data.py (컬럼명이 다르다)
    #       WHERE ds.doc_type <> 'IMAGE'             audit_asset_integrity.py (`<>` 다)
    #       WHERE status NOT IN ('READY','NO_IMAGE') audit_asset_integrity.py
    #
    #   판정 기준을 바꾼다: **SQL 문자열 안에 어휘 값이 따옴표째 들어 있으면 위반이다.**
    #   비교 연산자나 컬럼 이름을 열거하려 들면 그 목록이 늘 뒤처진다(방금 그랬다).
    #
    #   ★ 대소문자는 **구별한다.** 큐 어휘는 소문자('failed')이고 화면 어휘는
    #     대문자('FAILED')다 — `re.I` 를 걸면 `document_queue` 의 정상적인 소문자
    #     값을 화면 어휘 위반으로 오인한다.
    sqlish = re.compile(r"\b(SELECT|INSERT|UPDATE|DELETE)\b", re.I)
    pat = re.compile(r"'(%s)'" % "|".join(re.escape(v) for v in sorted(vocab)))

    def offends(text):
        return bool(sqlish.search(text) and pat.search(text))

    def code_strings(path):
        """실제 코드에 쓰이는 문자열만. docstring 은 뺀다."""
        tree = ast.parse(_io.open(path, encoding="utf-8-sig").read())
        docs = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.FunctionDef,
                                 ast.AsyncFunctionDef, ast.ClassDef)):
                body = getattr(node, "body", None)
                if body and isinstance(body[0], ast.Expr) and \
                        isinstance(body[0].value, ast.Constant) and \
                        isinstance(body[0].value.value, str):
                    docs.add(id(body[0].value))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) \
                    and id(node) not in docs:
                yield getattr(node, "lineno", 0), node.value

    # ★ 2026-09-04: 훑는 범위를 **저장소 전체**로 넓힌다.
    #
    #   예전에는 `api/v1/*.py` 열몇 개만 봤다. 그런데 이 어휘를 SQL 에 박아 두는
    #   코드는 거의 전부 그 바깥에 있었다 — 복구 스크립트, 로더, 감사기다.
    #   실측(2026-09-04): 프로덕션 .py 96개 중 **9개 파일에 27자리**가 있었고
    #   이 검사는 그동안 초록이었다. "검사했다"고 말하면서 결함이 있는 자리를
    #   통째로 건너뛰고 있었던 셈이다.
    #
    #   특히 나쁜 조합이 둘 있었다:
    #     * 복구 스크립트  오타 -> 0행 매치 -> "N건 보정했습니다"를 찍고 아무것도 안 고친다
    #     * 감사기        오타 -> 0행 매치 -> **"어긋남 없음"** = 거짓 초록
    #
    #   `test_queue_safety_invariants.py` 가 큐 어휘에서 이미 같은 결론에 이르러
    #   범위를 넓혔다(그 파일 (c) 항목). 같은 규칙을 화면 어휘에도 적용한다.
    root = os.path.dirname(os.path.abspath(__file__))
    try:
        _out = _sp_scan.run(["git", "ls-files", "*.py"], cwd=root,
                            capture_output=True, text=True, timeout=30)
        files = ([f for f in _out.stdout.split()
                  if f.endswith(".py") and "-DESKTOP-" not in f
                  and not os.path.basename(f).startswith("test_")]
                 if _out.returncode == 0 else [])
    except (OSError, _sp_scan.SubprocessError):
        files = []
    if len(files) < 20:
        # git 이 없는 배포본 - 예전 범위로 되돌린다(좁지만 0보다 낫다).
        api_dir = os.path.join(root, "api", "v1")
        files = ["api/v1/" + n for n in sorted(os.listdir(api_dir)) if n.endswith(".py")]

    # ★ `test_*.py` 는 **일부러** 뺀다 - 편의가 아니라 규칙이다 (2026-09-04).
    #
    #   검사의 fixture 는 상태값을 리터럴로 심어야 한다. 그것이 상수와 **독립인
    #   두 번째 출처**이기 때문이다. 이 저장소가 그 이유를 이미 적어 두었다
    #   (`test_queue_safety_invariants.py` (e)):
    #
    #       (b)/(c) 는 전부 같은 상수에서 파생되므로, 상수 값에 오타가 나면
    #       양쪽이 함께 틀려 **조용히 통과한다**(2026-08-31 변이 검증에서 실제로
    #       생존했다). 그래서 제품 코드가 DB 에 실제로 쓴 값을 손으로 적은 기대
    #       문자열과 맞춘다 - **두 출처가 독립이라 오타가 드러난다.**
    #
    #   즉 fixture 를 상수로 "정리"하면 그 독립성이 사라지고, 상수 자체의 오타를
    #   잡던 마지막 그물이 없어진다. 아래 `_fixture_layer_stays_independent()` 가
    #   그 전제가 아직 살아 있는지 확인한다.

    offenders = []
    scanned = 0
    for rel in files:
        path = os.path.join(root, rel.replace("/", os.sep))
        if not os.path.exists(path):
            continue
        scanned += 1
        try:
            strings = list(code_strings(path))
        except (OSError, SyntaxError):
            continue
        for lineno, text in strings:
            if offends(text):
                offenders.append((rel, lineno, text))
    # ★ 하한을 고정한다. 파일 열거가 깨지면 offenders 는 당연히 비고 이 검사는
    #   조용히 초록이 된다 - 방금 고친 것이 바로 그 침묵이다.
    check_true("훑을 파일을 실제로 찾았다 (%d개)" % scanned, scanned >= 40)

    # 정당한 예외는 뺀다(근거는 `ALLOWED_SQL_STATUS_LITERALS` 에 적혀 있다).
    def excused(rel, text):
        for (afile, marker) in ALLOWED_SQL_STATUS_LITERALS:
            if afile == rel and marker in text:
                return (afile, marker)
        return None

    remaining, used = [], set()
    for rel, lineno, text in offenders:
        key = excused(rel, text)
        if key:
            used.add(key)
        else:
            remaining.append("%s:%d" % (rel, lineno))
    remaining = sorted(set(remaining))
    if remaining:
        print("   ★ SQL 에 상태값이 문자열로 박힌 곳:")
        for o in remaining:
            print("      %s" % o)
        print("   오타는 예외가 아니라 0행 매치다. `api/constants.py` 의 값을 바인딩하라")
        print("   정당한 예외라면 `ALLOWED_SQL_STATUS_LITERALS` 에 **근거와 함께** 등록하라")
    check("SQL 에 상태값 리터럴이 박혀 있지 않다", remaining, [])

    # ★ 죽은 예외를 잡는다. 코드가 고쳐졌는데 예외가 남아 있으면, 그 자리에
    #   리터럴이 다시 생겨도 이 검사가 **눈감아 준다**(이 저장소의 다른 예외
    #   목록들이 전부 같은 짝 검사를 갖고 있는 이유다).
    dead = sorted("%s / %s" % k for k in ALLOWED_SQL_STATUS_LITERALS if k not in used)
    check("허용 목록에 죽은 항목이 없다", dead, [])

    # ★ 표식이 **한 문장만** 가리키는지 확인한다. 너무 짧은 표식은 여러 문장을
    #   덮어 새 위반까지 조용히 면제해 준다 - 예외 목록이 탐지기를 무디게 하는
    #   가장 흔한 방식이다.
    ambiguous = []
    for (afile, marker) in ALLOWED_SQL_STATUS_LITERALS:
        hit = [ln for rel, ln, text in offenders if rel == afile and marker in text]
        if len(hit) > 1:
            ambiguous.append("%s / %s -> %d문장" % (afile, marker, len(hit)))
    check("허용 표식이 문장 하나만 가리킨다", sorted(ambiguous), [])
    check_true("근거 없는 예외가 없다",
               all(isinstance(v, str) and len(v.strip()) >= 10
                   for v in ALLOWED_SQL_STATUS_LITERALS.values()))

    # 탐지기 자체 증명 -- 합성 입력에서는 반드시 잡히고, 바인딩은 잡히지 않아야 한다.
    check_true("탐지기가 `status='PENDING'` 을 잡는다",
               offends("UPDATE t SET x=? WHERE status='PENDING'"))
    check_true("탐지기가 `IN ('READY',...)` 를 잡는다",
               offends("SELECT 1 FROM t WHERE status IN ('READY','FAILED')"))
    # ★ 아래 넷이 예전 탐지기가 놓치던 모양이다(2026-09-04 실측으로 확인).
    check_true("★ INSERT VALUES 안의 리터럴도 잡는다",
               offends("INSERT INTO document_status (a,b,c) VALUES (?, ?, 'READY')"))
    check_true("★ 컬럼 이름이 달라도 잡는다(source='STATUS')",
               offends("DELETE FROM tenant_rights WHERE source='STATUS'"))
    check_true("★ `<>` 비교도 잡는다",
               offends("SELECT 1 FROM t WHERE doc_type <> 'IMAGE'"))
    check_true("★ NOT IN 도 잡는다",
               offends("SELECT 1 FROM t WHERE status NOT IN ('READY','NO_IMAGE')"))
    check_true("바인딩 형태는 잡지 않는다(오탐 없음)",
               not offends("UPDATE t SET status=? WHERE status=?"))
    check_true("어휘 밖 문자열은 잡지 않는다",
               not offends("SELECT 1 FROM t WHERE status='NOT_A_REAL_STATUS'"))
    check_true("SQL 이 아닌 문자열은 잡지 않는다(오탐 없음)",
               not offends("화면에 'READY' 라고 적는다"))
    # ★ 큐 어휘(소문자)를 화면 어휘 위반으로 오인하지 않는다. 두 어휘는 값이
    #   대소문자로 갈려 있고, 큐 쪽은 `test_queue_safety_invariants.py` 가 본다.
    check_true("큐의 소문자 상태는 이 검사의 대상이 아니다",
               not offends("SELECT 1 FROM document_queue WHERE status='failed'"))
    # ★ 어휘가 실제로 IMAGE 를 포함한다 - 포함하지 않으면 위 `<>` 증명이 공허해진다
    #   (`DocumentType` 에 IMAGE 가 빠져 있어 탐지기가 그 값을 찾지도 않던 때가 있었다).
    check_true("어휘에 IMAGE 가 있다(누락되면 탐지기가 그 값을 찾지 않는다)",
               "IMAGE" in vocab)





# ---------------------------------------------------------------------------
# SQL 에 상태값 리터럴을 **그대로 둬도 되는** 자리 (2026-09-04)
#
# 탐지기의 목적은 어휘 드리프트를 잡는 것이지 리터럴을 0개로 만드는 것이 아니다.
# 그래서 정당한 예외를 적을 자리를 둔다. **근거 없이는 늘리지 않는다** —
# 이 저장소의 다른 예외 목록(`KNOWN_UNLABELED` / `ALLOWED_SQL_PERCENT_TEMPLATES` /
# `SQL_PLACEHOLDER_SITES`)과 같은 규약이다.
#
# 예외로 인정할 수 있는 성격 (하나에 해당해야 한다)
#
#   역사적 값     지금 어휘에 없는 옛 값을 다루는 일회성 보정. 상수로 만들면
#                 "지금 쓰는 값"처럼 보여 오히려 헷갈린다.
#   부트스트랩    `api.constants` 를 import 할 수 없는 자리(순환 import 등).
#   표시 문자열   실행되지 않고 사람에게 보여 주기만 하는 SQL 예시.
#
# ★ 지금은 **비어 있다**(2026-09-04 실측: 프로덕션 위반 0건). 비어 있는 것이
#   정상이며, 아래 "죽은 예외" 검사가 목록이 낡는 것을 막는다.
ALLOWED_SQL_STATUS_LITERALS = {
    # ("파일경로", "문장 안의 표식"): "왜 정당한가",
    #
    # ★ 키는 **줄번호가 아니라 문장 표식**이다 (2026-09-04). 줄번호로 두면
    #   위쪽을 한 줄만 고쳐도 예외가 어긋나 애먼 빨강이 난다(실제로 났다).
    #   `ALLOWED_SQL_PERCENT_TEMPLATES` 가 SQL 문장 자체를 키로 쓰는 이유와 같다.
    #   표식은 그 문장에만 있는 조각이어야 한다(아래 "표식이 실제로 그 문장에만
    #   있다" 검사가 확인한다).
    #
    # ── 감사기 self-test 의 **시드** (2026-09-04, 변이 N2 로 발견) ──────────
    #
    #   `audit_asset_integrity.py --selftest` 는 스크래치 사본에 결함을 일부러
    #   심고 감사기가 그것을 잡는지 본다. 그 **시드**는 감사 질의가 쓰는 상수와
    #   독립이어야 한다.
    #
    #   같은 상수를 쓰게 했더니(2026-09-04 정본화 작업) `_READY = "REDY"` 오타에서
    #   시드와 판정이 함께 틀리며 self-test 가 **통과**했다. 그 상태의 감사기는
    #   운영 DB 에서 0행 매치로 "어긋남 없음"을 찍는다 — 감사기의 거짓 초록이다.
    #
    #   `test_queue_safety_invariants.py` (e) 가 같은 이유로 같은 선택을 한다:
    #   *"두 출처가 독립이라 오타가 드러난다."* 그래서 이 두 자리는 리터럴이 정답이다.
    ("audit_asset_integrity.py", "UPDATE document_status SET status='READY'"):
        "self-test 결함 B 시드 - 감사 질의의 상수와 독립인 두 번째 출처여야 한다",
    ("audit_asset_integrity.py", "WHERE ds.status = 'READY' LIMIT 1"):
        "self-test 결함 C 시드 - 같은 이유(변이 N2)",
}


# 상태 UPDATE 를 담은 함수가 반드시 불러야 하는 전이 검증 함수.
# (테이블, SQL 정규식용 이름, 있어야 하는 호출)
TRANSITION_GUARDED_TABLES = (
    ("payments", "assert_payment_transition"),
    ("subscriptions", "assert_subscription_transition"),
)


def test_fixture_layer_stays_an_independent_source():
    """검사 fixture 가 상태값을 **리터럴로** 들고 있는가 (2026-09-04 신설).

    ## 왜 이것을 검사하나 — 없어지면 아무도 모른다

    바로 위 탐지기는 제품 코드만 훑고 `test_*.py` 는 일부러 뺀다. 그 제외는
    편의가 아니라 **설계**다 — fixture 의 리터럴이 `api/constants.py` 와 독립인
    두 번째 출처이고, 그 독립성이 **상수 자체의 오타**를 잡는 마지막 그물이다
    (`test_queue_safety_invariants.py` (e) 가 같은 이유로 같은 방식을 쓴다).

    위험한 것은 선의의 정리다. 누군가 "일관성"을 이유로 fixture 의
    `status='READY'` 를 `DocumentStatus.READY.value` 로 바꾸면:

        * 어떤 검사도 붉어지지 않는다(오히려 더 깔끔해 보인다)
        * 그런데 그 순간 제품과 검사가 **같은 한 출처**를 보게 되어,
          `READY = "REDY"` 같은 오타가 양쪽을 함께 틀리게 만들어도
          모든 검사가 통과한다

    그래서 전제를 명시적으로 붙든다 — fixture 층에 리터럴이 **실제로 남아 있는지**.
    """
    print(chr(10) + "--- fixture 층이 독립된 출처로 남아 있는가 ---")
    import ast
    import io as _io
    import re
    import subprocess as _sp
    from api.constants import (
        PaymentStatus, SubscriptionStatus, RegistryRequestStatus,
        DocumentStatus, DocumentType,
    )

    vocab = set()
    for enum in (PaymentStatus, SubscriptionStatus, RegistryRequestStatus,
                 DocumentStatus, DocumentType):
        vocab |= {e.value for e in enum}
    sqlish = re.compile(r"\b(SELECT|INSERT|UPDATE|DELETE)\b", re.I)
    pat = re.compile(r"'(%s)'" % "|".join(re.escape(v) for v in sorted(vocab)))

    root = os.path.dirname(os.path.abspath(__file__))
    try:
        out = _sp.run(["git", "ls-files", "--exclude-standard", "test_*.py"],
                      cwd=root, capture_output=True, text=True, timeout=30)
        files = ([f for f in out.stdout.split()
                  if f.endswith(".py") and "-DESKTOP-" not in f]
                 if out.returncode == 0 else [])
    except (OSError, _sp.SubprocessError):
        files = []
    if len(files) < 10:
        files = sorted(n for n in os.listdir(root)
                       if n.startswith("test_") and n.endswith(".py")
                       and "-DESKTOP-" not in n)
    check_true("훑을 검사 파일을 실제로 찾았다 (%d개)" % len(files), len(files) >= 10)

    literal_sites = 0
    literal_files = set()
    for rel in files:
        path = os.path.join(root, rel.replace("/", os.sep))
        try:
            tree = ast.parse(_io.open(path, encoding="utf-8-sig").read())
        except (OSError, SyntaxError):
            continue
        docs = set()
        for node in ast.walk(tree):
            body = getattr(node, "body", None)
            if isinstance(node, (ast.Module, ast.FunctionDef,
                                 ast.AsyncFunctionDef, ast.ClassDef)) and body \
                    and isinstance(body[0], ast.Expr) \
                    and isinstance(body[0].value, ast.Constant) \
                    and isinstance(body[0].value.value, str):
                docs.add(id(body[0].value))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) \
                    and id(node) not in docs:
                if sqlish.search(node.value) and pat.search(node.value):
                    literal_sites += 1
                    literal_files.add(rel)

    print("   fixture 리터럴 %d자리 / 파일 %d개" % (literal_sites, len(literal_files)))
    # 하한은 넉넉히 잡는다 - 이 검사가 지키는 것은 "독립 출처가 살아 있다"이지
    # 특정 개수가 아니다. 실측(2026-09-04): 113자리 / 파일 14개.
    check_true("★ fixture 가 상태값을 리터럴로 들고 있다(독립 출처 %d자리)" % literal_sites,
               literal_sites >= 20)
    check_true("★ 한 파일에 몰려 있지 않다(검사 %d개가 독립적으로 심는다)"
               % len(literal_files), len(literal_files) >= 3)


def test_canonical_sets_are_not_relisted_in_python():
    """정본 **집합**을 파이썬 리터럴로 다시 나열하지 않는가 (2026-09-04 신설).

    ## 위 SQL 탐지기가 못 보는 자리

    위 검사는 **SQL 문자열 안의** 값을 본다. 그런데 어휘 드리프트는 SQL 밖에서도
    생긴다 — 같은 집합을 파이썬 튜플로 다시 적는 것이다. 실측(2026-09-04)에서
    `audit_asset_integrity.py` 한 함수 안에 그 모양이 둘 있었다:

        질의  ... ds.status NOT IN (?, ?)   <- `_HAS_ARTIFACT` 바인딩 (정본)
        집계  r["s"] not in ("READY", "NO_IMAGE")   <- 손으로 다시 적음

        질의  dq.status IN (?, ?)           <- QUEUE_STATUS_PENDING/REFRESH (정본)
        집계  r["status"] in ("pending", "refresh")  <- 손으로 다시 적음

    **한 함수 안에서 규칙이 둘**이다. 어휘가 늘면 질의는 따라가고 집계만 옛 값에
    머문다 — 그때 감사기는 어긋남을 **찾고도 0으로 센다**(거짓 초록).

    ## 판정 기준

    문자열 상수만으로 이루어진 튜플/리스트/집합 리터럴이 **선언된 정본 집합과
    정확히 같으면** 위반이다. 정본 자신의 선언(`X = ("A", "B")`)은 당연히 예외다.

    ★ 부분집합은 보지 않는다. "두 값을 우연히 함께 쓰는 것"과 "그 집합을 뜻하는 것"은
      다르고, 부분집합까지 잡으면 정상 코드를 괴롭힌다(이 검사의 목적은 어휘 드리프트
      방지이지 리터럴 박멸이 아니다).
    """
    print(chr(10) + "--- 정본 집합을 파이썬에서 다시 나열하지 않는가 ---")
    import ast
    import io as _io
    import subprocess as _sp
    import storage.database as _db
    from api.constants import (
        DocumentType, DOCUMENT_STATUSES_IN_USE, PAID_STATUSES,
        TERMINAL_PAYMENT_STATUSES, ENTITLED_SUBSCRIPTION_STATUSES,
    )

    # (정본 이름 -> 값 집합). 이름은 **선언과 같은 이름**이어야 한다 - 아래에서
    # "정본 자신의 선언"을 그 이름으로 알아본다.
    canon = {
        "DOC_STATUS_HAS_ARTIFACT": frozenset(_db.DOC_STATUS_HAS_ARTIFACT),
        "QUEUE_CLAIMABLE_STATUSES": frozenset(_db.QUEUE_CLAIMABLE_STATUSES),
        "QUEUE_IN_PROGRESS_STATUSES": frozenset(_db.QUEUE_IN_PROGRESS_STATUSES),
        "QUEUE_ACTIVE_STATUSES": frozenset(_db.QUEUE_ACTIVE_STATUSES),
        "QUEUE_OVERWRITE_STATUSES": frozenset(_db.QUEUE_OVERWRITE_STATUSES),
        "QUEUE_STATUSES": frozenset(_db.QUEUE_STATUSES),
        "DOCUMENT_STATUSES_IN_USE": frozenset(str(v) for v in DOCUMENT_STATUSES_IN_USE),
        "PAID_STATUSES": frozenset(str(v) for v in PAID_STATUSES),
        "TERMINAL_PAYMENT_STATUSES": frozenset(str(v) for v in TERMINAL_PAYMENT_STATUSES),
        "ENTITLED_SUBSCRIPTION_STATUSES":
            frozenset(str(v) for v in ENTITLED_SUBSCRIPTION_STATUSES),
        "DocumentType": frozenset(e.value for e in DocumentType),
    }
    check_true("정본 집합을 실제로 모았다 (%d개)" % len(canon), len(canon) >= 8)
    check_true("집합이 비어 있지 않다",
               all(len(v) >= 2 for v in canon.values()))

    root = os.path.dirname(os.path.abspath(__file__))
    try:
        out = _sp.run(["git", "ls-files", "--exclude-standard", "*.py"], cwd=root,
                      capture_output=True, text=True, timeout=30)
        files = ([f for f in out.stdout.split()
                  if f.endswith(".py") and "-DESKTOP-" not in f
                  and not os.path.basename(f).startswith("test_")]
                 if out.returncode == 0 else [])
    except (OSError, _sp.SubprocessError):
        files = []
    if len(files) < 20:
        files = sorted(n for n in os.listdir(root)
                       if n.endswith(".py") and not n.startswith("test_")
                       and "-DESKTOP-" not in n)
    check_true("훑을 파일을 실제로 찾았다 (%d개)" % len(files), len(files) >= 20)

    def relisted(tree):
        """(줄번호, 정본이름) - 정본 자신의 선언은 뺀다."""
        # `NAME = (...)` 형태로 선언되는 노드는 정본 자신이다.
        own = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Name) and t.id in canon:
                        own.add(id(node.value))
        found = []
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Tuple, ast.List, ast.Set)) or not node.elts:
                continue
            if id(node) in own:
                continue
            vals = [e.value for e in node.elts
                    if isinstance(e, ast.Constant) and isinstance(e.value, str)]
            if len(vals) < 2 or len(vals) != len(node.elts):
                continue
            same = frozenset(vals)
            for name, values in canon.items():
                if same == values:
                    found.append((getattr(node, "lineno", 0), name))
        return found

    offenders = []
    scanned = 0
    for rel in files:
        path = os.path.join(root, rel.replace("/", os.sep))
        try:
            tree = ast.parse(_io.open(path, encoding="utf-8-sig").read())
        except (OSError, SyntaxError):
            continue
        scanned += 1
        for lineno, name in relisted(tree):
            offenders.append("%s:%d  (%s 와 같다)" % (rel, lineno, name))
    check_true("실제로 훑었다 (%d개)" % scanned, scanned >= 20)
    if offenders:
        print("   ★ 정본 집합을 손으로 다시 나열한 곳:")
        for o in sorted(set(offenders)):
            print("      %s" % o)
        print("   그 상수를 그대로 참조하라 - 어휘가 늘면 한쪽만 옛 값에 머문다")
    check("정본 집합을 다시 나열한 곳이 없다", sorted(set(offenders)), [])

    # 탐지기 자기 증명 - 합성 입력에서 반드시 잡히고, 정본 선언은 잡히지 않는다.
    bad = ast.parse('x = 1 if s in ("READY", "NO_IMAGE") else 0')
    check_true("탐지기가 재나열을 잡는다",
               any(n == "DOC_STATUS_HAS_ARTIFACT" for _, n in relisted(bad)))
    own_decl = ast.parse('DOC_STATUS_HAS_ARTIFACT = ("READY", "NO_IMAGE")')
    check_true("정본 자신의 선언은 잡지 않는다(오탐 없음)", not relisted(own_decl))
    partial = ast.parse('x = s in ("READY",)')
    check_true("부분집합은 잡지 않는다(오탐 없음)", not relisted(partial))
    unrelated = ast.parse('x = s in ("A", "B")')
    check_true("어휘 밖 목록은 잡지 않는다(오탐 없음)", not relisted(unrelated))


def test_status_updates_call_transition_validation():
    """상태를 바꾸는 UPDATE 가 **전부** 전이 검증을 거치는가 (2026-09-01 신설).

    ## 기존 검사가 못 보는 자리

    - 위 §1/§2 는 `assert_payment_transition()` 이 **올바로 동작하는지**만 본다.
      그 함수를 아무도 안 불러도 전부 통과한다.
    - `test_subscription_policy.py` 의 hidden-writer 검사는 **어느 모듈이** 쓰는지를 본다.
      정본 모듈 **안에서** 검증 없는 UPDATE 가 새로 생기는 것은 그 검사의 사각이다
      (정본 파일은 통째로 예외 처리되기 때문이다).

    즉 "정본 모듈 안에 검증 없는 상태 UPDATE 를 한 줄 더한다"는 변경은
    지금까지 **어떤 검사에도 걸리지 않았다.**

    ## 무엇을 보는가

    함수 단위로 본다 - 어떤 함수가 `UPDATE <table> SET ... status = ...` SQL 문자열을
    담고 있으면, **같은 함수 안에서** 해당 전이 검증 함수를 불러야 한다.

    실측(2026-09-01) 현재 상태:

        api/v1/payments.py:refund_payment()        UPDATE + assert_payment_transition  OK
        api/v1/payments.py:process_webhook 계열     UPDATE + assert_payment_transition  OK
        api/v1/subscriptions.py:change_status()    UPDATE + assert_subscription_transition OK

    ★ INSERT 는 대상이 아니다 - 생성에는 이전 상태가 없다.
    ★ 검증을 부르는 위치(같은 함수 / 호출된 헬퍼)까지는 강제하지 않는다. 헬퍼로 빼는
      리팩터링을 막지 않기 위해, 같은 함수에서 못 찾으면 **같은 모듈의 다른 함수**에서
      찾는 것까지 허용한다. 그래도 모듈 전체에 호출이 0이면 잡힌다.
    """
    import ast
    import re
    import subprocess as _sp

    print("\n--- 상태 UPDATE 가 전이 검증을 거치는가 ---")
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

    def calls_in(node):
        got = set()
        for n in ast.walk(node):
            if isinstance(n, ast.Call):
                got.add(getattr(n.func, "id", None) or getattr(n.func, "attr", None))
        return got

    def validates(fn, fnmap, validator, depth=0, seen=None):
        """이 함수가 (직접 또는 같은 모듈의 헬퍼를 거쳐) 전이 검증을 부르는가.

        ★ 처음엔 "같은 모듈 어디서든 부르면 통과"로 썼는데, 변이를 넣어 보니
          **정본 모듈 안에 검증 없는 UPDATE 함수를 하나 더해도 그냥 통과**했다
          (그 모듈은 다른 함수에서 이미 검증을 부르고 있으니까). 즉 가장 중요한
          자리를 못 보는 공허한 검사였다. 그래서 **같은 함수**를 기본으로 하고,
          헬퍼로 빼는 리팩터링만 허용하도록 호출 그래프를 2단계까지만 따라간다.
        """
        seen = seen or set()
        if fn.name in seen or depth > 2:
            return False
        seen.add(fn.name)
        direct = calls_in(fn)
        if validator in direct:
            return True
        for callee in direct:
            target = fnmap.get(callee)
            if target is not None and validates(target, fnmap, validator, depth + 1, seen):
                return True
        return False

    total_sites = 0
    offenders = []
    for table, validator in TRANSITION_GUARDED_TABLES:
        pat = re.compile(r"UPDATE\s+%s\b[^;]*?\bSET\b[^;]*?\bstatus\s*=" % table, re.I | re.S)
        for rel in rels:
            try:
                src = open(os.path.join(root, rel.replace("/", os.sep)),
                           encoding="utf-8-sig").read()
                tree = ast.parse(src)
            except (OSError, SyntaxError):
                continue
            fnmap = {n.name: n for n in ast.walk(tree)
                     if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
            for fn in [n for n in ast.walk(tree)
                       if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
                has_update = any(
                    isinstance(c, ast.Constant) and isinstance(c.value, str)
                    and pat.search(c.value)
                    for c in ast.walk(fn))
                if not has_update:
                    continue
                total_sites += 1
                if not validates(fn, fnmap, validator):
                    offenders.append("%s:%s() -> %s 미호출" % (rel, fn.name, validator))


    # ── registry_requests: 근거의 **모양이 다르다** (2026-09-01 추가) ──────────
    #
    #   payments/subscriptions 와 달리 `assert_*_transition()` 같은 함수가 없다.
    #   `docs/STATE_MACHINES.md` §3 이 적어 둔 실제 계약은 이렇다:
    #
    #       PAYMENT_REQUIRED ──결제 성공──> PENDING ──> PROCESSING ──> COMPLETED
    #                                          └──> FAILED <┘
    #       "PAYMENT_REQUIRED 는 **관리자 전이 대상이 아니다** — 결제 성공으로만 PENDING"
    #
    #   그래서 `admin.py:ALLOWED_TRANSITIONS` 는 **관리자 경로 전용**이고
    #   PAYMENT_REQUIRED 키가 없는 것이 의도다(그것이 유료 관문이다). 즉 이 테이블에는
    #   단일 canonical 전이표가 없고, 두 경로가 각자 정당하다:
    #
    #       admin.py:update_registry_request_status  ALLOWED_TRANSITIONS 조회 + 조건부 UPDATE
    #       payments.py:create_payment               조건부 UPDATE (WHERE status=PAYMENT_REQUIRED)
    #
    #   ★ 없는 canonical 함수를 여기서 발명하지 않는다(제품 정책 결정이다).
    #     대신 **두 경로가 공통으로 갖고 있는 것**만 강제한다 — 출발 상태를 WHERE 에
    #     묶는 조건부 UPDATE다. 이것이 없으면 (1) 전이 검증이 없고 (2) TOCTOU 로
    #     다른 요청의 결과를 덮어쓴다(Sprint 39 가 그래서 넣은 조건이다).
    #
    #     `UPDATE registry_requests SET status=? WHERE id=?` 처럼 출발 상태를 안 거는
    #     writer 가 새로 생기면 잡힌다.
    reg_pat = re.compile(r"UPDATE\s+registry_requests\b[^;]*?\bSET\b[^;]*?\bstatus\s*=", re.I | re.S)
    # WHERE 절에서 status 를 다시 거는가. `WHERE ... status = ?` / `AND status=?`
    reg_where = re.compile(r"\bWHERE\b[^;]*?\bstatus\s*=", re.I | re.S)
    reg_sites = 0
    for rel in rels:
        try:
            src = open(os.path.join(root, rel.replace("/", os.sep)), encoding="utf-8-sig").read()
            tree = ast.parse(src)
        except (OSError, SyntaxError):
            continue
        fnmap = {n.name: n for n in ast.walk(tree)
                 if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
        for fn in fnmap.values():
            for c in ast.walk(fn):
                if not (isinstance(c, ast.Constant) and isinstance(c.value, str)):
                    continue
                if not reg_pat.search(c.value):
                    continue
                reg_sites += 1
                if not reg_where.search(c.value):
                    offenders.append(
                        "%s:%s() -> registry_requests.status 를 출발 상태 조건 없이 UPDATE"
                        % (rel, fn.name))
        # 함수 밖(모듈 최상위)도 본다. document_queue 절에서 mutation 으로 확인한 것과
        # 같은 사각이다 — 지금 이 테이블에는 그런 writer 가 0곳이지만(실측 2026-09-01),
        # 보수 스크립트가 최상위에 SQL 을 두는 일이 흔해 언제든 생길 수 있다.
        inside_reg = {id(x) for fn in fnmap.values() for x in ast.walk(fn)}
        for c in ast.walk(tree):
            if id(c) in inside_reg:
                continue
            if not (isinstance(c, ast.Constant) and isinstance(c.value, str)):
                continue
            if not reg_pat.search(c.value):
                continue
            reg_sites += 1
            if not reg_where.search(c.value):
                offenders.append(
                    "%s:<module> -> registry_requests.status 를 출발 상태 조건 없이 UPDATE"
                    % rel)
    check_true("검사가 공허하지 않다(registry status UPDATE 를 찾았다) - %d곳" % reg_sites,
               reg_sites >= 3)

    # ── document_queue: 근거가 **두 가지**다 (2026-09-01 추가) ─────────────────
    #
    #   이 테이블에는 전이표가 없다(`grep QUEUE_TRANSITION` 0건). 있는 것은 어휘
    #   (`storage/database.py:QUEUE_STATUSES`, 8종)와 그 어휘를 지키는 검사뿐이다.
    #   **없는 전이표를 여기서 만들지 않는다** - 어떤 전이가 허용되는지는 제품 정책이다.
    #
    #   대신 실제 writer 15곳이 공통으로 갖고 있는 것만 강제한다. 실측(2026-09-01)
    #   결과 근거의 모양이 둘로 갈린다:
    #
    #     (1) 출발 상태 CAS   WHERE ... status=?      9곳
    #         enqueue_documents / claim_next_queue_item / claim_next_item_rows /
    #         requeue_changed_documents x2 / reset_stale_queue x3 / release_queue_rows
    #         + repair_empty_status_capture.py
    #     (2) 클레임 소유권    _claim_is_still_ours()  5곳
    #         mark_queue_done / mark_queue_failed x2 /
    #         mark_queue_skipped_expired / mark_queue_unsupported
    #
    #   (2) 가 (1) 과 다른 이유: 워커가 이미 그 행을 **점유한 채** 종결하므로, 출발
    #   상태가 아니라 "아직 내 것인가"를 물어야 한다. `mark_queue_done()` 주석이
    #   그 이유를 적어 뒀다 - 회수된 뒤 덮으면 방금 성공한 문서가 'failed' 로 뒤집힌다.
    #
    #   둘 중 **아무것도 없는** UPDATE 가 새로 생기면 잡는다. 리터럴을 쓰는 경우는
    #   `test_queue_safety_invariants.py` 의 어휘 검사가 따로 잡으므로 여기서는
    #   **바인딩을 쓰면서 가드가 없는** 경우가 대상이다(그 조합이 지금 사각이었다).
    #   ★ 2026-09-01 mutation 으로 이 검사 자체를 시험해 **사각 두 개**를 찾아 좁혔다.
    #     아래 두 줄이 그 결과다. 되돌리면 같은 구멍이 다시 열린다.
    #
    #     (C) 함수 밖(모듈 최상위)의 UPDATE 를 못 봤다.
    #         `ast.walk(fn)` 로 함수만 훑었기 때문이다. 일회성 보수 스크립트는
    #         최상위에 SQL 을 두는 일이 흔하다(실측: `step*.py` 가 그 모양이다.
    #         지금은 `.gitignore:128` 로 추적 대상이 아니라 통과하지만, 추적되는
    #         파일이 같은 모양으로 하나 생기면 그대로 빠져나간다).
    #
    #     (D) 소유권 근거를 **이름이 보이는가**로 봤다. `claim_token` 은 종결 함수의
    #         **매개변수 이름**이라, `_claim_is_still_ours()` 호출을 지워도 이름은 그대로
    #         남아 검사가 통과했다. 실제로 호출을 지운 변이를 못 잡았다.
    #         그래서 **호출이 있는가**로 바꾼다. 실측(2026-09-01) 결과 CAS 가 없는
    #         종결 writer 넷은 전부 실제로 그 함수를 호출하므로 오탐이 늘지 않는다.
    dq_pat = re.compile(r"UPDATE\s+document_queue\b[^;]*?\bSET\b[^;]*?\bstatus\s*=", re.I | re.S)
    dq_where = re.compile(r"\bWHERE\b.*?\bstatus\s*(?:=|IN)", re.I | re.S)
    DQ_OWNERSHIP_CALL = "_claim_is_still_ours"
    dq_sites = 0

    def dq_scan(node, src_, rel_, where):
        """이 노드 안의 document_queue status UPDATE 를 센다. 가드 없으면 적어 둔다."""
        n = 0
        owns = (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and DQ_OWNERSHIP_CALL in calls_in(node))
        for c in ast.walk(node):
            if not (isinstance(c, ast.Constant) and isinstance(c.value, str)):
                continue
            if not dq_pat.search(c.value):
                continue
            n += 1
            if not dq_where.search(c.value) and not owns:
                offenders.append(
                    "%s:%s -> document_queue.status 를 출발상태 CAS 도 소유권 확인도 "
                    "없이 UPDATE" % (rel_, where))
        return n

    for rel in rels:
        try:
            src = open(os.path.join(root, rel.replace("/", os.sep)), encoding="utf-8-sig").read()
            tree = ast.parse(src)
        except (OSError, SyntaxError):
            continue
        fns = [n for n in ast.walk(tree)
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
        for fn in fns:
            dq_sites += dq_scan(fn, src, rel, "%s()" % fn.name)
        # 함수 안에 있는 노드는 위에서 이미 봤다. 남은 것(모듈 최상위)만 훑는다.
        inside = {id(x) for fn in fns for x in ast.walk(fn)}
        for c in ast.walk(tree):
            if id(c) in inside:
                continue
            if not (isinstance(c, ast.Constant) and isinstance(c.value, str)):
                continue
            if not dq_pat.search(c.value):
                continue
            dq_sites += 1
            if not dq_where.search(c.value):
                offenders.append(
                    "%s:<module> -> document_queue.status 를 출발상태 CAS 도 소유권 확인도 "
                    "없이 UPDATE (함수 밖이라 소유권 확인이 있을 수 없다)" % rel)
    check_true("검사가 공허하지 않다(document_queue status UPDATE 를 찾았다) - %d곳" % dq_sites,
               dq_sites >= 10)

    check_true("검사가 공허하지 않다(상태 UPDATE 함수를 실제로 찾았다) - %d곳" % total_sites,
               total_sites >= 3)
    check("★ 전이 검증 없이 상태를 바꾸는 함수", sorted(offenders), [])
    if offenders:
        print("      -> 상태를 바꾸기 전에 전이 검증을 부르라."
              " 안 부르면 금지된 전이가 그대로 DB 에 들어간다")

    # 자기 검증: 탐지기가 실제로 두 모양을 구별하는가.
    probe_bad = ast.parse(
        "def f(conn):\n"
        "    conn.execute('UPDATE payments SET status=?, updated_at=? WHERE id=?')\n")
    probe_good = ast.parse(
        "def f(conn):\n"
        "    assert_payment_transition(a, b)\n"
        "    conn.execute('UPDATE payments SET status=?, updated_at=? WHERE id=?')\n")
    pat_p = re.compile(r"UPDATE\s+payments\b[^;]*?\bSET\b[^;]*?\bstatus\s*=", re.I | re.S)
    def probe(tree_):
        fn = tree_.body[0]
        has = any(isinstance(c, ast.Constant) and isinstance(c.value, str)
                  and pat_p.search(c.value) for c in ast.walk(fn))
        return has and "assert_payment_transition" not in calls_in(fn)
    check_true("자기 검증: 검증 없는 UPDATE 를 잡는다", probe(probe_bad))
    check_true("자기 검증: 검증 있는 UPDATE 는 안 잡는다", not probe(probe_good))


def run():
    test_payment_transitions_allowed()
    test_payment_transitions_forbidden()
    test_payment_terminal_and_is_paid()
    test_status_updates_call_transition_validation()
    test_subscription_transitions_allowed()
    test_subscription_transitions_forbidden()
    test_resolve_expected_status()
    test_is_entitled()
    test_grace_period_end()
    test_corrupt_expiry_is_safe_and_logged()
    test_status_vocabulary_is_not_hardcoded_in_sql()
    test_fixture_layer_stays_an_independent_source()
    test_canonical_sets_are_not_relisted_in_python()

    print("\n" + "=" * 55)
    if failures:
        print("FAILED (%d): %s" % (len(failures), ", ".join(failures)))
        return 1
    print("ALL TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(run())
