from fastapi import APIRouter
from models.api_io_dto import QueryRequest, QueryResponse
from vector_store import get_relevant_docs
from llm_handler.gpt_client import gpt_answer

router = APIRouter()

@router.post("/query", response_model=QueryResponse) 
async def query_rag(req : QueryRequest):
    question = req.question
    
    #search vector
    docs = get_relevant_docs(question)
    
    #create llm answer
    answer = await gpt_answer(question, docs)
    
    return QueryResponse(question=question, answer=answer)