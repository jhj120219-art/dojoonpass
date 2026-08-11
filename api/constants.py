"""도메인 상태값 / Error Code 단일 정의 (CTO 승인 9·10번).

**기존 동작을 절대 바꾸지 않는다** — 문자열 값은 지금 DB에 들어있는 값 그대로다.
이 모듈은 흩어져 있던 리터럴을 한곳에 모아 오타와 누락을 막는 것이 목적이며,
값 자체를 새로 정하거나 바꾸지 않는다.

`str, Enum`을 상속시킨 이유: SQLite 바인딩과 JSON 직렬화에서 그냥 문자열처럼 동작하므로
`status == PaymentStatus.PAID`와 `status == "PAID"`가 모두 참이 된다. 기존 코드가
문자열을 그대로 쓰고 있어도 깨지지 않는다.
"""
from enum import Enum


class StrEnum(str, Enum):
    """문자열처럼 동작하는 Enum. `str(x)`가 "ClassName.MEMBER"가 되지 않도록 __str__을 고정한다."""

    def __str__(self) -> str:
        return self.value


# ---------------------------------------------------------------------------
# Payment
# ---------------------------------------------------------------------------
class PaymentStatus(StrEnum):
    """결제 상태 (CTO 승인 2번으로 확장).

    ★ SUCCESS는 **레거시 값**이다. 기존 payments 행과 MockProvider가 이 값을 쓰고 있어
    제거하면 기존 데이터가 해석 불가가 된다(Breaking Change). PAID와 동의어로 유지하고,
    신규 코드는 PAID를 쓴다. 조회 시에는 두 값을 모두 '성공'으로 취급해야 한다
    (`is_paid()` 참고).
    """
    CREATED = "CREATED"                  # 결제 레코드만 생성됨(주문 전)
    READY = "READY"                      # PG 주문 생성 완료, 결제창 호출 대기
    REQUESTED = "REQUESTED"              # 사용자가 결제창에서 결제를 시도함(승인 대기)
    PAID = "PAID"                        # 최종 승인 완료
    SUCCESS = "SUCCESS"                  # [레거시] PAID와 동의어 — 기존 데이터 호환용
    FAILED = "FAILED"                    # 승인 실패/거절
    EXPIRED = "EXPIRED"                  # 결제 시한 만료(가상계좌 미입금 등)
    CANCELLED = "CANCELLED"              # 승인 전 취소
    PARTIAL_REFUND = "PARTIAL_REFUND"    # 부분 환불
    REFUNDED = "REFUNDED"                # 전액 환불


# 결제가 "돈을 받은 상태"인지 판정할 때 쓰는 집합.
# PARTIAL_REFUND도 일부 금액은 남아있으므로 유효한 결제로 본다.
PAID_STATUSES = frozenset({
    PaymentStatus.PAID, PaymentStatus.SUCCESS, PaymentStatus.PARTIAL_REFUND,
})

# 더 이상 상태가 바뀌지 않는 종결 상태.
TERMINAL_PAYMENT_STATUSES = frozenset({
    PaymentStatus.FAILED, PaymentStatus.EXPIRED,
    PaymentStatus.CANCELLED, PaymentStatus.REFUNDED,
})


def is_paid(status: str) -> bool:
    """레거시 SUCCESS와 신규 PAID를 모두 '결제됨'으로 취급한다."""
    return status in PAID_STATUSES


class PaymentType(StrEnum):
    SUBSCRIPTION = "SUBSCRIPTION"
    OVERAGE_USAGE = "OVERAGE_USAGE"


class BillingCycle(StrEnum):
    MONTHLY = "MONTHLY"
    YEARLY = "YEARLY"


# ---------------------------------------------------------------------------
# Subscription
# ---------------------------------------------------------------------------
class SubscriptionStatus(StrEnum):
    """구독 상태 (CTO 승인 3번으로 확장). ACTIVE는 기존 값 그대로다."""
    ACTIVE = "ACTIVE"                # 정상 이용 중
    GRACE_PERIOD = "GRACE_PERIOD"    # 만료됐지만 유예 기간 — 아직 이용 가능
    PAUSED = "PAUSED"                # 일시정지 — 이용 불가, 재개 가능
    EXPIRED = "EXPIRED"              # 만료 — 이용 불가
    CANCELLED = "CANCELLED"          # 해지 — 이용 불가, 재개 불가


# 구독이 "지금 유효한지"(Premium 판정). GRACE_PERIOD는 아직 서비스를 제공한다 —
# 결제 실패 직후 즉시 차단하면 카드 갱신 중인 정상 사용자가 끊기기 때문이다.
ENTITLED_SUBSCRIPTION_STATUSES = frozenset({
    SubscriptionStatus.ACTIVE, SubscriptionStatus.GRACE_PERIOD,
})


class PlanCode(StrEnum):
    BASIC = "BASIC"
    PRO = "PRO"


# ---------------------------------------------------------------------------
# Registry (등기부 신청)
# ---------------------------------------------------------------------------
class RegistryRequestStatus(StrEnum):
    PENDING = "PENDING"                        # 접수됨(무료 or 결제 완료)
    PAYMENT_REQUIRED = "PAYMENT_REQUIRED"      # 무료 한도 초과 — 결제 필요
    PROCESSING = "PROCESSING"                  # 운영자 처리 중
    COMPLETED = "COMPLETED"                    # 발급 완료(doc_url 존재)
    FAILED = "FAILED"                          # 발급 실패(reason 존재)


class RegistryCreditReason(StrEnum):
    """무료 횟수 변동 사유 (CTO 승인 4번으로 확장)."""
    GRANT = "GRANT"          # 관리자 지급
    DEDUCT = "DEDUCT"        # 관리자 회수
    RESET = "RESET"          # 그 달 조정 초기화
    USAGE = "USAGE"          # 사용(등기부 신청으로 소진)
    EVENT = "EVENT"          # 이벤트 지급
    REFUND = "REFUND"        # 환불로 인한 복구
    OTHER = "OTHER"          # 기타 변경


# 원장 합계에 실제로 반영되는 사유(관리자 조정만).
# USAGE는 registry_usage가 이미 세고 있으므로 합계에 넣으면 이중 차감이 된다 —
# 로그(registry_credit_logs)에는 남기되 조정 합계에는 넣지 않는다.
ADJUSTMENT_REASONS = frozenset({
    RegistryCreditReason.GRANT, RegistryCreditReason.DEDUCT,
    RegistryCreditReason.RESET, RegistryCreditReason.EVENT,
    RegistryCreditReason.REFUND,
})


# ---------------------------------------------------------------------------
# Document (크롤러 수집 문서)
# ---------------------------------------------------------------------------
class DocumentStatus(StrEnum):
    COLLECTING = "COLLECTING"
    OCR = "OCR"
    PARSING = "PARSING"
    ANALYZING = "ANALYZING"
    READY = "READY"
    FAILED = "FAILED"


class DocumentType(StrEnum):
    SPEC = "SPEC"
    STATUS = "STATUS"
    APPRAISAL = "APPRAISAL"


# ---------------------------------------------------------------------------
# Admin
# ---------------------------------------------------------------------------
class AdminRole(StrEnum):
    ADMIN = "ADMIN"
    SUPER_ADMIN = "SUPER_ADMIN"


class AuditAction(StrEnum):
    """audit_logs.action (CTO 승인 5번)."""
    REGISTRY_STATUS_CHANGE = "REGISTRY_STATUS_CHANGE"
    REGISTRY_CREDIT_ADJUST = "REGISTRY_CREDIT_ADJUST"
    SUBSCRIPTION_STATUS_CHANGE = "SUBSCRIPTION_STATUS_CHANGE"
    PAYMENT_STATUS_CHANGE = "PAYMENT_STATUS_CHANGE"
    SOFT_DELETE = "SOFT_DELETE"
    RESTORE = "RESTORE"


class AuditTargetType(StrEnum):
    REGISTRY_REQUEST = "REGISTRY_REQUEST"
    REGISTRY_CREDIT = "REGISTRY_CREDIT"
    SUBSCRIPTION = "SUBSCRIPTION"
    PAYMENT = "PAYMENT"
    # 2026-08-11 Sprint 53 신설. Webhook 재처리는 결제에 연결되지 못한 노티에도 시도할 수 있어
    # (예: 아직 우리 payments row가 없는 이른 노티) 대상이 결제가 아니라 **수신 기록**인 경우가
    # 있다. 그때 PAYMENT으로 기록하면 존재하지 않는 결제를 가리키는 감사 행이 생긴다 —
    # 실제로 `target_id="webhook:234"` 같은 값을 넣었다가 dangling 감사 행으로 검출됐다.
    PAYMENT_WEBHOOK = "PAYMENT_WEBHOOK"
    USER = "USER"


# ---------------------------------------------------------------------------
# Error Code (CTO 승인 9번)
#
# 형식: <DOMAIN>_<SNAKE_CASE>. 클라이언트가 문구가 아니라 코드로 분기할 수 있게 한다
# (한국어 메시지는 언제든 바뀔 수 있고, 문구 비교는 깨지기 쉽다).
#
# ★ 기존 응답의 `message` 필드는 그대로 유지한다 — 프론트가 `result.message`를 읽고 있어
#   제거하면 Breaking Change다. `error`는 **추가** 필드다(api/auth.py:fail 참고).
# ---------------------------------------------------------------------------
class ErrorCode(StrEnum):
    # AUTH
    AUTH_TOKEN_MISSING = "AUTH_TOKEN_MISSING"
    AUTH_TOKEN_INVALID = "AUTH_TOKEN_INVALID"
    AUTH_SECRET_NOT_CONFIGURED = "AUTH_SECRET_NOT_CONFIGURED"

    # PAY
    PAY_INVALID_TYPE = "PAY_INVALID_TYPE"
    PAY_INVALID_PLAN = "PAY_INVALID_PLAN"
    PAY_INVALID_BILLING_CYCLE = "PAY_INVALID_BILLING_CYCLE"
    PAY_AMOUNT_MISMATCH = "PAY_AMOUNT_MISMATCH"
    PAY_NO_TARGET_REQUEST = "PAY_NO_TARGET_REQUEST"
    PAY_ALREADY_PROCESSED = "PAY_ALREADY_PROCESSED"
    PAY_FAILED = "PAY_FAILED"
    PAY_NOT_FOUND = "PAY_NOT_FOUND"
    PAY_INVALID_TRANSITION = "PAY_INVALID_TRANSITION"

    # SEARCH
    SEARCH_INVALID_SORT = "SEARCH_INVALID_SORT"
    SEARCH_FAILED = "SEARCH_FAILED"
    SEARCH_PRESET_NAME_REQUIRED = "SEARCH_PRESET_NAME_REQUIRED"
    SEARCH_PRESET_NAME_TOO_LONG = "SEARCH_PRESET_NAME_TOO_LONG"
    SEARCH_PRESET_TOO_LARGE = "SEARCH_PRESET_TOO_LARGE"
    SEARCH_PRESET_LIMIT_EXCEEDED = "SEARCH_PRESET_LIMIT_EXCEEDED"
    SEARCH_PRESET_NOT_FOUND = "SEARCH_PRESET_NOT_FOUND"

    # REGISTRY
    REGISTRY_ITEM_NOT_FOUND = "REGISTRY_ITEM_NOT_FOUND"
    REGISTRY_SUBSCRIPTION_REQUIRED = "REGISTRY_SUBSCRIPTION_REQUIRED"
    REGISTRY_REQUEST_NOT_FOUND = "REGISTRY_REQUEST_NOT_FOUND"
    REGISTRY_NOT_COMPLETED = "REGISTRY_NOT_COMPLETED"
    REGISTRY_DOCUMENT_NOT_FOUND = "REGISTRY_DOCUMENT_NOT_FOUND"
    REGISTRY_INVALID_TRANSITION = "REGISTRY_INVALID_TRANSITION"
    REGISTRY_CREDIT_INVALID_AMOUNT = "REGISTRY_CREDIT_INVALID_AMOUNT"
    REGISTRY_CREDIT_INVALID_REASON = "REGISTRY_CREDIT_INVALID_REASON"

    # ADMIN
    ADMIN_KEY_NOT_CONFIGURED = "ADMIN_KEY_NOT_CONFIGURED"
    ADMIN_FORBIDDEN = "ADMIN_FORBIDDEN"
    ADMIN_INSUFFICIENT_ROLE = "ADMIN_INSUFFICIENT_ROLE"
    ADMIN_INVALID_STATUS = "ADMIN_INVALID_STATUS"
    ADMIN_TARGET_NOT_FOUND = "ADMIN_TARGET_NOT_FOUND"
    ADMIN_INVALID_PARAMETER = "ADMIN_INVALID_PARAMETER"

    # SUBSCRIPTION
    SUBSCRIPTION_NOT_FOUND = "SUBSCRIPTION_NOT_FOUND"
    SUBSCRIPTION_INVALID_TRANSITION = "SUBSCRIPTION_INVALID_TRANSITION"
    SUBSCRIPTION_ALREADY_CANCELLED = "SUBSCRIPTION_ALREADY_CANCELLED"

    # FAVORITE / COMMON
    FAVORITE_ALREADY_EXISTS = "FAVORITE_ALREADY_EXISTS"
    FAVORITE_NOT_FOUND = "FAVORITE_NOT_FOUND"
    ITEM_NOT_FOUND = "ITEM_NOT_FOUND"
    INTERNAL_ERROR = "INTERNAL_ERROR"


# 도메인 접두사 → 담당 영역. 문서/테스트가 이 표를 기준으로 검증한다.
ERROR_CODE_DOMAINS = {
    "AUTH": "인증 (api/auth.py)",
    "PAY": "결제 (api/v1/payments.py)",
    "SEARCH": "검색·검색조건 저장 (api/v1/search.py, search_presets.py)",
    "REGISTRY": "등기부 신청·무료횟수 (api/v1/registry.py, registry_credits.py)",
    "ADMIN": "관리자 (api/v1/admin.py)",
    "SUBSCRIPTION": "구독 (api/v1/subscriptions.py)",
    "FAVORITE": "관심물건 (api/v1/favorites.py)",
    "ITEM": "물건 공통",
    "INTERNAL": "서버 내부 오류",
}
