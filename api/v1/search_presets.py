import json
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from datetime import datetime
from storage.database import get_connection
from api.auth import get_current_user, success, error_response
from api.constants import ErrorCode

router = APIRouter()

# 서버측 입력 한도. 프론트(SearchPresets.tsx)는 이름에 maxLength=50을 걸고 조건도 URL
# 파라미터에서만 뽑아 보내지만, API를 직접 호출하면 아무 제한이 없어 임의 크기의 문자열이
# 그대로 저장된다. 정상 사용을 절대 막지 않을 만큼 넉넉하게 잡되 상한은 둔다.
MAX_PRESET_NAME_LENGTH = 100
MAX_PRESET_CONDITIONS_LENGTH = 4000
MAX_PRESETS_PER_USER = 100


class SearchPresetRequest(BaseModel):
    name: str
    conditions: dict

@router.post("/search-presets")
def create_preset(req: SearchPresetRequest, user_id: str = Depends(get_current_user)):
    name = req.name.strip()
    if not name:
        return error_response(ErrorCode.SEARCH_PRESET_NAME_REQUIRED, "검색조건 이름을 입력해주세요")
    if len(name) > MAX_PRESET_NAME_LENGTH:
        return error_response(ErrorCode.SEARCH_PRESET_NAME_TOO_LONG, f"검색조건 이름이 너무 깁니다 (최대 {MAX_PRESET_NAME_LENGTH}자)")
    conditions_json = json.dumps(req.conditions, ensure_ascii=False)
    if len(conditions_json) > MAX_PRESET_CONDITIONS_LENGTH:
        return error_response(ErrorCode.SEARCH_PRESET_TOO_LARGE, "검색조건이 너무 큽니다")

    conn = get_connection()
    # 저장 개수 상한은 COUNT(집계)로 판정하므로 "row 하나를 조건부로 잠그는" 방식으로는
    # 막을 수 없다. COUNT 확인과 INSERT 사이에 다른 요청이 끼어들면 둘 다 통과해 상한을
    # 넘긴다 — 2026-08-12 Sprint 67에 실제로 재현했다(99개 상태에서 12개 동시 요청 ->
    # 2건 성공 -> 최종 101개). `api/v1/registry.py:create_registry_request()`가 무료횟수
    # COUNT에 쓰는 것과 **같은 패턴**으로, BEGIN IMMEDIATE로 확인+삽입을 원자화한다.
    conn.isolation_level = None
    try:
        conn.execute("BEGIN IMMEDIATE")
        try:
            saved_count = conn.execute(
                "SELECT COUNT(*) FROM search_presets WHERE user_id=?", (user_id,)
            ).fetchone()[0]
            if saved_count >= MAX_PRESETS_PER_USER:
                conn.execute("ROLLBACK")
                return error_response(ErrorCode.SEARCH_PRESET_LIMIT_EXCEEDED, f"저장 가능한 검색조건은 최대 {MAX_PRESETS_PER_USER}개입니다")

            now = datetime.now().isoformat()
            cur = conn.execute(
                "INSERT INTO search_presets (user_id, name, conditions, created_at) VALUES (?,?,?,?)",
                (user_id, name, conditions_json, now)
            )
            preset_id = cur.lastrowid
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        return success({"id": preset_id, "name": name, "created_at": now})
    finally:
        conn.close()

@router.get("/search-presets")
def get_presets(user_id: str = Depends(get_current_user)):
    conn = get_connection()
    try:
        rows = conn.execute(
            # created_at 동률 시 순서가 흔들리지 않도록 id로 tie-break한다(전 도메인 공통 규칙).
            "SELECT * FROM search_presets WHERE user_id=? ORDER BY created_at DESC, id DESC",
            (user_id,)
        ).fetchall()
        items = []
        for row in rows:
            items.append({
                "id": row["id"],
                "name": row["name"],
                "conditions": json.loads(row["conditions"]),
                "created_at": row["created_at"],
            })
        return success(items)
    finally:
        conn.close()

@router.delete("/search-presets/{preset_id}")
def delete_preset(preset_id: int, user_id: str = Depends(get_current_user)):
    conn = get_connection()
    try:
        result = conn.execute(
            "DELETE FROM search_presets WHERE id=? AND user_id=?",
            (preset_id, user_id)
        )
        conn.commit()
        if result.rowcount == 0:
            return error_response(ErrorCode.SEARCH_PRESET_NOT_FOUND, "검색조건을 찾을 수 없습니다")
        return success({"id": preset_id})
    finally:
        conn.close()
