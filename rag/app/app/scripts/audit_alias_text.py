# app/app/scripts/audit_alias_text.py
from app.app.infra.vector.chroma_store import get_collection
def has_alias_in_text(sample=1000):
    coll = get_collection()
    got = coll.peek(sample)
    docs = got["documents"] or []
    metas = got["metadatas"] or []
    hit = 0
    for d, m in zip(docs, metas):
        aliases = m.get("aliases") or m.get("aliases_csv") or ""
        if not aliases: continue
        if isinstance(aliases, list):
            ak = [a for a in aliases if a]
        else:
            ak = [x.strip() for x in str(aliases).split("|") if x.strip()]
        if not ak: continue
        if any(a.lower() in (d or "").lower() for a in ak[:3]):
            hit += 1
    print(f"[alias-in-text] docs containing any alias (top3): {hit}/{len(docs)}")
if __name__ == "__main__":
    has_alias_in_text()
