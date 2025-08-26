from __future__ import annotations
import argparse, json, hashlib
from typing import Dict, Any, List, Tuple

from app.app.infra.vector.chroma_store import (
    upsert_batch,
    reset_collection,
    hard_reset_persist_dir,
)
from app.app.domain.embeddings import EmbedAdapter

# 선택적: 고급 청킹이 있으면 사용
def _load_chunker():
    try:
        from app.app.domain.chunker import chunk_text  # (text, max_tokens=...) -> list[Chunk]
        return ("token", chunk_text)
    except Exception:
        return ("chars", None)

def _id_of(title: str) -> str:
    return hashlib.sha1((title or "").strip().encode("utf-8")).hexdigest()[:24]

def _extract_text_and_sections(d: Dict[str, Any]) -> Tuple[str, List[str]]:
    secs = d.get("sections") or {}
    y = secs.get("요약") or {}
    parts: List[str] = []
    if isinstance(y, dict):
        for key in ("text",):
            if y.get(key): parts.append(y[key])
        if not parts and isinstance(y.get("bullets"), list):
            parts.append("\n".join([str(b) for b in y["bullets"] if b]))
        if not parts and isinstance(y.get("chunks"), list):
            parts.append("\n".join([str(c) for c in y["chunks"] if c]))

    # fallback: 다른 섹션 전부 긁기 (text|content|summary 순)
    if not parts:
        for k, v in secs.items():
            if k == "요약": continue
            if isinstance(v, list):
                for it in v:
                    if not isinstance(it, dict): continue
                    for cand in ("text", "content", "summary"):
                        if it.get(cand):
                            parts.append(str(it[cand]))
                            break

    full = "\n\n".join([p for p in parts if p and p.strip()])
    return full, list(secs.keys())

def _chunk_fallback(text: str, max_chars: int = 2000) -> List[Tuple[str, Dict[str, Any]]]:
    """chunker 미탑재 시 문자 기준 청킹."""
    out: List[Tuple[str, Dict[str, Any]]] = []
    if not text: return out
    s = 0
    i = 0
    n = len(text)
    while s < n:
        e = min(s + max_chars, n)
        out.append((text[s:e], {"section": "요약/본문", "subsection": f"part-{i}"}))
        s = e
        i += 1
    return out

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True, help="v3 JSONL path")
    ap.add_argument("--batch", type=int, default=1000)
    ap.add_argument("--max-chars", type=int, default=2000, help="fallback chunk size (chars)")
    ap.add_argument("--reset", action="store_true", help="drop & recreate collection before ingest")
    args = ap.parse_args()

    # 깨진 sysdb(_type 오류) 방지: --reset이면 폴더 통째 초기화
    if args.reset:
        try:
            hard_reset_persist_dir()
        except Exception:
            # permission 등으로 실패하면 소프트 리셋이라도
            reset_collection()

    mode, chunker = _load_chunker()
    embedder = EmbedAdapter()

    staged: List[tuple[str, str, Dict[str, Any]]] = []
    total_docs = 0
    total_chunks = 0

    with open(args.input, "r", encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            title = d.get("title") or (d.get("metadata") or {}).get("seed_title")
            if not title: continue
            doc_id = d.get("doc_id") or _id_of(title)
            text, sections_present = _extract_text_and_sections(d)
            if not text: continue

            base_meta = {
                "doc_id": doc_id,
                "title": title,
                "seed_title": (d.get("metadata") or {}).get("seed_title") or "",
                "url": d.get("url") or "",
                "parent": d.get("parent") or "",
                # 리스트는 문자열로
                "sections_present": ",".join([str(s) for s in sections_present if s]) if sections_present else "",
            }


            # 청킹
            if mode == "token" and chunker is not None:
                try:
                    chunks = []
                    for ch in chunker(text, max_tokens=480):
                        m = dict(base_meta)
                        sec = getattr(ch, "meta", {}).get("section") if hasattr(ch, "meta") else None
                        sub = getattr(ch, "meta", {}).get("subsection") if hasattr(ch, "meta") else None
                        m.update({"section": sec or "요약/본문", "subsection": sub or ""})
                        chunks.append((doc_id, getattr(ch, "text", None) or str(ch), m))
                except Exception:
                    chunks = []
                    for text_piece, m2 in _chunk_fallback(text, args.max_chars):
                        m = dict(base_meta); m.update(m2)
                        chunks.append((doc_id, text_piece, m))
            else:
                chunks = []
                for text_piece, m2 in _chunk_fallback(text, args.max_chars):
                    m = dict(base_meta); m.update(m2)
                    chunks.append((doc_id, text_piece, m))

            staged.extend(chunks)
            total_docs += 1
            total_chunks += len(chunks)

            # 배치 업서트
            if len(staged) >= args.batch:
                try:
                    upsert_batch(staged, embedder, id_prefix=None)
                except KeyError as e:
                    if "_type" in str(e):
                        hard_reset_persist_dir()
                        upsert_batch(staged, embedder, id_prefix=None)
                    else:
                        raise
                staged.clear()

    if staged:
        try:
            upsert_batch(staged, embedder, id_prefix=None)
        except KeyError as e:
            if "_type" in str(e):
                hard_reset_persist_dir()
                upsert_batch(staged, embedder, id_prefix=None)
            else:
                raise
        staged.clear()

    print(f"[INGEST DONE] docs={total_docs} chunks={total_chunks} mode={mode}")

if __name__ == "__main__":
    main()
