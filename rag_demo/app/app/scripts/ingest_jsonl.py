# app/scripts/ingest_jsonl.py
import argparse, json, hashlib, re, sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Iterable
from pymongo import MongoClient, UpdateOne, ASCENDING
from configure import config

# Chroma upsert (프로젝트에 이미 있음)
from infra.vector.chroma_store import upsert as chroma_upsert

# ------------------------------ utils ------------------------------
def _md5(s: str) -> str:
    return hashlib.md5(s.encode("utf-8")).hexdigest()

def _sid(doc_id: str, idx: int, text: str) -> str:
    # 재실행 안전 ID
    return f"{doc_id}:{idx}:{_md5(text)[:10]}"

def _norm_str(x: Optional[str]) -> str:
    return (x or "").strip()

def _yield_jsonl(path: Path) -> Iterable[Dict[str, Any]]:
    with path.open("r", encoding="utf-8") as f:
        for ln, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except Exception as e:
                print(f"[WARN] line {ln} JSON parse error: {e}", file=sys.stderr)

# 매우 단순 청커 (문단→문장 기준, 길이 목표로 합치기)
_SENT = re.compile(r"(?<=[.!?。？！])\s+")
def simple_chunk(text: str, target_len: int = 900, max_len: int = 1300) -> List[str]:
    paras = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks: List[str] = []
    for p in paras:
        if len(p) <= target_len:
            chunks.append(p)
            continue
        sents = _SENT.split(p)
        buf = []
        cur = 0
        for s in sents:
            s = s.strip()
            if not s: 
                continue
            if cur + len(s) + 1 > max_len and buf:
                chunks.append(" ".join(buf))
                buf, cur = [s], len(s)
            else:
                buf.append(s); cur += len(s) + 1
        if buf:
            chunks.append(" ".join(buf))
    return chunks or ([text] if text.strip() else [])

# ------------------------------ ingest ------------------------------
def ensure_indexes(raw_col, chunk_col):
    try:
        raw_col.create_index([("doc_id", ASCENDING)], unique=True, name="u_doc_id")
    except Exception: pass
    try:
        chunk_col.create_index([("doc_id", ASCENDING), ("seg_index", ASCENDING)], unique=True, name="u_doc_seg")
    except Exception: pass

def row_to_chunks(row: Dict[str, Any], min_chars: int) -> List[Dict[str, Any]]:
    title   = _norm_str(row.get("title") or row.get("document_title"))
    doc_id  = _norm_str(row.get("doc_id") or row.get("id") or _md5(json.dumps(row)[:128]))
    section_order = row.get("section_order")
    sections = row.get("sections") if isinstance(row.get("sections"), dict) else None

    # 섹션 순서 결정
    sec_names: List[str] = []
    if sections:
        if isinstance(section_order, list) and section_order:
            # 파일에 들어있는 순서 유지
            sec_names = [s for s in section_order if s in sections]
        else:
            sec_names = list(sections.keys())

    out: List[Dict[str, Any]] = []
    idx = 0

    if sections:
        for sec in sec_names:
            entry = sections.get(sec)
            # entry가 dict인 케이스(권장: {"text": "...", "urls":[...]})
            if isinstance(entry, dict):
                raw_text = _norm_str(entry.get("text"))
                url_val = entry.get("urls")
                if isinstance(url_val, list) and url_val:
                    url = _norm_str(url_val[0])
                elif isinstance(url_val, str):
                    url = _norm_str(url_val)
                else:
                    url = ""
            # entry가 문자열인 케이스도 허용
            elif isinstance(entry, str):
                raw_text = _norm_str(entry)
                url = ""
            else:
                continue

            if not raw_text:
                continue

            chunks = simple_chunk(raw_text)  # 문단/문장 기반 간단 청킹
            for t in chunks:
                t = t.strip()
                if len(t) < min_chars:
                    continue
                out.append({
                    "id": _sid(doc_id, idx, t),     # Chroma id
                    "_id": _sid(doc_id, idx, t),    # Mongo chunk PK
                    "doc_id": doc_id,
                    "seg_index": idx,
                    "text": t,
                    "title": title,
                    "url": url,
                    "section": sec,
                })
                idx += 1

    else:
        # fallback: segments/text 스키마도 지원(다른 파일 재사용 대비)
        segs = row.get("segments")
        if isinstance(segs, list) and segs:
            chunks = [_norm_str(t) for t in segs if _norm_str(t)]
        else:
            text = _norm_str(row.get("text"))
            chunks = simple_chunk(text) if text else []

        for t in chunks:
            t = t.strip()
            if len(t) < min_chars:
                continue
            out.append({
                "id": _sid(doc_id, idx, t),
                "_id": _sid(doc_id, idx, t),
                "doc_id": doc_id,
                "seg_index": idx,
                "text": t,
                "title": title,
                "url": _norm_str(row.get("url")),
                "section": _norm_str(row.get("section") or row.get("category")),
            })
            idx += 1

    return out

def ingest_jsonl(jsonl_path: Path, batch: int, min_chars: int, mongo_only: bool):
    # Mongo 연결
    mc = MongoClient(config.MONGO_URI)
    db = mc[config.MONGO_DB]
    raw_col   = db[config.MONGO_RAW_COL]
    chunk_col = db[config.MONGO_CHUNK_COL]
    ensure_indexes(raw_col, chunk_col)

    total_chunks = 0
    chroma_buf: List[Dict[str, Any]] = []
    mongo_chunk_ops: List[UpdateOne] = []
    raw_upserts = 0

    for row in _yield_jsonl(jsonl_path):
        # raw upsert (doc_id 기준, 본문 메타만 저장)
        doc_id = _norm_str(row.get("doc_id") or row.get("id") or _norm_str(row.get("url")) or _norm_str(row.get("title")))
        if doc_id:
            raw = {
                "doc_id": doc_id,
                "title": _norm_str(row.get("title") or row.get("document_title")),
                "url": _norm_str(row.get("url")),
                "section": _norm_str(row.get("section") or row.get("category")),
            }
            # 원문 text/segments는 용량폭탄 되니 저장 여부는 선택. 필요하면 아래 주석 해제.
            # raw["text"] = _norm_str(row.get("text")) if row.get("text") else None
            raw_col.update_one({"doc_id": doc_id}, {"$setOnInsert": raw}, upsert=True)
            raw_upserts += 1

        # chunks
        chunks = row_to_chunks(row, min_chars=min_chars)
        if not chunks:
            continue

        # Mongo 청크 upsert(PrimaryKey = _id)
        for c in chunks:
            mongo_chunk_ops.append(
                UpdateOne({"_id": c["_id"]}, {"$setOnInsert": c}, upsert=True)
            )

        # Chroma 업서트 버퍼
        if not mongo_only:
            for c in chunks:
                chroma_buf.append({
                    "id": c["id"],
                    "text": c["text"],
                    "meta": {
                        "doc_id": c["doc_id"],
                        "title": c["title"],
                        "seg_index": c["seg_index"],
                        "url": c["url"],
                        "section": c["section"],
                    }
                })

        # 배치 플러시
        if len(mongo_chunk_ops) >= batch:
            chunk_col.bulk_write(mongo_chunk_ops, ordered=False)
            mongo_chunk_ops.clear()
        if not mongo_only and len(chroma_buf) >= batch:
            chroma_upsert(chroma_buf)
            chroma_buf.clear()

        total_chunks += len(chunks)

    # 잔여 플러시
    if mongo_chunk_ops:
        chunk_col.bulk_write(mongo_chunk_ops, ordered=False)
    if not mongo_only and chroma_buf:
        chroma_upsert(chroma_buf)

    print(f"[OK] raw upserts tried: {raw_upserts}")
    print(f"[OK] chunks indexed:    {total_chunks}")
    print(f"[OK] chroma collection: {config.CHROMA_COLLECTION} @ {config.CHROMA_PATH}")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--jsonl", required=True, help="path to jsonl file")
    ap.add_argument("--batch", type=int, default=int(config.INDEX_BATCH if hasattr(config, 'INDEX_BATCH') else 256))
    ap.add_argument("--min-chars", type=int, default=80, help="skip chunks shorter than this")
    ap.add_argument("--mongo-only", action="store_true", help="only write to Mongo, skip Chroma")
    args = ap.parse_args()

    path = Path(args.jsonl)
    if not path.exists():
        print(f"[ERR] not found: {path}")
        sys.exit(1)

    ingest_jsonl(path, batch=args.batch, min_chars=args.min_chars, mongo_only=args.mongo_only)

if __name__ == "__main__":
    main()
