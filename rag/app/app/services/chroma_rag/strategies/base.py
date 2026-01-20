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

        def _uid(it: Dict[str, Any]) -> str:
            md = it.get("metadata") or {}
            # Prefer stable doc_id -> chunk id -> fallback composite.
            did = md.get("doc_id")
            if did:
                return str(did)
            _id = it.get("id")
            if _id:
                return str(_id)
            title = (md.get("title") or it.get("title") or "").strip()
            sec = (md.get("section") or it.get("section") or "").strip()
            off = (md.get("offset") or it.get("offset") or "")
            return f"{title}|{sec}|{off}"

        seen = set()
        out: List[Dict[str, Any]] = []
        for it in items:
            meta = it.get("metadata") or {}
            key = _uid(it)
            if key in seen:
                continue
            seen.add(key)
            if it.get("score") is None:
                # Standardize: always attach a monotonic "score" (higher is better).
                dist = it.get("distance")
                if dist is not None:
                    space = getattr(service, "_last_space", None) or "cosine"
                    it["score"] = to_similarity(dist, space=space)
                elif it.get("_rrf") is not None:
                    it["score"] = float(it.get("_rrf") or 0.0)
                else:
                    it["score"] = 0.0
            out.append(it)
        return out

    def _rerank(self, service, q: str, items: List[Dict[str, Any]], k: int) -> List[Dict[str, Any]]:
        """
        CrossEncoder reranker가 설정되어 있을 경우, 입력 문서들을 재정렬하여 상위 k개를 반환합니다.
        """

        reranker = service._reranker
        if not reranker or not items:
            return items[:k]

        # (질문, 문서) 쌍 생성 (문서는 최대 800자까지 잘라서 사용)
        query_doc_pairs = [
            (q, (doc.get("text") or "")[:800])
            for doc in items
        ]

        batch_size = int(os.getenv("RAG_RERANK_BATCH", "64"))

        # CrossEncoder로 유사도 예측
        relevance_scores = reranker.predict(
            query_doc_pairs,
            batch_size=batch_size,
            convert_to_numpy=True
        )

        # 각 문서에 점수 추가
        for doc, score in zip(items, relevance_scores):
            doc["_ce"] = float(score)

        # 점수 기준 내림차순 정렬 후 상위 k개 선택
        sorted_items = sorted(items, key=lambda d: d.get("_ce", 0.0), reverse=True)
        return sorted_items[:k]


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
