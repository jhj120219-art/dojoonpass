"""도메인 상태값 / Error Code 단일 정의 (CTO 승인 9·10번).

**기존 동작을 절대 바꾸지 않는다** — 문자열 값은 지금 DB에 들어있는 값 그대로다.
이 모듈은 흩어져 있던 리터럴을 한곳에 모아 오타와 누락을 막는 것이 목적이며,
값 자체를 새로 정하거나 바꾸지 않는다.

`str, Enum`을 상속시킨 이유: SQLite 바인딩과 JSON 직렬화에서 그냥 문자열처럼 동작하므로
`status == PaymentStatus.PAID`와 `status == "PAID"`가 모두 참이 된다. 기존 코드가
문자열을 그대로 쓰고 있어도 깨지지 않는다.
"""
import unicodedata
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
    """`document_status.status` — 화면이 읽는 수집 상태.

    ★ 2026-08-31 정정: **`NO_IMAGE` 가 빠져 있었다.** 이 열거형은 여섯 값만 선언했는데,
      제품은 일곱 번째 값을 실제로 쓰고 있었다 —

          doc_worker.py:381        done_status = "NO_IMAGE" if result.get("no_asset") else "READY"
          api/v1/item.py           `_images_status()` 가 NO_IMAGE 를 그대로 내보낸다
          storage/database.py      DOC_STATUS_HAS_ARTIFACT = ("READY", "NO_IMAGE")
          audit_asset_integrity.py 정합성 판정이 NO_IMAGE 를 정상으로 센다
          properties/[id]/page.tsx DOC_STATUS_LABEL 에 '사진 없음' 으로 있다

      즉 DB·수집기·API·화면·감사기가 전부 아는 값을 **상태값 정의만 몰랐다.**
      이 모듈의 목적이 "흩어져 있던 리터럴을 한곳에 모아 오타와 누락을 막는 것"이므로
      그 목적에 반하는 상태였다. 값은 이미 DB 에 들어 있는 것 그대로 옮긴다.

      NO_IMAGE 를 FAILED 로 뭉뚱그리면 안 되는 이유가 코드 주석에 이미 적혀 있다 —
      "법원이 사진을 제공하지 않는다"는 **확인된 답**이지 실패가 아니고, 재시도해도
      결과가 같다. 실패로 보이면 사용자가 기다리면 생길 것처럼 오해한다.

    ★ OCR / PARSING / ANALYZING 은 **선언만 있고 아무도 쓰지 않는다**
      (2026-08-31 실측: 저장소 전체에서 이 값을 쓰는 코드 0곳, DB 행 0건).
      파이프라인 후반부를 위해 자리를 잡아 둔 값이며, 지우는 것은 상태 체계 축소라
      제품 결정이다. "정의됐다"와 "쓰인다"가 다르다는 것은 `docs/ERROR_CODES.md` 가
      Error Code 40개 중 19개만 방출된다고 적어 둔 것과 같은 구분이다.
    """
    COLLECTING = "COLLECTING"
    OCR = "OCR"
    PARSING = "PARSING"
    ANALYZING = "ANALYZING"
    READY = "READY"
    NO_IMAGE = "NO_IMAGE"
    FAILED = "FAILED"


# 지금 **실제로 쓰이는** 값. 위 열거형은 자리만 잡아 둔 값(OCR/PARSING/ANALYZING)을
# 포함하므로, "DB 에 이 값이 있어야 정상"을 판정할 때는 이쪽을 쓴다.
# `test_queue_safety_invariants.py` 의
# `test_document_status_vocabulary_is_declared_in_one_place` 가 실제 DB·코드와 대조한다.
DOCUMENT_STATUSES_IN_USE = frozenset({
    DocumentStatus.COLLECTING,
    DocumentStatus.READY,
    DocumentStatus.NO_IMAGE,
    DocumentStatus.FAILED,
})


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
    # 마이리스트 가져오기 (2026-08-28, api/v1/favorite_import.py)
    FAVORITE_IMPORT_EMPTY = "FAVORITE_IMPORT_EMPTY"
    FAVORITE_IMPORT_TOO_LARGE = "FAVORITE_IMPORT_TOO_LARGE"
    # 메모/태그 테이블(migration 026)이 아직 적용되지 않은 환경. **조용히 성공하지
    # 않기 위해** 별도 코드를 둔다 - INTERNAL_ERROR 로 뭉뚱그리면 화면이 "서버 오류"를
    # 띄워, 운영자가 고쳐야 할 것(마이그레이션 적용)을 알 수 없다.
    FAVORITE_NOTE_UNAVAILABLE = "FAVORITE_NOTE_UNAVAILABLE"
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


# ---------------------------------------------------------------------------
# SQLite INTEGER 범위 (2026-08-17 Sprint 144)
#
# 왜 필요한가 — 파이썬 int는 무한 정밀도인데 SQLite INTEGER는 64비트다.
# FastAPI의 `item_id: int` 경로 파라미터는 자릿수를 제한하지 않으므로
# `/api/v1/item/999999999999999999999` 같은 요청이 그대로 통과해 sqlite3에서
# `OverflowError: Python int too large to convert to SQLite INTEGER`로 터진다.
#
# 실측 2026-08-17 — **인증 없이** 다음 세 공개 엔드포인트가 전부 500을 냈다:
#     GET /api/v1/item/{item_id}
#     GET /api/v1/item/{item_id}/documents/{doc_type}
#     GET /api/v1/item/{item_id}/images/{seq}
#
# 데이터가 새지는 않지만 **없는 물건을 물었을 때 404가 아니라 500이 나가고**
# 서버 로그에 스택 트레이스가 쌓인다(운영 알림을 만드는 순간 노이즈가 된다).
# 이 저장소가 반복해서 지켜 온 원칙 — "모르는 것에 그럴듯한 답을 지어내지 않되,
# 실패는 정직한 상태 코드로 말한다" — 에 어긋나는 자리다.
#
# 범위를 벗어난 id는 **어떤 행도 될 수 없으므로 404가 정확한 답이다**(422가 아니다:
# 형식은 올바른 정수이고, 다만 존재할 수 없는 값일 뿐이다. 음수 id가 이미 404인 것과
# 같은 취급이라 기존 동작과도 일관된다).
SQLITE_MAX_INT = 2 ** 63 - 1
SQLITE_MIN_INT = -(2 ** 63)


def is_sqlite_int(value: int) -> bool:
    """SQLite INTEGER로 바인딩할 수 있는 값인가."""
    return SQLITE_MIN_INT <= value <= SQLITE_MAX_INT


# ---------------------------------------------------------------------------
# LIKE 패턴 이스케이프 (2026-09-02 신설)
# ---------------------------------------------------------------------------
# 검색 필터는 사용자가 친 글자를 `f"%{값}%"` 로 감싸 `LIKE ?` 에 바인딩한다.
# 바인딩이라 **SQL 주입은 아니다.** 그런데 `%` 와 `_` 는 LIKE 문법에서 **와일드카드**라
# 바인딩되어도 그대로 살아 있다. 즉 필터로 좁히라고 준 글자가 **넓히는 지시**가 된다.
#
# 실측(2026-09-02, auction_item 1,876행):
#
#     address_detail=아파트   ->   94행   (정상)
#     address_detail=아_트    ->   94행   <- '_' 가 아무 글자 하나와 맞는다
#     address_detail=아%트    ->  187행   <- '%' 가 아무 글자나와 맞는다
#     address_detail=%       -> 1876행   <- **필터가 전부를 돌려준다**
#     court_name/status/case_no/sigungu 도 전부 같다
#
# 오류도 빈 화면도 아니다. 사용자는 자기가 친 글자로 **좁혀진 결과**를 보고 있다고
# 믿는데 실제로는 남의 물건이 섞여 있다 — 이 저장소가 반복해서 잡아 온 "조용한 실패"다.
#
# 규칙은 여기 한 곳에만 둔다. 호출부는 반드시 `ESCAPE '\'` 를 함께 적어야 한다
# (SQLite 는 ESCAPE 절이 없으면 역슬래시를 특별 취급하지 않는다).
# 역슬래시를 **가장 먼저** 바꾼다 — 나중에 바꾸면 `%`->`\%` 로 넣은 역슬래시를 다시
# 이스케이프해 `\\%` 가 되어 원래 뜻이 깨진다.
LIKE_ESCAPE_CHAR = "\\"


def escape_like(value: str) -> str:
    """LIKE 패턴에서 `%` `_` 를 **글자 그대로** 찾도록 이스케이프한다.

    호출부 예: ``"full_address LIKE ? ESCAPE '\\\\'"`` + ``f"%{escape_like(v)}%"``

    감싸는 `%` 는 호출부가 붙인다 — 그것은 의도된 와일드카드라 이스케이프 대상이 아니다.
    """
    if not value:
        return ""
    return (str(value)
            .replace(LIKE_ESCAPE_CHAR, LIKE_ESCAPE_CHAR * 2)
            .replace("%", LIKE_ESCAPE_CHAR + "%")
            .replace("_", LIKE_ESCAPE_CHAR + "_"))


# ---------------------------------------------------------------------------
# 한글 정규화 (2026-09-02 신설)
# ---------------------------------------------------------------------------
# 같은 글자가 유니코드에서 **두 가지로 표현**된다.
#
#     '강' = U+AC15                     (NFC, 완성형 한 글자)
#     '강' = U+1100 U+1161 U+11BC       (NFD, 자모 세 글자)
#
# 화면에는 똑같이 보이는데 **바이트가 다르므로 SQL 비교/LIKE 가 맞지 않는다.**
# macOS 는 파일 이름을 NFD 로 보관해서, 거기서 복사한 주소·사건번호를 붙여 넣으면
# NFD 가 그대로 들어온다. 사용자는 "분명히 있는 물건인데 0건"을 보게 된다 —
# 오류도 아니고 빈 화면이라 원인을 짐작할 수도 없다.
#
# 실측(2026-09-02, 이 저장소의 실 DB / 수정 전):
#
#     auction_item 의 문자열 12,957개 중 NFC 가 아닌 값 **0개** (DB 는 전부 NFC)
#     그런데 질의를 NFD 로 주면
#         address_detail=아파트  NFC -> 94건 / NFD -> **0건**
#         sido=서울             NFC -> 275건 / NFD -> **0건**
#
# 즉 **DB 는 깨끗한데 입력만 다른 표현으로 오면 아무것도 못 찾는다.**
#
# 그래서 질의 입력을 NFC 로 맞춘다. NFC 입력에 대해서는 `NFC(x) == x` 라
# **지금 들어오는 모든 트래픽의 동작이 그대로다**(순수 가산).
#
# ※ 이 함수는 질의 쪽만 고친다. DB 쪽이 NFC 라는 전제 위에 서 있으므로, 그 전제는
#   `test_search.py` 가 불변식으로 지킨다 — 크롤러가 NFD 를 넣기 시작하면 그쪽이 먼저 운다.
#   (DB 를 되돌리는 것은 백필이고 승인 영역이라 여기서 하지 않는다.)
def to_nfc(value: str) -> str:
    """검색 입력을 NFC 로 맞춘다. 빈 값/None 은 그대로 빈 문자열."""
    if not value:
        return ""
    return unicodedata.normalize("NFC", str(value))
