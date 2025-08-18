# services/adapters.py
from typing import Any, Dict, List, Optional
from domain.models.document_model import DocumentItem
from rag_demo.app.app.infra.vector.metrics import to_similarity

def flatten_chroma_result(res: Dict[str, Any], default_space: str = "cosine") -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    if not isinstance(res, dict):
        return out

    space = (res.get("space") or default_space).lower()

    ids       = res.get("ids", [[]])
    docs      = res.get("documents", [[]])
    metas     = res.get("metadatas", [[]])
    distances = res.get("distances", [[]])

    ids       = ids[0] if isinstance(ids, list) and ids else []
    docs      = docs[0] if isinstance(docs, list) and docs else []
    metas     = metas[0] if isinstance(metas, list) and metas else []
    distances = distances[0] if isinstance(distances, list) and distances else []

    length = len(ids)  # ← 핵심: ids 기준으로 고정
    for i in range(length):
        _id  = ids[i]
        _doc = docs[i] if i < len(docs) else ""
        _met = metas[i] if i < len(metas) else {}
        _dst = distances[i] if i < len(distances) else None

        out.append({
            "id": _id,
            "text": _doc,
            "metadata": _met if isinstance(_met, dict) else {},
            "distance": _dst,
            "score": to_similarity(_dst, space),
            "space": space,
        })
    return out

def to_docitem(hit: Any) -> DocumentItem:
    # dict 경로만 사실상 표준. 나머지는 호환 유지하되 제한적으로.
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
        # 비권장 경로: 최소한의 호환만
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
