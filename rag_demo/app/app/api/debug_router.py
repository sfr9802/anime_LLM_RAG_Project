# api/debug.py
from fastapi import APIRouter, Query, Body, Header
from pydantic import BaseModel
from typing import Any, Dict, List, Optional, Literal
from ..services.retrieval_service import retrieve as svc_retrieve
from ..services.eval_service import evaluate_hit as svc_evaluate_hit

# ▼ 추가 import
from ..services.search_service import SearchService
from ..services.rag_service import RagService
from ..infra.llm.clients.local_http_client import chat
from ..configure import config
from ..infra.llm.provider import get_chat

router = APIRouter(prefix="/debug", tags=["debug"])

# 기존 그대로
@router.get("/retrieve")
def debug_retrieve(q: str = Query(..., min_length=1), k: int = 3, include_docs: bool = False):
    return svc_retrieve(q=q, k=k, include_docs=include_docs)

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
        [r.dict() for r in req.goldset],
        k=req.k, mode=req.mode, n_fetch=req.n_fetch
    )
    if "misses" in res and isinstance(res["misses"], list) and len(res["misses"]) > req.limit_misses:
        res["misses"] = res["misses"][:req.limit_misses]
        res["truncated_misses"] = True
    return res

# =========================
# 여기부터 LLM/RAG 디버그
# =========================

@router.get("/ping-llm")
async def ping_llm():
    provider = get_chat()
    out = await provider([{"role":"user","content":"한 줄로만 대답해."}], max_tokens=32, temperature=0.2)
    used_model = {
        "local-http": config.LLM_BASE_URL,
        "local-inproc": "llama-cpp-local",
        "openai": config.OPENAI_MODEL,
    }[config.LLM_PROVIDER]
    return {"ok": True, "provider": config.LLM_PROVIDER, "model": used_model, "answer": out}
# 2) RAG 즉석 호출 (검색→컨텍스트→LLM)
_rag = RagService(search=SearchService())

class RagAskIn(BaseModel):
    q: str
    section: Optional[str] = None
    k: int = 6
    max_tokens: int = 512
    temperature: float = 0.2
    preview_chars: int = 600  # 프롬프트/컨텍스트 미리보기 길이

@router.post("/rag-ask")
async def debug_rag_ask(req: RagAskIn):
    docs = _rag.retrieve_docs(req.q, section=req.section, top_k=req.k)
    context = _rag.build_context(docs)
    if not context:
        return {"answer": "컨텍스트가 없어 답변 생성을 생략한다.", "sources": [], "model": config.LLM_BASE_URL}

    prompt = _rag._render_prompt(req.q, context)
    messages = [
        {"role": "system", "content": "답변은 한국어. 제공된 컨텍스트만 사용. 모르면 모른다고 답하라."},
        {"role": "user", "content": prompt},
    ]
    out = await chat(messages, model=config.LLM_BASE_URL, max_tokens=req.max_tokens, temperature=req.temperature)

    # 소스 요약
    sources: List[Dict[str, Any]] = []
    for d in docs:
        meta = {}
        for k in ("id", "doc_id", "title", "score", "seg_index"):
            v = getattr(d, k, None) if not isinstance(d, dict) else d.get(k)
            if v is not None:
                meta[k] = v
        if meta:
            sources.append(meta)

    return {
        "answer": out,
        "model": config.LLM_MODEL,
        "sources": sources,
        "preview": {
            "context": context[:req.preview_chars],
            "prompt": prompt[:req.preview_chars],
        }
    }
@router.get("/retrieve")
def debug_retrieve(
    q: str = Query(..., min_length=1),
    k: int = Query(6, ge=1, le=100),
    include_docs: bool = Query(False),
    where: dict | None = Query(None),
    candidate_k: int | None = Query(None, ge=1, le=200),
    use_rerank: bool = Query(False),
    use_mmr: bool = Query(False),
    x_trace_id: str | None = Header(default=None),
):
    return svc_retrieve(
        q=q, k=k, include_docs=include_docs,
        where=where, candidate_k=candidate_k,
        use_rerank=use_rerank, use_mmr=use_mmr,
        trace_id=x_trace_id,
    )
