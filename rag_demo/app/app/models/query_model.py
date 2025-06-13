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
