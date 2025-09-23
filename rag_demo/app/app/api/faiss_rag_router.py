from fastapi import Query,APIRouter
from ..domain.models.query_model import RAGQueryResponse


router = APIRouter(prefix="/rag/v2", tags=["rag"])

@router.post("/ask", response_model=RAGQueryResponse)
async def rag_ask():
    