import httpx
from typing import List
from src.agent.types import Message
from config import Settings

def _endpoint(base_url: str) -> str:
    b = base_url.rstrip("/")
    return "chat/completions" if b.endswith("/v1") else "/v1/chat/completions"

class LLMClient:
    def __init__(self, cfg: Settings):
        self.cfg = cfg
        self.cli = httpx.AsyncClient(base_url=cfg.llm_base_url, timeout=cfg.llm_timeout)
        self.path = _endpoint(cfg.llm_base_url)
        self.headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if cfg.llm_api_key:
            self.headers["Authorization"] = f"Bearer {cfg.llm_api_key}"  # 필요 시

    async def ask(self, messages: List[Message], temperature: float, max_tokens: int) -> str:
        payload = {
            "model": self.cfg.llm_model,
            "messages": [m.model_dump() for m in messages],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        r = await self.cli.post(self.path, json=payload, headers=self.headers)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]

    async def aclose(self):  # TODO: 앱 종료 훅에서 호출
        await self.cli.aclose()
