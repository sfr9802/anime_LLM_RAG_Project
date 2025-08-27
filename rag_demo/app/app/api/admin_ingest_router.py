# app/app/api/admin_ingest_router.py
from __future__ import annotations
import os, asyncio, traceback
from uuid import uuid4
from typing import Dict, Any
from fastapi import APIRouter, BackgroundTasks, HTTPException, Header
from pydantic import BaseModel, Field
import datetime
from ..services.ingest_v2_service import ingest_v2_jsonl

router = APIRouter(prefix="/admin", tags=["admin"])
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN")
_lock = asyncio.Lock()
_jobs: Dict[str, Dict[str, Any]] = {}

class IngestReq(BaseModel):
    path: str = Field(..., description="out_with_chars.jsonl 경로")
    to_mongo: bool = True
    to_chroma: bool = True
    window: bool = True
    target: int = 700
    min_chars: int = 350
    max_chars: int = 1200
    overlap: int = 120

def _auth(x_admin_token: str | None):
    if ADMIN_TOKEN and x_admin_token != ADMIN_TOKEN:
        raise HTTPException(401, "invalid admin token")

def _run(job_id: str, req: IngestReq):
    try:
        res = ingest_v2_jsonl(
            req.path,
            to_mongo=req.to_mongo,
            to_chroma=req.to_chroma,
            window=req.window,
            target=req.target,
            min_chars=req.min_chars,
            max_chars=req.max_chars,
            overlap=req.overlap,
        )
        _jobs[job_id]["status"] = "done"
        _jobs[job_id]["result"] = res
    except Exception as e:
        _jobs[job_id]["status"] = "error"
        _jobs[job_id]["error"] = f"{type(e).__name__}: {e}"
        _jobs[job_id]["traceback"] = traceback.format_exc()

@router.post("/ingest/start")
async def start_ingest(req: IngestReq, background: BackgroundTasks, x_admin_token: str | None = Header(default=None)):
    _auth(x_admin_token)
    if _lock.locked():
        raise HTTPException(409, "ingest already running")
    job_id = str(uuid4())
    _jobs[job_id] = {"status": "running", "request": req.model_dump()}
    async def task():
        async with _lock:
            await asyncio.to_thread(_run, job_id, req)
    background.add_task(task)
    return {"job_id": job_id, "status": "running"}

@router.get("/ingest/{job_id}")
def ingest_status(job_id: str, x_admin_token: str | None = Header(default=None)):
    _auth(x_admin_token)
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(404, "job not found")
    return job


def _auth(x_admin_token: str | None):
    if not ADMIN_TOKEN:
        raise HTTPException(503, "admin is not configured")  # or 401
    if x_admin_token != ADMIN_TOKEN:
        raise HTTPException(401, "invalid admin token")

def _run(job_id: str, req: IngestReq):
    _jobs[job_id].update({"started_at": datetime.utcnow().isoformat(), "progress": 0})
    try:
        # ingest_v2_jsonl(...) 콜백/진행률 훅이 있으면 연결:
        # for p in ingest_v2_jsonl(..., on_progress=lambda pct: _jobs[job_id].update({"progress": pct})):
        res = ingest_v2_jsonl( ... )
        _jobs[job_id].update({"status":"done","result":res,"progress":100,"finished_at":datetime.utcnow().isoformat()})
    except Exception as e:
        _jobs[job_id].update({
            "status":"error",
            "error": f"{type(e).__name__}: {e}",
            "traceback": traceback.format_exc(),
            "finished_at": datetime.utcnow().isoformat()
        })