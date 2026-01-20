# app/app/infra/vector/chroma_store.py
from __future__ import annotations
from typing import Dict, Any, List, Optional, Callable
import os, threading, shutil, logging, importlib, json, inspect
from urllib.parse import quote

# 텔레메트리 차단
os.environ.setdefault("ANONYMIZED_TELEMETRY", "FALSE")
os.environ.setdefault("OTEL_SDK_DISABLED", "true")

import chromadb
from chromadb.config import Settings

# 프로젝트 설정
import app.app.configure.config as config
# 프로젝트 임베딩 빌더(Chroma 호환 객체 반환: name/embed_documents/embed_query 권장)
from app.app.domain.chroma_embeddings import build_embedding_fn

log = logging.getLogger("chroma_store")

# ───────────── consts ─────────────
_VALID_INCLUDE = {"documents", "embeddings", "metadatas", "distances", "uris", "data"}

# ───────────── sanitize ─────────────
def _sanitize_value(v):
    """
    메타데이터 값 정리:
    - 기본 스칼라(str/int/float/bool)는 그대로 유지
    - list/tuple/dict는 JSON 직렬화 가능한 경우 그대로 유지(배열/객체 where 쿼리 보존)
      * tuple은 list로 변환
    - 나머지는 JSON 문자열로 폴백
    """
    if v is None or isinstance(v, (str, int, float, bool)):
        return v
    if isinstance(v, tuple):
        v = list(v)
    if isinstance(v, (list, dict)):
        try:
            json.dumps(v, ensure_ascii=False)
            return v
        except Exception:
            return json.dumps(v, ensure_ascii=False)
    try:
        json.dumps(v, ensure_ascii=False)
        return v
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

# ───────────── globals ─────────────
_client: Optional[chromadb.Client] = None
_coll: Optional[Any] = None
_COLL_SPACE: Optional[str] = None  # actual space read from collection metadata
_lock = threading.Lock()
_EMBED_FN: Any = None  # 최종적으로 Chroma가 허용하는 EF 객체
_EMBED_FN_LOCK = threading.Lock()

# ───────────── config helpers ─────────────
def _db_path() -> str:
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

def _read_space_from_collection(coll: Any) -> Optional[str]:
    """Best-effort: read actual hnsw space from collection metadata.

    Returns lowercased space (e.g. 'cosine' | 'l2' | 'ip') or None if unknown.
    """
    try:
        meta = getattr(coll, 'metadata', None)
        meta = meta() if callable(meta) else meta
        if isinstance(meta, dict):
            sp = meta.get('hnsw:space') or meta.get('hnsw_space')
            if sp:
                return str(sp).lower()
    except Exception:
        pass
    return None

def _collection_space() -> str:
    """Return actual collection space if available; otherwise fall back to config.

    Cached for the default collection to avoid repeated attribute lookups.
    """
    global _COLL_SPACE
    if _COLL_SPACE:
        return _COLL_SPACE
    try:
        coll = get_collection()
        sp = _read_space_from_collection(coll)
    except Exception:
        sp = None
    _COLL_SPACE = sp or _space()
    return _COLL_SPACE

def _top_k_default() -> int:
    try:
        return int(getattr(config, "TOP_K", 8))
    except Exception:
        return 8

def _attach_ef_mode() -> str:
    """
    yes | no | auto (기본 auto)
    - yes : EF 반드시 부착 (인덱서/재임베딩)
    - no  : EF 없이 오픈 (서버 권장)
    - auto: 시도 후 실패/충돌시 EF 없이 폴백
    """
    v = (os.getenv("CHROMA_ATTACH_EF") or "auto").strip().lower()
    return v if v in {"yes","no","auto"} else "auto"

# ───────────── embed fn loader ─────────────
def _torch_cuda() -> bool:
    try:
        import torch
        return bool(torch.cuda.is_available())
    except Exception:
        return False

class _EmbeddingAdapter:
    """함수형 임베더를 Chroma EF 인터페이스로 감싼다."""
    def __init__(self, fn: Callable[[List[str]], List[List[float]]], name: str = "local-embed"):
        self._fn = fn
        self._name = name
    def name(self) -> str: return self._name
    def embed_documents(self, texts: List[str]) -> List[List[float]]: return self._fn(texts)
    def embed_query(self, text: str) -> List[float]: return self._fn([text])[0]
    # Chroma 0.4.16+ 는 파라미터명 'input' 을 검사한다.
    def __call__(self, input: List[str]) -> List[List[float]]:  # noqa: A003
        return self._fn(input)

class _WrapToChromaEF:
    """
    빌더가 반환한 객체가 __call__(input)이 없거나 시그니처가 다르면
    안전하게 감싸서 반환.
    """
    def __init__(self, inner: Any, name_fallback: str = "local-embed"):
        self._inner = inner
        self._name_fb = name_fallback
    def name(self) -> str:
        f = getattr(self._inner, "name", None)
        try:
            return f() if callable(f) else (f or self._name_fb)
        except Exception:
            return self._name_fb
    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        f = getattr(self._inner, "embed_documents", None)
        if callable(f):
            return f(texts)
        # 최후: embed_query를 돌려서 문서배열 처리
        q = getattr(self._inner, "embed_query", None)
        if callable(q):
            return [q(t) for t in texts]
        raise RuntimeError("inner embedder lacks embed_documents/embed_query")
    def embed_query(self, text: str) -> List[float]:
        q = getattr(self._inner, "embed_query", None)
        if callable(q):
            return q(text)
        # 문서 인코더만 있으면 한 개만 추출
        d = getattr(self._inner, "embed_documents", None)
        if callable(d):
            return d([text])[0]
        raise RuntimeError("inner embedder lacks embed_query/embed_documents")
    def __call__(self, input: List[str]) -> List[List[float]]:  # noqa: A003
        # __call__은 문서배열 인코딩과 동일
        return self.embed_documents(input)

def _get_embed_fn():
    """Chroma가 기대하는 EF 객체(name/embed_documents/embed_query/__call__(input)) 반환"""
    global _EMBED_FN
    if _EMBED_FN is not None:
        return _EMBED_FN

    with _EMBED_FN_LOCK:
        if _EMBED_FN is not None:
            return _EMBED_FN

        # 1) CHROMA_EMBED_FN="pkg.mod:factory" 우선
        dotted = os.getenv("CHROMA_EMBED_FN", "").strip()
        if dotted:
            try:
                mod, attr = dotted.split(":")
                factory = getattr(importlib.import_module(mod), attr)
                obj = factory() if callable(factory) else factory
                # 부족하면 래핑
                needs_wrap = not hasattr(obj, "__call__") or "input" not in str(inspect.signature(obj.__call__).parameters)
                if needs_wrap:
                    obj = _WrapToChromaEF(obj)
                _EMBED_FN = obj
                log.info(f"[Chroma] using custom embed fn: {dotted}")
                return _EMBED_FN
            except Exception as e:
                log.warning(f"[Chroma] CHROMA_EMBED_FN load failed: {e}")

        # 2) 프로젝트 표준 빌더(권장)
        try:
            obj = build_embedding_fn()
            needs_wrap = (not hasattr(obj, "__call__")) or ("input" not in str(inspect.signature(obj.__call__).parameters))
            if needs_wrap:
                obj = _WrapToChromaEF(obj)
            _EMBED_FN = obj
            log.info("[Chroma] using project build_embedding_fn()")
            return _EMBED_FN
        except Exception as e:
            log.warning(f"[Chroma] project build_embedding_fn() not available: {e}")

        # 3) SentenceTransformer 폴백(최후)
        from sentence_transformers import SentenceTransformer
        model_name = os.getenv("RAG_EMBED_MODEL", "BAAI/bge-m3")
        device = os.getenv("RAG_EMBED_DEVICE", "auto").lower()
        batch = int(os.getenv("RAG_EMBED_BATCH", "64"))
        # normalize 토글: true(기본)면 코사인 등가, false면 IP에서 크기 보존
        norm = (os.getenv("RAG_EMBED_NORMALIZE", "true").lower() != "false")
        if device == "auto":
            device = "cuda" if _torch_cuda() else "cpu"
        log.info(f"[Chroma] fallback ST model={model_name} device={device} batch={batch} normalize={norm}")
        st = SentenceTransformer(model_name, device=device)

        def _fn(texts: List[str]) -> List[List[float]]:
            vecs = st.encode(list(texts), batch_size=batch, normalize_embeddings=norm, convert_to_numpy=True)
            return vecs.tolist()

        _EMBED_FN = _EmbeddingAdapter(_fn, name=f"sbert:{model_name.rsplit('/',1)[-1]}")
        return _EMBED_FN

# ───────────── client/collection ─────────────
def _new_client(path: str) -> chromadb.Client:
    os.makedirs(path, exist_ok=True)
    log.info(f"[Chroma] init PersistentClient path={path}")
    return chromadb.PersistentClient(
        path=path,
        settings=Settings(
            anonymized_telemetry=False,
            allow_reset=True,
        ),
    )

def _open_with_mode(cli: chromadb.Client, name: str, space: str, mode: str):
    """모드에 따라 EF 부착/무부착 오픈."""
    if mode == "no":
        log.info("[Chroma] opening collection WITHOUT EF (mode=no)")
        try:
            return cli.get_collection(name)
        except Exception:
            return cli.get_or_create_collection(name=name, metadata={"hnsw:space": space})

    # yes/auto
    ef = _get_embed_fn()
    try:
        return cli.get_or_create_collection(
            name=name, metadata={"hnsw:space": space}, embedding_function=ef
        )
    except ValueError as e:
        # Chroma 버전에 따라 메시지가 달라짐 → auto에선 넓게 폴백
        if mode == "auto":
            log.warning(f"[Chroma] EF attach failed ({e}); opening WITHOUT EF (mode=auto)")
            try:
                return cli.get_collection(name)
            except Exception:
                return cli.get_or_create_collection(name=name, metadata={"hnsw:space": space})
        raise

def _ensure_client_and_collection() -> None:
    """기본 컬렉션을 준비. 모드에 따라 EF 부착/무부착."""
    global _client, _coll, _COLL_SPACE
    if _client is not None and _coll is not None:
        return
    with _lock:
        if _client is None:
            _client = _new_client(_db_path())
        if _coll is None:
            name = _col_name()
            space = _space()
            mode = _attach_ef_mode()
            log.info(f"[Chroma] get_or_create_collection name={name} space={space} mode={mode}")
            _coll = _open_with_mode(_client, name, space, mode)
            # read actual space from collection metadata (may differ from config for existing collections)
            global _COLL_SPACE
            _COLL_SPACE = _read_space_from_collection(_coll) or space

def _get_client() -> chromadb.Client:
    global _client
    if _client is None:
        _client = _new_client(_db_path())
    return _client

def create_collection(name: str, *, space: Optional[str] = None):
    """새 컬렉션 생성. 모드에 따라 EF 부착/무부착."""
    cli = _get_client()
    return _open_with_mode(cli, name, (space or _space()), _attach_ef_mode())

# ───────────── public api ─────────────
def get_collection():
    _ensure_client_and_collection()
    return _coll

def reset_collection() -> None:
    """컬렉션만 삭제 후 재생성(폴더 유지)."""
    global _client, _coll, _COLL_SPACE
    with _lock:
        if _client is None:
            _client = _new_client(_db_path())
        try:
            log.info(f"[Chroma] delete_collection name={_col_name()}")
            _client.delete_collection(_col_name())
        except Exception as e:
            log.warning(f"[Chroma] delete_collection ignored: {e}")
        mode = _attach_ef_mode()
        _coll = _open_with_mode(_client, _col_name(), _space(), mode)
        _COLL_SPACE = _read_space_from_collection(_coll) or _space()

def hard_reset_persist_dir() -> None:
    """저장 폴더 자체를 날리고 완전 초기화."""
    global _client, _coll, _COLL_SPACE
    path = _db_path()
    log.warning(f"[Chroma] HARD RESET path={path}")
    try:
        shutil.rmtree(path, ignore_errors=True)
    finally:
        os.makedirs(path, exist_ok=True)
    _client = None
    _coll = None
    global _COLL_SPACE
    _COLL_SPACE = None
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
        metadatas=[_sanitize_meta(m) for m in metadatas],
        embeddings=embeddings,  # None이면 collection EF 사용
    )

def upsert_batch(
    batch: List[tuple[str, str, Dict[str, Any]]],
    embedder: Callable[[List[str]], List[List[float]]] | Any = None,
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
        # 섹션에 구분자 충돌 가능 → URL-safe 인코딩
        section_safe = quote(str(meta.get("section","")), safe="")
        ids.append(f"{pid}{doc_id}|{section_safe}|{i}")
        docs.append(text)
        metas.append(_sanitize_meta(meta))

    emb_fn = (
        embedder.embed if hasattr(embedder, "embed")
        else (embedder if callable(embedder) else _get_embed_fn())
    )
    embs = emb_fn(docs)
    upsert(ids, docs, metas, embs)

def _build_include(include_docs: bool,
                   include_metas: bool,
                   include_distances: bool,
                   include_embeddings: bool) -> Optional[List[str]]:
    include: List[str] = []
    if include_docs:       include.append("documents")
    if include_metas:      include.append("metadatas")
    if include_distances:  include.append("distances")
    if include_embeddings: include.append("embeddings")  # ← 추가
    if not include:
        return None
    return [x for x in include if x in _VALID_INCLUDE] or None

def search(
    query: str = "",
    *,
    query_embeddings: Optional[List[float]] = None,
    where: Optional[Dict[str, Any]] = None,
    where_document: Optional[Dict[str, Any]] = None,
    n: Optional[int] = None,
    include_docs: bool = True,
    include_metas: bool = True,
    include_ids: bool = True,  # 유지하되 무시(Chroma 0.5+에선 include로 금지; ids는 항상 반환)
    include_distances: bool = True,
    include_embeddings: bool = False,   # ← 추가
) -> Dict[str, Any]:
    """
    기본: query_texts(컬렉션 EF 경유)
    실패 시: 직접 임베딩해서 query_embeddings로 폴백
    """
    coll = get_collection()
    k = _top_k_default() if n is None else max(1, min(int(n), 100))

    if (not query) and (query_embeddings is None):
        raise ValueError("either 'query' (text) or 'query_embeddings' must be provided")

    include = _build_include(include_docs, include_metas, include_distances, include_embeddings)
    if include_ids:
        log.debug("[Chroma] include_ids=True (ignored; ids are returned by default)")

    q_kwargs: Dict[str, Any] = {"n_results": k}
    if include: q_kwargs["include"] = include
    if where: q_kwargs["where"] = where
    if where_document: q_kwargs["where_document"] = where_document

    # 1) 클라이언트가 임베딩을 넘긴 경우
    if query_embeddings is not None:
        q_kwargs["query_embeddings"] = [query_embeddings]
        res = coll.query(**q_kwargs)
        return {"space": _collection_space(), **res}

    # 2) 텍스트 → EF 경유 시도, 실패 시 직접 임베딩 폴백
    try:
        q_kwargs["query_texts"] = [query]
        res = coll.query(**q_kwargs)
        return {"space": _collection_space(), **res}
    except Exception as e:
        log.warning(f"[Chroma] query_texts failed, fallback to query_embeddings: {e}")
        emb_obj = _get_embed_fn()
        try:
            emb = emb_obj.embed_query(query)  # 객체형
        except AttributeError:
            emb = emb_obj([query])[0]         # 함수형 어댑터
        q_kwargs.pop("query_texts", None)
        q_kwargs["query_embeddings"] = [emb]
        res = coll.query(**q_kwargs)
        return {"space": _collection_space(), **res}

# ───────────── migration utils ─────────────
def reembed_to_new_collection(
    src_name: str,
    dst_name: str,
    *,
    batch_limit: int = 1000,
    log_every: int = 5000,
) -> dict:
    """
    기존 컬렉션(src)에서 문서를 읽어 새 컬렉션(dst)에 재임베딩 후 add().
    """
    cli = _get_client()
    src = cli.get_collection(src_name)  # 기존: EF 유무 상관없음(읽기만)
    dst = create_collection(dst_name, space=_space())  # 새: 모드에 따라 EF 부착

    emb = _get_embed_fn()
    total = 0
    offset = 0
    while True:
        got = src.get(include=["documents", "metadatas"], limit=batch_limit, offset=offset)
        ids = got.get("ids") or []
        if not ids:
            break
        docs = got.get("documents") or []
        metas = got.get("metadatas") or []

        try:
            embs = emb.embed_documents(docs)
        except AttributeError:
            embs = emb(docs)

        dst.add(
            ids=ids,
            documents=docs,
            metadatas=[_sanitize_meta(m) for m in metas],
            embeddings=embs,
        )

        offset += len(ids)
        total += len(ids)
        if total and (total % log_every == 0):
            log.info(f"[migrate] moved {total} items...")

    src_cnt = src.count()
    dst_cnt = dst.count()
    log.info(f"[migrate] done: src={src_cnt}, dst={dst_cnt}, moved={total}")
    return {"src": src_name, "dst": dst_name, "moved": total, "src_count": src_cnt, "dst_count": dst_cnt}
