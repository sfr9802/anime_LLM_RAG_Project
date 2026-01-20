# services/retrieval_service.py
from __future__ import annotations
from typing import Any, Dict, Optional, Callable, List
from functools import lru_cache
from ..infra.vector.chroma_store import search as chroma_search
from ..services.adapters import flatten_chroma_result
from ..infra.vector.metrics import to_similarity  # <- distance -> score 정규화

SearchFn = Callable[..., Dict[str, Any]]

@lru_cache(maxsize=1)
def _get_ce():
    """CrossEncoder는 한번만 로드(서빙 병목 방지)."""
    from sentence_transformers import CrossEncoder
    import torch
    # max_length로 잘라 OOM 방지
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    return CrossEncoder("BAAI/bge-reranker-v2-m3", device=dev, max_length=512)

# (옵션) 간단 리랭크 & MMR 유틸
def _rerank_ce(query: str, items: List[Dict[str, Any]], top_k: int, text_max_chars: int = 4000) -> List[Dict[str, Any]]:
    try:
        ce = _get_ce()
        pairs = [(query, (it.get("text") or "")[:text_max_chars]) for it in items]
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
            # If rerank ran, prefer rerank_score; else fall back to similarity score.
            rel = c.get("rerank_score")
            if rel is None:
                rel = c.get("score")
            rel = float(rel or 0.0)
            # 같은 title 중복 최소화(간이 페널티)
            div = 0.0
            for s in selected:
                if (c.get("metadata") or {}).get("title") == (s.get("metadata") or {}).get("title"):
                    div = max(div, 0.6)
            val = lambda_ * rel - (1.0 - lambda_) * div
            if val > best_val:
                best, best_val = c, val
        selected.append(best)     # type: ignore[arg-type]
        candidates.remove(best)   # type: ignore[arg-type]
    return selected

def retrieve(
    q: str,
    k: int = 6,
    include_docs: bool = True,
    search_fn: SearchFn = chroma_search,
    where: Optional[Dict[str, Any]] = None,
    candidate_k: Optional[int] = None,
    use_rerank: bool = False,
    use_mmr: bool = False,
    min_score: Optional[float] = None,   # 선택: 낮은 점수 컷
    trace_id: Optional[str] = None,
) -> Dict[str, Any]:
    """상위 k 결과 + (옵션) 리랭크/MMR + topk_gap 계산."""
    cand = int(candidate_k or max(k * 3, 24))
    need_docs = include_docs or use_rerank  # 리랭크면 텍스트 필요

    res = search_fn(
        query=q, n=cand, where=where,
        include_docs=need_docs, include_metas=True, include_ids=True, include_distances=True
    )
    space = (res.get("space") or "cosine").lower()
    items = flatten_chroma_result(res)[:cand]

    # distance -> score 정규화 (0..1, 높을수록 유사)
    for it in items:
        it["score"] = to_similarity(it.get("distance"), space=space)

    # 너무 낮은 건 컷(선택)
    if min_score is not None:
        items = [it for it in items if (it.get("score") is not None and float(it["score"]) >= float(min_score))]

    # 리랭크 / MMR
    if use_rerank and items:
        items = _rerank_ce(q, items, top_k=min(cand, len(items)))
    if use_mmr and items:
        items = _mmr(items, top_k=min(cand, len(items)), lambda_=0.7)

    # 리랭크/MMR 안 쓰는 경우 기본 정렬: score desc -> distance asc
    if not use_rerank and not use_mmr:
        items.sort(key=lambda x: (-(x.get("score") or -1.0), (x.get("distance") or 1e9)))

    # 최종 상위 k
    items = items[:k]

    # gap 계산(절대/상대)
    topk_gap = None
    topk_rel_gap = None
    if len(items) >= 2 and items[0].get("score") is not None and items[-1].get("score") is not None:
        s1, s2 = float(items[0]["score"]), float(items[-1]["score"])
        topk_gap = round(s1 - s2, 4)
        if s1 > 1e-9:
            topk_rel_gap = round((s1 - s2) / s1, 4)

    if trace_id:
        print({"trace": trace_id, "route": "retrieve",
               "k": k, "cand": cand, "rerank": use_rerank, "mmr": use_mmr,
               "where": where, "min_score": min_score})

    return {
        "space": space,
        "q": q,
        "k": k,
        "where": where,
        "topk_gap": topk_gap,
        "topk_rel_gap": topk_rel_gap,  # 선택 필드
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
