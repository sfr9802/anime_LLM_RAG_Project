# app/router/experimental_search_router.py
from __future__ import annotations

from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException
from ..domain.models.search_model import SearchRequest, SearchResponse, SearchResult
from ..infra.vector import search_vectors  # __init__.py에서 export한 함수

router = APIRouter(prefix="/exp", tags=["experiment"])

@router.post("/search", response_model=SearchResponse)
async def experimental_search(req: SearchRequest) -> SearchResponse:
    # --- 안전한 파라미터 정규화 ---
    # top_k
    top_k: int = 6
    if hasattr(req, "top_k") and req.top_k is not None:
        try:
            top_k = int(req.top_k)
        except (TypeError, ValueError):
            raise HTTPException(status_code=422, detail="top_k must be an integer")
    if top_k < 1:
        top_k = 1
    if top_k > 100:
        top_k = 100

    # where
    where: Optional[Dict[str, Any]] = None
    if hasattr(req, "where") and req.where is not None:
        if not isinstance(req.where, dict):
            raise HTTPException(status_code=422, detail="where must be an object")
        where = req.where

    # query
    if not hasattr(req, "query") or not isinstance(req.query, str) or not req.query.strip():
        raise HTTPException(status_code=422, detail="query must be a non-empty string")
    query = req.query.strip()

    # --- 벡터 검색 호출 ---
    try:
        hits = search_vectors(query, where=where, n=top_k)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"vector search failed: {e!s}")

    if hits is None:
        raise HTTPException(status_code=500, detail="vector search returned None")
    if not isinstance(hits, list):
        raise HTTPException(status_code=500, detail="vector search must return a list")

    # --- 결과 변환(명시적 분기로 가독성↑ / Sonar S3358 회피) ---
    results: List[SearchResult] = []
    for h in hits:
        if not isinstance(h, dict):
            # 방어적으로 문자열화
            results.append(
                SearchResult(id="", title=None, section=None, url=None, score=None, text=str(h))
            )
            continue

        _id = h.get("id")
        if _id is None:
            _id = ""
        else:
            _id = str(_id)

        meta = h.get("meta")
        if not isinstance(meta, dict):
            meta = {}

        text = h.get("text")
        if text is None:
            text = ""

        score = h.get("score")  # 추가 계산(거리→점수 변환 등)은 vector_store 쪽에서 수행

        results.append(
            SearchResult(
                id=_id,
                title=meta.get("title"),
                section=meta.get("section"),
                url=meta.get("url"),
                score=score,
                text=text,
            )
        )

    return SearchResponse(query=query, results=results)
