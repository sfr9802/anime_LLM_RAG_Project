"""Convenience exports and registry for retrieval strategies."""

from typing import Dict

from .base import RetrievalStrategy
from .baseline import BaselineStrategy
from .chroma_only import ChromaOnlyStrategy


# Default strategy instances used by :func:`retrieve_docs`.
STRATEGIES: Dict[str, RetrievalStrategy] = {
    "baseline": BaselineStrategy(),
    "chroma_only": ChromaOnlyStrategy(),
    # ``multiq`` kept for backwards compatibility with older callers that
    # expected a multi-query expansion strategy. It mirrors ``chroma_only``.
    "multiq": ChromaOnlyStrategy(),
}


__all__ = [
    "RetrievalStrategy",
    "BaselineStrategy",
    "ChromaOnlyStrategy",
    "STRATEGIES",
]
