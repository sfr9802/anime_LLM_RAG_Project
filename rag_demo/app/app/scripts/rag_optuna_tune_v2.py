# -*- coding: utf-8 -*-
from __future__ import annotations
"""
Retrieval tuning runner (v3)
- Optuna-based hyperparameter search for Chroma-based retriever
- Reproducible dev-set caching (save/load)
- Cross-validation over fixed dev rows (optional)
- Consistent CSV schema for downstream analysis

Author: you
"""
import os
import sys
import json
import time
import csv
import math
import random
import contextlib
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional

# ==== .env loader (same behavior) ====
from dotenv import load_dotenv, find_dotenv

ENV_FILE: Optional[str] = None
NO_DOTENV = False
argv = sys.argv[1:]
for i, a in enumerate(argv):
    if a == "--env-file" and i + 1 < len(argv):
        ENV_FILE = argv[i + 1]
    elif a == "--no-dotenv":
        NO_DOTENV = True

if not NO_DOTENV:
    if ENV_FILE and os.path.exists(ENV_FILE):
        load_dotenv(ENV_FILE, override=True)
    else:
        load_dotenv(find_dotenv(filename=".env", usecwd=True), override=True)
        load_dotenv(find_dotenv(filename=".env.local", usecwd=True), override=True)

import optuna

# === project imports ===
from app.app.services.chroma_rag import RagService
from app.app.metrics.quality import (
    keys_from_docs,
    hit_at_k,
    recall_at_k,
    dup_rate,
    p_percentile,
)
from app.app.services.adapters import flatten_chroma_result
from app.app.infra.vector.chroma_store import search as chroma_search

print("CHROMA_DB_DIR =", os.getenv("CHROMA_DB_DIR"))
print("CHROMA_COLLECTION =", os.getenv("CHROMA_COLLECTION"))

# ========== helpers ==========
import unicodedata
import re

def _norm(s: str) -> str:
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
    rels = [1.0 if _norm(t) in G else 0.0 for t in retrieved[:k]]
    dcg = sum(rel / math.log2(i + 1) for i, rel in enumerate(rels, start=1))
    idcg = sum(1.0 / math.log2(i + 1) for i in range(1, min(k, len(G)) + 1))
    return (dcg / idcg) if idcg > 0 else 0.0


def _split_csv(v) -> List[str]:
    if not v:
        return []
    if isinstance(v, list):
        return [str(x).strip() for x in v if str(x).strip()]
    return [s.strip() for s in str(v).split("|") if s.strip()]


def _gold_keys_for_meta(m: Dict, by: str) -> List[str]:
    from app.app.infra.vector.chroma_store import get_collection

    coll = get_collection()
    where: Dict[str, Any] = {}
    if by == "doc":
        if not m.get("doc_id"):
            return []
        where = {"doc_id": m["doc_id"]}
    elif by == "seed":
        seed = m.get("seed_title") or m.get("parent")
        if not seed:
            return []
        where = {"seed_title": seed}
    else:
        t = m.get("title") or m.get("seed_title") or ""
        if not t:
            return []
        where = {"title": t}

    res = coll.get(where=where, include=["metadatas"], limit=10000)
    items = [
        {"metadata": md, "id": _id}
        for md, _id in zip(res.get("metadatas") or [], res.get("ids") or [])
    ]
    keys = keys_from_docs(items, by=by if by in ("title", "seed", "doc") else "title")

    uniq: List[str] = []
    seen: set[str] = set()
    for k in keys:
        if k in seen:
            continue
        seen.add(k)
        uniq.append(k)
    return uniq


def _make_queries_from_meta(m: Dict) -> List[str]:
    title = m.get("seed_title") or m.get("parent") or m.get("title") or ""
    ban = set()
    if title:
        ban.add(_norm(title))

    alias_strs: List[str] = []
    for key in ("aliases", "aliases_norm"):
        v = m.get(key)
        if isinstance(v, list):
            alias_strs.extend([x for x in v if x])
    alias_strs.extend(_split_csv(m.get("aliases_csv")))
    alias_strs.extend(_split_csv(m.get("aliases_norm_csv")))
    for key in ("original_title", "alt_title"):
        v = m.get(key)
        if isinstance(v, str):
            alias_strs.append(v)

    qs: List[str] = []
    if title:
        qs += [f"{title} 요약", f"{title} 줄거리", f"{title} 등장인물"]
    for a in alias_strs[:2]:
        a = (a or "").strip()
        if len(a) >= 2:
            qs += [f"{a} 요약", f"{a} 줄거리"]

    uniq, seen = [], set()
    for q in qs:
        q = q.strip()
        if len(q) < 2:
            continue
        nq = _norm(q)
        if nq in ban:
            continue
        if q in seen:
            continue
        seen.add(q)
        uniq.append(q)
    return uniq


def _sample_from_chroma(max_docs: int, section_hint: str = "요약") -> List[Dict]:
    from app.app.infra.vector.chroma_store import get_collection

    coll = get_collection()
    metas: List[Dict] = []
    ids: List[str] = []
    offset, batch = 0, 500
    try:
        while len(metas) < max_docs:
            res = coll.get(
                where={"section": section_hint} if section_hint else None,
                include=["metadatas"],
                limit=batch,
                offset=offset,
            )
            got_ids = res.get("ids") or []
            got_meta = res.get("metadatas") or []
            if not got_ids:
                break
            metas.extend(got_meta)
            ids.extend(got_ids)
            offset += len(got_ids)
            if len(metas) >= max_docs:
                break
    except Exception:
        # Fallback: filter by section in python
        metas, ids = [], []
        offset = 0
        while len(metas) < max_docs:
            res = coll.get(include=["metadatas"], limit=batch, offset=offset)
            got_ids = res.get("ids") or []
            got_meta = res.get("metadatas") or []
            if not got_ids:
                break
            for i, m in enumerate(got_meta):
                if section_hint and (m or {}).get("section") != section_hint:
                    continue
                metas.append(m or {})
                ids.append(got_ids[i] if i < len(got_ids) else None)
                if len(metas) >= max_docs:
                    break
            offset += len(got_ids)

    if not metas:
        res = coll.peek(min(max_docs, 1000))
        metas = res.get("metadatas") or []
        ids = res.get("ids") or []

    uniq: List[Dict] = []
    seen: set[str] = set()
    for i, m in enumerate(metas):
        m = m or {}
        doc_id = m.get("doc_id") or ids[i] or f"{m.get('title','')}|{m.get('section','')}"
        if doc_id in seen:
            continue
        seen.add(doc_id)
        uniq.append(m)
        if len(uniq) >= max_docs:
            break

    random.shuffle(uniq)
    return uniq


def _recall50_raw(q: str, gold: List[str], match_by: str) -> float:
    res = chroma_search(
        query=q,
        n=50,
        where=None,
        include_docs=True,
        include_metas=True,
        include_ids=True,
        include_distances=True,
    )
    items = flatten_chroma_result(res)
    mode = "doc" if match_by == "doc" else ("seed" if match_by == "seed" else "title")
    keys = keys_from_docs(items, by=mode)
    return recall_at_k(keys, gold, 50)


@contextlib.contextmanager
def patched_environ(env_patch: Dict[str, Any]):
    old: Dict[str, Optional[str]] = {}
    try:
        for k, v in env_patch.items():
            old[k] = os.environ.get(k)
            os.environ[k] = str(v)
        yield
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def _distinct_topk(docs: List[Dict], by: str, k: int) -> List[Dict]:
    """Enforce distinctness by 'title'|'seed'|'doc' on the final top-k list."""
    if k <= 0:
        return []
    if by not in ("title", "seed", "doc"):
        by = "title"
    seen: set[str] = set()
    out: List[Dict] = []
    for d in docs:
        md = (d or {}).get("metadata") or {}
        key: Optional[str] = None
        if by == "doc":
            key = md.get("doc_id") or md.get("id")
        elif by == "seed":
            key = md.get("seed_title") or md.get("parent")
        else:
            key = md.get("title") or md.get("seed_title") or md.get("parent")
        if not key:
            key = md.get("id") or str(len(out))
        if key in seen:
            continue
        seen.add(key)
        out.append(d)
        if len(out) >= k:
            break
    return out


def build_dev_rows(N: int, section: str, match_by: str, seed: int) -> List[Tuple[str, List[str]]]:
    random.seed(seed)
    metas = _sample_from_chroma(N, section_hint=section)
    dev_rows: List[Tuple[str, List[str]]] = []
    for m in metas:
        gold = _gold_keys_for_meta(m, match_by)
        if not gold:
            continue
        qs = _make_queries_from_meta(m)
        if not qs:
            continue
        q = random.choice(qs)
        dev_rows.append((q, gold))
    return dev_rows


def evaluate_config(
    dev_rows: List[Tuple[str, List[str]]],
    cfg: Dict[str, Any],
    envp: Dict[str, Any],
    svc: RagService,
    *,
    distinct_by: str,
) -> Dict[str, float]:
    with patched_environ(envp):
        hits: List[float] = []
        recs: List[float] = []
        mrrs: List[float] = []
        ndcgs: List[float] = []
        lats: List[float] = []
        dups: List[float] = []
        rec50_raw_vals: List[float] = []

        for q, gold in dev_rows:
            t0 = time.perf_counter()
            docs = svc.retrieve_docs(
                q,
                k=max(int(cfg["k"]), 1),
                where=None,
                candidate_k=cfg.get("candidate_k"),
                use_mmr=bool(cfg["use_mmr"]),
                lam=float(cfg["lam"]),
                strategy=str(cfg["strategy"]),
            )
            # Enforce distinctness post-retrieval (evaluation-time)
            docs = _distinct_topk(docs, by=distinct_by, k=int(cfg["k"]))
            dt = (time.perf_counter() - t0) * 1000.0

            mode = (
                "doc"
                if cfg["match_by"] == "doc"
                else ("seed" if cfg["match_by"] == "seed" else "title")
            )
            keys = keys_from_docs(docs, by=mode)

            hits.append(hit_at_k(keys, gold, int(cfg["k"])) )
            recs.append(recall_at_k(keys, gold, int(cfg["k"])) )
            mrrs.append(_mrr(keys, gold))
            ndcgs.append(_ndcg(keys, gold, int(cfg["k"])) )
            lats.append(dt)
            dups.append(dup_rate(keys))
            rec50_raw_vals.append(_recall50_raw(q, gold, str(cfg["match_by"])) )

        n = float(len(dev_rows) or 1)
        return dict(
            hit_at_k=sum(hits) / n,
            recall_at_k=sum(recs) / n,
            mrr=sum(mrrs) / n,
            ndcg=sum(ndcgs) / n,
            p95=p_percentile(lats, 95.0),
            dup_rate=sum(dups) / n,
            recall50_raw=sum(rec50_raw_vals) / n,
        )


def _split_folds(rows: List[Tuple[str, List[str]]], folds: int) -> List[List[Tuple[str, List[str]]]]:
    """Deterministic split into folds (contiguous blocks)."""
    n = len(rows)
    if folds <= 1 or n == 0:
        return [rows]
    fold_size = max(1, n // folds)
    out: List[List[Tuple[str, List[str]]]] = []
    for i in range(folds):
        s = i * fold_size
        e = (i + 1) * fold_size if i < folds - 1 else n
        out.append(rows[s:e])
    return out


def crossval_eval(
    svc: RagService,
    base_seed: int,
    folds: int,
    N: int,
    section: str,
    by: str,
    cfg: Dict[str, Any],
    envp: Dict[str, Any],
    distinct_by: str,
    dev_rows_global: Optional[List[Tuple[str, List[str]]]] = None,
) -> Dict[str, float]:
    metrics_list: List[Dict[str, float]] = []

    if dev_rows_global is not None and len(dev_rows_global) > 0:
        # Use fixed dev rows; slice to N then split into folds deterministically
        rows = dev_rows_global[: max(1, min(N, len(dev_rows_global)))]
        folds_rows = _split_folds(rows, max(1, folds))
        for fr in folds_rows:
            if not fr:
                continue
            m = evaluate_config(fr, cfg, envp, svc, distinct_by=distinct_by)
            metrics_list.append(m)
    else:
        # Backward-compatible behavior: build different samples per fold
        seeds = [base_seed + i * 29 for i in range(max(1, folds))]
        for s in seeds:
            rows = build_dev_rows(max(1, N // max(1, folds)), section, by, s)
            if not rows:
                continue
            m = evaluate_config(rows, cfg, envp, svc, distinct_by=distinct_by)
            metrics_list.append(m)

    if not metrics_list:
        raise RuntimeError("Empty dev rows across CV folds")

    out: Dict[str, float] = {}
    for k in metrics_list[0].keys():
        out[k] = sum(m[k] for m in metrics_list) / len(metrics_list)
    return out


def main():
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--N", type=int, default=200)
    ap.add_argument("--section", default="요약")
    ap.add_argument("--by", choices=["title", "seed", "doc"], default="title")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--outdir", default="tune_out_v2")
    ap.add_argument("--trials", type=int, default=120)
    ap.add_argument("--study", default="retrieval_tune_v2")
    ap.add_argument("--reranker", choices=["keep", "on", "off"], default="keep")
    ap.add_argument("--strategies", choices=["both", "baseline", "chroma_only"], default="both")
    ap.add_argument("--distinct-by", choices=["title", "seed", "doc"], default="title", help="Evaluation-time de-dup key")
    ap.add_argument("--xval", type=int, default=3, help="# of CV folds (>=1)")

    # Reproducible dev-set cache
    ap.add_argument("--devcache-save", default="", help="Save sampled dev rows(JSON)")
    ap.add_argument("--devcache-load", default="", help="Load sampled dev rows(JSON)")

    # Weights
    ap.add_argument("--w_recall", type=float, default=0.60)
    ap.add_argument("--w_mrr", type=float, default=0.20)
    ap.add_argument("--w_ndcg", type=float, default=0.20)
    ap.add_argument("--w_dup", type=float, default=0.30, help="Stronger duplicate penalty")
    ap.add_argument("--dup_target", type=float, default=0.15, help="No-penalty band for dup_rate")
    ap.add_argument("--w_lat", type=float, default=0.0)
    ap.add_argument("--lat_target_ms", type=float, default=600.0)

    # Locks / search spaces
    ap.add_argument("--k-choices", type=str, default="")
    ap.add_argument("--lam-choices", type=str, default="")
    ap.add_argument("--pre-k-range", type=str, default="")
    ap.add_argument("--mmr-k-range", type=str, default="")
    ap.add_argument("--rerank-in-range", type=str, default="")
    ap.add_argument("--fetch-k-range", type=str, default="")
    ap.add_argument("--fetch-k-aux-range", type=str, default="")
    ap.add_argument("--title-cap-choices", type=str, default="")
    ap.add_argument("--restrict-sweetspot", action="store_true")
    ap.add_argument("--force-mmr-on", action="store_true")
    ap.add_argument("--env-file", default=ENV_FILE or "")
    ap.add_argument("--no-dotenv", action="store_true", default=NO_DOTENV)

    args = ap.parse_args()

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    if args.reranker == "on":
        os.environ["RAG_USE_RERANK"] = "1"
    elif args.reranker == "off":
        os.environ["RAG_USE_RERANK"] = "0"

    svc = RagService()

    # ----------------- helpers -----------------
    def _parse_choices(s: str, cast):
        if not s:
            return None
        xs = [z.strip() for z in s.split(",") if z.strip()]
        return [cast(x) for x in xs]

    def _parse_range(s: str, cast=int):
        if not s:
            return None
        parts = [p.strip() for p in s.split(":") if p.strip()]
        if len(parts) == 1:
            a = cast(parts[0])
            return [a]
        if len(parts) == 2:
            a, b = cast(parts[0]), cast(parts[1])
            step = 1
        else:
            a, b, step = cast(parts[0]), parts[1], parts[2]
            a, b, step = cast(a), cast(b), cast(step)
        if cast is float:
            vals = []
            x = a
            while x <= b + 1e-12:
                vals.append(float(x))
                x += step
            return vals
        return list(range(a, b + 1, step))

    # ---- dev rows (cacheable) ----
    dev_rows: Optional[List[Tuple[str, List[str]]]] = None
    if args.devcache_load and Path(args.devcache_load).exists():
        data = json.loads(Path(args.devcache_load).read_text(encoding="utf-8"))
        dev_rows = [(d["q"], d["gold"]) for d in data]
        print(f"[devcache] loaded {len(dev_rows)} rows from {args.devcache_load}")
    else:
        dev_rows = build_dev_rows(args.N, args.section, args.by, args.seed)
        if args.devcache_save:
            Path(args.devcache_save).write_text(
                json.dumps([{"q": q, "gold": gold} for q, gold in dev_rows], ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            print(f"[devcache] saved {len(dev_rows)} rows to {args.devcache_save}")

    if not dev_rows:
        raise RuntimeError("dev set empty — check index/section/match_by.")

    # ---- objective ----
    def objective(trial: optuna.Trial) -> float:
        strat_space = (
            ["baseline", "chroma_only"] if args.strategies == "both" else [args.strategies]
        )
        strategy = trial.suggest_categorical("strategy", strat_space)

        k_choices = _parse_choices(args.k_choices, int)
        lam_choices = _parse_choices(args.lam_choices, float)

        k = trial.suggest_categorical("k", k_choices) if k_choices else trial.suggest_int("k", 4, 12)
        use_mmr = True if args.force_mmr_on else trial.suggest_categorical("use_mmr", [True, False])
        lam = (
            trial.suggest_categorical("lam", lam_choices)
            if lam_choices
            else trial.suggest_float("lam", 0.5, 0.9, step=0.05)
        )
        candidate_k = (
            trial.suggest_int("candidate_k", 80, 320, step=20) if strategy == "baseline" else None
        )

        # parse or fallback
        def rng(name: str, default_low: int, default_high: int) -> int:
            return trial.suggest_int(name, default_low, default_high, step=1)

        prek_candidates = _parse_range(args.pre_k_range, int)
        mmrk_candidates = _parse_range(args.mmr_k_range, int)
        fetchk_candidates = _parse_range(args.fetch_k_range, int)
        fetchk_aux_candidates = _parse_range(args.fetch_k_aux_range, int)
        rerank_candidates = _parse_range(args.rerank_in_range, int)
        title_cap_choices = _parse_choices(args.title_cap_choices, int)

        pre_k = (
            trial.suggest_categorical("RAG_MMR_PRE_K", prek_candidates)
            if prek_candidates
            else rng("RAG_MMR_PRE_K", 60, 200)
        )
        mmr_k = (
            trial.suggest_categorical("RAG_MMR_K", mmrk_candidates)
            if mmrk_candidates
            else rng("RAG_MMR_K", 24, 200)
        )
        fetch_k = (
            trial.suggest_categorical("RAG_FETCH_K", fetchk_candidates)
            if fetchk_candidates
            else rng("RAG_FETCH_K", 80, 240)
        )
        fetch_k_aux = (
            trial.suggest_categorical("RAG_FETCH_K_AUX", fetchk_aux_candidates)
            if fetchk_aux_candidates
            else rng("RAG_FETCH_K_AUX", max(int(k) * 4, 40), 180)
        )
        rerank_in = (
            trial.suggest_categorical("RAG_RERANK_IN", rerank_candidates)
            if rerank_candidates
            else rng("RAG_RERANK_IN", 12, 48)
        )
        title_cap = (
            trial.suggest_categorical("RAG_TITLE_CAP", title_cap_choices)
            if title_cap_choices
            else trial.suggest_int("RAG_TITLE_CAP", 1, 2)
        )

        # soft constraints
        if args.restrict_sweetspot:
            if k not in (8, 9):
                raise optuna.TrialPruned()
            if lam < 0.65 or lam > 0.85:
                raise optuna.TrialPruned()
            if pre_k < 80:
                raise optuna.TrialPruned()
            if rerank_in < 20 or rerank_in > 40:
                raise optuna.TrialPruned()
            if fetch_k > 160:
                raise optuna.TrialPruned()

        envp = {
            "RAG_TITLE_CAP": title_cap,
            "RAG_MMR_PRE_K": pre_k,
            "RAG_MMR_K": mmr_k,
            "RAG_RERANK_IN": rerank_in,
            "RAG_FETCH_K": fetch_k,
            "RAG_FETCH_K_AUX": fetch_k_aux,
        }
        cfg = dict(
            strategy=strategy,
            k=int(k),
            use_mmr=bool(use_mmr),
            lam=float(lam),
            candidate_k=int(candidate_k) if candidate_k is not None else None,
            match_by=str(args.by),
        )

        # CV evaluation (use fixed dev rows if provided)
        metrics = crossval_eval(
            svc,
            args.seed,
            max(1, args.xval),
            args.N,
            args.section,
            args.by,
            cfg,
            envp,
            args.distinct_by,
            dev_rows_global=dev_rows,
        )

        # scoring with stronger dup penalty
        lat_pen = max(0.0, (metrics["p95"] - args.lat_target_ms) / args.lat_target_ms)
        dup_over = max(0.0, metrics["dup_rate"] - args.dup_target)

        score = (
            args.w_recall * metrics["recall_at_k"]
            + args.w_mrr * metrics["mrr"]
            + args.w_ndcg * metrics["ndcg"]
            - args.w_dup * dup_over
            - args.w_lat * lat_pen
        )

        trial.set_user_attr("metrics", metrics)
        trial.set_user_attr("cfg", cfg)
        trial.set_user_attr("env", envp)
        return float(score)

    study = optuna.create_study(
        direction="maximize",
        study_name=args.study,
        pruner=optuna.pruners.MedianPruner(n_startup_trials=10),
    )
    study.optimize(objective, n_trials=args.trials)

    best = study.best_trial
    best_cfg = best.user_attrs["cfg"]
    best_env = best.user_attrs["env"]
    best_metrics = best.user_attrs["metrics"]
    best_score = float(best.value)

    best_path = Path(args.outdir) / "retrieval.best.v2.json"
    csv_path = Path(args.outdir) / "results.v2.csv"

    out = {
        "_score": best_score,
        "metrics": best_metrics,
        "cfg": best_cfg,
        "env": best_env,
        "reranker_mode": args.reranker,
        "N": args.N,
        "xval": args.xval,
        "by": args.by,
        "section": args.section,
        "distinct_by": args.distinct_by,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "trials": len(study.trials),
    }
    best_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    # CSV dump (standardized column names)
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "trial",
                "score",
                "strategy",
                "k",
                "use_mmr",
                "lam",
                "candidate_k",
                "p95",
                "recall_at_k",
                "mrr",
                "ndcg",
                "dup_rate",
                "recall50_raw",
                "RAG_TITLE_CAP",
                "RAG_MMR_PRE_K",
                "RAG_MMR_K",
                "RAG_RERANK_IN",
                "RAG_FETCH_K",
                "RAG_FETCH_K_AUX",
            ]
        )
        for t in study.trials:
            m = t.user_attrs.get("metrics", {}) or {}
            cfg = t.user_attrs.get("cfg", {}) or {}
            envp = t.user_attrs.get("env", {}) or {}
            w.writerow(
                [
                    t.number,
                    f"{t.value:.6f}" if t.value is not None else "",
                    cfg.get("strategy"),
                    cfg.get("k"),
                    cfg.get("use_mmr"),
                    cfg.get("lam"),
                    cfg.get("candidate_k"),
                    m.get("p95"),
                    m.get("recall_at_k"),
                    m.get("mrr"),
                    m.get("ndcg"),
                    m.get("dup_rate"),
                    m.get("recall50_raw"),
                    envp.get("RAG_TITLE_CAP"),
                    envp.get("RAG_MMR_PRE_K"),
                    envp.get("RAG_MMR_K"),
                    envp.get("RAG_RERANK_IN"),
                    envp.get("RAG_FETCH_K"),
                    envp.get("RAG_FETCH_K_AUX"),
                ]
            )

    print("[BEST.v2]")
    print(json.dumps(out, ensure_ascii=False, indent=2))
    print(f"\nSaved CSV: {csv_path.resolve()}\nSaved BEST: {best_path.resolve()}")


if __name__ == "__main__":
    main()
