import json, argparse

# === 기존 v3_fix.py의 _list_str/_norm_section 등 보조함수들 그대로 복붙하세요 ===
KNOWN = {"요약","본문","줄거리","설정","등장인물","평가"}

def _list_str(xs):
    if not xs: return []
    out = []
    for x in xs:
        if x is None: continue
        out.append(str(x))
    return out

def _norm_section(name, sec):
    if not isinstance(sec, dict): sec = {}
    s = {"name": str(name),
         "text": str(sec.get("text") or ""),
         "chunks": _list_str(sec.get("chunks") or []),
         "urls": _list_str(sec.get("urls") or [])}
    if "summary" in sec: s["summary"] = str(sec.get("summary") or "")
    if "bullets" in sec: s["bullets"] = _list_str(sec.get("bullets") or [])
    if "list" in sec and isinstance(sec["list"], list):
        fixed = []
        for it in sec["list"]:
            if not isinstance(it, dict): continue
            fixed.append({
                "name": str(it.get("name") or ""),
                "desc": str(it.get("desc") or ""),
                "url":  str(it.get("url") or "")
            })
        s["list"] = fixed
    if "model" in sec: s["model"] = str(sec.get("model") or "")
    if "ts" in sec:    s["ts"]    = str(sec.get("ts") or "")
    return s

def fix_line(line: str) -> str:
    rec = json.loads(line)
    new = {
        "title": rec.get("title") or rec.get("seed_title") or "",
        "seed_title": rec.get("seed_title") or rec.get("title") or "",
        "sections": []
    }
    for k in list(rec.keys()):
        if k in KNOWN:
            new["sections"].append(_norm_section(k, rec.pop(k)))
    for k,v in list(rec.items()):
        if isinstance(v, dict) and any(x in v for x in ("text","chunks","urls","summary","bullets","list")):
            new["sections"].append(_norm_section(k, rec.pop(k)))
    sec = rec.get("sections")
    if isinstance(sec, dict):
        for k,v in sec.items():
            new["sections"].append(_norm_section(k, v))
    elif isinstance(sec, list):
        for v in sec:
            name = v.get("name") if isinstance(v, dict) else "섹션"
            new["sections"].append(_norm_section(name, v if isinstance(v, dict) else {}))
    return json.dumps(new, ensure_ascii=False)

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--out", dest="out", required=True)
    args = ap.parse_args()

    with open(args.inp, "r", encoding="utf-8", errors="replace") as fi, \
         open(args.out, "w", encoding="utf-8", newline="\n") as fo:
        for line in fi:
            line = line.strip()
            if not line: continue
            fo.write(fix_line(line) + "\n")
