# models/query_model.py
from __future__ import annotations
from typing import List
from .document_model import DocumentItem
from models.base import AppBaseModel

class QueryRequest(AppBaseModel):
    question: str

class QueryResponse(AppBaseModel):
    question: str
    answer: str

class RAGQueryResponse(QueryResponse):
    documents: List["DocumentItem"]

# ← 여기 중요: 모든 클래스/임포트 정의가 끝난 "뒤"에서 호출
try:
    RAGQueryResponse.model_rebuild()      # Pydantic v2
except Exception:
    RAGQueryResponse.update_forward_refs()  # v1
