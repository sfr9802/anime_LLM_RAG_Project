# app/app/metrics/quality.py
from __future__ import annotations
import math
from typing import Dict, List, Tuple

# ───────────── helpers ─────────────
def _norm(s: str) -> str:
    import unicodedata, re
    s = unicodedata.normalize("NFKC", s or "").lower()
    return re.sub(r"[\s\W_]+", "", s)

def keys_from_docs(docs: List[Dict], by: str = "doc") -> List[str]:
    out: List[str] = []
    for d in docs:
        m = (d.get("metadata") or {})
        if by == "doc":
            out.append(m.get("doc_id") or "")
        else:
            out.append(m.get("seed_title") or m.get("parent") or m.get("title") or "")
    return out

# ───────────── per-query metrics ─────────────
def hit_at_k(retrieved_keys: List[str], gold_keys: List[str], k: int) -> int:
    G = { _norm(t) for t in gold_keys if t }
    for t in retrieved_keys[:k]:
        if _norm(t) in G:
            return 1
    return 0

def recall_at_k(retrieved_keys: List[str], gold_keys: List[str], k: int) -> float:
    # 단일 답(1개 gold) 기준에선 hit@k와 동일. 멀티 골드일 때는 비율로 확장 가능.
    return float(hit_at_k(retrieved_keys, gold_keys, k))

def dup_rate(keys_topk: List[str]) -> float:
    """top-k 내 중복률 = 1 - (#unique / k). by='doc' 키를 넣는 걸 권장."""
    k = len(keys_topk)
    if k <= 1:
        return 0.0
    return 1.0 - (len(set(keys_topk)) / float(k))

# ───────────── aggregation ─────────────
def p_percentile(values_ms: List[float], p: float = 95.0) -> float:
    if not values_ms:
        return 0.0
    xs = sorted(values_ms)
    # 최근린 방식: ceil(p/100 * n) - 1
    idx = max(0, min(len(xs) - 1, int(math.ceil((p/100.0) * len(xs)) - 1)))
    return float(xs[idx])

def average(xs: List[float]) -> float:
    return float(sum(xs) / len(xs)) if xs else 0.0

# ───────────── one-shot evaluator (원하면 바로 씀) ─────────────
def evaluate_batch(rows: List[Dict], k_recall: int = 5, report_key: str = "B", by: str = "doc") -> Dict:
    """
    rows[i]는 다음 키를 가진 dict여야 함:
      - f"keys{report_key}": List[str]  # retrieve된 key들(문서 ID나 타이틀)
      - "gold": List[str]               # 정답 키
      - f"lat{report_key}_ms": float    # ms 단위 지연
    """
    r_hits: List[float] = []
    r_dups: List[float] = []
    lats:   List[float] = []

    for r in rows:
        keys = r.get(f"keys{report_key}") or []
        gold = r.get("gold") or []
        r_hits.append(recall_at_k(keys, gold, k_recall))
        r_dups.append(dup_rate(keys[:max(1, len(keys))]))
        lat = r.get(f"lat{report_key}_ms")
        if isinstance(lat, (int, float)):
            lats.append(float(lat))

    return {
        f"recall@{k_recall}": average(r_hits),
        "dup_rate": average(r_dups),
        "p95_ms": p_percentile(lats, 95.0),
        "count": len(r_hits),
        "by": by,
        "report": report_key,
    }
