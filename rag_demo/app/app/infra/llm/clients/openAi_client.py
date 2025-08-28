
from __future__ import annotations
from typing import List, Dict, Optional
import httpx

try:
    from app.app.configure import config
except Exception:
    try:
        from configure import config
    except Exception:
        from configure.config import config

_http: Optional[httpx.AsyncClient] = None

async def chat(
    messages: List[Dict[str, str]],
    model: Optional[str] = None,
    max_tokens: int = 512,
    temperature: float = 0.2,
) -> str:
    global _http
    base_url = getattr(config, "LLM_BASE_URL", None) or getattr(config, "OPENAI_BASE_URL", None)
    if not base_url:
        raise RuntimeError("LLM_BASE_URL/OPENAI_BASE_URL must be set.")
    api_key = getattr(config, "LLM_API_KEY", None) or getattr(config, "OPENAI_API_KEY", None)
    used_model = model or getattr(config, "LLM_MODEL", None) or getattr(config, "OPENAI_MODEL", None)
    timeout = float(getattr(config, "LLM_TIMEOUT", 60.0) or getattr(config, "OPENAI_TIMEOUT", 60.0))

    if _http is None:
        _http = httpx.AsyncClient(base_url=base_url, timeout=timeout)

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    payload = {"model": used_model, "messages": messages, "max_tokens": max_tokens, "temperature": temperature}

    r = await _http.post("/v1/chat/completions", json=payload, headers=headers, timeout=timeout)
    r.raise_for_status()
    j = r.json()
    return j["choices"][0]["message"]["content"]
