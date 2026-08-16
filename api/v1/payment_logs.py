"""결제 로그 / Webhook 저장소 (CTO 승인 5번).

KG이니시스 실연동은 론칭 직전까지 연기하되, 로그 구조는 미리 만들어 둔다.
**실제 PG API Key 연결·호출은 이 모듈에 없다.**

왜 필요한가:
`payments` 테이블은 결제의 "최종 상태" 한 줄만 갖는다. 실연동이 붙으면
주문 생성 → 결제창 → 승인 → 서버 재검증 → (환불/Webhook)이 시간차를 두고 일어나는데,
그 궤적이 남지 않으면 결제 분쟁 시 무슨 일이 있었는지 재구성할 수 없다.

구조 (storage/migrations/014_create_payment_logs.sql):
- `payment_logs`     : 생명주기 각 단계를 시간순 append-only 기록
- `payment_webhooks` : PG가 보낸 노티 원문 보관 + 멱등 처리

호출부는 이 모듈의 함수만 알면 되고, 실연동 시 Provider 안에서 같은 함수를 부르면 된다.
"""
import json
import logging
from datetime import datetime
from typing import Any, Optional

logger = logging.getLogger(__name__)

# payment_logs.event_type — PaymentProvider(api/v1/payment_providers.py)의 생명주기와 1:1
EVENT_CREATE_ORDER = "CREATE_ORDER"
EVENT_CONFIRM = "CONFIRM"
EVENT_VERIFY = "VERIFY"
EVENT_CANCEL = "CANCEL"
EVENT_WEBHOOK = "WEBHOOK"
VALID_EVENT_TYPES = (
    EVENT_CREATE_ORDER, EVENT_CONFIRM, EVENT_VERIFY, EVENT_CANCEL, EVENT_WEBHOOK,
)

# payment_logs.status
LOG_SUCCESS = "SUCCESS"
LOG_FAILED = "FAILED"
LOG_PENDING = "PENDING"
VALID_LOG_STATUSES = (LOG_SUCCESS, LOG_FAILED, LOG_PENDING)

# payment_webhooks.processing_status
WEBHOOK_RECEIVED = "RECEIVED"
WEBHOOK_PROCESSED = "PROCESSED"
WEBHOOK_FAILED = "FAILED"
WEBHOOK_IGNORED = "IGNORED"      # 중복 수신 등 정상적으로 무시한 경우
VALID_WEBHOOK_STATUSES = (
    WEBHOOK_RECEIVED, WEBHOOK_PROCESSED, WEBHOOK_FAILED, WEBHOOK_IGNORED,
)

# 로그에 남기면 안 되는 키. PG 연동 시 payload에 카드번호/생년월일이 섞여 들어올 수 있어
# 저장 전에 반드시 지운다 — 로그는 개발자·운영자가 폭넓게 열람하는 데이터이기 때문이다.
SENSITIVE_KEYS = (
    "card_no", "cardno", "card_number", "cardnumber",
    "cvc", "cvv", "expiry", "exp_date",
    "password", "passwd", "pwd",
    "birth", "birthday", "birth_date", "ssn", "juminno",
    "auth_token", "access_token", "secret", "sign_key", "signkey", "api_key",
)
REDACTED = "***REDACTED***"


def mask_sensitive(payload: Any) -> Any:
    """민감 키를 재귀적으로 마스킹한다. 원본은 건드리지 않는다."""
    if isinstance(payload, dict):
        return {
            k: (REDACTED if k.lower().replace("-", "_") in SENSITIVE_KEYS
                else mask_sensitive(v))
            for k, v in payload.items()
        }
    if isinstance(payload, list):
        return [mask_sensitive(v) for v in payload]
    return payload


def _dump(payload: Any) -> Optional[str]:
    if payload is None:
        return None
    if isinstance(payload, str):
        return payload
    return json.dumps(mask_sensitive(payload), ensure_ascii=False)


def log_payment_event(
    conn,
    event_type: str,
    status: str,
    user_id: Optional[str] = None,
    payment_id: Optional[int] = None,
    provider: Optional[str] = None,
    order_id: Optional[str] = None,
    pg_transaction_id: Optional[str] = None,
    amount: Optional[int] = None,
    request_payload: Any = None,
    response_payload: Any = None,
    error_message: Optional[str] = None,
    at: datetime = None,
) -> int:
    """결제 생명주기 한 단계를 기록하고 id를 반환한다. commit은 호출부 책임이다.

    payment_id는 nullable이다 — 주문 생성이 실패해 payments row가 아예 만들어지지 않은
    경우에도 "시도했다"는 기록은 남아야 하기 때문이다.
    """
    if event_type not in VALID_EVENT_TYPES:
        raise ValueError(f"알 수 없는 결제 이벤트 유형입니다: {event_type}")
    if status not in VALID_LOG_STATUSES:
        raise ValueError(f"알 수 없는 결제 로그 상태입니다: {status}")

    return conn.execute(
        """
        INSERT INTO payment_logs
        (payment_id, user_id, event_type, status, provider, order_id,
         pg_transaction_id, amount, request_payload, response_payload,
         error_message, created_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (payment_id, user_id, event_type, status, provider, order_id,
         pg_transaction_id, amount, _dump(request_payload), _dump(response_payload),
         error_message, (at or datetime.now()).isoformat()),
    ).lastrowid


def get_payment_logs(conn, payment_id: int) -> list:
    rows = conn.execute(
        "SELECT * FROM payment_logs WHERE payment_id=? ORDER BY created_at ASC, id ASC",
        (payment_id,),
    ).fetchall()
    return [row_to_payment_log(r) for r in rows]


def row_to_payment_log(row) -> dict:
    return {
        "id": row["id"],
        "payment_id": row["payment_id"],
        "user_id": row["user_id"],
        "event_type": row["event_type"],
        "status": row["status"],
        "provider": row["provider"],
        "order_id": row["order_id"],
        "pg_transaction_id": row["pg_transaction_id"],
        "amount": row["amount"],
        "request_payload": row["request_payload"],
        "response_payload": row["response_payload"],
        "error_message": row["error_message"],
        "created_at": row["created_at"],
    }


def record_webhook(
    conn,
    provider: str,
    raw_payload: Any,
    event_type: Optional[str] = None,
    event_id: Optional[str] = None,
    pg_transaction_id: Optional[str] = None,
    payment_id: Optional[int] = None,
    signature_verified: bool = False,
    at: datetime = None,
) -> tuple[Optional[int], bool]:
    """PG Webhook 수신 기록. `(id, is_duplicate)`를 반환한다.

    PG는 우리 응답이 늦으면 같은 노티를 여러 번 보낸다. `event_id` UNIQUE로 멱등성을
    보장하고, 중복이면 새 행을 만들지 않고 기존 id와 `is_duplicate=True`를 돌려준다 —
    호출부는 이 값을 보고 후속 처리를 건너뛰면 된다.

    2026-08-15 정정: "수신 엔드포인트는 아직 없다(구조만 준비)"는 이 함수가 처음 만들어진
    Sprint 27 시점 서술이었다 ― Sprint 52/53에서 `api/v1/payments.py:receive_payment_webhook()`가
    이미 연결됐고, 그 경로가 서명 검증을 통과한 뒤에만 `signature_verified=True`로 호출한다
    (문장을 지우지 않고 정정만 덧붙인다는 이 저장소 관례를 따른다).
    """
    now = (at or datetime.now()).isoformat()

    if event_id:
        existing = conn.execute(
            "SELECT id FROM payment_webhooks WHERE event_id=?", (event_id,)
        ).fetchone()
        if existing:
            logger.info("중복 Webhook 수신 ― 무시합니다 (event_id=%s)", event_id)
            return existing["id"], True

    webhook_id = conn.execute(
        """
        INSERT INTO payment_webhooks
        (provider, event_type, event_id, pg_transaction_id, payment_id,
         signature_verified, processing_status, raw_payload, received_at)
        VALUES (?,?,?,?,?,?,?,?,?)
        """,
        (provider, event_type, event_id, pg_transaction_id, payment_id,
         1 if signature_verified else 0, WEBHOOK_RECEIVED, _dump(raw_payload), now),
    ).lastrowid
    return webhook_id, False


def mark_webhook_processed(conn, webhook_id: int, status: str,
                           error_message: Optional[str] = None,
                           at: datetime = None) -> None:
    if status not in VALID_WEBHOOK_STATUSES:
        raise ValueError(f"알 수 없는 Webhook 처리 상태입니다: {status}")
    conn.execute(
        "UPDATE payment_webhooks SET processing_status=?, error_message=?, processed_at=?"
        " WHERE id=?",
        (status, error_message, (at or datetime.now()).isoformat(), webhook_id),
    )


# ---------------------------------------------------------------------------
# 재처리 가능 여부 (2026-08-11 Sprint 53)
#
# 운영자가 실패한 Webhook을 다시 처리하려 할 때, **무엇을 다시 돌려도 되는지**를 한 곳에서
# 정한다. 목록 조회와 재처리 엔드포인트가 같은 함수를 쓰므로 "목록에는 가능하다고 떴는데
# 누르면 거부되는" 불일치가 생길 수 없다.
#
# 규칙은 기존 상태 의미에서 그대로 도출한 것이며 새 정책을 만들지 않았다:
#
#   RECEIVED  : 기록만 되고 처리가 끝나지 않았다(처리 도중 프로세스가 죽은 경우) -> 재처리 가능
#   IGNORED   : 의도적으로 넘어갔다. 그런데 그 사유 중 일부는 **시간이 지나면 해소된다** —
#               대표적으로 "해당 거래의 결제 내역을 찾을 수 없습니다"는 PG 노티가 우리
#               payments row보다 먼저 도착한 경합이라, 나중에 다시 돌리면 성공한다 -> 재처리 가능
#   PROCESSED : 이미 반영됐다 -> 재처리 대상 아님(다시 돌릴 이유가 없다)
#   FAILED    : 서명 검증 실패 등. **절대 재처리하지 않는다** — 신뢰한 적 없는 payload다
#
# ★ 그리고 상태와 무관하게 `signature_verified=0`이면 언제나 불가다.
#   검증되지 않은 payload를 운영자 손으로 적용할 수 있으면 서명 검증 자체가 무의미해진다.
REPROCESSABLE_STATUSES = (WEBHOOK_RECEIVED, WEBHOOK_IGNORED)


def webhook_reprocess_block_reason(row) -> Optional[str]:
    """재처리를 막아야 하는 이유. 가능하면 None을 반환한다.

    운영자가 상태를 오판하지 않도록 **왜 안 되는지**를 문자열로 돌려준다
    (목록 응답에도 그대로 실어 "가능/불가"만 보여주는 것보다 판단하기 쉽게 한다).
    """
    if not row["signature_verified"]:
        return "서명이 검증되지 않은 수신입니다 — 신뢰할 수 없는 payload라 재처리하지 않습니다"
    status = row["processing_status"]
    if status == WEBHOOK_PROCESSED:
        return "이미 정상 처리된 Webhook입니다 — 다시 적용할 것이 없습니다"
    if status == WEBHOOK_FAILED:
        return "처리 실패로 기록된 수신입니다 — 실패 사유를 확인한 뒤 PG에 재전송을 요청하세요"
    if status not in REPROCESSABLE_STATUSES:
        return f"재처리를 지원하지 않는 상태입니다: {status}"
    return None


def row_to_webhook(row) -> dict:
    block_reason = webhook_reprocess_block_reason(row)
    return {
        "id": row["id"],
        "provider": row["provider"],
        "event_type": row["event_type"],
        "event_id": row["event_id"],
        "pg_transaction_id": row["pg_transaction_id"],
        "payment_id": row["payment_id"],
        "signature_verified": bool(row["signature_verified"]),
        "processing_status": row["processing_status"],
        "raw_payload": row["raw_payload"],
        "error_message": row["error_message"],
        "received_at": row["received_at"],
        "processed_at": row["processed_at"],
        # --- 운영 판단용 파생 필드(2026-08-11 Sprint 53 추가) ---
        "reprocessable": block_reason is None,
        "reprocess_blocked_reason": block_reason,
    }
