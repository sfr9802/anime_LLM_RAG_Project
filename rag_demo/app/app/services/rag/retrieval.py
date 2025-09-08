from __future__ import annotations

"""Retrieval strategies and helpers for RagService."""

from typing import Any, Dict, List, Optional, Union
import os

from app.app.services.adapters import flatten_chroma_result
from app.app.infra.vector.chroma_store import search as chroma_search
from app.app.infra.vector.metrics import to_similarity

from .utils import _cap_by_title, _env_int, _env_ints, _expand_queries
from .fusion import _attach_embeddings, _rrf_merge
from .mmr import _mmr


def _dedup_and_score(self, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    out: List[Dict[str, Any]] = []
    for it in items:
        meta = it.get("metadata") or {}
        key = meta.get("doc_id") or (meta.get("title"), meta.get("section")) or it.get("id")
        if key in seen:
            continue
        seen.add(key)
        if it.get("score") is None:
            it["score"] = to_similarity(it.get("distance"), space=self._last_space)
        out.append(it)
    return out


def _rerank(self, q: str, items: List[Dict[str, Any]], k: int) -> List[Dict[str, Any]]:
    if not self._reranker or not items:
        return items[:k]
    pairs = [(q, (it.get("text") or "")[:800]) for it in items]
    bs = int(os.getenv("RAG_RERANK_BATCH", "64"))
    scores = self._reranker.predict(pairs, batch_size=bs, convert_to_numpy=True)
    for it, s in zip(items, scores):
        it["_ce"] = float(s)
    items.sort(key=lambda x: x.get("_ce", 0.0), reverse=True)
    return items[:k]


def _retrieve_baseline(
    self,
    q: str,
    *,
    k: int,
    where: Optional[Dict[str, Any]],
    candidate_k: Optional[int],
    use_mmr: bool,
    lam: float,
) -> List[Dict[str, Any]]:
    fetch_k = candidate_k or _env_int("RAG_FETCH_K", 160)
    res = chroma_search(
        query=q,
        n=fetch_k,
        where=where,
        include_docs=True,
        include_metas=True,
        include_ids=True,
        include_distances=True,
    )
    self._last_space = (res.get("space") or "cosine").lower()
    dedup0 = _dedup_and_score(self, flatten_chroma_result(res))

    cap_list = _env_ints("RAG_TITLE_CAP", [2])
    prek_list = _env_ints("RAG_MMR_PRE_K", [120])
    mmrk_list = _env_ints("RAG_MMR_K", [max(k * 4, 40)])
    rerank_in_lst = _env_ints("RAG_RERANK_IN", [24])
    ENS_MAX = int(os.getenv("RAG_ENS_MAX_COMBOS", "12"))

    pools: List[List[Dict[str, Any]]] = []
    if not use_mmr:
        tried = 0
        for cap in cap_list:
            if tried >= ENS_MAX:
                break
            dedup = _cap_by_title(dedup0, cap=cap)
            pools.append(dedup[: max(k * 6, 72)])
            tried += 1
    else:
        tried = 0
        for cap in cap_list:
            if tried >= ENS_MAX:
                break
            dedup = _cap_by_title(dedup0, cap=cap)
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
    merged = _dedup_and_score(self, merged)

    rerank_in = min(max(rerank_in_lst), len(merged))
    if self._reranker and rerank_in > 0:
        return _rerank(self, q, merged[:rerank_in], k)
    else:
        return merged[:k]


def _retrieve_chroma_only(
    self,
    q: str,
    *,
    k: int,
    where: Optional[Dict[str, Any]],
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
    self._last_space = (resA.get("space") or "cosine").lower()
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
    base = _dedup_and_score(self, items)

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
    merged = _dedup_and_score(self, merged)

    rerank_in = min(max(rerank_in_lst), len(merged))
    if self._reranker and rerank_in > 0:
        return _rerank(self, q, merged[:rerank_in], k)
    else:
        return merged[:k]


class BaselineStrategy:
    """Retrieve documents using the baseline strategy."""

    def __call__(
        self,
        svc: Any,
        q: str,
        *,
        k: int,
        where: Optional[Dict[str, Any]],
        candidate_k: Optional[int],
        use_mmr: bool,
        lam: float,
    ) -> List[Dict[str, Any]]:
        return _retrieve_baseline(
            svc,
            q,
            k=k,
            where=where,
            candidate_k=candidate_k,
            use_mmr=use_mmr,
            lam=lam,
        )


class ChromaOnlyStrategy:
    """Retrieve documents using only Chroma search."""

    def __call__(
        self,
        svc: Any,
        q: str,
        *,
        k: int,
        where: Optional[Dict[str, Any]],
        candidate_k: Optional[int],
        use_mmr: bool,
        lam: float,
    ) -> List[Dict[str, Any]]:
        # ``candidate_k`` is accepted for interface compatibility but ignored.
        return _retrieve_chroma_only(
            svc,
            q,
            k=k,
            where=where,
            use_mmr=use_mmr,
            lam=lam,
        )


_DEFAULT_STRATEGIES: Dict[str, Any] = {
    "baseline": BaselineStrategy(),
    "chroma_only": ChromaOnlyStrategy(),
    "multiq": ChromaOnlyStrategy(),
}


def retrieve_docs(
    self,
    q: str,
    *,
    k: int = 6,
    where: Optional[Dict[str, Any]] = None,
    candidate_k: Optional[int] = None,
    use_mmr: bool = True,
    lam: float = 0.5,
    strategy: Union[str, Any] = "baseline",
) -> List[Dict[str, Any]]:
    """Retrieve documents using the specified strategy.

    ``strategy`` may be a string key for built-in strategies or a callable
    implementing the same interface as :class:`BaselineStrategy`.
    """

    if isinstance(strategy, str):
        strat = _DEFAULT_STRATEGIES.get(strategy)
        if strat is None:
            raise ValueError(f"unknown strategy: {strategy}")
    else:
        strat = strategy

    return strat(
        self,
        q,
        k=k,
        where=where,
        candidate_k=candidate_k,
        use_mmr=use_mmr,
        lam=lam,
    )


__all__ = [
    "retrieve_docs",
    "BaselineStrategy",
    "ChromaOnlyStrategy",
]

