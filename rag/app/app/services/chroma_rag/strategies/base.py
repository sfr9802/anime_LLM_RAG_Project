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

    def _rerank(
        self,
        reranker_model,
        query: str,
        candidates: List[Dict[str, Any]],
        top_k: int,
        score_field: str = "ce_score"
    ) -> List[Dict[str, Any]]:
        """
        CrossEncoder를 이용해 후보 문서를 재정렬하고 상위 top_k개를 반환합니다.

        :param reranker_model: SentenceTransformer 등 CrossEncoder 모델
        :param query: 사용자 질문
        :param candidates: 문서 리스트 (dict)
        :param top_k: 상위 몇 개까지 선택할지
        :param score_field: 점수를 저장할 필드명 (기본: 'ce_score')
        :return: 재정렬된 상위 문서 리스트
        """
        if not reranker_model or not candidates:
            return candidates[:top_k]

        # (query, 문서) 쌍 생성
        query_passage_pairs = [
            (query, (doc.get("text") or "")[:800])
            for doc in candidates
        ]

        # 배치 사이즈 설정
        batch_size = int(os.getenv("RAG_RERANK_BATCH", "64"))

        # CrossEncoder로 점수 예측
        relevance_scores = reranker_model.predict(
            query_passage_pairs,
            batch_size=batch_size,
            convert_to_numpy=True
        )

        # 각 문서에 점수 부여
        for doc, score in zip(candidates, relevance_scores):
            doc[score_field] = float(score)

        # 점수 기준으로 정렬 후 상위 top_k 반환
        sorted_docs = sorted(
            candidates,
            key=lambda d: d.get(score_field, 0.0),
            reverse=True
        )
        return sorted_docs[:top_k]


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
