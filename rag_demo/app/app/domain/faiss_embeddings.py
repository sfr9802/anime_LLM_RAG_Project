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

    def embed_documents(
        self,
        docs: List[SimpleDocument],
        batch_size: int= 64
    ) -> List[tuple[str, np.ndarray]]:
        result : List[tuple[str, np.ndarray]] = []
        
        for i in range(0, len(docs), batch_size):
            batch = docs[i : i + batch_size]
            embed = self.model.encode(batch)
            dense_vecs = np.array(embed["dense_vecs"])
            dense_vecs = _normalize(dense_vecs)

            for j, (doc, vec) in enumerate(zip(batch, dense_vecs)) :
                doc_id = i+j
                if doc.id == None :
                    result.append((f"doc_{doc_id}", vec)) 
                else :
                    result.append((doc.id, vec))

    def embed_query(self, query: str) -> np.ndarray:
        embed = self.model.encode([query], is_query=True)
        dense = np.array(embed["dense_vecs"], dtype="float32")
        return _normalize(dense)[0]
        
