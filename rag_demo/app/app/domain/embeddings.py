# app/domain/embeddings.py
from __future__ import annotations
from typing import List, Optional, Literal, Callable, Any, Dict
import os
import numpy as np
import sys as _sys
# 너의 프로젝트에서 쓰일 수 있는 모든 경로 별칭을 통일
for _alias in (
    "app.app.domain.embeddings",  # RagService가 쓰는 경로
    "app.domain.embeddings",
):
    if _alias != __name__:
        _sys.modules.setdefault(_alias, _sys.modules[__name__])
# ──────────────────────────────────────────────────────────────────────────────
# 설정 로딩 (config 모듈 우선, 없으면 환경변수)
# ──────────────────────────────────────────────────────────────────────────────
try:
    from configure import config as _cfg  # type: ignore
except Exception:
    class _Dummy: ...
    _cfg = _Dummy()

def _get(name: str, default: Any) -> Any:
    if hasattr(_cfg, name):
        return getattr(_cfg, name)
    env_name = {
        "EMBED_BACKEND": "RAG_EMBEDDER",
        "EMBED_MODEL": "RAG_EMBED_MODEL",
        "EMBED_DIM": "RAG_EMBED_DIM",
        "EMBED_BATCH": "RAG_EMBED_BATCH",
        "EMBED_DEVICE": "RAG_EMBED_DEVICE",
        "EMBED_USE_PREFIX": "RAG_EMBED_USE_PREFIX",
        "EMBED_TRUST_REMOTE_CODE": "RAG_EMBED_TRUST_REMOTE_CODE",
        "OPENAI_API_KEY": "OPENAI_API_KEY",
        "OPENAI_EMBED_MODEL": "OPENAI_EMBED_MODEL",
    }.get(name)
    if env_name:
        v = os.getenv(env_name)
        if v is not None:
            if name in {"EMBED_DIM", "EMBED_BATCH"}:
                try: return int(v)
                except Exception: return default
            if name in {"EMBED_USE_PREFIX", "EMBED_TRUST_REMOTE_CODE"}:
                return str(v).lower() in {"1","true","yes","y"}
            return v
    return default

# 백엔드: fake | sbert | e5 | bge-m3 | openai
EMBED_BACKEND: Literal["fake","sbert","e5","bge-m3","openai"] = str(_get("EMBED_BACKEND", "bge-m3")).lower()
EMBED_MODEL: str = _get("EMBED_MODEL", "BAAI/bge-m3")
EMBED_DIM: int = int(_get("EMBED_DIM", 0))            # 0이면 모델에서 추론/지정
EMBED_BATCH: int = int(_get("EMBED_BATCH", 128))
EMBED_DEVICE: str = _get("EMBED_DEVICE", "cuda")      # "auto" | "cuda" | "cpu"
EMBED_USE_PREFIX: bool = bool(_get("EMBED_USE_PREFIX", True))
EMBED_TRUST_REMOTE_CODE: bool = bool(_get("EMBED_TRUST_REMOTE_CODE", True))

# OpenAI (옵션)
OPENAI_API_KEY: Optional[str] = _get("OPENAI_API_KEY", None)
OPENAI_EMBED_MODEL: str = _get("OPENAI_EMBED_MODEL", "text-embedding-3-small")  # 1536

PASSAGE_PREFIX = "passage: "
QUERY_PREFIX   = "query: "

# ──────────────────────────────────────────────────────────────────────────────
# 내부 상태
# ──────────────────────────────────────────────────────────────────────────────
_MODEL: Any = None
_BACKEND: str = EMBED_BACKEND
_DIM: int = EMBED_DIM  # 0이면 로드 후 결정

# ──────────────────────────────────────────────────────────────────────────────
# 유틸
# ──────────────────────────────────────────────────────────────────────────────
def _decide_device() -> str:
    if EMBED_DEVICE != "auto":
        return EMBED_DEVICE
    try:
        import torch  # type: ignore
        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        return "cpu"

def _normalize(v: np.ndarray) -> np.ndarray:
    if v.size == 0:
        return v.astype("float32")
    denom = np.linalg.norm(v, axis=1, keepdims=True) + 1e-8
    return (v / denom).astype("float32")

def _empty_matrix(dim: int) -> np.ndarray:
    dim = int(dim) if dim and dim > 0 else (1536 if _BACKEND == "openai" else 384)
    return np.zeros((0, dim), dtype="float32")

# ──────────────────────────────────────────────────────────────────────────────
# 로더들
# ──────────────────────────────────────────────────────────────────────────────
def _load_fake() -> Any:
    global _DIM
    if _DIM <= 0: _DIM = 384
    return "FAKE"

def _load_sbert() -> Any:
    global _DIM
    from sentence_transformers import SentenceTransformer
    device = _decide_device()
    m = SentenceTransformer(EMBED_MODEL, trust_remote_code=EMBED_TRUST_REMOTE_CODE, device=device)
    try:
        _DIM = int(m.get_sentence_embedding_dimension())
    except Exception:
        if _DIM <= 0: _DIM = 1024
    return m

def _load_e5() -> Any:
    return _load_sbert()

def _load_bge_m3() -> Any:
    """
    BGE-M3 dense 차원은 1024.
    """
    global _DIM
    from FlagEmbedding import BGEM3FlagModel  # pip install FlagEmbedding
    use_fp16 = _decide_device() == "cuda"
    name = EMBED_MODEL or "BAAI/bge-m3"
    m = BGEM3FlagModel(name, use_fp16=use_fp16)  # returns dict with "dense_vecs"
    _DIM = 1024
    return m

def _load_openai() -> Any:
    global _DIM
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY not set")
    try:
        from openai import OpenAI  # pip install openai>=1.0
    except Exception as e:
        raise RuntimeError("OpenAI SDK not installed: pip install openai") from e
    _DIM = 1536 if OPENAI_EMBED_MODEL.endswith("small") else (3072 if "large" in OPENAI_EMBED_MODEL else 1536)
    client = OpenAI(api_key=OPENAI_API_KEY)
    return client

_LOADER_MAP: Dict[str, Callable[[], Any]] = {
    "fake": _load_fake,
    "sbert": _load_sbert,
    "e5": _load_e5,
    "bge-m3": _load_bge_m3,
    "openai": _load_openai,
}

# ──────────────────────────────────────────────────────────────────────────────
# 인코더들
# ──────────────────────────────────────────────────────────────────────────────
def _encode_fake(texts: List[str]) -> np.ndarray:
    import hashlib
    out: list[np.ndarray] = []
    for t in texts:
        seed = int(hashlib.md5((t or "").encode("utf-8")).hexdigest(), 16) % (2**32 - 1)
        rs = np.random.default_rng(seed)
        v = rs.standard_normal(_DIM).astype("float32")
        v = v / (np.linalg.norm(v) + 1e-8)
        out.append(v)
    return np.vstack(out) if out else _empty_matrix(_DIM)

def _encode_sbert(texts: List[str]) -> np.ndarray:
    assert _MODEL is not None
    v = _MODEL.encode(
        texts,
        normalize_embeddings=True,
        batch_size=EMBED_BATCH,
        convert_to_numpy=True,
        show_progress_bar=False,
    )
    return v.astype("float32")

def _encode_bge_m3(texts: List[str]) -> np.ndarray:
    # BGEM3FlagModel.encode → {"dense_vecs": [...], "sparse_vecs": ...}
    out = _MODEL.encode(texts, batch_size=EMBED_BATCH)
    dense = np.array(out["dense_vecs"], dtype="float32")
    return _normalize(dense)

def _encode_openai(texts: List[str]) -> np.ndarray:
    resp = _MODEL.embeddings.create(model=OPENAI_EMBED_MODEL, input=texts)
    vecs = [np.array(d.embedding, dtype="float32") for d in resp.data]
    return _normalize(np.vstack(vecs)) if vecs else _empty_matrix(_DIM)

_ENCODER_MAP: Dict[str, Callable[[List[str]], np.ndarray]] = {
    "fake": _encode_fake,
    "sbert": _encode_sbert,
    "e5": _encode_sbert,
    "bge-m3": _encode_bge_m3,
    "openai": _encode_openai,
}

# ──────────────────────────────────────────────────────────────────────────────
# 퍼블릭 API
# ──────────────────────────────────────────────────────────────────────────────
def _ensure_loaded() -> None:
    global _MODEL
    if _MODEL is not None:
        return
    if _BACKEND not in _LOADER_MAP:
        raise RuntimeError(f"Unknown EMBED_BACKEND: {_BACKEND}")
    _MODEL = _LOADER_MAP[_BACKEND]()  # sets _DIM

def embedding_dim() -> int:
    _ensure_loaded()
    return int(_DIM)

def _encode(texts: List[str]) -> np.ndarray:
    _ensure_loaded()
    if not texts:
        return _empty_matrix(_DIM)
    return _ENCODER_MAP[_BACKEND](texts)

def embed_passages(texts: List[str], *, as_list: bool = False) -> np.ndarray | List[List[float]]:
    xs = [f"{PASSAGE_PREFIX}{t}" for t in texts] if EMBED_USE_PREFIX else texts
    embs = _encode(xs)
    return embs.tolist() if as_list else embs

def embed_queries(texts: List[str], *, as_list: bool = False) -> np.ndarray | List[List[float]]:
    xs = [f"{QUERY_PREFIX}{t}" for t in texts] if EMBED_USE_PREFIX else texts
    embs = _encode(xs)
    return embs.tolist() if as_list else embs

def switch_backend(backend: str, model: Optional[str] = None, dim: Optional[int] = None) -> None:
    """
    런타임 백엔드 전환(테스트/재인덱싱용).
    """
    global _BACKEND, EMBED_MODEL, _MODEL, _DIM
    _BACKEND = backend.lower()
    if model: EMBED_MODEL = model
    if dim is not None: _DIM = int(dim)
    _MODEL = None  # reload next call

# Chroma 쪽에서 .embed(list[str]) 콜 하도록 어댑터 제공
class EmbedAdapter:
    def embed(self, texts: List[str]) -> List[List[float]]:
        return embed_passages(texts, as_list=True)  # 문서(패시지) 기준
class ChromaEmbedding:
    """
    Chroma 0.5+ 호환 임베딩 어댑터.
    - name(): 식별자
    - embed_documents(texts): List[List[float]]
    - embed_query(text): List[float]
    - __call__(texts): List[List[float]]  (호환용)
    """
    def __init__(self, name: Optional[str] = None):
        # 너무 긴 모델명 줄이기
        mdl = EMBED_MODEL.rsplit("/", 1)[-1]
        self._name = name or f"{_BACKEND}:{mdl}"

    def name(self) -> str:
        return self._name

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        return embed_passages(texts, as_list=True)  # passage prefix/정규화 포함

    def embed_query(self, text: str) -> List[float]:
        return embed_queries([text], as_list=True)[0]  # query prefix/정규화 포함

    # 일부 버전은 __call__도 참조하므로 넣어줌
    def __call__(self, texts: List[str]) -> List[List[float]]:
        return self.embed_documents(texts)

def build_embedding_fn() -> ChromaEmbedding:
    """
    chroma_store에서 import해서 쓰는 엔트리포인트.
    """
    _ensure_loaded()  # 모델 로드 / 차원 확정
    return ChromaEmbedding()