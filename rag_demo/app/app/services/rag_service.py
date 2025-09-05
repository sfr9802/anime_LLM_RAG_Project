# app/app/services/rag_service.py
from __future__ import annotations
from typing import Any, Dict, List, Optional
import os, re, unicodedata, time
import numpy as np
import torch

try:
    from sentence_transformers import CrossEncoder  # pip install sentence-transformers
except Exception:
    CrossEncoder = None  # 미설치 시 자동 비활성

from app.app.infra.vector.chroma_store import search as chroma_search
from app.app.services.adapters import flatten_chroma_result
from app.app.domain.embeddings import embed_queries, embed_passages
from app.app.infra.llm.provider import get_chat
from app.app.configure import config

# 모델 스키마 (표준 경로 우선)
try:
    from app.app.domain.models.document_model import DocumentItem
    from app.app.domain.models.query_model import RAGQueryResponse
except Exception:
    from app.app.models.document_model import DocumentItem
    from app.app.models.query_model import RAGQueryResponse

# 벡터 스코어 → [0,1] 유사도 변환 (vector 메트릭)
from app.app.infra.vector.metrics import to_similarity

# 품질 메트릭(dup_rate, 키 추출)
try:
    from app.app.metrics.quality import dup_rate, keys_from_docs
except Exception:
    # metrics/quality.py가 없다면 안전 폴백
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

# --- 퍼지 매칭(rapidfuzz 있으면 사용, 없으면 difflib 폴백) --------------------------
try:
    from rapidfuzz import fuzz as _rf_fuzz
    def _fuzzy(a: str, b: str) -> float:
        return _rf_fuzz.partial_ratio(a, b) / 100.0
except Exception:
    from difflib import SequenceMatcher
    def _fuzzy(a: str, b: str) -> float:
        return SequenceMatcher(None, a, b).ratio()

# --- 간단 정규화/쿼리 확장 ---------------------------------------------------------
def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s).lower()
    return re.sub(r"[\s\W_]+", "", s, flags=re.UNICODE)

_DEFAULT_ALIAS_MAP = {
    "방도리": ["BanG Dream!", "bang dream", "bandori", "girls band party", "bangdream"],
    "귀칼": ["귀멸의 칼날"],
    "5등분의 신부": ["오등분의 신부", "The Quintessential Quintuplets", "5-toubun no hanayome", "五等分の花嫁"],
}
_ALIAS_MAP = getattr(config, "ALIAS_MAP", None) or _DEFAULT_ALIAS_MAP

def _expand_queries(q: str) -> List[str]:
    """원문 + 정규화 + 간단 별칭치환."""
    out = [q]
    nq = _norm(q)
    if nq != q:
        out.append(nq)
    for k, vs in _ALIAS_MAP.items():
        if k in q:
            out.extend(vs)
    # 고유화
    uniq, seen = [], set()
    for s in out:
        s = (s or "").strip()
        if len(s) < 2: continue
        if s in seen: continue
        seen.add(s); uniq.append(s)
    return uniq

def _title_from_meta(meta: Dict[str, Any]) -> str:
    return meta.get("seed_title") or meta.get("parent") or meta.get("title") or ""

def _title_boost(item: Dict[str, Any], qvars: List[str]) -> float:
    """메타 타이틀 vs 확장쿼리 간 퍼지 스코어(0..1)."""
    t = _title_from_meta(item.get("metadata") or {})
    if not t:
        return 0.0
    tn = _norm(t)
    best = 0.0
    for s in qvars:
        sn = _norm(s)
        best = max(best, _fuzzy(tn, sn))
    return float(best)


class RagService:
    def __init__(self):
        self.chat = get_chat()
        self._last_space: str = "cosine"  # 최근 검색 벡터 공간 저장(점수 변환에 필요)
        # 리랭커 세팅 (환경변수로 온/오프)
        self._use_reranker = bool(int(os.getenv("RAG_USE_RERANK", "1")))
        self._reranker = None
        if self._use_reranker and CrossEncoder is not None:
            dev = "cuda" if torch.cuda.is_available() else "cpu"
            # 한국어 포함 멀티링구얼 성능/가성비 좋음
            self._reranker = CrossEncoder("BAAI/bge-reranker-v2-m3", device=dev, max_length=512)

    # ------------------- 공통 유틸 -------------------
    def _mmr(self, q: str, items: List[Dict[str, Any]], k: int, lam: float = 0.5) -> List[Dict[str, Any]]:
        """GPU(torch)로 MMR 계산."""
        if not items:
            return items
        texts = [(it.get("text") or "") for it in items]

        # 임베딩 -> numpy -> torch
        cvs_np = np.array(embed_passages(texts))          # (n, d)
        qv_np  = np.array(embed_queries([q]))[0]          # (d,)

        device = "cuda" if torch.cuda.is_available() else "cpu"
        cvs = torch.from_numpy(cvs_np).to(device)
        qv  = torch.from_numpy(qv_np).to(device)

        n = cvs.shape[0]
        if n <= k:
            return items[:k]

        # cosine sim
        qn = torch.norm(qv) + 1e-8
        cn = torch.norm(cvs, dim=1) + 1e-8
        sim_q = (cvs @ qv) / (qn * cn)  # (n,)

        selected: List[int] = []
        mask = torch.zeros(n, dtype=torch.bool, device=device)
        while len(selected) < k:
            if not selected:
                i = int(torch.argmax(sim_q).item())
            else:
                sel = cvs[torch.tensor(selected, device=device)]
                seln = torch.norm(sel, dim=1) + 1e-8
                # (n, s)
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
        """doc_id(또는 title+section) 기준 중복 제거 + score 보정."""
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

    # ───────────────── 리랭크/확장/컨피던스 ─────────────────
    def _rerank(self, q: str, items: List[Dict[str, Any]], k: int) -> List[Dict[str, Any]]:
        """CrossEncoder로 최종 재정렬."""
        if not self._reranker or not items:
            return items[:k]
        pairs = [(q, (it.get("text") or "")[:800]) for it in items]  # 지나친 길이 컷
        bs = int(os.getenv("RAG_RERANK_BATCH", "64"))
        scores = self._reranker.predict(pairs, batch_size=bs, convert_to_numpy=True)
        for it, s in zip(items, scores):
            it["_ce"] = float(s)
        items.sort(key=lambda x: x.get("_ce", 0.0), reverse=True)
        return items[:k]

    def _expand_same_doc(self, items: List[Dict[str, Any]], per_doc: int = 2) -> List[Dict[str, Any]]:
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
        for did in doc_ids[:3]:  # 상위 3개 문서만 확장
            res = chroma_search(
                query="", n=per_doc * 6, where={"doc_id": did},
                include_docs=True, include_metas=True, include_ids=True, include_distances=True
            )
            ext = flatten_chroma_result(res)
            # 요약/본문 우선
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
        """상위 몇 개의 CE/유사도 평균으로 간단 컨피던스(0..1)."""
        if not items:
            return 0.0
        arr = [it.get("_ce", it.get("score", 0.0)) for it in items[:3]]
        if not arr:
            return 0.0
        lo, hi = min(arr), max(arr)
        if hi - lo < 1e-6:
            return float(arr[0])
        return float(sum((a - lo) / (hi - lo) for a in arr) / len(arr))

    # ------------------- 전략별 검색 -------------------
    def _retrieve_baseline(
        self, q: str, *, k: int, where: Optional[Dict[str, Any]],
        candidate_k: Optional[int], use_mmr: bool, lam: float
    ) -> List[Dict[str, Any]]:
        """단일 쿼리 경로. 후보 폭을 넓혀 MMR→(CE) 적용."""
        cand = max(k * 10, 120) if use_mmr or self._reranker else (candidate_k or max(k * 5, 40))
        res = chroma_search(
            query=q, n=cand, where=where,
            include_docs=True, include_metas=True, include_ids=True, include_distances=True
        )
        self._last_space = (res.get("space") or "cosine").lower()
        items = flatten_chroma_result(res)
        dedup = self._dedup_and_score(items)

        if use_mmr:
            pool = self._mmr(q, dedup[:max(k * 6, 60)], k=max(k * 4, 40), lam=lam)
        else:
            pool = dedup[:max(k * 10, 80)]

        return self._rerank(q, pool, k) if self._reranker else pool[:k]

    def _retrieve_chroma_only(
        self, q: str, *, k: int, where: Optional[Dict[str, Any]],
        use_mmr: bool, lam: float
    ) -> List[Dict[str, Any]]:
        """
        Chroma만으로 성능 보강:
        - 멀티쿼리(원문+정규화+간단 별칭) 병렬 조회 → 유니온
        - 타이틀 퍼지부스트(score와 가중 합성) → (MMR|CE)
        """
        qvars = _expand_queries(q)

        base_n = max(k * 6, 60)
        resA = chroma_search(
            query=q, n=base_n, where=where,
            include_docs=True, include_metas=True, include_ids=True, include_distances=True
        )
        self._last_space = (resA.get("space") or "cosine").lower()
        items = flatten_chroma_result(resA)

        add_n = max(k * 3, 30)
        for qq in qvars:
            if qq == q:
                continue
            res = chroma_search(
                query=qq, n=add_n, where=where,
                include_docs=True, include_metas=True, include_ids=True, include_distances=True
            )
            items += flatten_chroma_result(res)

        dedup = self._dedup_and_score(items)

        W_SIM = getattr(config, "RAG_W_SIM", 0.8)
        W_TITLE = getattr(config, "RAG_W_TITLE", 0.2)
        for it in dedup:
            boost = _title_boost(it, qvars)
            it["_combo"] = W_SIM * float(it.get("score") or 0.0) + W_TITLE * boost
        dedup.sort(key=lambda x: x.get("_combo", 0.0), reverse=True)

        if use_mmr:
            pool = self._mmr(q, dedup[:max(k * 8, 80)], k=max(k * 4, 40), lam=lam)
        else:
            pool = dedup[:max(k * 12, 120)]

        return self._rerank(q, pool, k) if self._reranker else pool[:k]

    # ------------------- 공개 API -------------------
    def retrieve_docs(
        self,
        q: str,
        *,
        k: int = 6,
        where: Optional[Dict[str, Any]] = None,
        candidate_k: Optional[int] = None,
        use_mmr: bool = True,
        lam: float = 0.5,
        strategy: str = "baseline",  # 'baseline' | 'chroma_only' | 'multiq'
    ) -> List[Dict[str, Any]]:
        if strategy == "baseline":
            return self._retrieve_baseline(q, k=k, where=where, candidate_k=candidate_k, use_mmr=use_mmr, lam=lam)
        elif strategy in ("chroma_only", "multiq"):
            return self._retrieve_chroma_only(q, k=k, where=where, use_mmr=use_mmr, lam=lam)
        else:
            raise ValueError(f"unknown strategy: {strategy}")

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

    async def ask(
        self,
        q: str,
        *,
        k: int = 6,
        where: Optional[Dict[str, Any]] = None,
        candidate_k: Optional[int] = None,
        use_mmr: bool = True,
        lam: float = 0.5,
        max_tokens: int = 512,
        temperature: float = 0.2,
        preview_chars: int = 600,
        strategy: str = "baseline",
    ) -> Dict[str, Any]:
        t_total0 = time.perf_counter()

        # 1) 문서 검색 (+ latency)
        t0 = time.perf_counter()
        docs = self.retrieve_docs(q, k=k, where=where, candidate_k=candidate_k, use_mmr=use_mmr, lam=lam, strategy=strategy)
        t_retr_ms = (time.perf_counter() - t0) * 1000.0

        # 1.5) 동일 문서 확장 (+ latency)
        t1_0 = time.perf_counter()
        docs = self._expand_same_doc(docs, per_doc=2)
        t_expand_ms = (time.perf_counter() - t1_0) * 1000.0

        # 컨피던스
        conf = self._conf(docs)
        min_conf = float(os.getenv("RAG_MIN_CONF", "0.20"))
        if conf < min_conf:
            resp = RAGQueryResponse(question=q, answer="컨텍스트가 불충분합니다. 더 구체적인 단서가 필요합니다.", documents=[]).model_dump()
            resp["metrics"] = {
                "k": k, "strategy": strategy, "use_reranker": bool(self._reranker),
                "retriever_ms": round(t_retr_ms, 1),
                "expand_ms": round(t_expand_ms, 1),
                "llm_ms": 0.0,
                "total_ms": round((time.perf_counter() - t_total0) * 1000.0, 1),
                "conf": round(conf, 4),
                "dup_rate_doc": dup_rate(keys_from_docs(docs, by="doc")),
                "dup_rate_title": dup_rate(keys_from_docs(docs, by="title")),
            }
            return resp

        context = self.build_context(docs)
        if not context:
            resp = RAGQueryResponse(question=q, answer="관련 컨텍스트가 없습니다.", documents=[]).model_dump()
            resp["metrics"] = {
                "k": k, "strategy": strategy, "use_reranker": bool(self._reranker),
                "retriever_ms": round(t_retr_ms, 1),
                "expand_ms": round(t_expand_ms, 1),
                "llm_ms": 0.0,
                "total_ms": round((time.perf_counter() - t_total0) * 1000.0, 1),
                "conf": round(conf, 4),
                "dup_rate_doc": dup_rate(keys_from_docs(docs, by="doc")),
                "dup_rate_title": dup_rate(keys_from_docs(docs, by="title")),
            }
            return resp

        # 2) 프롬프트 구성 & 호출 (+ LLM latency)
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
                "retriever_ms": round(t_retr_ms, 1),
                "expand_ms": round(t_expand_ms, 1),
                "llm_ms": 0.0,
                "total_ms": round((time.perf_counter() - t_total0) * 1000.0, 1),
                "conf": round(conf, 4),
                "dup_rate_doc": dup_rate(keys_from_docs(docs, by="doc")),
                "dup_rate_title": dup_rate(keys_from_docs(docs, by="title")),
            }
            return resp

        # 3) 문서들을 DocumentItem으로 변환
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

        # 4) 스키마 응답 + 지표
        resp = RAGQueryResponse(question=q, answer=out, documents=items).model_dump()
        resp["metrics"] = {
            "k": k,
            "strategy": strategy,
            "use_reranker": bool(self._reranker),
            "retriever_ms": round(t_retr_ms, 1),
            "expand_ms": round(t_expand_ms, 1),
            "llm_ms": round(t_llm_ms, 1),
            "total_ms": round((time.perf_counter() - t_total0) * 1000.0, 1),
            "conf": round(conf, 4),
            "dup_rate_doc": dup_rate(keys_from_docs(docs, by="doc")),
            "dup_rate_title": dup_rate(keys_from_docs(docs, by="title")),
            "device": "cuda" if torch.cuda.is_available() else "cpu",
            "retrieved": len(items),
        }
        return resp
