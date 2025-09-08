from __future__ import annotations

"""Dispatcher for RAG retrieval strategies."""

from typing import Any, Dict, List, Optional

from .strategies import STRATEGIES


def retrieve_docs(
    self,
    q: str,
    *,
    k: int = 6,
    where: Optional[Dict[str, Any]] = None,
    candidate_k: Optional[int] = None,
    use_mmr: bool = True,
    lam: float = 0.5,
    strategy: str = "baseline",
) -> List[Dict[str, Any]]:
    """Return documents retrieved by the named strategy.

    Parameters mirror those accepted by each strategy's ``retrieve`` method.
    """

    strat = STRATEGIES.get(strategy)
    if not strat:
        raise ValueError(f"unknown strategy: {strategy}")
    return strat.retrieve(
        self,
        q,
        k=k,
        where=where,
        candidate_k=candidate_k,
        use_mmr=use_mmr,
        lam=lam,
    )


def retrieve(
    self,
    q: str,
    *,
    k: int = 6,
    where: Optional[Dict[str, Any]] = None,
    candidate_k: Optional[int] = None,
    use_mmr: bool = True,
    lam: float = 0.5,
    strategy: str = "baseline",
) -> Dict[str, Any]:
    """Compatibility wrapper returning a structured payload.

    The original monolithic service exposed a ``retrieve`` function that
    returned a dictionary with metadata alongside the retrieved items.  The
    modern service dispatches to strategy objects and returns a bare list of
    document dictionaries.  To ease the transition for any callers still
    relying on the old return shape we keep a thin wrapper that packages the
    list into a dict.
    """

    items = retrieve_docs(
        self,
        q,
        k=k,
        where=where,
        candidate_k=candidate_k,
        use_mmr=use_mmr,
        lam=lam,
        strategy=strategy,
    )
    return {"q": q, "k": k, "where": where, "items": items}


__all__ = ["retrieve_docs", "retrieve"]
