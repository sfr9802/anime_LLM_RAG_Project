# app/app/api/debug.py
from __future__ import annotations
from fastapi import APIRouter, Body, Header
from pydantic import BaseModel, Field
from typing import Any, Dict, List, Optional, Literal
import os

from ..services.retrieval_service import retrieve as svc_retrieve
from ..services.eval_service import evaluate_hit as svc_evaluate_hit
from ..services.rag import RagService
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
    chat = get_chat()
    out = await chat([{"role":"user","content":"한 줄로만 대답해."}], max_tokens=32, temperature=0.2)

    provider = getattr(config, "LLM_PROVIDER", "local-http")
    if provider == "openai":
        used_model = getattr(config, "OPENAI_MODEL", os.getenv("OPENAI_MODEL", "openai-default"))
    else:  # local-http or others
        used_model = getattr(config, "LLM_MODEL", os.getenv("LLM_MODEL", "local-model"))

    return {"ok": True, "provider": provider, "model": used_model, "answer": out}

# ---------- RAG 즉석 호출 ----------
_rag = RagService()  # ✅ 인자 없이

class RagAskIn(BaseModel):
    q: str
    section: Optional[str] = None
    k: int = 6
    max_tokens: int = 512
    temperature: float = 0.2
    preview_chars: int = 600

@router.post("/rag-ask")
async def debug_rag_ask(req: RagAskIn):
    # ✅ RagService의 시그니처에 맞춰 호출 (section → where)
    where = {"section": req.section} if req.section else None
    return await _rag.ask(
        q=req.q,
        k=req.k,
        where=where,
        use_mmr=True,
        lam=0.5,
        max_tokens=req.max_tokens,
        temperature=req.temperature,
        preview_chars=req.preview_chars,
    )

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
