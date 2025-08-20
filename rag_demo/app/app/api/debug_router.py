# api/debug.py
from fastapi import APIRouter, Query, Body
from pydantic import BaseModel
from typing import Any, Dict, List, Optional, Literal
from services.retrieval_service import retrieve as svc_retrieve
from services.eval_service import evaluate_hit as svc_evaluate_hit

# ▼ 추가 import
from services.search_service import SearchService
from services.rag_service import RagService
from infra.llm.local_llm_client import chat
from configure import config

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

# 1) LLM 핑 (최소 통신 테스트)
@router.get("/ping-llm")
async def ping_llm():
    msg = [{"role": "user", "content": "한 줄로만 대답해."}]
    out = await chat(msg, model=config.LLM_MODEL, max_tokens=32, temperature=0.2)
    return {"ok": True, "model": config.LLM_MODEL, "answer": out}

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
        return {"answer": "컨텍스트가 없어 답변 생성을 생략한다.", "sources": [], "model": config.LLM_MODEL}

    prompt = _rag._render_prompt(req.q, context)
    messages = [
        {"role": "system", "content": "답변은 한국어. 제공된 컨텍스트만 사용. 모르면 모른다고 답하라."},
        {"role": "user", "content": prompt},
    ]
    out = await chat(messages, model=config.LLM_MODEL, max_tokens=req.max_tokens, temperature=req.temperature)

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
