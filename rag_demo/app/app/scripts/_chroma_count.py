import os, chromadb, statistics as stats
path = os.getenv('CHROMA_DB_DIR','./chroma_db')
coll = os.getenv('CHROMA_COLLECTION','namu_anime_v3')
client = chromadb.PersistentClient(path)
c = client.get_collection(coll)
cnt = c.count()
g = c.get(limit=100)
lens = [len(d) for d in (g.get('documents',[[]])[0] or []) if d]
print(f'collection={c.name}  path={path}')
print('count:', cnt)
if lens:
    print('doc_len: min/median/mean/max =', min(lens), int(stats.median(lens)), int(stats.mean(lens)), max(lens))
else:
    print('doc_len: N/A')
