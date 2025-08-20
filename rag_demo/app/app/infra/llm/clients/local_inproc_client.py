from __future__ import annotations
from typing import List, Dict, Optional
import anyio
from configure import config

_llm = None

def _get_llm():
    global _llm
    if _llm is None:
        from llama_cpp import Llama
        _llm = Llama(
            model_path=config.LLAMA_MODEL_PATH,
            n_ctx=config.LLAMA_CTX,
            n_gpu_layers=config.LLAMA_N_GPU_LAYERS,
            chat_format="gemma",   # Gemma 계열이면 이게 안전
            verbose=False,
        )
    return _llm

def _chat_sync(messages: List[Dict[str, str]], max_tokens: int, temperature: float) -> str:
    llm = _get_llm()
    out = llm.create_chat_completion(
        messages=messages,
        max_tokens=max_tokens,
        temperature=temperature,
    )
    return out["choices"][0]["message"]["content"]

async def chat(
    messages: List[Dict[str, str]],
    model: Optional[str] = None,   # 시그니처 통일용. 사용 안 함.
    max_tokens: int = 512,
    temperature: float = 0.2,
) -> str:
    # 동기 호출을 스레드로 감싸 async와 인터페이스 정합
    return await anyio.to_thread.run_sync(_chat_sync, messages, max_tokens, temperature)
