# clean_jsonl.py
import json, re, sys
from pathlib import Path

FLAGS = re.IGNORECASE
GAME_PR_RE = [re.compile(p, FLAGS) for p in [
    r"(CBT|OBT|사전\s*등록|사전등록|론칭|런칭|출시|대규모\s*업데이트)\b",
    r"(그라비티|넥슨|넷마블|엔씨소프트|카카오게임즈|스마일게이트|펄어비스)\b",
]]
def is_pr(x:str)->bool:
    t=x.strip()
    return any(rx.search(t) for rx in GAME_PR_RE)

inp, outp = Path(sys.argv[1]), Path(sys.argv[2])
with inp.open("r", encoding="utf-8") as fi, outp.open("w", encoding="utf-8") as fo:
    for line in fi:
        if not line.strip(): continue
        obj = json.loads(line)
        secs = obj.get("sections") or {}
        changed = False
        for k, v in list(secs.items()):
            ch = v.get("chunks") or []
            ch2 = [c for c in ch if not is_pr(c)]
            if len(ch2) != len(ch):
                v["chunks"] = ch2
                v["text"] = "\n\n".join(ch2)
                changed = True
            # 섹션이 비면 아예 제거
            if not v.get("chunks"):
                del secs[k]; changed = True
        if not secs:
            continue  # 문서 자체를 드롭
        obj["sections"] = secs
        fo.write(json.dumps(obj, ensure_ascii=False) + "\n")
