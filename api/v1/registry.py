import os
import mimetypes
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from datetime import datetime
from storage.database import get_connection
from api.auth import get_current_user, success, error_response
from api.constants import (
    ErrorCode, RegistryRequestStatus, RegistryCreditReason, SubscriptionStatus,
    is_sqlite_int,
)
from api.v1.registry_credits import log_credit_event

router = APIRouter()

# 플랜을 알 수 없을 때(구독 정보 조회 실패 등) 적용할 보수적 기본 한도.
# 실제 한도는 플랜별로 다르며 api/v1/payments.py의 PLAN_CATALOG가 단일 기준이다.
DEFAULT_FREE_LIMIT = 5
OVERAGE_FEE = 1000  # 무료 초과 시 건당 금액. api/v1/payments.py의 OVERAGE_USAGE 결제 검증이 이 값을 그대로 참조한다.

# 등기부 실제 문서 저장 위치. api/v1/documents.py의 DOCUMENT_ROOT(크롤러가 수집하는
# STATUS/SPEC/APPRAISAL)와는 별개다 — 등기부등본은 이 크롤러가 수집하는 대상이 아니라
# 별도 경로(대법원 인터넷등기소 등)로 발급받아 운영자가 Admin(api/v1/admin.py)을 통해
# doc_url을 등록하는 방식으로 연결한다(자동 수집 엔진 아님, 문서 전달 경로만 구현).
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REGISTRY_DOCUMENT_ROOT = os.path.join(PROJECT_ROOT, "registry_documents")

class RegistryRequest(BaseModel):
    item_id: int

def get_month_start(now: datetime = None) -> str:
    """이번 달 1일 00:00:00의 ISO 문자열. 무료 한도는 매월 리셋된다(정책 확정: 월 단위)."""
    now = now or datetime.now()
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()


def get_free_count(conn, user_id: str) -> int:
    """
    이번 달에 소진한 무료 등기부 횟수.

    used_at은 datetime.now().isoformat() 형식으로 저장되므로 문자열 비교로 월 경계를 나눌 수
    있다(ISO 8601은 사전순 = 시간순). 월이 바뀌면 자동으로 0부터 다시 센다 — 별도 리셋 배치 불요.
    """
    return conn.execute(
        "SELECT COUNT(*) FROM registry_usage WHERE user_id=? AND is_free=1 AND used_at >= ?",
        (user_id, get_month_start())
    ).fetchone()[0]


def get_entitled_subscription(conn, user_id: str, at: datetime = None):
    """지금 서비스를 이용할 수 있는 구독 행. 없으면 None.

    **판정을 SQL이 아니라 Python에서 한다.** 이유가 두 가지 있다:

    1) 유예 기간(GRACE_PERIOD)은 "만료시각 + 3일"이라 SQL 비교식만으로는 표현이 지저분하다.
       `state_machines.resolve_expected_status()`가 이미 그 규칙의 단일 기준이므로 재사용한다.
    2) DB에 저장된 status가 최신이 아닐 수 있다(자동 만료는 lazy sync 방식이라 조회 시점에
       맞춰진다). 여기서 `sync_expired_status()`를 부르면 **커밋이 일어나** 이 함수를
       호출하는 `create_registry_request()`의 `BEGIN IMMEDIATE` 트랜잭션이 중간에 끊긴다.
       그래서 DB는 건드리지 않고 "지금 있어야 할 상태"만 계산해 판정한다.

    정렬 tie-break(`id DESC`): `started_at`은 `datetime.now().isoformat()`인데 Windows의
    시계 분해능(~15.6ms)상 짧은 간격의 두 결제가 **완전히 같은 문자열**을 가질 수 있다.
    그러면 `ORDER BY started_at DESC`만으로는 어느 구독이 뽑힐지 정해지지 않아, 플랜
    업그레이드(베이직→프로) 직후 한도가 옛 플랜으로 잘못 계산될 수 있었다(docs/BUGS.md #16).
    """
    from api.v1.state_machines import is_entitled, resolve_expected_status

    now = at or datetime.now()
    rows = conn.execute("""
        SELECT * FROM subscriptions
        WHERE user_id=? AND status IN (?, ?)
        ORDER BY started_at DESC, id DESC
    """, (user_id, SubscriptionStatus.ACTIVE.value,
          SubscriptionStatus.GRACE_PERIOD.value)).fetchall()

    for row in rows:
        effective = resolve_expected_status(row["status"], row["expires_at"], now)
        if is_entitled(effective, row["expires_at"], now):
            return row
    return None


def get_plan_free_limit(conn, user_id: str) -> int:
    """
    플랜이 정하는 이번 달 무료 한도(관리자 조정 전 값).
    이용 가능한 구독의 plan에 따라 달라진다(베이직 5회 / 프로 10회).
    구독이 없으면 애초에 신청 자체가 막히므로 도달하지 않지만,
    플랜명을 해석할 수 없는 경우에는 보수적으로 기본값을 쓴다.
    """
    from api.v1.payments import get_registry_monthly_limit

    row = get_entitled_subscription(conn, user_id)
    if not row:
        return DEFAULT_FREE_LIMIT
    limit = get_registry_monthly_limit(row["plan"])
    return limit if limit > 0 else DEFAULT_FREE_LIMIT


def get_user_free_limit(conn, user_id: str) -> int:
    """
    실제로 적용되는 이번 달 무료 한도 = 플랜 한도 + 관리자 조정 합계.

    관리자 조정(api/v1/registry_credits.py)은 잔액 컬럼이 아니라 원장으로 관리되며,
    월이 바뀌면 자연히 초기화된다(기존 월 리셋 정책과 동일한 경계).
    차감이 과해 음수가 되면 0으로 막는다 — 무료 한도가 음수라는 상태는 의미가 없고,
    아래 `free_used < free_limit` 비교가 항상 거짓이 되어 전부 유료로 처리되면 충분하다.
    """
    from api.v1.registry_credits import get_credit_adjustment

    base = get_plan_free_limit(conn, user_id)
    return max(0, base + get_credit_adjustment(conn, user_id))

def has_active_subscription(conn, user_id: str) -> bool:
    """Premium 판정(docs/decision-log.md "Premium").

    2026-08-07: 판정 기준을 Lifecycle과 일치시켰다. 예전에는 `status='ACTIVE'`만 봐서,
    승인된 유예 기간(GRACE_PERIOD) 정책이 정의만 되고 실제 이용권 게이트에는 반영되지
    않는 상태였다 — 만료 직후 결제 재시도 중인 사용자가 즉시 차단됐다.
    이제 `get_entitled_subscription()` 하나가 유일한 판정 기준이다.

    함수명은 그대로 둔다 — `docs/decision-log.md`/`docs/backend.md`가 이 이름으로
    Premium 판정을 설명하고 있고, 이름을 바꾸면 문서·주석이 전부 어긋난다.
    """
    return get_entitled_subscription(conn, user_id) is not None

@router.post("/registry-requests")
def create_registry_request(req: RegistryRequest, user_id: str = Depends(get_current_user)):
    # SQLite INTEGER 범위 밖의 id는 어떤 물건도 될 수 없다 — 그대로 넘기면 sqlite3이
    # OverflowError를 던져 **로그인한 사용자가 500을 만들 수 있다**
    # (2026-08-17 Sprint 154 실측). 아래 "물건 존재 확인"과 같은 결론이므로 404로 끊는다.
    # get_connection() 앞에 두어 커넥션을 열지 않고 끝낸다.
    if not is_sqlite_int(req.item_id):
        raise HTTPException(status_code=404, detail="물건을 찾을 수 없습니다")
    conn = get_connection()
    # 무료횟수 COUNT는 api/v1/payments.py의 OVERAGE_USAGE처럼 "row 하나를 조건부로 잠그는"
    # 방식으로는 막을 수 없는 집계 값이라, 이 커넥션의 트랜잭션을 직접 제어해(BEGIN IMMEDIATE로
    # 즉시 쓰기 락 선점) COUNT 확인과 INSERT를 하나의 원자적 단위로 묶는다 — 동시 요청 중
    # 하나가 커밋을 마칠 때까지 다른 요청은 자신의 COUNT를 다시 셀 수 없으므로 레이스가 없어진다.
    conn.isolation_level = None
    try:
        # 물건 존재 확인
        item = conn.execute(
            "SELECT id FROM auction_item WHERE id=?", (req.item_id,)
        ).fetchone()
        if not item:
            raise HTTPException(status_code=404, detail="물건을 찾을 수 없습니다")

        # 구독 확인
        if not has_active_subscription(conn, user_id):
            return error_response(ErrorCode.REGISTRY_SUBSCRIPTION_REQUIRED, "구독이 필요합니다")

        now = datetime.now().isoformat()

        conn.execute("BEGIN IMMEDIATE")
        try:
            # 멱등성/중복 신청 방지 — 같은 사용자가 같은 물건에 이미 진행 중인 신청이
            # 있으면 그 신청을 그대로 돌려준다(새로 만들지 않는다). 이 검사가 없으면
            # 같은 item_id로 반복 호출할 때마다 무료횟수를 매번 새로 소진하거나
            # PAYMENT_REQUIRED 행이 계속 쌓여, 중복 클릭/새로고침 재제출/직접 API 호출로
            # 한 물건에 대해 무료 한도를 여러 번 소모하거나 중복 결제 대상을 만들 수 있었다
            # (2026-08-09 재현 확인: 승인 없이 수정 가능한 버그로 판단 — 새 UX/Spec을
            # 도입하는 게 아니라 "사용자당 물건당 진행 중인 신청은 1건"이라는, 기존
            # 응답 스키마를 그대로 쓰는 멱등 처리다. COMPLETED/FAILED는 종결 상태이므로
            # 재신청(재발급 시도)을 막지 않는다).
            existing = conn.execute("""
                SELECT * FROM registry_requests
                WHERE user_id=? AND item_id=? AND status IN (?,?,?)
                ORDER BY requested_at DESC, id DESC LIMIT 1
            """, (user_id, req.item_id, RegistryRequestStatus.PENDING.value,
                  RegistryRequestStatus.PAYMENT_REQUIRED.value,
                  RegistryRequestStatus.PROCESSING.value)).fetchone()

            # 무료 횟수 확인 (이 지점부터는 쓰기 락을 쥐고 있어 다른 요청과 절대 겹치지 않는다)
            # 한도는 플랜별로 다르고(베이직 5 / 프로 10), 사용량은 이번 달 것만 센다.
            # 기존 신청을 그대로 돌려줄 때도 "지금 남은 무료 횟수"는 최신값으로 안내해야
            # 하므로 이 계산은 existing 분기 이전에 항상 수행한다(추가 소모는 하지 않음).
            free_limit = get_user_free_limit(conn, user_id)
            free_used = get_free_count(conn, user_id)

            if existing:
                conn.commit()
                return success({
                    "id": existing["id"],
                    "item_id": existing["item_id"],
                    "status": existing["status"],
                    "is_free": existing["status"] != RegistryRequestStatus.PAYMENT_REQUIRED.value,
                    "free_remaining": max(0, free_limit - free_used),
                    "charged_amount": OVERAGE_FEE if existing["status"] == RegistryRequestStatus.PAYMENT_REQUIRED.value else 0,
                    "requested_at": existing["requested_at"],
                    "already_requested": True,
                })

            is_free = free_used < free_limit
            # 청구액은 여기서 한 번만 정한다 — 아래 두 분기의 응답/기록이 같은 값을 쓴다.
            charged_amount = 0 if is_free else OVERAGE_FEE

            # PAYMENT_REQUIRED 처리
            if not is_free:
                req_id = conn.execute("""
                    INSERT INTO registry_requests
                    (user_id, item_id, status, requested_at)
                    VALUES (?,?,?,?)
                """, (user_id, req.item_id, RegistryRequestStatus.PAYMENT_REQUIRED.value, now)).lastrowid
                conn.commit()
                return success({
                    "id": req_id,
                    "item_id": req.item_id,
                    "status": RegistryRequestStatus.PAYMENT_REQUIRED.value,
                    "is_free": False,
                    "free_remaining": 0,
                    "charged_amount": charged_amount,
                    "requested_at": now,
                })

            # 무료 사용 기록
            usage_id = conn.execute("""
                INSERT INTO registry_usage
                (user_id, item_id, is_free, charged_amount, used_at)
                VALUES (?,?,?,?,?)
            """, (user_id, req.item_id, 1, charged_amount, now)).lastrowid

            # 무료 횟수 변동 추적 로그(CTO 승인 4번 — 기록 대상에 "사용"이 포함된다).
            # ★ 이 로그는 한도 계산에 반영되지 않는다. 사용량은 registry_usage가 이미 세고
            # 있어서(get_free_count) 조정 원장에도 넣으면 이중 차감이 된다 —
            # registry_credit_logs는 "무엇이 언제 왜 움직였는가"를 보는 추적 전용이다.
            # balance_after에는 이 사용을 반영한 잔여 무료 횟수를 남긴다.
            log_credit_event(
                conn, user_id, RegistryCreditReason.USAGE, -1,
                reason=f"등기부 신청 (item_id={req.item_id})",
                actor="USER", related_usage_id=usage_id,
                balance_after=free_limit - free_used - 1,
            )

            # 신청 생성
            req_id = conn.execute("""
                INSERT INTO registry_requests
                (user_id, item_id, usage_id, status, requested_at)
                VALUES (?,?,?,?,?)
            """, (user_id, req.item_id, usage_id, RegistryRequestStatus.PENDING.value, now)).lastrowid

            conn.commit()
            return success({
                "id": req_id,
                "item_id": req.item_id,
                "status": RegistryRequestStatus.PENDING.value,
                "is_free": True,
                "free_remaining": free_limit - free_used - 1,
                "charged_amount": charged_amount,
                "requested_at": now,
            })
        except Exception:
            conn.rollback()
            raise
    finally:
        conn.close()

@router.get("/registry-requests")
def get_registry_requests(user_id: str = Depends(get_current_user)):
    conn = get_connection()
    try:
        # ★ LEFT JOIN이어야 한다 (2026-08-13 Sprint 98).
        #
        #   `auction_item` 행이 사라진 신청은 INNER JOIN에서 **목록에서 통째로 사라진다.**
        #   그런데 그 신청은 **멀쩡히 쓸 수 있는 상태다** — 다운로드 경로
        #   (`download_registry()`)는 JOIN을 하지 않으므로, 실제 파일만 있으면 200으로
        #   문서를 그대로 내려준다. 즉 "받을 수는 있는데 화면에는 존재하지 않는" 신청이다.
        #
        #   프런트가 request_id를 얻는 유일한 경로가 이 목록이라(`mypage/page.tsx:146`,
        #   `properties/[id]/page.tsx:257`) 사용자는 **자기가 돈을 내고 발급받은 문서에
        #   도달할 방법이 없다.** 관리자 목록은 Sprint 97에서 LEFT JOIN으로 고쳐 보이는데
        #   정작 소유자에게만 안 보인다 — Sprint 95(admin이 파일 존재를 확인하지 않아
        #   "완료인데 못 받는" 상태를 만든 것)와 방향만 반대인 같은 부류다.
        #
        #   임시 복사본에서 실측(Sprint 98): 물건 행 삭제 후
        #   사용자 목록 0건 / 사용자 상세 404 / 관리자 목록 1건 / 다운로드 200.
        #
        #   `case_no`/`full_address`는 None으로 내려간다 — 프런트는 이미 두 필드를
        #   `string | null`로 선언하고 `|| '-'`로 그리므로 계약 변경이 아니다.
        rows = conn.execute("""
            SELECT rr.*, ai.full_address, ai.case_no
            FROM registry_requests rr
            LEFT JOIN auction_item ai ON rr.item_id = ai.id
            WHERE rr.user_id = ?
            ORDER BY rr.requested_at DESC, rr.id DESC
        """, (user_id,)).fetchall()
        return success([{
            "id": r["id"],
            "item_id": r["item_id"],
            "case_no": r["case_no"],
            "full_address": r["full_address"],
            "status": r["status"],
            "reason": r["reason"],
            "requested_at": r["requested_at"],
            "completed_at": r["completed_at"],
        } for r in rows])
    finally:
        conn.close()

@router.get("/registry-requests/{request_id}")
def get_registry_request(request_id: int, user_id: str = Depends(get_current_user)):
    # 범위 밖 id는 어떤 신청도 될 수 없다(OverflowError -> 500 방지, Sprint 154).
    if not is_sqlite_int(request_id):
        raise HTTPException(status_code=404, detail="신청을 찾을 수 없습니다")
    conn = get_connection()
    try:
        # LEFT JOIN 이유는 위 목록(`get_registry_requests()`)과 같다 (Sprint 98).
        # 여기서 INNER JOIN을 남겨두면 목록에는 보이는 신청이 상세에서만 404가 되어,
        # 사용자가 카드를 눌렀을 때 "없는 신청"이라는 거짓말을 보게 된다.
        row = conn.execute("""
            SELECT rr.*, ai.full_address, ai.case_no
            FROM registry_requests rr
            LEFT JOIN auction_item ai ON rr.item_id = ai.id
            WHERE rr.id=? AND rr.user_id=?
        """, (request_id, user_id)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="신청을 찾을 수 없습니다")
        return success({
            "id": row["id"],
            "item_id": row["item_id"],
            "case_no": row["case_no"],
            "full_address": row["full_address"],
            "status": row["status"],
            "reason": row["reason"],
            "requested_at": row["requested_at"],
            "completed_at": row["completed_at"],
        })
    finally:
        conn.close()

@router.get("/registry-requests/{request_id}/download")
def download_registry(request_id: int, user_id: str = Depends(get_current_user)):
    # 범위 밖 id는 어떤 신청도 될 수 없다(OverflowError -> 500 방지, Sprint 154).
    # 소유권 확인과 같은 이유로 존재 자체를 노출하지 않는 404를 그대로 쓴다.
    if not is_sqlite_int(request_id):
        raise HTTPException(status_code=404, detail="신청을 찾을 수 없습니다")
    conn = get_connection()
    try:
        # 본인 신청만 조회 가능(WHERE user_id=?로 소유권 확인) — 다른 유저의 request_id를
        # 넣어도 404로 응답해 존재 자체를 노출하지 않는다.
        row = conn.execute(
            "SELECT * FROM registry_requests WHERE id=? AND user_id=?",
            (request_id, user_id)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="신청을 찾을 수 없습니다")
        if row["status"] != RegistryRequestStatus.COMPLETED.value:
            # PENDING/PAYMENT_REQUIRED/PROCESSING/FAILED 등 실제 상태를 그대로 알려준다(거짓 UI 금지).
            return error_response(ErrorCode.REGISTRY_NOT_COMPLETED, f"발급이 완료되지 않았습니다 (현재 상태: {row['status']})")
        if not row["doc_url"]:
            # COMPLETED인데 doc_url이 없는 경우는 admin.py가 COMPLETED 전이 시 doc_url을 필수로
            # 받으므로 정상 경로로는 발생하지 않지만, 방어적으로 처리한다.
            return error_response(ErrorCode.REGISTRY_DOCUMENT_NOT_FOUND, "발급된 문서를 찾을 수 없습니다")

        # 경로 탐색 방지: api/v1/documents.py:get_document()와 동일한 방식(commonpath 검사).
        file_path = os.path.join(REGISTRY_DOCUMENT_ROOT, row["doc_url"])
        real_root = os.path.realpath(REGISTRY_DOCUMENT_ROOT)
        real_file_path = os.path.realpath(file_path)
        # ★ 2026-08-26 (`docs/BUGS.md` #229): 드라이브가 다르면 `commonpath` 가 ValueError 다.
        #   위 주석이 가리키는 `documents.py` 를 그대로 베껴 왔는데 **그쪽도 같은 구멍**이었다
        #   — 복제된 판정은 결함까지 함께 복제된다. 세 곳을 같은 방식으로 맞췄다.
        try:
            outside = os.path.commonpath([real_root, real_file_path]) != real_root
        except ValueError:
            outside = True
        if outside:
            raise HTTPException(status_code=404, detail="문서를 찾을 수 없습니다")
        # "있다"의 기준을 **저장소의 다른 파일 서빙 경로와 같게** 맞춘다 (2026-08-14).
        #
        #   예전에는 `os.path.exists()`만 봤다. 두 가지가 새어 나갔다.
        #
        #   1. **0바이트 파일이 200으로 나간다.** 사용자는 등기부 발급에 돈을 내고
        #      **빈 파일**을 받는다. 오류 안내조차 없다(실측 재현: HTTP 200 / 0 bytes).
        #      `api/v1/documents.py`(무료 법원문서)는 Sprint 98에 이미 이것을 막았는데,
        #      **돈이 걸린 이쪽이 더 느슨하게 남아 있었다.**
        #   2. `exists()`는 **디렉터리에도 True**다. 그 경우 아래 FileResponse가 터져
        #      404가 아니라 500이 된다.
        #
        #   기준은 이 저장소가 이미 합의해 둔 것을 쓴다 —
        #   `crawler/doc_paths.py:doc_exists()` = `exists() and getsize() > 0`.
        #   쓰는 쪽(크롤러)과 읽는 쪽(API)이 같은 정의를 쓰지 않으면, 한쪽은 "없음"이라
        #   재수집 대상으로 보는 파일을 다른 쪽은 "있음"이라고 답하게 된다.
        if not os.path.isfile(real_file_path) or os.path.getsize(real_file_path) == 0:
            raise HTTPException(status_code=404, detail="문서 파일을 찾을 수 없습니다")

        media_type, _ = mimetypes.guess_type(real_file_path)
        return FileResponse(
            real_file_path,
            media_type=media_type or "application/octet-stream",
            filename=os.path.basename(real_file_path),
            content_disposition_type="attachment",
        )
    finally:
        conn.close()
