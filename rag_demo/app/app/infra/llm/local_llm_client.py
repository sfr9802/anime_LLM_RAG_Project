# app/infra/llm/local_llm_client.py
from __future__ import annotations
from typing import List, Dict, Optional
import os
import httpx
import anyio

from configure import config

# 공통: messages 형식은 OpenAI chat와 동일 [{"role":"system/user/assistant","content":"..."}]

async def chat(
    messages: List[Dict[str, str]],
    model: Optional[str] = None,
    max_tokens: int = 512,
    temperature: float = 0.2,
) -> str:
    if config.LLM_BACKEND == "http":
        return await _chat_http(messages, model or config.LLM_MODEL, max_tokens, temperature)
    else:
        # in-process llama-cpp-python은 동기 → 스레드에서 실행
        return await anyio.to_thread.run_sync(_chat_local_sync, messages, model or config.LLM_MODEL, max_tokens, temperature)

# ---------------- HTTP (llama.cpp server with OpenAI-compatible API) ----------------
async def _chat_http(messages: List[Dict[str, str]], model: str, max_tokens: int, temperature: float) -> str:
    payload = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    headers = {
        "Authorization": f"Bearer {config.OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(base_url=config.OPENAI_BASE_URL, timeout=config.OPENAI_TIMEOUT) as cli:
        r = await cli.post("/chat/completions", json=payload, headers=headers)
        r.raise_for_status()
        data = r.json()
        return data["choices"][0]["message"]["content"]

# ---------------- In-Process (llama-cpp-python) ----------------
_llm = None

def _get_llm():
    global _llm
    if _llm is None:
        from llama_cpp import Llama
        _llm = Llama(
            model_path=config.LLAMA_MODEL_PATH,
            n_ctx=config.LLAMA_CTX,
            n_gpu_layers=config.LLAMA_N_GPU_LAYERS,
            chat_format="gemma",  # Gemma 계열
            verbose=False,
        )
    return _llm

def _chat_local_sync(messages: List[Dict[str, str]], model: str, max_tokens: int, temperature: float) -> str:
    llm = _get_llm()
    out = llm.create_chat_completion(
        messages=messages,
        max_tokens=max_tokens,
        temperature=temperature,
    )
    return out["choices"][0]["message"]["content"]
