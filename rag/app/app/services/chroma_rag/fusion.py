from __future__ import annotations

"""Functions that fuse or augment retrieval results."""

from typing import Any, Dict, List
from collections import defaultdict

from app.app.infra.vector.chroma_store import get_collection


def _attach_embeddings(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    ids = [str(it.get("id") or "") for it in items if it.get("id")]
    if not ids:
        return items

    coll = get_collection()
    res = coll.get(ids=ids, include=["embeddings"])

    res_ids = res.get("ids")
    embs = res.get("embeddings")

    if res_ids is None:
        res_ids = []
    elif hasattr(res_ids, "tolist"):
        res_ids = res_ids.tolist()

    if embs is None:
        embs = []
    elif hasattr(embs, "tolist"):
        embs = embs.tolist()

    n = min(len(res_ids), len(embs))
    emap = {str(res_ids[i]): embs[i] for i in range(n)}

    for it in items:
        _id = str(it.get("id") or "")
        if _id in emap:
            it["embedding"] = emap[_id]
    return items


def _rrf_merge(ranked_lists: List[List[Dict[str, Any]]], K: int = 60) -> List[Dict[str, Any]]:
    score = defaultdict(float)
    keep: Dict[str, Dict[str, Any]] = {}
    for lst in ranked_lists:
        for r, it in enumerate(lst, start=1):
            _id = str(it.get("id") or "")
            if not _id:
                continue
            score[_id] += 1.0 / (K + r)
            if _id not in keep:
                keep[_id] = it
    merged = list(keep.values())
    # Attach rank-fusion score for downstream debugging / fallback scoring.
    for it in merged:
        _id = str(it.get("id") or "")
        if _id:
            it["_rrf"] = float(score.get(_id, 0.0))
    merged.sort(key=lambda it: score.get(str(it.get("id") or ""), 0.0), reverse=True)
    return merged


__all__ = ["_attach_embeddings", "_rrf_merge"]

