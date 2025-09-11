# app/app/scripts/audit_ceiling.py
from app.app.scripts.rag_optuna_tune import build_dev_rows, _recall50_raw
from app.app.metrics.quality import keys_from_docs, recall_at_k
from app.app.services.rag import RagService

def run(N=200, section="요약", by="title", k=9):
    svc = RagService()
    dev = build_dev_rows(N, section, by, seed=42)
    gaps = []
    for q, gold in dev:
        raw50 = _recall50_raw(q, gold, by)
        docs = svc.retrieve_docs(q, k=k, strategy="chroma_only", use_mmr=True, lam=0.85)
        keys = keys_from_docs(docs, by=by)
        rk = recall_at_k(keys, gold, k)
        gaps.append((raw50, rk))
    hi = sum(1 for r50, _ in gaps if r50 >= 0.8) / len(gaps)
    print(f"[ceiling] share(raw50>=0.8)={hi:.3f}, avg_gap={sum(r50-rk for r50,rk in gaps)/len(gaps):.3f}")
    return gaps

if __name__ == "__main__":
    run()
