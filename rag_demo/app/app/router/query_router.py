from fastapi import APIRouter
from models.query_model import QueryRequest, QueryResponse
from vector_store.faiss import get_relevant_docs
from llm_handler.gpt_client import ask_gpt
from prompt.loader import render_template
import logging

router = APIRouter()

@router.post("/query", response_model=QueryResponse)
def handle_query(req: QueryRequest):
    question = req.question
    logging.info(f"[QueryRAG] 들어온 질문: {question}")

    docs = get_relevant_docs(question)
    context = "\n\n".join([doc.get("text", "") for doc in docs])

    if not context.strip():
        logging.warning(f"[QueryRAG] 관련 문서 없음: {question}")
        return QueryResponse(question=question, answer="관련 문서를 찾지 못했어요.")

    prompt = render_template("rag_prompt", context=context, question=question)
    answer = ask_gpt(prompt=prompt)

    logging.info(f"[QueryRAG] Q: {question} / A: {answer}")
    return QueryResponse(question=question, answer=answer)




"""
# 비동기는 openAI API에서 공식적으로 지원하지 않음.
# httpx 로 어거지 async 가능하지만 비용 이슈 발생 가능
@router.post("/query", response_model=QueryResponse) 
async def query_rag(req : QueryRequest):
    question = req.question
    
    #search vector
    docs = get_relevant_docs(question)
    
    #create llm answer
    answer = await ask_gpt(question, docs)
    
    return QueryResponse(question=question, answer=answer)
"""
