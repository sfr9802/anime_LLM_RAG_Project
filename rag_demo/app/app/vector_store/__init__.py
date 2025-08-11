# app/vector_store/__init__.py
from typing import List, Dict, Any
from app.configure.config import settings

# 기존 것들
from .faiss import get_relevant_docs as _faiss_search
from .query import search as _chroma_search  # 내가 준 chroma용 search()

def retrieve(query: str, top_k: int = 6, where: Dict[str, Any] | None = None):
    backend = getattr(settings, "VECTOR_BACKEND", "chroma")  # env로 전환 가능
    if backend == "faiss":
        return _faiss_search(query, top_k=top_k)  # 네 기존 반환 형태 유지
    return _chroma_search(query, where=where, n=top_k)        # chroma 반환 형태와 맞춤
