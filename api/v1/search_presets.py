from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from datetime import datetime
from storage.database import get_connection
from api.auth import get_current_user, success, fail

router = APIRouter()

class SearchPresetRequest(BaseModel):
    name: str
    conditions: dict

@router.post("/search-presets")
def create_preset(req: SearchPresetRequest, user_id: str = Depends(get_current_user)):
    import json
    conn = get_connection()
    try:
        now = datetime.now().isoformat()
        cur = conn.execute(
            "INSERT INTO search_presets (user_id, name, conditions, created_at) VALUES (?,?,?,?)",
            (user_id, req.name, json.dumps(req.conditions, ensure_ascii=False), now)
        )
        conn.commit()
        return success({"id": cur.lastrowid, "name": req.name, "created_at": now})
    finally:
        conn.close()

@router.get("/search-presets")
def get_presets(user_id: str = Depends(get_current_user)):
    import json
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM search_presets WHERE user_id=? ORDER BY created_at DESC",
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
            return fail("검색조건을 찾을 수 없습니다")
        return success({"id": preset_id})
    finally:
        conn.close()
