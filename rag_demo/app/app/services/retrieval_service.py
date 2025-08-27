# services/retrieval_service.py  (교체)
from __future__ import annotations
from typing import Any, Dict, Optional, Callable, List
from ..infra.vector.chroma_store import search as chroma_search
from ..services.adapters import flatten_chroma_result

# (옵션) 간단 리랭크 & MMR 유틸
def _rerank_ce(query: str, items: List[Dict[str, Any]], top_k: int) -> List[Dict[str, Any]]:
    try:
        from sentence_transformers import CrossEncoder
        ce = CrossEncoder("BAAI/bge-reranker-v2-m3")
        pairs = [(query, it.get("text") or "") for it in items]
        scores = ce.predict(pairs).tolist()
        for it, s in zip(items, scores):
            it["rerank_score"] = float(s)
        items.sort(key=lambda x: x["rerank_score"], reverse=True)
        return items[:top_k]
    except Exception:
        # 실패하면 원본 유지
        return items[:top_k]

def _mmr(items: List[Dict[str, Any]], top_k: int, lambda_: float = 0.7) -> List[Dict[str, Any]]:
    if len(items) <= top_k:
        return items
    selected: List[Dict[str, Any]] = []
    candidates = items[:]
    while candidates and len(selected) < top_k:
        best, best_val = None, -1e9
        for c in candidates:
            rel = float(c.get("score") or 0.0)
            # 같은 title 중복 최소화(간이 페널티)
            div = 0.0
            for s in selected:
                if (c.get("metadata") or {}).get("title") == (s.get("metadata") or {}).get("title"):
                    div = max(div, 0.6)
            val = lambda_ * rel - (1.0 - lambda_) * div
            if val > best_val:
                best, best_val = c, val
        selected.append(best)
        candidates.remove(best)
    return selected

SearchFn = Callable[..., Dict[str, Any]]

def retrieve(
    q: str,
    k: int = 6,
    include_docs: bool = True,
    search_fn: SearchFn = chroma_search,
    where: Optional[Dict[str, Any]] = None,
    candidate_k: Optional[int] = None,
    use_rerank: bool = False,
    use_mmr: bool = False,
    trace_id: Optional[str] = None,
) -> Dict[str, Any]:
    """상위 k 결과 + (옵션) 리랭크/MMR + topk_gap 계산."""
    cand = int(candidate_k or max(k * 3, 24))
    res = search_fn(
        query=q, n=cand, where=where,
        include_docs=True, include_metas=True, include_ids=True, include_distances=True
    )
    items = flatten_chroma_result(res)[:cand]

    if use_rerank and items:
        items = _rerank_ce(q, items, top_k=cand)
    if use_mmr and items:
        items = _mmr(items, top_k=cand, lambda_=0.7)

    items = items[:k]

    topk_gap = None
    if len(items) >= 2 and items[0]["score"] is not None and items[-1]["score"] is not None:
        topk_gap = round(float(items[0]["score"]) - float(items[-1]["score"]), 4)

    if trace_id:
        print({"trace": trace_id, "route": "retrieve",
               "k": k, "cand": cand, "rerank": use_rerank, "mmr": use_mmr, "where": where})

    return {
        "space": res.get("space"),
        "q": q,
        "k": k,
        "where": where,
        "topk_gap": topk_gap,
        "items": [
            {
                "rank": i + 1,
                "id": it.get("id"),
                "title": (it.get("metadata") or {}).get("title"),
                "url": (it.get("metadata") or {}).get("url"),
                "section": (it.get("metadata") or {}).get("section"),
                "distance": it.get("distance"),
                "score": it.get("score"),
                "text": (it.get("text") or "") if include_docs else None,
            } for i, it in enumerate(items)
        ],
    }
