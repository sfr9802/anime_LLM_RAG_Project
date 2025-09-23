# app/app/services/ingest_v2_service.py
from __future__ import annotations
from typing import Dict, Any, List
import json, hashlib, time
from pymongo import UpdateOne
from pymongo.errors import PyMongoError

from ..configure import config
from ..domain.chroma_embeddings import embed_passages  # 반환: np.ndarray 또는 list 지원 권장
from ..infra.vector.chroma_store import upsert as chroma_upsert
from ..infra.mongo.mongo_client import get_db  # db = get_db()

from ..domain.chunker import window_by_chars

def _stable_id(doc_id: str, section: str, i: int, text: str) -> str:
    h = hashlib.md5(f"{doc_id}|{section}|{i}|{text}".encode("utf-8")).hexdigest()[:24]
    return f"{h}_{i}"

def _flush_chroma(ids: List[str], docs: List[str], metas: List[Dict[str, Any]]) -> int:
    if not ids: return 0
    # Chroma 버전 호환 위해 list-of-list 전달
    embs = embed_passages(docs, as_list=True)  # 중요
    chroma_upsert(ids, docs, metas, embs)
    return len(ids)

def ingest_v2_jsonl(
    path: str,
    *,
    to_mongo: bool = True,
    to_chroma: bool = True,
    window: bool = True,
    target: int = 700,
    min_chars: int = 350,
    max_chars: int = 1200,
    overlap: int = 120,
) -> Dict[str, Any]:
    db = get_db()
    works = db[ getattr(config, "MONGO_WORKS_COL", "works") ]
    chars = db[ getattr(config, "MONGO_CHARS_COL", "characters") ]

    if to_mongo:
        try:
            works.create_index("doc_id", unique=True)
            works.create_index("seed")
            works.create_index("title")
            chars.create_index([("doc_id",1),("name",1)], unique=True)
            chars.create_index("seed")
            chars.create_index("name")
        except Exception:
            pass

    B = getattr(config, "INDEX_BATCH", 256)

    mw_ops: List[UpdateOne] = []
    mc_ops: List[UpdateOne] = []

    ids: List[str] = []; docs: List[str] = []; metas: List[Dict[str, Any]] = []
    total = up_w = up_c = pushed = 0

    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line: continue
            total += 1
            doc = json.loads(line)

            seed = (doc.get("seed") or doc.get("title") or "").strip()
            doc_id = (doc.get("doc_id") or "").strip()
            sections = doc.get("sections") or {}
            if not doc_id or not sections: 
                continue

            # Mongo
            if to_mongo:
                mw_ops.append(UpdateOne({"doc_id": doc_id}, {"$set": doc}, upsert=True))
                ch = (sections.get("등장인물") or {}).get("list") or []
                for c in ch:
                    name = (c.get("name") or "").strip()
                    if not name: 
                        continue
                    mc_ops.append(UpdateOne(
                        {"doc_id": doc_id, "name": name},
                        {"$set": {
                            "doc_id": doc_id, "seed": seed, "name": name,
                            "desc": c.get("desc") or "", "url": c.get("url") or "",
                        }},
                        upsert=True
                    ))
                if len(mw_ops) >= 1000:
                    try:
                        res = works.bulk_write(mw_ops, ordered=False)
                        up_w += (res.upserted_count or 0) + (res.modified_count or 0)
                    except PyMongoError:
                        pass
                    finally:
                        mw_ops.clear()
                if len(mc_ops) >= 2000:
                    try:
                        res = chars.bulk_write(mc_ops, ordered=False)
                        up_c += (res.upserted_count or 0) + (res.modified_count or 0)
                    except PyMongoError:
                        pass
                    finally:
                        mc_ops.clear()

            # Chroma
            if to_chroma:
                for sec, sobj in sections.items():
                    chks = list(sobj.get("chunks") or [])
                    if window:
                        chks = window_by_chars(chks, target=target, min_chars=min_chars, max_chars=max_chars, overlap=overlap)
                    for i, ctext in enumerate(chks):
                        t = (ctext or "").strip()
                        if len(t) < 5: 
                            continue
                        cid = _stable_id(doc_id, sec, i, t)
                        meta = {"doc_id": doc_id, "seed": seed, "section": sec, "type": "section", "i": i}
                        ids.append(cid); docs.append(t); metas.append(meta)
                        if len(ids) >= B:
                            pushed += _flush_chroma(ids, docs, metas)
                            ids.clear(); docs.clear(); metas.clear()

                ch_list = (sections.get("등장인물") or {}).get("list") or []
                for c in ch_list:
                    name = (c.get("name") or "").strip()
                    desc = (c.get("desc") or "").strip()
                    if not name or len(desc) < 5: 
                        continue
                    text = f"{name}\n{desc}"
                    cid = _stable_id(doc_id, "등장인물", hash(name) & 0xffff, name)
                    meta = {"doc_id": doc_id, "seed": seed, "section": "등장인물", "type": "character", "name": name}
                    ids.append(cid); docs.append(text); metas.append(meta)
                    if len(ids) >= B:
                        pushed += _flush_chroma(ids, docs, metas)
                        ids.clear(); docs.clear(); metas.clear()

    # flush
    if to_mongo and mw_ops:
        try:
            res = works.bulk_write(mw_ops, ordered=False)
            up_w += (res.upserted_count or 0) + (res.modified_count or 0)
        except PyMongoError:
            pass
    if to_mongo and mc_ops:
        try:
            res = chars.bulk_write(mc_ops, ordered=False)
            up_c += (res.upserted_count or 0) + (res.modified_count or 0)
        except PyMongoError:
            pass
    if to_chroma and ids:
        pushed += _flush_chroma(ids, docs, metas)

    return {"total": total, "mongo_works": up_w, "mongo_chars": up_c, "chroma_indexed": pushed}
