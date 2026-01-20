from __future__ import annotations

from typing import Optional
from fastapi import APIRouter, Body, Depends, HTTPException, Query

from app.app.services import RagBackend, get_rag_service
from app.app.domain.models.query_model import QueryRequest, RAGQueryResponse

router = APIRouter(prefix="/rag/v2", tags=["rag"])


@router.post("/ask", response_model=RAGQueryResponse)
async def rag_v2_ask(
    req: QueryRequest = Body(...),
    k: int = Query(6, ge=1, le=50),
    candidate_k: Optional[int] = Query(None, ge=1, le=200),
    use_mmr: bool = Query(True),
    lam: float = Query(0.5, ge=0.0, le=1.0),
    max_tokens: int = Query(512, ge=1, le=4096),
    temperature: float = Query(0.2, ge=0.0, le=2.0),
    preview_chars: int = Query(600, ge=0, le=8000),
    section: Optional[str] = Query(None),
    rag: RagBackend = Depends(get_rag_service),
):
    try:
        where = {"section": section} if section else None
        return await rag.ask(
            q=req.question,
            k=k,
            where=where,
            candidate_k=candidate_k,
            use_mmr=use_mmr,
            lam=lam,
            max_tokens=max_tokens,
            temperature=temperature,
            preview_chars=preview_chars,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except TimeoutError:
        raise HTTPException(status_code=504, detail="RAG inference timeout")
    except Exception:
        raise HTTPException(status_code=502, detail="RAG inference failed")
