# app/vector_store/ingest.py
from __future__ import annotations
from typing import Dict, Any, Iterable, List, Tuple
import re, hashlib
from pymongo import MongoClient
from configure import config
from rag_demo.app.app.domain.embeddings import embed_passages
from vector_store.chroma_store import upsert

_ws = re.compile(r"\s+")
def _clean(s: str) -> str:
    return _ws.sub(" ", (s or "").replace("\u200b"," ").replace("\ufeff"," ")).strip()

def _is_noise(s: str) -> bool:
    if not s or len(s.strip()) < 10:
        return True
    # 라틴 글자 비율 높으면 노이즈로 간주(가벼운 휴리스틱)
    latin = sum(ch.isascii() and ch.isalpha() for ch in s)
    ratio = latin / max(1, len(s))
    if ratio > 0.6:
        return True
    # 뉴스/스크랩 잔재 흔한 패턴 제거
    if "Google" in s or "日 언론" in s:
        return True
    return False

def _stable_id(url: str, idx: int) -> str:
    h = hashlib.md5(f"{url}#{idx}".encode("utf-8")).hexdigest()[:16]
    return f"{h}#{idx}"

def ingest_prechunked(records: Iterable[Dict[str, Any]], dry_run: bool = False):
    """
    records: {
      "title": str, "url": str, "parent": Optional[str],
      "metadata": {..., "seed_title": str}, "chunks": List[str]
    }
    """
    mc = MongoClient(config.MONGO_URI)
    pages = mc[config.MONGO_DB][config.MONGO_RAW_COL]

    B = config.INDEX_BATCH
    buf_ids: List[str] = []
    buf_meta: List[Dict[str, Any]] = []
    buf_txt: List[str] = []
    pushed = 0
    inserted = 0

    for r in records:
        url = r.get("url") or ""
        parent = r.get("parent")
        title = r.get("title") or ""
        seed = (r.get("metadata") or {}).get("seed_title") or title

        # section / title 정규화
        if parent and (title in ("등장인물", "캐릭터", "인물", "설정", "평가")):
            section, proper_title = title, parent
        else:
            section, proper_title = "본문", title

        chunks: List[str] = [ _clean(c) for c in (r.get("chunks") or []) ]
        chunks = [c for c in chunks if not _is_noise(c)]

        full_text = " ".join(chunks)
        page_doc = {
            "url": url,
            "title": proper_title,
            "section": section,
            "seed": seed,
            "text": full_text,
            "meta": r.get("metadata") or {}
        }

        if not dry_run:
            # upsert by url+section
            pages.update_one(
                {"url": url, "section": section},
                {"$set": page_doc},
                upsert=True
            )
            inserted += 1

        # 바로 Chroma 배치 구성
        for i, ctext in enumerate(chunks):
            cid = _stable_id(url, i)
            meta = {"url": url, "title": proper_title, "section": section, "seed": seed}
            buf_ids.append(cid); buf_meta.append(meta); buf_txt.append(ctext)
            if len(buf_ids) >= B:
                embs = embed_passages(buf_txt)
                upsert(buf_ids, buf_txt, buf_meta, embs)
                pushed += len(buf_ids)
                buf_ids, buf_meta, buf_txt = [], [], []

    if buf_ids:
        embs = embed_passages(buf_txt)
        upsert(buf_ids, buf_txt, buf_meta, embs)
        pushed += len(buf_ids)

    print(f"[prechunked] mongo upsert pages: {inserted}, chroma indexed chunks: {pushed}")
