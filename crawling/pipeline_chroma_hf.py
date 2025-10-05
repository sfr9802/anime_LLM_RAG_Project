#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
입력 JSONL(문서 단위)을 섹션 단위로 정리하고,
요약이 부족한 항목만 로컬 LLM으로 재요약한 뒤 병합,
본문을 청킹하여 Chroma에 upsert,
또한 HF 업로드용 섹션/청크 JSONL 산출.

- 스키마 화이트리스트: ["요약","본문","등장인물","설정","줄거리","평가"]
- 요약 재생성 기준: summary_len<120 or bullet_count!=5 or missing
- 요약 입력 상한: 6000 chars
- 청킹: 대충 문장 경계 고려한 greedy character chunk (기본 750~900, overlap 120)
"""

import os, sys, json, re, hashlib, time, argparse
from typing import Dict, Any, Iterable, List, Tuple, Optional
from collections import Counter, defaultdict

# ----- optional deps (lazy import) -----
def _lazy_req():
    import requests
    return requests

def _lazy_chroma(embed_model: str):
    import chromadb
    from chromadb import PersistentClient
    try:
        # new helper (chroma>=0.5)
        from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction
        emb_fn = SentenceTransformerEmbeddingFunction(model_name=embed_model)
        return PersistentClient, emb_fn
    except Exception:
        # fallback: manual embed fn via sentence-transformers
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer(embed_model)
        class _EF:
            def __call__(self, inputs: List[str]) -> List[List[float]]:
                return model.encode(inputs, normalize_embeddings=True).tolist()
        return chromadb.PersistentClient, _EF()

# ----- defaults -----
KEEP_SECTIONS = {"요약","본문","등장인물","설정","줄거리","평가"}
SUM_MAX_CHARS = 6000
BULLET_TARGET = 5

# ----- text utils -----
_SENT_SPLIT = re.compile(r"(?<=[\.!?…])\s+|(?<=다\.)\s+")
_WS = re.compile(r"\s+")

def split_sentences(text: str) -> List[str]:
    return [s.strip() for s in _SENT_SPLIT.split(text) if s and s.strip()]

def greedy_chunks(text: str, min_len=750, max_len=900, overlap=120) -> List[str]:
    """문장 경계 가급적 유지하는 문자 기반 청킹."""
    sents = split_sentences(text)
    out, buf, cur = [], [], 0
    for s in sents:
        s_len = len(s) + 1
        if cur + s_len <= max_len:
            buf.append(s); cur += s_len
        else:
            if cur >= min_len:
                out.append(" ".join(buf))
                # overlap
                back = " ".join(buf)
                if overlap > 0 and len(back) > overlap:
                    tail = back[-overlap:]
                    buf, cur = [tail, s], len(tail) + s_len
                else:
                    buf, cur = [s], s_len
            else:
                out.append(" ".join(buf))
                buf, cur = [s], s_len
    if buf:
        out.append(" ".join(buf))
    return [t.strip() for t in out if t and t.strip()]

# ----- id helpers -----
def stable_id(seed: str, title: str) -> str:
    base = (seed or "") + "||" + (title or "")
    return hashlib.md5(base.encode("utf-8")).hexdigest()

def pick_title(obj: Dict[str,Any]) -> str:
    return (obj.get("meta",{}).get("seed_title")
            or obj.get("seed")
            or obj.get("title")
            or "")

def pick_source_url(obj: Dict[str,Any], sec_name: str, sec_obj: Dict[str,Any]) -> Optional[str]:
    urls = []
    if isinstance(sec_obj, dict):
        u = sec_obj.get("urls")
        if isinstance(u, list) and u:
            urls = u
    if not urls:
        body = obj.get("sections", {}).get("본문", {})
        if isinstance(body, dict):
            u = body.get("urls")
            if isinstance(u, list) and u:
                urls = u
    for k in ["url","source_url","link"]:
        v = obj.get(k)
        if isinstance(v, str) and v:
            urls = [v]; break
    return urls[0] if urls else None

# ----- I/O -----
def read_jsonl(path: str) -> Iterable[Dict[str,Any]]:
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line=line.strip()
            if not line: continue
            try:
                yield json.loads(line)
            except Exception:
                continue

def write_jsonl(path: str, rows: Iterable[Dict[str,Any]]):
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False)+"\n")

# ----- cleaning / flattening -----
def flatten_sections(src_path: str, sum_max_chars=SUM_MAX_CHARS):
    section_rows = []
    section_counts = Counter()
    bad_keys = Counter()
    title_overwrite = 0

    # metrics to decide resummarize
    by_doc_summary_len = {}
    by_doc_bullets = {}
    by_doc_has_summary = {}
    by_doc_body_len = {}
    titles = {}

    for obj in read_jsonl(src_path):
        title = pick_title(obj)
        if title and obj.get("title") != title:
            title_overwrite += 1
        doc_id = obj.get("doc_id") or stable_id(obj.get("seed",""), title)
        titles[doc_id] = title

        sections = obj.get("sections", {})
        if not isinstance(sections, dict):
            sections = {}

        # collect weird keys
        for k in list(sections.keys()):
            if k not in KEEP_SECTIONS:
                bad_keys[k] += 1

        for name, sec in sections.items():
            if name not in KEEP_SECTIONS:
                continue
            if not isinstance(sec, dict):
                sec = {}

            # map fields
            text_val = sec.get("text")
            summary_val = None
            bullets_val = None
            summary_model = None

            if name == "요약":
                summary_val = sec.get("summary") or sec.get("text") or None
                bullets = sec.get("bullets")
                if isinstance(bullets, list): bullets_val = bullets
                summary_model = sec.get("model") or obj.get("summary_model")

            rec = {
                "doc_id": doc_id,
                "title": title,
                "seed": obj.get("seed"),
                "section": name,
                "text": (text_val if name!="요약" else None),
                "summary": summary_val,
                "bullets": bullets_val,
                "summary_model": (summary_model if name=="요약" else None),
                "summary_params": ({"max_input_chars": sum_max_chars, "style":"ko-5-bullets"} if name=="요약" else None),
                "source_url": pick_source_url(obj, name, sec),
                "source": "namu",
                "language": "ko",
                "fetched_at": obj.get("meta",{}).get("fetched_at"),
                "created_at": obj.get("created_at"),
            }
            section_rows.append(rec)
            section_counts[name] += 1

            if name == "요약":
                s = (summary_val or "")
                by_doc_summary_len[doc_id] = len(s)
                bc = len(bullets_val) if isinstance(bullets_val, list) else 0
                by_doc_bullets[doc_id] = bc
                by_doc_has_summary[doc_id] = (len(s)>0 or bc>0)

            if name == "본문":
                t = (text_val or "")
                by_doc_body_len[doc_id] = len(t)

    return {
        "rows": section_rows,
        "stats": {
            "section_counts": dict(section_counts),
            "bad_keys": bad_keys.most_common(20),
            "title_overwrite": title_overwrite,
        },
        "metrics": {
            "titles": titles,
            "summary_len": by_doc_summary_len,
            "bullet_count": by_doc_bullets,
            "has_summary": by_doc_has_summary,
            "body_len": by_doc_body_len,
        }
    }

# ----- resummarization target selection -----
def select_resum_targets(metrics, min_body=300, min_sum_len=120, bullet_target=BULLET_TARGET):
    rows = []
    titles = metrics["titles"]
    body_len = metrics["body_len"]
    sum_len = metrics["summary_len"]
    bullets = metrics["bullet_count"]
    has_sum = metrics["has_summary"]

    for did, title in titles.items():
        bl = body_len.get(did, 0)
        if bl and bl < min_body:
            continue
        sl = sum_len.get(did, 0)
        bc = bullets.get(did, 0)
        need = False
        reasons = []
        if not has_sum.get(did, False):
            need = True; reasons.append("missing_summary")
        if sl < min_sum_len:
            need = True; reasons.append(f"short_summary({sl})")
        if bc != bullet_target:
            need = True; reasons.append(f"bullet_count={bc}")
        if need:
            rows.append({
                "doc_id": did,
                "title": title,
                "summary_len": sl,
                "bullet_count": bc,
                "body_len": bl,
                "reason": ",".join(reasons)
            })
    return rows

# ----- LLM call -----
def build_prompt(text: str) -> str:
    return f"""역할: 한국어 위키/애니 텍스트 요약가
지시:
- 한국어 불릿 {BULLET_TARGET}개
- 사실 중심, 팬덤/추측 금지
- 각 불릿은 1문장 50~120자
- 작품명/고유명사 원문 표기 유지
- 출력 형식: 각 줄을 "- "로 시작

원문:
{text[:SUM_MAX_CHARS]}"""

def chat_complete(base_url: str, model: str, prompt: str, timeout=120) -> str:
    requests = _lazy_req()
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2
    }
    r = requests.post(f"{base_url}/chat/completions", json=payload, timeout=timeout)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]

def parse_bullets(summary_text: str) -> List[str]:
    lines = [l.strip() for l in summary_text.splitlines()]
    out = []
    for ln in lines:
        if not ln: continue
        if ln.startswith(("- ", "• ", "* ", "1.", "2.", "3.", "4.", "5.")):
            ln = ln.lstrip("*•").strip()
            if ln.startswith("- "): ln = ln[2:].strip()
            out.append(ln)
        else:
            out.append(ln)
    # normalize to exactly BULLET_TARGET by trimming/padding (padding rare)
    if len(out) > BULLET_TARGET:
        out = out[:BULLET_TARGET]
    return out

# ----- merge new summaries into section rows -----
def merge_summaries(section_rows: List[Dict[str,Any]],
                    new_summaries: Dict[str, Dict[str,Any]],
                    model_name: str):
    # index by (doc_id, section)
    by_key: Dict[Tuple[str,str], int] = {}
    for i, r in enumerate(section_rows):
        by_key[(r["doc_id"], r["section"])] = i

    for did, s_obj in new_summaries.items():
        key = (did, "요약")
        bullets = s_obj.get("bullets")
        txt = "\n".join(f"- {b}" for b in bullets) if bullets else s_obj.get("summary","")
        if key in by_key:
            i = by_key[key]
            section_rows[i]["summary"] = txt
            section_rows[i]["bullets"] = bullets
            section_rows[i]["summary_model"] = model_name
        else:
            # create new 요약 row
            # try to get a title from any row with same did
            title = None
            for r in section_rows:
                if r["doc_id"] == did:
                    title = r["title"]; break
            section_rows.append({
                "doc_id": did,
                "title": title or "",
                "seed": None,
                "section": "요약",
                "text": None,
                "summary": txt,
                "bullets": bullets,
                "summary_model": model_name,
                "summary_params": {"max_input_chars": SUM_MAX_CHARS, "style":"ko-5-bullets"},
                "source_url": None,
                "source": "namu",
                "language": "ko",
                "fetched_at": None,
                "created_at": None
            })

# ----- chunk rows (본문 only) -----
def build_chunks(section_rows: List[Dict[str,Any]],
                 min_len=750, max_len=900, overlap=120) -> List[Dict[str,Any]]:
    bodies = [r for r in section_rows if r["section"]=="본문" and (r.get("text") or "").strip()]
    out = []
    for r in bodies:
        doc_id = r["doc_id"]
        title = r["title"]
        src = r.get("text","")
        parts = greedy_chunks(src, min_len=min_len, max_len=max_len, overlap=overlap)
        for i, chunk in enumerate(parts):
            out.append({
                "uid": f"{doc_id}#b{i:04d}",
                "doc_id": doc_id,
                "title": title,
                "chunk_index": i,
                "text": chunk,
                "section": "본문",
                "source_url": r.get("source_url"),
                "language": "ko"
            })
    return out

# ----- chroma upsert -----
def upsert_chroma(chroma_dir: str, collection: str,
                  chunks: List[Dict[str,Any]], embed_model="sentence-transformers/all-MiniLM-L6-v2",
                  batch_size=512):
    PersistentClient, emb_fn = _lazy_chroma(embed_model)
    client = PersistentClient(path=chroma_dir)
    col = client.get_or_create_collection(name=collection, embedding_function=emb_fn)

    ids, docs, metas = [], [], []
    for ch in chunks:
        ids.append(ch["uid"])
        docs.append(ch["text"])
        metas.append({
            "doc_id": ch["doc_id"],
            "title": ch["title"],
            "chunk_index": ch["chunk_index"],
            "section": "본문",
            "source_url": ch.get("source_url"),
            "language": "ko"
        })
        if len(ids) >= batch_size:
            col.upsert(ids=ids, documents=docs, metadatas=metas)
            ids, docs, metas = [], [], []
    if ids:
        col.upsert(ids=ids, documents=docs, metadatas=metas)

# ----- main pipeline -----
def run(args):
    os.makedirs(args.outdir, exist_ok=True)

    # 1) flatten/clean
    pack = flatten_sections(args.input, sum_max_chars=SUM_MAX_CHARS)
    rows = pack["rows"]
    metrics = pack["metrics"]

    clean_path = os.path.join(args.outdir, "hf_clean_sections.jsonl")
    write_jsonl(clean_path, rows)

    # 2) select resummarize targets
    targets = select_resum_targets(metrics,
                                   min_body=args.min_body,
                                   min_sum_len=args.min_sum_len,
                                   bullet_target=BULLET_TARGET)
    resum_list_path = os.path.join(args.outdir, "to_resummarize.jsonl")
    write_jsonl(resum_list_path, targets)

    # 3) resummarize if enabled
    new_sums: Dict[str, Dict[str,Any]] = {}
    if not args.skip_resum and targets:
        # build body map
        body_map = {}
        for r in rows:
            if r["section"]=="본문":
                body_map[r["doc_id"]] = r.get("text") or ""
        base = args.llm_base or os.getenv("LLM_BASE_URL", "http://localhost:8000/v1")
        model = args.llm_model or os.getenv("LLM_MODEL", "gemma-2-9b-it")

        for i, t in enumerate(targets, 1):
            did = t["doc_id"]
            text = body_map.get(did, "")
            if len(text) < args.min_body:
                continue
            prompt = build_prompt(text)
            try:
                out = chat_complete(base, model, prompt, timeout=args.llm_timeout)
            except Exception as e:
                print(f"[WARN] LLM fail {did}: {e}", file=sys.stderr)
                continue
            bullets = parse_bullets(out)
            new_sums[did] = {"summary": out, "bullets": bullets}
            if args.llm_sleep > 0:
                time.sleep(args.llm_sleep)

    # 4) merge back summaries
    if new_sums:
        merge_summaries(rows, new_sums, model_name=(args.llm_model or os.getenv("LLM_MODEL","gemma-2-9b-it")))

    final_sections_path = os.path.join(args.outdir, "hf_sections_final.jsonl")
    write_jsonl(final_sections_path, rows)

    # 5) make chunks
    chunks = build_chunks(rows, min_len=args.chunk_min, max_len=args.chunk_max, overlap=args.chunk_overlap)
    chunks_path = os.path.join(args.outdir, "hf_chunks.jsonl")
    write_jsonl(chunks_path, chunks)

    # 6) upsert to chroma
    if args.do_chroma:
        upsert_chroma(args.chroma_dir, args.chroma_collection, chunks,
                      embed_model=args.embed_model, batch_size=args.batch_size)

    # 7) stats echo
    print("== DONE ==")
    print(f"clean_sections: {clean_path}")
    print(f"to_resummarize: {resum_list_path} (count={len(targets)})")
    if new_sums:
        print(f"resummarized: {len(new_sums)}")
    print(f"final_sections: {final_sections_path} (rows={len(rows)})")
    print(f"chunks: {chunks_path} (rows={len(chunks)})")
    if args.do_chroma:
        print(f"chroma upserted to: dir={args.chroma_dir}, collection={args.chroma_collection}")

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("-i","--input", required=True, help="원본 JSONL (문서 단위)")
    ap.add_argument("-o","--outdir", default="./out", help="산출물 디렉토리")

    # resummarize
    ap.add_argument("--skip-resum", action="store_true", help="요약 재생성 스킵")
    ap.add_argument("--min-body", type=int, default=300)
    ap.add_argument("--min-sum-len", type=int, default=120)
    ap.add_argument("--llm-base", default=os.getenv("LLM_BASE_URL"))
    ap.add_argument("--llm-model", default=os.getenv("LLM_MODEL"))
    ap.add_argument("--llm-timeout", type=int, default=120)
    ap.add_argument("--llm-sleep", type=float, default=0.0, help="요청 간 sleep(sec)")

    # chunking
    ap.add_argument("--chunk-min", type=int, default=750)
    ap.add_argument("--chunk-max", type=int, default=900)
    ap.add_argument("--chunk-overlap", type=int, default=120)

    # chroma
    ap.add_argument("--do-chroma", action="store_true")
    ap.add_argument("--chroma-dir", default=os.getenv("CHROMA_DB_DIR","./chroma_db"))
    ap.add_argument("--chroma-collection", default=os.getenv("CHROMA_COLLECTION","namu_anime_v2"))
    ap.add_argument("--embed-model", default=os.getenv("EMBED_MODEL","sentence-transformers/all-MiniLM-L6-v2"))
    ap.add_argument("--batch-size", type=int, default=512)

    args = ap.parse_args()
    run(args)
