"""Subscription Lifecycle (CTO 승인 3번).

상태: ACTIVE / GRACE_PERIOD / PAUSED / EXPIRED / CANCELLED

핵심 설계 — **자동 만료를 배치에 의존하지 않는다.**
이 프로젝트에는 상시 실행되는 스케줄러가 크롤링 배치뿐이고, 만료 처리를 거기에 얹으면
"배치가 안 돌아서 만료가 안 됨"이 곧 과금 사고가 된다. 대신 조회 시점에
`resolve_expected_status()`로 계산하고, 조회하는 김에 DB 상태도 맞춰 둔다(lazy sync).
그래서 배치가 없어도 정확하고, 나중에 배치를 붙여도 결과가 같다.

무료 등기부 초기화는 별도 작업이 필요 없다 — 한도는 `used_at >= 이번달 1일`로 계산되므로
월이 바뀌면 자동으로 0부터 다시 센다(`api/v1/registry.py`).
"""
import logging
from datetime import datetime, timedelta

from api.constants import SubscriptionStatus
from api.v1.state_machines import (
    assert_subscription_transition, is_entitled, resolve_expected_status,
    grace_period_end,
)

logger = logging.getLogger(__name__)


def row_to_subscription(row) -> dict:
    """구독 행 → 응답 dict. 기존 `payments.py:row_to_subscription`과 필드가 동일하고,
    상태 해석에 필요한 파생 필드만 추가한다(기존 필드는 하나도 바꾸지 않는다)."""
    expires_at = row["expires_at"]
    status = row["status"]
    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "plan": row["plan"],
        "price": row["price"],
        "status": status,
        "started_at": row["started_at"],
        "expires_at": expires_at,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        # --- 파생 필드(추가) ---
        "effective_status": resolve_expected_status(status, expires_at),
        "is_entitled": is_entitled(resolve_expected_status(status, expires_at), expires_at),
        "grace_period_end": grace_period_end(expires_at) if expires_at else None,
    }


def sync_expired_status(conn, user_id: str = None, at: datetime = None,
                        *, commit: bool) -> int:
    """시간 경과로 상태가 바뀌어야 하는 구독을 실제로 갱신한다(lazy sync).

    `user_id`를 주면 그 사용자 것만, 없으면 전체를 훑는다. 반환값은 실제로 바뀐 행 수.

    ★ `commit`은 **키워드 전용이고 기본값이 없다** — 호출부가 반드시 명시해야 한다.
    이 함수는 UPDATE를 하므로 커밋 시점이 호출 맥락에 따라 완전히 달라진다:

      - 읽기 경로(Admin 목록 등)에서 부를 때는 `commit=True`.
        호출부에 트랜잭션이 없으므로 여기서 확정해야 변경이 남는다.
      - 쓰기 트랜잭션 안에서 부를 때는 `commit=False`.
        여기서 커밋하면 **호출부의 트랜잭션이 중간에 끊긴다**
        (`create_registry_request()`의 `BEGIN IMMEDIATE`가 대표적인 예 — 무료횟수 확인과
        INSERT의 원자성이 깨져 동시성 버그가 되살아난다).

    기본값을 주지 않은 이유가 이것이다. 어느 쪽을 기본으로 삼아도 반대 맥락에서 조용히
    틀리며, 그 실패는 테스트로 잡기 어렵다.
    """
    now = at or datetime.now()
    sql = ("SELECT id, status, expires_at FROM subscriptions"
           " WHERE status IN (?, ?)")
    params = [SubscriptionStatus.ACTIVE.value, SubscriptionStatus.GRACE_PERIOD.value]
    if user_id:
        sql += " AND user_id = ?"
        params.append(user_id)

    changed = 0
    for row in conn.execute(sql, params).fetchall():
        expected = resolve_expected_status(row["status"], row["expires_at"], now)
        if expected == row["status"]:
            continue
        # 전이 규칙을 우회하지 않는다 — 자동 전이도 같은 관문을 통과해야 한다.
        try:
            assert_subscription_transition(row["status"], expected)
        except Exception:
            logger.warning("자동 만료 전이가 규칙에 막힘: id=%s %s -> %s",
                           row["id"], row["status"], expected)
            continue
        conn.execute(
            "UPDATE subscriptions SET status=?, updated_at=? WHERE id=?",
            (str(expected), now.isoformat(), row["id"]),
        )
        logger.info("구독 자동 전이: id=%s %s -> %s", row["id"], row["status"], expected)
        changed += 1

    if changed and commit:
        conn.commit()
    return changed


def get_active_subscription(conn, user_id: str, at: datetime = None,
                            *, commit: bool = True):
    """이 사용자의 현재 유효한 구독 행. 없으면 None.

    조회 전에 만료 동기화를 돌려 "만료됐는데 ACTIVE로 남아있는" 행이 잡히지 않게 한다.
    정렬 tie-break(`id DESC`)는 docs/BUGS.md #16과 같은 이유다.

    쓰기 트랜잭션 안에서 쓸 거라면 `commit=False`를 넘겨야 한다(위 `sync_expired_status` 참고).
    단, 이용권 판정만 필요하다면 DB를 전혀 건드리지 않는
    `api/v1/registry.py:get_entitled_subscription()` 쪽이 더 안전하다.
    """
    sync_expired_status(conn, user_id, at, commit=commit)
    # sync_expired_status가 방금 "지금 있어야 할 상태"로 status를 맞춰뒀으므로
    # status IN (ACTIVE, GRACE_PERIOD)만으로 이미 유효한 구독이다. GRACE_PERIOD는
    # 정의상 expires_at이 이미 지난 상태라, 여기에 `expires_at > now` 조건을 더하면
    # 방금 동기화한 GRACE_PERIOD 행이 스스로 걸러져 None이 반환된다(과거 버그).
    return conn.execute(
        """
        SELECT * FROM subscriptions
        WHERE user_id=? AND status IN (?, ?)
        ORDER BY started_at DESC, id DESC LIMIT 1
        """,
        (user_id, SubscriptionStatus.ACTIVE.value,
         SubscriptionStatus.GRACE_PERIOD.value),
    ).fetchone()


def change_status(conn, subscription_id: int, target: str,
                  actor: str = "SYSTEM", at: datetime = None) -> dict:
    """구독 상태를 바꾼다. 전이 규칙에 어긋나면 InvalidTransition을 던진다.

    부수 효과(만료 시각 조정)는 상태별로 다르다:
      PAUSED  : 남은 기간을 보존해야 하므로 만료 시각을 건드리지 않는다.
                (재개 시 남은 일수를 다시 얹는 정책은 요금 정산 규칙이 필요해 여기서 정하지 않는다)
      ACTIVE  : 만료된 구독을 되살리는 경우라면 호출부가 새 expires_at을 함께 넘긴다
      CANCELLED/EXPIRED : 즉시 종료 — 만료 시각을 지금으로 당긴다
    """
    now = at or datetime.now()
    row = conn.execute("SELECT * FROM subscriptions WHERE id=?", (subscription_id,)).fetchone()
    if not row:
        raise LookupError("구독을 찾을 수 없습니다")

    assert_subscription_transition(row["status"], target)

    if target in (SubscriptionStatus.CANCELLED, SubscriptionStatus.EXPIRED):
        conn.execute(
            "UPDATE subscriptions SET status=?, expires_at=?, updated_at=? WHERE id=?",
            (str(target), now.isoformat(), now.isoformat(), subscription_id),
        )
    else:
        conn.execute(
            "UPDATE subscriptions SET status=?, updated_at=? WHERE id=?",
            (str(target), now.isoformat(), subscription_id),
        )

    logger.info("구독 상태 변경: id=%s %s -> %s (by=%s)",
                subscription_id, row["status"], target, actor)
    updated = conn.execute("SELECT * FROM subscriptions WHERE id=?", (subscription_id,)).fetchone()
    return {"before": row_to_subscription(row), "after": row_to_subscription(updated)}


def renew(conn, subscription_id: int, period_days: int,
          actor: str = "SYSTEM", at: datetime = None) -> dict:
    """갱신 — 만료 시각을 연장하고 ACTIVE로 되돌린다.

    연장 기준점: 아직 만료 전이면 **기존 만료 시각에서** 이어 붙이고(사용자가 손해 보지
    않도록), 이미 지났으면 **지금부터** 센다(과거 시점에서 더하면 갱신하자마자 또 만료된다).
    """
    now = at or datetime.now()
    row = conn.execute("SELECT * FROM subscriptions WHERE id=?", (subscription_id,)).fetchone()
    if not row:
        raise LookupError("구독을 찾을 수 없습니다")

    base = now
    if row["expires_at"]:
        try:
            current_expiry = datetime.fromisoformat(row["expires_at"])
            if current_expiry > now:
                base = current_expiry
        except (TypeError, ValueError):
            pass  # 형식이 깨져 있으면 지금부터 센다

    new_expires = (base + timedelta(days=period_days)).isoformat()
    if row["status"] != SubscriptionStatus.ACTIVE:
        assert_subscription_transition(row["status"], SubscriptionStatus.ACTIVE)

    conn.execute(
        "UPDATE subscriptions SET status=?, expires_at=?, updated_at=? WHERE id=?",
        (SubscriptionStatus.ACTIVE.value, new_expires, now.isoformat(), subscription_id),
    )
    logger.info("구독 갱신: id=%s expires %s -> %s (by=%s)",
                subscription_id, row["expires_at"], new_expires, actor)
    updated = conn.execute("SELECT * FROM subscriptions WHERE id=?", (subscription_id,)).fetchone()
    return {"before": row_to_subscription(row), "after": row_to_subscription(updated)}
