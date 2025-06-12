from fastapi import APIRouter
from models.api_io_dto import QueryRequest, QueryResponse
from vector_store import get_relevant_docs
from llm_handler.gpt_client import ask_gpt
from pydantic import BaseModel
from langchain.chat_models import ChatOpenAI
from langchain.chains import RetrievalQA
from langchain.vectorstores import FAISS
from langchain.embeddings import HuggingFaceEmbeddings
from models.api_io_dto import QueryRequest, QueryResponse

router = APIRouter()

@router.post("/query", response_model=QueryResponse)
def handle_query(req: QueryRequest):
    docs = get_relevant_docs(req.question)
    context = "\n\n".join(docs)
    prompt = f"""
    다음 문서를 참고해서 질문에 답변해줘 :
    {context}
    
    질문 : {req.question}
    """
    answer = ask_gpt(prompt=prompt)
    return QueryResponse(
        question=req.question,
        answer = answer
    )



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
