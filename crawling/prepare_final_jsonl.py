# prepare_final_jsonl.py
# 사용법:
#   python prepare_final_jsonl.py -i out_with_chars.jsonl -o out_with_chars.final.jsonl
import json, argparse, hashlib
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

def load_jsonl(p: Path):
    with p.open("r", encoding="utf-8") as f:
        for i, line in enumerate(f, start=1):
            s = line.strip()
            if not s: 
                continue
            try:
                obj = json.loads(s)
                obj["_line_no"] = i
                yield obj
            except Exception:
                # 깨진 라인은 무시
                continue

def first_str(d: Dict[str, Any], keys: List[str]) -> Optional[str]:
    for k in keys:
        v = d.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None

def get_seed(r: Dict[str, Any]) -> Optional[str]:
    return first_str(r, ["seed","title","name"])

def get_url(r: Dict[str, Any]) -> Optional[str]:
    return first_str(r, ["url","source_url","href"])

def get_title(r: Dict[str, Any]) -> Optional[str]:
    return first_str(r, ["title","seed","name"])

def pick_summary(r: Dict[str, Any]) -> Optional[str]:
    # 우선순위: llm_summary_norm > llm_summary > summary > top_summary > sum_text > sum_text_top > sections.요약/개요 계열
    cands = [
        first_str(r, ["llm_summary_norm","llm_summary","summary","top_summary","sum_text","sum_text_top"])
    ]
    secs = r.get("sections")
    if isinstance(secs, dict):
        for key in ["요약","개요","Summary","요약/개요","개요/요약"]:
            v = secs.get(key)
            if isinstance(v, dict) and isinstance(v.get("text"), str) and v["text"].strip():
                cands.append(v["text"].strip())
            elif isinstance(v, str) and v.strip():
                cands.append(v.strip())
    for c in cands:
        if c and isinstance(c, str) and c.strip():
            return c.strip()
    return None

def pick_bullets(r: Dict[str, Any]) -> List[str]:
    for k in ["summary_bullets","sum_bullets","bullets","llm_bullets","top_bullets"]:
        v = r.get(k)
        if isinstance(v, list):
            return [x.strip() for x in v if isinstance(x, str) and x.strip()][:5]  # 최대 5개
    return []

def to_char_obj(x: Any) -> Optional[Dict[str, Any]]:
    if isinstance(x, str) and x.strip():
        return {"name": None, "summary": x.strip()}
    if isinstance(x, dict):
        name = None
        for nk in ["name","character","title","이름","명칭","char","alias"]:
            if isinstance(x.get(nk), str) and x[nk].strip():
                name = x[nk].strip(); break
        summ = None
        for sk in ["summary","desc","설명","요약","text"]:
            if isinstance(x.get(sk), str) and x[sk].strip():
                summ = x[sk].strip(); break
        rest = {k:v for k,v in x.items() if k not in ["name","character","title","이름","명칭","char","alias","summary","desc","설명","요약","text"]}
        obj = {"name": name, "summary": summ}
        if rest: obj["meta"] = rest
        if name or summ or rest:
            return obj
    return None

def pick_characters(r: Dict[str, Any]) -> List[Dict[str, Any]]:
    for k in ["characters","chars","character_list","char_summaries","character_summaries"]:
        v = r.get(k)
        if isinstance(v, list) and v:
            norm = []
            for x in v:
                obj = to_char_obj(x)
                if obj: norm.append(obj)
            return norm[:200]  # 안전 상한
    return []

def stable_doc_id(seed: Optional[str], url: Optional[str], fallback: Optional[str]) -> str:
    base = (seed or "") + "|" + (url or "") + "|" + (fallback or "")
    return hashlib.sha1(base.encode("utf-8")).hexdigest()

def score_record(r: Dict[str, Any]) -> Tuple[int,int,int,int]:
    s = pick_summary(r) or ""
    b = pick_bullets(r)
    c = pick_characters(r)
    sec_cnt = len(r.get("sections", {})) if isinstance(r.get("sections"), dict) else 0
    return (len(s), len(b), len(c), sec_cnt)

def dedup_key(r: Dict[str, Any]) -> Tuple[str,str,str]:
    seed = get_seed(r) or ""
    url  = get_url(r) or ""
    did  = r.get("doc_id") or r.get("id") or ""
    return (seed, url, did)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-i","--input", required=True, help="원본 JSONL 경로")
    ap.add_argument("-o","--output", required=True, help="최종본 JSONL 경로")
    args = ap.parse_args()

    src = Path(args.input); dst = Path(args.output)
    assert src.exists(), f"입력 파일 없음: {src}"

    # 1) 로드 + 중복키 그룹핑
    best = {}
    total = 0
    for r in load_jsonl(src):
        total += 1
        key = dedup_key(r)
        if key not in best:
            best[key] = r
        else:
            if score_record(r) > score_record(best[key]):
                best[key] = r

    deduped = list(best.values())

    # 2) 표준 필드 주입
    with dst.open("w", encoding="utf-8") as f:
        for r in deduped:
            seed, url, title = get_seed(r), get_url(r), get_title(r)
            summary  = pick_summary(r)
            bullets  = pick_bullets(r)
            chars    = pick_characters(r)
            doc_id   = r.get("doc_id") or r.get("id")
            if not doc_id:
                doc_id = stable_doc_id(seed, url, summary or str(r.get("_line_no")))

            r2 = dict(r)
            r2.pop("_line_no", None)
            r2["doc_id"] = doc_id
            if seed is not None:  r2["seed"] = seed
            if title is not None: r2["title"] = title
            if url is not None:   r2["url"] = url
            if summary is not None: r2["summary"] = summary
            r2["summary_bullets"] = bullets
            r2["characters"] = chars

            f.write(json.dumps(r2, ensure_ascii=False) + "\n")

    print(f"총 입력: {total}  →  최종 출력: {len(deduped)}")
    print(f"완료: {dst}")

if __name__ == "__main__":
    main()
