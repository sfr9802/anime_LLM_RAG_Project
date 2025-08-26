# sinks_ingest.py
from __future__ import annotations
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

from dotenv import load_dotenv
from pymongo import MongoClient, ASCENDING
import chromadb
from sentence_transformers import SentenceTransformer
import numpy as np

load_dotenv()

# --- Mongo ---
MONGO_URI       = os.getenv("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB        = os.getenv("MONGO_DB", "clean_namu_crawl")
MONGO_RAW_COL   = os.getenv("MONGO_RAW_COL", "pages")
MONGO_CHUNK_COL = os.getenv("MONGO_CHUNK_COL", "chunks")

# --- Vector / Embedding ---
CHROMA_PATH       = os.getenv("CHROMA_PATH", "./data/chroma")
CHROMA_COLLECTION = os.getenv("CHROMA_COLLECTION", "namu-anime")
EMBED_MODEL       = os.getenv("EMBED_MODEL", "BAAI/bge-m3")
EMBED_BATCH       = int(os.getenv("EMBED_BATCH", "32"))
VECTOR_BACKEND    = os.getenv("VECTOR_BACKEND", "chroma").lower()

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

# ---------- Embedder (CPU) ----------
class STEmbedder:
    def __init__(self, model_name: str = EMBED_MODEL, device: str = "cpu", batch_size: int = EMBED_BATCH):
        self.model = SentenceTransformer(model_name, device=device)
        self.batch_size = batch_size

    def encode(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []
        arr = self.model.encode(
            texts,
            batch_size=self.batch_size,
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False
        )
        return [v.astype(np.float32).tolist() for v in arr]

# ---------- Mongo ----------
class MongoSink:
    def __init__(self):
        self.cli = MongoClient(MONGO_URI)
        db = self.cli[MONGO_DB]
        self.pages = db[MONGO_RAW_COL]
        self.chunks = db[MONGO_CHUNK_COL]
        self.ensure_indexes()

    def ensure_indexes(self):
        self.pages.create_index([("_id", ASCENDING)], unique=True, name="pk_doc_id")
        self.pages.create_index([("seed", ASCENDING)], name="idx_seed")
        self.pages.create_index([("title", ASCENDING)], name="idx_title")
        self.pages.create_index([("created_at", ASCENDING)], name="idx_created_at")
        self.pages.create_index([("vectorized", ASCENDING)], name="idx_vectorized")

        self.chunks.create_index([("_id", ASCENDING)], unique=True, name="pk_chunk_id")
        self.chunks.create_index([("doc_id", ASCENDING), ("seg_index", ASCENDING)], unique=True, name="uk_doc_seg")
        self.chunks.create_index([("section", ASCENDING)], name="idx_section")

    def upsert_page(self, doc: Dict[str, Any], n_segments: int):
        # 요약 메타 뽑기
        y = (doc.get("sections") or {}).get("요약") or {}
        page = {
            "_id": doc["doc_id"],
            "doc_id": doc["doc_id"],
            "seed": doc.get("seed"),
            "title": doc.get("title"),
            "urls": doc.get("urls", []),
            "summary": doc.get("summary"),
            "sum_bullets": doc.get("sum_bullets", []),
            "raw_len": doc.get("raw_len"),
            "sum_len": doc.get("sum_len"),
            "compression_ratio": doc.get("compression_ratio"),
            "summary_model": y.get("model"),
            "summary_ts": y.get("ts"),
            "meta": doc.get("meta") or {},
            "created_at": doc.get("created_at") or _now_iso(),
            "updated_at": _now_iso(),
            "n_segments": int(n_segments),
            "vectorized": False,
            "vector_ts": None,
            "chroma_segment_ids": [],
        }
        self.pages.replace_one({"_id": page["_id"]}, page, upsert=True)

    def upsert_chunks(self, doc: Dict[str, Any]) -> Tuple[List[str], List[str], List[Dict[str, Any]]]:
        ids, texts, metas = [], [], []
        idx = 0
        for sec_name, sec_obj in (doc.get("sections") or {}).items():
            if sec_name == "요약":
                continue
            if not isinstance(sec_obj, dict):
                continue
            for c in (sec_obj.get("chunks") or []):
                cid = f"{doc['doc_id']}:{idx}"
                chunk_doc = {
                    "_id": cid,
                    "doc_id": doc["doc_id"],
                    "seg_index": idx,
                    "section": sec_name,
                    "title": doc.get("title"),
                    "urls": sec_obj.get("urls") or [],
                    "text": c,
                    "created_at": doc.get("created_at") or _now_iso(),
                    "updated_at": _now_iso(),
                }
                self.chunks.replace_one({"_id": cid}, chunk_doc, upsert=True)

                ids.append(cid)
                texts.append(c)
                metas.append({"doc_id": doc["doc_id"], "seg_index": idx, "section": sec_name, "title": doc.get("title")})
                idx += 1
        return ids, texts, metas

    def mark_vectorized(self, doc_id: str, seg_ids: List[str]):
        self.pages.update_one(
            {"_id": doc_id},
            {"$set": {"vectorized": True, "vector_ts": _now_iso(), "chroma_segment_ids": seg_ids}}
        )

    def close(self):
        try:
            self.cli.close()
        except:
            pass

# ---------- Chroma ----------
class ChromaSink:
    def __init__(self, embedder: STEmbedder):
        if VECTOR_BACKEND != "chroma":
            raise RuntimeError(f"Unsupported VECTOR_BACKEND={VECTOR_BACKEND}")
        self.client = chromadb.PersistentClient(path=CHROMA_PATH)
        try:
            self.coll = self.client.get_collection(CHROMA_COLLECTION)
        except:
            self.coll = self.client.create_collection(CHROMA_COLLECTION, metadata={"embed_model": EMBED_MODEL})
        self.embedder = embedder

    def upsert_embeddings(self, ids: List[str], texts: List[str], metas: List[Dict[str, Any]]) -> List[str]:
        if not ids:
            return []
        vectors = self.embedder.encode(texts)  # CPU
        self.coll.upsert(ids=ids, documents=texts, metadatas=metas, embeddings=vectors)
        return ids
