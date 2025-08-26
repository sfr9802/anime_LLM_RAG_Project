import os, chromadb
from chromadb.utils import embedding_functions

client = chromadb.PersistentClient(os.getenv('CHROMA_DB_DIR'))
ef = embedding_functions.SentenceTransformerEmbeddingFunction(model_name='BAAI/bge-m3')  # 1024D
c = client.get_collection(os.getenv('CHROMA_COLLECTION'), embedding_function=ef)

r = c.query(query_texts=['귀멸의 칼날 줄거리'], n_results=3)
print('ids:', r['ids'][0])
print('preview:', [ (d or '')[:160].replace('\n',' ') for d in r['documents'][0] ])
