"""등기부 무료 횟수 조정(credit) 서비스.

CTO 승인 6번: 관리자가 등기부 무료 횟수를 추가/차감/초기화할 수 있어야 한다.
Admin UI는 없어도 되지만 API/DB/Model/Service/테스트/문서는 구현한다.

설계 (storage/migrations/015_create_registry_credits.sql 참고):
잔액 컬럼을 따로 두지 않고 **조정 원장(ledger)** 만 append-only로 쌓는다.

    유효 한도 = 플랜 월 한도(PLAN_CATALOG) + 이번 달 조정 합계

잔액을 별도 컬럼으로 들면 registry_usage 기반 사용량 계산과 상태가 이중화되어 반드시
어긋난다(docs/decision-log.md의 Premium 판정이 별도 테이블을 거부한 것과 같은 이유).
원장 방식은 (1) 누가/언제/왜 바꿨는지 전부 남고 (2) 월이 바뀌면 조정도 자연히 초기화되며
(3) 동기화 버그가 원천적으로 불가능하다.
"""
from datetime import datetime
from typing import Optional

from api.constants import RegistryCreditReason

# 조정 유형. 값은 api/constants.py:RegistryCreditReason과 동일하다 — 여기서는
# **한도 계산에 반영되는 관리자 조정 3종**만 허용한다.
# USAGE/EVENT/REFUND 같은 사유는 추적 로그(registry_credit_logs)에만 남고, 원장에 넣으면
# registry_usage가 이미 세고 있는 사용량과 이중 차감이 된다.
REASON_GRANT = RegistryCreditReason.GRANT.value
REASON_DEDUCT = RegistryCreditReason.DEDUCT.value
REASON_RESET = RegistryCreditReason.RESET.value
VALID_REASON_TYPES = (REASON_GRANT, REASON_DEDUCT, REASON_RESET)

# 한 번의 조정으로 움직일 수 있는 최대치. 오타(0 하나 더 붙이는 실수)로 과금 정책이
# 무너지는 것을 막는 안전장치다.
MAX_ADJUSTMENT = 100


def get_current_month(at: datetime = None) -> str:
    """조정이 적용되는 월. `YYYY-MM` — registry.py의 월 리셋 경계와 같은 기준이다."""
    return (at or datetime.now()).strftime("%Y-%m")


def get_credit_adjustment(conn, user_id: str, month: str = None) -> int:
    """해당 월의 순 조정량. RESET 이후의 조정만 합산한다.

    RESET은 "그 시점까지의 조정을 없던 것으로 한다"는 표식이므로, 같은 달에 RESET이 있으면
    가장 마지막 RESET **이후**에 기록된 GRANT/DEDUCT만 유효하다.
    """
    month = month or get_current_month()
    last_reset = conn.execute(
        "SELECT MAX(id) FROM registry_credits"
        " WHERE user_id=? AND effective_month=? AND reason_type=?",
        (user_id, month, REASON_RESET),
    ).fetchone()[0]

    if last_reset is None:
        row = conn.execute(
            "SELECT COALESCE(SUM(amount), 0) FROM registry_credits"
            " WHERE user_id=? AND effective_month=?",
            (user_id, month),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT COALESCE(SUM(amount), 0) FROM registry_credits"
            " WHERE user_id=? AND effective_month=? AND id > ?",
            (user_id, month, last_reset),
        ).fetchone()
    return row[0]


def add_credit(conn, user_id: str, reason_type: str, amount: int,
               reason: Optional[str], created_by: str, at: datetime = None) -> int:
    """조정을 원장에 기록하고 id를 반환한다. 호출부가 commit을 책임진다.

    amount는 항상 "양수 크기"로 받고, 부호는 reason_type이 정한다 — 호출부가 실수로
    음수를 넘겨 GRANT가 차감이 되는 일이 없도록 여기서 정규화한다.
    """
    if reason_type not in VALID_REASON_TYPES:
        raise ValueError(f"알 수 없는 조정 유형입니다: {reason_type}")

    if reason_type == REASON_RESET:
        signed = 0
    else:
        if amount <= 0:
            raise ValueError("조정 수량은 1 이상이어야 합니다")
        if amount > MAX_ADJUSTMENT:
            raise ValueError(f"한 번에 조정 가능한 최대 수량은 {MAX_ADJUSTMENT}입니다")
        signed = amount if reason_type == REASON_GRANT else -amount

    now = (at or datetime.now())
    credit_id = conn.execute(
        """
        INSERT INTO registry_credits
        (user_id, reason_type, amount, reason, effective_month, created_by, created_at)
        VALUES (?,?,?,?,?,?,?)
        """,
        (user_id, reason_type, signed, reason, get_current_month(now),
         created_by, now.isoformat()),
    ).lastrowid

    # 추적 로그도 함께 남긴다(CTO 승인 4번). 원장(registry_credits)은 "한도 계산에 반영되는
    # 조정"만 담고, 로그(registry_credit_logs)는 "무료 횟수가 움직인 모든 사건"을 담는다.
    # 같은 트랜잭션에 넣어 조정과 로그가 함께 성립하게 한다.
    log_credit_event(
        conn, user_id, reason_type, signed,
        reason=reason, actor=created_by, related_credit_id=credit_id, at=now,
    )
    return credit_id


def log_credit_event(conn, user_id: str, reason_type: str, delta: int,
                     reason: Optional[str] = None, actor: str = "SYSTEM",
                     related_credit_id: Optional[int] = None,
                     related_usage_id: Optional[int] = None,
                     balance_after: Optional[int] = None,
                     at: datetime = None) -> int:
    """무료 횟수 변동 추적 로그 1건 (registry_credit_logs).

    `balance_after`를 넘기지 않으면 이 시점의 조정 합계를 스냅샷으로 남긴다 —
    나중에 "그때 얼마였나"를 재계산 없이 볼 수 있게 하기 위함이다.
    commit은 호출부 책임(업무 트랜잭션과 함께 커밋되어야 한다).
    """
    now = at or datetime.now()
    if balance_after is None:
        balance_after = get_credit_adjustment(conn, user_id, get_current_month(now))
    return conn.execute(
        """
        INSERT INTO registry_credit_logs
        (user_id, reason_type, delta, balance_after, reason, effective_month,
         actor, related_credit_id, related_usage_id, created_at)
        VALUES (?,?,?,?,?,?,?,?,?,?)
        """,
        (user_id, str(reason_type), delta, balance_after, reason,
         get_current_month(now), actor, related_credit_id, related_usage_id,
         now.isoformat()),
    ).lastrowid


def get_credit_logs(conn, user_id: str, limit: int = 100) -> list:
    rows = conn.execute(
        "SELECT * FROM registry_credit_logs WHERE user_id=?"
        " ORDER BY created_at DESC, id DESC LIMIT ?",
        (user_id, limit),
    ).fetchall()
    return [row_to_credit_log(r) for r in rows]


def row_to_credit_log(row) -> dict:
    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "reason_type": row["reason_type"],
        "delta": row["delta"],
        "balance_after": row["balance_after"],
        "reason": row["reason"],
        "effective_month": row["effective_month"],
        "actor": row["actor"],
        "related_credit_id": row["related_credit_id"],
        "related_usage_id": row["related_usage_id"],
        "created_at": row["created_at"],
    }


def row_to_credit(row) -> dict:
    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "reason_type": row["reason_type"],
        "amount": row["amount"],
        "reason": row["reason"],
        "effective_month": row["effective_month"],
        "created_by": row["created_by"],
        "created_at": row["created_at"],
    }
