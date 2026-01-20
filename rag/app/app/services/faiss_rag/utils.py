from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.app.infra.vector.faiss_store import get_relevant_docs


def _match_where(meta: Dict[str, Any], where: Dict[str, Any]) -> bool:
    for key, value in where.items():
        if meta.get(key) != value:
            return False
    return True


def retrieve_docs(
    q: str,
    *,
    k: int = 6,
    where: Optional[Dict[str, Any]] = None,
    candidate_k: Optional[int] = None,
    use_mmr: bool = False,
    lam: float = 0.5,
) -> List[Dict[str, Any]]:
    """Fetch documents from FAISS and normalize to the RAG doc schema."""
    fetch_k = int(candidate_k or max(k * 3, 24))
    hits = get_relevant_docs(q, top_k=fetch_k)

    items: List[Dict[str, Any]] = []
    for hit in hits:
        meta = hit.get("meta") or {}
        if where and not _match_where(meta, where):
            continue
        items.append(
            {
                "id": hit.get("id"),
                "text": hit.get("text"),
                "score": hit.get("score"),
                "metadata": meta,
            }
        )

    items.sort(key=lambda x: (-(x.get("score") or 0.0)))
    return items[:k]


__all__ = ["retrieve_docs"]
