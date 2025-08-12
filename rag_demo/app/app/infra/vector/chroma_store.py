from __future__ import annotations
from typing import Dict, Any, List, Optional, Union
import threading
import chromadb
from configure import config

_client: Optional[chromadb.Client] = None
_coll: Optional[Any] = None
_lock = threading.Lock()

def _space() -> str:
    """거리 공간: 'cosine' | 'l2' | 'ip' (기본 cosine)"""
    return getattr(config, "CHROMA_SPACE", "cosine").lower()

def get_collection():
    """Chroma 컬렉션 lazy init (thread-safe)"""
    global _client, _coll
    if _client is None or _coll is None:
        with _lock:
            if _client is None:
                _client = chromadb.PersistentClient(path=config.CHROMA_PATH)
            if _coll is None:
                _coll = _client.get_or_create_collection(
                    name=config.CHROMA_COLLECTION,
                    metadata={"hnsw:space": _space()},
                )
    return _coll

def upsert(
    ids: List[str],
    documents: List[str],
    metadatas: List[Dict[str, Any]],
    embeddings: Optional[List[List[float]]] = None,
) -> None:
    """
    벡터/문서 upsert. embeddings 생략 시 컬렉션에 설정된 embedding_function 사용.
    """
    n = len(ids)
    if n == 0:
        return
    assert len(documents) == n and len(metadatas) == n, "upsert arrays length mismatch"
    if embeddings is not None:
        assert len(embeddings) == n, "embeddings length mismatch"

    coll = get_collection()

    # 충돌 회피: 동일 ID 미리 삭제(없으면 무시)
    try:
        coll.delete(ids=ids)
    except Exception:
        pass

    coll.add(
        ids=ids,
        documents=documents,
        metadatas=metadatas,
        embeddings=embeddings,  # None이면 내부 임베딩 함수가 처리
    )

def search(
    query: str = "",
    *,
    query_embeddings: Optional[List[float]] = None,
    where: Optional[Dict[str, Any]] = None,
    where_document: Optional[Dict[str, Any]] = None,
    n: int = None,
    include_docs: bool = True,
    include_metas: bool = True,
    include_ids: bool = True,
    include_distances: bool = True,
) -> Dict[str, Any]:
    """
    Chroma raw 결과를 그대로 반환하되, 디버깅/후처리용으로 'space'를 추가한다.
    - 점수(score) 계산/리랭킹은 상위 계층(metrics/adapters)에서 처리.
    - query_texts 또는 query_embeddings 중 하나만 사용.
    """
    coll = get_collection()
    if n is None:
        n = getattr(config, "TOP_K", 3)
    n = max(1, min(int(n), 100))

    if (not query) and (query_embeddings is None):
        raise ValueError("either 'query' (text) or 'query_embeddings' must be provided")

    include: List[str] = []
    if include_docs: include.append("documents")
    if include_metas: include.append("metadatas")
    if include_ids: include.append("ids")
    if include_distances: include.append("distances")

    q_kwargs: Dict[str, Any] = {
        "n_results": n,
        "include": include or None,
    }
    if where: q_kwargs["where"] = where
    if where_document: q_kwargs["where_document"] = where_document

    if query_embeddings is not None:
        # 이미 계산된 쿼리 임베딩 사용
        q_kwargs["query_embeddings"] = [query_embeddings]
    else:
        q_kwargs["query_texts"] = [query]

    res = coll.query(**q_kwargs)

    # 상위 계층에서 metric 변환/평탄화를 할 수 있도록 space를 싣는다.
    return {
        "space": _space(),
        **res,
    }