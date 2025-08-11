# services/adapters.py
from typing import Any, Dict, List, Optional
from models.document_model import DocumentItem

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

def flatten_chroma_result(res: Dict[str, Any]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    if not isinstance(res, dict):
        return out

    ids       = res.get("ids")
    docs      = res.get("documents")
    metas     = res.get("metadatas")
    distances = res.get("distances")

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
            "metadata": _met,
            "score": _score_from_distance(_dst),
        }
        out.append(item)
    return out

def to_docitem(hit: Any) -> DocumentItem:
    if isinstance(hit, DocumentItem):
        return hit

    if isinstance(hit, dict):
        _id = hit.get("id")
        if _id is None:
            _id = ""
        else:
            _id = str(_id)

        txt = hit.get("text")
        if txt is None:
            txt = str(hit)
        else:
            txt = str(txt)

        score: Optional[float] = hit.get("score")
        if score is None and "distance" in hit:
            try:
                score = 1.0 - float(hit["distance"])
            except (TypeError, ValueError):
                score = None
        meta = hit.get("metadata") or hit.get("meta")
        if not isinstance(meta, dict):
            meta = {}

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
        score: Optional[float] = None
        if len(hit) > 2:
            score = hit[2]
        meta: Dict[str, Any] = {}
        if len(hit) > 3 and isinstance(hit[3], dict):
            meta = hit[3]

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
