# -*- coding: utf-8 -*-
from __future__ import annotations
import os, json, time, argparse, csv, itertools, random, math, contextlib
from pathlib import Path
from typing import Dict, Any, List, Tuple

from app.app.services.rag_service import RagService
from app.app.metrics.quality import (
    keys_from_docs, hit_at_k, recall_at_k, dup_rate, p_percentile
)
from app.app.services.adapters import flatten_chroma_result
from app.app.infra.vector.chroma_store import search as chroma_search

# ====== util ======
def _norm(s: str) -> str:
    import unicodedata, re
    s = unicodedata.normalize("NFKC", s or "").lower()
    return re.sub(r"[\s\W_]+", "", s)

def _mrr(retrieved: List[str], gold: List[str]) -> float:
    G = {_norm(t) for t in gold if t}
    for i, t in enumerate(retrieved, 1):
        if _norm(t) in G:
            return 1.0 / i
    return 0.0

def _ndcg(retrieved: List[str], gold: List[str], k: int) -> float:
    G = {_norm(t) for t in gold if t}
    dcg = 0.0
    for i, t in enumerate(retrieved[:k], 1):
        rel = 1.0 if _norm(t) in G else 0.0
        if rel:
            dcg += 1.0 / math.log2(i + 1)
    ideal_hits = min(len(G), k)
    idcg = sum(1.0 / math.log2(i + 1) for i in range(1, ideal_hits + 1))
    return dcg / idcg if idcg > 0 else 0.0

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
        # fallback: 전체에서 수집 후 section 필터
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

def _recall50_raw(q: str, gold: List[str], match_by: str) -> float:
    res = chroma_search(
        query=q, n=50, where=None,
        include_docs=True, include_metas=True, include_ids=True, include_distances=True
    )
    items = flatten_chroma_result(res)
    keys = keys_from_docs(items, by=("title" if match_by == "title" else "doc"))
    return recall_at_k(keys, gold, 50)

@contextlib.contextmanager
def patched_environ(env_patch: Dict[str, Any]):
    old = {}
    try:
        for k, v in env_patch.items():
            old[k] = os.environ.get(k)
            os.environ[k] = str(v)
        yield
    finally:
        for k, v in old.items():
            if v is None: os.environ.pop(k, None)
            else: os.environ[k] = v

# ====== evaluation ======
def evaluate_config(dev_rows: List[Tuple[str, List[str]]],
                    cfg: Dict[str, Any],
                    envp: Dict[str, Any],
                    reranker: str = "keep") -> Dict[str, Any]:
    """
    dev_rows: [(query, gold_titles_or_docs), ...]
    cfg: strategy/k/use_mmr/lam/candidate_k
    envp: RAG_* 환경 변수 dict
    reranker: "keep" | "on" | "off"
    """
    # 리랭커 모드 고정
    if reranker == "on":
        os.environ["RAG_USE_RERANK"] = "1"
    elif reranker == "off":
        os.environ["RAG_USE_RERANK"] = "0"
    else:
        # keep: 건드리지 않음
        pass

    with patched_environ(envp):
        svc = RagService()

        hits, recs, mrrs, ndcgs, lats, dups = [], [], [], [], [], []
        rec50_raw_vals = []

        for q, gold in dev_rows:
            t0 = time.perf_counter()
            docs = svc.retrieve_docs(
                q,
                k=cfg["k"],
                where=None,
                candidate_k=cfg.get("candidate_k"),
                use_mmr=cfg["use_mmr"],
                lam=cfg["lam"],
                strategy=cfg["strategy"],
            )
            dt = (time.perf_counter() - t0) * 1000.0
            keys = keys_from_docs(docs, by=("title" if cfg["match_by"]=="title" else "doc"))

            hits.append(hit_at_k(keys, gold, cfg["k"]))
            recs.append(recall_at_k(keys, gold, cfg["k"]))
            mrrs.append(_mrr(keys, gold))
            ndcgs.append(_ndcg(keys, gold, cfg["k"]))
            lats.append(dt)
            dups.append(dup_rate(keys))

            # raw@50 (CE/MMR 전)
            rec50_raw_vals.append(_recall50_raw(q, gold, cfg["match_by"]))

        n = len(dev_rows) or 1
        metrics = dict(
            hit_at_k=sum(hits)/n,
            recall_at_k=sum(recs)/n,
            mrr=sum(mrrs)/n,
            ndcg=sum(ndcgs)/n,
            p95=p_percentile(lats, 95.0),
            dup_rate=sum(dups)/n,
            recall50_raw=sum(rec50_raw_vals)/n
        )
        return metrics

# ====== main (grid sweep) ======
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--N", type=int, default=200, help="샘플링할 문서 수(=쿼리 수)")
    ap.add_argument("--section", default="요약", help="섹션 힌트(''이면 전체)")
    ap.add_argument("--by", choices=["title","doc"], default="title", help="평가 매칭 기준")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--outdir", default="tune_out")
    ap.add_argument("--grid_json", default="", help="그리드 정의 JSON 파일 경로(없으면 내장 기본값)")
    ap.add_argument("--reranker", choices=["keep","on","off"], default="keep")
    # 스코어 가중치
    ap.add_argument("--w_recall", type=float, default=0.6)
    ap.add_argument("--w_mrr", type=float, default=0.2)
    ap.add_argument("--w_ndcg", type=float, default=0.2)
    ap.add_argument("--w_dup", type=float, default=0.1)
    ap.add_argument("--w_lat", type=float, default=0.0)
    ap.add_argument("--lat_target_ms", type=float, default=600.0)
    args = ap.parse_args()

    random.seed(args.seed)
    outdir = Path(args.outdir); outdir.mkdir(parents=True, exist_ok=True)

    # 1) dev 쿼리 셋 만들기(Chroma 메타 → 쿼리 합성)
    metas = _sample_from_chroma(args.N, section_hint=args.section)
    dev_rows: List[Tuple[str, List[str]]] = []
    for m in metas:
        gold = [ (m.get("seed_title") or m.get("title") or "") ] if args.by=="title" \
               else [ (m.get("doc_id") or "") ]
        qs = _make_queries_from_meta(m)
        if not gold or not gold[0] or not qs: 
            continue
        q = random.choice(qs)
        dev_rows.append((q, gold))

    # 2) 그리드 불러오기
    if args.grid_json and Path(args.grid_json).exists():
        grid = json.loads(Path(args.grid_json).read_text("utf-8"))
    else:
        # 기본값(필요 시 파일로 빼서 쓰면 됨)
        grid = {
            "strategy": ["baseline", "chroma_only"],
            "k": [4, 6, 8, 10, 12],
            "use_mmr": [True, False],
            "lam": [0.0, 0.2, 0.4, 0.6],
            "candidate_k": [80, 120, 160, 240],   # baseline에서만 의미
            # env 파라미터
            "RAG_TITLE_CAP": [1, 2, 3],
            "RAG_MMR_PRE_K": [60, 120, 160],
            "RAG_MMR_K": [40, 80, 120],
            "RAG_RERANK_IN": [16, 24, 32],
            "RAG_FETCH_K": [80, 120, 160, 200],
            "RAG_FETCH_K_AUX": [40, 80, 120],
        }

    # 3) 그리드 전개
    keys_cfg = ["strategy","k","use_mmr","lam","candidate_k"]
    keys_env = ["RAG_TITLE_CAP","RAG_MMR_PRE_K","RAG_MMR_K","RAG_RERANK_IN","RAG_FETCH_K","RAG_FETCH_K_AUX"]

    space_cfg = [ (k, grid.get(k, [None])) for k in keys_cfg ]
    space_env = [ (k, grid.get(k, [None])) for k in keys_env ]

    combos_cfg = list(itertools.product(*[v for _, v in space_cfg]))
    combos_env = list(itertools.product(*[v for _, v in space_env]))

    # 4) 스윕
    results: List[Dict[str, Any]] = []
    best: Dict[str, Any] = {}
    best_score = -1e9

    # 이전 베스트(롤백 대비)
    best_path = outdir / "retrieval.best.json"
    last_good = outdir / "retrieval.last_good.json"
    prev = json.loads(best_path.read_text("utf-8")) if best_path.exists() else None
    prev_score = prev["_score"] if prev else -1e9

    total_trials = 0
    for vals_cfg in combos_cfg:
        cfg = dict(zip(keys_cfg, vals_cfg))
        # 불필요 파라미터 정리
        if cfg.get("strategy") != "baseline":
            cfg["candidate_k"] = None
        cfg["match_by"] = args.by

        for vals_env in combos_env:
            envp = dict(zip(keys_env, vals_env))
            # None 값 제거
            cfg_clean = {k:v for k,v in cfg.items() if v is not None}
            env_clean = {k:str(v) for k,v in envp.items() if v is not None}

            metrics = evaluate_config(dev_rows, cfg_clean, env_clean, reranker=args.reranker)

            # 스코어: 가중 합 - 패널티
            lat_pen = max(0.0, (metrics["p95"] - args.lat_target_ms) / args.lat_target_ms)
            score = (
                args.w_recall * metrics["recall_at_k"] +
                args.w_mrr    * metrics["mrr"] +
                args.w_ndcg   * metrics["ndcg"] -
                args.w_dup    * metrics["dup_rate"] -
                args.w_lat    * lat_pen
            )

            row = dict(
                score=score,
                cfg=cfg_clean,
                env=env_clean,
                metrics=metrics
            )
            results.append(row)
            total_trials += 1

            if score > best_score:
                best_score = score
                best = row

    # 5) 결과 저장(CSV + best/rollback)
    csv_path = outdir / "results.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["score","strategy","k","use_mmr","lam","candidate_k",
                    "p95","recall@k","mrr","ndcg","dup","recall50_raw",
                    "RAG_TITLE_CAP","RAG_MMR_PRE_K","RAG_MMR_K","RAG_RERANK_IN","RAG_FETCH_K","RAG_FETCH_K_AUX"])
        for r in sorted(results, key=lambda x: x["score"], reverse=True):
            c, e, m = r["cfg"], r["env"], r["metrics"]
            w.writerow([
                f"{r['score']:.6f}",
                c.get("strategy"), c.get("k"), c.get("use_mmr"), c.get("lam"), c.get("candidate_k"),
                f"{m['p95']:.1f}", f"{m['recall_at_k']:.6f}", f"{m['mrr']:.6f}", f"{m['ndcg']:.6f}", f"{m['dup_rate']:.6f}",
                f"{m['recall50_raw']:.6f}",
                e.get("RAG_TITLE_CAP"), e.get("RAG_MMR_PRE_K"), e.get("RAG_MMR_K"),
                e.get("RAG_RERANK_IN"), e.get("RAG_FETCH_K"), e.get("RAG_FETCH_K_AUX"),
            ])

    # 롤백 파일 백업
    if best_path.exists():
        last_good.write_text(best_path.read_text("utf-8"), encoding="utf-8")

    # 개선 확인(이전 대비 1%↑ 또는 recall@k +0.01)
    improved = True
    if prev:
        improved = (best_score >= prev_score * 1.01) or (
            best["metrics"]["recall_at_k"] >= prev.get("metrics", {}).get("recall_at_k", 0.0) + 0.01
        )

    best_out = {
        "_score": best_score,
        "cfg": best.get("cfg", {}),
        "env": best.get("env", {}),
        "metrics": best.get("metrics", {}),
        "reranker_mode": args.reranker,
        "N": len(dev_rows),
        "by": args.by,
        "section": args.section,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "trials": total_trials
    }
    best_path.write_text(json.dumps(best_out, ensure_ascii=False, indent=2), encoding="utf-8")

    if not improved and last_good.exists():
        # 롤백
        best_path.write_text(last_good.read_text("utf-8"), encoding="utf-8")

    print(f"[BEST] score={best_score:.6f}")
    print(json.dumps(best_out, ensure_ascii=False, indent=2))
    print(f"\nSaved CSV: {csv_path.resolve()}\nSaved BEST: {best_path.resolve()}")

if __name__ == "__main__":
    main()
