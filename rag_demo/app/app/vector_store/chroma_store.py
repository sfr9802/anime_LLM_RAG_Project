from __future__ import annotations
import chromadb
from app.configure.config import settings

_client: chromadb.Client | None = None
_coll = None

def get_collection():
    global _client, _coll
    if _client is None:
        _client = chromadb.PersistentClient(path=settings.CHROMA_PATH)
    if _coll is None:
        _coll = _client.get_or_create_collection(settings.CHROMA_COLLECTION)
    return _coll

def upsert(ids, documents, metadatas, embeddings):
    coll = get_collection()
    # 동일 id 존재 시 충돌 방지
    try:
        coll.delete(ids=ids)
    except Exception:
        pass
    coll.add(ids=ids, documents=documents, metadatas=metadatas, embeddings=embeddings)
