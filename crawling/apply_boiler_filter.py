# apply_boiler_filter.py
import json, sys

src, dst, boiler_path = sys.argv[1], sys.argv[2], sys.argv[3]
boiler = set(open(boiler_path, "r", encoding="utf-8").read().splitlines())
def load_boiler(path):
    lines = []
    for enc in ("utf-8","utf-8-sig","cp949","utf-16","utf-16le","utf-16be","latin-1"):
        try:
            with open(path,"r",encoding=enc) as f:
                lines = [ln.strip() for ln in f if ln.strip() and not ln.strip().startswith("#")]
            break
        except UnicodeDecodeError:
            continue
    # 앞에 're:'면 정규식, 그 외는 부분 포함 키워드로 처리
    regs = []
    subs = []
    import re
    for ln in lines:
        if ln.lower().startswith("re:"):
            regs.append(re.compile(ln[3:], re.IGNORECASE))
        else:
            subs.append(ln.lower())
    return regs, subs

regexes, substrs = load_boiler(boiler_path)

def is_boiler(c: str) -> bool:
    cl = c.lower()
    if any(s in cl for s in substrs):
        return True
    if any(rx.search(c) for rx in regexes):
        return True
    return False

with open(src, "r", encoding="utf-8") as fi, open(dst, "w", encoding="utf-8") as fo:
    for ln in fi:
        if not ln.strip(): continue
        o = json.loads(ln)
        secs = o.get("sections") or {}
        for k, v in list(secs.items()):
            ch = v.get("chunks") or []
            ch2 = [c for c in ch if not is_boiler(c)]
            if ch2:
                v["chunks"] = ch2
                v["text"] = "\n\n".join(ch2)
            else:
                del secs[k]
        if secs:
            o["sections"] = secs
            fo.write(json.dumps(o, ensure_ascii=False) + "\n")
