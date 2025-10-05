# vector_store/faiss_store.py

import faiss
import os
import json
import numpy as np
import errno
import tempfile
from typing import List, Dict, Any
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
        
