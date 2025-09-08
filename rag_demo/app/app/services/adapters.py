# app/app/services/adapters.py
from typing import Any, Dict, List, Optional
from ..domain.models.document_model import DocumentItem
from ..infra.vector.metrics import to_similarity

def _first_dim(x):
    """Chroma query 결과(보통 [ [..] ])를 첫 쿼리 축으로 평탄화.
    리스트/튜플/넘파이 전부 안전 처리."""
    if x is None:
        return []
    # 리스트 계열
    if isinstance(x, (list, tuple)):
        if len(x) > 0 and isinstance(x[0], (list, tuple)):
            return x[0]
        return list(x)
    # 넘파이 계열
    try:
        import numpy as np  # optional
        if isinstance(x, np.ndarray):
            if x.ndim >= 2:
                return x[0]
            return x.tolist()
    except Exception:
        pass
    # 기타는 그대로
    return x

def flatten_chroma_result(res: Dict[str, Any]) -> List[Dict[str, Any]]:
    ids  = _first_dim(res.get("ids") or [])
    docs = _first_dim(res.get("documents") or [])
    metas = _first_dim(res.get("metadatas") or [])
    dists = _first_dim(res.get("distances") or [])
    embs  = res.get("embeddings", None)
    if embs is not None:
        embs = _first_dim(embs)  # ← 여기서도 1차원으로

    space = (res.get("space") or "cosine").lower()

    if not ids:
        return []

    out: List[Dict[str, Any]] = []
    n = len(ids)
    for i in range(n):
        distance = dists[i] if i < len(dists) else None
        text = docs[i] if i < len(docs) else None
        meta = metas[i] if i < len(metas) else {}

        item = {
            "id": ids[i],
            "text": text,
            "metadata": meta or {},
            "distance": distance,
            "score": to_similarity(distance, space=space),
        }

        # 임베딩이 있으면 안전하게 list로 변환
        if embs is not None and i < len(embs):
            e = embs[i]
            try:
                e = e.tolist()  # numpy → list
            except Exception:
                pass
            item["embedding"] = e

        out.append(item)

    # 유사도 내림차순
    out.sort(key=lambda x: (x.get("score") is not None, x.get("score")), reverse=True)
    return out

def to_docitem(hit: Any) -> DocumentItem:
    if isinstance(hit, dict):
        _id = str(hit.get("id") or "")
        txt = str(hit.get("text") or str(hit))
        meta = hit.get("metadata") or hit.get("meta") or {}
        if not isinstance(meta, dict):
            meta = {}

        score: Optional[float] = hit.get("score")
        if score is None:
            score = to_similarity(hit.get("distance"), (hit.get("space") or "cosine"))

        return DocumentItem(
            id=_id,
            page_id=meta.get("page_id"),
            chunk_id=meta.get("chunk_id"),
            url=meta.get("url"),
            title=meta.get("title"),
            section=meta.get("section"),
            seed=meta.get("seed"),
            score=score,
            text=txt,
        )

    if isinstance(hit, (list, tuple)):
        _id = "" if len(hit) < 1 or hit[0] is None else str(hit[0])
        txt = "" if len(hit) < 2 or hit[1] is None else str(hit[1])
        score = hit[2] if len(hit) > 2 else None
        meta: Dict[str, Any] = hit[3] if len(hit) > 3 and isinstance(hit[3], dict) else {}

        return DocumentItem(
            id=_id,
            page_id=meta.get("page_id"),
            chunk_id=meta.get("chunk_id"),
            url=meta.get("url"),
            title=meta.get("title"),
            section=meta.get("section"),
            seed=meta.get("seed"),
            score=score,
            text=txt,
        )

    return DocumentItem(id="", text=str(hit), score=None)
