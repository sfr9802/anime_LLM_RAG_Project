# app/app/api/rag_router.py
from __future__ import annotations
from typing import Optional
from fastapi import APIRouter, Body, Depends, HTTPException, Query
from app.app.services.chroma_rag import RagService
from app.app.domain.models.query_model import QueryRequest, RAGQueryResponse  # ← 네 모델 사용

router = APIRouter(prefix="/rag", tags=["rag"])
_rag = RagService()
def get_rag() -> RagService: return _rag

@router.post("/ask", response_model=RAGQueryResponse)
async def rag_ask(
    req: QueryRequest = Body(...),
    k: int = Query(6, ge=1, le=50),
    candidate_k: Optional[int] = Query(None, ge=1, le=200),
    use_mmr: bool = Query(True),
    lam: float = Query(0.5, ge=0.0, le=1.0),
    max_tokens: int = Query(512, ge=1, le=4096),
    temperature: float = Query(0.2, ge=0.0, le=2.0),
    preview_chars: int = Query(600, ge=0, le=8000),
    rag: RagService = Depends(get_rag),
):
    try:
        # 기존 ask는 dict를 반환하니, 위에서 model_dump() 되어 나옴
        return await rag.ask(
            q=req.question,
            k=k, candidate_k=candidate_k, use_mmr=use_mmr, lam=lam,
            where=None,  # 필요 시 쿼리파라미터로 추가
            max_tokens=max_tokens, temperature=temperature, preview_chars=preview_chars,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"RAG inference failed: {e}")

@router.get("/healthz")
async def rag_health():
    return {"ok": True}
