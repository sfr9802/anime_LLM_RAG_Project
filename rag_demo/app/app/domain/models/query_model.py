# models/query_model.py
from __future__ import annotations
from typing import List
from .base import AppBaseModel

class QueryRequest(AppBaseModel):
    question: str

class QueryResponse(AppBaseModel):
    question: str
    answer: str

class RAGQueryResponse(QueryResponse):
    documents: List["DocumentItem"]  # 문자열로 참조

# 모든 클래스 정의 이후에 import & 재빌드
from .document_model import DocumentItem
RAGQueryResponse.model_rebuild()
