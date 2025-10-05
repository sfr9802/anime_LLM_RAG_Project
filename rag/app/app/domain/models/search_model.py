from typing import List
from .base import AppBaseModel

class SearchRequest(AppBaseModel):
    query: str
    top_k: int = 3

class SearchResult(AppBaseModel):
    doc_id: str
    content: str
    score: float

class SearchResponse(AppBaseModel):
    result: List[SearchResult]
