from sentence_transformers import SentenceTransformer
import faiss
import numpy as np
from app.app.infra.mongo import mongo_client 
from bson import ObjectId
from dotenv import load_dotenv
import os

load_dotenv(".env.best_title", override=True)

DEFAULT_TUNING = {
    "k" = int(os.getenv("RAG_DEFUALT_K", 8)),
}

id_map = {}
texts = []
object_ids = []

model = SentenceTransformer("all-MiniLM-L6-v2")

#TODO: 인덱스 로딩, 문서 벡터 매핑
index = faiss.IndexFlatL2(384)

def embed(text: str):
    return model.encode([text])[0]

def init_index():
    global id_map

    col = mongo_client.get_collection()
    docs = list(col.find())

    texts = [doc['text'] for doc in docs]
    object_ids = [doc['_id'] for doc in docs]

    vectors = np.array([embed(t) for t in texts]).astype('float32')  # faiss는 float32만 됨!
    index.add(vectors)

    id_map = {i: str(oid) for i, oid in enumerate(object_ids)}

def get_docs_by_ids(id_list):
    col = mongo_client.get_collection()
    object_ids = [ObjectId(i) for i in id_list]
    return list(col.find({"_id": {"$in": object_ids}}))

def get_relevant_docs(question: str, top_k=3):
    if index.ntotal == 0:
        raise ValueError("FAISS index is empty. Call init_index() first.")

    q_vector = embed(question).astype('float32')
    D, I = index.search(np.array([q_vector]), top_k)
    matched_ids = [id_map[i] for i in I[0]]
    return get_docs_by_ids(matched_ids)

