from fastapi import APIRouter, Header
from typing import Optional, Dict, Any
from app.app.infra.llm.provider import get_chat
from ..configure import config
import os
router = APIRouter(prefix="/recover", tags=["debug"])

@router.get("/health")
async def recover_health(x_trace_id : Optional[str] = Header(None)):
    return recover_health_response(x_trace_id)

async def recover_health_response(
    
    trace_id : Optional[str] = None
    ) -> Dict[str, Any] :
    
    status = bool(trace_id)
    
    answer = await recover_health_llm(status)
    
    if trace_id :
        return {
            "status" : "auth ok",
            "response" : answer,
            "x_trace_id" : trace_id
        }
    else :
        return{
            "status" : "auth fail",
            "response" : answer,
            "x_trace_id" : trace_id
        }
        
async def recover_health_llm(status : bool):
    chat = get_chat()
    llm_out = await chat([{"role":"user", "content":f"인증 여부를 귀엽게 말해줘. status 값이 True면 인증, False면 실패야, status={status}"}], max_tokens = 32, temperature = 0.2)
    
    provider = getattr(config, "LLM_PROVIDER", "local-http")
    
    if provider == "openai" : 
        used_model = getattr(config, "OPENAI_MODEL", os.getenv("LLM_MODEL", "openai-default"))
    else :
        used_model = getattr(config, "LLM_MODEL", os.getenv("LLM_MODEL", "local-model"))
    
    return {
        "ok" : True,
        "provider" : provider,
        "model" : used_model,
        "anwser" : llm_out
    }