
from __future__ import annotations
from typing import List, Dict, Optional
import anyio

try:
    from app.app.configure import config
except Exception:
    try:
        from configure import config
    except Exception:
        from configure.config import config

_llm = None

def _get_llm():
    global _llm
    if _llm is None:
        from llama_cpp import Llama
        _llm = Llama(
            model_path=getattr(config, "LLAMA_MODEL_PATH", None),
            n_ctx=int(getattr(config, "LLAMA_CTX", 8192)),
            n_gpu_layers=int(getattr(config, "LLAMA_N_GPU_LAYERS", 0)),
            chat_format=str(getattr(config, "LLAMA_CHAT_FORMAT", "gemma")),
            verbose=False,
        )
    return _llm

def _chat_sync(messages: List[Dict[str, str]], max_tokens: int, temperature: float) -> str:
    out = _get_llm().create_chat_completion(
        messages=messages,
        max_tokens=max_tokens,
        temperature=temperature,
    )
    return out["choices"][0]["message"]["content"]

async def chat(
    messages: List[Dict[str, str]],
    model: Optional[str] = None,  # unused; kept for signature compatibility
    max_tokens: int = 512,
    temperature: float = 0.2,
) -> str:
    return await anyio.to_thread.run_sync(_chat_sync, messages, max_tokens, temperature)
