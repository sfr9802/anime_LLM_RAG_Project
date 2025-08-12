from __future__ import annotations
from typing import List
import numpy as np
import torch
from sentence_transformers import SentenceTransformer
from configure import config


_model: SentenceTransformer | None = None

def get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        device = "cuda" if torch.cuda.is_available() else "cpu"
        _model = SentenceTransformer(config.EMBED_MODEL, trust_remote_code=True, device=device)
    return _model

def _encode(texts: List[str]) -> np.ndarray:
    if not texts:
        return np.zeros((0, 3), dtype="float32")
    m = get_model()
    embs = m.encode(
        texts,
        normalize_embeddings=True,
        batch_size=config.EMBED_BATCH,
        convert_to_numpy=True,
        show_progress_bar=False,
    )
    return embs.astype("float32")

def embed_passages(texts: List[str]) -> np.ndarray:
    # bge-m3 권장: 문서 앞에 'passage: '
    return _encode([f"passage: {t}" for t in texts])

def embed_queries(texts: List[str]) -> np.ndarray:
    # bge-m3 권장: 쿼리 앞에 'query: '
    return _encode([f"query: {t}" for t in texts])
