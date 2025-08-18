# rag_demo/app/app/domain/embeddings.py
from __future__ import annotations
from typing import List, Optional, Literal, Callable, Any, Dict
import os
import numpy as np

# ──────────────────────────────────────────────────────────────────────────────
# 설정 로딩 (config 모듈이 있으면 우선, 없으면 환경변수 fallback)
# ──────────────────────────────────────────────────────────────────────────────
try:
    from configure import config as _cfg
except Exception:
    class _Dummy:
        pass
    _cfg = _Dummy()

def _get(name: str, default: Any) -> Any:
    # config.X 가 있으면 우선 사용, 없으면 환경변수 → 기본값
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
                try:
                    return int(v)
                except Exception:
                    return default
            if name in {"EMBED_USE_PREFIX", "EMBED_TRUST_REMOTE_CODE"}:
                return str(v).lower() in {"1","true","yes","y"}
            return v
    return default

# 백엔드: fake | sbert | e5 | bge-m3 | openai
EMBED_BACKEND: Literal["fake","sbert","e5","bge-m3","openai"] = _get("EMBED_BACKEND", "sbert").lower()
EMBED_MODEL: str = _get("EMBED_MODEL", "intfloat/multilingual-e5-base")  # sbert/e5 기본
EMBED_DIM: int = int(_get("EMBED_DIM", 0))  # 0이면 모델에서 추론
EMBED_BATCH: int = int(_get("EMBED_BATCH", 32))
EMBED_DEVICE: str = _get("EMBED_DEVICE", "auto")  # "auto" | "cuda" | "cpu"
EMBED_USE_PREFIX: bool = bool(_get("EMBED_USE_PREFIX", True))
EMBED_TRUST_REMOTE_CODE: bool = bool(_get("EMBED_TRUST_REMOTE_CODE", True))

# OpenAI (옵션)
OPENAI_API_KEY: Optional[str] = _get("OPENAI_API_KEY", None)
OPENAI_EMBED_MODEL: str = _get("OPENAI_EMBED_MODEL", "text-embedding-3-small")  # 1536차원

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
        import torch
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
    if _DIM <= 0:
        _DIM = 384
    return "FAKE"

def _load_sbert() -> Any:
    global _DIM
    from sentence_transformers import SentenceTransformer
    device = _decide_device()
    m = SentenceTransformer(EMBED_MODEL, trust_remote_code=EMBED_TRUST_REMOTE_CODE, device=device)
    try:
        _DIM = m.get_sentence_embedding_dimension()
    except Exception:
        # 대개는 지원함. 혹시 몰라서 fallback
        _DIM = 768 if _DIM <= 0 else _DIM
    return m

def _load_e5() -> Any:
    # sbert 경로 그대로 씀 (모델만 e5)
    return _load_sbert()

def _load_bge_m3() -> Any:
    global _DIM
    # pip install FlagEmbedding
    from FlagEmbedding import BGEM3FlagModel
    use_fp16 = _decide_device() == "cuda"
    m = BGEM3FlagModel(EMBED_MODEL or "BAAI/bge-m3", use_fp16=use_fp16)
    _DIM = 1024  # bge-m3 dense dim
    return m

def _load_openai() -> Any:
    global _DIM
    # pip install openai>=1.0.0
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY not set")
    try:
        from openai import OpenAI
    except Exception as e:
        raise RuntimeError("OpenAI SDK not installed: pip install openai") from e
    _DIM = 1536 if OPENAI_EMBED_MODEL.endswith("small") else 3072 if "large" in OPENAI_EMBED_MODEL else 1536
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
    # 안정 해시 기반 의사난수 → 재현성 있음
    import hashlib
    rngs = [int(hashlib.md5((t or "").encode("utf-8")).hexdigest(), 16) % (2**32 - 1) for t in texts]
    out = []
    for seed in rngs:
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
    # dense only
    out = _MODEL.encode(texts, batch_size=EMBED_BATCH)
    dense = out["dense_vecs"]
    return _normalize(np.array(dense, dtype="float32"))

def _encode_openai(texts: List[str]) -> np.ndarray:
    # one API call per batch (SDK가 max input에 따라 적절히 배치 필요할 수도 있음)
    # 여기서는 간단히 한 번에 요청 → 길면 upstream에서 나눠라.
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
    _MODEL = _LOADER_MAP[_BACKEND]()  # sets _DIM as needed

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
    런타임에 백엔드 전환(테스트/재인덱싱용).
    backend: "fake"|"sbert"|"e5"|"bge-m3"|"openai"
    """
    global _BACKEND, EMBED_MODEL, _MODEL, _DIM
    _BACKEND = backend.lower()
    if model:
        EMBED_MODEL = model
    if dim is not None:
        _DIM = int(dim)
    _MODEL = None  # reload on next call

def embed_passages(texts: List[str], as_list: bool = False):
    embs = _encode([f"passage: {t}" for t in texts])
    return embs.tolist() if as_list else embs

def embed_queries(texts: List[str], as_list: bool = False):
    embs = _encode([f"query: {t}" for t in texts])
    return embs.tolist() if as_list else embs