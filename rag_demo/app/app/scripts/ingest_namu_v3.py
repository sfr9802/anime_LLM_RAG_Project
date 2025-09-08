# -*- coding: utf-8 -*-
from __future__ import annotations
import argparse, json, hashlib, re, unicodedata
from typing import Dict, Any, List, Tuple

from ..infra.vector.chroma_store import (
    upsert_batch,
    reset_collection,
    hard_reset_persist_dir,
)
from ..domain.embeddings import EmbedAdapter

# ---- 정규화 & 별칭 유틸 -------------------------------------------------
def _norm(s: str) -> str:
    if not s: return ""
    s = unicodedata.normalize("NFKC", s).lower()
    return re.sub(r"[\s\W_]+", "", s, flags=re.UNICODE)

def _strip_paren(s: str) -> str:
    return re.sub(r"\s*\([^)]*\)\s*", " ", s or "").strip()

def _aliases_from_title(title: str, seed: str | None) -> List[str]:
    cands = []
    for t in [title, seed or ""]:
        t = (t or "").strip()
        if not t: continue
        cands += [
            t, _strip_paren(t),                      # 괄호부제 제거
            re.sub(r"\s+", "", t),                  # 공백 제거
            re.sub(r"[\s\W_]+", "", t),             # 기호 제거
            re.sub(r"[^0-9a-zA-Z가-힣]+", "", t),    # 과격 정규화
        ]
    seen, out = set(), []
    for x in cands:
        x = x.strip()
        if len(x) < 2: continue
        if x in seen: continue
        seen.add(x); out.append(x)
    return out

# ---- 섹션 표준화 & 추출 --------------------------------------------------
_STD_SECS = {
    "요약": "요약",
    "개요": "요약",
    "줄거리": "본문",
    "본문": "본문",
    "등장인물": "등장인물",
    "설정": "설정",
    "평가": "평가",
    # 동의어
    "소개": "요약",
    "시놉시스": "본문",
    "스토리": "본문",
    "인물": "등장인물",
    "캐릭터": "등장인물",
    "세계관": "설정",
    "반응": "평가",
}
def _std_section_name(k: str) -> str:
    return _STD_SECS.get(k, k if k in ("요약","본문","등장인물","설정","평가") else "본문")

def _extract_section_texts(d: Dict[str, Any]) -> List[Tuple[str, str]]:
    """
    반환: [(section, text), ...] — ‘요약’ 우선, 그 외 섹션 전부 포함
    """
    secs = d.get("sections") or {}
    out: List[Tuple[str, str]] = []

    # 1) 요약
    y = secs.get("요약") or {}
    if isinstance(y, dict):
        buf = []
        if y.get("text"): buf.append(str(y["text"]))
        if isinstance(y.get("bullets"), list): buf.append("\n".join(str(b) for b in y["bullets"] if b))
        if isinstance(y.get("chunks"), list): buf.append("\n".join(str(c) for c in y["chunks"] if c))
        ytxt = "\n\n".join([t for t in buf if t and t.strip()])
        if ytxt: out.append(("요약", ytxt))

    # 2) 그 외 섹션 전부
    for k, v in secs.items():
        if k == "요약": continue
        sec = _std_section_name(k)
        if isinstance(v, dict):
            buf = []
            for cand in ("text","content","summary"):
                if v.get(cand): buf.append(str(v[cand]))
            if isinstance(v.get("chunks"), list):
                buf.append("\n".join(str(c) for c in v["chunks"] if c))
            txt = "\n\n".join([t for t in buf if t and t.strip()])
            if txt: out.append((sec, txt))
        elif isinstance(v, list):
            parts = []
            for it in v:
                if not isinstance(it, dict): continue
                for cand in ("text","content","summary"):
                    if it.get(cand):
                        parts.append(str(it[cand])); break
            if parts:
                out.append((sec, "\n\n".join(parts)))
    return out

# ---- 청커 로더 -----------------------------------------------------------
def _load_chunker():
    try:
        from ..domain.chunker import fast_chunk as _fx
        return ("fast", _fx)
    except Exception:
        try:
            from ..domain.chunker import make_chunks as _mk
            return ("make", _mk)
        except Exception:
            try:
                from ..domain.chunker import chunk_text as _ct
                return ("token", _ct)
            except Exception:
                return ("chars", None)

def _chunk_fallback(text: str, max_chars: int = 1200, overlap: int = 200) -> List[str]:
    out: List[str] = []
    if not text: return out
    n, s = len(text), 0
    while s < n:
        e = min(s + max_chars, n)
        out.append(text[s:e])
        if e >= n: break
        s = max(0, e - overlap)
    return out

# ---- 메타 스칼라 ----------------------------------------------------------
import json as _json
def _to_scalar(v):
    if isinstance(v, (str, int, float, bool)) or v is None:
        return v
    if isinstance(v, list):
        return "|".join(str(x) for x in v)
    if isinstance(v, dict):
        return _json.dumps(v, ensure_ascii=False, separators=(",", ":"))
    return str(v)

# ---- ID ------------------------------------------------------------------
def _id_of(title: str) -> str:
    return hashlib.sha1((title or "").strip().encode("utf-8")).hexdigest()[:24]

# ---- MAIN ----------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True, help="v3 JSONL path")
    ap.add_argument("--batch", type=int, default=800)
    ap.add_argument("--max-chars", type=int, default=1200, help="fallback chunk size (chars)")
    ap.add_argument("--overlap", type=int, default=200, help="fallback chunk overlap (chars)")
    ap.add_argument("--reset", action="store_true", help="drop & recreate collection before ingest")
    ap.add_argument("--with-header", action="store_true",
                    help="청크 본문 앞에 '[title] · [section]' 헤더를 텍스트로도 삽입(기본 off)")
    args = ap.parse_args()

    if args.reset:
        try:
            hard_reset_persist_dir()
        except Exception:
            reset_collection()

    mode, chunker = _load_chunker()
    embedder = EmbedAdapter()  # embeddings.py의 백엔드 설정 사용

    staged: List[tuple[str, str, Dict[str, Any]]] = []
    total_docs = 0
    total_chunks = 0
    doc_chunk_idx: Dict[str, int] = {}  # 각 문서의 청크 카운터

    with open(args.input, "r", encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            title = d.get("title") or (d.get("seed") or "")
            if not title: continue
            doc_id = d.get("doc_id") or _id_of(title)

            # 섹션 텍스트 전부 뽑기(요약+본문 등)
            sec_texts = _extract_section_texts(d)
            if not sec_texts: continue

            seed_title = d.get("seed") or d.get("title") or ""
            aliases = _aliases_from_title(title, seed_title)

            meta_base = {
                "doc_id": doc_id,
                "title": title,
                "seed_title": seed_title,
                "title_norm": _norm(title),
                "seed_title_norm": _norm(seed_title),
                "aliases_csv": "|".join(aliases),
                "aliases_norm_csv": "|".join(_norm(a) for a in aliases),
                "url": d.get("url") or "",
                "parent": d.get("parent") or "",
                "sections_present": ",".join(sorted({s for s, _ in sec_texts})),
            }

            try:
                if mode == "token":
                    for section, raw in sec_texts:
                        header = f"[{title}] · [{section}]\n" if args.with_header else ""
                        for ch in chunker(header + raw, max_tokens=480, stride=120):
                            piece = getattr(ch, "text", None) or str(ch)
                            idx = doc_chunk_idx.get(doc_id, 0); doc_chunk_idx[doc_id] = idx + 1
                            chunk_hash = hashlib.sha1(piece.encode("utf-8")).hexdigest()[:8]
                            vid = f"{doc_id}:{section}:{idx:04d}:{chunk_hash}"

                            m = dict(meta_base)
                            m.update({"section": section, "subsection": getattr(ch, "meta", {}).get("subsection",""),
                                      "chunk_id": f"{idx:04d}"})
                            m = {k: _to_scalar(v) for k, v in m.items()}
                            staged.append((vid, piece, m))

                elif mode == "make":
                    for section, raw in sec_texts:
                        for sec, piece in chunker(raw, section=section, attach_header=args.with_header):
                            idx = doc_chunk_idx.get(doc_id, 0); doc_chunk_idx[doc_id] = idx + 1
                            chunk_hash = hashlib.sha1(piece.encode("utf-8")).hexdigest()[:8]
                            vid = f"{doc_id}:{sec}:{idx:04d}:{chunk_hash}"

                            m = dict(meta_base); m.update({"section": sec, "subsection": "", "chunk_id": f"{idx:04d}"})
                            m = {k: _to_scalar(v) for k, v in m.items()}
                            staged.append((vid, piece, m))

                elif mode == "fast":
                    for section, raw in sec_texts:
                        for sec, piece in chunker(raw, section=section, target=900, max_chars=1600, overlap=150,
                                                  attach_header=args.with_header):
                            idx = doc_chunk_idx.get(doc_id, 0); doc_chunk_idx[doc_id] = idx + 1
                            chunk_hash = hashlib.sha1(piece.encode("utf-8")).hexdigest()[:8]
                            vid = f"{doc_id}:{sec}:{idx:04d}:{chunk_hash}"

                            m = dict(meta_base); m.update({"section": sec, "subsection": "", "chunk_id": f"{idx:04d}"})
                            m = {k: _to_scalar(v) for k, v in m.items()}
                            staged.append((vid, piece, m))

                else:
                    # 문자 폴백
                    for section, raw in sec_texts:
                        header = f"[{title}] · [{section}]\n" if args.with_header else ""
                        for piece in _chunk_fallback(header + raw, args.max_chars, args.overlap):
                            idx = doc_chunk_idx.get(doc_id, 0); doc_chunk_idx[doc_id] = idx + 1
                            chunk_hash = hashlib.sha1(piece.encode("utf-8")).hexdigest()[:8]
                            vid = f"{doc_id}:{section}:{idx:04d}:{chunk_hash}"

                            m = dict(meta_base); m.update({"section": section, "subsection": "", "chunk_id": f"{idx:04d}"})
                            m = {k: _to_scalar(v) for k, v in m.items()}
                            staged.append((vid, piece, m))

            except Exception:
                # 완전 폴백
                for section, raw in sec_texts:
                    header = f"[{title}] · [{section}]\n" if args.with_header else ""
                    for piece in _chunk_fallback(header + raw, args.max_chars, args.overlap):
                        idx = doc_chunk_idx.get(doc_id, 0); doc_chunk_idx[doc_id] = idx + 1
                        chunk_hash = hashlib.sha1(piece.encode("utf-8")).hexdigest()[:8]
                        vid = f"{doc_id}:{section}:{idx:04d}:{chunk_hash}"

                        m = dict(meta_base); m.update({"section": section, "subsection": "", "chunk_id": f"{idx:04d}"})
                        m = {k: _to_scalar(v) for k, v in m.items()}
                        staged.append((vid, piece, m))

            total_docs += 1

            if len(staged) >= args.batch:
                upsert_batch(staged, embedder, id_prefix=None)
                total_chunks += len(staged)
                staged.clear()

    if staged:
        upsert_batch(staged, embedder, id_prefix=None)
        total_chunks += len(staged)
        staged.clear()

    print(f"[INGEST DONE] docs={total_docs} chunks={total_chunks} mode={mode}")

if __name__ == "__main__":
    main()
