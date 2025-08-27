# router/query_router.py
from fastapi import APIRouter, Query
from ..domain.models.query_model import QueryRequest, QueryResponse, RAGQueryResponse
from ..services.search_service import SearchService
from ..services.rag_service import RagService

router = APIRouter(prefix="/rag", tags=["rag"])

# 의존성 간단 주입
_search = SearchService(top_k=6)
_rag = RagService(_search)

@router.post("/query", response_model=QueryResponse)
def rag_query(req: QueryRequest, top_k: int = Query(6), section: str | None = Query(None)):
    docs = _rag.retrieve_docs(req.question, section=section, top_k=top_k)
    if not docs:
        return QueryResponse(question=req.question, answer="관련 문서를 찾지 못했어요.")
    # 임시 답변 (LLM 전)
    return QueryResponse(question=req.question, answer=f"(임시) {len(docs)}건 컨텍스트 확보")

@router.post("/query/debug", response_model=RAGQueryResponse)
def rag_query_debug(req: QueryRequest, top_k: int = Query(6), section: str | None = Query(None)):
    docs = _rag.retrieve_docs(req.question, section=section, top_k=top_k)
    return RAGQueryResponse(question=req.question, answer="(debug) retrieved", documents=docs)
