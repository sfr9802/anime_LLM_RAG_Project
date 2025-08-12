# app/vector_store/metrics.py
from __future__ import annotations
import math
from typing import Optional

def to_similarity(distance: Optional[float], space: str = "cosine") -> Optional[float]:
    if distance is None:
        return None
    d = float(distance)
    s = space.lower()
    if s == "cosine":
        sim = 1.0 - d
    elif s == "l2":
        sim = 1.0 / (1.0 + d)          # 단조 변환
    elif s == "ip":
        sim = 1.0 / (1.0 + math.exp(-d))  # 0~1로 눌러 표시용
    else:
        sim = 1.0 - d                   # 안전 디폴트
    # 보기용 클리핑
    if sim < 0.0: sim = 0.0
    if sim > 1.0: sim = 1.0
    return sim
