from __future__ import annotations

from functools import lru_cache
from typing import Any, Protocol

from app.app.configure import config
from app.app.services.chroma_rag import RagService
from app.app.services.faiss_rag.service import FaissRagService


class RagBackend(Protocol):
    async def parse_query(self, q: str, *, with_mode: bool = False) -> Any: ...
    async def ask(self, q: str, **kwargs) -> Any: ...
    def retrieve_docs(self, q: str, **kwargs) -> Any: ...


def _rag_backend() -> str:
    return (getattr(config, "VECTOR_BACKEND", "chroma") or "chroma").lower()


@lru_cache(maxsize=1)
def get_rag_service() -> RagBackend:
    backend = _rag_backend()
    if backend == "faiss":
        return FaissRagService()
    return RagService()


__all__ = ["RagBackend", "get_rag_service"]
