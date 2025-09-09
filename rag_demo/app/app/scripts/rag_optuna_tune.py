# -*- coding: utf-8 -*-
from __future__ import annotations
import os, json, time, argparse, csv, random, math, contextlib
from pathlib import Path
from typing import Dict, Any, List, Tuple

import optuna  # pip install optuna

from app.app.services.rag import RagService
from app.app.metrics.quality import (
    keys_from_docs, hit_at_k, recall_at_k, dup_rate, p_percentile
)
from app.app.services.adapters import flatten_chroma_result
from app.app.infra.vector.chroma_store import search as chroma_search

# ========== util ==========
def _norm(s: str) -> str:
    import unicodedata, re
    s = unicodedata.normalize("NFKC", s or "").lower()
    return re.sub(r"[\\s\\W_]+", "", s)

def _mrr(retrieved: List[str], gold: List[str]) -> float:
    G = {_norm(t) for t in gold if t}
    for i, t in enumerate(retrieved, 1):
        if _norm(t) in G:
            return 1.0 / i
    return 0.0

def _ndcg(retrieved: List[str], gold: List[str], k: int) -> float:
    G = {_norm(t) for t in gold if t}
    rels = [1.0 if _norm(t) in G else 0.0 for t in retrieved[:k]]
    dcg = sum(rel / math.log2(i+1) for i, rel in enumerate(rels, start=1))
    idcg = sum(1.0 / math.log2(i+1) for i in range(1, min(k, len(G)) + 1))
    return (dcg / idcg) if idcg > 0 else 0.0

def _split_csv(v) -> List[str]:
    if not v: return []
    if isinstance(v, list):
        return [str(x).strip() for x in v if str(x).strip()]
    return [s.strip() for s in str(v).split("|") if s.strip()]

def _gold_keys_for_meta(m: Dict, by: str) -> List[str]:
    """
    B. GOLD 집합 확장: 해당 메타에 매칭되는 모든 청크 키를 수집한다.
    by ∈ {'title','seed','doc'} 에 따라 keys_from_docs의 기준을 맞춘다.
    """
    from app.app.infra.vector.chroma_store import get_collection
    coll = get_collection()
    where = {}
    if by == "doc":
        if not m.get("doc_id"): return []
        where = {"doc_id": m["doc_id"]}
    elif by == "seed":
        seed = m.get("seed_title") or m.get("parent")
        if not seed: return []
        where = {"seed_title": seed}
    else:  # 'title'
        t = m.get("title") or m.get("seed_title") or ""
        if not t: return []
        where = {"title": t}

    res = coll.get(where=where, include=["metadatas"], limit=6666)
    items = [{"metadata": md, "id": _id} for md, _id in zip(res.get("metadatas") or [], res.get("ids") or [])]
    # 기준(by)에 맞춘 key 집합 생성
    keys = keys_from_docs(items, by=by if by in ("title","seed","doc") else "title")
    # 중복 제거
    uniq, seen = [], set()
    for k in keys:
        if k in seen: continue
        seen.add(k); uniq.append(k)
    return uniq

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
    mode = "doc" if match_by=="doc" else ("seed" if match_by=="seed" else "title")
    keys = keys_from_docs(items, by=mode)
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

# ========== evaluation ==========
def build_dev_rows(N: int, section: str, match_by: str, seed: int) -> List[Tuple[str, List[str]]]:
    """
    B. GOLD 집합 확장 적용:
    - 이전: gold = [단일 키]
    - 변경: 해당 메타에 매칭되는 모든 청크를 조회하여 GOLD 집합 생성
    """
    random.seed(seed)
    metas = _sample_from_chroma(N, section_hint=section)
    dev_rows: List[Tuple[str, List[str]]] = []
    for m in metas:
        # GOLD 키를 match_by 기준으로 확장해 수집
        gold = _gold_keys_for_meta(m, match_by)
        if not gold:
            continue
        # 쿼리 후보 생성 & 샘플
        qs = _make_queries_from_meta(m)
        if not qs:
            continue
        q = random.choice(qs)
        dev_rows.append((q, gold))
    return dev_rows

def evaluate_config(dev_rows, cfg: Dict[str, Any], envp: Dict[str, Any], svc: RagService) -> Dict[str, float]:
    # svc는 프로세스당 1회 생성해 재사용(리랭커/임베더 재로딩 방지)
    with patched_environ(envp):
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
            mode = "doc" if cfg["match_by"]=="doc" else ("seed" if cfg["match_by"]=="seed" else "title")
            keys = keys_from_docs(docs, by=mode)

            hits.append(hit_at_k(keys, gold, cfg["k"]))
            recs.append(recall_at_k(keys, gold, cfg["k"]))
            mrrs.append(_mrr(keys, gold))
            ndcgs.append(_ndcg(keys, gold, cfg["k"]))
            lats.append(dt)
            dups.append(dup_rate(keys))
            rec50_raw_vals.append(_recall50_raw(q, gold, cfg["match_by"]))

        n = len(dev_rows) or 1
        return dict(
            hit_at_k=sum(hits)/n,
            recall_at_k=sum(recs)/n,
            mrr=sum(mrrs)/n,
            ndcg=sum(ndcgs)/n,
            p95=p_percentile(lats, 95.0),
            dup_rate=sum(dups)/n,
            recall50_raw=sum(rec50_raw_vals)/n
        )

# ========== main ==========
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--N", type=int, default=200, help="샘플링할 문서 수(=쿼리 수)")
    ap.add_argument("--section", default="요약", help="섹션 힌트(''이면 전체)")
    ap.add_argument("--by", choices=["title","seed","doc"], default="title", help="평가 매칭 기준")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--outdir", default="tune_out")
    ap.add_argument("--trials", type=int, default=120)
    ap.add_argument("--study", default="retrieval_tune")
    ap.add_argument("--reranker", choices=["keep","on","off"], default="keep")
    ap.add_argument("--strategies", choices=["both","baseline","chroma_only"],
                default="both", help="전략 공간 제한")
    # 스코어 가중치
    ap.add_argument("--w_recall", type=float, default=0.6)
    ap.add_argument("--w_mrr", type=float, default=0.2)
    ap.add_argument("--w_ndcg", type=float, default=0.2)
    ap.add_argument("--w_dup", type=float, default=0.1)
    ap.add_argument("--w_lat", type=float, default=0.0)
    ap.add_argument("--lat_target_ms", type=float, default=600.0)
    # 롤백 기준
    ap.add_argument("--improve-pct", type=float, default=0.01, help="점수 상대 개선율(예: 0.01=+1%)")
    ap.add_argument("--improve-recall", type=float, default=0.01, help="recall@k 절대 개선치")
    
    args = ap.parse_args()

    outdir = Path(args.outdir); outdir.mkdir(parents=True, exist_ok=True)

    # 리랭커 모드 고정(인스턴스 생성 전)
    if args.reranker == "on":
        os.environ["RAG_USE_RERANK"] = "1"
    elif args.reranker == "off":
        os.environ["RAG_USE_RERANK"] = "0"
    # keep이면 그대로 둔다

    # RagService 1회 생성(전 트라이얼 공유)
    svc = RagService()

    dev_rows = build_dev_rows(args.N, args.section, args.by, args.seed)
    if not dev_rows:
        raise RuntimeError("dev set이 비었습니다. 인덱스/섹션/매칭 기준을 확인하세요.")

    # ---- Optuna Objective ----
    def objective(trial: optuna.Trial) -> float:
        strat_space = ["baseline", "chroma_only"] if args.strategies == "both" else [args.strategies]
        strategy = trial.suggest_categorical("strategy", strat_space)
        k = trial.suggest_int("k", 4, 12)
        use_mmr = trial.suggest_categorical("use_mmr", [True, False])
        lam = trial.suggest_float("lam", 0.0, 0.8, step=0.1)
        candidate_k = trial.suggest_int("candidate_k", 80, 320, step=20) if strategy == "baseline" else None

        # C. 파라미터 관계 제약: MMR_K ≤ PRE_K ≤ FETCH_K
        pre_k = trial.suggest_int("RAG_MMR_PRE_K", 60, 200, step=20)
        mmr_k = trial.suggest_int("RAG_MMR_K", max(k*3, 24), pre_k, step=10)  # 상한=pre_k
        fetch_k = trial.suggest_int("RAG_FETCH_K", max(pre_k, 80), 240, step=20)  # 하한=pre_k
        # 보조 fetch는 기존 범위 유지(필요시 fetch_k로 상한 조정 가능)
        fetch_k_aux = trial.suggest_int("RAG_FETCH_K_AUX", max(k*4, 40), 160, step=20)
        rerank_in = trial.suggest_int("RAG_RERANK_IN", 12, 48, step=4)

        # 방어적 assert (Optuna가 범위로 보장하지만, 런타임 보호)
        assert mmr_k <= pre_k <= fetch_k, f"Invalid chain: MMR_K({mmr_k}) ≤ PRE_K({pre_k}) ≤ FETCH_K({fetch_k}) violated"

        # env 파라미터(네 서비스가 env 기반으로 읽음)
        envp = {
            "RAG_TITLE_CAP": trial.suggest_int("RAG_TITLE_CAP", 1, 3),
            "RAG_MMR_PRE_K": pre_k,
            "RAG_MMR_K":     mmr_k,
            "RAG_RERANK_IN": rerank_in,
            "RAG_FETCH_K":   fetch_k,
            "RAG_FETCH_K_AUX": fetch_k_aux,
        }

        cfg = dict(strategy=strategy, k=k, use_mmr=use_mmr, lam=lam,
                   candidate_k=candidate_k, match_by=args.by)

        metrics = evaluate_config(dev_rows, cfg, envp, svc)

        lat_pen = max(0.0, (metrics["p95"] - args.lat_target_ms) / args.lat_target_ms)
        score = (
            args.w_recall * metrics["recall_at_k"] +
            args.w_mrr    * metrics["mrr"] +
            args.w_ndcg   * metrics["ndcg"] -
            args.w_dup    * metrics["dup_rate"] -
            args.w_lat    * lat_pen
        )

        trial.set_user_attr("metrics", metrics)
        trial.set_user_attr("cfg", cfg)
        trial.set_user_attr("env", envp)
        return score

    study = optuna.create_study(direction="maximize", study_name=args.study,
                                pruner=optuna.pruners.MedianPruner(n_startup_trials=10))
    study.optimize(objective, n_trials=args.trials)

    best = study.best_trial
    best_cfg = best.user_attrs["cfg"]
    best_env = best.user_attrs["env"]
    best_metrics = best.user_attrs["metrics"]
    best_score = float(best.value)

    # ---- 저장 & 롤백 ----
    best_path = outdir / "retrieval.best.json"
    last_good = outdir / "retrieval.last_good.json"
    csv_path  = outdir / "results.csv"

    prev = json.loads(best_path.read_text("utf-8")) if best_path.exists() else None
    prev_score = prev.get("_score", -1e9) if prev else -1e9
    prev_recall = prev.get("metrics", {}).get("recall_at_k", 0.0) if prev else 0.0

    if best_path.exists():
        last_good.write_text(best_path.read_text("utf-8"), encoding="utf-8")

    improved = (best_score >= prev_score * (1.0 + args.improve_pct)) or \
               (best_metrics["recall_at_k"] >= prev_recall + args.improve_recall) or \
               (prev_score < -1e8)  # 최초 저장

    out = {
        "_score": best_score,
        "metrics": best_metrics,
        "cfg": best_cfg,
        "env": best_env,
        "reranker_mode": args.reranker,
        "N": len(dev_rows),
        "by": args.by,
        "section": args.section,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "trials": len(study.trials)
    }
    best_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    if not improved and last_good.exists():
        best_path.write_text(last_good.read_text("utf-8"), encoding="utf-8")

    # ---- 전체 결과 CSV 덤프 ----
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["trial","score","strategy","k","use_mmr","lam","candidate_k",
                    "p95","recall@k","mrr","ndcg","dup","recall50_raw",
                    "RAG_TITLE_CAP","RAG_MMR_PRE_K","RAG_MMR_K","RAG_RERANK_IN","RAG_FETCH_K","RAG_FETCH_K_AUX"])
        for t in study.trials:
            m = t.user_attrs.get("metrics", {})
            cfg = t.user_attrs.get("cfg", {})
            envp = t.user_attrs.get("env", {})
            w.writerow([
                t.number, f"{t.value:.6f}" if t.value is not None else "",
                cfg.get("strategy"), cfg.get("k"), cfg.get("use_mmr"), cfg.get("lam"), cfg.get("candidate_k"),
                m.get("p95"), m.get("recall_at_k"), m.get("mrr"), m.get("ndcg"), m.get("dup_rate"), m.get("recall50_raw"),
                envp.get("RAG_TITLE_CAP"), envp.get("RAG_MMR_PRE_K"), envp.get("RAG_MMR_K"),
                envp.get("RAG_RERANK_IN"), envp.get("RAG_FETCH_K"), envp.get("RAG_FETCH_K_AUX"),
            ])

    print("[BEST]")
    print(json.dumps(out, ensure_ascii=False, indent=2))
    print(f"\\nSaved CSV: {csv_path.resolve()}\\nSaved BEST: {best_path.resolve()}")

if __name__ == "__main__":
    main()
