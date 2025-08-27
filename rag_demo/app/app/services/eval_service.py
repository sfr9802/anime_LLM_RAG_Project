# services/eval_service.py
from __future__ import annotations
from typing import Any, Dict, List, Optional, Literal, Callable
from ..infra.vector.chroma_store import search as chroma_search
from ..services.adapters import flatten_chroma_result

SearchFn = Callable[..., Dict[str, Any]]

def _match(item: Dict[str,Any], gold: Dict[str,Any], mode: str) -> bool:
    meta = item.get("metadata") or {}
    if mode == "chunk":
        gids = gold.get("id")
        if not gids: return False
        if isinstance(gids, str): gids = [gids]
        return item.get("id") in set(gids)
    if mode == "title":
        gt = (gold.get("title") or "").strip()
        return bool(gt) and (meta.get("title") or "").strip() == gt
    gu = (gold.get("url") or "").strip()
    return bool(gu) and (meta.get("url") or "").strip() == gu

def evaluate_hit(
    goldset: List[Dict[str, Any]],
    k: int = 3,
    mode: Literal["page","title","chunk"] = "page",
    n_fetch: Optional[int] = None,
    search_fn: SearchFn = chroma_search,
) -> Dict[str, Any]:
    n = n_fetch or k
    total = hits = 0
    rr_sum = 0.0
    misses, diags = [], []

    for row in goldset:
        q, gold = row["q"], row["gold"]
        res = search_fn(q, n=n, include_docs=False, include_metas=True, include_ids=True, include_distances=True)
        items = flatten_chroma_result(res)[:n]

        found_rank = None
        for r, it in enumerate(items, start=1):
            if _match(it, gold, mode):
                found_rank = r; break

        total += 1
        if found_rank and found_rank <= k:
            hits += 1; rr_sum += 1.0 / found_rank
        else:
            misses.append({
                "q": q, "gold": gold,
                "top": [{
                    "rank": i+1,
                    "title": (it["metadata"] or {}).get("title"),
                    "url": (it["metadata"] or {}).get("url"),
                    "score": it.get("score"),
                    "distance": it.get("distance"),
                } for i, it in enumerate(items[:3])]
            })

        topk_gap = None
        if len(items) >= k and items[0]["score"] is not None and items[k-1]["score"] is not None:
            topk_gap = round(items[0]["score"] - items[k-1]["score"], 4)
        diags.append({
            "q": q, "hit": int(bool(found_rank and found_rank <= k)),
            "rank": found_rank, "top1_score": items[0]["score"] if items else None, "topk_gap": topk_gap
        })

    return {
        "k": k, "mode": mode, "count": total,
        "hit@k": hits / max(1,total),
        "mrr@k": rr_sum / max(1,total),
        "misses": misses, "diagnostics": diags
    }
