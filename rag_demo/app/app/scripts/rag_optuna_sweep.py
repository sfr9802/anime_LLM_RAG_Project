# app/app/scripts/rag_optuna_sweep.py
# -*- coding: utf-8 -*-
from __future__ import annotations
import argparse, itertools, subprocess, sys, json, time
from pathlib import Path
from typing import List, Dict, Any

def _parse_csv(s: str) -> List[str]:
    if not s:
        return []
    parts = [p.strip() for p in s.split(",")]
    # "all", "*", "" → 전체 섹션 의미로 빈 문자열로 치환
    out = []
    for p in parts:
        if p.lower() in {"all", "*"}:
            out.append("")
        else:
            out.append(p)
    return out

def _sec_label(sec: str) -> str:
    return "all" if sec == "" else sec

def _mk_outdir(base: Path, by: str, sec: str, reranker: str, seed: int) -> Path:
    return base / f"by={by}" / f"sec={_sec_label(sec)}" / f"rerank={reranker}" / f"seed={seed}"

def _run_once(
    pyexe: str,
    module: str,
    base_args: Dict[str, Any],
    section: str,
    by: str,
    reranker: str,
    seed: int,
    strategies: str,
    outdir: Path,
    study_prefix: str,
) -> Dict[str, Any]:
    outdir.mkdir(parents=True, exist_ok=True)
    study = f"{study_prefix}_{by}_{_sec_label(section)}_{reranker}_s{seed}"
    # argv 리스트로 안전 전달(빈 섹션은 --section= 형태로)
    cmd = [
        pyexe, "-m", module,
        "--N", str(base_args["N"]),
        f"--section={section}",
        "--by", by,
        "--trials", str(base_args["trials"]),
        "--study", study,
        "--outdir", str(outdir),
        "--reranker", reranker,
        "--strategies", strategies,
        "--w_recall", str(base_args["w_recall"]),
        "--w_mrr", str(base_args["w_mrr"]),
        "--w_ndcg", str(base_args["w_ndcg"]),
        "--w_dup", str(base_args["w_dup"]),
        "--w_lat", str(base_args["w_lat"]),
        "--lat_target_ms", str(base_args["lat_target_ms"]),
        "--improve-pct", str(base_args["improve_pct"]),
        "--improve-recall", str(base_args["improve_recall"]),
    ]
    t0 = time.perf_counter()
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    dt = round((time.perf_counter() - t0), 2)
    ok = (proc.returncode == 0)
    result = {
        "ok": ok,
        "returncode": proc.returncode,
        "secs": dt,
        "cmd": cmd,
        "stdout": proc.stdout[-2000:],  # 꼬리만 저장
        "stderr": proc.stderr[-2000:],
        "study": study,
        "outdir": str(outdir),
        "by": by, "section": section, "reranker": reranker, "seed": seed,
    }
    # 각 조합 결과 요약 파일로 남김
    (outdir / "_sweep_run.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sections", default="all", help="예: '요약,본문,all' (all=* 또는 빈 섹션 의미)")
    ap.add_argument("--bys", default="doc", help="예: 'doc,seed,title'")
    ap.add_argument("--rerankers", default="off,on", help="실행 모드: 'off,on,keep' 중 선택 콤마")
    ap.add_argument("--seeds", default="42", help="예: '42,123,777'")
    ap.add_argument("--strategies", choices=["both","baseline","chroma_only"], default="both")
    ap.add_argument("--N", type=int, default=200)
    ap.add_argument("--trials", type=int, default=120)
    ap.add_argument("--study-prefix", default="sweep")
    ap.add_argument("--outbase", default="tune_sweep")
    # 가중치/지연 패널티/개선조건(기존 tune.py 인자 그대로 연결)
    ap.add_argument("--w_recall", type=float, default=1.0)
    ap.add_argument("--w_mrr", type=float, default=0.0)
    ap.add_argument("--w_ndcg", type=float, default=0.0)
    ap.add_argument("--w_dup", type=float, default=0.0)
    ap.add_argument("--w_lat", type=float, default=0.0)
    ap.add_argument("--lat_target_ms", type=float, default=600.0)
    ap.add_argument("--improve_pct", type=float, default=0.01)
    ap.add_argument("--improve_recall", type=float, default=0.01)
    args = ap.parse_args()

    sections = _parse_csv(args.sections)
    bys = [b.strip() for b in args.bys.split(",") if b.strip()]
    rerankers = [r.strip() for r in args.rerankers.split(",") if r.strip()]
    seeds = [int(s.strip()) for s in args.seeds.split(",") if s.strip()]

    base = Path(args.outbase)
    base.mkdir(parents=True, exist_ok=True)

    base_args = dict(
        N=args.N, trials=args.trials,
        w_recall=args.w_recall, w_mrr=args.w_mrr, w_ndcg=args.w_ndcg,
        w_dup=args.w_dup, w_lat=args.w_lat,
        lat_target_ms=args.lat_target_ms,
        improve_pct=args.improve_pct, improve_recall=args.improve_recall,
    )

    pyexe = sys.executable
    module = "app.app.scripts.rag_optuna_tune"

    manifest: List[Dict[str, Any]] = []
    for (sec, by, rer, seed) in itertools.product(sections, bys, rerankers, seeds):
        outdir = _mk_outdir(base, by, sec, rer, seed)
        res = _run_once(
            pyexe, module, base_args,
            section=sec, by=by, reranker=rer, seed=seed,
            strategies=args.strategies,
            outdir=outdir, study_prefix=args.study_prefix,
        )
        manifest.append(res)

    (base / "_SWEEP_MANIFEST.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[SWEEP DONE] {len(manifest)} runs → {base.resolve()}")

if __name__ == "__main__":
    main()
