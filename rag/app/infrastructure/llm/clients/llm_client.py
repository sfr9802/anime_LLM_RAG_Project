# old ver

from __future__ import annotations
from typing import List, Dict, Optional
import httpx
from app.runtime.config import Settings as _SettingsCls
config = _SettingsCls()

async def chat(
    messages: List[Dict[str, str]],
    model: Optional[str] = None,
    max_tokens: int = 512,
    temperature: float = 0.2,
) -> str:
    payload = {
        "model": model or config.llm_model_alias,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    headers = {
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(base_url=config.llm_base_url, timeout=60.0) as cli:
        r = await cli.post("/chat/completions", json=payload, headers=headers)
        r.raise_for_status()
        data = r.json()
        return data["choices"][0]["message"]["content"]
