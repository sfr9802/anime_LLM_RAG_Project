# vector_store/faiss_store.py

import faiss
import os
import numpy as np
import errno
from functools import lru_cache
from typing import List, Dict, Any

from app.app.domain.faiss_embeddings import FaissEmbedder
from app.app.configure import config
from ...utils.utils import _normalize, _read_jsonl, _atomic_write_jsonl


class FAISSVectorStore:
    def __init__(self, dim: int, index_path: str, docs_path: str):
        self.dim = int(dim)
        self.index_path = index_path
        self.docs_path = docs_path
        
        self.index = faiss.Index = None
        self.docs = List[Dict[str, Any]]

        self._load_or_initialize()

    def _load_or_initialize(self):
        index_exists = os.path.exists(self.index_path)
        docs_exists = os.path.exists(self.docs_path)
        
        if index_exists and docs_exists :
            self.index = faiss.read_index(self.index_path)
            if self.index.d != self.dim:
                raise ValueError(f"인덱싱 차원과 임베딩 차원하고 안맞아요 : file={self.index.d}, expected={self.dim}")
            self.docs = _read_jsonl(self.docs_path)
            
            if self.index.ntotal != len(self.docs) :
                raise ValueError(
                     f"Inconsistent store: index.ntotal({self.index.ntotal}) != len(docs)({len(self.docs)})"
                )
        elif index_exists ^ docs_exists :
            raise FileNotFoundError(
                errno.ENOENT,
                f"저장이 제대로 안된듯. 인덱스 혹은 도큐먼트 둘중 하나만 존재함 {self.index_path}, {self.docs_path}"
            )
        else:
            self.index = faiss.IndexFlatL2(self.dim) #cosine 거리를 위해 L2 정규화
            self.docs = []
            
            
    def add(self, embeddings: np.ndarray, docs: List[Dict[str, Any]]):
        if embeddings.ndim != 2 or embeddings.shape[1] != self.dim:
            raise ValueError(f"임베딩 차원하고 input된 차원하고 다름 (N, {self.dim}), input {embeddings.shape}")
        if len(docs) != embeddings.shape[0]:
            raise ValueError(f"len(docs)({len(docs)}) != embeddings.N({embeddings.shape[0]})")
        
        vectors = _normalize(embeddings.astype("float32"))
        
        self.index.add(vectors)
        self.docs.extend(docs)
        
        if self.index.ntotal != len(self.docs):
            raise RuntimeError("Post-add mismatch between index.ntotal and docs length")


    def search(self, query_vector: np.ndarray, k: int = 5) -> List[Dict[str, Any]]:
        if query_vector.ndim == 1:
            query_vector = query_vector[None, :]
        if query_vector.shape[1] != self.dim:
            raise ValueError(f"query_vector dim must be {self.dim}, got {query_vector.shape[1]}")
        query = _normalize(query_vector.astype("float32"))
        dist, idx = self.index.search(query, k)
        
        results : List[Dict[str, Any]] = []
        for i, score in zip(idx[0], dist[0]) :
            if i < 0 :
                continue
            doc = self.docs[i]
            results.append({"score":float(score), "doc":doc})
        return results
        

    def save(self):
        
        os.makedirs(os.path.dirname(self.index_path) or ".", exist_ok=True)
        faiss.write_index(self.index, self.index_path)
        
        _atomic_write_jsonl(self.docs_path, self.docs)


def _similarity_from_distance(distance: float) -> float:
    if distance < 0.0:
        return 0.0
    # normalized vectors: distance in [0, 2]; convert to [0, 1]
    return max(0.0, 1.0 - (distance / 2.0))


def _env_int(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, str(default)))
    except (TypeError, ValueError):
        return int(default)


@lru_cache(maxsize=1)
def _get_faiss_store() -> FAISSVectorStore:
    dim = _env_int("FAISS_DIM", 1024)
    index_path = os.getenv("FAISS_INDEX_PATH", "faiss.index")
    docs_path = os.getenv("FAISS_DOCS_PATH", "faiss_docs.jsonl")
    return FAISSVectorStore(dim=dim, index_path=index_path, docs_path=docs_path)


@lru_cache(maxsize=1)
def _get_faiss_embedder() -> FaissEmbedder:
    model_name = os.getenv("FAISS_EMBED_MODEL", config.EMBED_MODEL)
    return FaissEmbedder(model_name=model_name)


def get_relevant_docs(query: str, top_k: int = 5) -> List[Dict[str, Any]]:
    store = _get_faiss_store()
    embedder = _get_faiss_embedder()
    query_vec = embedder.embed_query(query)
    hits = store.search(query_vec, k=top_k)
    out: List[Dict[str, Any]] = []
    for hit in hits:
        doc = hit.get("doc") or {}
        meta = doc.get("metadata") or doc.get("meta") or {}
        score = hit.get("score")
        if score is None:
            sim = None
        else:
            sim = _similarity_from_distance(float(score))
        out.append(
            {
                "id": doc.get("id") or doc.get("doc_id") or "",
                "text": doc.get("text") or doc.get("content") or "",
                "score": sim,
                "meta": meta,
            }
        )
    return out


__all__ = ["FAISSVectorStore", "get_relevant_docs"]
        
