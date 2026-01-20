from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.app.services.chroma_rag.service import RagService
from .utils import retrieve_docs as _retrieve_docs


class FaissRagService(RagService):
    """RAG service using FAISS for retrieval while sharing the core pipeline."""

    def retrieve_docs(
        self,
        q: str,
        *,
        k: int = 6,
        where: Optional[Dict[str, Any]] = None,
        candidate_k: Optional[int] = None,
        use_mmr: bool = False,
        lam: float = 0.5,
        strategy: str = "baseline",
    ) -> List[Dict[str, Any]]:
        return _retrieve_docs(
            q,
            k=k,
            where=where,
            candidate_k=candidate_k,
            use_mmr=use_mmr,
            lam=lam,
        )


__all__ = ["FaissRagService"]
