from __future__ import annotations

from typing import Any, Dict, List, Optional, TYPE_CHECKING
from .base import AppBaseModel

if TYPE_CHECKING:
    from .document_model import DocumentItem

class QueryRequest(AppBaseModel):
    question: str

class QueryResponse(AppBaseModel):
    question: str
    answer: str

class RAGQueryResponse(QueryResponse):
    documents: List["DocumentItem"] = []
    metrics: Dict[str, Any] = {}

# pydantic v2 forward ref rebuild
RAGQueryResponse.model_rebuild()
