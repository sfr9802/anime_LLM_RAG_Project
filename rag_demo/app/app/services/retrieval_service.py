# services/retrieval_service.py
from __future__ import annotations
from typing import Any, Dict, List, Optional, Callable
from infra.vector.chroma_store import search as chroma_search
from services.adapters import flatten_chroma_result

SearchFn = Callable[..., Dict[str, Any]]

def retrieve(
    q: str,
    k: int = 3,
    include_docs: bool = False,
    search_fn: SearchFn = chroma_search,
) -> Dict[str, Any]:
    """상위 k 결과 + 분리도(topk_gap) 계산까지 서비스에서 처리"""
    res = search_fn(
        query=q, n=k,
        include_docs=include_docs,
        include_metas=True, include_ids=True, include_distances=True
    )
    items = flatten_chroma_result(res)[:k]

    topk_gap = None
    if len(items) >= 2 and items[0]["score"] is not None and items[-1]["score"] is not None:
        topk_gap = round(items[0]["score"] - items[-1]["score"], 4)

    return {
        "space": res.get("space"),
        "q": q,
        "k": k,
        "topk_gap": topk_gap,
        "items": [
            {
                "rank": i+1,
                "id": it.get("id"),
                "title": (it.get("metadata") or {}).get("title"),
                "url": (it.get("metadata") or {}).get("url"),
                "section": (it.get("metadata") or {}).get("section"),
                "distance": it.get("distance"),
                "score": it.get("score"),
                "snippet": (it.get("text") or "")[:240] if include_docs else None,
            } for i, it in enumerate(items)
        ],
    }
