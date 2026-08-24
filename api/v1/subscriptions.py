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
        # 읽었던 상태를 WHERE에 다시 건다 — 이 모듈의 다른 writer(`change_status()`,
        # `renew()`)가 이미 쓰는 패턴이다. 여기만 조건 없이 쓰고 있었다.
        #
        # ★ 2026-08-24 Sprint 254 (BUGS #180). 조건이 없으면 **읽은 뒤 바뀐 상태를
        #   그대로 덮는다.** 이 함수는 읽기 경로(`GET /api/v1/subscriptions/me`,
        #   Admin 목록)에서 `BEGIN IMMEDIATE` 없이 불리므로 SELECT와 UPDATE 사이가
        #   실제로 열려 있다 — 다른 writer 들과 달리 락으로 닫혀 있지 않다.
        #
        #   실측(scratch DB, 커넥션 래퍼로 창을 벌려 결정적 재현):
        #     ACTIVE 를 읽음 -> 그 사이 해지(CANCELLED) -> 여기서 EXPIRED 로 덮어씀
        #   CANCELLED 는 **최종 상태**(state_machines.py: `CANCELLED: set()`)라
        #   CANCELLED -> EXPIRED 는 금지된 전이다. 즉 이 UPDATE 는 바로 위에서
        #   "전이 규칙을 우회하지 않는다"고 적어 둔 그 관문을 **실제로 우회했다** —
        #   판정에 쓴 상태(ACTIVE)와 덮어쓰는 대상의 상태(CANCELLED)가 다르기 때문이다.
        #   그리고 로그에는 `ACTIVE -> EXPIRED` 라는 사실이 아닌 문장이 남았다.
        #   해지된 구독이 EXPIRED 가 되면 재구독으로 되살아난다(EXPIRED -> ACTIVE 는 허용).
        cursor = conn.execute(
            "UPDATE subscriptions SET status=?, updated_at=? WHERE id=? AND status=?",
            (str(expected), now.isoformat(), row["id"], row["status"]),
        )
        if cursor.rowcount == 0:
            # 진 쪽은 조용히 빠진다 — 실패가 아니다. 이긴 쪽의 판단이 더 최신이고,
            # 다음 호출이 그 새 상태를 기준으로 다시 판단한다(이 함수는 idempotent 하다).
            logger.info("구독 자동 전이 생략: id=%s (읽은 상태 %s 가 그 사이 바뀌었다)",
                        row["id"], row["status"])
            continue
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


class ConcurrentStatusChange(Exception):
    """다른 요청이 SELECT와 UPDATE 사이에 먼저 상태를 바꿨다(TOCTOU 충돌).

    2026-08-12 발견: Admin PATCH /admin/subscriptions/{id}(유일한 호출부)에 서로 다른 목표
    상태로 동시 요청 2건을 보내면, 가드가 없어 **둘 다 200으로 성공 응답**하고 최종 DB
    상태는 나중에 커밋된 쪽으로 조용히 결정됐다(재현 5/5) — `docs/BUGS.md` #21(Admin 등기부
    상태 전이 레이스)과 같은 부류의 결함이 이 경로에는 아직 없었다. registry.py/payments.py가
    이미 쓰는 "BEGIN IMMEDIATE + 조건부 UPDATE(WHERE id=? AND status=?) + rowcount 확인"
    패턴을 그대로 적용해 해소한다.
    """


class ReactivationRequiresNewExpiry(Exception):
    """이미 지난 `expires_at`을 가진 구독을 ACTIVE로 되돌리려는데 새 만료 시각이 없다.

    2026-08-12 발견: `change_status()`의 ACTIVE 분기는 기존에 `expires_at`을 전혀 건드리지
    않았다 — 이 함수의 docstring 자체가 "만료된 구독을 되살리는 경우라면 호출부가 새
    expires_at을 함께 넘긴다"고 명시하는데, 실제로는 그 값을 받을 매개변수조차 없었다.
    재현: EXPIRED 구독을 Admin PATCH로 ACTIVE로 바꾸면 200이 오지만, 같은 응답 안의
    `effective_status`가 이미 `EXPIRED`이고(과거 만료 시각을 그대로 지닌 채라 lazy sync가
    즉시 되돌린다), 바로 다음 조회에서 DB 상태도 원래대로 `EXPIRED`로 돌아와 있었다 —
    "성공했다고 응답했지만 아무 일도 일어나지 않은" 조용한 실패. 며칠/몇 개월을 얼마나
    연장할지는 이 함수가 정할 수 없는 값이라(요금 정산 정책, `subscriptions` 테이블에
    `billing_cycle`도 저장되지 않는다) 조용히 실패하는 대신 **호출부에 새 expires_at을
    요구**한다 — 이미 미래 시각을 갖고 있는 PAUSED→ACTIVE(재개)는 영향 없다.
    """


def change_status(conn, subscription_id: int, target: str,
                  actor: str = "SYSTEM", at: datetime = None,
                  new_expires_at: datetime = None) -> dict:
    """구독 상태를 바꾼다. 전이 규칙에 어긋나면 InvalidTransition을 던진다.

    부수 효과(만료 시각 조정)는 상태별로 다르다:
      PAUSED  : 남은 기간을 보존해야 하므로 만료 시각을 건드리지 않는다.
                (재개 시 남은 일수를 다시 얹는 정책은 요금 정산 규칙이 필요해 여기서 정하지 않는다)
      ACTIVE  : 현재 `expires_at`이 이미 지났다면(만료된 구독 재활성화) `new_expires_at`이
                반드시 있어야 한다 — 없으면 `ReactivationRequiresNewExpiry`. 아직 지나지
                않았다면(PAUSED에서 재개) 기존 값을 그대로 둔다. `new_expires_at`이 주어지면
                현재 상태와 무관하게 그 값으로 갱신한다(호출부가 명시적으로 원한 경우).
      CANCELLED/EXPIRED : 즉시 종료 — 만료 시각을 지금으로 당긴다

    동시 요청 방어: 함수 진입 직후 쓰기 락을 선점하고(`BEGIN IMMEDIATE`), UPDATE의 WHERE에
    읽었던 현재 상태를 다시 걸어 rowcount로 검증한다 — 그 사이 다른 요청이 먼저 상태를
    바꿨다면 `ConcurrentStatusChange`를 던진다(registry.py §19/payments.py 환불과 동일 패턴).
    """
    conn.isolation_level = None
    conn.execute("BEGIN IMMEDIATE")

    now = at or datetime.now()
    row = conn.execute("SELECT * FROM subscriptions WHERE id=?", (subscription_id,)).fetchone()
    if not row:
        raise LookupError("구독을 찾을 수 없습니다")

    current_status = row["status"]
    assert_subscription_transition(current_status, target)

    if target in (SubscriptionStatus.CANCELLED, SubscriptionStatus.EXPIRED):
        cursor = conn.execute(
            "UPDATE subscriptions SET status=?, expires_at=?, updated_at=? WHERE id=? AND status=?",
            (str(target), now.isoformat(), now.isoformat(), subscription_id, current_status),
        )
    elif target == SubscriptionStatus.ACTIVE:
        currently_expired = bool(row["expires_at"]) and row["expires_at"] <= now.isoformat()
        if new_expires_at is None and currently_expired:
            conn.rollback()
            raise ReactivationRequiresNewExpiry(
                f"만료 시각({row['expires_at']})이 이미 지난 구독을 ACTIVE로 되돌리려면"
                " 새 expires_at이 필요합니다"
            )
        if new_expires_at is not None:
            cursor = conn.execute(
                "UPDATE subscriptions SET status=?, expires_at=?, updated_at=? WHERE id=? AND status=?",
                (str(target), new_expires_at.isoformat(), now.isoformat(), subscription_id, current_status),
            )
        else:
            cursor = conn.execute(
                "UPDATE subscriptions SET status=?, updated_at=? WHERE id=? AND status=?",
                (str(target), now.isoformat(), subscription_id, current_status),
            )
    else:
        cursor = conn.execute(
            "UPDATE subscriptions SET status=?, updated_at=? WHERE id=? AND status=?",
            (str(target), now.isoformat(), subscription_id, current_status),
        )

    if cursor.rowcount == 0:
        conn.rollback()
        raise ConcurrentStatusChange(
            f"다른 요청이 먼저 구독 상태를 바꿨습니다 (기대한 현재 상태: {current_status})"
        )

    logger.info("구독 상태 변경: id=%s %s -> %s (by=%s)",
                subscription_id, current_status, target, actor)
    updated = conn.execute("SELECT * FROM subscriptions WHERE id=?", (subscription_id,)).fetchone()
    return {"before": row_to_subscription(row), "after": row_to_subscription(updated)}


def renew(conn, subscription_id: int, period_days: int,
          actor: str = "SYSTEM", at: datetime = None) -> dict:
    """갱신 — 만료 시각을 연장하고 ACTIVE로 되돌린다.

    연장 기준점: 아직 만료 전이면 **기존 만료 시각에서** 이어 붙이고(사용자가 손해 보지
    않도록), 이미 지났으면 **지금부터** 센다(과거 시점에서 더하면 갱신하자마자 또 만료된다).

    ## 동시 갱신 방어 (2026-08-13 Sprint 78)

    이 함수는 read -> compute -> write이고, 예전에는 write가 `WHERE id=?`뿐이었다. 그래서
    두 갱신이 겹치면 **뒤엣것이 앞엣것의 연장을 통째로 덮어썼다.** 결정적으로 재현했다
    (SELECT와 UPDATE 사이에 다른 커넥션의 갱신을 끼워 넣는 방식, journal_mode=delete/wal
    양쪽 동일):

        기존 만료 2026-06-25, 30일 갱신 2건(=결제 2건)
          기대: 60일 연장   실제: **30일**   -> 사용자가 산 기간 한 주기를 잃는다

    같은 모듈의 `change_status()`는 이미 "조건부 UPDATE + rowcount 확인"으로 이 부류를
    막고 있었다(registry.py §19 / payments.py 환불과 같은 패턴). 돈을 받고 기간을 늘리는
    쪽에만 그 가드가 없었다.

    **`BEGIN IMMEDIATE`를 쓰지 않는 이유**: 이 함수는 `change_status()`와 트랜잭션 계약이
    다르다 — 호출부가 트랜잭션을 소유한다(테스트/호출부가 `BEGIN` 안에서 부른다). 여기서
    새 트랜잭션을 시작하면 "cannot start a transaction within a transaction"으로 기존
    계약이 깨진다. 그래서 낙관적 잠금(읽은 값을 UPDATE의 WHERE에 다시 거는 방식)만 쓴다 —
    잠금 모드와 무관하게 동작하고, 계약을 바꾸지 않는다.

    충돌을 감지하면 조용히 덮어쓰는 대신 `ConcurrentStatusChange`를 던진다. 호출부는
    **다시 읽어 다시 계산**해야 한다(재시도하면 두 주기가 정확히 누적된다). 갱신은 돈이
    걸린 조작이라 "성공했다고 응답했지만 기간이 늘지 않은" 상태를 만들면 안 된다.

    **던질 때 롤백하지 않는다** — `change_status()`와 다른 점이다. 그쪽은 트랜잭션을
    소유하므로 스스로 되돌려야 하지만, 여기서 롤백하면 같은 트랜잭션에 담긴 호출부의 다른
    작업(결제 기록 등)까지 함께 지운다. 대신 호출부가 **재시도 전에 롤백해야 한다** —
    실패한 UPDATE가 열어 둔 쓰기 트랜잭션을 닫지 않으면 다음 쓰기가 `database is locked`로
    막힌다(`test_subscription_policy.py` §11이 이 계약을 고정한다).
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
            # 형식이 깨져 있으면 지금부터 센다. 폴백 방향은 옳지만(과거 시점에서 더하면
            # 갱신하자마자 또 만료된다) 조용히 넘어가면 안 된다 — 사용자가 남은 기간을
            # 잃는 쪽이므로 반드시 드러나야 한다 (2026-08-11 Sprint 56).
            logger.warning(
                "구독 %s의 만료 시각을 해석할 수 없습니다 (expires_at=%r) ― "
                "기존 잔여 기간을 이어 붙이지 못하고 지금부터 다시 셉니다",
                subscription_id, row["expires_at"]
            )

    new_expires = (base + timedelta(days=period_days)).isoformat()
    if row["status"] != SubscriptionStatus.ACTIVE:
        assert_subscription_transition(row["status"], SubscriptionStatus.ACTIVE)

    # 읽었던 값(status/expires_at)을 WHERE에 다시 건다. 그 사이 다른 갱신이나 상태 변경이
    # 먼저 반영됐다면 rowcount==0이 되어 이 UPDATE는 아무 행도 건드리지 않는다.
    # `expires_at`은 NULL일 수 있으므로(무기한 구독) `=` 대신 `IS`로 비교해야 한다 —
    # `NULL = NULL`은 SQL에서 참이 아니라 NULL이라, `=`를 쓰면 무기한 구독의 갱신이
    # **항상** 충돌로 오판된다.
    cursor = conn.execute(
        "UPDATE subscriptions SET status=?, expires_at=?, updated_at=?"
        " WHERE id=? AND status=? AND expires_at IS ?",
        (SubscriptionStatus.ACTIVE.value, new_expires, now.isoformat(),
         subscription_id, row["status"], row["expires_at"]),
    )
    if cursor.rowcount == 0:
        raise ConcurrentStatusChange(
            "다른 요청이 먼저 구독을 갱신/변경했습니다"
            f" (기대한 현재 상태: {row['status']}, 만료: {row['expires_at']})"
        )
    logger.info("구독 갱신: id=%s expires %s -> %s (by=%s)",
                subscription_id, row["expires_at"], new_expires, actor)
    updated = conn.execute("SELECT * FROM subscriptions WHERE id=?", (subscription_id,)).fetchone()
    return {"before": row_to_subscription(row), "after": row_to_subscription(updated)}


# ---------------------------------------------------------------------------
# 사용자용 조회 엔드포인트 (2026-08-11 Sprint 52 신설)
#
# 왜 지금 만드는가 — **결제한 사용자가 자기 구독을 볼 방법이 아예 없었다.**
# `GET /api/v1/payments`(결제 내역)는 있는데 구독은 사용자용 경로가 하나도 없어서,
# 프론트는 등기부 신청이 실패할 때 돌아오는 error code(REGISTRY_SUBSCRIPTION_REQUIRED)로
# "구독이 없구나"를 **간접 추론**하는 것이 유일한 방법이었다. 플랜/만료일/유예기간을
# 확인할 방법은 없었다(2026-08-09 Sprint 38이 "사용자용 엔드포인트 자체가 없다"고 기록).
#
# 마이페이지 화면의 **스펙은 미정**이라 화면은 만들지 않는다(`docs/FRONTEND_MASTER_SPEC.md` §16).
# 다만 어떤 마이페이지 스펙이 나오든 반드시 필요한 이 조회 계약은 화면과 무관하게 성립하므로
# 여기까지만 만든다. 새 개념을 도입하지 않고 이 모듈의 기존 함수를 그대로 재사용한다.
#
# 응답 형태는 `/payments`·`/favorites`·`/recent-items`와 동일한 **envelope + 리스트**다.
# 새 관례를 만들지 않는다 — 어느 것이 지금 유효한지는 각 행의 `is_entitled`로 판단한다.
# ---------------------------------------------------------------------------
from fastapi import APIRouter, Depends  # noqa: E402  (모듈 하단 배치 — 위쪽은 순수 로직)

from api.auth import get_current_user, success  # noqa: E402
from storage.database import get_connection  # noqa: E402

router = APIRouter()


@router.get("/subscriptions/me")
def get_my_subscriptions(user_id: str = Depends(get_current_user)):
    """내 구독 목록(최신순). 인증 필수 — 본인 것만 반환한다.

    조회 시점에 시간 경과분을 반영한다(lazy sync) — Admin 목록과 같은 규칙이라
    "관리자 화면에서는 만료인데 사용자 화면에서는 아직 ACTIVE" 같은 불일치가 생기지 않는다.
    """
    conn = get_connection()
    try:
        # 이 사용자 것만 동기화한다. 읽기 경로라 여기서 확정해야 변경이 남는다(commit=True).
        sync_expired_status(conn, user_id=user_id, commit=True)
        rows = conn.execute(
            # created_at 동률 시 순서가 흔들리지 않도록 id로 tie-break(전 도메인 공통 규칙).
            "SELECT * FROM subscriptions WHERE user_id=? ORDER BY created_at DESC, id DESC",
            (user_id,),
        ).fetchall()
        return success([row_to_subscription(r) for r in rows])
    finally:
        conn.close()
