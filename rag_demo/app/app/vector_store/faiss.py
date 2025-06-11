from sentence_transformers import SentenceTransformer
import faiss
import numpy as np

model = SentenceTransformer("all-MiniLM-L6-v2")

#TODO: 인덱스 로딩, 문서 벡터 매핑
index = faiss.indexFlatL2(384)

def embed(text: str):
    return model.encode([text])[0]

def get_relevant_docs(question:str, top_k=3):
    q_vettor = embed(question)
    D, I = index.search(np.array([q_vettor]), top_k)
    #TODO 결과 문서 반환
    return [{"text":f"문서 {i} 내용"} for i in I[0]]