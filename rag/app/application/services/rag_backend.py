from __future__ import annotations

from functools import lru_cache
from typing import Any, Protocol

from app.runtime.config import Settings as _SettingsCls
config = _SettingsCls()
from app.application.services.rag_service import RagService
from app.application.services.faiss_rag_service import FaissRagService


class RagBackend(Protocol):
    async def parse_query(self, q: str, *, with_mode: bool = False) -> Any: ...
    async def ask(self, q: str, **kwargs) -> Any: ...
    def retrieve_docs(self, q: str, **kwargs) -> Any: ...


def _rag_backend() -> str:
    return (config.vector_backend or "chroma").lower()


@lru_cache(maxsize=1)
def get_rag_service() -> RagBackend:
    backend = _rag_backend()
    if backend == "faiss":
        return FaissRagService()
    return RagService()


__all__ = ["RagBackend", "get_rag_service"]
