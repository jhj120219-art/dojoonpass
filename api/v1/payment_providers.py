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
    def charge(self, payment_type: str, amount: int, metadata: Optional[str]) -> ChargeResult:
        raise NotImplementedError

    def create_order(self, payment_type: str, amount: int, metadata: Optional[str]) -> OrderResult:
        """주문 생성 — 실제 PG에서는 클라이언트가 결제창을 열 때 쓸 order_id를 발급받는 단계."""
        raise NotImplementedError

    def confirm_payment(self, order_id: str, pg_transaction_id: str, amount: int) -> ChargeResult:
        """결제 승인 — 사용자가 PG 결제창에서 결제를 마친 뒤, 서버가 최종 승인을 확정하는 단계."""
        raise NotImplementedError

    def cancel_payment(self, pg_transaction_id: str, reason: Optional[str] = None) -> ChargeResult:
        """결제 취소/환불."""
        raise NotImplementedError

    def verify_payment(self, pg_transaction_id: str) -> ChargeResult:
        """결제 검증 — 클라이언트가 준 값을 그대로 믿지 않고, 서버가 PG API로 실제 승인 여부를
        독립적으로 재확인하는 단계(실연동 시 보안상 반드시 필요)."""
        raise NotImplementedError

    def handle_webhook(self, payload: dict[str, Any]) -> WebhookEvent:
        """PG가 보내는 Webhook payload를 처리해 내부 이벤트로 정규화한다(서명 검증 포함, 실연동 시)."""
        raise NotImplementedError


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

    def handle_webhook(self, payload: dict[str, Any]) -> WebhookEvent:
        # 실제 PG라면 서명(signature) 검증부터 해야 한다. Mock은 Webhook을 실제로 받지
        # 않으므로(요청사항: Webhook 서버 구현 금지) payload를 그대로 신뢰해 정규화만 한다.
        return WebhookEvent(
            event_type=payload.get("event_type", "PAYMENT_CONFIRMED"),
            pg_transaction_id=payload.get("pg_transaction_id"),
            status=PaymentStatus.SUCCESS.value,
        )


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
