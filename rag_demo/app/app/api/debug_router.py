# app/app/api/debug.py
from __future__ import annotations
from fastapi import APIRouter, Body, Header, HTTPException
from pydantic import BaseModel, Field
from typing import Any, Dict, List, Optional, Literal

from ..services.retrieval_service import retrieve as svc_retrieve
from ..services.eval_service import evaluate_hit as svc_evaluate_hit
from ..services.search_service import SearchService
from ..services.rag_service import RagService
from ..infra.llm.provider import get_chat
from ..configure import config

router = APIRouter(prefix="/debug", tags=["debug"])

# ---------- Retrieve (POST, Body로 dict 수용) ----------
class RetrieveDebugReq(BaseModel):
    q: str = Field(..., min_length=1)
    k: int = 6
    include_docs: bool = False
    where: Optional[Dict[str, Any]] = None
    candidate_k: Optional[int] = None
    use_rerank: bool = False
    use_mmr: bool = False

@router.post("/retrieve")
def debug_retrieve(req: RetrieveDebugReq, x_trace_id: Optional[str] = Header(None)):
    return svc_retrieve(
        q=req.q, k=req.k, include_docs=req.include_docs,
        where=req.where, candidate_k=req.candidate_k,
        use_rerank=req.use_rerank, use_mmr=req.use_mmr,
        trace_id=x_trace_id,
    )

# ---------- Eval ----------
class GoldRow(BaseModel):
    q: str
    gold: Dict[str, Any]

class EvalReq(BaseModel):
    k: int = 3
    mode: Literal["page","title","chunk"] = "page"
    n_fetch: Optional[int] = None
    goldset: List[GoldRow]
    limit_misses: int = 50

@router.post("/eval_hit")
def debug_eval_hit(req: EvalReq = Body(...)):
    res = svc_evaluate_hit(
        [r.model_dump() for r in req.goldset],
        k=req.k, mode=req.mode, n_fetch=req.n_fetch
    )
    if "misses" in res and isinstance(res["misses"], list) and len(res["misses"]) > req.limit_misses:
        res["misses"] = res["misses"][:req.limit_misses]
        res["truncated_misses"] = True
    return res

# ---------- LLM Ping ----------
@router.get("/ping-llm")
async def ping_llm():
    provider = get_chat()
    out = await provider([{"role":"user","content":"한 줄로만 대답해."}], max_tokens=32, temperature=0.2)
    used_model = {
        "local-http": getattr(config, "LLM_BASE_URL", "local-http"),
        "local-inproc": "llama-cpp-local",
        "openai": getattr(config, "OPENAI_MODEL", "openai-default"),
    }.get(getattr(config, "LLM_PROVIDER", "local-http"), "unknown")
    return {"ok": True, "provider": config.LLM_PROVIDER, "model": used_model, "answer": out}

# ---------- RAG 즉석 호출 ----------
_rag = RagService(search=SearchService())  # 간단히 전역 싱글톤

class RagAskIn(BaseModel):
    q: str
    section: Optional[str] = None
    k: int = 6
    max_tokens: int = 512
    temperature: float = 0.2
    preview_chars: int = 600

@router.post("/rag-ask")
async def debug_rag_ask(req: RagAskIn):
    docs = _rag.retrieve_docs(req.q, section=req.section, top_k=req.k)
    context = _rag.build_context(docs)
    if not context:
        return {"answer": "컨텍스트가 없어 답변 생성을 생략한다.", "sources": [], "model": getattr(config, "LLM_BASE_URL", "")}

    prompt = _rag._render_prompt(req.q, context)
    messages = [
        {"role": "system", "content": "답변은 한국어. 제공된 컨텍스트만 사용. 모르면 모른다고 답하라."},
        {"role": "user", "content": prompt},
    ]
    provider = get_chat()
    out = await provider(messages, max_tokens=req.max_tokens, temperature=req.temperature)

    used_model = {
        "local-http": getattr(config, "LLM_BASE_URL", "local-http"),
        "local-inproc": "llama-cpp-local",
        "openai": getattr(config, "OPENAI_MODEL", "openai-default"),
    }.get(getattr(config, "LLM_PROVIDER", "local-http"), "unknown")

    sources: List[Dict[str, Any]] = []
    for d in docs:
        meta: Dict[str, Any] = {}
        for k in ("id", "doc_id", "title", "score", "seg_index", "url", "section"):
            v = getattr(d, k, None) if not isinstance(d, dict) else d.get(k)
            if v is not None:
                meta[k] = v
        if meta:
            sources.append(meta)

    return {
        "answer": out,
        "provider": config.LLM_PROVIDER,
        "model": used_model,
        "sources": sources,
        "preview": {
            "context": context[:req.preview_chars],
            "prompt": prompt[:req.preview_chars],
        }
    }
@router.get("/count")
def debug_count():
    from ..infra.vector.chroma_store import get_collection
    return {"count": get_collection().count()}

@router.get("/peek")
def debug_peek(id: str):
    from ..infra.vector.chroma_store import get_collection
    c = get_collection()
    g = c.get(ids=[id], include=["documents","metadatas"])
    return {"ids": g.get("ids"), "documents": g.get("documents"), "metadatas": g.get("metadatas")}