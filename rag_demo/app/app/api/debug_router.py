# api/debug.py
from fastapi import APIRouter, Query, Body
from pydantic import BaseModel
from typing import Any, Dict, List, Optional, Literal
from services.retrieval_service import retrieve as svc_retrieve
from services.eval_service import evaluate_hit as svc_evaluate_hit

router = APIRouter(prefix="/debug", tags=["debug"])

@router.get("/retrieve")
def debug_retrieve(q: str = Query(..., min_length=1), k: int = 3, include_docs: bool = False):
    return svc_retrieve(q=q, k=k, include_docs=include_docs)

class GoldRow(BaseModel):
    q: str
    gold: Dict[str, Any]

class EvalReq(BaseModel):
    k: int = 3
    mode: Literal["page","title","chunk"] = "page"
    n_fetch: Optional[int] = None
    goldset: List[GoldRow]
    limit_misses: int = 50

@router.post("/eval_hit")
def debug_eval_hit(req: EvalReq = Body(...)):
    res = svc_evaluate_hit(
        [r.dict() for r in req.goldset],
        k=req.k, mode=req.mode, n_fetch=req.n_fetch
    )
    # 응답 부풀림 방지
    if "misses" in res and isinstance(res["misses"], list) and len(res["misses"]) > req.limit_misses:
        res["misses"] = res["misses"][:req.limit_misses]
        res["truncated_misses"] = True
    return res