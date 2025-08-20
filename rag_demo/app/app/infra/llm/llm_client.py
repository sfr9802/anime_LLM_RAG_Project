# app/infra/llm/llm_client.py
from __future__ import annotations
from typing import List, Dict
import httpx, anyio
from configure import config

# 공통 인터페이스
async def chat(messages: List[Dict[str, str]], max_tokens: int = 512, temperature: float = 0.2) -> str:
    prov = config.LLM_PROVIDER
    if prov == "local-http":
        return await _chat_http(
            base_url=config.LOCAL_LLM_BASE_URL,
            api_key=config.LOCAL_LLM_API_KEY,
            model=config.LOCAL_LLM_MODEL,
            messages=messages, max_tokens=max_tokens, temperature=temperature,
            timeout=config.LOCAL_LLM_TIMEOUT,
        )
    elif prov == "openai":
        return await _chat_http(
            base_url=config.OPENAI_BASE_URL,
            api_key=config.OPENAI_API_KEY,
            model=config.OPENAI_MODEL,
            messages=messages, max_tokens=max_tokens, temperature=temperature,
            timeout=config.OPENAI_TIMEOUT,
        )
    elif prov == "local-inproc":
        return await anyio.to_thread.run_sync(_chat_local_sync, messages, max_tokens, temperature)
    else:
        raise ValueError(f"Unknown LLM_PROVIDER: {prov}")

# OpenAI 호환 HTTP
async def _chat_http(*, base_url: str, api_key: str, model: str,
                     messages: List[Dict[str, str]], max_tokens: int, temperature: float, timeout: float) -> str:
    payload = {"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": temperature}
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    async with httpx.AsyncClient(base_url=base_url, timeout=timeout) as cli:
        r = await cli.post("/chat/completions", json=payload, headers=headers)
        r.raise_for_status()
        data = r.json()
        return data["choices"][0]["message"]["content"]

# in-process llama-cpp-python
_llm = None
def _get_llm():
    global _llm
    if _llm is None:
        from llama_cpp import Llama
        _llm = Llama(
            model_path=config.LLAMA_MODEL_PATH,
            n_ctx=config.LLAMA_CTX,
            n_gpu_layers=config.LLAMA_N_GPU_LAYERS,
            chat_format="gemma",
            verbose=False,
        )
    return _llm

def _chat_local_sync(messages: List[Dict[str, str]], max_tokens: int, temperature: float) -> str:
    llm = _get_llm()
    out = llm.create_chat_completion(messages=messages, max_tokens=max_tokens, temperature=temperature)
    return out["choices"][0]["message"]["content"]
