"""임장(현장 확인) API — DISCOVER → REVIEW → **FIELD** → DECIDE 의 세 번째 칸.

## 왜 생겼나 (2026-09-04)

콕찰이 줄이려는 것은 "경매 의사결정에 드는 시간"이다. 그 시간은 네 칸으로 나뉘는데
(`docs/PRODUCT_STRATEGY.md`), 그중 **FIELD 가 코드에 한 줄도 없었다** — 전수 확인에서
`임장`/`field`/`inspection` 을 다루는 route·API·테이블이 0개였다.

그래서 사용자는 현장에서 본 것을 콕찰 밖(수첩·메모앱·카톡)에 적고, 판단할 때 그것을
다시 찾아 와야 했다. **그 왕복이 곧 이 제품이 줄이겠다고 말한 시간이다.**

## 무엇을 하고 무엇을 하지 않는가

하는 것 — 사용자가 **직접 확인하고 직접 적은 것**을 물건에 붙여 보관한다.
  체크리스트 / 현장 메모 / 위험요소 / 사용자 본인의 입찰 판단.

하지 않는 것 — **점수·추천·수익률·자동 투자판단.**
  `docs/decision-log.md` 와 `docs/CLAUDE.md` 가 프로젝트 범위 밖으로 못박았다.
  이 모듈은 판단을 **대신하지 않고 기록만** 한다. `decision` 은 사용자가 고른 값이다.

## 마이그레이션이 아직 안 돈 환경

030 의 운영 적용은 승인 영역이다(`docs/CLAUDE.md`). 그래서 표가 없는 환경이 실제로
존재한다. 그때 **조용히 성공하지 않는다** — 503 + `FIELD_UNAVAILABLE` 로 답한다.
`api/v1/favorites.py` 가 `favorite_notes` 에 쓰는 것과 같은 방식이고, 같은 이유다:
`INTERNAL_ERROR` 로 뭉뚱그리면 화면이 "서버 오류"를 띄워, 운영자가 실제로 해야 할 일
(마이그레이션 적용)을 알 수 없다.
"""
import logging
import sqlite3
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from storage.database import get_connection
from api.auth import get_current_user, success, error_response
from api.constants import ErrorCode, is_sqlite_int

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# 체크리스트 — **어휘의 정본은 여기 하나뿐이다.**
#
# 항목을 행(`field_visit_checks.check_key`)으로 저장하는 이유가 이것이다. 열로 두면
# 항목이 바뀔 때마다 마이그레이션이 필요하고, 그 적용은 승인 영역이라 제품 속도가
# 스키마에 묶인다. 지금은 이 튜플을 고치면 끝난다.
#
# ★ 항목을 새로 지어내지 않았다. 전부 **제품이 이미 모델링하고 있는 개념**에
#   앵커링했다 — 현장에서 확인할 것은 "문서로는 알 수 없는 그 개념의 실제 상태"다:
#
#     occupancy   `rights_summary.occupancy_status` / `is_vacant`  (점유 상태)
#     tenant      `tenant_rights` 행                                (임차인)
#     eviction    `rights_summary.occupancy_difficulty`             (명도 난이도)
#     building    물건 자체(감정평가서로는 외관·노후를 알 수 없다)
#     surroundings `auction_item.full_address` 주변                 (입지)
#     price       `appraisal_price` / `minimum_bid_price` 대비 실거래
#
#   즉 이 목록은 "새 제품 정책"이 아니라 **이미 있는 데이터의 현장 대조표**다.
#   문구 자체는 제품 결정이므로 바뀔 수 있고, 그때 바꾸는 곳이 여기 한 곳이다.
CHECK_ITEMS = (
    ("occupancy", "점유 상태 — 실제로 누가 살고 있는가"),
    ("tenant", "임차인 — 만나서 확인했는가"),
    ("eviction", "명도 난이도 — 협의 가능성"),
    ("building", "건물 상태 — 외관·노후·하자"),
    ("surroundings", "주변 환경 — 접근성·소음·상권"),
    ("price", "실제 시세 — 인근 실거래 대비"),
)
CHECK_KEYS = tuple(k for k, _ in CHECK_ITEMS)

# 임장 진행 상태.
FIELD_STATUS_IN_PROGRESS = "IN_PROGRESS"
FIELD_STATUS_DONE = "DONE"
FIELD_STATUSES = (FIELD_STATUS_IN_PROGRESS, FIELD_STATUS_DONE)

# 사용자 본인의 입찰 판단. **제품이 계산하지 않는다** — 고르는 것은 사람이다.
DECISION_BID = "BID"      # 입찰한다
DECISION_HOLD = "HOLD"    # 더 본다
DECISION_DROP = "DROP"    # 접는다
DECISIONS = (DECISION_BID, DECISION_HOLD, DECISION_DROP)

# 자유 서술 길이 상한. 모바일 한 손 입력이 전제라 짧다 —
# 긴 글을 받으려고 만든 자리가 아니다(현장에서 길게 쓰지 않는다).
MAX_NOTE_LEN = 2000


def _table_ready(conn) -> bool:
    """030 이 적용된 환경인가. `favorites.py` 의 `notes_ready` 와 같은 판정이다."""
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='field_visits'"
    ).fetchone() is not None


def _require_valid_id(item_id: int):
    """범위 밖 id 는 **어떤 행도 될 수 없다** — 표가 있든 없든 답이 같다.

    ★ 순서가 중요하다 (2026-09-04, `test_id_bounds_sweep.py` 가 잡았다).
      처음에는 `_require_table()` 을 먼저 불렀다. 그러면 마이그레이션이 안 된
      환경에서 **범위 밖 id 까지 503** 을 받는다 — 사용자 입력이 틀린 것을
      "서버가 준비되지 않았다"로 답하는 셈이고, 저장소의 "어떤 라우트도 5xx 를
      내지 않는다" 불변식도 깬다(Sprint 154 가 세운 규칙).

      싼 검사를 먼저 한다: id 가 애초에 물건이 될 수 없으면 404 다.
    """
    if not is_sqlite_int(item_id):
        raise HTTPException(
            status_code=404,
            detail=error_response(ErrorCode.ITEM_NOT_FOUND, "물건을 찾을 수 없습니다"))


def _require_table(conn):
    if not _table_ready(conn):
        # 503 - 코드 결함이 아니라 **환경이 아직 준비되지 않은 것**이다.
        raise HTTPException(
            status_code=503,
            detail=error_response(
                ErrorCode.FIELD_UNAVAILABLE,
                "임장 기능이 아직 준비되지 않았습니다 (migration 030 미적용)"),
        )


def _item_exists(conn, item_id: int) -> bool:
    """`api/v1/favorites.py:item_exists()` 와 **같은 판정**이다.

    `is_sqlite_int` 가드도 같은 이유로 있다 — 범위 밖 id 를 그대로 넘기면 sqlite3 이
    OverflowError 를 내서 **로그인한 사용자가 500 을 만들 수 있다**(Sprint 154).
    """
    if not is_sqlite_int(item_id):
        return False
    return conn.execute(
        "SELECT 1 FROM auction_item WHERE id = ?", (item_id,)
    ).fetchone() is not None


def _clip(text: Optional[str]) -> Optional[str]:
    """빈 문자열은 None 으로 접는다 — "안 적었다"와 "빈칸을 적었다"를 나누지 않는다."""
    if text is None:
        return None
    text = text.strip()
    return text or None


def _visit_row(conn, user_id: str, item_id: int):
    return conn.execute(
        "SELECT * FROM field_visits WHERE user_id = ? AND item_id = ?",
        (user_id, item_id)).fetchone()


def _checks_of(conn, visit_id: int) -> dict:
    rows = conn.execute(
        "SELECT check_key, checked, note FROM field_visit_checks WHERE visit_id = ?",
        (visit_id,)).fetchall()
    return {r["check_key"]: r for r in rows}


# ---------------------------------------------------------------------------
# REVIEW -> FIELD 준비 (2026-09-04)
#
# 사용자가 임장을 시작할 때 **"현장에서 무엇을 확인해야 하는가"를 이미 일부 알고
# 있게** 한다. 상세 화면에서 본 것을 현장에서 다시 떠올리려고 앱을 오가는 왕복이
# 곧 T2D 이고, 그 왕복을 줄이는 것이 이 기능의 전부다.
#
# ★ 새 판단 기준을 만들지 않는다
#
#   여기서 하는 일은 **이미 저장된 값을 그대로 옮겨 적는 것**뿐이다. "위험하다" /
#   "주의" 같은 평가를 붙이지 않는다 — 그것은 새 법률 판단 기준이고
#   `docs/decision-log.md` 가 범위 밖으로 못박은 자동 투자판단에 가깝다.
#   항목마다 붙는 값은 전부 다른 화면이 이미 보여 주고 있는 사실이다.
#
# ★ 개인정보를 싣지 않는다
#
#   `tenant_rights` 에는 **임차인 실명 240행 + 전체 주소 + 보증금**이 들어 있다
#   (`api/v1/item.py` 머리말, `docs/BUGS.md` #254). 그래서 그 표를 조인하지 않고
#   `rights_summary.total_tenant_count` 라는 **이미 집계된 수**만 쓴다. 현장에서
#   필요한 것은 "몇 명인가"이지 "누구인가"가 아니다.
#
# ★ 저장하지 않는다
#
#   `field_visits` 에 복사해 두면 그날의 값이 굳어 원본과 갈라진다(이 저장소가
#   반복해 겪은 모양). 읽을 때마다 현재 값을 본다.
def _review_facts(conn, item_id: int) -> dict:
    """이 물건에 대해 **이미 저장돼 있는** 사실. 없으면 빈 dict.

    스키마가 뒤처진 환경(면적 컬럼이 없는 DB 등)에서도 죽지 않는다 —
    부가 정보 하나 때문에 임장 화면이 통째로 실패하면 안 된다.
    """
    facts = {}
    try:
        row = conn.execute(
            "SELECT property_type, sido, sigungu, dong, status,"
            "       case_no, item_no, court_name, full_address FROM auction_item"
            " WHERE id = ?", (item_id,)).fetchone()
        if row:
            facts.update({k: row[k] for k in row.keys()})
    except sqlite3.Error:
        pass
    # 면적은 025 가 만든다 - 없는 환경이 실제로 있다.
    try:
        row = conn.execute(
            "SELECT building_area, land_area FROM auction_item WHERE id = ?",
            (item_id,)).fetchone()
        if row:
            facts.update({k: row[k] for k in row.keys()})
    except sqlite3.Error:
        pass
    try:
        row = conn.execute(
            "SELECT occupancy_status, is_vacant, occupancy_difficulty,"
            " total_tenant_count FROM rights_summary WHERE item_id = ?",
            (item_id,)).fetchone()
        if row:
            facts.update({k: row[k] for k in row.keys()})
    except sqlite3.Error:
        pass
    return facts


def _known_for(check_key: str, f: dict):
    """체크 항목 하나에 대해 **이미 아는 것**. 모르면 None.

    돌려주는 것은 짧은 사실 문장이다. 판단·권고가 아니다.
    모르면 `None` 을 준다 — "정보 없음" 같은 문구를 지어내지 않는다. 화면이
    그 자리를 어떻게 그릴지는 화면이 정한다.
    """
    def s(v):
        v = (v or "").strip() if isinstance(v, str) else v
        return v or None

    if check_key == "occupancy":
        parts = [p for p in (s(f.get("occupancy_status")),
                             ("공실로 기록됨" if f.get("is_vacant") == 1 else None)) if p]
        return " / ".join(parts) if parts else None
    if check_key == "tenant":
        n = f.get("total_tenant_count")
        return ("임차인 %d명으로 기록됨" % n) if isinstance(n, int) and n >= 0 else None
    if check_key == "eviction":
        return s(f.get("occupancy_difficulty"))
    if check_key == "building":
        parts = [p for p in (s(f.get("property_type")),
                             ("건물 %g㎡" % f["building_area"]) if f.get("building_area") else None,
                             ("토지 %g㎡" % f["land_area"]) if f.get("land_area") else None) if p]
        return " · ".join(parts) if parts else None
    if check_key == "surroundings":
        parts = [p for p in (s(f.get("sido")), s(f.get("sigungu")), s(f.get("dong"))) if p]
        return " ".join(parts) if parts else None
    if check_key == "price":
        # 금액은 싣지 않는다 - 상세 화면이 이미 보여 주고, 서식은 화면의 몫이다
        # (`src/lib/format.ts`). 여기서는 사건 상태(유찰 표기)만 옮긴다.
        return s(f.get("status"))
    return None


def _serialize(conn, row) -> dict:
    """응답 한 벌. **모양을 두 곳에서 만들지 않는다** — 시작/조회/저장/완료가 전부 이것을 쓴다.

    (`favorites.py:item_exists()` 주석이 적어 둔 함정을 되풀이하지 않는다 —
     같은 개념의 응답 모양이 두 벌로 갈라지면 한쪽만 고쳐지는 날이 온다.)
    """
    stored = _checks_of(conn, row["id"])
    facts = _review_facts(conn, row["item_id"])
    checks = []
    done = 0
    for key, label in CHECK_ITEMS:
        got = stored.get(key)
        is_checked = bool(got["checked"]) if got else False
        if is_checked:
            done += 1
        checks.append({
            "key": key,
            "label": label,
            "checked": is_checked,
            "note": (got["note"] if got else None),
            # REVIEW 에서 이미 확인된 사실. 현장에서 **대조할 대상**이지 판단이 아니다.
            "known": _known_for(key, facts),
        })
    # ── 이 화면이 **어느 물건인지** (2026-09-05) ────────────────────────
    #
    #   임장 화면은 제목이 "임장 기록" 하나였고, 물건을 가리키는 말이 **한 군데도
    #   없었다.** 현장에서는 하루에 여러 건을 도는데, 그 화면만 보고는 지금 어느
    #   물건에 적고 있는지 알 수 없다. 확인하려면 상세로 나갔다 돌아와야 하고 —
    #   그것이 정확히 이 제품이 줄이겠다고 말한 왕복이다. 더 나쁜 쪽은 조용한
    #   경우다: **엉뚱한 물건에 기록해도 화면이 아무 말을 하지 않는다.**
    #
    #   `_review_facts()` 가 이미 `auction_item` 을 읽고 있으므로 질의는 늘지 않는다.
    #   값이 없으면 None 을 그대로 준다 — "정보 없음" 같은 문구를 지어내지 않는다.
    ident = {
        "case_no": facts.get("case_no"),
        "item_no": facts.get("item_no"),
        "court_name": facts.get("court_name"),
        "full_address": facts.get("full_address"),
    }
    return {
        "item_id": row["item_id"],
        "item": ident,
        "status": row["status"],
        "started_at": row["started_at"],
        "completed_at": row["completed_at"],
        "memo": row["memo"],
        "risk_note": row["risk_note"],
        "decision": row["decision"],
        "decided_at": row["decided_at"],
        "checks": checks,
        # 화면이 진행률을 스스로 세지 않게 서버가 준다 — 같은 계산이 프런트마다
        # 갈라지는 것을 막는다(`api/v1/item.py` 가 `openable` 을 주는 것과 같은 이유).
        "checked_count": done,
        "check_total": len(CHECK_ITEMS),
        # 몇 항목이 REVIEW 데이터로 미리 채워졌는가. 화면이 세지 않게 서버가 준다
        # (`checked_count` 와 같은 이유 - 같은 계산이 화면마다 갈라지지 않게).
        "known_count": sum(1 for c in checks if c["known"]),
    }


class StartRequest(BaseModel):
    item_id: int


@router.post("/field-visits")
def start_visit(req: StartRequest, user_id: str = Depends(get_current_user)):
    """임장 시작. **이미 있으면 그것을 돌려준다**(중복 요청이 오류가 아니다).

    현장에서 버튼을 두 번 누르는 것은 흔하다. 그때 409 를 던지면 사용자는 아무것도
    못 하고, 화면은 "이미 시작했다"를 스스로 처리해야 한다. 같은 결과로 수렴시킨다.
    """
    conn = get_connection()
    try:
        _require_table(conn)
        if not _item_exists(conn, req.item_id):
            raise HTTPException(
                status_code=404,
                detail=error_response(ErrorCode.ITEM_NOT_FOUND, "물건을 찾을 수 없습니다"))
        now = datetime.now().isoformat()
        existing = _visit_row(conn, user_id, req.item_id)
        if existing is None:
            try:
                conn.execute(
                    "INSERT INTO field_visits"
                    " (user_id, item_id, status, started_at, created_at, updated_at)"
                    " VALUES (?,?,?,?,?,?)",
                    (user_id, req.item_id, FIELD_STATUS_IN_PROGRESS, now, now, now))
                conn.commit()
            except sqlite3.IntegrityError:
                # 같은 사용자가 동시에 두 번 눌렀다. UNIQUE 가 막았고, 이긴 쪽의 행을 쓴다.
                conn.rollback()
            existing = _visit_row(conn, user_id, req.item_id)
        return success(_serialize(conn, existing))
    finally:
        conn.close()


@router.get("/field-visits/{item_id}")
def get_visit(item_id: int, user_id: str = Depends(get_current_user)):
    """이 물건의 **내** 임장 기록. 없으면 404 — 화면이 "시작하기"를 그린다."""
    conn = get_connection()
    try:
        _require_valid_id(item_id)
        _require_table(conn)
        row = _visit_row(conn, user_id, item_id)
        if row is None:
            raise HTTPException(
                status_code=404,
                detail=error_response(ErrorCode.FIELD_VISIT_NOT_FOUND,
                                      "임장 기록이 없습니다"))
        return success(_serialize(conn, row))
    finally:
        conn.close()


class CheckRequest(BaseModel):
    check_key: str
    checked: bool
    note: Optional[str] = None


@router.put("/field-visits/{item_id}/checks")
def put_check(item_id: int, req: CheckRequest,
              user_id: str = Depends(get_current_user)):
    """체크 항목 하나를 저장한다. **한 번에 하나**다.

    현장에서 쓰는 화면이라 항목을 누를 때마다 즉시 저장한다 — "저장" 버튼을 따로
    두면 전파가 끊기는 곳에서 사용자가 적은 것이 통째로 사라진다.
    """
    conn = get_connection()
    try:
        _require_valid_id(item_id)
        _require_table(conn)
        if req.check_key not in CHECK_KEYS:
            raise HTTPException(
                status_code=400,
                detail=error_response(ErrorCode.FIELD_INVALID_CHECK_KEY,
                                      "알 수 없는 확인 항목입니다"))
        note = _clip(req.note)
        if note is not None and len(note) > MAX_NOTE_LEN:
            raise HTTPException(
                status_code=400,
                detail=error_response(ErrorCode.FIELD_NOTE_TOO_LONG,
                                      "메모가 너무 깁니다"))
        row = _visit_row(conn, user_id, item_id)
        if row is None:
            raise HTTPException(
                status_code=404,
                detail=error_response(ErrorCode.FIELD_VISIT_NOT_FOUND,
                                      "임장 기록이 없습니다"))
        now = datetime.now().isoformat()
        conn.execute(
            "INSERT INTO field_visit_checks (visit_id, check_key, checked, note, updated_at)"
            " VALUES (?,?,?,?,?)"
            " ON CONFLICT(visit_id, check_key) DO UPDATE SET"
            "   checked=excluded.checked, note=excluded.note, updated_at=excluded.updated_at",
            (row["id"], req.check_key, 1 if req.checked else 0, note, now))
        conn.execute("UPDATE field_visits SET updated_at=? WHERE id=?", (now, row["id"]))
        conn.commit()
        return success(_serialize(conn, _visit_row(conn, user_id, item_id)))
    finally:
        conn.close()


class NotesRequest(BaseModel):
    memo: Optional[str] = None
    risk_note: Optional[str] = None


@router.put("/field-visits/{item_id}/notes")
def put_notes(item_id: int, req: NotesRequest,
              user_id: str = Depends(get_current_user)):
    """현장 메모 / 위험요소.

    ★ 보내지 않은 필드는 **건드리지 않는다.** 화면이 메모만 저장할 때 위험요소가
      지워지면 안 된다 — `migrate_execute` 의 병합 정책("빈 값이 기존 값을 지우지
      않는다")과 같은 판단이다. 지우려면 빈 문자열을 **명시적으로** 보낸다.
    """
    conn = get_connection()
    try:
        _require_valid_id(item_id)
        _require_table(conn)
        row = _visit_row(conn, user_id, item_id)
        if row is None:
            raise HTTPException(
                status_code=404,
                detail=error_response(ErrorCode.FIELD_VISIT_NOT_FOUND,
                                      "임장 기록이 없습니다"))
        for value in (req.memo, req.risk_note):
            if value is not None and len(value) > MAX_NOTE_LEN:
                raise HTTPException(
                    status_code=400,
                    detail=error_response(ErrorCode.FIELD_NOTE_TOO_LONG,
                                          "메모가 너무 깁니다"))
        memo = row["memo"] if req.memo is None else _clip(req.memo)
        risk = row["risk_note"] if req.risk_note is None else _clip(req.risk_note)
        now = datetime.now().isoformat()
        conn.execute(
            "UPDATE field_visits SET memo=?, risk_note=?, updated_at=? WHERE id=?",
            (memo, risk, now, row["id"]))
        conn.commit()
        return success(_serialize(conn, _visit_row(conn, user_id, item_id)))
    finally:
        conn.close()


class CompleteRequest(BaseModel):
    # 임장을 끝내면서 판단까지 함께 남길 수 있다(현장에서 결론이 나는 경우).
    # 안 정했으면 생략한다 — 그때 `decision` 은 NULL 로 남는다.
    decision: Optional[str] = None


@router.post("/field-visits/{item_id}/complete")
def complete_visit(item_id: int, req: CompleteRequest,
                   user_id: str = Depends(get_current_user)):
    """임장 완료. 다시 눌러도 같은 결과다(멱등).

    ★ 체크를 다 하지 않아도 완료할 수 있다. 현장에서 확인 못 하는 항목은 늘 있고
      (문이 닫혀 있다, 임차인이 없다), 그때 완료를 막으면 사용자는 기록 자체를
      포기한다. **덜 확인한 채로 끝난 임장도 사실이므로 그대로 남긴다** —
      `checked_count` 가 그 사실을 응답에 담는다.
    """
    conn = get_connection()
    try:
        _require_valid_id(item_id)
        _require_table(conn)
        if req.decision is not None and req.decision not in DECISIONS:
            raise HTTPException(
                status_code=400,
                detail=error_response(ErrorCode.FIELD_INVALID_DECISION,
                                      "알 수 없는 판단 값입니다"))
        row = _visit_row(conn, user_id, item_id)
        if row is None:
            raise HTTPException(
                status_code=404,
                detail=error_response(ErrorCode.FIELD_VISIT_NOT_FOUND,
                                      "임장 기록이 없습니다"))
        now = datetime.now().isoformat()
        # 이미 완료된 것을 다시 완료해도 `completed_at` 은 **처음 값**을 지킨다 —
        # "언제 다녀왔는가"는 사실이고, 버튼을 두 번 눌렀다고 바뀌지 않는다.
        completed_at = row["completed_at"] or now
        decision = row["decision"] if req.decision is None else req.decision
        decided_at = row["decided_at"]
        if req.decision is not None and req.decision != row["decision"]:
            decided_at = now
        conn.execute(
            "UPDATE field_visits SET status=?, completed_at=?, decision=?, decided_at=?,"
            " updated_at=? WHERE id=?",
            (FIELD_STATUS_DONE, completed_at, decision, decided_at, now, row["id"]))
        conn.commit()
        return success(_serialize(conn, _visit_row(conn, user_id, item_id)))
    finally:
        conn.close()


class DecisionRequest(BaseModel):
    decision: str


@router.put("/field-visits/{item_id}/decision")
def put_decision(item_id: int, req: DecisionRequest,
                 user_id: str = Depends(get_current_user)):
    """입찰 판단만 따로 바꾼다 — 임장을 끝낸 뒤 마음이 바뀌는 것이 정상이다.

    **판단은 사용자가 고른다.** 이 엔드포인트는 고른 값을 적을 뿐 계산하지 않는다
    (`docs/decision-log.md`: 자동 투자판단은 프로젝트 범위 밖).
    """
    conn = get_connection()
    try:
        _require_valid_id(item_id)
        _require_table(conn)
        if req.decision not in DECISIONS:
            raise HTTPException(
                status_code=400,
                detail=error_response(ErrorCode.FIELD_INVALID_DECISION,
                                      "알 수 없는 판단 값입니다"))
        row = _visit_row(conn, user_id, item_id)
        if row is None:
            raise HTTPException(
                status_code=404,
                detail=error_response(ErrorCode.FIELD_VISIT_NOT_FOUND,
                                      "임장 기록이 없습니다"))
        now = datetime.now().isoformat()
        decided_at = row["decided_at"] if req.decision == row["decision"] else now
        conn.execute(
            "UPDATE field_visits SET decision=?, decided_at=?, updated_at=? WHERE id=?",
            (req.decision, decided_at, now, row["id"]))
        conn.commit()
        return success(_serialize(conn, _visit_row(conn, user_id, item_id)))
    finally:
        conn.close()
