"""마이리스트 가져오기 / 관심물건 메모·태그 — 2026-08-28 신설.

## 무엇을 만들었나

`docs/SPRINT227_MYLIST_EXPORT.md` 가 만든 **내보내기**의 짝인 **가져오기**다.

    [경쟁사 마이페이지에서 사람이 복사]
        -> POST /api/v1/favorites/import/preview   (읽기 전용. 파싱 + 매칭)
        -> 화면에서 사용자가 확인/후보 선택
        -> POST /api/v1/favorites/import/commit    (확정된 item_id 만 저장)
        -> GET  /api/v1/favorites                  (메모/태그가 함께 나온다)

## 하지 않는 것 (명시)

  * **외부 상용 서비스에 요청하지 않는다.** 이 모듈에는 HTTP 클라이언트가 없다.
    입력은 오직 사용자가 붙여넣은 문자열이다.
  * **추측으로 물건을 고르지 않는다.** 후보가 둘 이상이면 `AMBIGUOUS` 로 돌려주고,
    커밋은 **사용자가 확정한 `item_id`** 만 받는다. 커밋 API 는 텍스트를 다시 파싱하지
    않는다 -- 미리보기와 커밋이 각자 파싱하면 두 결과가 갈릴 수 있다.
  * **못 찾은 줄을 버리지 않는다.** 원문(`raw`)과 사유를 그대로 돌려준다.

## 멱등성 -- 같은 텍스트를 두 번 가져와도 안전하다

  * `favorites` 는 `UNIQUE(user_id, item_id)` 라 두 번째 삽입이 `ALREADY_FAVORITED` 다.
  * `favorite_notes` 는 `UNIQUE(user_id, item_id)` 위에 UPSERT 한다. **빈 값으로
    기존 메모를 지우지 않는다** -- 재실행이 사용자가 나중에 쓴 메모를 날리면 안 된다.

## `favorite_notes` 가 아직 없는 환경 (중요)

migration 026 은 **운영 적용이 승인 영역**이다. 그래서 이 코드는 테이블이 없어도
죽지 않는다 -- 관심물건 담기는 그대로 되고 메모/태그만 조용히 빠지되, **조용히**
빠졌다는 사실을 응답의 `notes_enabled: false` 와 로그로 알린다.
(값 없이 성공했다고 말하는 것이 이 저장소가 반복해 경계해 온 실패 모양이다.)
"""
import logging
import sqlite3
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from storage.database import get_connection, chunked_for_sql
from api.auth import get_current_user, success, error_response
from api.constants import ErrorCode, is_sqlite_int
from normalizer.mylist_import import (
    MAX_LINES, MAX_MEMO_LENGTH, MAX_SOURCE_LENGTH,
    STATUS_ALREADY, STATUS_AMBIGUOUS, STATUS_DUPLICATE_INPUT,
    STATUS_MATCHED, STATUS_NOT_FOUND,
    case_no_parts, dedupe_key, normalize_tags, parse_mylist_text, resolve_row,
)

logger = logging.getLogger(__name__)
router = APIRouter()

# `IN (...)` 나누기는 `storage.database.chunked_for_sql()` 한 곳이 정한다 -- 여기서
# 자체 상수를 두면 SQLite 변수 상한이 달라졌을 때 이 파일만 뒤처진다(BUGS #243).

# 커밋 1회 상한. 미리보기 상한(MAX_LINES)과 같아야 한다 -- 미리보기에서 본 것을
# 그대로 커밋하지 못하면 사용자는 무엇이 빠졌는지 알 수 없다.
MAX_COMMIT_ROWS = MAX_LINES

# 응답에 싣는 후보 상한. 사건번호 하나에 물건이 수십 개인 경우가 있어 상한을 둔다.
MAX_CANDIDATES_PER_ROW = 20

_ITEM_COLUMNS = """
    id, case_no, item_no, court_name, property_type,
    sido, sigungu, full_address, appraisal_price, minimum_bid_price,
    bid_rate, auction_date, status, fail_count
"""


class ImportPreviewRequest(BaseModel):
    text: str
    # 사용자가 적어 주는 출처 라벨(자유 입력). 우리가 서비스명을 목록으로 제공하지 않는다 --
    # 제공하면 그 목록 자체가 "우리가 그 서비스와 연동한다"는 잘못된 신호가 된다.
    source: Optional[str] = None


class ImportCommitRow(BaseModel):
    item_id: int
    memo: Optional[str] = None
    tags: Optional[List[str]] = None
    source: Optional[str] = None


class ImportCommitRequest(BaseModel):
    rows: List[ImportCommitRow]


class NoteRequest(BaseModel):
    memo: Optional[str] = None
    tags: Optional[List[str]] = None
    source: Optional[str] = None


def notes_table_exists(conn) -> bool:
    """migration 026 이 적용됐는가. 없으면 메모/태그 없이 동작한다(위 모듈 주석 참고)."""
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='favorite_notes'"
    ).fetchone()
    return row is not None


def fetch_candidates(conn, parts: List[str]) -> List[dict]:
    """사건번호 구성요소들로 후보 물건을 모은다.

    두 갈래로 찾는다. **왜 두 갈래인가** -- 저장된 `case_no` 가 단일일 수도, 병합
    (`"A / B"`)일 수도 있기 때문이다.

        (1) 정확 일치   `case_no IN (...)`     DB 가 단일로 갖고 있는 경우. 인덱스를 탄다.
        (2) 부분 일치   `case_no LIKE '%A%'`   DB 가 병합으로 갖고 있는 경우.
                        (1) 에서 못 찾은 구성요소에만 돈다.

    (2) 는 선행 와일드카드라 인덱스를 못 타고 전수 훑기다. 그래서 **(1) 이 실패한
    것에만** 돌린다. 비용을 정직하게 적어 둔다: 최악의 경우(붙여넣은 사건번호가 전부
    DB 에 없음) 조각 수만큼 전수 훑기가 난다 -- 입력이 500줄로 제한되므로 상한이
    있는 비용이고, 사용자가 직접 누른 1회성 작업이다.

    나누기는 `chunked_for_sql()` 이 한다. 직접 세면 SQLite 변수 상한을 넘겨
    "too many SQL variables" 로 **가져오기 전체**가 죽는다(BUGS #243 이 실측한
    실패 모양이다 - 느려지는 것이 아니라 실행이 멈춘다).

    (2) 가 접두 오검출(`2024타경1009` 가 `2024타경100920` 에 걸림)을 낼 수 있지만
    **판정은 하지 않는다** -- 여기는 후보를 모으는 자리이고, 같은 물건인지는
    `resolve_row()` 가 구성요소 **정확 일치**로 다시 본다.
    """
    if not parts:
        return []

    found: dict = {}
    matched_parts = set()

    for chunk in chunked_for_sql(parts, vars_per_item=1, conn=conn):
        placeholders = ",".join("?" * len(chunk))
        rows = conn.execute(
            "SELECT %s FROM auction_item WHERE case_no IN (%s)" % (_ITEM_COLUMNS, placeholders),
            tuple(chunk),
        ).fetchall()
        for row in rows:
            found[row["id"]] = dict(row)
            matched_parts |= case_no_parts(row["case_no"])

    remaining = [p for p in parts if p not in matched_parts]
    for chunk in chunked_for_sql(remaining, vars_per_item=1, conn=conn):
        where = " OR ".join(["case_no LIKE ?"] * len(chunk))
        rows = conn.execute(
            "SELECT %s FROM auction_item WHERE %s" % (_ITEM_COLUMNS, where),
            tuple("%" + p + "%" for p in chunk),
        ).fetchall()
        for row in rows:
            found[row["id"]] = dict(row)

    return list(found.values())


def _candidate_view(item: dict) -> dict:
    """후보를 화면이 고를 수 있을 만큼만 보여 준다. 값은 **가공하지 않는다**
    (`src/lib/exportList.ts` 가 축약을 금지한 것과 같은 이유 -- 화면이 정한다)."""
    return {
        "id": item["id"],
        "case_no": item["case_no"],
        "item_no": item["item_no"],
        "court_name": item["court_name"],
        "property_type": item["property_type"],
        "full_address": item["full_address"],
        "appraisal_price": item["appraisal_price"],
        "minimum_bid_price": item["minimum_bid_price"],
        "auction_date": item["auction_date"],
        "status": item["status"],
    }


@router.post("/favorites/import/preview")
def preview_import(req: ImportPreviewRequest, user_id: str = Depends(get_current_user)):
    """붙여넣은 텍스트를 파싱해 우리 물건과 맞춰 본다. **아무것도 저장하지 않는다.**"""
    parsed = parse_mylist_text(req.text)
    rows = parsed["rows"]
    source = (req.source or "").strip()[:MAX_SOURCE_LENGTH]

    if not rows:
        return success({
            "rows": [],
            "summary": _summarize([]),
            "truncated": parsed["truncated"],
            "header_detected": parsed["header_detected"],
            "notes_enabled": True,
            "source": source,
        }, message="가져올 내용을 찾지 못했습니다")

    all_parts: List[str] = []
    seen_parts = set()
    for row in rows:
        for part in sorted(case_no_parts(row.get("case_no"))):
            if part not in seen_parts:
                seen_parts.add(part)
                all_parts.append(part)

    conn = get_connection()
    try:
        candidates = fetch_candidates(conn, all_parts)
        by_id = {c["id"]: c for c in candidates}

        # 이미 담긴 관심물건. 한 번의 쿼리로 읽고 파이썬에서 대조한다 -- 행마다 물으면
        # 곧바로 N+1 이고(favorites.py 가 같은 이유로 JOIN 으로 바꿨다) 결과는 같다.
        favorited = {
            r["item_id"] for r in conn.execute(
                "SELECT item_id FROM favorites WHERE user_id = ?", (user_id,)
            ).fetchall()
        }
        notes_enabled = notes_table_exists(conn)
    finally:
        conn.close()

    seen_keys = set()
    out = []
    for row in rows:
        key = dedupe_key(row)
        if key is not None and key in seen_keys:
            # 붙여넣기 안의 중복. **버리지 않고** 사유와 함께 보여 준다.
            out.append(_row_view(row, STATUS_DUPLICATE_INPUT, None, [], [], source))
            continue
        if key is not None:
            seen_keys.add(key)

        resolved = resolve_row(row, candidates)
        status = resolved["status"]
        item_id = resolved["item_id"]
        if status == STATUS_MATCHED and item_id in favorited:
            status = STATUS_ALREADY

        cand_views = [
            _candidate_view(by_id[cid])
            for cid in resolved["candidate_ids"][:MAX_CANDIDATES_PER_ROW]
            if cid in by_id
        ]
        out.append(_row_view(row, status, item_id, cand_views,
                             resolved["narrowed_by"], source))

    return success({
        "rows": out,
        "summary": _summarize(out),
        "truncated": parsed["truncated"],
        "header_detected": parsed["header_detected"],
        "notes_enabled": notes_enabled,
        "source": source,
    })


def _row_view(parsed: dict, status: str, item_id, candidates, narrowed_by, source) -> dict:
    return {
        "line_no": parsed.get("line_no"),
        "raw": parsed.get("raw"),
        "case_no": parsed.get("case_no"),
        "item_no": parsed.get("item_no"),
        "court_name": parsed.get("court_name"),
        "address": parsed.get("address"),
        "memo": parsed.get("memo") or "",
        "tags": parsed.get("tags") or [],
        "source": source,
        "status": status,
        "item_id": item_id,
        "candidates": candidates,
        "narrowed_by": narrowed_by,
    }


def _summarize(rows) -> dict:
    """상태별 개수. **0인 상태도 키를 남긴다** -- 화면이 `?? 0` 으로 감추면
    "0건"과 "그 상태가 아예 없음"이 같아 보인다."""
    from normalizer.mylist_import import ALL_STATUSES
    counts = {s: 0 for s in ALL_STATUSES}
    for row in rows:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    counts["total"] = len(rows)
    # 바로 담을 수 있는 것 = 특정됐고 아직 안 담긴 것.
    counts["importable"] = counts.get(STATUS_MATCHED, 0)
    return counts


@router.post("/favorites/import/commit")
def commit_import(req: ImportCommitRequest, user_id: str = Depends(get_current_user)):
    """미리보기에서 **사용자가 확정한** 행만 저장한다.

    ★ 행마다 독립적으로 커밋한다(부분 성공). 하나를 통째 트랜잭션으로 묶으면 한 줄의
      문제가 나머지 499줄을 되돌린다 -- 가져오기는 "가능한 만큼 들어가고 나머지를
      알려주는" 것이 맞다. 대신 **무엇이 왜 안 들어갔는지 행별로 돌려준다.**
    """
    if not req.rows:
        return error_response(ErrorCode.FAVORITE_IMPORT_EMPTY, "가져올 항목이 없습니다")
    if len(req.rows) > MAX_COMMIT_ROWS:
        return error_response(
            ErrorCode.FAVORITE_IMPORT_TOO_LARGE,
            "한 번에 가져올 수 있는 항목은 최대 %d개입니다" % MAX_COMMIT_ROWS)

    now = datetime.now().isoformat()
    conn = get_connection()
    try:
        notes_enabled = notes_table_exists(conn)
        results = []
        added = already = failed = 0
        # 같은 item_id 가 요청 안에 두 번 오면 두 번째는 `ALREADY` 가 된다 --
        # UNIQUE 제약이 그렇게 만들어 주므로 여기서 따로 걸러내지 않는다.
        for row in req.rows:
            outcome = _commit_one(conn, user_id, row, now, notes_enabled)
            results.append(outcome)
            if outcome["status"] == "ADDED":
                added += 1
            elif outcome["status"] == STATUS_ALREADY:
                already += 1
            else:
                failed += 1

        return success({
            "results": results,
            "summary": {"added": added, "already": already,
                        "failed": failed, "total": len(results)},
            "notes_enabled": notes_enabled,
        })
    finally:
        conn.close()


def _commit_one(conn, user_id: str, row: ImportCommitRow, now: str,
                notes_enabled: bool) -> dict:
    item_id = row.item_id
    # SQLite INTEGER 범위 밖 id 는 어떤 행도 될 수 없다. 그대로 넘기면 OverflowError ->
    # 500 이고, 로그인한 사용자가 그 500 을 만들 수 있다(favorites.py 가 같은 방어를 한다).
    if not is_sqlite_int(item_id):
        return {"item_id": item_id, "status": STATUS_NOT_FOUND,
                "reason": "물건을 찾을 수 없습니다"}

    exists = conn.execute(
        "SELECT 1 FROM auction_item WHERE id = ?", (item_id,)).fetchone()
    if not exists:
        return {"item_id": item_id, "status": STATUS_NOT_FOUND,
                "reason": "물건을 찾을 수 없습니다"}

    status = "ADDED"
    try:
        conn.execute(
            "INSERT INTO favorites (user_id, item_id, created_at) VALUES (?,?,?)",
            (user_id, item_id, now))
        conn.commit()
    except sqlite3.IntegrityError:
        # UNIQUE(user_id,item_id) 위반 = 이미 담겨 있다. 실패가 아니라 **멱등**이다.
        # 다른 무결성 오류(FK 등)까지 여기로 뭉뚱그리지 않도록, 위에서 물건 존재를
        # 먼저 확인해 두었다.
        conn.rollback()
        status = STATUS_ALREADY
    except Exception:
        conn.rollback()
        logger.exception("관심물건 저장 실패 (user_id=%s, item_id=%s)", user_id, item_id)
        return {"item_id": item_id, "status": "FAILED", "reason": "저장하지 못했습니다"}

    note_written = False
    if notes_enabled:
        try:
            note_written = _upsert_note(conn, user_id, item_id, row.memo,
                                        row.tags, row.source, now)
        except Exception:
            conn.rollback()
            # 메모 실패가 담기 자체를 되돌리지는 않는다. 그러나 **성공했다고 말하지도
            # 않는다** -- 행 결과에 `note_written: false` 로 남긴다.
            logger.exception("관심물건 메모 저장 실패 (user_id=%s, item_id=%s)",
                             user_id, item_id)

    return {"item_id": item_id, "status": status, "reason": None,
            "note_written": note_written}


def _upsert_note(conn, user_id: str, item_id: int, memo, tags, source, now: str) -> bool:
    """메모/태그/출처를 UPSERT 한다. **빈 값으로 기존 값을 지우지 않는다.**

    같은 텍스트를 두 번 가져오는 것은 정상 사용이고(사용자가 목록을 갱신한다),
    그때 두 번째 가져오기에 메모 칸이 비어 있다고 해서 사용자가 그동안 써 둔 메모를
    날리면 안 된다. 지우는 것은 **명시적인 메모 편집(PUT)** 의 일이다.
    """
    memo_value = (memo or "").strip()[:MAX_MEMO_LENGTH]
    tags_value = normalize_tags(tags)
    source_value = (source or "").strip()[:MAX_SOURCE_LENGTH]
    if not (memo_value or tags_value or source_value):
        return False

    conn.execute(
        """
        INSERT INTO favorite_notes
            (user_id, item_id, memo, tags, source, created_at, updated_at)
        VALUES (?,?,?,?,?,?,?)
        ON CONFLICT(user_id, item_id) DO UPDATE SET
            memo    = COALESCE(NULLIF(excluded.memo, ''),    favorite_notes.memo),
            tags    = COALESCE(NULLIF(excluded.tags, ''),    favorite_notes.tags),
            source  = COALESCE(NULLIF(excluded.source, ''),  favorite_notes.source),
            updated_at = excluded.updated_at
        """,
        (user_id, item_id, memo_value, tags_value, source_value, now, now))
    conn.commit()
    return True


@router.put("/favorites/{item_id}/note")
def put_note(item_id: int, req: NoteRequest, user_id: str = Depends(get_current_user)):
    """메모/태그/출처를 **통째로 교체**한다. 빈 값을 보내면 지운다.

    가져오기의 UPSERT 와 규칙이 다른 것은 의도다 -- 저쪽은 재실행 안전(멱등)이 목적이고,
    이쪽은 사용자가 "지우겠다"고 누른 결과다. 두 규칙을 한 함수에 섞으면 어느 쪽도
    정확하지 않게 된다.
    """
    if not is_sqlite_int(item_id):
        return error_response(ErrorCode.ITEM_NOT_FOUND, "물건을 찾을 수 없습니다")

    memo = (req.memo or "").strip()[:MAX_MEMO_LENGTH]
    tags = normalize_tags(req.tags)
    source = (req.source or "").strip()[:MAX_SOURCE_LENGTH]

    conn = get_connection()
    try:
        if not notes_table_exists(conn):
            # 조용히 성공하지 않는다. 화면이 "저장됨"을 띄우면 사용자는 메모가
            # 남았다고 믿는다 -- 남지 않는다.
            return error_response(ErrorCode.FAVORITE_NOTE_UNAVAILABLE,
                                  "메모 기능이 아직 준비되지 않았습니다")
        # **내 관심물건에만** 쓸 수 있다. `auction_item` 존재만 보면 담지도 않은 물건에
        # 메모가 쌓이고, 그 메모는 어느 화면에도 나오지 않는다(도달 불가 데이터).
        mine = conn.execute(
            "SELECT 1 FROM favorites WHERE user_id=? AND item_id=?",
            (user_id, item_id)).fetchone()
        if not mine:
            return error_response(ErrorCode.FAVORITE_NOT_FOUND, "등록된 관심물건이 없습니다")

        now = datetime.now().isoformat()
        conn.execute(
            """
            INSERT INTO favorite_notes
                (user_id, item_id, memo, tags, source, created_at, updated_at)
            VALUES (?,?,?,?,?,?,?)
            ON CONFLICT(user_id, item_id) DO UPDATE SET
                memo = excluded.memo,
                tags = excluded.tags,
                source = excluded.source,
                updated_at = excluded.updated_at
            """,
            (user_id, item_id, memo, tags, source, now, now))
        conn.commit()
        return success({"item_id": item_id, "memo": memo, "tags": tags,
                        "source": source, "updated_at": now})
    finally:
        conn.close()
