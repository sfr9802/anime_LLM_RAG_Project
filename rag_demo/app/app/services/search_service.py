from typing import List, Dict, Any, Optional
from vector_store import retrieve  # __init__.py에서 backend 스위치
from services.adapters import to_docitem
from models.document_model import DocumentItem

class SearchService:
    def __init__(self, top_k: int = 6):
        self.top_k = top_k

    def search(
        self, query: str, section: Optional[str] = None, top_k: Optional[int] = None
    ) -> List[DocumentItem]:
        where: Dict[str, Any] | None = {"section": section} if section else None
        n = top_k or self.top_k
        hits = retrieve(query, top_k=n, where=where)
        return [to_docitem(h) for h in hits]
