# 현재 사용 X 
# 추후 OpenAI API 연동 시 사용을 위해 제작

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
        "model": model or config.OPENAI_MODEL,
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
