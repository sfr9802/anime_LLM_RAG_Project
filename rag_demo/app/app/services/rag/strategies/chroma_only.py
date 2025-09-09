from __future__ import annotations
"""Chroma-only retrieval strategy with query expansion + optional hybrid BM25."""

from typing import Any, Dict, List, Optional
import os

from app.app.services.adapters import flatten_chroma_result
from app.app.infra.vector.chroma_store import search as chroma_search

from ..utils import _cap_by_title, _env_int, _env_ints, _expand_queries
from ..fusion import _attach_embeddings, _rrf_merge
from ..mmr import _mmr
from .base import RetrievalStrategy

try:
    # 선택: BM25 스파스 검색기 (없으면 None)
    from app.app.domain.bm25 import bm25_search  # (query, n, where) -> flatten_chroma_like list
except Exception:
    bm25_search = None


def _rrf_merge_weighted(lists: List[List[Dict[str, Any]]], weights: Optional[List[float]] = None, K: int = 60) -> List[Dict[str, Any]]:
    """가중치 RRF. 동일 id를 기준으로 랭크 기반 점수 합산.
    weights가 None이면 1.0로 처리.
    """
    if not lists:
        return []
    if weights is None:
        weights = [1.0] * len(lists)
    score_map: Dict[str, float] = {}
    pick: Dict[str, Dict[str, Any]] = {}
    for li, items in enumerate(lists):
        w = float(weights[li] if li < len(weights) else 1.0)
        for r, it in enumerate(items, start=1):
            _id = it.get("id") or f"{it.get('title','')}|{it.get('section','')}|{it.get('offset','')}"
            score_map[_id] = score_map.get(_id, 0.0) + (w / (K + r))
            if _id not in pick:
                pick[_id] = it
    merged = sorted(pick.values(), key=lambda it: score_map[it.get("id") or ""], reverse=True)
    return merged


class ChromaOnlyStrategy(RetrievalStrategy):
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
        qvars = _expand_queries(q)

        # 프로파일 기반 기본값 (env가 있으면 env 우선)
        profile = (os.getenv("RAG_PROFILE") or "").lower()  # "quality" | "balanced"
        base_n = _env_int("RAG_FETCH_K", 120)
        aux_n  = _env_int("RAG_FETCH_K_AUX", 60)

        lists: List[List[Dict[str, Any]]] = []
        resA = chroma_search(
            query=q,
            n=(candidate_k or base_n),
            where=where,
            include_docs=True,
            include_metas=True,
            include_ids=True,
            include_distances=True,
        )
        service._last_space = (resA.get("space") or "cosine").lower()
        lists.append(flatten_chroma_result(resA))

        for qq in qvars:
            if qq == q:
                continue
            res = chroma_search(
                query=qq,
                n=aux_n,
                where=where,
                include_docs=True,
                include_metas=True,
                include_ids=True,
                include_distances=True,
            )
            lists.append(flatten_chroma_result(res))

        # ----- Optional Hybrid (BM25) -----
        hybrid_on = (os.getenv("HYBRID_USE", "false").lower() in ("1", "true", "yes")) and (bm25_search is not None)
        alpha = float(os.getenv("HYBRID_ALPHA", "0.25"))  # 0.2~0.3 권장
        if hybrid_on:
            try:
                bm = bm25_search(q, n=base_n, where=where)  # flatten_chroma_result 형태를 맞추는 걸 권장
                # 가중 RRF 병합: [chroma main, expansions..., bm25]
                weights = [1.0] * len(lists) + [alpha]
                items = _rrf_merge_weighted(lists + [bm], weights=weights, K=60)
            except Exception:
                # 안전장치: 실패 시 chroma-only로 진행
                items = _rrf_merge(lists, K=60)
        else:
            items = _rrf_merge(lists, K=60)

        base = self._dedup_and_score(service, items)

        # 프로파일 디폴트
        if profile == "quality":
            default_cap, default_prek, default_mmrk, default_rerank_in = [2], [80], [40], [20]
        else:
            default_cap, default_prek, default_mmrk, default_rerank_in = [2], [80], [30], [30]

        cap_list      = _env_ints("RAG_TITLE_CAP",  default_cap)
        prek_list     = _env_ints("RAG_MMR_PRE_K",  default_prek)
        mmrk_list     = _env_ints("RAG_MMR_K",      default_mmrk)
        rerank_in_lst = _env_ints("RAG_RERANK_IN",  default_rerank_in)
        ENS_MAX = int(os.getenv("RAG_ENS_MAX_COMBOS", "12"))

        pools: List[List[Dict[str, Any]]] = []

        if not use_mmr:
            tried = 0
            for cap in cap_list:
                if tried >= ENS_MAX:
                    break
                dedup = _cap_by_title(base, cap=cap)
                pools.append(dedup[: max(k * 6, 72)])
                tried += 1
        else:
            tried = 0
            for cap in cap_list:
                if tried >= ENS_MAX:
                    break
                dedup = _cap_by_title(base, cap=cap)
                if not dedup:
                    continue
                prek_max = min(max(prek_list), len(dedup))
                pre_base = _attach_embeddings(dedup[:prek_max])
                for prek in prek_list:
                    if tried >= ENS_MAX:
                        break
                    prek = min(prek, len(pre_base))
                    if prek <= 0:
                        continue
                    for mmrk in mmrk_list:
                        if tried >= ENS_MAX:
                            break
                        mmrk = min(mmrk, prek)
                        if mmrk <= 0:
                            continue
                        pre = pre_base[:prek]
                        pools.append(_mmr(q, pre, k=mmrk, lam=lam))
                        tried += 1

        merged = _rrf_merge(pools, K=60) if len(pools) > 1 else (pools[0] if pools else [])
        merged = self._dedup_and_score(service, merged)

        rerank_in = min(max(rerank_in_lst), len(merged))
        if service._reranker and rerank_in > 0:
            reranked = self._rerank(service, q, merged[:rerank_in], k)
            if len(reranked) < k:
                tail = [it for it in merged[rerank_in:] if it not in reranked]
                reranked.extend(tail[: k - len(reranked)])
            return reranked[:k]
        return merged[:k]


__all__ = ["ChromaOnlyStrategy"]