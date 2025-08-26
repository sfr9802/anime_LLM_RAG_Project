import os, chromadb, torch
from FlagEmbedding import BGEM3FlagModel

client = chromadb.PersistentClient(os.getenv('CHROMA_DB_DIR'))
c = client.get_collection(os.getenv('CHROMA_COLLECTION'))

m = BGEM3FlagModel('BAAI/bge-m3',
                   use_fp16=torch.cuda.is_available(),
                   device='cuda' if torch.cuda.is_available() else 'cpu')

queries = ['귀멸의 칼날 줄거리']
q = m.encode_queries(queries)['dense_vecs'].tolist()  # (1,1024)
r = c.query(query_embeddings=q, n_results=3)

print('ids:', r['ids'][0])
for i, (doc, meta) in enumerate(zip(r['documents'][0], r.get('metadatas',[[]])[0])):
    print(f'#{i+1}', (doc or '')[:200].replace('\n',' '), meta)
