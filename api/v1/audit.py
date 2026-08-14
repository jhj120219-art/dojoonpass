"""Admin 작업 감사 로그 (CTO 승인 5번).

기록 항목: admin_id / action / target_type / target_id / before / after / created_at

기존에도 `logger.info`로 상태 전이를 남기고 있었지만, 로그 파일은 회전·유실되고 조회가
불가능하다. DB에 남겨야 "이 신청이 왜 FAILED가 됐는지"를 나중에 실제로 되짚을 수 있다.

`before`/`after`는 **변경된 필드만** JSON으로 담는다 — 전체 행을 통째로 넣으면 무엇이
바뀌었는지 오히려 안 보이고, 민감정보가 섞여 들어갈 여지도 커진다.
"""
import json
import logging
from datetime import datetime
from typing import Any, Optional

logger = logging.getLogger(__name__)


# 민감 키 마스킹은 `payment_logs.py` 것을 **재사용**한다 (2026-08-14).
#
# 세 번째 복사본을 만들지 않는다 — 같은 판정을 여러 벌 두면 한쪽만 고쳐져 갈라진다는 것이
# 이 저장소가 반복해서 겪은 문제다(0바이트 판정 5벌, 시각 비교 2벌 …).
# `payment_logs`는 audit 를 import 하지 않으므로 순환도 생기지 않는다.
from api.v1.payment_logs import mask_sensitive  # noqa: E402


def _dump(value: Any) -> Optional[str]:
    """감사 로그용 직렬화. **마스킹을 거친다.**

    위 docstring 이 "전체 행을 통째로 넣으면 민감정보가 섞여 들어갈 여지가 커진다"고
    경고하지만, 그건 **관례**일 뿐 강제되지 않았다. 실제 호출부 5곳은 전부 손으로 고른
    스칼라 dict 를 넘기고 있어 지금은 안전하다(2026-08-14 전수 확인 — `card_no`/`cvc`/
    `access_token` 같은 키가 하나도 없다).

    문제는 그 다음이다. 누가 `before=webhook_row` 처럼 행을 통째로 넘기면 그대로
    `audit_logs` 에 저장되고, **그 로그는 운영자가 폭넓게 열람한다.**
    결제 로그(`payment_logs._dump`)는 이미 마스킹을 하는데 감사 로그만 하지 않아
    **같은 성질의 기록에 서로 다른 기준**이 적용되고 있었다.

    지금 payload 들에는 민감 키가 없으므로 이 변경은 **동작상 무영향**(no-op)이고,
    앞으로의 사고만 막는다. `default=str` 은 그대로 둔다 — datetime 등이 섞여도
    직렬화가 죽지 않아야 한다(감사 기록을 잃는 것이 더 나쁘다).
    """
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return json.dumps(mask_sensitive(value), ensure_ascii=False, default=str)


def record_audit(
    conn,
    admin_id: str,
    action: str,
    target_type: str,
    target_id: Any = None,
    before: Any = None,
    after: Any = None,
    at: datetime = None,
) -> int:
    """감사 로그 1건. commit은 호출부 책임이다(업무 트랜잭션과 함께 커밋되어야 하므로).

    감사 기록이 실패했다고 본 업무를 되돌리면 안 되지만, 반대로 본 업무만 커밋되고 감사가
    빠지는 것도 곤란하다 — 같은 커넥션·같은 트랜잭션에 넣어 둘이 함께 성립하게 한다.
    """
    return conn.execute(
        """
        INSERT INTO audit_logs
        (admin_id, action, target_type, target_id, before, after, created_at)
        VALUES (?,?,?,?,?,?,?)
        """,
        (admin_id, action, target_type,
         str(target_id) if target_id is not None else None,
         _dump(before), _dump(after), (at or datetime.now()).isoformat()),
    ).lastrowid


def row_to_audit_log(row) -> dict:
    return {
        "id": row["id"],
        "admin_id": row["admin_id"],
        "action": row["action"],
        "target_type": row["target_type"],
        "target_id": row["target_id"],
        "before": row["before"],
        "after": row["after"],
        "created_at": row["created_at"],
    }


def get_audit_logs(conn, target_type: str = None, target_id: Any = None,
                   admin_id: str = None, action: str = None,
                   limit: int = 100, offset: int = 0) -> tuple[int, list]:
    """감사 로그 조회. `(total, items)`를 반환한다.

    정렬에 `id DESC` tie-break를 건다 — `created_at`이 동률이면 offset 페이지네이션에서
    같은 행이 두 페이지에 나오거나 빠질 수 있다(docs/BUGS.md #16과 같은 이유).
    """
    conditions = ["1=1"]
    params: list = []
    if target_type:
        conditions.append("target_type = ?")
        params.append(target_type)
    if target_id is not None:
        conditions.append("target_id = ?")
        params.append(str(target_id))
    if admin_id:
        conditions.append("admin_id = ?")
        params.append(admin_id)
    if action:
        conditions.append("action = ?")
        params.append(action)
    where = " AND ".join(conditions)

    total = conn.execute(
        "SELECT COUNT(*) FROM audit_logs WHERE %s" % where, params
    ).fetchone()[0]
    rows = conn.execute(
        "SELECT * FROM audit_logs WHERE %s ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?" % where,
        params + [limit, offset],
    ).fetchall()
    return total, [row_to_audit_log(r) for r in rows]
