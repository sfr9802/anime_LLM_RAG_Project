from fastapi import APIRouter, HTTPException
from models.api_io_dto import SearchRequest, SearchResponse, SearchResult
from vector_store import search_vectors  # __init__.py에서 export한 함수

router = APIRouter(prefix="/exp", tags=["experiment"])

@router.post("/search", response_model=SearchResponse)
async def experimental_search(req: SearchRequest) -> SearchResponse:
    # SearchRequest 가정: query: str, top_k: int = 6, where: dict | None = None
    top_k = getattr(req, "top_k", None) or 6
    where = getattr(req, "where", None)

    hits = search_vectors(req.query, where=where, n=top_k)
    if hits is None:
        raise HTTPException(status_code=500, detail="vector search failed")

    results = [
        SearchResult(
            id=h["id"],
            title=(h["meta"] or {}).get("title"),
            section=(h["meta"] or {}).get("section"),
            url=(h["meta"] or {}).get("url"),
            score=h.get("score"),
            text=h["text"],
        )
        for h in hits
    ]

    return SearchResponse(query=req.query, results=results)
