from __future__ import annotations
"""BM25 sparse 검색 어댑터 (선택). 없으면 하이브리드는 비활성.

요구사항:
- 반환 형식은 flatten_chroma_result 와 가능한 유사하게 맞추라.
  최소 필드: id, title, section, metadata(dict), (선택)distance/score
- 인덱스 구축/로드는 프로젝트 사정에 맞게 구현.

빠른 시작(로컬):
- pip install rank-bm25
- 아래 임시 인메모리 구현을 실제 인덱스 로더로 교체.
"""
from typing import Any, Dict, List, Optional

try:
    from rank_bm25 import BM25Okapi
except Exception as e:
    BM25Okapi = None

_TOKENIZED_CORPUS: List[List[str]] = []
_META: List[Dict[str, Any]] = []
_ID: List[str] = []


def _simple_tokenize(text: str) -> List[str]:
    import re
    return [t for t in re.split(r"\W+", (text or "").lower()) if t]


def load_dummy_index(docs: List[Dict[str, Any]]) -> None:
    """예시용 인메모리 인덱스. 실서비스에선 교체하라."""
    global _TOKENIZED_CORPUS, _META, _ID
    _TOKENIZED_CORPUS = [_simple_tokenize(d.get("doc", "")) for d in docs]
    _META = [d.get("metadata", {}) for d in docs]
    _ID = [d.get("id") or str(i) for i, d in enumerate(docs)]


def bm25_search(query: str, n: int = 120, where: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    if BM25Okapi is None or not _TOKENIZED_CORPUS:
        raise RuntimeError("BM25 index is not ready. Install rank-bm25 and load index.")
    bm25 = BM25Okapi(_TOKENIZED_CORPUS)
    scores = bm25.get_scores(_simple_tokenize(query))
    ranked = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:n]
    out: List[Dict[str, Any]] = []
    for i in ranked:
        meta = dict(_META[i])
        out.append({
            "id": _ID[i],
            "title": meta.get("title", ""),
            "section": meta.get("section", ""),
            "metadata": meta,
            # distance는 없으므로 생략; RRF는 rank 기반이라 문제 없음
        })
    return out

