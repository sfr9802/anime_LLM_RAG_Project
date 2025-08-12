# app/vector_store/__init__.py
from typing import Dict, Any, List, Optional
from configure import config
from .faiss import get_relevant_docs as _faiss_search
from .chroma_store import search as _chroma_search

def _score_from_distance(distance: Optional[float]) -> Optional[float]:
    if distance is None:
        return None
    try:
        score = 1.0 - float(distance)
    except (TypeError, ValueError):
        return None
    if score < 0.0:
        return 0.0
    if score > 1.0:
        return 1.0
    return score

def _flatten_chroma(res: Dict[str, Any]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    if not isinstance(res, dict):
        return out

    ids       = res.get("ids")
    docs      = res.get("documents")
    metas     = res.get("metadatas")
    distances = res.get("distances")

    # 단일 질의 기준으로 첫 배치만 안전하게 추출
    ids       = ids[0]       if isinstance(ids, list) and ids else []
    docs      = docs[0]      if isinstance(docs, list) and docs else []
    metas     = metas[0]     if isinstance(metas, list) and metas else []
    distances = distances[0] if isinstance(distances, list) and distances else []

    length = len(ids)
    for i in range(length):
        _id  = ids[i] if i < len(ids) else ""
        _doc = docs[i] if i < len(docs) else ""
        _met = metas[i] if i < len(metas) else {}
        _dst = distances[i] if i < len(distances) else None

        item: Dict[str, Any] = {
            "id": _id,
            "text": _doc,
            "meta": _met,
            "score": _score_from_distance(_dst),
        }
        out.append(item)

    return out

def retrieve(query: str, top_k: int = config.TOP_K, where: Dict[str, Any] | None = None):
    backend = getattr(config, "VECTOR_BACKEND", "chroma").lower()
    k = int(top_k)
    if k < 1:
        k = 1
    if backend == "faiss":
        return _faiss_search(query, top_k=k)
    return _chroma_search(query, where=where, n=k)

def search_vectors(query: str, where: Optional[Dict[str, Any]] = None, n: int = config.TOP_K) -> List[Dict[str, Any]]:
    backend = getattr(config, "VECTOR_BACKEND", "chroma").lower()
    k = int(n)
    if k < 1:
        k = 1

    if backend == "faiss":
        faiss_hits = _faiss_search(query, top_k=k)  # 예상: [(id, text, score, meta), ...]
        out: List[Dict[str, Any]] = []
        for h in faiss_hits:
            _id = ""
            _txt = ""
            _scr: Optional[float] = None
            _met: Dict[str, Any] = {}

            if isinstance(h, (list, tuple)):
                if len(h) > 0:
                    _id = "" if h[0] is None else str(h[0])
                if len(h) > 1:
                    _txt = "" if h[1] is None else str(h[1])
                if len(h) > 2:
                    _scr = h[2]
                if len(h) > 3 and isinstance(h[3], dict):
                    _met = h[3]
            elif isinstance(h, dict):
                _id  = "" if h.get("id")   is None else str(h.get("id"))
                _txt = "" if h.get("text") is None else str(h.get("text"))
                _scr = h.get("score")
                meta_candidate = h.get("meta") or h.get("metadata")
                if isinstance(meta_candidate, dict):
                    _met = meta_candidate

            out.append({"id": _id, "text": _txt, "meta": _met, "score": _scr})
        return out

    # chroma
    chroma_res = _chroma_search(query, where=where, n=k)
    return _flatten_chroma(chroma_res)
