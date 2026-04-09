"""Response schemas."""
from __future__ import annotations
from typing import Dict, List, Optional
from pydantic import BaseModel, ConfigDict

class DocumentItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: Optional[str] = None
    page_id: Optional[str] = None
    chunk_id: Optional[str] = None
    url: Optional[str] = None
    title: Optional[str] = None
    section: Optional[str] = None
    seed: Optional[str] = None
    score: Optional[float] = None
    text: Optional[str] = None

class QueryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    question: str
    answer: str

class RAGQueryResponse(QueryResponse):
    documents: List[DocumentItem] = []
    metrics: Dict = {}

class SearchResult(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    doc_id: Optional[str] = None
    content: Optional[str] = None
    score: Optional[float] = None

class SearchResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    result: List[SearchResult] = []
