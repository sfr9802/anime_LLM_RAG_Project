from __future__ import annotations
from typing import Callable, Awaitable, Dict, List
from configure import config

# 각 클라이언트의 chat 함수를 가져오지 않고 지연 import로 의존 최소화
def get_chat() -> Callable[[List[Dict[str, str]], int, float], Awaitable[str]]:
    prov = config.LLM_PROVIDER
    if prov == "local-http":
        from .clients.local_http_client import chat
        return lambda messages, max_tokens=512, temperature=0.2: chat(
            messages, model=config.LOCAL_LLM_MODEL, max_tokens=max_tokens, temperature=temperature
        )
    if prov == "local-inproc":
        from .clients.local_inproc_client import chat
        return lambda messages, max_tokens=512, temperature=0.2: chat(
            messages, model=None, max_tokens=max_tokens, temperature=temperature
        )
    if prov == "openai":
        from .clients.openAi_client import chat
        return lambda messages, max_tokens=512, temperature=0.2: chat(
            messages, model=config.OPENAI_MODEL, max_tokens=max_tokens, temperature=temperature
        )
    raise ValueError(f"Unknown LLM_PROVIDER: {prov}")
