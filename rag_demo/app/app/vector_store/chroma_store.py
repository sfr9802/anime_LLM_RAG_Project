# app/vector_store/query.py
from __future__ import annotations
from typing import Dict, Any, List, Optional
import threading
import chromadb
from configure import config

_client: Optional[chromadb.Client] = None
_coll = None
_lock = threading.Lock()

def get_collection():
    global _client, _coll
    if _client is None or _coll is None:
        with _lock:
            if _client is None:
                _client = chromadb.PersistentClient(path=config.CHROMA_PATH)
            if _coll is None:
                _coll = _client.get_or_create_collection(config.CHROMA_COLLECTION)
    return _coll

def upsert(ids: List[str], documents: List[str], metadatas: List[Dict[str, Any]], embeddings: List[List[float]]):
    # 길이 검증
    n = len(ids)
    assert len(documents) == n and len(metadatas) == n and len(embeddings) == n, "upsert arrays length mismatch"
    coll = get_collection()
    # 충돌 회피: 존재 가능성에 대비해 삭제 시도(실패 무시)
    if n:
        try:
            coll.delete(ids=ids)
        except Exception:
            pass
    coll.add(ids=ids, documents=documents, metadatas=metadatas, embeddings=embeddings)

def search(query: str, where: Optional[Dict[str, Any]] = None, n: int = config.TOP_K):
    if not query or not isinstance(query, str):
        raise ValueError("query must be non-empty str")
    # n 정규화
    n = max(1, min(int(n), 100))  # 과도한 요청 제한
    coll = get_collection()
    res = coll.query(query_texts=[query], n_results=n, where=where)
    # 간단 스모크 로그(필요하면 로거로 교체)
    # print(f"[chroma] q='{query[:50]}...' n={n} where={bool(where)} hits={len(res.get('ids', [[]])[0]) if res else 0}")
    return res
