from __future__ import annotations

import random
from typing import Any, Dict, List, Optional

from .utils import _env_float, _env_int

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


def base_metrics(
    *,
    k: int,
    strategy: str,
    use_reranker: bool,
    retriever_ms: float,
    expand_ms: float,
    llm_ms: float,
    total_ms: float,
    conf: float,
    docs: List[Dict[str, Any]],
    device: str,
    parser_mode: str,
    parsed_query: str,
    retrieved: Optional[int] = None,
) -> Dict[str, Any]:
    return {
        "k": k,
        "strategy": strategy,
        "use_reranker": use_reranker,
        "retriever_ms": round(retriever_ms, 1),
        "expand_ms": round(expand_ms, 1),
        "llm_ms": round(llm_ms, 1),
        "total_ms": round(total_ms, 1),
        "conf": round(conf, 4),
        "dup_rate_doc": dup_rate(keys_from_docs(docs, by="doc")),
        "dup_rate_title": dup_rate(keys_from_docs(docs, by="title")),
        "device": device,
        "retrieved": int(retrieved if retrieved is not None else len(docs)),
        "query_parser": parser_mode,
        "parsed_query": parsed_query,
    }


def eval_query_metrics(
    service,
    q: str,
    *,
    k: int,
    where: Optional[Dict[str, Any]],
    candidate_k: Optional[int],
    use_mmr: bool,
    lam: float,
    strategy: str,
) -> Dict[str, Any]:
    docs = service.retrieve_docs(
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
        "conf": round(service._conf(docs), 4),
        "dup_rate_doc": dup_rate(keys_from_docs(docs, by="doc")),
        "dup_rate_title": dup_rate(keys_from_docs(docs, by="title")),
    }


def should_eval_query_parse() -> bool:
    if _env_int("RAG_QUERY_PARSE_EVAL", 0) != 1:
        return False
    rate = _env_float("RAG_QUERY_PARSE_EVAL_RATE", 1.0)
    if rate >= 1.0:
        return True
    if rate <= 0.0:
        return False
    return random.random() < rate


async def maybe_attach_query_parse_eval(
    service,
    parser,
    metrics: Dict[str, Any],
    *,
    original_q: str,
    parsed_q: str,
    parsed_mode: str,
    k: int,
    where: Optional[Dict[str, Any]],
    candidate_k: Optional[int],
    use_mmr: bool,
    lam: float,
    strategy: str,
) -> None:
    """
    Adds metrics["query_parse_eval"] with retrieval-only comparison:
    - regex query vs llm query
    NOTE: This can be expensive; it's gated by should_eval_query_parse().
    """
    if not should_eval_query_parse():
        return

    regex_q = parser.parse_regex(original_q)

    # LLM parse 중복 방지: 이미 llm 모드로 파싱했다면 parsed_q 재사용
    if parsed_mode == "llm":
        llm_q = parsed_q
    else:
        llm_q = await parser.parse_llm(original_q)

    metrics["query_parse_eval"] = {
        "regex": eval_query_metrics(
            service,
            regex_q,
            k=k,
            where=where,
            candidate_k=candidate_k,
            use_mmr=use_mmr,
            lam=lam,
            strategy=strategy,
        ),
        "llm": eval_query_metrics(
            service,
            llm_q,
            k=k,
            where=where,
            candidate_k=candidate_k,
            use_mmr=use_mmr,
            lam=lam,
            strategy=strategy,
        ),
    }


__all__ = [
    "base_metrics",
    "eval_query_metrics",
    "maybe_attach_query_parse_eval",
    "should_eval_query_parse",
]
