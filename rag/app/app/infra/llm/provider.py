
from __future__ import annotations
from typing import Optional, List, Dict, Awaitable, Callable
import httpx

# Try both import paths to match your codebase
try:
    from app.app.configure import config  # modern path
except Exception:  # fallback
    try:
        from configure import config  # e.g. `from configure import config`
    except Exception:
        from configure.config import config  # e.g. `from configure.config import config`

# --- Simple interface ---
class LLMClient:
    async def chat(self, messages: List[Dict[str, str]], *, model: Optional[str] = None,
                   max_tokens: int = 512, temperature: float = 0.2) -> str:
        raise NotImplementedError

# --- HTTP (OpenAI-compatible: OpenAI / vLLM / other servers) ---
class _OpenAIHTTPClient(LLMClient):
    def __init__(self, http: httpx.AsyncClient, *, base_url: str,
                 api_key: Optional[str], default_model: Optional[str], timeout: float = 60.0):
        self._http, self._base_url, self._api_key, self._default_model, self._timeout = (
            http, base_url.rstrip("/"), api_key, default_model, timeout
        )

    async def chat(self, messages: List[Dict[str, str]], *, model: Optional[str] = None,
                   max_tokens: int = 512, temperature: float = 0.2) -> str:
        used_model = model or self._default_model
        if not used_model:
            raise RuntimeError("LLM model is not set (LLM_MODEL / OPENAI_MODEL / LOCAL_LLM_MODEL).")
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        payload = {
            "model": used_model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        r = await self._http.post(f"{self._base_url}/chat/completions", json=payload, headers=headers, timeout=self._timeout)
        r.raise_for_status()
        j = r.json()
        return j["choices"][0]["message"]["content"]

# --- Factory / DI helpers ---
_http_singleton: Optional[httpx.AsyncClient] = None
_client_singleton: Optional[LLMClient] = None

def _normalize_provider(v: Optional[str]) -> str:
    if not v:
        return "openai"
    v = v.strip().lower()
    if v == "local-http":
        return "local_http"
    return v

def build_client(async_http_client: httpx.AsyncClient | None = None) -> LLMClient:
    provider = _normalize_provider(getattr(config, "LLM_PROVIDER", None))

    if provider in ("openai", "local_http"):
        base_url = getattr(config, "LLM_BASE_URL", None) or getattr(config, "OPENAI_BASE_URL", None)
        if not base_url:
            raise RuntimeError("LLM_BASE_URL (or OPENAI_BASE_URL) must be set for HTTP providers.")
        api_key = getattr(config, "LLM_API_KEY", None) or getattr(config, "OPENAI_API_KEY", None)
        model = getattr(config, "LLM_MODEL", None) or getattr(config, "LOCAL_LLM_MODEL", None) or getattr(config, "OPENAI_MODEL", None)
        timeout = float(getattr(config, "LLM_TIMEOUT", 60.0) or getattr(config, "OPENAI_TIMEOUT", 60.0))
        http = async_http_client or httpx.AsyncClient(base_url=base_url, timeout=timeout)
        return _OpenAIHTTPClient(http, base_url=base_url, api_key=api_key, default_model=model, timeout=timeout)

    raise RuntimeError(f"Unknown LLM_PROVIDER: {provider}")

async def get_client() -> LLMClient:
    global _client_singleton, _http_singleton
    if _client_singleton is None:
        _client_singleton = build_client()
    return _client_singleton

# --- Legacy wrapper (keeps old call sites working) ---
def get_chat() -> Callable[[List[Dict[str, str]], int, float], Awaitable[str]]:
    async def _call(messages: List[Dict[str, str]], max_tokens: int = 512, temperature: float = 0.2) -> str:
        client = await get_client()
        return await client.chat(messages, max_tokens=max_tokens, temperature=temperature)
    return _call
