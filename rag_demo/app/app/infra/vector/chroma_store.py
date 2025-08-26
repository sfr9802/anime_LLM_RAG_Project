from __future__ import annotations
from typing import Dict, Any, List, Optional, Callable
import os, threading, shutil, logging

# ── 텔레메트리 완전 차단(임포트 전에) ────────────────────────────────────────
os.environ.setdefault("ANONYMIZED_TELEMETRY", "FALSE")
os.environ.setdefault("OTEL_SDK_DISABLED", "true")

import chromadb
from chromadb.config import Settings

# 프로젝트 설정
import app.app.configure.config as config
# 파일 상단 import 아래 아무데나 추가
import json

def _sanitize_value(v):
    if v is None:
        return None
    if isinstance(v, (str, int, float, bool)):
        return v
    if isinstance(v, (list, tuple)):
        # 리스트는 문자열로 합치거나 json 문자열로 변환
        try:
            return ",".join("" if x is None else str(x) for x in v)
        except Exception:
            return json.dumps(v, ensure_ascii=False)
    # dict/기타 → json 문자열
    try:
        return json.dumps(v, ensure_ascii=False)
    except Exception:
        return str(v)

def _sanitize_meta(meta: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for k, v in (meta or {}).items():
        sv = _sanitize_value(v)
        if sv is None:
            continue
        out[str(k)] = sv
    return out

log = logging.getLogger("chroma_store")

_client: Optional[chromadb.Client] = None
_coll: Optional[Any] = None
_lock = threading.Lock()

# ── helpers ──────────────────────────────────────────────────────────────────
def _db_path() -> str:
    # env 최우선 → config → 기본값
    return (
        os.getenv("CHROMA_DB_DIR")
        or getattr(config, "CHROMA_DB_DIR", None)
        or os.getenv("CHROMA_PATH")
        or getattr(config, "CHROMA_PATH", "./data/chroma")
    )

def _col_name() -> str:
    return getattr(config, "CHROMA_COLLECTION", "namu_anime_v3")

def _space() -> str:
    return str(getattr(config, "CHROMA_SPACE", "cosine")).lower()

def _top_k_default() -> int:
    try:
        return int(getattr(config, "TOP_K", 8))
    except Exception:
        return 8

def _new_client(path: str) -> chromadb.Client:
    os.makedirs(path, exist_ok=True)
    log.info(f"[Chroma] init PersistentClient path={path}")
    return chromadb.PersistentClient(
        path=path,
        settings=Settings(
            anonymized_telemetry=False,  # 추가 방어
            allow_reset=True,
        ),
    )

def _ensure_client_and_collection() -> None:
    global _client, _coll
    if _client is not None and _coll is not None:
        return
    with _lock:
        if _client is None:
            _client = _new_client(_db_path())
        if _coll is None:
            name = _col_name()
            space = _space()
            log.info(f"[Chroma] get_or_create_collection name={name} space={space}")
            _coll = _client.get_or_create_collection(
                name=name,
                metadata={"hnsw:space": space},
            )

# ── public api ───────────────────────────────────────────────────────────────
def get_collection():
    _ensure_client_and_collection()
    return _coll

def reset_collection() -> None:
    """컬렉션만 삭제 후 재생성(폴더 유지). 깨졌으면 hard_reset_persist_dir()을 써라."""
    global _client, _coll
    with _lock:
        if _client is None:
            _client = _new_client(_db_path())
        try:
            log.info(f"[Chroma] delete_collection name={_col_name()}")
            _client.delete_collection(_col_name())
        except Exception as e:
            log.warning(f"[Chroma] delete_collection ignored: {e}")
        _coll = _client.get_or_create_collection(
            name=_col_name(),
            metadata={"hnsw:space": _space()},
        )

def hard_reset_persist_dir() -> None:
    """저장 폴더 자체를 날리고 완전 초기화. (_type 에러 등 깨졌을 때 사용)"""
    global _client, _coll
    path = _db_path()
    log.warning(f"[Chroma] HARD RESET path={path}")
    try:
        shutil.rmtree(path, ignore_errors=True)
    finally:
        os.makedirs(path, exist_ok=True)
    _client = None
    _coll = None
    _ensure_client_and_collection()

def upsert(
    ids: List[str],
    documents: List[str],
    metadatas: List[Dict[str, Any]],
    embeddings: Optional[List[List[float]]] = None,
) -> None:
    n = len(ids)
    if n == 0:
        return
    assert len(documents) == n and len(metadatas) == n, "upsert arrays length mismatch"
    if embeddings is not None:
        assert len(embeddings) == n, "embeddings length mismatch"

    coll = get_collection()

    # 동일 ID 선삭제(없으면 무시)
    try:
        coll.delete(ids=ids)
    except Exception:
        pass

    coll.add(
        ids=ids,
        documents=documents,
        metadatas=metadatas,
        embeddings=embeddings,
    )

def upsert_batch(
    batch: List[tuple[str, str, Dict[str, Any]]],
    embedder: Callable[[List[str]], List[List[float]]] | Any,
    *,
    id_prefix: str | None = None,
) -> None:
    if not batch:
        return
    ids: List[str] = []
    docs: List[str] = []
    metas: List[Dict[str, Any]] = []

    for i, (doc_id, text, meta) in enumerate(batch):
        pid = f"{id_prefix}|" if id_prefix else ""
        ids.append(f"{pid}{doc_id}|{meta.get('section','')}|{i}")
        docs.append(text)
        metas.append(_sanitize_meta(meta))

    if hasattr(embedder, "embed"):
        embs = embedder.embed(docs)
    else:
        embs = embedder(docs)

    upsert(ids, docs, metas, embs)

def search(
    query: str = "",
    *,
    query_embeddings: Optional[List[float]] = None,
    where: Optional[Dict[str, Any]] = None,
    where_document: Optional[Dict[str, Any]] = None,
    n: Optional[int] = None,
    include_docs: bool = True,
    include_metas: bool = True,
    include_ids: bool = True,
    include_distances: bool = True,
) -> Dict[str, Any]:
    coll = get_collection()
    k = _top_k_default() if n is None else max(1, min(int(n), 100))

    if (not query) and (query_embeddings is None):
        raise ValueError("either 'query' (text) or 'query_embeddings' must be provided")

    include: List[str] = []
    if include_docs: include.append("documents")
    if include_metas: include.append("metadatas")
    if include_ids: include.append("ids")
    if include_distances: include.append("distances")

    q_kwargs: Dict[str, Any] = {"n_results": k, "include": include or None}
    if where: q_kwargs["where"] = where
    if where_document: q_kwargs["where_document"] = where_document

    if query_embeddings is not None:
        q_kwargs["query_embeddings"] = [query_embeddings]
    else:
        q_kwargs["query_texts"] = [query]

    res = coll.query(**q_kwargs)
    return {"space": _space(), **res}
