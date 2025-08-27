# services/adapters.py
from typing import Any, Dict, List, Optional
from ..domain.models.document_model import DocumentItem
from ..infra.vector.metrics import to_similarity

def flatten_chroma_result(res: Dict[str, Any]) -> List[Dict[str, Any]]:
    ids = res.get("ids") or [[]]
    docs = res.get("documents") or [[]]
    metas = res.get("metadatas") or [[]]
    dists = res.get("distances") or [[]]
    space = (res.get("space") or "cosine").lower()  # chroma_store가 넣어줌  :contentReference[oaicite:2]{index=2}

    out = []
    if not ids or not ids[0]:
        return out

    for i in range(len(ids[0])):
        distance = dists[0][i] if dists and dists[0] and i < len(dists[0]) else None
        out.append({
            "id": ids[0][i],
            "text": docs[0][i] if docs and docs[0] and i < len(docs[0]) else None,
            "metadata": metas[0][i] if metas and metas[0] and i < len(metas[0]) else {},
            "distance": distance,
            "score": to_similarity(distance, space=space),  # ← 공식 변환  :contentReference[oaicite:3]{index=3}
        })
    # 유사도 내림차순
    out.sort(key=lambda x: (x["score"] is not None, x["score"]), reverse=True)
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
