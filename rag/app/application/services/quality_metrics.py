from __future__ import annotations
import math
from typing import Any, Dict, List

# ───────────── helpers ─────────────
def _norm(s: str) -> str:
    import unicodedata, re
    s = unicodedata.normalize("NFKC", s or "").lower()
    return re.sub(r"[\\s\\W_]+", "", s)

def _doc_from_id(raw_id: Any) -> str:
    """
    인덱스 ID가 'doc_id:section:idx:hash8' 형태일 때 앞부분에서 doc_id 복구.
    그 외 형식이면 그대로 반환.
    """
    if not raw_id:
        return ""
    s = str(raw_id)
    return s.split(":", 1)[0] if ":" in s else s

def _safe_meta(d: Any) -> Dict[str, Any]:
    """
    dict/DocumentItem 모두 지원하는 메타 추출기.
    """
    if isinstance(d, dict):
        return d.get("metadata") or {}
    m = getattr(d, "metadata", None)
    return m if isinstance(m, dict) else {}

# ───────────── key extraction ─────────────
def keys_from_docs(docs: List[Any], by: str = "doc") -> List[str]:
    """
    by: 'doc' | 'seed' | 'title'
      - 'doc' : metadata.doc_id 없으면 id에서 복구
      - 'seed': DocumentItem.seed -> metadata.seed_title -> parent -> title
      - 'title': metadata.title (엄격: fallback 금지)
    dict/DocumentItem 모두 안전 처리.
    """
    out: List[str] = []
    for d in docs:
        if isinstance(d, dict):
            meta = d.get("metadata") or {}
            rid = d.get("id")
            did = meta.get("doc_id") or _doc_from_id(rid)
            title = meta.get("title") or (d.get("title") or "")
            seed  = meta.get("seed_title") or meta.get("parent") or (d.get("seed") or "")
        else:
            meta = _safe_meta(d)
            rid = getattr(d, "id", None)
            did = meta.get("doc_id") or _doc_from_id(rid)
            title = getattr(d, "title", None) or meta.get("title") or ""
            seed  = getattr(d, "seed", None) or meta.get("seed_title") or meta.get("parent")

        if by == "doc":
            key = did or ""
        elif by == "seed":
            key = (seed or "").strip()
        else:  # 'title' (엄격 모드: title이 없으면 빈 문자열)
            key = (title or "").strip()

        out.append(key)
    return out

# ───────────── per-query metrics ─────────────
def hit_at_k(retrieved_keys: List[str], gold_keys: List[str], k: int) -> int:
    G = {_norm(t) for t in gold_keys if t}
    for t in retrieved_keys[:k]:
        if _norm(t) in G:
            return 1
    return 0

def recall_at_k(retrieved_keys: List[str], gold_keys: List[str], k: int) -> float:
    """
    진짜 리콜: top-k에서 '서로 다른' GOLD 항목이 몇 개 나왔는지 / |G|
    동일 키가 여러 번 나와도 1회로만 인정한다.
    """
    G = {_norm(t) for t in gold_keys if t}
    if not G:
        return 0.0
    matched = set()
    for t in retrieved_keys[:k]:
        nt = _norm(t)
        if nt in G:
            matched.add(nt)
            if len(matched) == len(G):  # 조기종료
                break
    return float(len(matched)) / float(len(G))

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
    import math as _m
    idx = max(0, min(len(xs) - 1, int(_m.ceil((p/100.0) * len(xs)) - 1)))
    return float(xs[idx])

def average(xs: List[float]) -> float:
    return float(sum(xs) / len(xs)) if xs else 0.0

# ───────────── one-shot evaluator ─────────────
def evaluate_batch(rows: List[Dict], k_recall: int = 5, report_key: str = "B", by: str = "doc") -> Dict:
    """
    rows[i] 예:
      {
        f"keys{report_key}": List[str],  # retrieve된 key들(문서 ID/seed/title)
        "gold": List[str],               # 정답 키 집합
        f"lat{report_key}_ms": float     # 지연(ms)
      }
    """
    recalls: List[float] = []
    r_dups: List[float] = []
    lats:   List[float] = []

    for r in rows:
        keys = r.get(f"keys{report_key}") or []
        gold = r.get("gold") or []
        recalls.append(recall_at_k(keys, gold, k_recall))
        r_dups.append(dup_rate(keys[:k_recall]))
        lat = r.get(f"lat{report_key}_ms")
        if isinstance(lat, (int, float)):
            lats.append(float(lat))

    return {
        f"recall@{k_recall}": average(recalls),
        "dup_rate": average(r_dups),
        "p95_ms": p_percentile(lats, 95.0),
        "count": len(recalls),
        "by": by,
        "report": report_key,
    }
