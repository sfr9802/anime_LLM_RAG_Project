# merge_characters_from_raw.py
# 사용법:
#   python merge_characters_from_raw.py -r namu_anime_raw.jsonl -v namu_anime_v3.jsonl -o namu_anime_v3.with_chars.jsonl
import json, re, argparse
from pathlib import Path
from collections import defaultdict

BAD_SUBPAGE = ["방영","설정","노래","앨범","리뷰","평가","목록","에피소드","화수","제작진","오프닝","엔딩","ost","용어","세계관","배경","상품","굿즈","게임","소설","만화","미디어믹스"]

def clean(t:str)->str:
    t = re.sub(r"\[\d+\]", "", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t

def first_summary(r):
    c = r.get("content")
    if isinstance(c, str) and c.strip(): return clean(c)[:500]
    for ch in (r.get("chunks") or []):
        t = ch if isinstance(ch, str) else (ch.get("text") or ch.get("content"))
        if isinstance(t, str) and t.strip(): return clean(t)[:500]
    return ""

def is_character_page(r):
    parent = (r.get("parent") or "").lower()
    title  = (r.get("title") or "").lower()
    meta   = r.get("metadata", {}) or {}
    if any(k in parent for k in ["등장인물","캐릭","성우"]): return True
    if meta.get("depth", 0) >= 2 and r.get("title") != meta.get("seed_title"):
        if not any(b in title for b in BAD_SUBPAGE): return True
    return False

def build_char_index(raw_path: Path):
    idx = defaultdict(list)
    with raw_path.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip(): continue
            r = json.loads(line)
            seed = (r.get("metadata") or {}).get("seed_title")
            if not seed: continue
            if not is_character_page(r): continue
            name = r.get("title"); summ = first_summary(r)
            if not (name and summ): continue
            idx[seed].append({"name": name, "summary": summ})
    # dedup & clamp
    for seed, lst in list(idx.items()):
        seen=set(); out=[]
        for c in lst:
            k=c["name"].strip()
            if k in seen: continue
            seen.add(k); out.append(c)
        out.sort(key=lambda x: len(x["summary"]), reverse=True)
        idx[seed]=out[:50]
    return idx

def merge(v3_path: Path, char_idx: dict, out_path: Path):
    with v3_path.open("r", encoding="utf-8") as fin, out_path.open("w", encoding="utf-8") as fout:
        hit=tot=0
        for line in fin:
            if not line.strip(): continue
            r = json.loads(line); tot+=1
            seed = r.get("seed") or r.get("title")
            chars = char_idx.get(seed)
            if chars:
                r["characters"] = chars; hit+=1
            fout.write(json.dumps(r, ensure_ascii=False)+"\n")
    print(f"v3 총 {tot}건 중 캐릭터 채워진 문서 {hit}건 → {out_path}")

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("-r","--raw", required=True)
    ap.add_argument("-v","--v3", required=True)
    ap.add_argument("-o","--out", required=True)
    args = ap.parse_args()
    idx = build_char_index(Path(args.raw))
    merge(Path(args.v3), idx, Path(args.out))
