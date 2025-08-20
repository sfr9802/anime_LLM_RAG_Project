# old ver

from __future__ import annotations
from typing import List, Dict, Optional
import httpx
from configure import config

async def chat(
    messages: List[Dict[str, str]],
    model: Optional[str] = None,
    max_tokens: int = 512,
    temperature: float = 0.2,
) -> str:
    payload = {
        "model": model or config.LOCAL_LLM_MODEL,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    headers = {
        "Authorization": f"Bearer {config.LOCAL_LLM_API_KEY}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(base_url=config.LOCAL_LLM_BASE_URL, timeout=config.LOCAL_LLM_TIMEOUT) as cli:
        r = await cli.post("/chat/completions", json=payload, headers=headers)
        r.raise_for_status()
        data = r.json()
        return data["choices"][0]["message"]["content"]
