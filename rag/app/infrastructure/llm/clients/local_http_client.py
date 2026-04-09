from __future__ import annotations
from typing import List, Dict, Optional
import httpx
from urllib.parse import urljoin

from app.runtime.config import Settings as _SettingsCls
config = _SettingsCls()

_http: Optional[httpx.AsyncClient] = None
_endpoint_path = "v1/chat/completions"  # 선행 슬래시 금지: base_url에 서브패스 있을 때 안전

def _build_base_url() -> str:
    base_url = config.llm_base_url
    if not base_url:
        raise RuntimeError("llm_base_url must be set.")
    return str(base_url).rstrip("/")

async def close_http() -> None:
    global _http
    if _http is not None:
        await _http.aclose()
        _http = None

async def chat(
    messages: List[Dict[str, str]],
    model: Optional[str] = None,
    max_tokens: int = 512,
    temperature: float = 0.2,
) -> str:
    global _http

    base_url = _build_base_url()
    api_key = None  # local HTTP typically doesn't need API key
    used_model = model or config.llm_model_alias
    if not used_model:
        raise RuntimeError("Model must be specified via arg or llm_model_alias.")

    timeout = 60.0

    if _http is None:
        _http = httpx.AsyncClient(base_url=base_url, timeout=timeout)

    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    payload = {
        "model": used_model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        # "stream": False,  # 스트리밍 붙일 때 True + SSE로 처리
    }

    # base_url이 서브패스를 포함할 수 있으므로 상대경로 사용
    url = _endpoint_path  # == "v1/chat/completions"
    try:
        resp = await _http.post(url, json=payload, headers=headers, timeout=timeout)
        resp.raise_for_status()
        j = resp.json()
        return j["choices"][0]["message"]["content"]
    except httpx.HTTPStatusError as e:
        # 상태/본문 같이 노출
        detail = None
        try:
            detail = e.response.json()
        except Exception:
            detail = e.response.text
        raise RuntimeError(f"LLM HTTP {e.response.status_code}: {detail}") from e
    except httpx.HTTPError as e:
        raise RuntimeError(f"LLM HTTP error: {e}") from e
