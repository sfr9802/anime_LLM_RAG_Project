# embedding/embedder.py

import numpy as np
from typing import List
from dataclasses import dataclass
import os
from .utils import _normalize

DEVICE = os.getenv("RAG_EMBED_DEVICE", "cuda")

@dataclass
class SimpleDocument:
    id: str
    text: str
    metadata: dict


class FaissEmbedder:
    def __init__(self, model_name: str):
        self.model_name = model_name
        self.model = self._load_model()
        self.dim = 1024  # 모델 dim 저장 (bge-m3 기준)

    def _load_model(self):
        from FlagEmbedding import BGEM3FlagModel
        name = "BAAI/bge-m3"
        model = BGEM3FlagModel(name, use_fp16=DEVICE)
        return model

    def embed_documents(self, docs: List[SimpleDocument]) -> np.ndarray:
        embed = self.model.encode(docs, batch_size= 1024)
        dense = np.array(embed["dense_vecs"], dtype="float32")
        return _normalize(dense)

    def embed_query(self, query: str) -> np.ndarray:
        
        
        pass
