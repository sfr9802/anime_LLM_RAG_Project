from __future__ import annotations

"""Main RAG service orchestrating retrieval and answer generation."""

from typing import Any, Dict, List, Optional
import json
import logging
import os
import re
import time
import numpy as np
import torch

try:
    from sentence_transformers import CrossEncoder
except Exception:  # pragma: no cover - dependency optional
    CrossEncoder = None

from app.app.infra.llm.provider import get_chat
from app.app.infra.vector.metrics import to_similarity

try:
    from app.app.domain.models.document_model import DocumentItem
    from app.app.domain.models.query_model import RAGQueryResponse
except Exception:  # pragma: no cover
    from app.app.models.document_model import DocumentItem
    from app.app.models.query_model import RAGQueryResponse

from .utils import _env_float, _env_int
from .expand import _expand_same_doc, _quota_by_section
from .retrieval import retrieve_docs as _retrieve_docs

try:
    from app.app.metrics.quality import dup_rate, keys_from_docs
except Exception:  # pragma: no cover
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


_RERANKER_SINGLETON = None
_RERANKER_DEVICE = None
_LOG = logging.getLogger("rag.query_parse")


class RagService:
    """High level interface used by API layers."""

    def __init__(self, force_reranker: Optional[bool] = None):
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
                    except Exception:  # pragma: no cover
                        pass
                _RERANKER_SINGLETON = ce
                _RERANKER_DEVICE = dev
            self._reranker = _RERANKER_SINGLETON

    # wrappers -----------------------------------------------------------------
    def retrieve_docs(
        self,
        q: str,
        *,
        k: int = 6,
        where: Optional[Dict[str, Any]] = None,
        candidate_k: Optional[int] = None,
        use_mmr: bool = True,
        lam: float = 0.5,
        strategy: str = "baseline",
    ) -> List[Dict[str, Any]]:
        return _retrieve_docs(
            self,
            q,
            k=k,
            where=where,
            candidate_k=candidate_k,
            use_mmr=use_mmr,
            lam=lam,
            strategy=strategy,
        )

    def _expand_same_doc(self, q: str, items: List[Dict[str, Any]], per_doc: int = 2) -> List[Dict[str, Any]]:
        return _expand_same_doc(q, items, per_doc=per_doc)

    def _quota_by_section(self, items: List[Dict[str, Any]], quota: Dict[str, int], k: int) -> List[Dict[str, Any]]:
        return _quota_by_section(items, quota, k)

    # scoring ------------------------------------------------------------------
    def _conf(self, items: List[Dict[str, Any]]) -> float:
        if not items:
            return 0.0
        ce = [it.get("_ce") for it in items[:5] if it.get("_ce") is not None]
        if ce:
            x = np.array(ce, dtype=np.float32)
            x = x - x.max()
            p = np.exp(x)
            p = p / (p.sum() + 1e-8)
            return float(p[0])
        arr = [it.get("score", 0.0) for it in items[:3]]
        if not arr:
            return 0.0
        lo, hi = min(arr), max(arr)
        if hi - lo < 1e-6:
            return float(arr[0])
        return float(sum((a - lo) / (hi - lo) for a in arr) / len(arr))

    # context construction ------------------------------------------------------
    def build_context(
        self,
        docs: List[Dict[str, Any]],
        *,
        per_doc_limit: int = 1200,
        hard_limit: int = 6000,
    ) -> str:
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
        from ...prompt.loader import render_template
        return render_template("rag_prompt", question=question, context=context)

    def _parse_query_regex(self, q: str) -> str:
        cleaned = re.sub(r"[\"'`]+", "", q or "")
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        return cleaned or q

    async def _parse_query_llm(self, q: str) -> str:
        from ...prompt.loader import render_template
        prompt = render_template("query_parse_prompt", user_query=q)
        max_tokens = _env_int("RAG_QUERY_PARSE_MAX_TOKENS", 120)
        temperature = _env_float("RAG_QUERY_PARSE_TEMPERATURE", 0.0)
        try:
            out = await self.chat(
                [
                    {"role": "user", "content": prompt},
                ],
                max_tokens=max_tokens,
                temperature=temperature,
            )
        except Exception:
            _LOG.exception("Query parse failed; falling back to original query.")
            return q

        raw = (out or "").strip()
        if not raw:
            _LOG.info("Query parse returned empty output; falling back.")
            return q
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            left = raw.find("{")
            right = raw.rfind("}")
            if left < 0 or right < 0 or right <= left:
                _LOG.info("Query parse returned non-JSON output; falling back.")
                return q
            try:
                data = json.loads(raw[left : right + 1])
            except json.JSONDecodeError:
                _LOG.info("Query parse returned invalid JSON; falling back.")
                return q

        parsed = (data.get("query") or "").strip()
        if parsed:
            _LOG.info("Query parsed: original=%s parsed=%s", q, parsed)
        else:
            _LOG.info("Query parse produced empty query; falling back.")
        return parsed or q

    async def _parse_query(self, q: str) -> str:
        mode = (os.getenv("RAG_QUERY_PARSER", "regex") or "regex").strip().lower()
        if mode == "llm":
            return await self._parse_query_llm(q)
        return self._parse_query_regex(q)

    def _eval_query_metrics(
        self,
        q: str,
        *,
        k: int,
        where: Optional[Dict[str, Any]],
        candidate_k: Optional[int],
        use_mmr: bool,
        lam: float,
        strategy: str,
    ) -> Dict[str, Any]:
        docs = self.retrieve_docs(
            q,
            k=k,
            where=where,
            candidate_k=candidate_k,
            use_mmr=use_mmr,
            lam=lam,
            strategy=strategy,
        )
        return {
            "query": q,
            "retrieved": len(docs),
            "conf": round(self._conf(docs), 4),
            "dup_rate_doc": dup_rate(keys_from_docs(docs, by="doc")),
            "dup_rate_title": dup_rate(keys_from_docs(docs, by="title")),
        }

    # public -------------------------------------------------------------------
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

        t0 = time.perf_counter()
        parsed_q = await self._parse_query(q)
        docs = self.retrieve_docs(
            parsed_q,
            k=k,
            where=where,
            candidate_k=candidate_k,
            use_mmr=use_mmr,
            lam=lam,
            strategy=strategy,
        )
        t_retr_ms = (time.perf_counter() - t0) * 1000.0

        conf = self._conf(docs)
        min_conf = _env_float("RAG_MIN_CONF", float(os.getenv("RAG_MIN_CONF", "0.20")))
        eval_on = _env_int("RAG_QUERY_PARSE_EVAL", 0) == 1
        if conf < min_conf:
            resp = RAGQueryResponse(
                question=q,
                answer="컨텍스트가 불충분합니다. 더 구체적인 단서가 필요합니다.",
                documents=[],
            ).model_dump()
            resp["metrics"] = {
                "k": k,
                "strategy": strategy,
                "use_reranker": bool(self._reranker),
                "retriever_ms": round(t_retr_ms, 1),
                "expand_ms": 0.0,
                "llm_ms": 0.0,
                "total_ms": round((time.perf_counter() - t_total0) * 1000.0, 1),
                "conf": round(conf, 4),
                "dup_rate_doc": dup_rate(keys_from_docs(docs, by="doc")),
                "dup_rate_title": dup_rate(keys_from_docs(docs, by="title")),
                "device": "cuda" if torch.cuda.is_available() else "cpu",
                "retrieved": len(docs),
            }
            if eval_on:
                regex_q = self._parse_query_regex(q)
                llm_q = await self._parse_query_llm(q)
                resp["metrics"]["query_parse_eval"] = {
                    "regex": self._eval_query_metrics(
                        regex_q,
                        k=k,
                        where=where,
                        candidate_k=candidate_k,
                        use_mmr=use_mmr,
                        lam=lam,
                        strategy=strategy,
                    ),
                    "llm": self._eval_query_metrics(
                        llm_q,
                        k=k,
                        where=where,
                        candidate_k=candidate_k,
                        use_mmr=use_mmr,
                        lam=lam,
                        strategy=strategy,
                    ),
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
                "k": k,
                "strategy": strategy,
                "use_reranker": bool(self._reranker),
                "retriever_ms": round(t_retr_ms, 1),
                "expand_ms": round(t_expand_ms, 1),
                "llm_ms": 0.0,
                "total_ms": round((time.perf_counter() - t_total0) * 1000.0, 1),
                "conf": round(conf, 4),
                "dup_rate_doc": dup_rate(keys_from_docs(docs, by="doc")),
                "dup_rate_title": dup_rate(keys_from_docs(docs, by="title")),
                "device": "cuda" if torch.cuda.is_available() else "cpu",
                "retrieved": len(docs),
            }
            if eval_on:
                regex_q = self._parse_query_regex(q)
                llm_q = await self._parse_query_llm(q)
                resp["metrics"]["query_parse_eval"] = {
                    "regex": self._eval_query_metrics(
                        regex_q,
                        k=k,
                        where=where,
                        candidate_k=candidate_k,
                        use_mmr=use_mmr,
                        lam=lam,
                        strategy=strategy,
                    ),
                    "llm": self._eval_query_metrics(
                        llm_q,
                        k=k,
                        where=where,
                        candidate_k=candidate_k,
                        use_mmr=use_mmr,
                        lam=lam,
                        strategy=strategy,
                    ),
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
        except Exception as e:  # pragma: no cover
            resp = RAGQueryResponse(question=q, answer=f"LLM 호출 실패: {e}", documents=[]).model_dump()
            resp["metrics"] = {
                "k": k,
                "strategy": strategy,
                "use_reranker": bool(self._reranker),
                "retriever_ms": round(t_retr_ms, 1),
                "expand_ms": round(t_expand_ms, 1),
                "llm_ms": 0.0,
                "total_ms": round((time.perf_counter() - t_total0) * 1000.0, 1),
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
                    seed=meta.get("seed_title")
                    or meta.get("parent")
                    or meta.get("title"),
                    score=float(score) if score is not None else None,
                    text=text[:1200],
                )
            )
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
        if eval_on:
            regex_q = self._parse_query_regex(q)
            llm_q = await self._parse_query_llm(q)
            resp["metrics"]["query_parse_eval"] = {
                "regex": self._eval_query_metrics(
                    regex_q,
                    k=k,
                    where=where,
                    candidate_k=candidate_k,
                    use_mmr=use_mmr,
                    lam=lam,
                    strategy=strategy,
                ),
                "llm": self._eval_query_metrics(
                    llm_q,
                    k=k,
                    where=where,
                    candidate_k=candidate_k,
                    use_mmr=use_mmr,
                    lam=lam,
                    strategy=strategy,
                ),
            }
        return resp


__all__ = ["RagService"]
