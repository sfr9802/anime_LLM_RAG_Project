from fastapi import FastAPI
from .security.auth_middleware import AuthOnlyMiddleware
from .api import query_router, search_router, debug_router, admin_ingest_router, rag_router

app = FastAPI()

# 🔒 전역 인증(검증만)
app.add_middleware(
    AuthOnlyMiddleware,
    # secret 미지정 시 JWT_SECRET 환경변수 사용
    protected_prefixes=("/rag", "/search", "/admin", "/api"),
    public_paths=("/health", "/docs", "/openapi.json", "/redoc"),
)

# 라우터 등록(개별 라우터는 건드릴 필요 없음)
app.include_router(query_router.router)
app.include_router(search_router.router)
app.include_router(debug_router.router)
app.include_router(admin_ingest_router.router)
app.include_router(rag_router.router)

@app.get("/health")
def health():
    return {"ok": True}
