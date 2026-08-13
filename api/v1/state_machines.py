"""Payment / Subscription 상태 전이 규칙 (CTO 승인 2·3번).

상태 전이를 "허용된 것만" 명시적으로 선언하고, 그 외 전이는 전부 거부한다.
`api/v1/admin.py`의 `ALLOWED_TRANSITIONS`(등기부 신청)가 이미 쓰던 방식과 같은 패턴이다 —
새 개념을 도입하지 않고 기존 구조를 확장했다.

**기존 동작을 바꾸지 않는다**: 지금 결제는 `MockProvider`가 곧바로 `SUCCESS`를 만들고
그 뒤로 상태가 바뀌는 경로가 없다. 이 모듈은 *앞으로* 상태를 바꾸려는 코드(환불/Webhook/
Admin 조작)가 반드시 통과해야 할 관문이며, 지금 흐름에는 개입하지 않는다.
"""
import logging
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

from api.constants import (
    PaymentStatus, SubscriptionStatus,
    TERMINAL_PAYMENT_STATUSES, ENTITLED_SUBSCRIPTION_STATUSES,
)


class InvalidTransition(ValueError):
    """허용되지 않은 상태 전이. 호출부가 400으로 변환한다."""

    def __init__(self, current: str, target: str, domain: str):
        self.current, self.target, self.domain = current, target, domain
        super().__init__(f"{domain}: {current} -> {target} 전이는 허용되지 않습니다")


# ---------------------------------------------------------------------------
# Payment
#
# 실제 PG 흐름: CREATED -> READY(주문 생성) -> REQUESTED(사용자 결제) -> PAID(승인)
# 그 뒤 환불은 PAID -> PARTIAL_REFUND -> REFUNDED 또는 PAID -> REFUNDED.
#
# SUCCESS는 레거시 값이라 PAID와 **같은 전이 규칙**을 갖는다(기존 행이 환불 가능해야 하므로).
# ---------------------------------------------------------------------------
PAYMENT_TRANSITIONS: dict[str, set[str]] = {
    PaymentStatus.CREATED: {
        PaymentStatus.READY, PaymentStatus.FAILED, PaymentStatus.CANCELLED,
    },
    PaymentStatus.READY: {
        PaymentStatus.REQUESTED, PaymentStatus.FAILED,
        PaymentStatus.EXPIRED, PaymentStatus.CANCELLED,
    },
    PaymentStatus.REQUESTED: {
        # 승인 결과를 기다리는 단계. 성공/실패/만료/취소 어디로든 갈 수 있다.
        PaymentStatus.PAID, PaymentStatus.SUCCESS,
        PaymentStatus.FAILED, PaymentStatus.EXPIRED, PaymentStatus.CANCELLED,
    },
    PaymentStatus.PAID: {
        PaymentStatus.PARTIAL_REFUND, PaymentStatus.REFUNDED,
    },
    # 레거시 SUCCESS도 PAID와 동일하게 환불 가능해야 한다
    PaymentStatus.SUCCESS: {
        PaymentStatus.PARTIAL_REFUND, PaymentStatus.REFUNDED,
    },
    # 부분 환불 후 잔액까지 환불하면 전액 환불이 된다. 부분 환불의 반복도 허용한다.
    PaymentStatus.PARTIAL_REFUND: {
        PaymentStatus.PARTIAL_REFUND, PaymentStatus.REFUNDED,
    },
    # 종결 상태 — 여기서 나가는 전이는 없다
    PaymentStatus.FAILED: set(),
    PaymentStatus.EXPIRED: set(),
    PaymentStatus.CANCELLED: set(),
    PaymentStatus.REFUNDED: set(),
}


def can_transition_payment(current: str, target: str) -> bool:
    return target in PAYMENT_TRANSITIONS.get(current, set())


def assert_payment_transition(current: str, target: str) -> None:
    """허용되지 않으면 InvalidTransition을 던진다."""
    if target not in {s.value for s in PaymentStatus}:
        raise InvalidTransition(current, target, "Payment")
    if not can_transition_payment(current, target):
        raise InvalidTransition(current, target, "Payment")


def is_terminal_payment(status: str) -> bool:
    return status in TERMINAL_PAYMENT_STATUSES


# ---------------------------------------------------------------------------
# Subscription
#
# ACTIVE -> GRACE_PERIOD : 만료됐지만 유예 기간(결제 재시도 중). 아직 이용 가능
# GRACE_PERIOD -> ACTIVE : 갱신 결제 성공
# GRACE_PERIOD -> EXPIRED: 유예 기간도 지남
# ACTIVE -> PAUSED       : 사용자/운영자 일시정지
# PAUSED -> ACTIVE       : 재개
# * -> CANCELLED         : 해지(되돌릴 수 없음)
# EXPIRED -> ACTIVE      : 재구독(새 결제)
# ---------------------------------------------------------------------------
SUBSCRIPTION_TRANSITIONS: dict[str, set[str]] = {
    SubscriptionStatus.ACTIVE: {
        SubscriptionStatus.GRACE_PERIOD, SubscriptionStatus.PAUSED,
        SubscriptionStatus.EXPIRED, SubscriptionStatus.CANCELLED,
    },
    SubscriptionStatus.GRACE_PERIOD: {
        SubscriptionStatus.ACTIVE, SubscriptionStatus.EXPIRED,
        SubscriptionStatus.CANCELLED,
    },
    SubscriptionStatus.PAUSED: {
        SubscriptionStatus.ACTIVE, SubscriptionStatus.EXPIRED,
        SubscriptionStatus.CANCELLED,
    },
    # 만료된 구독은 재결제로 되살릴 수 있다
    SubscriptionStatus.EXPIRED: {
        SubscriptionStatus.ACTIVE, SubscriptionStatus.CANCELLED,
    },
    # 해지는 최종 상태 — 다시 쓰려면 새 구독을 만든다
    SubscriptionStatus.CANCELLED: set(),
}

# 만료 후 유예 기간. 결제 실패 직후 즉시 차단하면 카드 갱신 중인 정상 사용자가 끊긴다.
GRACE_PERIOD_DAYS = 3


def can_transition_subscription(current: str, target: str) -> bool:
    return target in SUBSCRIPTION_TRANSITIONS.get(current, set())


def assert_subscription_transition(current: str, target: str) -> None:
    if target not in {s.value for s in SubscriptionStatus}:
        raise InvalidTransition(current, target, "Subscription")
    if not can_transition_subscription(current, target):
        raise InvalidTransition(current, target, "Subscription")


def is_entitled(status: str, expires_at: Optional[str], at: datetime = None) -> bool:
    """지금 서비스를 이용할 수 있는 구독인지.

    판정을 `resolve_expected_status()`에 위임한다 — 그쪽이 이미 "지금 있어야 할 상태"의
    단일 기준이기 때문이다. 여기서 만료 시각을 따로 비교하면 규칙이 두 곳에 생겨 어긋난다.

    ★ 실제로 그 버그가 있었다: 예전 구현은 상태가 GRACE_PERIOD여도 `expires_at > now`를
    요구했는데, 유예 기간은 **정의상 만료 시각을 지난 뒤**의 상태다. 그래서 승인된 유예
    정책이 코드에서는 한 번도 작동하지 않았다(만료 즉시 차단).
    유예의 기한은 `expires_at`이 아니라 `expires_at + GRACE_PERIOD_DAYS`다.

    `expires_at`이 None이면 무기한으로 본다(기존 `has_active_subscription`과 동일한 해석).
    """
    return resolve_expected_status(status, expires_at, at) in ENTITLED_SUBSCRIPTION_STATUSES


def resolve_expected_status(status: str, expires_at: Optional[str],
                            at: datetime = None) -> str:
    """시간 경과만으로 결정되는 "지금 있어야 할 상태"를 계산한다(자동 만료).

    별도 배치 없이 조회 시점에 판정할 수 있게 순수 함수로 둔다 — 크론이 없는 환경에서
    배치에 의존하면 "배치가 안 돌아서 만료가 안 됨" 같은 사고가 난다.

    ACTIVE인데 만료시각이 지났으면 → 유예 기간 안이면 GRACE_PERIOD, 지났으면 EXPIRED.
    PAUSED/CANCELLED는 시간과 무관하게 유지된다(사용자 의사로 정해진 상태이므로).
    """
    now = at or datetime.now()
    if status in (SubscriptionStatus.PAUSED, SubscriptionStatus.CANCELLED,
                  SubscriptionStatus.EXPIRED):
        return status
    if not expires_at:
        return status

    expires = _parse(expires_at)
    if expires is None or now < expires:
        return status if status != SubscriptionStatus.GRACE_PERIOD else SubscriptionStatus.GRACE_PERIOD
    # 만료 시각을 지났다 — 유예 기간이 남았는지 확인
    if now < expires + timedelta(days=GRACE_PERIOD_DAYS):
        return SubscriptionStatus.GRACE_PERIOD
    return SubscriptionStatus.EXPIRED


def grace_period_end(expires_at: str) -> Optional[str]:
    expires = _parse(expires_at)
    if expires is None:
        return None
    return (expires + timedelta(days=GRACE_PERIOD_DAYS)).isoformat()


def _parse(value: str) -> Optional[datetime]:
    """ISO 문자열 파싱. 형식이 깨져 있으면 None을 돌려 호출부가 상태를 바꾸지 않게 한다
    (파싱 실패를 '만료'로 해석하면 정상 구독자가 끊긴다).

    2026-08-11 Sprint 56: **반드시 로그를 남긴다.** 폴백 자체는 옳지만 예전에는 조용했다 —
    `expires_at`이 깨진 구독은 `effective_status()`가 영원히 만료로 넘기지 않으므로
    **무기한 유효한 구독**이 되고, 그 사실을 알 방법이 없었다. 안전한 방향으로 실패하는
    것과 실패를 숨기는 것은 다르다.
    """
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        logger.warning(
            "구독 만료 시각을 해석할 수 없습니다 (expires_at=%r) ― 만료 판정을 보류합니다. "
            "이 구독은 만료되지 않으므로 데이터 점검이 필요합니다", value
        )
        return None
