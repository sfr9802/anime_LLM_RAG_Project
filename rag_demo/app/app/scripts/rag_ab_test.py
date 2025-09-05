# app/app/scripts/rag_ab_test.py
# -*- coding: utf-8 -*-
from __future__ import annotations
import argparse, time, json, math, random, os
from pathlib import Path
from typing import List, Dict, Tuple

from app.app.services.rag_service import RagService
from app.app.metrics.quality import (
    keys_from_docs, hit_at_k, recall_at_k, dup_rate, p_percentile
)
# 추가: raw Chroma top-50 리콜 측정을 위해 직접 조회
from app.app.services.adapters import flatten_chroma_result
from app.app.infra.vector.chroma_store import search as chroma_search

# ----- utils -----
def _norm(s: str) -> str:
    import unicodedata, re
    s = unicodedata.normalize("NFKC", s or "").lower()
    return re.sub(r"[\s\W_]+", "", s)

def _mrr(retrieved: List[str], gold: List[str]) -> float:
    G = { _norm(t) for t in gold if t }
    for i, t in enumerate(retrieved, 1):
        if _norm(t) in G:
            return 1.0 / i
    return 0.0

def _ndcg(retrieved: List[str], gold: List[str], k: int) -> float:
    G = { _norm(t) for t in gold if t }
    rels = [1.0 if _norm(t) in G else 0.0 for t in retrieved[:k]]
    # DCG: sum_{i=1..k} rel_i / log2(i+1)
    dcg = sum(rel / math.log2(i+1) for i, rel in enumerate(rels, start=1))
    # IDCG: perfect ranking
    idcg = sum(1.0 / math.log2(i+1) for i in range(1, min(k, len(G)) + 1))
    return (dcg / idcg) if idcg > 0 else 0.0

def _bootstrap_ci(diffs: List[float], iters: int = 2000, alpha: float = 0.05) -> Tuple[float,float,float]:
    if not diffs:
        return (0.0, 0.0, 0.0)
    boots = []
    n = len(diffs)
    for _ in range(iters):
        sample = [diffs[random.randrange(n)] for _ in range(n)]
        boots.append(sum(sample)/n)
    boots.sort()
    mean = sum(diffs)/n
    lo = boots[int((alpha/2)*iters)]
    hi = boots[int((1-alpha/2)*iters)]
    return (mean, lo, hi)

# ----- query synth from metadata -----
def _split_csv(v) -> List[str]:
    if not v: return []
    if isinstance(v, list):
        return [str(x).strip() for x in v if str(x).strip()]
    return [s.strip() for s in str(v).split("|") if s.strip()]

def _make_queries_from_meta(m: Dict) -> List[str]:
    t = m.get("seed_title") or m.get("parent") or m.get("title") or ""
    qs: List[str] = []
    if t:
        qs += [t, f"{t} 요약", f"{t} 줄거리", f"{t} 등장인물"]
    qs += _split_csv(m.get("aliases_csv"))
    qs += _split_csv(m.get("aliases_norm_csv"))
    for key in ("aliases", "aliases_norm", "original_title", "alt_title"):
        v = m.get(key)
        if isinstance(v, list): qs += v[:2]
        elif isinstance(v, str): qs.append(v)
    uniq, seen = [], set()
    for q in qs:
        q = q.strip()
        if len(q) < 2: continue
        if q in seen: continue
        seen.add(q); uniq.append(q)
    return uniq

# ----- sample metadata from Chroma -----
def _sample_from_chroma(max_docs: int, section_hint: str = "요약") -> List[Dict]:
    from app.app.infra.vector.chroma_store import get_collection
    coll = get_collection()

    metas, ids = [], []
    offset, batch = 0, 500
    try:
        while len(metas) < max_docs:
            res = coll.get(
                where={"section": section_hint} if section_hint else None,
                include=["metadatas"],
                limit=batch, offset=offset,
            )
            got_ids = res.get("ids") or []
            got_meta = res.get("metadatas") or []
            if not got_ids: break
            metas.extend(got_meta); ids.extend(got_ids)
            offset += len(got_ids)
            if len(metas) >= max_docs: break
    except Exception:
        metas, ids = [], []
        offset = 0
        while len(metas) < max_docs:
            res = coll.get(include=["metadatas"], limit=batch, offset=offset)
            got_ids = res.get("ids") or []
            got_meta = res.get("metadatas") or []
            if not got_ids: break
            for i, m in enumerate(got_meta):
                if section_hint and (m or {}).get("section") != section_hint: continue
                metas.append(m or {}); ids.append(got_ids[i] if i < len(got_ids) else None)
                if len(metas) >= max_docs: break
            offset += len(got_ids)

    if not metas:
        res = coll.peek(min(max_docs, 1000))
        metas = res.get("metadatas") or []
        ids = res.get("ids") or []

    uniq, seen = [], set()
    for i, m in enumerate(metas):
        m = m or {}
        doc_id = m.get("doc_id") or ids[i] or f"{m.get('title','')}|{m.get('section','')}"
        if doc_id in seen: continue
        seen.add(doc_id); uniq.append(m)
        if len(uniq) >= max_docs: break

    random.shuffle(uniq)
    return uniq

# ----- raw chroma recall@50 (pre-rerank, pre-MMR) -----
def _recall50_raw(q: str, gold: List[str], match_by: str) -> float:
    res = chroma_search(
        query=q, n=50, where=None,
        include_docs=True, include_metas=True, include_ids=True, include_distances=True
    )
    items = flatten_chroma_result(res)
    keys = keys_from_docs(items, by=("title" if match_by == "title" else "doc"))
    return recall_at_k(keys, gold, 50)

# ----- pre-rerank recall@50 for a strategy (MMR/캡까지 반영, CE만 비활성) -----
def _recall50_prerank_for_strategy(q: str, gold: List[str], strategy: str, match_by: str, svc_nr: RagService) -> float:
    try:
        docs50 = svc_nr.retrieve_docs(q, k=50, strategy=strategy, use_mmr=True)
        keys = keys_from_docs(docs50, by=("title" if match_by == "title" else "doc"))
        return recall_at_k(keys, gold, 50)
    except Exception:
        return 0.0

# ----- main A/B -----
def run(max_docs: int, k: int, stratA: str, stratB: str, seed: int = 42,
        section_hint: str = "요약", match_by: str = "title", report: str = "B"):
    random.seed(seed)
    svc = RagService()  # 기본(환경설정대로, 보통 리랭커 활성)

    # 리랭커 비활성 인스턴스(프리랭크 측정용)
    _orig = os.environ.get("RAG_USE_RERANK")
    os.environ["RAG_USE_RERANK"] = "0"
    svc_nr = RagService()
    if _orig is None:
        del os.environ["RAG_USE_RERANK"]
    else:
        os.environ["RAG_USE_RERANK"] = _orig

    metas = _sample_from_chroma(max_docs=max_docs, section_hint=section_hint)

    rows = []
    for m in metas:
        gold = [ (m.get("seed_title") or m.get("title") or "") ] if match_by == "title" else [ (m.get("doc_id") or "") ]
        queries = _make_queries_from_meta(m)
        if not queries or not gold or not gold[0]:
            continue
        q = random.choice(queries)

        # A/B 최종(현재 설정, 보통 리랭커 on)
        t0 = time.perf_counter(); A = svc.retrieve_docs(q, k=k, strategy=stratA); tA = time.perf_counter()-t0
        t0 = time.perf_counter(); B = svc.retrieve_docs(q, k=k, strategy=stratB); tB = time.perf_counter()-t0

        keysA = keys_from_docs(A, by=("title" if match_by=="title" else "doc"))
        keysB = keys_from_docs(B, by=("title" if match_by=="title" else "doc"))

        # 추가 지표: raw chroma와 pre-rerank(CE off, k=50)
        rec50_raw = _recall50_raw(q, gold, match_by)
        rec50_preA = _recall50_prerank_for_strategy(q, gold, stratA, match_by, svc_nr)
        rec50_preB = _recall50_prerank_for_strategy(q, gold, stratB, match_by, svc_nr)

        rows.append({
            "q": q, "gold": gold, "k": k,
            "hitA": hit_at_k(keysA, gold, k),     "hitB": hit_at_k(keysB, gold, k),
            "mrrA": _mrr(keysA, gold),            "mrrB": _mrr(keysB, gold),
            "ndcgA": _ndcg(keysA, gold, k),       "ndcgB": _ndcg(keysB, gold, k),
            "latA_ms": tA*1000.0,                 "latB_ms": tB*1000.0,
            "dupA": dup_rate(keysA),              "dupB": dup_rate(keysB),
            "keysA": keysA, "keysB": keysB,
            # 추가
            "rec50_raw": rec50_raw,
            "rec50_preA": rec50_preA,
            "rec50_preB": rec50_preB,
        })

    # aggregate
    def _agg(keyA, keyB, bigger=True):
        A = [r[keyA] for r in rows]; B = [r[keyB] for r in rows]
        n = len(A) or 1
        meanA = sum(A)/n if A else 0.0
        meanB = sum(B)/n if B else 0.0
        diffs = [b-a for a,b in zip(A,B)]
        mean, lo, hi = _bootstrap_ci(diffs) if diffs else (0.0, 0.0, 0.0)
        rel = (meanB - meanA) / (meanA + 1e-12) * 100.0 if meanA else 0.0
        wins = sum(1 for a,b in zip(A,B) if (b>a if bigger else b<a))
        ties = sum(1 for a,b in zip(A,B) if b==a)
        winrate = (wins + 0.5*ties) / (len(A) if A else 1)
        return dict(meanA=meanA, meanB=meanB, rel_pct=rel, diff_mean=mean, ci95=(lo,hi), winrate=winrate)

    R_hit  = _agg("hitA","hitB", True)
    R_mrr  = _agg("mrrA","mrrB", True)
    R_ndcg = _agg("ndcgA","ndcgB", True)
    R_lat  = _agg("latA_ms","latB_ms", False)

    # README용 품질 지표(리포트 타깃: A or B)
    keys_key = f"keys{report}"
    lat_key  = f"lat{report}_ms"
    rec5 = sum(recall_at_k(r[keys_key], r["gold"], 5) for r in rows) / (len(rows) or 1)
    dup  = sum(dup_rate(r[keys_key]) for r in rows) / (len(rows) or 1)
    p95  = p_percentile([r[lat_key] for r in rows if isinstance(r.get(lat_key), (int,float))], 95.0)

    # 추가 집계: recall@50 (raw / pre-A / pre-B)
    rec50_raw_mean = sum(r.get("rec50_raw", 0.0) for r in rows) / (len(rows) or 1)
    rec50_preA_mean = sum(r.get("rec50_preA", 0.0) for r in rows) / (len(rows) or 1)
    rec50_preB_mean = sum(r.get("rec50_preB", 0.0) for r in rows) / (len(rows) or 1)

    print(f"\n--- Report ({report}) ---")
    print(f"recall@5          {rec5:.3f}")
    print(f"recall@50(raw)    {rec50_raw_mean:.3f}")
    print(f"recall@50(pre-A)  {rec50_preA_mean:.3f}")
    print(f"recall@50(pre-B)  {rec50_preB_mean:.3f}")
    print(f"p95               {p95:.0f} ms")
    print(f"dup_rate          {dup:.3f}")

    print(f"\n=== Self A/B on Chroma (N={len(rows)}, k={k}, section='{section_hint}', by={match_by}) ===")
    def pr(tag, R):
        print(f"{tag:10s} | A={R['meanA']:.4f}  B={R['meanB']:.4f}  Δ%={R['rel_pct']:.2f}%  "
              f"Δ={R['diff_mean']:.4f}  CI95=({R['ci95'][0]:.4f},{R['ci95'][1]:.4f})  win={R['winrate']:.2%}")
    pr("Hit@k", R_hit); pr("MRR", R_mrr); pr("nDCG", R_ndcg); pr("Latency", R_lat)

    out = Path(f"ab_chroma_self_{stratA}_vs_{stratB}_k{k}_{match_by}_{section_hint or 'all'}_{report}.json")
    out.write_text(json.dumps({
        "rows": rows,
        "summary": {
            "hit": R_hit, "mrr": R_mrr, "ndcg": R_ndcg, "lat_ms": R_lat,
            "quality": {
                "report": report, "by": match_by,
                "recall@5": round(rec5, 4),
                "recall@50_raw": round(rec50_raw_mean, 4),
                "recall@50_preA": round(rec50_preA_mean, 4),
                "recall@50_preB": round(rec50_preB_mean, 4),
                "p95_ms": round(p95, 1), "dup_rate": round(dup, 4)
            }
        }
    }, ensure_ascii=False, indent=2), encoding="utf8")
    print(f"\nSaved: {out.resolve()}")

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--N", type=int, default=200, help="샘플링할 문서 수(=쿼리 수)")
    ap.add_argument("--k", type=int, default=6)
    ap.add_argument("--A", default="baseline", help="전략 A (baseline|chroma_only)")
    ap.add_argument("--B", default="chroma_only", help="전략 B (baseline|chroma_only)")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--section", default="요약", help="샘플링할 섹션 필터 (빈문자열이면 전체)")
    ap.add_argument("--by", choices=["title","doc"], default="title", help="평가 매칭 기준")
    ap.add_argument("--report", choices=["A","B"], default="B", help="품질 지표를 어느 전략 기준으로 낼지")
    args = ap.parse_args()
    run(max_docs=args.N, k=args.k, stratA=args.A, stratB=args.B, seed=args.seed,
        section_hint=args.section, match_by=args.by, report=args.report)
