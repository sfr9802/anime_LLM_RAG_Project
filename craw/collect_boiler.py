# collect_boiler.py
import json, sys
from collections import defaultdict

src = sys.argv[1]
boiler_len_max = int(sys.argv[2]) if len(sys.argv) > 2 else 80
thresh = int(sys.argv[3]) if len(sys.argv) > 3 else 5

line_seeds = defaultdict(set)

with open(src, "r", encoding="utf-8") as f:
    for ln in f:
        if not ln.strip(): continue
        o = json.loads(ln)
        seed = o.get("seed") or o.get("title") or ""
        secs = o.get("sections") or {}
        for v in secs.values():
            for c in (v.get("chunks") or []):
                if c and len(c) <= boiler_len_max:
                    line_seeds[c].add(seed)

boiler = [t for t,s in line_seeds.items() if len(s) >= thresh and len(t) <= boiler_len_max]
print("\n".join(boiler))
