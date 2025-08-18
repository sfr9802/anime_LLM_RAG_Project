# services/search_service.py
from typing import List, Dict, Any, Optional
from rag_demo.app.app.infra.vector import retrieve
from services.adapters import to_docitem, flatten_chroma_result  # ⬅ 추가
from domain.models.document_model import DocumentItem

class SearchService:
    def __init__(self, top_k: int = 6):
        self.top_k = top_k

    def search(
        self, query: str, section: Optional[str] = None, top_k: Optional[int] = None
    ) -> List[DocumentItem]:
        where: Dict[str, Any] | None = {"section": section} if section else None
        n = int(top_k or self.top_k)
        hits = retrieve(query, top_k=n, where=where)

        # ⬇⬇⬇ 추가: Chroma(dict)면 평탄화
        if isinstance(hits, dict):
            hits = flatten_chroma_result(hits)

        return [to_docitem(h) for h in hits]
