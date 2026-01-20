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
    from app.app.infra.sparse.bm25 import bm25_search  # (query, n, where) -> flatten_chroma_like list
except Exception:
    bm25_search = None


def _rrf_id(it: Dict[str, Any]) -> str:
    return it.get("id") or f"{it.get('title','')}|{it.get('section','')}|{it.get('offset','')}"


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
            rid = _rrf_id(it)
            score_map[rid] = score_map.get(rid, 0.0) + (w / (K + r))
            if rid not in pick:
                pick[rid] = it
    merged = list(pick.values())
    for it in merged:
        it["_rrf"] = float(score_map.get(_rrf_id(it), 0.0))
    return sorted(merged, key=lambda it: score_map[_rrf_id(it)], reverse=True)


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
        qvars_all = _expand_queries(q)

        # 프로파일 기반 기본값 (env가 있으면 env 우선)
        profile = (os.getenv("RAG_PROFILE") or "").lower()  # "quality" | "balanced"
        base_n = _env_int("RAG_FETCH_K", 120)
        aux_n  = _env_int("RAG_FETCH_K_AUX", 60)

        # 확장 상한 및 감쇠
        max_exp = int(os.getenv("RAG_MAX_EXPANSIONS", "2"))
        aux_decay = float(os.getenv("RAG_AUX_DECAY", "0.75"))
        qvars = []
        for i, qq in enumerate(qvars_all):
            if qq == q: continue
            if i >= max_exp: break
            qvars.append((qq, max(16, int(aux_n * (aux_decay ** i)))))

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

        for qq, n_i in qvars:
            res = chroma_search(
                query=qq,
                n=n_i,
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

        def _is_sentence_like(s: str) -> bool:
            return len((s or "").split()) >= 6 or any(ch in (s or "") for ch in ".?!")

        use_w = os.getenv("RAG_USE_WEIGHTED_EXP", "true").lower() in ("1", "true", "yes")

        def _merge_expansion_only() -> List[Dict[str, Any]]:
            if use_w:
                a0 = float(os.getenv("RAG_EXP_ALPHA", "1.0"))
                decay = float(os.getenv("RAG_EXP_DECAY", "0.6"))
                weights = [a0] + [a0 * (decay ** i) for i in range(len(lists) - 1)]
                return _rrf_merge_weighted(lists, weights=weights, K=int(os.getenv("RAG_RRF_K", "60")))
            return _rrf_merge(lists, K=int(os.getenv("RAG_RRF_K", "60")))

        if hybrid_on:
            try:
                # 문장형 질의면 하이브리드 가중치 축소
                cooldown = float(os.getenv("HYBRID_ALPHA_SENT_COOLDOWN", "0.6"))
                a = alpha * (cooldown if _is_sentence_like(q) else 1.0)
                bm = bm25_search(q, n=base_n, where=where)  # flatten_chroma_like list
                rrf_K = int(os.getenv("RAG_RRF_K", "60"))
                weights = [1.0] * len(lists) + [a]
                items = _rrf_merge_weighted(lists + [bm], weights=weights, K=rrf_K)
            except Exception:
                # Hybrid failed -> fall back to expansion-only merge
                items = _merge_expansion_only()
        else:
            items = _merge_expansion_only()

        base = self._dedup_and_score(service, items)

        # 섹션/문단 캡 (선택)
        sec_cap = int(os.getenv("RAG_SECTION_CAP", "0"))
        if sec_cap > 0:
            def _cap_by_section(items: List[Dict[str, Any]], cap: int = 1) -> List[Dict[str, Any]]:
                count, out = {}, []
                for it in items:
                    md = it.get("metadata", {})
                    key = (md.get("title") or it.get("title", ""), md.get("section") or it.get("section", ""))
                    c = count.get(key, 0)
                    if c < cap:
                        out.append(it); count[key] = c + 1
                return out
            base = _cap_by_section(base, cap=sec_cap)

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

        merged = _rrf_merge(pools, K=int(os.getenv("RAG_RRF_K", "60"))) if len(pools) > 1 else (pools[0] if pools else [])
        merged = self._dedup_and_score(service, merged)

        rerank_in = min(max(rerank_in_lst), len(merged))
        if service._reranker and rerank_in > 0:
            reranked = self._rerank(service, q, merged[:rerank_in], k)
            if len(reranked) < k:
                chosen = { _rrf_id(it) for it in reranked }
                tail = [it for it in merged[rerank_in:] if _rrf_id(it) not in chosen]
                reranked.extend(tail[: k - len(reranked)])

            # ── 최종 하드 디듑(옵션) ─────────────────────────────────────────
            final_mode = (os.getenv("RAG_FINAL_DEDUP_BY", "none") or "none").lower()
            if final_mode == "title":
                out = _cap_by_title(reranked, cap=1)
                if len(out) < k:
                    seen = { ( (it.get("metadata", {}) or {}).get("title") or it.get("title") or "" ).strip().lower()
                             for it in out }
                    for it in merged[rerank_in:]:
                        t = ( (it.get("metadata", {}) or {}).get("title") or it.get("title") or "" ).strip().lower()
                        if t and t in seen:
                            continue
                        out.append(it); seen.add(t)
                        if len(out) >= k: break
                return out[:k]
            # ────────────────────────────────────────────────────────────────
            return reranked[:k]

        final_mode = (os.getenv("RAG_FINAL_DEDUP_BY", "none") or "none").lower()
        if final_mode == "title":
            out = _cap_by_title(merged, cap=1)
            if len(out) < k:
                seen = { ( (it.get("metadata", {}) or {}).get("title") or it.get("title") or "" ).strip().lower()
                         for it in out }
                for it in merged:
                    t = ( (it.get("metadata", {}) or {}).get("title") or it.get("title") or "" ).strip().lower()
                    if t and t in seen:
                        continue
                    out.append(it); seen.add(t)
                    if len(out) >= k: break
            return out[:k]
        return merged[:k]


__all__ = ["ChromaOnlyStrategy"]