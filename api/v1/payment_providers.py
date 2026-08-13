import hashlib
import hmac
import logging
import os
import uuid
from dataclasses import dataclass
from typing import Any, Optional

from api.constants import PaymentStatus

logger = logging.getLogger(__name__)

# PG 실연동 준비 단계(PAYMENT_PROVIDER env var로 교체 가능). 지금은 mock만 실제로 동작하고
# kginicis는 자리만 잡아둔 상태다 — 계약/API Key 발급 전이라 실제 승인 로직은 구현하지 않는다.
# api/v1/payments.py는 이 모듈의 get_payment_provider()만 알면 되고, provider 내부 구현이
# 바뀌어도 payments.py를 다시 고칠 필요가 없도록 인터페이스를 고정한다.
#
# PG사(2026-08-06 CTO 확정): **KG이니시스**. TossProvider/PortOneProvider는 확정 이전의
# 후보 자리로, 폐기 예정이며 신규 코드에서 참조하지 않는다(삭제는 승인 필요 작업이라 유지).
#
# v2(2026-08-05): charge()는 "요청하면 즉시 승인/거절"하는 단일 동기 호출만 모델링해
# 실제 PG 흐름(주문 생성→결제창→Webhook→PG 검증→최종 승인)을 표현하지
# 못했다. 아래 5개 메서드를 추가해 그 흐름 각 단계를 인터페이스로 분리한다. 이번 Sprint는
# 인터페이스와 MockProvider 구현까지만 — api/v1/payments.py는 아직 이 메서드들을 호출하지
# 않는다(기존 charge() 호출 경로 그대로, 회귀 없음). 실제 엔드포인트 연결은 PG사 확정 후
# 별도 Sprint에서 진행한다.


@dataclass
class ChargeResult:
    status: str  # payments.status와 동일한 값(api/constants.py:PaymentStatus)만 사용한다
    pg_provider: Optional[str]
    pg_transaction_id: Optional[str]


@dataclass
class OrderResult:
    """create_order()의 결과. 클라이언트가 PG 결제창을 여는 데 필요한 주문 식별자."""
    order_id: str
    pg_provider: Optional[str]


@dataclass
class WebhookEvent:
    """handle_webhook()의 결과. PG가 보낸 원본 payload를 내부에서 다루기 쉬운 형태로 정규화한다."""
    event_type: str  # 예: PAYMENT_CONFIRMED / PAYMENT_CANCELLED
    pg_transaction_id: Optional[str]
    status: str  # payments.status와 동일한 값


class PaymentProvider:
    # 미구현 메서드는 **반드시 사유가 담긴** NotImplementedError를 던진다 (2026-08-13 Sprint 78).
    #
    # 예전에는 전부 `raise NotImplementedError`(메시지 없음)였다. 그 예외는 조용히 사라지지
    # 않고 사용자·운영자에게 그대로 노출되는데, 메시지가 비어 있어 **원인이 통째로 빠졌다.**
    #
    #     api/v1/payments.py:refund_payment()  except NotImplementedError as e:
    #         log_payment_event(..., error_message=str(e))   -> payment_logs.error_message = ""
    #         raise RefundError(..., f"환불 처리에 실패했습니다: {e}")  -> "...실패했습니다: "
    #
    # 실측(Sprint 78 신규 검사): `PAYMENT_PROVIDER=kginicis`로 환불을 시도하면 원장에
    # `status=FAILED, error_message=''`가 남는다. 실패한 사실은 추적되지만 **왜 실패했는지는
    # 어디에도 없다.** 이 저장소가 진단에 대해 반복해서 지킨 원칙("조용히 넘기면 원인을
    # 추적할 수 없으므로 반드시 남긴다")이 이 경로에서만 빠져 있었다.
    #
    # 어느 provider의 어느 단계인지까지 담는다 — provider를 교체하는 전환기에는 "무엇이 아직
    # 준비되지 않았는가"가 바로 그 두 정보다. TossProvider/PortOneProvider가 이미 같은 방식으로
    # 사유를 담고 있었으므로(폐기 안내), 기본 구현을 그 수준에 맞춘 것이다.
    def _not_implemented(self, method: str) -> NotImplementedError:
        return NotImplementedError(
            "%s.%s()는 아직 구현되지 않았습니다 (PG 실연동 대기 중)"
            % (type(self).__name__, method)
        )

    def charge(self, payment_type: str, amount: int, metadata: Optional[str]) -> ChargeResult:
        raise self._not_implemented("charge")

    def create_order(self, payment_type: str, amount: int, metadata: Optional[str]) -> OrderResult:
        """주문 생성 — 실제 PG에서는 클라이언트가 결제창을 열 때 쓸 order_id를 발급받는 단계."""
        raise self._not_implemented("create_order")

    def confirm_payment(self, order_id: str, pg_transaction_id: str, amount: int) -> ChargeResult:
        """결제 승인 — 사용자가 PG 결제창에서 결제를 마친 뒤, 서버가 최종 승인을 확정하는 단계."""
        raise self._not_implemented("confirm_payment")

    def cancel_payment(self, pg_transaction_id: str, reason: Optional[str] = None) -> ChargeResult:
        """결제 취소/환불."""
        raise self._not_implemented("cancel_payment")

    def verify_payment(self, pg_transaction_id: str) -> ChargeResult:
        """결제 검증 — 클라이언트가 준 값을 그대로 믿지 않고, 서버가 PG API로 실제 승인 여부를
        독립적으로 재확인하는 단계(실연동 시 보안상 반드시 필요)."""
        raise self._not_implemented("verify_payment")

    def handle_webhook(self, payload: dict[str, Any]) -> WebhookEvent:
        """PG가 보내는 Webhook payload를 처리해 내부 이벤트로 정규화한다(서명 검증 포함, 실연동 시)."""
        raise self._not_implemented("handle_webhook")

    def verify_webhook_signature(self, raw_body: bytes, headers: dict[str, str]) -> bool:
        """Webhook 요청이 정말 이 PG에서 온 것인지 검증한다.

        2026-08-11 Sprint 52 신설. Webhook 수신 엔드포인트를 만들면서 필요해졌다 —
        수신 엔드포인트는 **사용자 인증이 없는 공개 경로**라, 서명 검증이 유일한 방어선이다.
        검증되지 않은 요청으로 결제 상태를 바꿀 수 있으면 누구나 "결제 완료"를 위조할 수 있다.

        **기본 구현은 항상 False(fail-closed)** — 검증 방법을 모르는 provider는 어떤 요청도
        신뢰하지 않는다. 조용히 True를 돌려주는 기본값을 두면, 새 provider를 추가하면서
        이 메서드를 잊었을 때 방어가 통째로 사라진다.
        """
        return False


class MockProvider(PaymentProvider):
    """PG 미연동 상태의 Mock 결제. 항상 SUCCESS — 기존 api/v1/payments.py의 동작과 완전히 동일하다."""

    def charge(self, payment_type: str, amount: int, metadata: Optional[str]) -> ChargeResult:
        return ChargeResult(
            status=PaymentStatus.SUCCESS.value,
            pg_provider=None,
            pg_transaction_id=f"MOCK-{uuid.uuid4().hex}",
        )

    def create_order(self, payment_type: str, amount: int, metadata: Optional[str]) -> OrderResult:
        return OrderResult(order_id=f"MOCK-ORDER-{uuid.uuid4().hex}", pg_provider=None)

    def confirm_payment(self, order_id: str, pg_transaction_id: str, amount: int) -> ChargeResult:
        # 실제 PG라면 여기서 PG API를 호출해 order_id/amount가 실제 승인 내역과 일치하는지
        # 확인한 뒤 승인한다. Mock은 검증할 실제 결제가 없으므로 항상 승인 처리한다.
        return ChargeResult(
            status=PaymentStatus.SUCCESS.value,
            pg_provider=None,
            pg_transaction_id=pg_transaction_id or f"MOCK-{uuid.uuid4().hex}",
        )

    def cancel_payment(self, pg_transaction_id: str, reason: Optional[str] = None) -> ChargeResult:
        return ChargeResult(status=PaymentStatus.REFUNDED.value, pg_provider=None, pg_transaction_id=pg_transaction_id)

    def verify_payment(self, pg_transaction_id: str) -> ChargeResult:
        # 실제 PG라면 PG의 "결제 조회" API를 호출해 재확인한다. Mock은 항상 SUCCESS로 답한다
        # (Mock 결제는 confirm_payment 시점에 이미 무조건 성공하므로 재확인할 실패 케이스가 없음).
        return ChargeResult(status=PaymentStatus.SUCCESS.value, pg_provider=None, pg_transaction_id=pg_transaction_id)

    # Mock Webhook이 인정하는 이벤트 → 결제 상태 매핑.
    # 값은 전부 api/constants.py:PaymentStatus에 이미 있는 것만 쓴다(새 상태를 만들지 않는다).
    WEBHOOK_EVENT_STATUS = {
        "PAYMENT_CONFIRMED": PaymentStatus.PAID.value,
        "PAYMENT_FAILED": PaymentStatus.FAILED.value,
        "PAYMENT_CANCELLED": PaymentStatus.CANCELLED.value,
        "PAYMENT_EXPIRED": PaymentStatus.EXPIRED.value,
        "PAYMENT_REFUNDED": PaymentStatus.REFUNDED.value,
    }

    def handle_webhook(self, payload: dict[str, Any]) -> WebhookEvent:
        """Webhook payload를 내부 이벤트로 정규화한다.

        2026-08-11 Sprint 52 정정: 예전 구현은 event_type과 무관하게 **항상 SUCCESS**를
        돌려줬다. 그 상태로 수신 엔드포인트를 붙이면 `PAYMENT_FAILED` 노티를 받고도 결제를
        성공으로 바꾸는 결함이 된다. event_type을 실제로 해석하도록 고쳤다.
        알 수 없는 event_type은 상태를 바꾸지 않도록 빈 문자열을 돌려준다(호출부가 무시).

        서명 검증은 이 메서드가 아니라 `verify_webhook_signature()`가 담당한다 —
        수신 엔드포인트가 **정규화보다 먼저** 검증하도록 분리했다.
        """
        event_type = payload.get("event_type") or ""
        return WebhookEvent(
            event_type=event_type,
            pg_transaction_id=payload.get("pg_transaction_id"),
            status=self.WEBHOOK_EVENT_STATUS.get(event_type, ""),
        )

    def verify_webhook_signature(self, raw_body: bytes, headers: dict[str, str]) -> bool:
        """공유 시크릿 HMAC-SHA256으로 검증한다.

        Mock은 실제 PG가 아니므로 PG가 정한 서명 규격이 없다. 대신 **실연동과 같은 모양의
        방어**(원문 바디에 대한 HMAC + 상수시간 비교)를 구현해, 수신 엔드포인트의 보안 경로가
        실제로 동작하는지 테스트로 검증할 수 있게 한다.

        `PAYMENT_WEBHOOK_SECRET`이 설정돼 있지 않으면 **항상 False**다(fail-closed) —
        시크릿 없이 Webhook을 열어두면 누구나 결제 상태를 위조할 수 있다.
        값은 운영자가 발급하며 이 코드가 만들어내지 않는다.
        """
        secret = os.getenv("PAYMENT_WEBHOOK_SECRET", "").strip()
        if not secret:
            logger.warning("PAYMENT_WEBHOOK_SECRET 미설정 ― Webhook 서명 검증을 통과시키지 않습니다")
            return False
        # 헤더 이름은 대소문자를 가리지 않는다(HTTP 표준).
        provided = ""
        for key, value in headers.items():
            if key.lower() == "x-webhook-signature":
                provided = (value or "").strip()
                break
        if not provided:
            return False
        expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
        # 상수 시간 비교 — admin.py의 require_admin()이 쓰는 것과 같은 방어다.
        return hmac.compare_digest(expected, provided)


class KGInicisProvider(PaymentProvider):
    """KG이니시스 실연동 자리(2026-08-06 CTO 확정 PG사).

    6개 생명주기 메서드(charge/create_order/confirm_payment/cancel_payment/verify_payment/
    handle_webhook) 전부 PaymentProvider의 기본 구현(NotImplementedError)을 그대로 물려받는다 —
    호출하면 어떤 경로로 들어와도 조용히 성공하지 않고 명확히 실패한다.

    실제 구현은 KG이니시스 계약 + 상점ID(MID)/서명키 발급이 선행돼야 하므로 승인 대기 상태다
    (docs/decision-log.md "PG사 확정 — KG이니시스", docs/backend.md 주의사항 참고).
    구현 시 이 클래스만 채우면 되고 api/v1/payments.py는 수정하지 않아도 된다.
    """

    def charge(self, payment_type: str, amount: int, metadata: Optional[str]) -> ChargeResult:
        raise NotImplementedError("KG이니시스 실연동 미구현 (계약/API Key 발급 대기)")


class TossProvider(PaymentProvider):
    """[폐기 예정] Toss Payments 자리. 2026-08-06 PG사가 KG이니시스로 확정되면서 후보에서
    제외됐다 — 신규 코드에서 참조하지 않는다. 삭제는 승인 필요 작업이라 코드만 남겨둔다.
    선택 시 KGInicisProvider와 동일하게 즉시 NotImplementedError로 실패한다."""

    def charge(self, payment_type: str, amount: int, metadata: Optional[str]) -> ChargeResult:
        raise NotImplementedError("Toss는 폐기된 PG 후보입니다 (확정 PG사: KG이니시스)")


class PortOneProvider(PaymentProvider):
    """[폐기 예정] PortOne 자리. 2026-08-06 PG사가 KG이니시스로 확정되면서 후보에서
    제외됐다 — 신규 코드에서 참조하지 않는다. 삭제는 승인 필요 작업이라 코드만 남겨둔다.
    선택 시 KGInicisProvider와 동일하게 즉시 NotImplementedError로 실패한다."""

    def charge(self, payment_type: str, amount: int, metadata: Optional[str]) -> ChargeResult:
        raise NotImplementedError("PortOne은 폐기된 PG 후보입니다 (확정 PG사: KG이니시스)")


# PAYMENT_PROVIDER 허용값. "kginicis"가 확정 PG사이고, toss/portone은 폐기 예정 후보라
# 기존 .env 호환을 위해서만 남겨둔다(둘 다 선택해도 호출 시 NotImplementedError).
_PROVIDERS = {
    "mock": MockProvider,
    "kginicis": KGInicisProvider,
    "toss": TossProvider,
    "portone": PortOneProvider,
}

# 폐기 예정 PG 후보. get_payment_provider()가 선택 사실을 경고로 남긴다 — 운영 .env에
# 남아있는 옛 값을 조용히 지나치지 않도록.
_DEPRECATED_PROVIDERS = ("toss", "portone")

# provider 이름의 허용값 (2026-08-13 Sprint 78).
#
# `_PROVIDERS`가 이 저장소에서 provider 이름의 단일 출처다 — webhook 수신 경로가
# `get_payment_provider_by_name()`으로 이 맵에 대고 검증하므로, `payment_webhooks.provider`에
# 저장될 수 있는 값의 집합이 곧 이 맵의 키다. 조회 쪽(Admin 목록 필터)이 같은 집합을 봐야
# "오타"와 "그 PG의 노티가 없다"를 구분할 수 있다.
#
# 목록을 손으로 다시 적지 않고 맵에서 도출한다 — `api/v1/admin.py`가 Enum에서 허용값을
# 도출하기로 정한 것과 같은 이유다(손으로 적으면 provider가 늘 때 조용히 어긋난다).
VALID_PROVIDER_NAMES = tuple(_PROVIDERS)


def get_payment_provider_by_name(name: str) -> PaymentProvider:
    """이름으로 provider를 만든다 (2026-08-11 Sprint 52 신설).

    Webhook 수신 경로는 **URL의 provider 이름**으로 어떤 PG가 보낸 노티인지 판단한다 —
    환경변수(`PAYMENT_PROVIDER`)가 아니다. PG를 교체하는 전환기에는 옛 PG의 노티가
    한동안 계속 들어오기 때문이다. 알 수 없는 이름은 ValueError로 거부한다.
    """
    provider_cls = _PROVIDERS.get((name or "").strip().lower())
    if provider_cls is None:
        raise ValueError(
            f"알 수 없는 PAYMENT_PROVIDER 값입니다: {name} "
            f"(허용값: {', '.join(_PROVIDERS)})"
        )
    return provider_cls()


def get_payment_provider() -> PaymentProvider:
    # .env에 PAYMENT_PROVIDER가 없으면 기존과 동일하게 mock으로 동작한다(하위호환 유지).
    name = os.getenv("PAYMENT_PROVIDER", "mock").strip().lower()
    provider_cls = _PROVIDERS.get(name)
    if provider_cls is None:
        raise ValueError(
            f"알 수 없는 PAYMENT_PROVIDER 값입니다: {name} "
            f"(허용값: {', '.join(_PROVIDERS)})"
        )
    if name in _DEPRECATED_PROVIDERS:
        logger.warning(
            "PAYMENT_PROVIDER=%s 는 폐기된 PG 후보입니다. 확정 PG사는 KG이니시스(kginicis)입니다.",
            name,
        )
    return provider_cls()
