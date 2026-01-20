# app/app/main.py
from __future__ import annotations
import os
from pathlib import Path

from dotenv import load_dotenv

# 1) .env 로딩: 루트/ configure/.env 모두 시도
ROOT = Path(__file__).resolve().parents[2]  # 프로젝트 루트
for p in (ROOT / ".env", ROOT / "configure" / ".env"):
    if p.exists():
        load_dotenv(dotenv_path=p, override=False)

# 2) config import (부작용으로 configure/.env도 로딩됨)
from .configure import config

from fastapi import FastAPI
from .security.auth_middleware import AuthOnlyMiddleware
from .api import (
    admin_ingest_router,
    chroma_rag_router,
    debug_router,
    faiss_rag_router,
    query_router,
    search_router,
)

app = FastAPI()

# 3) Base64 플래그 보정: config.JWT_SECRET이 Base64라면 이게 반드시 1이어야 함
os.environ.setdefault("JWT_SECRET_B64", "1")

# 4) 미들웨어는 **한 번만** 추가 + 시크릿 직접 주입
app.add_middleware(
    AuthOnlyMiddleware,
    secret=config.JWT_SECRET,
    protected_prefixes=("/rag", "/search", "/admin", "/api"),
    public_paths=("/health", "/docs", "/openapi.json", "/redoc"),
)

# 라우터
app.include_router(query_router.router)
app.include_router(search_router.router)
app.include_router(debug_router.router)
app.include_router(admin_ingest_router.router)
app.include_router(chroma_rag_router.router)
app.include_router(faiss_rag_router.router)

@app.get("/health")
def health():
    return {"ok": True}
