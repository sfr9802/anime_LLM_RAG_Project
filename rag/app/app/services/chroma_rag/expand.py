from __future__ import annotations

"""Context expansion helpers."""

from typing import Any, Dict, List

from app.app.infra.vector.chroma_store import search as chroma_search
from app.app.services.adapters import flatten_chroma_result
from app.app.infra.vector.metrics import to_similarity


def _expand_same_doc(q: str, items: List[Dict[str, Any]], per_doc: int = 2) -> List[Dict[str, Any]]:
    """Bring additional chunks from top documents to enrich context."""
    if not items:
        return items
    doc_ids: List[str] = []
    for it in items:
        did = (it.get("metadata") or {}).get("doc_id")
        if did and did not in doc_ids:
            doc_ids.append(did)
    extras: List[Dict[str, Any]] = []
    taken_per: Dict[str, int] = {}
    for did in doc_ids[:3]:
        res = chroma_search(
            query=q,
            n=per_doc * 6,
            where={"doc_id": did},
            include_docs=True,
            include_metas=True,
            include_ids=True,
            include_distances=True,
        )
        ext = flatten_chroma_result(res)

        # Ensure ext chunks have usable score for sorting.
        space = (res.get("space") or "cosine").lower()
        for e in ext:
            if e.get("score") is None and e.get("distance") is not None:
                e["score"] = to_similarity(e.get("distance"), space=space)

        def _prio(x):
            sec = (x.get("metadata") or {}).get("section") or ""
            return {"요약": 0, "본문": 1}.get(sec, 2), -(x.get("score") or 0.0)

        ext.sort(key=_prio)
        seen_ids = {str(it.get("id")) for it in items}
        for e in ext:
            if str(e.get("id")) in seen_ids:
                continue
            cnt = taken_per.get(did, 0)
            if cnt >= per_doc:
                break
            extras.append(e)
            taken_per[did] = cnt + 1
    return items + extras


def _quota_by_section(items: List[Dict[str, Any]], quota: Dict[str, int], k: int) -> List[Dict[str, Any]]:
    out, used, rest = [], {s: 0 for s in quota}, []
    for it in items:
        sec = (it.get("metadata") or {}).get("section") or ""
        if sec in quota and used[sec] < quota[sec]:
            out.append(it)
            used[sec] += 1
        else:
            rest.append(it)
        if len(out) >= k:
            return out[:k]
    out += rest
    return out[:k]


__all__ = ["_expand_same_doc", "_quota_by_section"]

