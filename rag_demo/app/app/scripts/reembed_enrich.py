# app/app/scripts/reembed_enrich.py
from __future__ import annotations
import os, itertools
from app.app.infra.vector.chroma_store import get_collection, create_collection
from rag_demo.app.app.domain.chroma_embeddings import embed_passages

SRC = os.getenv("SRC_COLLECTION", "namu_anime_v3")
DST = os.getenv("DST_COLLECTION", "namu_anime_v3_enriched")
BATCH = int(os.getenv("BATCH", "800"))

def _aliases(md):
  acc = []
  for k in ("aliases","aliases_norm"):
    v = md.get(k)
    if isinstance(v, list): acc.extend([x for x in v if x])
  for k in ("aliases_csv","aliases_norm_csv","alt_title","original_title"):
    v = md.get(k)
    if isinstance(v, str): acc.extend([x.strip() for x in v.split("|") if x.strip()])
  # 고유 유지 & 길이 제한
  seen, out = set(), []
  for a in acc:
    a = a.strip()
    if len(a) < 2 or a.lower() in seen: continue
    seen.add(a.lower()); out.append(a)
    if len(out) >= 5: break
  return out

def _enrich(doc, md):
  title = (md.get("title") or md.get("seed_title") or "").strip()
  aliases = _aliases(md)
  head = []
  if title: head.append(f"[TITLE] {title}")
  if aliases: head.append(f"[ALIASES] {', '.join(aliases)}")
  if not head: return doc or ""
  return f"{' '.join(head)}\n{doc or ''}"

def main():
  src = get_collection()              # 현재 CHROMA_COLLECTION이 SRC여야 함
  dst = create_collection(DST)        # 새 컬렉션 생성(같은 space/EF 모드)
  total = src.count()
  print(f"[enrich] src={SRC} count={total} -> dst={DST}")

  offset = 0
  while True:
    got = src.get(include=["documents","metadatas"], limit=BATCH, offset=offset)
    ids = got.get("ids") or []
    if not ids: break
    docs = got.get("documents") or []
    metas = got.get("metadatas") or []

    enriched = [_enrich(d, (m or {})) for d, m in zip(docs, metas)]
    embs = embed_passages(enriched, as_list=True)
    dst.add(ids=ids, documents=enriched, metadatas=metas, embeddings=embs)

    offset += len(ids)
    if offset % (BATCH*10) == 0: print(f"[enrich] moved {offset}/{total}")
  print("[enrich] done.")

if __name__ == "__main__":
  main()
