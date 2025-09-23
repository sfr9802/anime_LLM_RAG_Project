# app/vector_store/ingest.py
from __future__ import annotations
from typing import Dict, Any, Iterable, List, Tuple
import re, hashlib, time
from pymongo import MongoClient, UpdateOne
from pymongo.errors import PyMongoError
from configure import config
from rag_demo.app.app.domain.chroma_embeddings import embed_passages
from infra.vector.chroma_store import upsert

_ws = re.compile(r"\s+")

SECTION_ALIASES = {
    "등장인물": "등장인물", "캐릭터": "등장인물", "인물": "등장인물",
    "설정": "설정", "세계관": "설정",
    "평가": "평가", "반응": "평가",
    "줄거리": "줄거리", "개요": "줄거리", "시놉시스": "줄거리",
    "에피소드": "에피소드", "방영": "방영", "방영 정보": "방영",
}

def _clean(s: str) -> str:
    return _ws.sub(" ", (s or "").replace("\u200b"," ").replace("\ufeff"," ")).strip()

def _is_noise(s: str) -> bool:
    if not s or len(s.strip()) < 10:
        return True
    txt = s.strip()
    # 라틴 비율(문자만) 계산
    letters = [ch for ch in txt if ch.isalpha()]
    if letters:
        latin = sum(ch.isascii() for ch in letters)
        ratio = latin / max(1, len(letters))
        if ratio > 0.7:  # 좀 더 보수적으로
            return True
    # 흔한 스크랩 패턴
    low = txt.lower()
    if "google" in low:
        return True
    if "日 언론" in txt or "日언론" in txt:
        return True
    return False

def _stable_id(url: str, idx: int, ctext: str) -> str:
    # url+idx+내용 해시를 섞어서 재청크에도 의미-벡터 불일치 최소화
    h = hashlib.md5(f"{url}#{idx}::{ctext}".encode("utf-8")).hexdigest()[:24]
    return f"{h}_{idx}"

def _norm_section(title: str, parent: str|None) -> Tuple[str, str]:
    if parent:
        key = title.strip()
        norm = SECTION_ALIASES.get(key, None)
        if norm:
            return norm, parent
    return "본문", title or (parent or "")

def _ensure_indexes(pages):
    # url+section 유니크 인덱스
    try:
        pages.create_index([("url", 1), ("section", 1)], unique=True, name="u_url_section")
    except Exception:
        pass

def _flush_to_chroma(ids: List[str], txts: List[str], metas: List[Dict[str, Any]], retries: int = 3):
    if not ids:
        return 0
    for attempt in range(retries):
        try:
            embs = embed_passages(txts)  # 내부에서 배치 처리한다고 가정
            upsert(ids, txts, metas, embs)
            return len(ids)
        except Exception as e:
            if attempt == retries - 1:
                raise
            time.sleep(0.8 * (attempt + 1))
    return 0

def ingest_prechunked(records: Iterable[Dict[str, Any]], dry_run: bool = False):
    """
    records: {
      "title": str, "url": str, "parent": Optional[str],
      "metadata": {..., "seed_title": str}, "chunks": List[str]
    }
    """
    mc = MongoClient(config.MONGO_URI)
    pages = mc[config.MONGO_DB][config.MONGO_RAW_COL]
    _ensure_indexes(pages)

    B = getattr(config, "INDEX_BATCH", 128)
    mongo_ops: List[UpdateOne] = []

    buf_ids: List[str] = []
    buf_meta: List[Dict[str, Any]] = []
    buf_txt: List[str] = []

    pushed = 0
    inserted = 0

    for r in records:
        url = (r.get("url") or "").strip()
        parent = r.get("parent")
        title = (r.get("title") or "").strip()
        seed = (r.get("metadata") or {}).get("seed_title") or title

        section, proper_title = _norm_section(title, parent)

        chunks: List[str] = [ _clean(c) for c in (r.get("chunks") or []) ]
        chunks = [c for c in chunks if not _is_noise(c)]

        if not chunks:
            # 빈 페이지는 Mongo/Chroma 모두 스킵
            continue

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
            mongo_ops.append(
                UpdateOne({"url": url, "section": section}, {"$set": page_doc}, upsert=True)
            )
            if len(mongo_ops) >= 1000:
                try:
                    res = pages.bulk_write(mongo_ops, ordered=False)
                    inserted += (res.upserted_count or 0) + (res.modified_count or 0)
                except PyMongoError:
                    # 실패하더라도 다음 배치 시 재시도 기회가 있음
                    pass
                finally:
                    mongo_ops = []

        # Chroma 배치 구성 (dry_run이면 완전히 건너뜀)
        if not dry_run:
            for i, ctext in enumerate(chunks):
                cid = _stable_id(url, i, ctext)
                meta = {"url": url, "title": proper_title, "section": section, "seed": seed}
                buf_ids.append(cid); buf_meta.append(meta); buf_txt.append(ctext)
                if len(buf_ids) >= B:
                    pushed += _flush_to_chroma(buf_ids, buf_txt, buf_meta)
                    buf_ids.clear(); buf_meta.clear(); buf_txt.clear()

    # 남은 Mongo 배치 플러시
    if not dry_run and mongo_ops:
        try:
            res = pages.bulk_write(mongo_ops, ordered=False)
            inserted += (res.upserted_count or 0) + (res.modified_count or 0)
        except PyMongoError:
            pass
        finally:
            mongo_ops = []

    # 남은 Chroma 배치 플러시
    if not dry_run and buf_ids:
        pushed += _flush_to_chroma(buf_ids, buf_txt, buf_meta)

    print(f"[prechunked] mongo upsert pages: {inserted}, chroma indexed chunks: {pushed}")
