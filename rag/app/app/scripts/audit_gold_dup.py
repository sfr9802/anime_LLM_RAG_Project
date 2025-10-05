# app/app/scripts/audit_gold_dup.py
from collections import Counter
from app.app.scripts.rag_optuna_tune import _sample_from_chroma, _gold_keys_for_meta, _make_queries_from_meta

def run(N=500, section="요약", by="title"):
    metas = _sample_from_chroma(N, section_hint=section)
    gold_sizes = []
    title_counts = Counter()
    for m in metas:
        gold = _gold_keys_for_meta(m, by)
        gold_sizes.append(len(gold))
        t = (m.get("title") or "").strip().lower()
        title_counts[t] += 1
    print(f"[gold] avg|p90|max sizes = {sum(gold_sizes)/len(gold_sizes):.2f} | "
          f"{sorted(gold_sizes)[int(0.9*len(gold_sizes))]} | {max(gold_sizes)}")
    heavy = [t for t,c in title_counts.items() if c>=10]
    print(f"[dup] titles with >=10 metas: {len(heavy)} samples: {heavy[:5]}")
    return gold_sizes, title_counts

if __name__ == "__main__":
    run()
