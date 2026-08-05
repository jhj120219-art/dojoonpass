import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from api.v1.search import router as search_router
from api.v1.item import router as item_router
from api.v1.doc_stats import router as doc_stats_router
from api.v1.favorites import router as favorites_router
from api.v1.recent_items import router as recent_router
from api.v1.search_presets import router as presets_router
from api.v1.registry import router as registry_router
from api.v1.documents import router as documents_router
from api.v1.payments import router as payments_router
from api.v1.admin import router as admin_router

app = FastAPI(
    title="도준패스 법원경매 API",
    description="전국 법원경매 데이터 검색 및 권리분석 API",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    # Content-Disposition은 브라우저 CORS 기본 안전 헤더 목록에 없어 명시적으로 노출해야
    # 프론트(registry-requests/{id}/download)가 응답의 파일명을 읽을 수 있다.
    expose_headers=["Content-Disposition"],
)

app.include_router(search_router, prefix="/api/v1", tags=["search"])
app.include_router(item_router, prefix="/api/v1", tags=["item"])
app.include_router(doc_stats_router, prefix="/api/v1", tags=["document"])
app.include_router(favorites_router, prefix="/api/v1", tags=["favorites"])
app.include_router(recent_router, prefix="/api/v1", tags=["recent"])
app.include_router(presets_router, prefix="/api/v1", tags=["presets"])
app.include_router(registry_router, prefix="/api/v1", tags=["registry"])
app.include_router(documents_router, prefix="/api/v1", tags=["documents"])
app.include_router(payments_router, prefix="/api/v1", tags=["payments"])
app.include_router(admin_router, prefix="/api/v1", tags=["admin"])

@app.get("/")
def root():
    return {"success": True, "data": {"status": "ok", "version": "1.0.0"}, "message": None}

@app.get("/api/v1/stats")
def stats():
    from storage.database import get_connection
    conn = get_connection()
    try:
        total = conn.execute("SELECT COUNT(*) FROM auction_item").fetchone()[0]
        by_sido = conn.execute(
            "SELECT sido, COUNT(*) as cnt FROM auction_item GROUP BY sido ORDER BY cnt DESC"
        ).fetchall()
        by_date = conn.execute(
            "SELECT auction_date, COUNT(*) as cnt FROM auction_item "
            "GROUP BY auction_date ORDER BY auction_date DESC LIMIT 7"
        ).fetchall()
        return {
            "success": True,
            "data": {
                "total": total,
                "by_sido": [dict(r) for r in by_sido],
                "by_date": [dict(r) for r in by_date],
            },
            "message": None
        }
    finally:
        conn.close()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api_server:app", host="127.0.0.1", port=8000, reload=True)
