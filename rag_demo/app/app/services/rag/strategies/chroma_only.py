from __future__ import annotations

"""Chroma-only retrieval strategy with query expansion."""

from typing import Any, Dict, List, Optional
import os

from app.app.services.adapters import flatten_chroma_result
from app.app.infra.vector.chroma_store import search as chroma_search

from ..utils import _cap_by_title, _env_int, _env_ints, _expand_queries
from ..fusion import _attach_embeddings, _rrf_merge
from ..mmr import _mmr
from .base import RetrievalStrategy


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

        base_n = _env_int("RAG_FETCH_K", max(k * 8, 80))
        aux_n = _env_int("RAG_FETCH_K_AUX", max(k * 4, 40))

        lists: List[List[Dict[str, Any]]] = []
        resA = chroma_search(
            query=q,
            n=base_n,
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

        items = _rrf_merge(lists, K=60)
        base = self._dedup_and_score(service, items)

        cap_list = _env_ints("RAG_TITLE_CAP", [2])
        prek_list = _env_ints("RAG_MMR_PRE_K", [160])
        mmrk_list = _env_ints("RAG_MMR_K", [max(k * 4, 40)])
        rerank_in_lst = _env_ints("RAG_RERANK_IN", [24])
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
            return self._rerank(service, q, merged[:rerank_in], k)
        else:
            return merged[:k]


__all__ = ["ChromaOnlyStrategy"]
