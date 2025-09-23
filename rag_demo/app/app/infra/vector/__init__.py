# app/vector_store/__init__.py
from __future__ import annotations
from typing import Dict, Any, List, Optional
import logging

import app.app.configure.config as config  # 프로젝트 경로 유지

log = logging.getLogger("vector_store")


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

        out.append({
            "id": _id,
            "text": _doc,
            "meta": _met,
            "score": _score_from_distance(_dst),
        })

    return out


def _backend() -> str:
    try:
        return getattr(config, "VECTOR_BACKEND", "chroma").lower()
    except Exception:
        return "chroma"


def _topk(n: Optional[int]) -> int:
    if n is None:
        try:
            return int(getattr(config, "TOP_K", 8))
        except Exception:
            return 8
    try:
        k = int(n)
    except Exception:
        k = 8
    return 1 if k < 1 else k


def _search_chroma(query: str, *, where: Optional[Dict[str, Any]] = None, n: Optional[int] = None) -> Dict[str, Any]:
    # ✅ 지연 임포트: chroma만 쓸 때 chroma만 로드
    from app.app.infra.vector.chroma_store import search as chroma_search
    return chroma_search(query, where=where, n=_topk(n))


def _search_faiss(query: str, *, top_k: int):
    # ✅ 지연 임포트: faiss가 필요할 때만 시도. 실패하면 chroma로 폴백.
    try:
        from .faiss.faiss_store import get_relevant_docs as faiss_search
    except Exception as e:
        log.warning("FAISS backend requested but unavailable (%s). Falling back to Chroma.", e)
        return None
    return faiss_search(query, top_k=top_k)  # 예상: [(id, text, score, meta), ...] 혹은 유사 구조


def retrieve(query: str, top_k: int = None, where: Dict[str, Any] | None = None):
    """
    백엔드별 원래 반환을 유지:
      - faiss: faiss 검색 결과 그대로 반환(튜플/리스트 등)
      - chroma: chroma raw dict 그대로 반환
    """
    backend = _backend()
    k = _topk(top_k)

    if backend == "faiss":
        hits = _search_faiss(query, top_k=k)
        if hits is not None:
            return hits
        # faiss 불가 시 chroma로 폴백
        return _search_chroma(query, where=where, n=k)

    return _search_chroma(query, where=where, n=k)


def search_vectors(query: str, where: Optional[Dict[str, Any]] = None, n: int = None) -> List[Dict[str, Any]]:
    """
    항상 동일한 형태로 반환:
      [{"id": str, "text": str, "meta": dict, "score": float|None}, ...]
    """
    backend = _backend()
    k = _topk(n)

    if backend == "faiss":
        hits = _search_faiss(query, top_k=k)
        if hits is None:
            # faiss 없으면 chroma 폴백 + 평탄화
            return _flatten_chroma(_search_chroma(query, where=where, n=k))

        out: List[Dict[str, Any]] = []
        for h in hits:
            _id = ""
            _txt = ""
            _scr: Optional[float] = None
            _met: Dict[str, Any] = {}

            if isinstance(h, (list, tuple)):
                if len(h) > 0 and h[0] is not None:
                    _id = str(h[0])
                if len(h) > 1 and h[1] is not None:
                    _txt = str(h[1])
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
    return _flatten_chroma(_search_chroma(query, where=where, n=k))
