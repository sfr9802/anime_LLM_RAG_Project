
from __future__ import annotations
from typing import List, Dict, Optional
import httpx

from app.runtime.config import Settings as _SettingsCls
config = _SettingsCls()

_http: Optional[httpx.AsyncClient] = None

async def chat(
    messages: List[Dict[str, str]],
    model: Optional[str] = None,
    max_tokens: int = 512,
    temperature: float = 0.2,
) -> str:
    global _http
    base_url = config.llm_base_url
    if not base_url:
        raise RuntimeError("llm_base_url must be set.")
    api_key = None
    used_model = model or config.llm_model_alias
    timeout = 60.0

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
