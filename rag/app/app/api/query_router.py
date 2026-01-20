# app/app/api/query_router.py
from fastapi import APIRouter, Depends, Query
from ..domain.models.query_model import QueryRequest, QueryResponse, RAGQueryResponse
from ..services import RagBackend, get_rag_service

router = APIRouter(prefix="/rag", tags=["rag"])

def _where_from(section: str | None):
    return {"section": section} if section else None

@router.post("/query", response_model=QueryResponse)
async def rag_query(
    req: QueryRequest,
    top_k: int = Query(6, ge=1, le=50),
    section: str | None = Query(None),
    rag: RagBackend = Depends(get_rag_service),
):
    parsed_q = await rag.parse_query(req.question)
    docs = rag.retrieve_docs(
        parsed_q,
        k=top_k,
        where=_where_from(section),
        use_mmr=False,   # 동선 확인용이면 우선 끔
    )
    if not docs:
        return QueryResponse(question=req.question, answer="관련 문서를 찾지 못했어요.")
    return QueryResponse(question=req.question, answer=f"(임시) {len(docs)}건 컨텍스트 확보")

@router.post("/query/debug", response_model=RAGQueryResponse)
async def rag_query_debug(
    req: QueryRequest,
    top_k: int = Query(6, ge=1, le=50),
    section: str | None = Query(None),
    rag: RagBackend = Depends(get_rag_service),
):
    # 실제 RAG 호출 (LLM까지)
    return await rag.ask(
        q=req.question,
        k=top_k,
        where=_where_from(section),
        use_mmr=True,
        lam=0.5,
        max_tokens=512,
        temperature=0.2,
    )
