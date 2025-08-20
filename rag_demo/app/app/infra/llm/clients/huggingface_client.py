# Embeding model

from sentence_transformers import SentenceTransformer
import numpy as np
from typing import List
from configure.config import EMBED_MODEL

_model = None

def get_model():
    global _model
    if _model is None:
        # 최초 1회 다운로드 필요. 이후 로컬 캐시 사용
        _model = SentenceTransformer(EMBED_MODEL, trust_remote_code=True)
    return _model

def embed_texts(texts: List[str]) -> np.ndarray:
    model = get_model()
    # bge-m3는 단문/장문 모두 OK
    embs = model.encode(texts, normalize_embeddings=True, batch_size=32, show_progress_bar=False)
    return np.asarray(embs, dtype="float32")
