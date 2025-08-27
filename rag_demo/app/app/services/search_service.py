# services/search_service.py (핵심 부분 교체)
from typing import List, Dict, Any, Optional
from ..services.retrieval_service import retrieve as svc_retrieve
from ..services.adapters import to_docitem, flatten_chroma_result
from ..domain.models.document_model import DocumentItem

class SearchService:
    def __init__(self, top_k: int = 6):
        self.top_k = top_k

    def search(
        self, query: str, section: Optional[str] = None, top_k: Optional[int] = None
    ) -> List[DocumentItem]:
        where: Dict[str, Any] | None = {"section": section} if section else None
        k = int(top_k or self.top_k)

        res = svc_retrieve(
            q=query, k=k, where=where,
            include_docs=True, use_rerank=True, use_mmr=True
        )
        # 래퍼(dict)면 items 경로 사용
        items = res.get("items") if isinstance(res, dict) else res

        # 혹시 raw chroma dict가 넘어오면 평탄화
        if isinstance(items, dict):
            items = flatten_chroma_result(items)
        return [to_docitem(h) for h in (items or [])]
