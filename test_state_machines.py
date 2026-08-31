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

from api.constants import PaymentStatus, SubscriptionStatus, is_paid
from api.v1.state_machines import (
    can_transition_payment, assert_payment_transition, is_terminal_payment,
    can_transition_subscription, assert_subscription_transition,
    is_entitled, resolve_expected_status, grace_period_end,
    InvalidTransition, GRACE_PERIOD_DAYS,
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
    from api.constants import (
        PaymentStatus, SubscriptionStatus, RegistryRequestStatus,
        DocumentStatus, DocumentType,
    )

    vocab = set()
    for enum in (PaymentStatus, SubscriptionStatus, RegistryRequestStatus,
                 DocumentStatus, DocumentType):
        vocab |= {e.value for e in enum}
    check_true("어휘를 열거형에서 뽑았다(검사가 공허하지 않다)", len(vocab) >= 20)

    # `status='X'` / `status IN ('X', ...)` / `doc_type IN ('X', ...)` 형태만 본다.
    col = r"(?:status|doc_type)"
    pat = re.compile(
        r"%s\s*(?:=|==)\s*'(%s)'|%s\s+IN\s*\(\s*'(%s)'"
        % (col, "|".join(re.escape(v) for v in sorted(vocab)),
           col, "|".join(re.escape(v) for v in sorted(vocab))),
        re.I)

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

    root = os.path.dirname(os.path.abspath(__file__))
    api_dir = os.path.join(root, "api", "v1")
    offenders = []
    scanned = 0
    for name in sorted(os.listdir(api_dir)):
        if not name.endswith(".py"):
            continue
        path = os.path.join(api_dir, name)
        scanned += 1
        for lineno, text in code_strings(path):
            if pat.search(text):
                offenders.append("api/v1/%s:%d" % (name, lineno))
    check_true("훑을 파일을 실제로 찾았다", scanned >= 10)
    check("SQL 에 상태값 리터럴이 박혀 있지 않다", sorted(set(offenders)), [])

    # 탐지기 자체 증명 -- 합성 입력에서는 반드시 잡히고, 바인딩은 잡히지 않아야 한다.
    check_true("탐지기가 `status='PENDING'` 을 잡는다",
               bool(pat.search("UPDATE t SET x=? WHERE status='PENDING'")))
    check_true("탐지기가 `IN ('READY',...)` 를 잡는다",
               bool(pat.search("WHERE status IN ('READY','FAILED')")))
    check_true("바인딩 형태는 잡지 않는다(오탐 없음)",
               not pat.search("UPDATE t SET status=? WHERE status=?"))
    check_true("어휘 밖 문자열은 잡지 않는다",
               not pat.search("WHERE status='NOT_A_REAL_STATUS'"))



def run():
    test_payment_transitions_allowed()
    test_payment_transitions_forbidden()
    test_payment_terminal_and_is_paid()
    test_subscription_transitions_allowed()
    test_subscription_transitions_forbidden()
    test_resolve_expected_status()
    test_is_entitled()
    test_grace_period_end()
    test_corrupt_expiry_is_safe_and_logged()
    test_status_vocabulary_is_not_hardcoded_in_sql()

    print("\n" + "=" * 55)
    if failures:
        print("FAILED (%d): %s" % (len(failures), ", ".join(failures)))
        return 1
    print("ALL TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(run())
