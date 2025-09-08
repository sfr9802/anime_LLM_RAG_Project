
from __future__ import annotations
from typing import Any, Dict, List, Optional
import os, re, unicodedata, time
import numpy as np
import torch
from collections import defaultdict

try:
    from sentence_transformers import CrossEncoder
except Exception:
    CrossEncoder = None

from app.app.infra.vector.chroma_store import search as chroma_search, get_collection
from app.app.services.adapters import flatten_chroma_result
from app.app.domain.embeddings import embed_queries, embed_passages
from app.app.infra.llm.provider import get_chat
from app.app.configure import config

try:
    from app.app.domain.models.document_model import DocumentItem
    from app.app.domain.models.query_model import RAGQueryResponse
except Exception:
    from app.app.models.document_model import DocumentItem
    from app.app.models.query_model import RAGQueryResponse

from app.app.infra.vector.metrics import to_similarity

try:
    from app.app.metrics.quality import dup_rate, keys_from_docs
except Exception:
    def dup_rate(keys_topk: List[str]) -> float:
        k = len(keys_topk)
        return 0.0 if k <= 1 else 1.0 - (len(set(keys_topk)) / float(k))
    def keys_from_docs(docs: List[Dict], by: str = "doc") -> List[str]:
        out: List[str] = []
        for d in docs:
            m = (d.get("metadata") or {})
            if by == "doc":
                out.append(m.get("doc_id") or "")
            else:
                out.append(m.get("seed_title") or m.get("parent") or m.get("title") or "")
        return out

# ---------- helpers ----------
def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "").lower()
    return re.sub(r"[\s\W_]+", "", s, flags=re.UNICODE)

_DEFAULT_ALIAS_MAP = {
    "방도리": ["BanG Dream!", "bang dream", "bandori", "girls band party", "bangdream"],
    "귀칼": ["귀멸의 칼날"],
    "5등분의 신부": ["오등분의 신부", "The Quintessential Quintuplets", "5-toubun no hanayome", "五等分の花嫁"],
}
_ALIAS_MAP = getattr(config, "ALIAS_MAP", None) or _DEFAULT_ALIAS_MAP

def _expand_queries(q: str) -> List[str]:
    out = [q]
    nq = _norm(q)
    if nq != q:
        out.append(nq)
    for k, vs in _ALIAS_MAP.items():
        if k in q:
            out.extend(vs)
    uniq, seen = [], set()
    for s in out:
        s = (s or "").strip()
        if len(s) < 2: continue
        if s in seen: continue
        seen.add(s); uniq.append(s)
    return uniq

def _title_from_meta(meta: Dict[str, Any]) -> str:
    return meta.get("seed_title") or meta.get("parent") or meta.get("title") or ""

# ---------- tuning utils ----------
def _cap_by_title(items: List[Dict[str, Any]], cap: int = 2) -> List[Dict[str, Any]]:
    if cap <= 0 or not items:
        return items
    cnt: Dict[str, int] = {}
    out: List[Dict[str, Any]] = []
    for it in items:
        meta = it.get("metadata") or {}
        title = meta.get("seed_title") or meta.get("parent") or meta.get("title") or ""
        c = cnt.get(title, 0)
        if c < cap:
            out.append(it)
            cnt[title] = c + 1
    return out

def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except Exception:
        return default

def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except Exception:
        return default
    
def _env_ints(name: str, default: List[int]) -> List[int]:
    raw = os.getenv(name)
    if not raw:
        return list(default)
    toks = [t.strip() for t in raw.replace(";", ",").split(",")]
    out: List[int] = []
    for t in toks:
        if not t:
            continue
        try:
            out.append(int(t))
        except Exception:
            pass
    out = sorted(set(out))
    return out or list(default)

_RERANKER_SINGLETON = None
_RERANKER_DEVICE = None
ENS_MAX = int(os.getenv("RAG_ENS_MAX_COMBOS", "12"))

class RagService:
    def __init__(self, force_reranker: Optional[bool]=None):
        self.chat = get_chat()
        self._last_space: str = "cosine"
        want = bool(int(os.getenv("RAG_USE_RERANK", "1")))
        if force_reranker is not None:
            want = bool(force_reranker)
        self._reranker = None
        if want and CrossEncoder is not None:
            dev = "cuda" if torch.cuda.is_available() else "cpu"
            global _RERANKER_SINGLETON, _RERANKER_DEVICE
            if _RERANKER_SINGLETON is None or _RERANKER_DEVICE != dev:
                ce = CrossEncoder("BAAI/bge-reranker-v2-m3", device=dev, max_length=512)
                if dev == "cuda" and os.getenv("RAG_RERANK_FP16", "1") == "1":
                    try:
                        ce.model.half()
                    except Exception:
                        pass
                _RERANKER_SINGLETON = ce
                _RERANKER_DEVICE = dev
            self._reranker = _RERANKER_SINGLETON

    # ---------- common ----------
    def _attach_embeddings(self, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        ids = [str(it.get("id") or "") for it in items if it.get("id")]
        if not ids:
            return items

        coll = get_collection()
        res = coll.get(ids=ids, include=["embeddings"])

        # ❌ 금지: res.get("embeddings") or []
        # ✅ 명시적 None 체크 + 리스트화
        res_ids = res.get("ids")
        embs = res.get("embeddings")

        # 일부 구현은 np.ndarray로 반환할 수 있음 → 리스트로 변환
        if res_ids is None:
            res_ids = []
        elif hasattr(res_ids, "tolist"):
            res_ids = res_ids.tolist()

        if embs is None:
            embs = []
        elif hasattr(embs, "tolist"):  # np.ndarray 등
            embs = embs.tolist()

        # 길이 불일치 방어
        n = min(len(res_ids), len(embs))
        emap = {str(res_ids[i]): embs[i] for i in range(n)}

        for it in items:
            _id = str(it.get("id") or "")
            if _id in emap:
                it["embedding"] = emap[_id]
        return items


    def _rrf_merge(self, ranked_lists: List[List[Dict[str, Any]]], K: int = 60) -> List[Dict[str, Any]]:
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
        merged.sort(key=lambda it: score.get(str(it.get("id") or ""), 0.0), reverse=True)
        return merged

    def _mmr(self, q: str, items: List[Dict[str, Any]], k: int, lam: float = 0.5) -> List[Dict[str, Any]]:
        if not items:
            return items

        vecs: List[np.ndarray] = []
        use_db = True
        for it in items:
            emb = it.get("embedding")
            if emb is None:
                use_db = False
                break
            vecs.append(np.asarray(emb, dtype="float32"))

        if use_db and vecs:
            cvs_np = np.vstack(vecs)
        else:
            texts = [(it.get("text") or "") for it in items]
            cvs_np = np.array(embed_passages(texts))

        qv_np = np.array(embed_queries([q]))[0]

        device = "cuda" if torch.cuda.is_available() else "cpu"
        cvs = torch.from_numpy(cvs_np).to(device)
        qv  = torch.from_numpy(qv_np).to(device)

        n = cvs.shape[0]
        if n <= k:
            return items[:k]

        qn = torch.norm(qv) + 1e-8
        cn = torch.norm(cvs, dim=1) + 1e-8
        sim_q = (cvs @ qv) / (qn * cn)

        selected: List[int] = []
        mask = torch.zeros(n, dtype=torch.bool, device=device)
        while len(selected) < k:
            if not selected:
                i = int(torch.argmax(sim_q).item())
            else:
                sel = cvs[torch.tensor(selected, device=device)]
                seln = torch.norm(sel, dim=1) + 1e-8
                sim_div = (cvs @ sel.T) / (cn.unsqueeze(1) * seln.unsqueeze(0))
                sim_div = sim_div.max(dim=1).values
                mmr = lam * sim_q - (1 - lam) * sim_div
                mmr[mask] = -1e9
                i = int(torch.argmax(mmr).item())
            selected.append(i); mask[i] = True
            if mask.all():
                break

        return [items[i] for i in selected]

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

    def _expand_same_doc(self, q: str, items: List[Dict[str, Any]], per_doc: int = 2) -> List[Dict[str, Any]]:
        """상위 문서(doc_id)의 다른 섹션/청크를 몇 개 더 끌어와 컨텍스트를 두텁게."""
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
            # 빈 쿼리 대신 원 쿼리를 사용해 거리/점수 일관성 유지
            res = chroma_search(
                query=q, n=per_doc * 6, where={"doc_id": did},
                include_docs=True, include_metas=True, include_ids=True,
                include_distances=True
            )
            ext = flatten_chroma_result(res)
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
                extras.append(e); taken_per[did] = cnt + 1
        return items + extras

    def _conf(self, items: List[Dict[str, Any]]) -> float:
        if not items:
            return 0.0
        ce = [it.get("_ce") for it in items[:5] if it.get("_ce") is not None]
        if ce:
            x = np.array(ce, dtype=np.float32)
            x = x - x.max()
            p = np.exp(x); p = p / (p.sum() + 1e-8)
            return float(p[0])
        arr = [it.get("score", 0.0) for it in items[:3]]
        if not arr:
            return 0.0
        lo, hi = min(arr), max(arr)
        if hi - lo < 1e-6:
            return float(arr[0])
        return float(sum((a - lo) / (hi - lo) for a in arr) / len(arr))

    # ---------- strategies ----------
    def _retrieve_baseline(self, q: str, *, k: int, where: Optional[Dict[str, Any]],
                       candidate_k: Optional[int], use_mmr: bool, lam: float) -> List[Dict[str, Any]]:
        fetch_k   = candidate_k or _env_int("RAG_FETCH_K", 160)
        res = chroma_search(
            query=q, n=fetch_k, where=where,
            include_docs=True, include_metas=True, include_ids=True,
            include_distances=True
        )
        self._last_space = (res.get("space") or "cosine").lower()
        dedup0 = self._dedup_and_score(flatten_chroma_result(res))

        cap_list      = _env_ints("RAG_TITLE_CAP",   [2])
        prek_list     = _env_ints("RAG_MMR_PRE_K",   [120])
        mmrk_list     = _env_ints("RAG_MMR_K",       [max(k * 4, 40)])
        rerank_in_lst = _env_ints("RAG_RERANK_IN",   [24])
        ENS_MAX       = int(os.getenv("RAG_ENS_MAX_COMBOS", "12"))

        pools: List[List[Dict[str, Any]]] = []
        if not use_mmr:
            tried = 0
            for cap in cap_list:
                if tried >= ENS_MAX:
                    break
                dedup = _cap_by_title(dedup0, cap=cap)
                pools.append(dedup[:max(k * 6, 72)])
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
                pre_base = self._attach_embeddings(dedup[:prek_max])
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
                        pools.append(self._mmr(q, pre, k=mmrk, lam=lam))
                        tried += 1

        merged = self._rrf_merge(pools, K=60) if len(pools) > 1 else (pools[0] if pools else [])
        merged = self._dedup_and_score(merged)

        rerank_in = min(max(rerank_in_lst), len(merged))
        if self._reranker and rerank_in > 0:
            return self._rerank(q, merged[:rerank_in], k)
        else:
            return merged[:k]


    def _retrieve_chroma_only(self, q: str, *, k: int, where: Optional[Dict[str, Any]],
                          use_mmr: bool, lam: float) -> List[Dict[str, Any]]:
        qvars = _expand_queries(q)

        base_n = _env_int("RAG_FETCH_K", max(k * 8, 80))
        aux_n  = _env_int("RAG_FETCH_K_AUX", max(k * 4, 40))

        lists: List[List[Dict[str, Any]]] = []
        resA = chroma_search(
            query=q, n=base_n, where=where,
            include_docs=True, include_metas=True, include_ids=True,
            include_distances=True
        )
        self._last_space = (resA.get("space") or "cosine").lower()
        lists.append(flatten_chroma_result(resA))

        for qq in qvars:
            if qq == q:
                continue
            res = chroma_search(
                query=qq, n=aux_n, where=where,
                include_docs=True, include_metas=True, include_ids=True,
                include_distances=True
            )
            lists.append(flatten_chroma_result(res))

        # 1) 멀티쿼리 결합
        items = self._rrf_merge(lists, K=60)
        base  = self._dedup_and_score(items)

        # 2) 리스트형 하이퍼 파라미터 읽기
        cap_list      = _env_ints("RAG_TITLE_CAP",   [2])
        prek_list     = _env_ints("RAG_MMR_PRE_K",   [160])
        mmrk_list     = _env_ints("RAG_MMR_K",       [max(k * 4, 40)])
        rerank_in_lst = _env_ints("RAG_RERANK_IN",   [24])
        ENS_MAX       = int(os.getenv("RAG_ENS_MAX_COMBOS", "12"))

        pools: List[List[Dict[str, Any]]] = []

        if not use_mmr:
            # MMR OFF: title_cap 여러 값으로 풀 만들어서 합치기
            tried = 0
            for cap in cap_list:
                if tried >= ENS_MAX:
                    break
                dedup = _cap_by_title(base, cap=cap)
                pools.append(dedup[:max(k * 6, 72)])
                tried += 1
        else:
            # MMR ON: cap × prek × mmrk 조합 전부
            tried = 0
            for cap in cap_list:
                if tried >= ENS_MAX:
                    break
                dedup = _cap_by_title(base, cap=cap)
                if not dedup:
                    continue
                # 임베딩은 한 번만 붙이고 슬라이스 재활용
                prek_max = min(max(prek_list), len(dedup))
                pre_base = self._attach_embeddings(dedup[:prek_max])

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
                        pools.append(self._mmr(q, pre, k=mmrk, lam=lam))
                        tried += 1

        # 3) 조합 풀을 RRF로 앙상블 → 스코어/중복 정리
        merged = self._rrf_merge(pools, K=60) if len(pools) > 1 else (pools[0] if pools else [])
        merged = self._dedup_and_score(merged)

        # 4) 리랭커 컷도 리스트 지원(최댓값 사용)
        rerank_in = min(max(rerank_in_lst), len(merged))
        if self._reranker and rerank_in > 0:
            return self._rerank(q, merged[:rerank_in], k)
        else:
            return merged[:k]


    # ---------- public ----------
    def retrieve_docs(self, q: str, *, k: int = 6, where: Optional[Dict[str, Any]] = None,
                      candidate_k: Optional[int] = None, use_mmr: bool = True,
                      lam: float = 0.5, strategy: str = "baseline") -> List[Dict[str, Any]]:
        if strategy == "baseline":
            return self._retrieve_baseline(q, k=k, where=where, candidate_k=candidate_k, use_mmr=use_mmr, lam=lam)
        elif strategy in ("chroma_only", "multiq"):
            return self._retrieve_chroma_only(q, k=k, where=where, use_mmr=use_mmr, lam=lam)
        else:
            raise ValueError(f"unknown strategy: {strategy}")

    def _quota_by_section(self, items: List[Dict[str, Any]], quota: Dict[str, int], k: int) -> List[Dict[str, Any]]:
        out, used, rest = [], {s: 0 for s in quota}, []
        for it in items:
            sec = (it.get("metadata") or {}).get("section") or ""
            if sec in quota and used[sec] < quota[sec]:
                out.append(it); used[sec] += 1
            else:
                rest.append(it)
            if len(out) >= k:
                return out[:k]
        out += rest
        return out[:k]

    def build_context(self, docs: List[Dict[str, Any]], *, per_doc_limit: int = 1200, hard_limit: int = 6000) -> str:
        chunks: List[str] = []
        total = 0
        for i, d in enumerate(docs, 1):
            meta = d.get("metadata") or {}
            title = meta.get("seed_title") or meta.get("parent") or meta.get("title") or ""
            section = meta.get("section") or ""
            body = (d.get("text") or "").strip()
            if not body:
                continue
            if per_doc_limit and len(body) > per_doc_limit:
                body = body[:per_doc_limit]
            piece = f"[S{i}] {title} · {section}\n{body}"
            if hard_limit and total + len(piece) > hard_limit:
                break
            chunks.append(piece)
            total += len(piece)
        return "\n\n".join(chunks)

    def _render_prompt(self, question: str, context: str) -> str:
        return (
            "규칙:\n"
            "1) 아래 <컨텍스트>만 근거로 한국어로 간결히 답하라.\n"
            "2) 문장 끝에 [S#] 표기로 근거 조각을 1~2개 인용하라.\n"
            "3) 컨텍스트에 없으면 '모르겠다'고 답하라. 추측 금지.\n"
            "4) 수치/고유명사는 컨텍스트 표기 그대로 사용.\n\n"
            f"<컨텍스트>\n{context}\n\n"
            f"<질문>\n{question}\n"
        )

    async def ask(self, q: str, *, k: int = 6, where: Optional[Dict[str, Any]] = None,
                  candidate_k: Optional[int] = None, use_mmr: bool = True,
                  lam: float = 0.5, max_tokens: int = 512, temperature: float = 0.2,
                  preview_chars: int = 600, strategy: str = "baseline") -> Dict[str, Any]:
        t_total0 = time.perf_counter()

        t0 = time.perf_counter()
        docs = self.retrieve_docs(q, k=k, where=where, candidate_k=candidate_k, use_mmr=use_mmr, lam=lam, strategy=strategy)
        t_retr_ms = (time.perf_counter() - t0) * 1000.0

        conf = self._conf(docs)
        min_conf = _env_float("RAG_MIN_CONF", float(os.getenv("RAG_MIN_CONF", "0.20")))
        if conf < min_conf:
            resp = RAGQueryResponse(question=q, answer="컨텍스트가 불충분합니다. 더 구체적인 단서가 필요합니다.", documents=[]).model_dump()
            resp["metrics"] = {
                "k": k, "strategy": strategy, "use_reranker": bool(self._reranker),
                "retriever_ms": round(t_retr_ms, 1), "expand_ms": 0.0, "llm_ms": 0.0,
                "total_ms": round((time.perf_counter() - t_total0) * 1000.0, 1),
                "conf": round(conf, 4),
                "dup_rate_doc": dup_rate(keys_from_docs(docs, by="doc")),
                "dup_rate_title": dup_rate(keys_from_docs(docs, by="title")),
                "device": "cuda" if torch.cuda.is_available() else "cpu",
                "retrieved": len(docs),
            }
            return resp

        t1_0 = time.perf_counter()
        docs = self._expand_same_doc(q, docs, per_doc=2)
        t_expand_ms = (time.perf_counter() - t1_0) * 1000.0

        if os.getenv("RAG_USE_SECTION_QUOTA", "0") == "1":
            quota = {"요약": 2, "본문": 4}
            docs = self._quota_by_section(docs, quota, k)

        context = self.build_context(docs)
        if not context:
            resp = RAGQueryResponse(question=q, answer="관련 컨텍스트가 없습니다.", documents=[]).model_dump()
            resp["metrics"] = {
                "k": k, "strategy": strategy, "use_reranker": bool(self._reranker),
                "retriever_ms": round(t_retr_ms, 1), "expand_ms": round(t_expand_ms, 1),
                "llm_ms": 0.0, "total_ms": round((time.perf_counter() - t_total0) * 1000.0, 1),
                "conf": round(conf, 4),
                "dup_rate_doc": dup_rate(keys_from_docs(docs, by="doc")),
                "dup_rate_title": dup_rate(keys_from_docs(docs, by="title")),
                "device": "cuda" if torch.cuda.is_available() else "cpu",
                "retrieved": len(docs),
            }
            return resp

        prompt = self._render_prompt(q, context)
        messages = [
            {"role": "system", "content": "답변은 한국어. 제공된 컨텍스트만 사용. 모르면 모른다고 답하라."},
            {"role": "user", "content": prompt},
        ]
        try:
            t_llm0 = time.perf_counter()
            out = await self.chat(messages, max_tokens=max_tokens, temperature=temperature)
            t_llm_ms = (time.perf_counter() - t_llm0) * 1000.0
        except Exception as e:
            resp = RAGQueryResponse(question=q, answer=f"LLM 호출 실패: {e}", documents=[]).model_dump()
            resp["metrics"] = {
                "k": k, "strategy": strategy, "use_reranker": bool(self._reranker),
                "retriever_ms": round(t_retr_ms, 1), "expand_ms": round(t_expand_ms, 1),
                "llm_ms": 0.0, "total_ms": round((time.perf_counter() - t_total0) * 1000.0, 1),
                "conf": round(conf, 4),
                "dup_rate_doc": dup_rate(keys_from_docs(docs, by="doc")),
                "dup_rate_title": dup_rate(keys_from_docs(docs, by="title")),
                "device": "cuda" if torch.cuda.is_available() else "cpu",
                "retrieved": len(docs),
            }
            return resp

        items: List[DocumentItem] = []
        space = self._last_space
        for d in docs:
            meta = d.get("metadata") or {}
            text = (d.get("text") or "").strip()
            if not text:
                continue
            score = d.get("score")
            if score is None:
                score = to_similarity(d.get("distance"), space=space)
            items.append(
                DocumentItem(
                    id=str(d.get("id") or ""),
                    page_id=meta.get("page_id"),
                    chunk_id=meta.get("chunk_id"),
                    url=meta.get("url"),
                    title=meta.get("title"),
                    section=meta.get("section"),
                    seed=meta.get("seed_title") or meta.get("parent") or meta.get("title"),
                    score=float(score) if score is not None else None,
                    text=text[:1200],
                )
            )
        resp = RAGQueryResponse(question=q, answer=out, documents=items).model_dump()
        resp["metrics"] = {
            "k": k, "strategy": strategy, "use_reranker": bool(self._reranker),
            "retriever_ms": round(t_retr_ms, 1), "expand_ms": round(t_expand_ms, 1),
            "llm_ms": round(t_llm_ms, 1), "total_ms": round((time.perf_counter() - t_total0) * 1000.0, 1),
            "conf": round(conf, 4),
            "dup_rate_doc": dup_rate(keys_from_docs(docs, by="doc")),
            "dup_rate_title": dup_rate(keys_from_docs(docs, by="title")),
            "device": "cuda" if torch.cuda.is_available() else "cpu",
            "retrieved": len(items),
        }
        return resp
