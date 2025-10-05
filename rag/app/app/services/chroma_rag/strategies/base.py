from __future__ import annotations

"""Base classes and helpers for RAG retrieval strategies."""

from typing import Any, Dict, List, Optional
import os

from app.app.infra.vector.metrics import to_similarity


class RetrievalStrategy:
    """Strategy interface used by :func:`retrieve_docs`."""

    # helper methods ---------------------------------------------------------
    def _dedup_and_score(self, service, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Remove duplicate documents and attach similarity scores."""
        seen = set()
        out: List[Dict[str, Any]] = []
        for it in items:
            meta = it.get("metadata") or {}
            key = meta.get("doc_id") or (meta.get("title"), meta.get("section")) or it.get("id")
            if key in seen:
                continue
            seen.add(key)
            if it.get("score") is None:
                it["score"] = to_similarity(it.get("distance"), space=service._last_space)
            out.append(it)
        return out

    def _rerank(self, service, q: str, items: List[Dict[str, Any]], k: int) -> List[Dict[str, Any]]:
        """Apply CrossEncoder reranking if available."""
        if not service._reranker or not items:
            return items[:k]
        pairs = [(q, (it.get("text") or "")[:800]) for it in items]
        bs = int(os.getenv("RAG_RERANK_BATCH", "64"))
        scores = service._reranker.predict(pairs, batch_size=bs, convert_to_numpy=True)
        for it, s in zip(items, scores):
            it["_ce"] = float(s)
        items.sort(key=lambda x: x.get("_ce", 0.0), reverse=True)
        return items[:k]

    # main API ----------------------------------------------------------------
    def retrieve(
        self,
        service,
        q: str,
        *,
        k: int,
        where: Optional[Dict[str, Any]],
        candidate_k: Optional[int],
        use_mmr: bool,
        lam: float,
    ) -> List[Dict[str, Any]]:
        raise NotImplementedError


__all__ = ["RetrievalStrategy"]
