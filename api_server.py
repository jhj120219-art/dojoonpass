import sys, os, logging
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

# 로깅 설정. 크롤러 계열(mvp_scraper.py / doc_worker.py / migrate_execute.py)은 전부
# basicConfig를 직접 호출하는데 API 서버만 빠져 있었다 — 그 결과 root logger에 핸들러가
# 없고 기본 레벨이 WARNING이라, api/v1/*의 logger.info(예: Admin 상태 전이 감사 로그)가
# 통째로 버려지고 warning조차 timestamp/모듈명 없이 lastResort로만 찍혔다.
# 같은 포맷("%(asctime)s [%(levelname)s] ...")으로 맞추되, API 쪽은 어느 모듈이 남긴
# 로그인지가 중요하므로 %(name)s를 함께 넣는다. 레벨은 LOG_LEVEL로 조절 가능(기본 INFO).
logging.basicConfig(
    level=getattr(logging, os.getenv("LOG_LEVEL", "INFO").strip().upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler()],
)
# 서드파티 라이브러리의 INFO 로그(요청 1건마다 한 줄)가 우리 로그를 덮지 않도록 낮춘다.
for _noisy in ("httpx", "httpcore", "urllib3"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)

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

# 허용 Origin. 미설정이면 기존과 동일하게 "*"(전체 허용)로 동작한다 — 하위호환 유지.
# 운영 배포 시 .env에 CORS_ALLOW_ORIGINS=https://<프론트 도메인> 형태로(콤마 구분 다중 가능)
# 지정하면 그 목록만 허용한다. 인증은 쿠키가 아니라 Authorization 헤더(Bearer)라 CSRF
# 위험은 없지만, 운영에서 굳이 전 도메인에 API를 열어둘 이유도 없다.
_cors_origins_env = os.getenv("CORS_ALLOW_ORIGINS", "").strip()
CORS_ALLOW_ORIGINS = (
    [o.strip() for o in _cors_origins_env.split(",") if o.strip()] if _cors_origins_env else ["*"]
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ALLOW_ORIGINS,
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
